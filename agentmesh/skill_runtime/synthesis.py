from __future__ import annotations

import json

from agents import Agent, RunConfig, Runner
from agents.models.interface import Model

from agentmesh.models import SkillNodeResult, SkillSynthesisResult

_SYNTHESIS_INSTRUCTIONS = """Synthesize only the supplied normalized Skill node results.
Do not add facts, sources, tool output, or hidden reasoning. Every claim must cite existing node result IDs.
Factual claims must also cite existing source IDs. Advice without a source must set recommendation=true.
Preserve limitations and degradation. Return the required structured schema.
"""


class SynthesisValidationError(ValueError):
    def __init__(self, codes: list[str]):
        self.codes = list(dict.fromkeys(codes))
        super().__init__(", ".join(self.codes))


def validate_synthesis(synthesis: SkillSynthesisResult, results: list[SkillNodeResult]) -> None:
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
    if errors:
        raise SynthesisValidationError(errors)


def deterministic_synthesis(
    results: list[SkillNodeResult],
    *,
    degradation: str | None,
) -> SkillSynthesisResult:
    limitations = [item for result in results for item in result.limitations]
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
    return SkillSynthesisResult(
        summary="\n\n".join(result.summary for result in results),
        sections=[f"{result.skill_id}: {result.summary}" for result in results],
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
    ) -> tuple[SkillSynthesisResult, bool]:
        payload = {
            "output_contract": output_contract,
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
                validate_synthesis(synthesis, results)
                return synthesis, False
            except SynthesisValidationError as error:
                errors = error.codes
            except Exception:
                errors = ["synthesis_schema_invalid"]
        return deterministic_synthesis(results, degradation=degradation), True


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
