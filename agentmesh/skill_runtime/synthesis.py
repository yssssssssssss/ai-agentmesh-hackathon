from __future__ import annotations

import json

from agents import Agent, RunConfig, Runner
from agents.models.interface import Model

from agentmesh.models import SkillNodeResult, SkillPlanNode, SkillSynthesisResult
from agentmesh.task_routing.contracts import CompletionCheckResult, TaskRoutingResult

_SYNTHESIS_INSTRUCTIONS = """Synthesize only the supplied normalized Skill node results.
Do not add facts, sources, tool output, or hidden reasoning. Every claim must cite existing node result IDs.
Factual claims must also cite existing source IDs. Advice without a source must set recommendation=true.
Use presentation_requirements only to organize the report; never invent content to fill a requested section.
Set presentation_outputs to the requested presentation requirements actually rendered in sections.
Preserve limitations and degradation. Return the required structured schema.
"""
_PRESENTATION_LABELS = {
    "strategy_map": "策略地图",
    "mental_model": "用户心智模型",
    "design_principles": "设计原则",
    "opportunity_list": "机会点",
    "prioritized_actions": "P0/P1/P2 行动",
    "roadmap": "实施路径",
    "metrics_plan": "指标与验证计划",
    "comparison_table": "对比结论",
    "report": "综合报告",
}


class SynthesisValidationError(ValueError):
    def __init__(self, codes: list[str]):
        self.codes = list(dict.fromkeys(codes))
        super().__init__(", ".join(self.codes))


def validate_synthesis(
    synthesis: SkillSynthesisResult,
    results: list[SkillNodeResult],
    *,
    required_presentation_outputs: list[str] | None = None,
) -> None:
    results_by_id = {result.id: result for result in results}
    artifact_ids = {artifact_id for result in results for artifact_id in result.artifact_ids}
    errors: list[str] = []
    if results and not synthesis.claims:
        errors.append("missing_claim_lineage")
    for claim in synthesis.claims:
        if not set(claim.node_result_ids).issubset(results_by_id):
            errors.append("unknown_node_result")
            continue
        claim_source_ids = {
            source.id
            for result_id in claim.node_result_ids
            for source in results_by_id[result_id].sources
        }
        if not set(claim.source_ids).issubset(claim_source_ids):
            errors.append("unknown_source")
        if not claim.recommendation and not claim.source_ids:
            errors.append("factual_claim_without_source")
    if not set(synthesis.artifact_ids).issubset(artifact_ids):
        errors.append("unknown_artifact")
    if not set(synthesis.presentation_outputs).issubset(required_presentation_outputs or []):
        errors.append("unknown_presentation_output")
    if required_presentation_outputs and not set(required_presentation_outputs).issubset(
        synthesis.presentation_outputs
    ):
        errors.append("missing_presentation_output")
    if errors:
        raise SynthesisValidationError(errors)


def deterministic_synthesis(
    results: list[SkillNodeResult],
    *,
    degradation: str | None,
    presentation_requirements: list[str] | None = None,
    completion_check: CompletionCheckResult | None = None,
) -> SkillSynthesisResult:
    limitations = [item for result in results for item in result.limitations]
    if completion_check is not None:
        limitations.extend(completion_check.gaps)
    if degradation:
        limitations.append(degradation)
    claims = [
        {
            "text": result.summary,
            "node_result_ids": [result.id],
            "source_ids": [source.id for source in result.sources],
            "recommendation": not result.sources,
        }
        for result in results
    ]
    result_sections = [f"{result.skill_id}: {result.summary}" for result in results]
    requested_sections = [
        f"{_PRESENTATION_LABELS[requirement]}：\n"
        + "\n".join(f"- {item}" for result in results for item in [*result.findings, *result.recommendations])
        for requirement in presentation_requirements or []
        if requirement in _PRESENTATION_LABELS
    ]
    return SkillSynthesisResult(
        summary="\n\n".join(result.summary for result in results),
        sections=requested_sections or result_sections,
        presentation_outputs=list(dict.fromkeys(presentation_requirements or [])),
        claims=claims,
        limitations=list(dict.fromkeys(limitations)),
        next_actions=[item for result in results for item in result.recommendations],
        artifact_ids=list(dict.fromkeys(item for result in results for item in result.artifact_ids)),
    )


class SkillSynthesisService:
    async def synthesize(
        self,
        *,
        model: Model,
        output_contract: list[str],
        results: list[SkillNodeResult],
        degradation: str | None,
        routing_result: TaskRoutingResult | None = None,
        completion_check: CompletionCheckResult | None = None,
        plan_nodes: list[SkillPlanNode] | None = None,
    ) -> tuple[SkillSynthesisResult, bool]:
        presentation_requirements = (
            list(routing_result.presentation_requirements) if routing_result is not None else []
        )
        payload = {
            "output_contract": output_contract,
            "presentation_requirements": presentation_requirements,
            "task_routing": routing_result.model_dump(mode="json") if routing_result is not None else None,
            "completion_check": completion_check.model_dump(mode="json") if completion_check is not None else None,
            "plan_nodes": [node.model_dump(mode="json") for node in plan_nodes or []],
            "node_results": [result.model_dump(mode="json") for result in results],
            "degradation": degradation,
        }
        errors: list[str] = []
        for attempt in range(2):
            agent = Agent(
                name="AgentMesh Skill Synthesis",
                instructions=_SYNTHESIS_INSTRUCTIONS,
                model=model,
                tools=[],
                output_type=SkillSynthesisResult,
            )
            request = {**payload, "repair_error_codes": errors if attempt else []}
            try:
                run = await Runner.run(
                    agent,
                    json.dumps(request, ensure_ascii=False),
                    max_turns=2,
                    run_config=RunConfig(
                        workflow_name="skill_result_synthesis",
                        trace_include_sensitive_data=False,
                    ),
                )
                synthesis = SkillSynthesisResult.model_validate(run.final_output)
                validate_synthesis(
                    synthesis,
                    results,
                    required_presentation_outputs=presentation_requirements,
                )
                return synthesis, False
            except SynthesisValidationError as error:
                errors = error.codes
            except Exception:
                errors = ["synthesis_schema_invalid"]
        return deterministic_synthesis(
            results,
            degradation=degradation,
            presentation_requirements=presentation_requirements,
            completion_check=completion_check,
        ), True


def render_synthesis(synthesis: SkillSynthesisResult) -> str:
    parts = [synthesis.summary]
    if synthesis.sections:
        parts.extend(synthesis.sections)
    if synthesis.claims:
        rendered_claims = []
        for claim in synthesis.claims:
            lineage = ", ".join([*claim.node_result_ids, *claim.source_ids])
            rendered_claims.append(f"- {claim.text} [{lineage}]")
        parts.append("结论与血缘：\n" + "\n".join(rendered_claims))
    if synthesis.limitations:
        parts.append("限制：\n" + "\n".join(f"- {item}" for item in synthesis.limitations))
    if synthesis.next_actions:
        parts.append("下一步：\n" + "\n".join(f"- {item}" for item in synthesis.next_actions))
    return "\n\n".join(part for part in parts if part.strip())
