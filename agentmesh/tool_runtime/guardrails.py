from __future__ import annotations

import json
import re

from agents import ToolGuardrailFunctionOutput, tool_input_guardrail, tool_output_guardrail

from agentmesh.risk import RiskDecision, assess_external_content

_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:"
    r"[\"']?authorization[\"']?\s*:\s*[\"']?bearer\s+[^\s,;}，；。！？\"']+|"
    r"bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"[\"']?(?:set-cookie|cookie)[\"']?\s*[:=]\s*(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n,，。！？\"'}\]]+)|"
    r"[\"']?(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|password|credential|token|secret)"
    r"[\"']?\s*[:=]\s*[\"']?[^\s\"',;}，；。！？]+"
    r")"
)
_SENSITIVE_JSON_KEYS = frozenset(
    {
        "api_key",
        "access_token",
        "authorization",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "secret",
        "set_cookie",
        "token",
    }
)
_QUOTED_LOCAL_PATH_PATTERN = re.compile(
    r'"(?:/(?:Users|home|private|tmp|var/folders)/[^"\r\n]*|[A-Za-z]:\\[^"\r\n]*)"'
    r"|'(?:/(?:Users|home|private|tmp|var/folders)/[^'\r\n]*|[A-Za-z]:\\[^'\r\n]*)'"
)
_LOCAL_PATH_PATTERN = re.compile(
    r"(?<![\w:])(?:/(?:Users|home|private|tmp|var/folders)/[^\r\n,;，；。！？\"'}\]]+|"
    r"[A-Za-z]:\\[^\r\n,;，；。！？\"'}\]]+)"
)
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(r"(?<![A-Za-z0-9])1[3-9]\d{9}(?![A-Za-z0-9])")


def _normalized_json_key(value: object) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")
    compact = key.replace("_", "")
    return next(
        (candidate for candidate in _SENSITIVE_JSON_KEYS if compact == candidate.replace("_", "")),
        key,
    )


def _json_contains_credential(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _normalized_json_key(key) in _SENSITIVE_JSON_KEYS or _json_contains_credential(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_json_contains_credential(item) for item in value)
    return isinstance(value, str) and bool(_CREDENTIAL_PATTERN.search(value))


def _parsed_json(text: str) -> object | None:
    if not text.lstrip().startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def contains_credential(text: str) -> bool:
    parsed = _parsed_json(text)
    return (parsed is not None and _json_contains_credential(parsed)) or bool(_CREDENTIAL_PATTERN.search(text))


def _redact_unstructured_text(text: str) -> str:
    redacted = _CREDENTIAL_PATTERN.sub("[REDACTED_CREDENTIAL]", text)
    redacted = _QUOTED_LOCAL_PATH_PATTERN.sub("[REDACTED_LOCAL_PATH]", redacted)
    redacted = _LOCAL_PATH_PATTERN.sub("[REDACTED_LOCAL_PATH]", redacted)
    if "@" in redacted:
        redacted = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)
    if "1" in redacted:
        redacted = _PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
    return redacted


def _redact_json(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED_CREDENTIAL]"
                if _normalized_json_key(key) in _SENSITIVE_JSON_KEYS
                else _redact_json(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        return _redact_unstructured_text(value)
    return value


def redact_sensitive_text(text: str) -> str:
    """Remove credentials, contact data, and host-local paths before persistence."""
    parsed = _parsed_json(text)
    if parsed is not None:
        return json.dumps(_redact_json(parsed), ensure_ascii=False, separators=(",", ":"))
    return _redact_unstructured_text(text)


def unsafe_tool_output_reason(text: str) -> str | None:
    if contains_credential(text):
        return "credential_like_output"
    if assess_external_content(text).decision != RiskDecision.ALLOW:
        return "untrusted_instruction_output"
    return None


@tool_input_guardrail(name="agentmesh_secret_input_guardrail")
def reject_secret_arguments(data) -> ToolGuardrailFunctionOutput:  # noqa: ANN001
    raw = data.context.tool_arguments or "{}"
    if contains_credential(raw):
        return ToolGuardrailFunctionOutput.reject_content("Tool arguments contained a credential-like value.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ToolGuardrailFunctionOutput.reject_content("Tool arguments were not valid JSON.")
    if not isinstance(parsed, dict):
        return ToolGuardrailFunctionOutput.reject_content("Tool arguments must be a JSON object.")
    return ToolGuardrailFunctionOutput.allow()


@tool_output_guardrail(name="agentmesh_external_output_guardrail")
def quarantine_unsafe_output(data) -> ToolGuardrailFunctionOutput:  # noqa: ANN001
    reason = unsafe_tool_output_reason(str(data.output or ""))
    if reason == "credential_like_output":
        return ToolGuardrailFunctionOutput.reject_content("Tool output contained a credential-like value and was withheld.")
    if reason is not None:
        return ToolGuardrailFunctionOutput.reject_content(
            "Tool output contained untrusted instruction-like content and was withheld for review."
        )
    return ToolGuardrailFunctionOutput.allow()
