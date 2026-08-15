from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from agentmesh.acquisition import AcquisitionAgent, AcquisitionRequest, AcquisitionResult, MockAcquisitionAgent
from agentmesh.datasources import DataSourceConnector, DataSourceQuery, DataSourceResult, is_read_only_data_operation
from agentmesh.models import Source, ToolDefinition, now_utc
from agentmesh.provider_status import (
    ProviderStatus,
    ProviderTelemetry,
    build_provider_status,
    provider_error_code,
    provider_metadata,
)
from agentmesh.store import SQLiteStore
from agentmesh.web_research import WebSearchProvider, WebSearchResult

READ_ONLY_O2_OPERATIONS = {"search", "query", "list", "find-tables", "schema", "describe"}
_o2_research_telemetry = ProviderTelemetry()

# Verified against the working DesignOS Oxygen connector
# (designOS/backend/src/services/oxygenConnector.ts). The metasearch sub-CLI
# requires an explicit gateway endpoint and authenticates through the locally
# installed CLI's own login state, not a token environment variable.
DEFAULT_METASEARCH_ENDPOINT = "https://agentkits-a2a-gateway.jd.com/agents/sku-search"

# Maps the logical capability name to the standalone sub-CLI binary that
# DesignOS verified on a real machine. When the standalone binary is present we
# call it directly; otherwise we fall back to the `o2 launch <cli>` main entry.
STANDALONE_O2_BINARIES = {
    "metasearch": "oxygen-metasearch",
    "oxygen-metasearch": "oxygen-metasearch",
    "o2-kb": "o2-kb",
    "oxygen-comment": "oxygen-comment",
    "bdp-copilot": "bdp-copilot",
}


def env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def metasearch_endpoint() -> str:
    return os.getenv("AGENTMESH_O2_METASEARCH_ENDPOINT", "").strip() or DEFAULT_METASEARCH_ENDPOINT


def _standalone_binary_for(cli_name: str) -> str | None:
    binary = STANDALONE_O2_BINARIES.get(cli_name)
    if binary and shutil.which(binary):
        return binary
    return None


def _runner_for_cli(cli_name: str, fallback: O2CommandRunner | None = None) -> O2CommandRunner:
    """Prefer the verified standalone sub-CLI binary; fall back to the o2 main entry."""
    standalone = _standalone_binary_for(cli_name)
    if standalone is not None:
        return O2CommandRunner(binary=standalone)
    return fallback or O2CommandRunner()


def normalize_tool_id(value: str) -> str:
    return "o2_" + "".join(char if char.isalnum() else "_" for char in value.strip().lower()).strip("_")


