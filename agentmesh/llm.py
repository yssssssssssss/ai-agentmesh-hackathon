from __future__ import annotations

import os
from time import monotonic
from typing import Any

import httpx

from agentmesh.models import ModelDefinition
from agentmesh.provider_status import ProviderStatus, ProviderTelemetry, build_provider_status

DEFAULT_MODEL_ID = "default"
DEFAULT_LLM_TIMEOUT_SECONDS = 30.0
DEFAULT_LLM_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_CHAT_LLM_TIMEOUT_SECONDS = 120.0
DEFAULT_RESEARCH_SKILL_TIMEOUT_SECONDS = 180.0
DEFAULT_MARKET_LLM_TIMEOUT_SECONDS = 180.0
_llm_telemetry = ProviderTelemetry()


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        api_style: str = "chat_completions",
        http_client: httpx.Client | None = None,
        timeout_seconds: float | None = None,
        connect_timeout_seconds: float | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_style = api_style
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else llm_timeout_seconds()
        self.connect_timeout_seconds = (
            connect_timeout_seconds if connect_timeout_seconds is not None else llm_connect_timeout_seconds()
        )
        self.http_client = http_client or httpx.Client(timeout=self._httpx_timeout())

    @classmethod
    def from_env(cls, *, timeout_seconds: float | None = None) -> LLMClient | None:
        return cls.from_model_id(os.getenv("AGENTMESH_MODEL_DEFAULT") or DEFAULT_MODEL_ID, timeout_seconds=timeout_seconds)

    @classmethod
    def from_model_id(cls, model_id: str | None, *, timeout_seconds: float | None = None) -> LLMClient | None:
        config = model_config_from_env(model_id)
        if config is None or not config["api_key"]:
            return None
        return cls(
            base_url=config["base_url"],
            api_key=config["api_key"],
            model=config["model_name"],
            api_style=config.get("api_style", "chat_completions"),
            timeout_seconds=timeout_seconds,
        )

    def _httpx_timeout(self) -> httpx.Timeout:
        connect = min(self.connect_timeout_seconds, self.timeout_seconds)
        return httpx.Timeout(self.timeout_seconds, connect=connect)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        started = monotonic()
        try:
            if self.api_style == "gemini_contents":
                result = self._complete_with_gemini_contents(system_prompt, user_prompt)
            elif self.api_style == "responses":
                result = self._complete_with_responses_api(system_prompt, user_prompt)
            else:
                result = self._complete_with_chat_completions(system_prompt, user_prompt)
            _llm_telemetry.success((monotonic() - started) * 1000)
            return result
        except httpx.TimeoutException as error:
            _llm_telemetry.failure(error, (monotonic() - started) * 1000)
            raise LLMRequestError("timeout", f"LLM request timed out after {self.timeout_seconds:g}s") from error
        except httpx.HTTPStatusError as error:
            reason = "auth_error" if error.response.status_code in {401, 403} else "http_status"
            wrapped = LLMRequestError(reason, f"LLM service returned HTTP {error.response.status_code}")
            _llm_telemetry.failure(wrapped, (monotonic() - started) * 1000)
            raise wrapped from error
        except httpx.RequestError as error:
            _llm_telemetry.failure(error, (monotonic() - started) * 1000)
            raise LLMRequestError("request_error", "LLM request failed before receiving a response") from error
        except (KeyError, TypeError, ValueError) as error:
            _llm_telemetry.failure(error, (monotonic() - started) * 1000)
            raise LLMRequestError("invalid_response", "LLM response payload could not be parsed") from error

    def _complete_with_chat_completions(self, system_prompt: str, user_prompt: str) -> str:
        response = self.http_client.post(
            api_url(self.base_url, "chat_completions"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"].strip()

    def _complete_with_responses_api(self, system_prompt: str, user_prompt: str) -> str:
        response = self.http_client.post(
            api_url(self.base_url, "responses"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        return parse_responses_output(response.json()).strip()

    def _complete_with_gemini_contents(self, system_prompt: str, user_prompt: str) -> str:
        response = self.http_client.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            },
        )
        response.raise_for_status()
        return parse_gemini_contents_output(response.json()).strip()


def model_config_from_env(model_id: str | None) -> dict[str, str] | None:
    normalized_id = normalize_model_id(model_id)
    if normalized_id == DEFAULT_MODEL_ID:
        base_url = os.getenv("AI_API_URL") or os.getenv("AGENTMESH_LLM_BASE_URL")
        api_key = os.getenv("AI_API_KEY") or os.getenv("AGENTMESH_LLM_API_KEY")
        model = os.getenv("AI_MODEL") or os.getenv("AGENTMESH_LLM_MODEL")
        label = os.getenv("AGENTMESH_LLM_LABEL") or model or "Default model"
        api_style = os.getenv("AI_API_STYLE") or os.getenv("AGENTMESH_LLM_API_STYLE") or infer_api_style(base_url)
    else:
        prefix = f"AGENTMESH_MODEL_{env_key(normalized_id)}"
        base_url = os.getenv(f"{prefix}_BASE_URL")
        api_key = os.getenv(f"{prefix}_API_KEY")
        model = os.getenv(f"{prefix}_MODEL")
        label = os.getenv(f"{prefix}_LABEL") or model or normalized_id
        api_style = os.getenv(f"{prefix}_API_STYLE") or infer_api_style(base_url)

    if not base_url or not api_key or not model:
        return None
    return {
        "id": normalized_id,
        "label": label,
        "provider": "openai_compatible",
        "base_url": base_url,
        "api_key": api_key,
        "model_name": model,
        "api_style": api_style,
    }


def llm_provider_status() -> ProviderStatus:
    configured = model_config_from_env(os.getenv("AGENTMESH_MODEL_DEFAULT") or DEFAULT_MODEL_ID) is not None
    return build_provider_status(
        name="llm",
        configured=configured,
        ready=configured,
        telemetry=_llm_telemetry,
        error=None if configured else "not_configured",
    )


class LLMRequestError(RuntimeError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def llm_timeout_seconds() -> float:
    return _positive_float_env("AGENTMESH_LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS)


def llm_chat_timeout_seconds() -> float:
    return _positive_float_env("AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS", DEFAULT_CHAT_LLM_TIMEOUT_SECONDS)


def research_skill_timeout_seconds() -> float:
    return _positive_float_env(
        "AGENTMESH_RESEARCH_SKILL_TIMEOUT_SECONDS",
        DEFAULT_RESEARCH_SKILL_TIMEOUT_SECONDS,
    )


def market_llm_timeout_seconds() -> float:
    """Timeout for the autonomous market's background LLM calls (signal synthesis, delegated
    answer, match confirm). Much longer than the interactive chat timeout — these run in
    background workers, not on a user-facing latency budget, so they must not silently time
    out and fall back to templates."""
    return _positive_float_env("AGENTMESH_MARKET_LLM_TIMEOUT_SECONDS", DEFAULT_MARKET_LLM_TIMEOUT_SECONDS)


def llm_connect_timeout_seconds() -> float:
    return _positive_float_env("AGENTMESH_LLM_CONNECT_TIMEOUT_SECONDS", DEFAULT_LLM_CONNECT_TIMEOUT_SECONDS)


def llm_timeout_config() -> dict[str, Any]:
    return {
        "timeout_seconds": llm_timeout_seconds(),
        "chat_timeout_seconds": llm_chat_timeout_seconds(),
        "research_skill_timeout_seconds": research_skill_timeout_seconds(),
        "connect_timeout_seconds": llm_connect_timeout_seconds(),
    }


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def list_model_definitions_from_env() -> list[ModelDefinition]:
    configured_ids = {
        normalize_model_id(os.getenv("AGENTMESH_MODEL_DEFAULT") or DEFAULT_MODEL_ID),
        DEFAULT_MODEL_ID,
    }
    raw_ids = os.getenv("AGENTMESH_MODELS", "")
    configured_ids.update(normalize_model_id(item) for item in raw_ids.split(",") if item.strip())

    definitions: list[ModelDefinition] = []
    for model_id in sorted(configured_ids):
        config = model_config_from_env(model_id)
        if config is None:
            if model_id == DEFAULT_MODEL_ID:
                definitions.append(
                    ModelDefinition(
                        id=DEFAULT_MODEL_ID,
                        label="本地兜底模式",
                        provider="local_fallback",
                        model_name="local_fallback",
                        configured=False,
                    )
                )
            continue
        definitions.append(
            ModelDefinition(
                id=config["id"],
                label=config["label"],
                provider=config["provider"],
                model_name=config["model_name"],
                configured=bool(config["api_key"]),
            )
        )
    return definitions


def normalize_model_id(model_id: str | None) -> str:
    value = (model_id or DEFAULT_MODEL_ID).strip()
    return value or DEFAULT_MODEL_ID


def env_key(model_id: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in model_id).upper()


def infer_api_style(base_url: str | None) -> str:
    normalized = (base_url or "").rstrip("/")
    if "modelservice.jdcloud.com" in normalized and normalized.endswith("/responses"):
        return "gemini_contents"
    return "responses" if normalized.endswith("/responses") else "chat_completions"


def api_url(base_url: str, api_style: str) -> str:
    if api_style == "responses":
        return base_url if base_url.rstrip("/").endswith("/responses") else f"{base_url}/responses"
    return base_url if base_url.rstrip("/").endswith("/chat/completions") else f"{base_url}/chat/completions"


def parse_responses_output(payload: dict[str, object]) -> str:
    direct_text = payload.get("output_text")
    if isinstance(direct_text, str):
        return direct_text
    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    raise ValueError("Responses API payload did not contain output text")


def parse_gemini_contents_output(payload: dict[str, object]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Gemini payload did not contain candidates")
    parts: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        raw_parts = content.get("parts")
        if not isinstance(raw_parts, list):
            continue
        for part in raw_parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    if not parts:
        raise ValueError("Gemini payload did not contain text parts")
    return "\n".join(parts)
