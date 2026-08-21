#!/usr/bin/env python3
"""Characterize the accepted AgentMesh target once, offline, against disposable SQLite.

This is a focused evidence execution, not a test suite. It runs production v1
routing/runtime and research-v2 routing/runtime/read/purge code from target base
dec6b55, using deterministic synthetic inputs and offline stubs only.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
OUTPUT = Path(os.environ.get("AGENTMESH_TARGET_CHARACTERIZATION_OUTPUT", REPOSITORY_ROOT / "build/agentmesh-target-characterization-v2"))
CASES_DIR = OUTPUT / "cases"
FIXTURE = OUTPUT / "fixture.sqlite3"
REPORT = OUTPUT / "report.json"
ATTESTATION = OUTPUT / "attestation.json"
SOURCE_HASHES = OUTPUT / "source-hashes.json"
ENVIRONMENT = OUTPUT / "environment.json"
HASHES = OUTPUT / "SHA256SUMS"
MANIFEST = OUTPUT / "manifest.json"
REPO = REPOSITORY_ROOT
LEGACY_CHARACTERIZER = REPO / "tests/fixtures/ai_x_history/characterize_v2_history.py"
TARGET_BASE = "dec6b55b3e97913c052ee2b665c063aec77a9dd3"
TARGET_TREE = "eb39f8159afb421233b657747192447734fd8b07"
EXECUTION_ID = "agentmesh-target-characterization-v2"

CASE_IDS = [
    "v1-routing",
    "research-v2-routing",
    "client-turn-replay",
    "missing-runtime-fail-closed",
    "off-rollback",
    "owner-read",
    "foreign-owner-hidden",
    "integrity-corruption-rejected",
    "restart-read",
    "purge-tombstone/history-no-mutation",
]
CASE_FILENAMES = {
    case_id: f"{index:02d}-{case_id.replace('/', '-')}.json"
    for index, case_id in enumerate(CASE_IDS, start=1)
}

# Remove ambient credentials before importing any runtime integration module.
SCRUBBED_ENVIRONMENT_NAMES = [
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "TAVILY_API_KEY",
]
for _name in SCRUBBED_ENVIRONMENT_NAMES:
    os.environ.pop(_name, None)
os.environ["AGENTMESH_AGENT_RUNTIME"] = "v2"
os.environ["AGENTMESH_SDK_STRICT_TOOLS"] = "true"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))


def canonical_bytes(value: object) -> bytes:
    """Canonical UTF-8 JSON profile used for all generated JSON evidence."""

    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def write_canonical(path: Path, value: object) -> None:
    path.write_bytes(canonical_bytes(value))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "path": path.relative_to(OUTPUT).as_posix(),
        "sha256": sha256_file(path),
    }


def git(*args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(REPO), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def load_history_characterizer():
    spec = importlib.util.spec_from_file_location("target_history_characterizer", LEGACY_CHARACTERIZER)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load focused history characterizer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.OUTPUT = OUTPUT
    module.FIXTURE = FIXTURE
    return module


def source_hash_manifest() -> dict[str, object]:
    resolved = str(git("rev-parse", TARGET_BASE))
    tree = str(git("show", "-s", "--format=%T", TARGET_BASE))
    if resolved != TARGET_BASE or tree != TARGET_TREE:
        raise AssertionError(f"target identity mismatch: {resolved} {tree}")

    tracked = str(git("ls-tree", "-r", "--name-only", TARGET_BASE, "--", "agentmesh")).splitlines()
    production_paths = sorted(path for path in tracked if path.endswith(".py"))
    records: list[dict[str, object]] = []
    for relative in production_paths:
        target_bytes = git("show", f"{TARGET_BASE}:{relative}", binary=True)
        current_path = REPO / relative
        current_bytes = current_path.read_bytes()
        records.append(
            {
                "current_bytes": len(current_bytes),
                "current_sha256": sha256_bytes(current_bytes),
                "matches_target_base": current_bytes == target_bytes,
                "path": relative,
                "target_bytes": len(target_bytes),
                "target_sha256": sha256_bytes(target_bytes),
            }
        )

    support_records: list[dict[str, object]] = []
    for relative in [
        "tests/research_orchestration_testkit.py",
        "tests/fixtures/ai_x_history/characterize_v2_history.py",
    ]:
        current = (REPO / relative).read_bytes()
        target_exists = subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "-e", f"{TARGET_BASE}:{relative}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        target = git("show", f"{TARGET_BASE}:{relative}", binary=True) if target_exists else None
        support_records.append(
            {
                "current_bytes": len(current),
                "current_sha256": sha256_bytes(current),
                "matches_target_base": target == current if target is not None else None,
                "path": relative,
                "role": "characterization_support",
                "target_bytes": len(target) if target is not None else None,
                "target_sha256": sha256_bytes(target) if target is not None else None,
            }
        )

    required_exact_paths = {
        "agentmesh/agent_runtime/service.py",
        "agentmesh/agent_runtime/settings.py",
        "agentmesh/models.py",
        "agentmesh/research_orchestration/runtime.py",
        "agentmesh/research_orchestration/workflow.py",
        "agentmesh/routes/agent_runs.py",
        "agentmesh/store.py",
    }
    observed_paths = {str(item["path"]) for item in records}
    if not required_exact_paths <= observed_paths:
        raise AssertionError("required runtime source path is absent from target tree")

    return {
        "all_production_python_sources_match_target_base": all(
            bool(item["matches_target_base"]) for item in records
        ),
        "canonicalization": "utf8-sort-keys-compact-v1",
        "production_python_file_count": len(records),
        "production_python_sources": records,
        "required_exact_paths": sorted(required_exact_paths),
        "schema_version": "agentmesh-target-source-hashes-v1",
        "support_sources": support_records,
        "target": {
            "commit": TARGET_BASE,
            "subject": str(git("show", "-s", "--format=%s", TARGET_BASE)),
            "tree": TARGET_TREE,
        },
        "worktree_head": str(git("rev-parse", "HEAD")),
    }


def environment_manifest() -> dict[str, object]:
    package_names = ["fastapi", "openai-agents", "pydantic", "PyYAML", "starlette"]
    packages: dict[str, str | None] = {}
    for name in package_names:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "canonicalization": "utf8-sort-keys-compact-v1",
        "executable": sys.executable,
        "git_version": subprocess.run(
            ["git", "--version"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "machine": platform.machine(),
        "packages": packages,
        "platform": platform.platform(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "schema_version": "agentmesh-target-characterization-environment-v1",
        "sqlite_runtime_version": sqlite3.sqlite_version,
        "system": platform.system(),
        "system_release": platform.release(),
    }


class NetworkGuard:
    """Fail and record any in-process network attempt."""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._socket_connect = socket.socket.connect
        self._create_connection = socket.create_connection
        self._getaddrinfo = socket.getaddrinfo

    def __enter__(self) -> NetworkGuard:
        guard = self

        def blocked_connect(_socket, address):  # noqa: ANN001, ANN202
            guard.attempts.append(f"socket.connect:{address!r}")
            raise RuntimeError("network disabled by target characterization")

        def blocked_create_connection(address, *args, **kwargs):  # noqa: ANN001, ANN202, ARG001
            guard.attempts.append(f"socket.create_connection:{address!r}")
            raise RuntimeError("network disabled by target characterization")

        def blocked_getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001, ANN202, ARG001
            guard.attempts.append(f"socket.getaddrinfo:{host!r}:{port!r}")
            raise RuntimeError("network disabled by target characterization")

        socket.socket.connect = blocked_connect
        socket.create_connection = blocked_create_connection
        socket.getaddrinfo = blocked_getaddrinfo
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        socket.socket.connect = self._socket_connect
        socket.create_connection = self._create_connection
        socket.getaddrinfo = self._getaddrinfo


def table_count(repository, table: str, where: str = "", values: tuple = ()) -> int:  # noqa: ANN001
    with repository._connect() as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table} {where}", values).fetchone()[0])


def request_for(research_runtime: object | None, *, include_runtime: bool = True):
    from starlette.requests import Request

    state = SimpleNamespace()
    if include_runtime:
        state.research_runtime = research_runtime
    scope = {
        "app": SimpleNamespace(state=state),
        "headers": [],
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/agent/runs",
        "query_string": b"",
        "scheme": "http",
        "server": ("offline.invalid", 80),
        "client": ("127.0.0.1", 0),
        "type": "http",
    }
    return Request(scope)


async def routing_characterization(repository, history_module) -> dict[str, dict[str, object]]:  # noqa: ANN001
    from agents.testing import ScriptedModel, assistant_message
    from fastapi import HTTPException

    import agentmesh.routes.agent_runs as agent_run_routes
    import agentmesh.routes.chat as chat_routes
    from agentmesh.agent_runtime.service import AgentRuntimeService
    from agentmesh.models import AgentRun, AgentRunCreateRequest
    from agentmesh.research_orchestration.artifacts import ArtifactStore
    from agentmesh.research_orchestration.compiler import CompetitivePlanCompiler
    from agentmesh.research_orchestration.planning import (
        CompetitiveRequirementPlanner,
        requirement_version_from_result,
    )
    from agentmesh.research_orchestration.runtime import ResearchRuntime
    from agentmesh.research_orchestration.workflow import ResearchWorkflowService
    from agentmesh.skill_runtime.service import SkillCatalogService
    from research_orchestration_testkit import competitive_snapshot

    user = repository.get_user(history_module.USER_ID)
    if user is None:
        raise AssertionError("synthetic owner was not created")

    class DeterministicPlanning:
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.compile_calls = 0

        async def prepare_requirement(
            self,
            run: AgentRun,
            *,
            version: int,
            clarification_answers: dict[str, str] | None = None,
            revision=None,  # noqa: ANN001
        ):
            self.prepare_calls += 1
            raw_input = revision.research_goal if revision is not None and revision.research_goal else run.input_text
            answers = dict(clarification_answers or {})
            if revision is not None and revision.competitor_scope:
                answers["clarify_competitor_scope"] = revision.competitor_scope
            result = await CompetitiveRequirementPlanner().plan(
                raw_input,
                explicit_skill_name="competitive-analysis",
                clarification_answers=answers,
                model=None,
            )
            return requirement_version_from_result(run.id, version, result)

        def compile_plan(self, run: AgentRun, requirement, *, version: int):  # noqa: ANN001, ANN201
            self.compile_calls += 1
            snapshot = competitive_snapshot(history_module.BASE_TIME)
            return CompetitivePlanCompiler().compile(
                requirement,
                snapshot,
                plan_version=version,
                now=history_module.BASE_TIME,
            )

    class CountingExecution:
        def __init__(self) -> None:
            self.calls = 0

        async def claim_and_run(self, attempt_id: str, *, token: str | None = None) -> None:
            del attempt_id, token
            self.calls += 1

    scripted_model = ScriptedModel(
        [
            [assistant_message("Synthetic v1 routing response.")],
            [assistant_message("Synthetic off rollback response.")],
        ]
    )
    v1_runtime = AgentRuntimeService(
        repository,
        model=scripted_model,
        enabled=True,
        skill_catalog=SkillCatalogService(repository),
    )
    planning = DeterministicPlanning()
    execution = CountingExecution()
    workflow_service = ResearchWorkflowService(
        repository,
        planning,
        execution,
        ArtifactStore(repository),
        execution_allowed=lambda: False,
    )
    research_runtime = ResearchRuntime(repository, workflow_service, execution_enabled=False)
    await research_runtime.start()

    # Route module globals intentionally point to the one disposable database.
    prior_route_store = agent_run_routes.store
    prior_agent_runtime = chat_routes.agent.agent_runtime
    agent_run_routes.store = repository
    chat_routes.agent.agent_runtime = v1_runtime

    results: dict[str, dict[str, object]] = {}
    try:
        os.environ["AGENTMESH_SKILL_ORCHESTRATION"] = "preview"
        v1_request = AgentRunCreateRequest(
            content="生成一段合成欢迎语。",
            client_turn_id="turn_synthetic_v1_routing",
            orchestration_mode="single",
        )
        response = await agent_run_routes.start_agent_run(
            v1_request,
            request_for(research_runtime),
            user,
        )
        v1_created = response.item
        task = v1_runtime._tasks.get(v1_created.id)
        if task is not None:
            await task
        v1_stored = repository.get_agent_run(v1_created.id)
        v1_workflow = repository.get_research_workflow(v1_created.id)
        v1_passed = bool(
            v1_stored is not None
            and v1_stored.orchestration_version == "v1"
            and v1_stored.status.value == "completed"
            and v1_workflow is None
        )
        results["v1-routing"] = {
            "expected": {
                "created_orchestration_version": "v1",
                "research_workflow_created": False,
                "route": "AgentRuntimeService.start",
            },
            "inputs": {
                "client_turn_id": v1_request.client_turn_id,
                "configured_mode": "preview",
                "content_class": "synthetic ordinary request",
                "requested_orchestration_mode": v1_request.orchestration_mode.value,
                "user_scope": {
                    "project_id": user.default_project_id,
                    "user_id": user.id,
                    "workspace_id": user.workspace_id,
                },
            },
            "observations": {
                "created_orchestration_version": v1_stored.orchestration_version if v1_stored else None,
                "final_status": v1_stored.status.value if v1_stored else None,
                "research_workflow_created": v1_workflow is not None,
                "scripted_model": type(scripted_model).__name__,
            },
            "passed": v1_passed,
        }

        research_request = AgentRunCreateRequest(
            content="对比合成甲产品与合成乙产品的能力、恢复和适用场景。",
            client_turn_id="turn_synthetic_research_v2",
            orchestration_mode="auto",
        )
        v1_run_count_before = table_count(repository, "agent_runs", "WHERE orchestration_version = 'v1'")
        response = await agent_run_routes.start_agent_run(
            research_request,
            request_for(research_runtime),
            user,
        )
        research_created = response.item
        await workflow_service.wait_for_idle()
        research_stored = repository.get_agent_run(research_created.id)
        research_projection = workflow_service.get_projection(
            research_created.id,
            owner=history_module.ResearchOwnerScope(
                user_id=user.id,
                workspace_id=user.workspace_id,
                project_id=user.default_project_id,
            ),
        )
        v1_run_count_after = table_count(repository, "agent_runs", "WHERE orchestration_version = 'v1'")
        research_passed = bool(
            research_stored is not None
            and research_stored.orchestration_version == "research-v2"
            and research_stored.orchestration_mode == "preview"
            and research_projection.orchestration_version == "research-v2"
            and research_projection.workflow.active_gate.value == "plan_confirmation"
            and planning.prepare_calls == 1
            and planning.compile_calls == 1
            and execution.calls == 0
            and v1_run_count_after == v1_run_count_before
        )
        results["research-v2-routing"] = {
            "expected": {
                "created_orchestration_version": "research-v2",
                "effective_mode": "preview",
                "provider_execution_calls": 0,
                "route": "ResearchRuntime.start_run",
            },
            "inputs": {
                "client_turn_id": research_request.client_turn_id,
                "configured_mode": "preview",
                "content_class": "synthetic competitive request",
                "requested_orchestration_mode": research_request.orchestration_mode.value,
            },
            "observations": {
                "active_gate": research_projection.workflow.active_gate.value,
                "compile_calls": planning.compile_calls,
                "created_orchestration_version": (
                    research_stored.orchestration_version if research_stored else None
                ),
                "effective_mode": research_stored.orchestration_mode if research_stored else None,
                "execution_calls": execution.calls,
                "prepare_calls": planning.prepare_calls,
                "v1_run_count_delta": v1_run_count_after - v1_run_count_before,
            },
            "passed": research_passed,
        }

        os.environ["AGENTMESH_SKILL_ORCHESTRATION"] = "off"
        run_count_before_replay = table_count(repository, "agent_runs")
        thread_count_before_replay = len(repository.chat_threads)
        event_count_before_replay = len(repository.list_agent_run_events(research_created.id))
        replay_response = await agent_run_routes.start_agent_run(
            research_request,
            request_for(research_runtime),
            user,
        )
        replayed = replay_response.item
        run_count_after_replay = table_count(repository, "agent_runs")
        thread_count_after_replay = len(repository.chat_threads)
        event_count_after_replay = len(repository.list_agent_run_events(research_created.id))
        replay_passed = bool(
            replayed.id == research_created.id
            and replayed.orchestration_version == "research-v2"
            and run_count_after_replay == run_count_before_replay
            and thread_count_after_replay == thread_count_before_replay
            and event_count_after_replay == event_count_before_replay
        )
        results["client-turn-replay"] = {
            "expected": {
                "new_run_created": False,
                "replayed_version": "research-v2",
                "routing_precedence": "client_turn_id replay before current mode routing",
            },
            "inputs": {
                "client_turn_id": research_request.client_turn_id,
                "mode_after_original_creation": "off",
                "original_version": "research-v2",
                "payload_equal_to_original": True,
            },
            "observations": {
                "event_count_delta": event_count_after_replay - event_count_before_replay,
                "replayed_same_run": replayed.id == research_created.id,
                "replayed_version": replayed.orchestration_version,
                "run_count_delta": run_count_after_replay - run_count_before_replay,
                "thread_count_delta": thread_count_after_replay - thread_count_before_replay,
            },
            "passed": replay_passed,
        }

        os.environ["AGENTMESH_SKILL_ORCHESTRATION"] = "preview"
        missing_request = AgentRunCreateRequest(
            content="比较合成丙产品与合成丁产品的能力和局限。",
            client_turn_id="turn_synthetic_missing_runtime",
            orchestration_mode="auto",
        )
        run_count_before_missing = table_count(repository, "agent_runs")
        thread_count_before_missing = len(repository.chat_threads)
        missing_status = None
        missing_detail = None
        try:
            await agent_run_routes.start_agent_run(
                missing_request,
                request_for(None, include_runtime=False),
                user,
            )
        except HTTPException as error:
            missing_status = error.status_code
            missing_detail = error.detail
        run_count_after_missing = table_count(repository, "agent_runs")
        thread_count_after_missing = len(repository.chat_threads)
        missing_passed = bool(
            missing_status == 503
            and missing_detail == "Research Runtime is unavailable"
            and run_count_after_missing == run_count_before_missing
            and thread_count_after_missing == thread_count_before_missing
        )
        results["missing-runtime-fail-closed"] = {
            "expected": {
                "detail": "Research Runtime is unavailable",
                "fallback_to_v1": False,
                "status_code": 503,
            },
            "inputs": {
                "client_turn_id": missing_request.client_turn_id,
                "configured_mode": "preview",
                "content_class": "synthetic competitive request",
                "research_runtime_present": False,
            },
            "observations": {
                "detail": missing_detail,
                "run_count_delta": run_count_after_missing - run_count_before_missing,
                "status_code": missing_status,
                "thread_count_delta": thread_count_after_missing - thread_count_before_missing,
            },
            "passed": missing_passed,
        }

        os.environ["AGENTMESH_SKILL_ORCHESTRATION"] = "off"
        off_request = AgentRunCreateRequest(
            content="对比合成戊产品与合成己产品的能力和适用场景。",
            client_turn_id="turn_synthetic_off_rollback",
            orchestration_mode="auto",
        )
        workflows_before_off = table_count(repository, "research_workflows")
        response = await agent_run_routes.start_agent_run(
            off_request,
            request_for(research_runtime),
            user,
        )
        off_created = response.item
        task = v1_runtime._tasks.get(off_created.id)
        if task is not None:
            await task
        off_stored = repository.get_agent_run(off_created.id)
        workflows_after_off = table_count(repository, "research_workflows")
        historical_projection = workflow_service.get_projection(
            research_created.id,
            owner=history_module.ResearchOwnerScope(
                user_id=user.id,
                workspace_id=user.workspace_id,
                project_id=user.default_project_id,
            ),
        )
        off_passed = bool(
            off_stored is not None
            and off_stored.orchestration_version == "v1"
            and off_stored.orchestration_mode == "off"
            and repository.get_research_workflow(off_stored.id) is None
            and workflows_after_off == workflows_before_off
            and historical_projection.orchestration_version == "research-v2"
            and execution.calls == 0
        )
        results["off-rollback"] = {
            "expected": {
                "historical_research_v2_readable": True,
                "new_orchestration_version": "v1",
                "new_research_workflow_created": False,
            },
            "inputs": {
                "client_turn_id": off_request.client_turn_id,
                "configured_mode": "off",
                "content_class": "synthetic competitive request",
            },
            "observations": {
                "execution_calls": execution.calls,
                "historical_research_v2_readable": (
                    historical_projection.orchestration_version == "research-v2"
                ),
                "new_orchestration_mode": off_stored.orchestration_mode if off_stored else None,
                "new_orchestration_version": off_stored.orchestration_version if off_stored else None,
                "new_research_workflow_created": (
                    repository.get_research_workflow(off_stored.id) is not None if off_stored else None
                ),
                "workflow_count_delta": workflows_after_off - workflows_before_off,
            },
            "passed": off_passed,
        }
    finally:
        agent_run_routes.store = prior_route_store
        chat_routes.agent.agent_runtime = prior_agent_runtime
        await research_runtime.shutdown()

    return results


def case_document(case_id: str, raw: dict[str, object]) -> dict[str, object]:
    return {
        "case_id": case_id,
        "canonicalization": "utf8-sort-keys-compact-v1",
        "expected": raw["expected"],
        "inputs": raw["inputs"],
        "observations": raw["observations"],
        "sequence": CASE_IDS.index(case_id) + 1,
        "verdict": "passed" if raw["passed"] else "failed",
    }


def history_cases(checks: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    owner = checks["owner_read"]
    foreign = checks["foreign_owner_hidden"]
    corruption = checks["integrity_corruption_rejected"]
    restart = checks["restart_read"]
    pure_read = checks["history_projection_no_mutation_actions"]
    purge = checks["purge_tombstones"]
    return {
        "owner-read": {
            "expected": {
                "integrity_errors": [],
                "response_discriminator": "research-v2",
                "stored_version": "research-v2",
            },
            "inputs": {
                "dispatch": "exact stored orchestration_version",
                "owner_scope": {
                    "project_id": "project_fixture",
                    "user_id": "user_fixture_owner",
                    "workspace_id": "workspace_fixture",
                },
                "run_id": "run_v2_history_001",
            },
            "observations": owner,
            "passed": bool(owner["passed"]),
        },
        "foreign-owner-hidden": {
            "expected": {
                "exception": "ResearchNotFoundError",
                "existence_disclosed": False,
            },
            "inputs": {
                "foreign_scope": {
                    "project_id": "project_fixture_foreign",
                    "user_id": "user_fixture_foreign",
                    "workspace_id": "workspace_fixture_foreign",
                },
                "run_id": "run_v2_history_001",
            },
            "observations": foreign,
            "passed": bool(foreign["passed"]),
        },
        "integrity-corruption-rejected": {
            "expected": {
                "exception": "ResearchConflictError",
                "projection_returned": False,
            },
            "inputs": {
                "corruption": (
                    "agent_runs payload discriminator changed while indexed stored version "
                    "remained research-v2"
                ),
                "database": "isolated copy of disposable fixture",
                "run_id": "run_v2_history_001",
            },
            "observations": corruption,
            "passed": bool(corruption["passed"]),
        },
        "restart-read": {
            "expected": {
                "projection_hash_stable": True,
                "scheduling_on_read": False,
            },
            "inputs": {
                "restart": "new SQLiteStore and ResearchWorkflowService over the same copied database",
                "run_id": "run_v2_history_001",
            },
            "observations": restart,
            "passed": bool(restart["passed"]),
        },
        "purge-tombstone/history-no-mutation": {
            "expected": {
                "history_read_mutations": 0,
                "owner_purge_creates_tombstones": True,
                "post_purge_history_hidden": True,
                "run_input_retained": True,
            },
            "inputs": {
                "history_read_database": "isolated copy of disposable fixture",
                "purge_database": "separate isolated copy of disposable fixture",
                "run_id": "run_v2_history_001",
            },
            "observations": {
                "history_no_mutation": pure_read,
                "purge_tombstone": purge,
            },
            "passed": bool(pure_read["passed"] and purge["passed"]),
        },
    }


def sqlite_attestation(path: Path) -> dict[str, object]:
    with sqlite3.connect(path) as connection:
        integrity_rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        quick_rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    companions = [
        candidate.name
        for candidate in [Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")]
        if candidate.exists()
    ]
    return {
        "application_id": application_id,
        "bytes": path.stat().st_size,
        "companions": companions,
        "integrity_check": integrity_rows,
        "path": path.name,
        "quick_check": quick_rows,
        "sha256": sha256_file(path),
        "user_version": user_version,
    }


def prepare_output() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    keep = Path(__file__).resolve()
    for path in list(OUTPUT.iterdir()):
        if path.resolve() == keep:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    CASES_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    prepare_output()
    executed_script = OUTPUT / "characterize_target.py"
    source_script = Path(__file__).resolve()
    if executed_script.resolve() != source_script:
        shutil.copyfile(source_script, executed_script)
    source_manifest = source_hash_manifest()
    if not source_manifest["all_production_python_sources_match_target_base"]:
        raise AssertionError("current production Python sources do not match target base")
    write_canonical(SOURCE_HASHES, source_manifest)
    write_canonical(ENVIRONMENT, environment_manifest())

    history_module = load_history_characterizer()
    with NetworkGuard() as network_guard:
        build_observation = history_module.build_fixture(FIXTURE)
        repository = history_module.SQLiteStore(FIXTURE)
        routing = asyncio.run(routing_characterization(repository, history_module))
        history_checks = history_module.characterize(FIXTURE)
        sanitization = history_module.sanitization_scan(FIXTURE)
    history_module.canonicalize_database(FIXTURE)

    raw_cases = {**routing, **history_cases(history_checks)}
    if set(raw_cases) != set(CASE_IDS):
        raise AssertionError(f"case set mismatch: {sorted(raw_cases)}")
    case_documents: list[dict[str, object]] = []
    for case_id in CASE_IDS:
        document = case_document(case_id, raw_cases[case_id])
        write_canonical(CASES_DIR / CASE_FILENAMES[case_id], document)
        case_documents.append(document)

    fixture_record = sqlite_attestation(FIXTURE)
    fixture_passed = bool(
        fixture_record["integrity_check"] == ["ok"]
        and fixture_record["quick_check"] == ["ok"]
        and fixture_record["companions"] == []
    )
    all_cases_passed = all(document["verdict"] == "passed" for document in case_documents)
    offline_passed = not network_guard.attempts and build_observation["external_provider_calls"] == 0
    sanitization_passed = bool(sanitization["passed"])
    overall_passed = bool(
        all_cases_passed
        and fixture_passed
        and offline_passed
        and sanitization_passed
        and source_manifest["all_production_python_sources_match_target_base"]
    )

    case_records = [file_record(CASES_DIR / CASE_FILENAMES[case_id]) for case_id in CASE_IDS]
    report = {
        "canonicalization": "utf8-sort-keys-compact-v1",
        "case_count": len(case_documents),
        "case_files": case_records,
        "cases": [
            {
                "case_id": document["case_id"],
                "sequence": document["sequence"],
                "verdict": document["verdict"],
            }
            for document in case_documents
        ],
        "environment": file_record(ENVIRONMENT),
        "execution": {
            "external_provider_calls": build_observation["external_provider_calls"],
            "fixture_build_terminal_status": build_observation["terminal_status"],
            "kind": "single focused offline characterization script; not a test suite",
            "network_attempts": network_guard.attempts,
            "network_used": False,
            "offline_model_stub_calls_for_terminal_history": build_observation["offline_model_stub_calls"],
            "offline_tool_stub_calls_for_terminal_history": build_observation["offline_tool_stub_calls"],
            "provider_adapters_constructed": False,
            "routing_model_stub": "agents.testing.ScriptedModel",
            "synthetic_ids_only": True,
        },
        "execution_id": EXECUTION_ID,
        "fixture": fixture_record,
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_verdict": "passed" if overall_passed else "failed",
        "required_case_ids": CASE_IDS,
        "sanitization": sanitization,
        "schema_version": "agentmesh-accepted-target-characterization-report-v2",
        "source_hashes": file_record(SOURCE_HASHES),
        "target": {
            "commit": TARGET_BASE,
            "tree": TARGET_TREE,
            "worktree_head": str(git("rev-parse", "HEAD")),
        },
        "verdicts": {document["case_id"]: document["verdict"] for document in case_documents},
    }
    write_canonical(REPORT, report)

    attested_paths = [
        executed_script,
        FIXTURE,
        REPORT,
        SOURCE_HASHES,
        ENVIRONMENT,
        *[CASES_DIR / CASE_FILENAMES[case_id] for case_id in CASE_IDS],
    ]
    attestation = {
        "attestation_version": "agentmesh-accepted-target-characterization-attestation-v2",
        "attested_files": [file_record(path) for path in attested_paths],
        "case_count": len(case_documents),
        "case_verdicts": {document["case_id"]: document["verdict"] for document in case_documents},
        "execution_id": EXECUTION_ID,
        "fixture": fixture_record,
        "offline_execution": {
            "external_provider_calls": 0,
            "network_attempts": network_guard.attempts,
            "network_used": False,
            "provider_adapters_constructed": False,
            "scrubbed_credential_environment_names": SCRUBBED_ENVIRONMENT_NAMES,
        },
        "overall": "passed" if overall_passed else "failed",
        "report": file_record(REPORT),
        "sanitization_passed": sanitization_passed,
        "source_exactness_passed": source_manifest["all_production_python_sources_match_target_base"],
        "synthetic_data_only": True,
        "target_base": TARGET_BASE,
        "target_tree": TARGET_TREE,
    }
    write_canonical(ATTESTATION, attestation)

    sum_paths = sorted(
        [path for path in OUTPUT.rglob("*") if path.is_file() and path not in {HASHES, MANIFEST}],
        key=lambda path: path.relative_to(OUTPUT).as_posix().encode(),
    )
    HASHES.write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(OUTPUT).as_posix()}\n"
            for path in sum_paths
        ),
        encoding="utf-8",
    )
    manifest_paths = sorted(
        [path for path in OUTPUT.rglob("*") if path.is_file() and path != MANIFEST],
        key=lambda path: path.relative_to(OUTPUT).as_posix().encode(),
    )
    manifest = {
        "attestation": file_record(ATTESTATION),
        "canonicalization": "utf8-sort-keys-compact-v1",
        "directory": str(OUTPUT),
        "execution_id": EXECUTION_ID,
        "file_count_excluding_manifest": len(manifest_paths),
        "files": [file_record(path) for path in manifest_paths],
        "fixture": file_record(FIXTURE),
        "manifest_self_excluded": True,
        "overall": "passed" if overall_passed else "failed",
        "report": file_record(REPORT),
        "schema_version": "agentmesh-target-characterization-manifest-v2",
        "target_base": TARGET_BASE,
    }
    write_canonical(MANIFEST, manifest)

    print(
        json.dumps(
            {
                "attestation": str(ATTESTATION),
                "manifest": str(MANIFEST),
                "overall": manifest["overall"],
                "report": str(REPORT),
                "verdicts": report["verdicts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if overall_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