class O2CommandError(RuntimeError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(slots=True)
class O2CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    def json(self) -> Any:
        payload = self.stdout.strip() or "null"
        return json.loads(payload)


class O2CommandRunner:
    def __init__(self, binary: str | None = None, timeout_seconds: int = 45):
        self.binary = binary or os.getenv("AGENTMESH_O2_COMMAND", "o2")
        self.timeout_seconds = max(1, timeout_seconds)

    def available(self) -> bool:
        return self._executable() is not None

    def run(self, *args: str) -> O2CommandResult:
        executable = self._executable()
        if executable is None:
            raise O2CommandError("unavailable", f"Oxygen-CLI command not found: {self.binary}")
        try:
            completed = subprocess.run(
                [executable, *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise O2CommandError("timeout", "Oxygen-CLI command timed out") from error
        result = O2CommandResult(
            argv=[executable, *args],
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        if result.returncode != 0:
            raise O2CommandError("provider_error", f"Oxygen-CLI command failed with exit code {result.returncode}")
        return result

    def run_json(self, *args: str) -> Any:
        return self.run(*args).json()

    def _executable(self) -> str | None:
        executable = shutil.which(self.binary)
        if executable is not None:
            return executable
        local_executable = Path(sys.executable).with_name(self.binary)
        if local_executable.exists():
            return str(local_executable)
        return None


class O2RegistryAdapter:
    def __init__(self, runner: O2CommandRunner | None = None):
        self.runner = runner or O2CommandRunner()

    def status(self) -> dict[str, Any]:
        installed = self.runner.available()
        version = None
        login_status: dict[str, Any] = {"available": False, "logged_in": False}
        if installed:
            try:
                version = self.runner.run("--version").stdout.strip()
            except O2CommandError:
                version = None
            try:
                payload = self.runner.run_json("login", "--status", "--json")
                login_status = {
                    "available": True,
                    "logged_in": bool(
                        _extract_first(payload, ("logged_in", "loggedIn", "is_logged_in", "status"))
                        in {"logged_in", "logged-in", "ok", True}
                    ),
                    "raw": _redact_sensitive_payload(payload),
                }
            except Exception as error:  # pragma: no cover - defensive integration boundary
                login_status = {"available": True, "logged_in": False, "error": str(error)}
        return {
            "installed": installed,
            "binary": self.runner.binary,
            "version": version,
            "login": login_status,
            "setup_checks": o2_setup_checks(self.runner) if installed else [],
        }

    def discover_tools(self, limit: int = 50) -> list[ToolDefinition]:
        payload: Any | None = None
        for command in (
            ("list", "--agent-json", "--limit", str(limit)),
            ("discover", "--local", "--limit", str(limit)),
        ):
            try:
                payload = self.runner.run_json(*command)
                break
            except Exception:
                continue
        if payload is None:
            return []
        items = _extract_items(payload)
        return [_tool_definition_from_item(item) for item in items[:limit]]

    def sync_tools(self, repository: SQLiteStore, granted_by: str = "system", limit: int = 50) -> list[ToolDefinition]:
        tools = self.discover_tools(limit=limit)
        for tool in tools:
            existing = repository.get_tool_definition(tool.id)
            if existing is None:
                repository.save_tool_definition(tool)
                continue
            merged = existing.model_copy(deep=True)
            merged.name = tool.name
            merged.description = tool.description
            merged.category = tool.category
            merged.risk_level = tool.risk_level
            merged.enabled = tool.enabled
            merged.provider = tool.provider
            merged.external_name = tool.external_name
            merged.metadata = tool.metadata
            merged.updated_at = now_utc()
            repository.save_tool_definition(merged)
        return tools


class O2ResearchProvider(WebSearchProvider):
    def __init__(
        self,
        runner: O2CommandRunner | None = None,
        command_template: str | None = None,
        cli_name: str | None = None,
        endpoint: str | None = None,
    ):
        self.command_template = command_template or os.getenv("AGENTMESH_O2_RESEARCH_COMMAND_TEMPLATE")
        self.cli_name = cli_name or os.getenv("AGENTMESH_O2_RESEARCH_CLI", "metasearch")
        self.endpoint = endpoint or metasearch_endpoint()
        # When no runner is injected, prefer the verified standalone sub-CLI binary.
        self.runner = runner or _runner_for_cli(self.cli_name)

    def search(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        started = monotonic()
        try:
            argv = self._argv(query, limit)
            payload = self.runner.run_json(*argv)
            results = [_web_result_from_item(item) for item in _extract_items(payload)[:limit]]
        except Exception as error:
            _o2_research_telemetry.failure(error, (monotonic() - started) * 1000)
            raise
        _o2_research_telemetry.success((monotonic() - started) * 1000)
        return results

    def _argv(self, query: str, limit: int) -> list[str]:
        if self.command_template:
            rendered = self.command_template.format(
                query=shlex.quote(query), limit=str(limit), cli=shlex.quote(self.cli_name)
            )
            return shlex.split(rendered)
        if self.cli_name in {"metasearch", "oxygen-metasearch"}:
            if self.runner.binary == "oxygen-metasearch":
                # Verified DesignOS standalone form.
                return ["--json", "search", "--output", "json", "--endpoint", self.endpoint, query]
            # o2 main-entry fallback (also verified, no token-env required).
            return ["launch", "metasearch", "search", query, "--endpoint", self.endpoint, "--output", "json"]
        if self.cli_name == "o2-kb":
            token = os.getenv("AGENTMESH_O2_KB_RECALL_TOKEN", "")
            app = os.getenv("AGENTMESH_O2_KB_FOLDER_TO_APP", "")
            if self.runner.binary == "o2-kb":
                # Verified DesignOS standalone form: `o2-kb recall list --json <query>`.
                argv = ["recall", "list", "--json", query]
            else:
                argv = ["launch", "o2-kb", "recall", "list", query, "--json"]
            if token:
                argv.extend(["--token", token])
            if app:
                argv.extend(["--folder-to-app", app])
            return argv
        return ["launch", self.cli_name, "search", query, "--limit", str(limit), "--json"]


class O2DataSourceConnector(DataSourceConnector):
    connector_name = "o2_cli"

    def __init__(
        self,
        runner: O2CommandRunner | None = None,
        command_template: str | None = None,
        cli_name: str | None = None,
        endpoint: str | None = None,
    ):
        self.command_template = command_template or os.getenv("AGENTMESH_O2_DATA_COMMAND_TEMPLATE")
        self.cli_name = cli_name or os.getenv("AGENTMESH_O2_DATA_CLI", "metasearch")
        self.endpoint = endpoint or metasearch_endpoint()
        # When no runner is injected, prefer the verified standalone sub-CLI binary.
        self.runner = runner or _runner_for_cli(self.cli_name)

    def query(self, query: DataSourceQuery) -> DataSourceResult:
        if not is_read_only_data_operation(query.operation):
            raise ValueError("Only read-only operations are supported by the Oxygen data connector")
        started = monotonic()
        argv = self._argv(query)
        payload = self.runner.run_json(*argv)
        items = _extract_items(payload)
        records = [_flatten_item(item) for item in items]
        title = str(query.parameters.get("title") or query.parameters.get("keyword") or query.operation)
        source = Source(
            title=f"o2:{self.cli_name}",
            source_type="data_source",
            reference=f"o2://{self.cli_name}/{query.operation}",
        )
        return DataSourceResult(
            connector_name=self.connector_name,
            title=f"{title} 查询结果",
            records=records,
            source=source,
            metadata={
                **provider_metadata(
                    requested_provider=query.connector_name,
                    actual_provider=f"o2:{self.cli_name}",
                    mode="real",
                    latency_ms=(monotonic() - started) * 1000,
                ),
                "cli": self.cli_name,
            },
        )

    def _argv(self, query: DataSourceQuery) -> list[str]:
        keyword = str(query.parameters.get("keyword") or query.parameters.get("query") or query.operation)
        limit = str(int(query.parameters.get("limit") or 10))
        if self.command_template:
            rendered = self.command_template.format(
                query=shlex.quote(keyword),
                limit=limit,
                cli=shlex.quote(self.cli_name),
                operation=shlex.quote(query.operation),
            )
            return shlex.split(rendered)
        if self.cli_name in {"metasearch", "oxygen-metasearch"}:
            if self.runner.binary == "oxygen-metasearch":
                # Verified DesignOS standalone form.
                return ["--json", "search", "--output", "json", "--endpoint", self.endpoint, keyword]
            # o2 main-entry fallback (also verified, no token-env required).
            return ["launch", "metasearch", "search", keyword, "--endpoint", self.endpoint, "--output", "json"]
        if self.cli_name == "oxygen-comment":
            standalone = self.runner.binary == "oxygen-comment"
            argv = [] if standalone else ["launch", "oxygen-comment"]
            argv.append("--json")
            if query.parameters.get("dry_run"):
                argv.append("--dry-run")
            argv.extend(["comment", "list", "--page-size", limit])
            for parameter, flag in (
                ("comment_level", "--comment-level"),
                ("sku_ids", "--sku-ids"),
                ("sku_name", "--sku-name"),
                ("content", "--content"),
                ("begin_time", "--begin-time"),
                ("end_time", "--end-time"),
                ("page", "--page"),
            ):
                value = query.parameters.get(parameter)
                if value is not None and value != "":
                    argv.extend([flag, str(value)])
            # Fall back to an explicit keyword as a SKU name when no SKU filter is given.
            explicit_keyword = query.parameters.get("keyword") or query.parameters.get("query")
            if not query.parameters.get("sku_ids") and not query.parameters.get("sku_name") and explicit_keyword:
                argv.extend(["--sku-name", str(explicit_keyword)])
            return argv
        if self.cli_name == "bdp-copilot":
            return ["launch", "bdp-copilot", "--json-output", "find-tables", keyword]
        return ["launch", self.cli_name, query.operation, keyword, "--limit", limit, "--json"]


class O2AcquisitionAgent(AcquisitionAgent):
    actor = "o2_research_agent"

    def __init__(self, provider: O2ResearchProvider):
        self.provider = provider

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        started = monotonic()
        results = self.provider.search(request.query)
        metadata = provider_metadata(
            requested_provider="o2_research",
            actual_provider="o2_research",
            mode="real",
            latency_ms=(monotonic() - started) * 1000,
        )
        if not results:
            return AcquisitionResult(
                actor=self.actor,
                title="未找到 Oxygen-CLI 资料",
                content="Oxygen-CLI 没有返回可用结果。",
                sources=[],
                metadata=metadata,
            )
        return AcquisitionResult(
            actor=self.actor,
            title="Oxygen-CLI 检索结果",
            content="\n".join(f"{item.title}: {item.snippet}" for item in results),
            sources=[Source(title=item.title, source_type="cli_page", reference=item.url) for item in results],
            metadata=metadata,
        )


class CompositeAcquisitionAgent(AcquisitionAgent):
    def __init__(self, agents: list[AcquisitionAgent]):
        self.agents = agents

    def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        results: list[AcquisitionResult] = []
        diagnostics: list[str] = []
        legacy_diagnostics: list[str] = []
        provider_errors: list[Exception] = []
        requested_provider = _provider_name_for_agent(self.agents[0]) if self.agents else "research"
        for agent in self.agents:
            provider_name = _provider_name_for_agent(agent)
            actor_name = getattr(agent, "actor", provider_name)
            try:
                result = agent.acquire(request)
            except Exception as error:  # pragma: no cover - provider boundary
                error_code = provider_error_code(error)
                diagnostics.append(f"{provider_name}:{error_code}")
                legacy_diagnostics.append(f"{actor_name}:{error_code}")
                provider_errors.append(error)
                continue
            if result.sources:
                results.append(result)
            else:
                diagnostics.append(f"{provider_name}:empty_result")
                legacy_diagnostics.append(f"{actor_name}:empty_result")
        if not results:
            if provider_errors:
                raise provider_errors[-1]
            raise O2CommandError("empty_result", "Configured acquisition providers returned no sources")
        if len(results) == 1:
            result = results[0]
            if diagnostics:
                result.metadata["requested_provider"] = requested_provider
                result.metadata["fallback_reason"] = " | ".join(diagnostics)[:500]
            return result
        actor = "+".join(sorted({item.actor for item in results}))
        title = " / ".join(item.title for item in results[:2])
        content = "\n\n".join(f"[{item.actor}] {item.content}" for item in results if item.content)
        sources: list[Source] = []
        for item in results:
            sources.extend(item.sources)
        actual_provider = ",".join(sorted({item.metadata.get("actual_provider", "unknown") for item in results}))
        latency_ms = sum(float(item.metadata.get("latency_ms", "0")) for item in results)
        metadata = provider_metadata(
            requested_provider=requested_provider,
            actual_provider=actual_provider,
            mode="real",
            latency_ms=latency_ms,
            fallback_reason=" | ".join(diagnostics) or None,
        )
        return AcquisitionResult(actor=actor, title=title, content=content, sources=sources, metadata=metadata)


def _provider_name_for_agent(agent: AcquisitionAgent) -> str:
    actor = getattr(agent, "actor", "research")
    return actor.removesuffix("_agent")


def build_acquisition_agent() -> AcquisitionAgent:
    agents: list[AcquisitionAgent] = []
    if env_flag("AGENTMESH_O2_RESEARCH_ENABLED"):
        agents.append(O2AcquisitionAgent(O2ResearchProvider()))
    from agentmesh.web_research import WebAcquisitionAgent, provider_from_env

    web_provider = provider_from_env()
    if web_provider is not None:
        agents.append(WebAcquisitionAgent(web_provider))
    if not agents:
        return MockAcquisitionAgent()
    if len(agents) == 1:
        return agents[0]
    return CompositeAcquisitionAgent(agents)


def maybe_register_o2_data_connector(registry: object) -> None:
    if not env_flag("AGENTMESH_O2_DATA_ENABLED"):
        return
    if hasattr(registry, "register"):
        registry.register(O2DataSourceConnector.connector_name, O2DataSourceConnector())


def o2_research_provider_status(runner: O2CommandRunner | None = None) -> ProviderStatus:
    configured = env_flag("AGENTMESH_O2_RESEARCH_ENABLED")
    command_runner = runner or O2CommandRunner()
    ready = configured and command_runner.available()
    return build_provider_status(
        name="o2_research",
        configured=configured,
        ready=ready,
        telemetry=_o2_research_telemetry,
        error=None if ready else ("not_configured" if not configured else "unavailable"),
    )


def o2_setup_checks(runner: O2CommandRunner | None = None) -> list[dict[str, Any]]:
    check_runner = runner or O2CommandRunner()
    return [
        _registry_login_check(check_runner),
        _metasearch_token_check(check_runner),
        _o2_kb_init_check(check_runner),
        _oxygen_comment_credentials_check(check_runner),
        _bdp_copilot_runtime_check(check_runner),
        _browser_bridge_check(),
    ]


def _registry_login_check(runner: O2CommandRunner) -> dict[str, Any]:
    try:
        payload = runner.run_json("login", "--status", "--json")
    except Exception as error:
        return _setup_check("o2_registry_login", "O2 registry login", "needs_config", str(error))
    logged_in = bool(
        _extract_first(payload, ("logged_in", "loggedIn", "is_logged_in", "status"))
        in {"logged_in", "logged-in", "ok", True}
    )
    return _setup_check(
        "o2_registry_login",
        "O2 registry login",
        "ready" if logged_in else "needs_config",
        "O2 registry is logged in" if logged_in else "Run `o2 login` first",
    )


def _metasearch_token_check(runner: O2CommandRunner) -> dict[str, Any]:
    try:
        if shutil.which("oxygen-metasearch"):
            payload = O2CommandRunner(binary="oxygen-metasearch").run_json("--json", "doctor")
        else:
            payload = runner.run_json("launch", "metasearch", "--json", "doctor")
    except Exception as error:
        return _setup_check("metasearch_token", "metasearch token", "needs_config", str(error))
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    token_available = bool(data.get("token_available"))
    return _setup_check(
        "metasearch_token",
        "metasearch token",
        "ready" if token_available else "needs_config",
        "metasearch token is available"
        if token_available
        else "Run `oxygen-metasearch login` (or `o2 launch metasearch login`) to authenticate the CLI",
    )


def _o2_kb_init_check(runner: O2CommandRunner) -> dict[str, Any]:
    try:
        runner.run_json("launch", "o2-kb", "config", "list", "--json")
    except Exception as error:
        return _setup_check("o2_kb_init", "o2-kb init", "needs_config", str(error))
    return _setup_check("o2_kb_init", "o2-kb init", "ready", "o2-kb config is initialized")


def _oxygen_comment_credentials_check(runner: O2CommandRunner) -> dict[str, Any]:
    try:
        payload = runner.run_json("launch", "oxygen-comment", "--json", "doctor")
    except Exception as error:
        return _setup_check("oxygen_comment_credentials", "oxygen-comment credentials", "needs_config", str(error))
    result = payload.get("result", {}) if isinstance(payload, dict) else {}
    ready = bool(result.get("ready"))
    return _setup_check(
        "oxygen_comment_credentials",
        "oxygen-comment credentials",
        "ready" if ready else "needs_config",
        str(result.get("reason") or ("oxygen-comment is ready" if ready else "Configure oxygen-comment credentials")),
    )


def _bdp_copilot_runtime_check(runner: O2CommandRunner) -> dict[str, Any]:
    try:
        runner.run("launch", "bdp-copilot", "--help")
    except Exception as error:
        return _setup_check("bdp_copilot_runtime", "bdp-copilot runtime", "needs_config", str(error))
    return _setup_check("bdp_copilot_runtime", "bdp-copilot runtime", "ready", "bdp-copilot runtime is available")


def _browser_bridge_check() -> dict[str, Any]:
    command = os.getenv("AGENTMESH_BROWSER_BRIDGE_COMMAND", "webcli")
    executable = shutil.which(command)
    if executable is None:
        return _setup_check("browser_bridge", "Browser Bridge", "unavailable", f"{command} command not found")
    try:
        completed = subprocess.run(
            [executable, "daemon", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception as error:
        return _setup_check("browser_bridge", "Browser Bridge", "needs_config", str(error))
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    if completed.returncode != 0:
        return _setup_check("browser_bridge", "Browser Bridge", "needs_config", output or "daemon status failed")
    connected = "Extension: connected" in output
    return _setup_check(
        "browser_bridge",
        "Browser Bridge",
        "ready" if connected else "needs_config",
        "Browser Bridge extension connected" if connected else "Browser Bridge daemon is running but extension is not connected",
    )


def _setup_check(check_id: str, label: str, status: str, message: str) -> dict[str, Any]:
    return {"id": check_id, "label": label, "status": status, "message": message}


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "products", "records", "tables", "capabilities", "cli_list", "clis"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("data", "result", "response"):
        value = payload.get(key)
        nested_items = _extract_items(value)
        if nested_items:
            return nested_items
    if isinstance(payload.get("item"), dict):
        return [payload["item"]]
    return []


def _extract_first(payload: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                return payload[key]
        for nested_key in ("data", "result", "status"):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                value = _extract_first(nested, keys)
                if value is not None:
                    return value
    return None


def _redact_sensitive_payload(payload: Any) -> Any:
    sensitive_keys = ("cookie", "token", "password", "secret", "credential", "key")
    if isinstance(payload, list):
        return [_redact_sensitive_payload(item) for item in payload]
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if any(marker in key.lower() for marker in sensitive_keys):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive_payload(value)
        return redacted
    return payload


def _tool_definition_from_item(item: dict[str, Any]) -> ToolDefinition:
    raw_name = str(item.get("name") or item.get("id") or item.get("cli_name") or item.get("title") or "o2_tool")
    tool_id = normalize_tool_id(str(item.get("tool_id") or raw_name))
    description = str(item.get("description") or item.get("summary") or item.get("capability") or "")
    category = str(item.get("category") or item.get("group") or item.get("type") or "o2")
    risk_level = str(item.get("risk_level") or item.get("risk") or "medium")
    metadata = {
        "provider": "o2",
        "external_name": raw_name,
        "version": str(item.get("version") or ""),
        "status": str(item.get("status") or ""),
        "entry_point": str(item.get("entry_point") or item.get("entryPoint") or ""),
    }
    return ToolDefinition(
        id=tool_id,
        name=raw_name,
        description=description or raw_name,
        category=category,
        risk_level=risk_level,
        provider="o2",
        external_name=raw_name,
        metadata=metadata,
        enabled=str(item.get("status") or "").lower() not in {"disabled", "deprecated", "blocked"},
    )


def _web_result_from_item(item: dict[str, Any]) -> WebSearchResult:
    url = str(item.get("url") or item.get("href") or item.get("link") or item.get("reference") or "")
    title = str(item.get("title") or item.get("name") or url or "Oxygen-CLI result")
    snippet = str(item.get("snippet") or item.get("content") or item.get("summary") or item.get("description") or "")
    return WebSearchResult(title=title, url=url or f"o2://result/{title}", snippet=snippet)


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in item.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            flat[key] = value
    return flat
