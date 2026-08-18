from __future__ import annotations

import json

from agents import GuardrailFunctionOutput, input_guardrail, output_guardrail

from agentmesh.risk import RiskDecision, assess_external_content
from agentmesh.tool_runtime.guardrails import contains_credential


def _text(value) -> str:  # noqa: ANN001
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


@input_guardrail(name="agentmesh_input_policy", run_in_parallel=False)
def agentmesh_input_guardrail(_ctx, _agent, input_value) -> GuardrailFunctionOutput:  # noqa: ANN001
    text = _text(input_value)
    assessment = assess_external_content(text)
    return GuardrailFunctionOutput(
        output_info={"finding_codes": [finding.rule_id for finding in assessment.findings]},
        tripwire_triggered=assessment.decision != RiskDecision.ALLOW,
    )


@output_guardrail(name="agentmesh_output_policy")
def agentmesh_output_guardrail(_ctx, _agent, output) -> GuardrailFunctionOutput:  # noqa: ANN001
    text = _text(output)
    leaked_secret = contains_credential(text)
    return GuardrailFunctionOutput(
        output_info={"secret_pattern": leaked_secret},
        tripwire_triggered=leaked_secret,
    )
