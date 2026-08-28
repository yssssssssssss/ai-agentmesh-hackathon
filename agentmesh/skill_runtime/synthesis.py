from __future__ import annotations

import json
import re

from agents import Agent, ModelSettings, RunConfig, Runner
from agents.models.interface import Model

from agentmesh.models import SkillNodeResult, SkillPlanNode, SkillSynthesisResult
from agentmesh.task_routing.contracts import CompletionCheckResult, TaskRoutingResult

_SYNTHESIS_INSTRUCTIONS = """Synthesize only the supplied normalized Skill node results.
Do not add facts, sources, tool output, or hidden reasoning. Every claim must cite existing node result IDs.
Factual claims must also cite existing source IDs. Advice without a source must set recommendation=true.
Keep technical IDs only in the structured claim fields; never print them in summary, sections, limitations,
or next_actions. Do not repeat complete node deliverables because the runtime appends them deterministically.
Write summary as a concise executive summary. Node deliverable_markdown content is preserved verbatim by the
runtime, so do not replace it with labels or summaries. Use sections only for substantive cross-cutting analysis
requested by presentation_requirements; never invent content to fill a requested section.
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
_DELIVERABLE_LABELS = {
    "competitive_analysis": "竞品分析",
    "experience_metrics": "体验指标",
    "interview_guide": "访谈提纲",
    "measurement_plan": "度量计划",
    "research_evidence": "研究证据",
    "research_plan": "研究计划",
    "survey": "问卷",
    "synthesis": "综合结论",
    "usability_test_plan": "可用性测试方案",
}
_INTERNAL_RESULT_ID_PATTERN = re.compile(r"\[?\bnode_result_[A-Za-z0-9_.:-]+\b\]?")
_SYNTHESIS_MAX_TOKENS = 4_096


class SynthesisValidationError(ValueError):
    def __init__(self, codes: list[str]):
        self.codes = list(dict.fromkeys(codes))
        super().__init__(", ".join(self.codes))


def _strip_internal_result_ids(text: str) -> str:
    return _INTERNAL_RESULT_ID_PATTERN.sub("", text).strip()


def _legacy_deliverable_body(result: SkillNodeResult) -> str:
    """Keep old persisted results readable without pretending they contain a full deliverable."""
    parts = [result.summary.strip()]
    if result.findings:
        parts.append("### 主要发现\n" + "\n".join(f"- {item}" for item in result.findings))
    if result.recommendations:
        parts.append("### 建议\n" + "\n".join(f"- {item}" for item in result.recommendations))
    return "\n\n".join(part for part in parts if part)


def _node_section_title(node: SkillPlanNode | None, result: SkillNodeResult) -> str:
    output_name = node.output_contract[0] if node is not None and node.output_contract else ""
    return _DELIVERABLE_LABELS.get(output_name, output_name.replace("_", " ").strip() or result.skill_id)


def compose_report_sections(
    results: list[SkillNodeResult],
    *,
    plan_nodes: list[SkillPlanNode] | None = None,
) -> list[str]:
    """Preserve complete node deliverables in approved DAG order."""
    results_by_node_id = {result.node_id: result for result in results}
    ordered: list[tuple[SkillPlanNode | None, SkillNodeResult]] = []
    seen_result_ids: set[str] = set()
    for node in plan_nodes or []:
        result = results_by_node_id.get(node.id)
        if result is not None:
            ordered.append((node, result))
            seen_result_ids.add(result.id)
    ordered.extend((None, result) for result in results if result.id not in seen_result_ids)

    return [
        f"## {_node_section_title(node, result)}\n\n"
        f"{result.deliverable_markdown.strip() or _legacy_deliverable_body(result)}"
        for node, result in ordered
    ]


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
    plan_nodes: list[SkillPlanNode] | None = None,
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
    result_sections = compose_report_sections(results, plan_nodes=plan_nodes)
    requested_sections = [
        f"{_PRESENTATION_LABELS[requirement]}：\n"
        + "\n".join(f"- {item}" for result in results for item in [*result.findings, *result.recommendations])
        for requirement in presentation_requirements or []
        if requirement in _PRESENTATION_LABELS
    ]
    return SkillSynthesisResult(
        summary="\n\n".join(result.summary for result in results),
        sections=[*requested_sections, *result_sections],
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
            "node_results": [
                result.model_dump(mode="json", exclude={"deliverable_markdown"})
                for result in results
            ],
            "degradation": degradation,
        }
        errors: list[str] = []
        for attempt in range(2):
            agent = Agent(
                name="AgentMesh Skill Synthesis",
                instructions=_SYNTHESIS_INSTRUCTIONS,
                model=model,
                model_settings=ModelSettings(max_tokens=_SYNTHESIS_MAX_TOKENS),
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
                synthesis.summary = _strip_internal_result_ids(synthesis.summary)
                synthesis.sections = compose_report_sections(results, plan_nodes=plan_nodes)
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
            plan_nodes=plan_nodes,
        ), True


def render_synthesis(synthesis: SkillSynthesisResult) -> str:
    parts = [f"# 最终报告\n\n## 执行摘要\n\n{synthesis.summary}"]
    if synthesis.sections:
        parts.extend(synthesis.sections)
    if synthesis.limitations:
        parts.append("## 限制与已知边界\n\n" + "\n".join(f"- {item}" for item in synthesis.limitations))
    if synthesis.next_actions:
        parts.append("## 下一步建议\n\n" + "\n".join(f"- {item}" for item in synthesis.next_actions))
    return _strip_internal_result_ids("\n\n".join(part for part in parts if part.strip()))
