"""Tool-free model adapters for DeepSearch synthesis and semantic review."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from agents import Agent, RunConfig, Runner
from agents.models.interface import Model

from agentmesh.artifacts import DeepSearchEvidenceManifestV1, TrustedEvidenceEnvelopeV1
from agentmesh.deepsearch.contracts import ProblemGraphV1, RequirementVersionV1
from agentmesh.deepsearch.reporting import (
    DeepSearchReportingError,
    materialize_deepsearch_review,
    materialize_deepsearch_synthesis,
)
from agentmesh.models import (
    AgentRun,
    Artifact,
    DeepSearchReportReviewDraftV1,
    DeepSearchReviewOutcomeV1,
    DeepSearchSynthesisDraftV1,
    DeepSearchSynthesisV1,
    SkillNodeResult,
    SkillPlan,
)

_SYNTHESIS_INSTRUCTIONS = """Create only structured DeepSearch claim drafts from the supplied evidence.
Every factual or recommendation claim must cite existing evidence_item_ids and their exact node_result_ids,
source_ids, question_ids, and success_criterion_ids. Never invent IDs, sources, evidence, or report prose.
Do not output claim IDs; the server owns identity. If repair_error_codes is non-empty, correct those errors.
"""

_REVIEW_INSTRUCTIONS = """Review the supplied DeepSearch claims against the frozen requirement and evidence.
Return only pass, revise, or block plus existing claim/section IDs and stable limitation codes.
Do not rewrite claims, invent IDs, add prose, or alter lineage. A non-pass verdict must identify an actionable
claim ID, section ID, or limitation code. If repair_error_codes is non-empty, correct those errors.
"""


def _evidence_projection(
    *,
    manifest: DeepSearchEvidenceManifestV1,
    evidence_artifacts: Mapping[str, Artifact],
) -> list[dict[str, object]]:
    projection: list[dict[str, object]] = []
    for item in manifest.items:
        artifact = evidence_artifacts.get(item.evidence_artifact_id)
        if artifact is None:
            raise DeepSearchReportingError()
        try:
            envelope = TrustedEvidenceEnvelopeV1.model_validate_json(artifact.content)
        except (TypeError, ValueError) as error:
            raise DeepSearchReportingError() from error
        projection.append(
            {
                **item.model_dump(mode="json"),
                "normalized_reference": envelope.normalized_reference,
                "retrieved_at": envelope.retrieved_at.isoformat(),
                "excerpt": envelope.excerpt,
                "content_hash": envelope.content_hash,
            }
        )
    return projection


class DeepSearchSynthesisService:
    """Produce strict claim drafts; callers own budget and fallback policy."""

    async def synthesize(
        self,
        *,
        model: Model,
        run: AgentRun,
        plan: SkillPlan,
        requirement: RequirementVersionV1,
        graph: ProblemGraphV1,
        results: Sequence[SkillNodeResult],
        manifest: DeepSearchEvidenceManifestV1,
        evidence_artifacts: Mapping[str, Artifact],
        revision_count: int,
        prior_review: DeepSearchReviewOutcomeV1 | None = None,
    ) -> DeepSearchSynthesisV1:
        payload = {
            "requirement": requirement.payload.model_dump(mode="json"),
            "problem_graph": graph.model_dump(mode="json"),
            "plan": {
                "id": plan.id,
                "version": plan.version,
                "nodes": [
                    {
                        "id": node.id,
                        "question_ids": node.question_ids,
                        "output_contract": node.output_contract,
                    }
                    for node in plan.nodes
                ],
            },
            "node_results": [result.model_dump(mode="json") for result in results],
            "evidence": _evidence_projection(
                manifest=manifest,
                evidence_artifacts=evidence_artifacts,
            ),
            "revision_count": revision_count,
            "prior_review": (
                prior_review.model_dump(mode="json") if prior_review is not None else None
            ),
        }
        errors: list[str] = []
        last_error: Exception | None = None
        for attempt in range(2):
            agent = Agent(
                name="AgentMesh DeepSearch Synthesis",
                instructions=_SYNTHESIS_INSTRUCTIONS,
                model=model,
                tools=[],
                output_type=DeepSearchSynthesisDraftV1,
            )
            try:
                response = await Runner.run(
                    agent,
                    json.dumps(
                        {**payload, "repair_error_codes": errors if attempt else []},
                        ensure_ascii=False,
                    ),
                    max_turns=2,
                    run_config=RunConfig(
                        workflow_name="deepsearch_synthesis",
                        trace_include_sensitive_data=False,
                    ),
                )
                draft = DeepSearchSynthesisDraftV1.model_validate(response.final_output)
                return materialize_deepsearch_synthesis(
                    run=run,
                    plan=plan,
                    revision_count=revision_count,
                    drafts=draft.claims,
                )
            except DeepSearchReportingError as error:
                last_error = error
                errors = [error.code]
            except Exception as error:
                if getattr(error, "code", "") in {
                    "deepsearch_budget_exhausted",
                    "deepsearch_recovery_exhausted",
                }:
                    raise
                last_error = error
                errors = ["deepsearch_synthesis_schema_invalid"]
        raise DeepSearchReportingError("deepsearch_synthesis_invalid") from last_error


class DeepSearchReviewService:
    """Produce a structured semantic verdict over one immutable synthesis."""

    async def review(
        self,
        *,
        model: Model,
        run: AgentRun,
        plan: SkillPlan,
        requirement: RequirementVersionV1,
        graph: ProblemGraphV1,
        synthesis: DeepSearchSynthesisV1,
        manifest: DeepSearchEvidenceManifestV1,
        evidence_artifacts: Mapping[str, Artifact],
        reviewed_at: datetime,
    ) -> DeepSearchReviewOutcomeV1:
        payload = {
            "requirement": requirement.payload.model_dump(mode="json"),
            "problem_graph": graph.model_dump(mode="json"),
            "sections": [
                {"section_id": question.id, "heading": question.question}
                for question in graph.questions
            ],
            "synthesis": synthesis.model_dump(mode="json"),
            "evidence": _evidence_projection(
                manifest=manifest,
                evidence_artifacts=evidence_artifacts,
            ),
        }
        errors: list[str] = []
        last_error: Exception | None = None
        for attempt in range(2):
            agent = Agent(
                name="AgentMesh DeepSearch Review",
                instructions=_REVIEW_INSTRUCTIONS,
                model=model,
                tools=[],
                output_type=DeepSearchReportReviewDraftV1,
            )
            try:
                response = await Runner.run(
                    agent,
                    json.dumps(
                        {**payload, "repair_error_codes": errors if attempt else []},
                        ensure_ascii=False,
                    ),
                    max_turns=2,
                    run_config=RunConfig(
                        workflow_name="deepsearch_review",
                        trace_include_sensitive_data=False,
                    ),
                )
                draft = DeepSearchReportReviewDraftV1.model_validate(response.final_output)
                return materialize_deepsearch_review(
                    run=run,
                    plan=plan,
                    requirement=requirement,
                    graph=graph,
                    synthesis=synthesis,
                    draft=draft,
                    reviewer_type="model",
                    reviewed_at=reviewed_at,
                )
            except DeepSearchReportingError as error:
                last_error = error
                errors = [error.code]
            except Exception as error:
                if getattr(error, "code", "") in {
                    "deepsearch_budget_exhausted",
                    "deepsearch_recovery_exhausted",
                }:
                    raise
                last_error = error
                errors = ["deepsearch_review_schema_invalid"]
        raise DeepSearchReportingError("deepsearch_review_invalid") from last_error
