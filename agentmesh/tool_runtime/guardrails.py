from __future__ import annotations

import json
import re

from agents import ToolGuardrailFunctionOutput, tool_input_guardrail, tool_output_guardrail

from agentmesh.risk import RiskDecision, assess_external_content

_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:authorization\s*:\s*bearer\s+[^\s,;}]+|"
    r"(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|password|token|secret|credential)"
    r"\s*[:=]\s*[^\s,;}]+)"
)


def contains_credential(text: str) -> bool:
    return bool(_CREDENTIAL_PATTERN.search(text))


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
