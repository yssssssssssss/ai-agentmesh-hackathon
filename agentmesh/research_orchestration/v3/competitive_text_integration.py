"""Deterministic, non-production Competitive Text integration harness.

This module composes the isolated research-v3 planning, execution, delivery, review,
reporting, and Workbench projection seams. It uses synthetic data and in-memory
adapters only; nothing here is registered with Store, FastAPI, or a Provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from agentmesh.research_orchestration.v3.canonical import (
    canonical_json_v3_bytes,
    canonical_json_v3_sha256,
)
from agentmesh.research_orchestration.v3.catalog import CompetitiveTextCatalog, load_competitive_text_catalog
from agentmesh.research_orchestration.v3.common import ProblemGraphArtifactRefV3, SealedArtifactRefV3
from agentmesh.research_orchestration.v3.deliverable import (
    ActionRecommendationV1,
    AnalysisNodeV3,
    CompetitiveAnalysisTextPayloadV1,
    CompetitorSampleV1,
    ConclusionNodeV3,
    DifferenceV1,
    DimensionMatrixRowV1,
    DimensionValueV1,
    FactFindingV3,
    FindingGraphV3,
    ImpactV1,
    QuestionCoverageV3,
    RecommendationV3,
    ResearchDeliverableCoverageV3,
    RoadmapItemV1,
    SuccessCriterionCoverageV3,
    SummaryNodeV3,
)
from agentmesh.research_orchestration.v3.delivery_service import (
    CompetitiveDeliverableDraftV3,
    CompetitiveTextDeliverableService,
)
from agentmesh.research_orchestration.v3.evidence import EvidenceManifestV3, VerifiedArtifactContentV3
from agentmesh.research_orchestration.v3.evidence_materializer import EvidenceManifestMaterializer
from agentmesh.research_orchestration.v3.execution import (
    ActorAdapterRegistrationV3,
    ExecutionOutcome,
    ExecutionRecoveryState,
    ExecutionRecoveryStateMachine,
    HeterogeneousActorDispatcher,
    PlanInputResolver,
    RecoveryPauseReason,
    StepApprovalProofV3,
    WaveExecutionEngine,
    WaveExecutionResult,
)
from agentmesh.research_orchestration.v3.execution_plan import (
    ExecutionPlanV3,
    ExecutionPlanVersionV3,
    PlanStepV3,
)
from agentmesh.research_orchestration.v3.in_memory import (
    InMemoryArtifactReadAdapter,
    InMemoryResearchV3Repository,
)
from agentmesh.research_orchestration.v3.planning.candidates import CompetitiveTextCandidateGenerator
from agentmesh.research_orchestration.v3.planning.capabilities import CompetitiveTextCapabilityResolver
from agentmesh.research_orchestration.v3.planning.compiler import CompetitiveTextCandidateCompiler
from agentmesh.research_orchestration.v3.planning.facade import CompetitiveTextPlanningFacade
from agentmesh.research_orchestration.v3.planning.models import (
    ActorRuntimeDescriptorV3,
    CompetitiveTextPlanningBundleV3,
)
from agentmesh.research_orchestration.v3.planning.problem_graphs import (
    CompetitiveTextProblemGraphPlanner,
    DeterministicProblemGraphProposalFake,
)
from agentmesh.research_orchestration.v3.planning.requirements import (
    CompetitiveTextRequirementPlanner,
    DeterministicRequirementProposalFake,
)
from agentmesh.research_orchestration.v3.ports import ActorExecutionRequestV3, ActorExecutionResultV3
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.report_composition import CompetitiveTextReportCompositionService
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import ResearchTaskV3
from agentmesh.research_orchestration.v3.review import REVIEW_DIMENSIONS, PassedReportReviewV3, ReviewDimensionV3
from agentmesh.research_orchestration.v3.review_service import ReportReviewService, SemanticReviewResultV3
from agentmesh.research_orchestration.v3.snapshots import (
    FrozenActorV3,
    FrozenDocumentV3,
    FrozenModelPolicyV3,
    ResearchControlSnapshotV3,
)
from agentmesh.research_orchestration.v3.web_projection import (
    ResearchV3WorkbenchAggregateV1,
    WorkbenchAggregateV1,
    WorkbenchApprovalV1,
    WorkbenchAttemptV1,
    WorkbenchDeliverableV1,
    WorkbenchGateV1,
    WorkbenchProjectionProvenanceV1,
    WorkbenchReportV1,
    WorkbenchReviewV1,
    WorkbenchStepV1,
    WorkbenchWorkflowV1,
    project_verified_evidence_for_workbench,
)

_FIXED_TIME = datetime(2026, 8, 21, 9, 30, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _FIXED_TIME


class _SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def new(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}_{self._next}"


class _PlanningRepositoryAdapter:
    """Adapts the append-only repository to the planning Artifact port."""

    def __init__(self, repository: InMemoryResearchV3Repository) -> None:
        self._repository = repository

    def seal_problem_graph(self, *, run_id: str, graph: ProblemGraphV1) -> ProblemGraphArtifactRefV3:
        return self._repository.seal_problem_graph(
            run_id,
            graph,
            expected_state_version=self._repository.state_version(run_id),
        )

    def seal_control_snapshot(
        self,
        *,
        run_id: str,
        snapshot: ResearchControlSnapshotV3,
    ) -> SealedArtifactRefV3:
        return self._repository.append_control_snapshot(
            run_id,
            snapshot,
            expected_state_version=self._repository.state_version(run_id),
        )

    def read_control_snapshot(self, artifact: SealedArtifactRefV3) -> ResearchControlSnapshotV3 | None:
        return self._repository.get_control_snapshot(artifact)


def _json_schema_document(document_id: str, content: dict[str, object]) -> FrozenDocumentV3:
    content_bytes = canonical_json_v3_bytes(content)
    return FrozenDocumentV3(
        document_id=document_id,
        kind="json_schema",
        media_type="application/json",
        content_hash=canonical_json_v3_sha256(content),
        size_bytes=len(content_bytes),
        content=content,
    )


_WEB_RESEARCH_INPUT = _json_schema_document(
    "integration-web-research-input-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence", "research_goal"],
        "properties": {
            "evidence": {
                "type": ["array", "null"],
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "url", "snippet"],
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string", "minLength": 1},
                        "snippet": {"type": "string"},
                        "score": {"type": ["number", "null"]},
                        "published_date": {"type": ["string", "null"]},
                    },
                },
            },
            "research_goal": {"type": "string", "minLength": 1},
        },
    },
)
_ANALYSIS_INPUT = _json_schema_document(
    "integration-competitive-analysis-input-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence", "dimensions"],
        "properties": {
            "evidence": {"type": ["array", "object", "null"]},
            "dimensions": {
                "type": "array",
                "minItems": 2,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)
_SYNTHESIS_INPUT = _json_schema_document(
    "integration-competitive-synthesis-input-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["analysis"],
        "properties": {"analysis": {"type": ["object", "null"]}},
    },
)
_SYNTHESIS_OUTPUT = _json_schema_document(
    "integration-competitive-synthesis-output-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["text"],
        "properties": {"text": {"type": "string", "minLength": 1}},
    },
)
_REVIEW_INPUT = _json_schema_document(
    "integration-competitive-review-input-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["report"],
        "properties": {"report": {"type": ["object", "null"]}},
    },
)
_REVIEW_OUTPUT = _json_schema_document(
    "integration-competitive-review-output-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["review"],
        "properties": {"review": {"type": "object"}},
    },
)


class _DescriptorRegistry:
    def __init__(self) -> None:
        self._descriptors = {
            ("tool", "tavily-web-search"): ActorRuntimeDescriptorV3(
                actor_type="tool",
                actor_id="tavily-web-search",
                implementation_id="integration.synthetic_web_search",
                implementation_version="1",
                execution_mode="real",
                health_state="healthy",
                enabled=True,
                authorized=True,
                required_provider="tavily",
                runtime_tool_definition_id="tool_web_research",
                runtime_gateway_name="web_research",
                input_schema_document_id="source-tavily-input-schema",
                output_schema_document_id="source-tavily-output-schema",
            ),
            ("skill", "competitive-web-research"): ActorRuntimeDescriptorV3(
                actor_type="skill",
                actor_id="competitive-web-research",
                implementation_id="integration.synthetic_web_research",
                implementation_version="1",
                execution_mode="deterministic",
                health_state="healthy",
                enabled=True,
                authorized=True,
                input_schema_document_id=_WEB_RESEARCH_INPUT.document_id,
                output_schema_document_id="source-skill-result-envelope-schema",
                instruction_document_id="competitive-web-research-instructions",
                documents=(_WEB_RESEARCH_INPUT,),
            ),
            ("skill", "competitive-analysis"): ActorRuntimeDescriptorV3(
                actor_type="skill",
                actor_id="competitive-analysis",
                implementation_id="integration.synthetic_competitive_analysis",
                implementation_version="1",
                execution_mode="deterministic",
                health_state="healthy",
                enabled=True,
                authorized=True,
                input_schema_document_id=_ANALYSIS_INPUT.document_id,
                output_schema_document_id="source-skill-result-envelope-schema",
                instruction_document_id="competitive-analysis-instructions",
                documents=(_ANALYSIS_INPUT,),
            ),
            ("llm", "competitive-text-synthesis-v1"): ActorRuntimeDescriptorV3(
                actor_type="llm",
                actor_id="competitive-text-synthesis-v1",
                implementation_id="integration.synthetic_synthesis",
                implementation_version="1",
                execution_mode="deterministic",
                health_state="healthy",
                enabled=True,
                authorized=True,
                input_schema_document_id=_SYNTHESIS_INPUT.document_id,
                output_schema_document_id=_SYNTHESIS_OUTPUT.document_id,
                instruction_document_id="competitive-text-synthesis-prompt",
                documents=(_SYNTHESIS_INPUT, _SYNTHESIS_OUTPUT),
            ),
            ("reviewer", "competitive-text-quality-reviewer-v1"): ActorRuntimeDescriptorV3(
                actor_type="reviewer",
                actor_id="competitive-text-quality-reviewer-v1",
                implementation_id="integration.synthetic_reviewer",
                implementation_version="1",
                execution_mode="deterministic",
                health_state="healthy",
                enabled=True,
                authorized=True,
                input_schema_document_id=_REVIEW_INPUT.document_id,
                output_schema_document_id=_REVIEW_OUTPUT.document_id,
                instruction_document_id="competitive-analysis-review-v3",
                documents=(_REVIEW_INPUT, _REVIEW_OUTPUT),
            ),
        }

    def describe(self, actor_type: str, actor_id: str) -> ActorRuntimeDescriptorV3 | None:
        return self._descriptors.get((actor_type, actor_id))


class _OwnerApprovalAvailable:
    def can_request(
        self,
        *,
        run_id: str,
        authority: str,
        capability_type: str,
        capability_id: str,
    ) -> bool:
        del run_id, capability_type, capability_id
        return authority == "owner"


def _research_task(*, blocked: bool) -> ResearchTaskV3:
    return ResearchTaskV3.model_validate(
        {
            "schema_version": "research-task-v3",
            "task_type": "competitive_research",
            "business_domain": "productivity_software",
            "research_goal": "Compare Alpha and Beta for a product-team pilot.",
            "comparison_dimensions": ["capabilities", "limitations"],
            "target_audience": ["product_team"],
            "scope": [] if blocked else ["Alpha", "Beta"],
            "constraints": [
                {
                    "id": "constraint_public",
                    "statement": "Use synthetic public evidence only.",
                    "source": "user",
                }
            ],
            "success_criteria": [
                {
                    "id": "criterion_traceable",
                    "statement": "Every material difference is traceable.",
                }
            ],
            "expected_deliverables": ["competitive_analysis_report"],
            "assumptions": [{"key": "market", "value": "global", "editable": True}],
            "ambiguities": (
                [{"id": "ambiguity_scope", "statement": "Competitors are unknown.", "blocking": True}]
                if blocked
                else []
            ),
            "clarification_questions": (
                [
                    {
                        "key": "competitors",
                        "question": "Which competitors should be compared?",
                        "rationale": "A comparison scope is required.",
                    }
                ]
                if blocked
                else []
            ),
            "blocking_issues": [],
            "sensitivity": "public",
            "pii_detected": False,
        }
    )


def _planning_facade(
    repository: InMemoryResearchV3Repository,
) -> tuple[CompetitiveTextCatalog, CompetitiveTextPlanningFacade]:
    catalog = load_competitive_text_catalog()
    artifacts = _PlanningRepositoryAdapter(repository)
    ids = _SequentialIds()
    clock = _FixedClock()
    requirements = CompetitiveTextRequirementPlanner(
        proposal_port=DeterministicRequirementProposalFake(
            _research_task(blocked=True),
            _research_task(blocked=False),
        ),
        id_generator=ids,
        clock=clock,
    )
    problem_graphs = CompetitiveTextProblemGraphPlanner(
        proposal_port=DeterministicProblemGraphProposalFake(),
        artifacts=artifacts,
    )
    capabilities = CompetitiveTextCapabilityResolver(
        descriptors=_DescriptorRegistry(),
        approvals=_OwnerApprovalAvailable(),
        artifacts=artifacts,
        clock=clock,
        resolved_for_agent_id="integration_harness",
        model_policy=FrozenModelPolicyV3(
            requested_provider="synthetic",
            requested_model="deterministic-integration-fake",
            structured_output_mode="json_schema",
            adapter_compatibility_id="integration-harness-v1",
        ),
    )
    return catalog, CompetitiveTextPlanningFacade(
        catalog=catalog,
        requirements=requirements,
        problem_graphs=problem_graphs,
        capabilities=capabilities,
        candidates=CompetitiveTextCandidateGenerator(),
        compiler=CompetitiveTextCandidateCompiler(
            catalog=catalog,
            artifacts=artifacts,
            id_generator=ids,
            clock=clock,
        ),
    )


class _DeterministicActorFake:
    """Write synthetic verified Artifacts while honoring the frozen result envelope.

    The Tool envelope uses ``execution_mode=real`` because that is a frozen boundary
    requirement. The implementation itself remains a local fake and never calls Tavily.
    """

    def __init__(
        self,
        artifacts: InMemoryArtifactReadAdapter,
        frozen_actors: dict[tuple[str, str], FrozenActorV3],
        *,
        fail_actor_id: str | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._frozen_actors = frozen_actors
        self._fail_actor_id = fail_actor_id
        self.calls: list[tuple[str, int]] = []

    async def execute(self, request: ActorExecutionRequestV3) -> ActorExecutionResultV3:
        self.calls.append((request.step.actor_id, request.step.step_number))
        if request.step.actor_id == self._fail_actor_id:
            raise RuntimeError(f"synthetic failure for {request.step.actor_id}")
        frozen_actor = self._frozen_actors[(request.step.actor_type, request.step.actor_id)]
        content = self._content(request)
        artifact = SealedArtifactRefV3(
            artifact_id=f"artifact_actor_{request.attempt_id}_{request.step.step_number}",
            kind="actor_result",
            schema_version="actor-result-v1",
            content_hash=canonical_json_v3_sha256(content),
        )
        result = ActorExecutionResultV3(
            run_id=request.run_id,
            plan_version_id=request.plan_version_id,
            attempt_id=request.attempt_id,
            step_number=request.step.step_number,
            actor_type=request.step.actor_type,
            actor_id=request.step.actor_id,
            step_contract_hash=request.step.contract_hash,
            result_artifact=artifact,
            receipt_id=f"receipt_actor_{request.attempt_id}_{request.step.step_number}",
            implementation_id=frozen_actor.implementation_id,
            execution_mode=frozen_actor.execution_mode,
        )
        self._artifacts.append_verified_json(
            VerifiedArtifactContentV3(
                run_id=result.run_id,
                plan_version_id=result.plan_version_id,
                attempt_id=result.attempt_id,
                step_number=result.step_number,
                actor_type=result.actor_type,
                actor_id=result.actor_id,
                step_contract_hash=result.step_contract_hash,
                receipt_id=result.receipt_id,
                implementation_id=result.implementation_id,
                execution_mode=result.execution_mode,
                artifact=result.result_artifact,
                content=content,
            )
        )
        return result

    @staticmethod
    def _content(request: ActorExecutionRequestV3) -> dict[str, object]:
        if request.step.actor_type == "tool":
            output = {
                "results": [
                    {
                        "source_id": "source_alpha_docs",
                        "title": "Alpha synthetic product documentation",
                        "url": "https://alpha.example.test/product",
                        "snippet": "Alpha documents team workflows and export controls.",
                        "retrieved_at": _FIXED_TIME.isoformat(),
                        "registrable_domain": "example.test",
                        "independence_group": "alpha_docs",
                        "conflict_status": "none",
                        "risk_flags": [],
                        "truncated": False,
                        "redaction": "masked",
                    },
                    {
                        "source_id": "source_beta_docs",
                        "title": "Beta synthetic product documentation",
                        "url": "https://beta.example.test/product",
                        "snippet": "Beta documents rapid setup and a smaller control surface.",
                        "retrieved_at": _FIXED_TIME.isoformat(),
                        "registrable_domain": "example.test",
                        "independence_group": "beta_docs",
                        "conflict_status": "none",
                        "risk_flags": [],
                        "truncated": False,
                        "redaction": "masked",
                    },
                ]
            }
            return {"output": output, "redacted_output_hash": canonical_json_v3_sha256(output)}
        if request.step.actor_type == "llm":
            return {"output": {"text": "Alpha offers stronger controls; Beta offers faster setup."}}
        return {
            "output": {
                "version": "skill-output-v2",
                "status": "succeeded",
                "summary": f"Synthetic output for {request.step.actor_id}.",
                "findings": [],
                "assumptions": [],
                "limitations": ["Synthetic integration evidence only."],
                "recommendations": ["Run a bounded pilot."],
                "payload": {"comparison": "Alpha controls; Beta speed."},
            }
        }


class _DeterministicSynthesisFake:
    async def synthesize(
        self,
        *,
        requirement,
        plan,
        actor_results,
        actor_artifacts,
        evidence_manifest: EvidenceManifestV3,
    ) -> CompetitiveDeliverableDraftV3:
        if len(actor_results) != len(actor_artifacts):
            raise ValueError("synthetic synthesis requires verified coverage for every Actor result")
        evidence_ids = tuple(item.id for item in evidence_manifest.evidence)
        question_ids = tuple(dict.fromkeys(question_id for step in plan.payload.steps for question_id in step.question_ids))
        summaries = tuple(
            SummaryNodeV3(
                id=f"summary_{index}",
                finding_ids=("finding_public_difference",),
                analysis_ids=("analysis_tradeoff",),
                summary="Alpha emphasizes controls while Beta emphasizes setup speed.",
            )
            for index, _ in enumerate(question_ids, start=1)
        )
        risks = tuple(
            f"Excluded optional capability {gap.capability_id}: {gap.code}."
            for gap in plan.payload.capability_gaps
        )
        return CompetitiveDeliverableDraftV3(
            method_summary="Compared two synthetic public sources with the frozen Competitive Text method.",
            finding_graph=FindingGraphV3(
                findings=(
                    FactFindingV3(
                        id="finding_public_difference",
                        kind="fact",
                        evidence_ids=evidence_ids,
                        statement="Alpha documents more controls while Beta documents faster setup.",
                    ),
                ),
                analyses=(
                    AnalysisNodeV3(
                        id="analysis_tradeoff",
                        finding_ids=("finding_public_difference",),
                        statement="The tradeoff affects pilot governance and time to value.",
                    ),
                ),
                sub_question_summaries=summaries,
                overall_conclusions=(
                    ConclusionNodeV3(
                        id="conclusion_pilot",
                        summary_ids=tuple(item.id for item in summaries),
                        statement="Pilot Alpha when governance controls outweigh setup speed.",
                    ),
                ),
            ),
            payload=CompetitiveAnalysisTextPayloadV1(
                competitor_samples=(
                    CompetitorSampleV1(
                        id="alpha",
                        name="Alpha",
                        rationale="Synthetic in-scope competitor.",
                        evidence_ids=(evidence_ids[0],),
                    ),
                    CompetitorSampleV1(
                        id="beta",
                        name="Beta",
                        rationale="Synthetic in-scope competitor.",
                        evidence_ids=(evidence_ids[1],),
                    ),
                ),
                dimension_matrix=(
                    DimensionMatrixRowV1(
                        dimension="team adoption",
                        weight=Decimal("1"),
                        values=(
                            DimensionValueV1(
                                sample_id="alpha",
                                value="Stronger governance controls",
                                score=Decimal("4"),
                                evidence_ids=(evidence_ids[0],),
                            ),
                            DimensionValueV1(
                                sample_id="beta",
                                value="Faster initial setup",
                                score=Decimal("3"),
                                evidence_ids=(evidence_ids[1],),
                            ),
                        ),
                    ),
                ),
                differences=(
                    DifferenceV1(
                        id="difference_governance_speed",
                        dimension="team adoption",
                        statement="Alpha favors controls; Beta favors setup speed.",
                        evidence_ids=evidence_ids,
                    ),
                ),
                impacts=(
                    ImpactV1(
                        difference_id="difference_governance_speed",
                        audience="product_team",
                        statement="The team must choose between governance depth and setup speed.",
                    ),
                ),
                action_recommendations=(
                    ActionRecommendationV1(
                        id="action_pilot",
                        difference_ids=("difference_governance_speed",),
                        priority="P1",
                        statement="Run a two-week synthetic evaluation.",
                    ),
                ),
                management_summary=("Alpha is the stronger synthetic fit for a governance-led pilot.",),
                roadmap=(
                    RoadmapItemV1(
                        priority="P1",
                        statement="Run the bounded pilot.",
                        metric="Completion rate",
                        validation_method="Synthetic task review",
                    ),
                ),
                visual_evidence=(),
                screenshot_comparisons=(),
            ),
            recommendations=(
                RecommendationV3(
                    id="recommendation_pilot",
                    priority="P1",
                    statement="Pilot Alpha and measure setup cost.",
                    finding_ids=("finding_public_difference",),
                ),
            ),
            coverage=ResearchDeliverableCoverageV3(
                question_coverage=tuple(
                    QuestionCoverageV3(question_id=question_id, summary_ids=(summaries[index].id,))
                    for index, question_id in enumerate(question_ids)
                ),
                success_criterion_coverage=tuple(
                    SuccessCriterionCoverageV3(
                        success_criterion_id=criterion.id,
                        conclusion_or_recommendation_ids=("conclusion_pilot", "recommendation_pilot"),
                    )
                    for criterion in requirement.payload.success_criteria
                ),
            ),
            risks_and_open_issues=risks,
        )


class _DeterministicPassingReviewFake:
    async def review(self, **kwargs) -> SemanticReviewResultV3:
        return SemanticReviewResultV3(
            receipt_id="receipt_semantic_review_pass",
            rubric_snapshot_hash=kwargs["rubric_snapshot_hash"],
            verdict="pass",
            dimensions=tuple(
                ReviewDimensionV3(id=dimension_id, passed=True, issues=())
                for dimension_id in REVIEW_DIMENSIONS
            ),
        )


@dataclass(frozen=True, slots=True)
class PreparedCompetitiveTextRun:
    run_id: str
    selected_candidate_id: Literal["depth", "speed"]
    repository: InMemoryResearchV3Repository
    artifacts: InMemoryArtifactReadAdapter
    facade: CompetitiveTextPlanningFacade = field(repr=False)
    catalog: CompetitiveTextCatalog = field(repr=False)
    blocked: CompetitiveTextPlanningBundleV3
    ready: CompetitiveTextPlanningBundleV3
    selected_plan: ExecutionPlanVersionV3


@dataclass(frozen=True, slots=True)
class ExecutedCompetitiveTextRun:
    attempt_id: str
    execution: WaveExecutionResult
    actor_calls: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class CompletedCompetitiveTextRun:
    prepared: PreparedCompetitiveTextRun
    executed: ExecutedCompetitiveTextRun
    evidence_manifest: EvidenceManifestV3
    review: PassedReportReviewV3
    report: ReportDocumentV3
    workbench: WorkbenchAggregateV1


@dataclass(frozen=True, slots=True)
class PlanRevisionDemonstration:
    source_plan: ExecutionPlanVersionV3
    failed_attempt: ExecutedCompetitiveTextRun
    recovery: ExecutionRecoveryState
    successor_plan: ExecutionPlanVersionV3
    successor_attempt: ExecutedCompetitiveTextRun


class CompetitiveTextIntegrationHarness:
    """Explicit test harness for the full isolated Competitive Text slice."""

    async def prepare(
        self,
        *,
        run_id: str,
        candidate_id: Literal["depth", "speed"],
    ) -> PreparedCompetitiveTextRun:
        repository = InMemoryResearchV3Repository()
        artifacts = InMemoryArtifactReadAdapter()
        catalog, facade = _planning_facade(repository)
        blocked = await facade.prepare(
            run_id=run_id,
            user_request="Compare two competitors.",
        )
        repository.append_requirement(
            blocked.requirement,
            expected_state_version=repository.state_version(run_id),
        )
        ready = await facade.prepare(
            run_id=run_id,
            user_request="Compare Alpha and Beta.",
            previous_requirement=blocked.requirement,
        )
        repository.append_requirement(
            ready.requirement,
            expected_state_version=repository.state_version(run_id),
        )
        assert ready.candidates is not None
        repository.append_candidate_set(
            run_id,
            ready.requirement.id,
            ready.candidates,
            expected_state_version=repository.state_version(run_id),
        )
        selected_plan = facade.compile_selected(bundle=ready, candidate_id=candidate_id)
        repository.append_plan(
            selected_plan,
            expected_state_version=repository.state_version(run_id),
        )
        return PreparedCompetitiveTextRun(
            run_id=run_id,
            selected_candidate_id=candidate_id,
            repository=repository,
            artifacts=artifacts,
            facade=facade,
            catalog=catalog,
            blocked=blocked,
            ready=ready,
            selected_plan=selected_plan,
        )

    async def execute(
        self,
        prepared: PreparedCompetitiveTextRun,
        *,
        attempt_id: str,
        approved: bool,
        fail_actor_id: str | None = None,
        plan: ExecutionPlanVersionV3 | None = None,
    ) -> ExecutedCompetitiveTextRun:
        selected_plan = plan or prepared.selected_plan
        snapshot = prepared.repository.read_control_snapshot(
            selected_plan.payload.control_snapshot_artifact
        )
        if snapshot is None:
            raise ValueError("selected Plan control snapshot failed verified readback")
        frozen_actors = {
            (frozen.actor_type, frozen.actor_id): frozen for frozen in snapshot.actors
        }
        actor = _DeterministicActorFake(
            prepared.artifacts,
            frozen_actors,
            fail_actor_id=fail_actor_id,
        )
        dispatcher = HeterogeneousActorDispatcher(
            registrations=tuple(
                ActorAdapterRegistrationV3(
                    actor_type=frozen.actor_type,
                    actor_id=frozen.actor_id,
                    implementation_id=frozen.implementation_id,
                    implementation_version=frozen.implementation_version,
                    execution_mode=frozen.execution_mode,
                    adapter=actor,
                )
                for frozen in snapshot.actors
            ),
            control_snapshots=prepared.repository,
        )
        proofs = (
            tuple(
                StepApprovalProofV3(
                    run_id=selected_plan.run_id,
                    plan_version_id=selected_plan.id,
                    attempt_id=attempt_id,
                    step_number=step.step_number,
                    role=step.approval_role,
                    decision="approved",
                    receipt_id=f"approval_{attempt_id}_{step.step_number}",
                )
                for step in selected_plan.payload.steps
                if step.requires_approval and step.approval_role is not None
            )
            if approved
            else ()
        )
        execution = await WaveExecutionEngine(
            dispatcher,
            input_resolver=PlanInputResolver(prepared.artifacts),
        ).execute(
            plan=selected_plan,
            attempt_id=attempt_id,
            approval_proofs=proofs,
        )
        return ExecutedCompetitiveTextRun(
            attempt_id=attempt_id,
            execution=execution,
            actor_calls=tuple(actor.calls),
        )

    async def run_success(
        self,
        *,
        run_id: str,
        candidate_id: Literal["depth", "speed"],
    ) -> CompletedCompetitiveTextRun:
        prepared = await self.prepare(run_id=run_id, candidate_id=candidate_id)
        executed = await self.execute(
            prepared,
            attempt_id=f"attempt_{candidate_id}",
            approved=True,
        )
        actor_results = executed.execution.require_delivery_results()
        for result in actor_results:
            prepared.repository.append_actor_result(
                result,
                expected_state_version=prepared.repository.state_version(run_id),
            )
        manifest, evidence_artifacts = EvidenceManifestMaterializer(prepared.artifacts).materialize(
            plan=prepared.selected_plan,
            attempt_id=executed.attempt_id,
            actor_results=actor_results,
            collected_at=_FIXED_TIME,
        )
        manifest_artifact = prepared.repository.append_evidence_manifest(
            manifest,
            expected_state_version=prepared.repository.state_version(run_id),
        )
        deliverable = await CompetitiveTextDeliverableService(
            _DeterministicSynthesisFake(),
            artifacts=prepared.artifacts,
        ).create_deliverable(
            requirement=prepared.ready.requirement,
            plan=prepared.selected_plan,
            attempt_id=executed.attempt_id,
            actor_results=actor_results,
            evidence_manifest=manifest,
            evidence_manifest_artifact=manifest_artifact,
        )
        deliverable_artifact = prepared.repository.append_deliverable(
            deliverable,
            expected_state_version=prepared.repository.state_version(run_id),
        )
        assert prepared.ready.problem_graph is not None
        review = await ReportReviewService.from_catalog(
            _DeterministicPassingReviewFake(),
            prepared.catalog,
            artifacts=prepared.artifacts,
        ).review(
            requirement=prepared.ready.requirement,
            plan=prepared.selected_plan,
            problem_graph=prepared.ready.problem_graph,
            deliverable=deliverable,
            deliverable_artifact=deliverable_artifact,
            actor_results=actor_results,
            evidence_manifest=manifest,
            evidence_manifest_artifact=manifest_artifact,
            evidence_artifacts=evidence_artifacts,
            revision_round=0,
        )
        passed_review = PassedReportReviewV3.model_validate(review.model_dump(mode="python"))
        review_artifact = prepared.repository.append_review(
            passed_review,
            expected_state_version=prepared.repository.state_version(run_id),
        )
        report = CompetitiveTextReportCompositionService.from_catalog(prepared.catalog).compose(
            deliverable=deliverable,
            deliverable_artifact=deliverable_artifact,
            review=passed_review,
            review_artifact=review_artifact,
        )
        report_artifact = prepared.repository.append_report(
            report,
            expected_state_version=prepared.repository.state_version(run_id),
        )
        evidence_projection = project_verified_evidence_for_workbench(
            artifact=manifest_artifact,
            manifest=manifest,
            verified_artifacts=evidence_artifacts,
        )
        state_version = prepared.repository.state_version(run_id)
        aggregate = ResearchV3WorkbenchAggregateV1(
            schema_version="research-workbench-aggregate-v1",
            projection_kind="research-v3-current",
            orchestration_version="research-v3",
            run_id=run_id,
            workflow=WorkbenchWorkflowV1(
                state="text_report",
                state_version=state_version,
                gate=WorkbenchGateV1(kind="none", status="inactive"),
            ),
            requirement=prepared.ready.requirement,
            candidates=prepared.ready.candidates,
            selected_plan=prepared.selected_plan,
            approvals=tuple(
                WorkbenchApprovalV1(
                    gate_key=f"step_{step.step_number}_{step.approval_role}",
                    plan_version_id=prepared.selected_plan.id,
                    role=step.approval_role,
                    decision="approved",
                    receipt_id=f"approval_{executed.attempt_id}_{step.step_number}",
                )
                for step in prepared.selected_plan.payload.steps
                if step.requires_approval and step.approval_role is not None
            ),
            attempt=WorkbenchAttemptV1(
                attempt_id=executed.attempt_id,
                run_id=run_id,
                plan_version_id=prepared.selected_plan.id,
                status="completed",
                steps=tuple(
                    WorkbenchStepV1(
                        step_number=step.step_number,
                        actor_type=step.actor_type,
                        actor_id=step.actor_id,
                        step_contract_hash=step.contract_hash,
                        expected_outputs=step.expected_outputs,
                        status="succeeded",
                        result=actor_results[index],
                    )
                    for index, step in enumerate(prepared.selected_plan.payload.steps)
                ),
            ),
            recovery=None,
            evidence=evidence_projection,
            deliverable=WorkbenchDeliverableV1(
                artifact=deliverable_artifact,
                content=deliverable,
            ),
            review=WorkbenchReviewV1(
                artifact=review_artifact,
                content=passed_review,
            ),
            report=WorkbenchReportV1(
                artifact=report_artifact,
                content=report,
            ),
            provenance=WorkbenchProjectionProvenanceV1(
                source_kind="isolated_fixture",
                projection_schema_version="research-workbench-aggregate-v1",
                projected_at=_FIXED_TIME,
                source_state_version=state_version,
                baseline_state_id="text_report",
            ),
        )
        workbench = WorkbenchAggregateV1.model_validate(aggregate.model_dump(mode="python"))
        return CompletedCompetitiveTextRun(
            prepared=prepared,
            executed=executed,
            evidence_manifest=manifest,
            review=passed_review,
            report=report,
            workbench=workbench,
        )

    async def demonstrate_optional_plan_revision(self, *, run_id: str) -> PlanRevisionDemonstration:
        prepared = await self.prepare(run_id=run_id, candidate_id="depth")
        source_plan = _make_optional_plan(prepared.selected_plan, optional_step_number=2, version=2)
        prepared.repository.append_plan(
            source_plan,
            expected_state_version=prepared.repository.state_version(run_id),
        )
        failed_attempt = await self.execute(
            prepared,
            attempt_id="attempt_optional_failure",
            approved=True,
            fail_actor_id="competitive-web-research",
            plan=source_plan,
        )
        if failed_attempt.execution.outcome != ExecutionOutcome.PLAN_REVISION_REQUIRED:
            raise RuntimeError("synthetic optional failure did not request a Plan revision")
        for result in failed_attempt.execution.actor_results:
            prepared.repository.append_actor_result(
                result,
                expected_state_version=prepared.repository.state_version(run_id),
            )
        successor_plan = prepared.facade.compile_selected(
            bundle=prepared.ready,
            candidate_id="speed",
            plan_version=3,
        )
        prepared.repository.append_plan(
            successor_plan,
            expected_state_version=prepared.repository.state_version(run_id),
        )
        recovery = ExecutionRecoveryStateMachine.pause(
            ExecutionRecoveryStateMachine.start(
                plan_version_id=source_plan.id,
                attempt_id=failed_attempt.attempt_id,
            ),
            step_number=2,
            required=False,
            reason=RecoveryPauseReason.FAILED,
        )
        recovery = ExecutionRecoveryStateMachine.skip(
            recovery,
            new_plan_version_id=successor_plan.id,
            new_attempt_id="attempt_revised_speed",
        )
        recovery = ExecutionRecoveryStateMachine.begin_successor(recovery)
        successor_attempt = await self.execute(
            prepared,
            attempt_id=recovery.attempt_id,
            approved=True,
            plan=successor_plan,
        )
        for result in successor_attempt.execution.require_delivery_results():
            prepared.repository.append_actor_result(
                result,
                expected_state_version=prepared.repository.state_version(run_id),
            )
        return PlanRevisionDemonstration(
            source_plan=source_plan,
            failed_attempt=failed_attempt,
            recovery=recovery,
            successor_plan=successor_plan,
            successor_attempt=successor_attempt,
        )


def _make_optional_plan(
    source: ExecutionPlanVersionV3,
    *,
    optional_step_number: int,
    version: int,
) -> ExecutionPlanVersionV3:
    steps: list[PlanStepV3] = []
    for step in source.payload.steps:
        values = step.model_dump(mode="python", exclude={"contract_hash"})
        if step.step_number == optional_step_number:
            values["required"] = False
        values["contract_hash"] = canonical_json_v3_sha256(values)
        steps.append(PlanStepV3.model_validate(values))
    payload_values = source.payload.model_dump(mode="python")
    payload_values["steps"] = steps
    payload = ExecutionPlanV3.model_validate(payload_values)
    return ExecutionPlanVersionV3(
        id=f"plan_optional_{version}",
        run_id=source.run_id,
        requirement_version_id=source.requirement_version_id,
        version=version,
        schema_version="execution-plan-v3",
        plan_hash=canonical_json_v3_sha256(payload),
        payload=payload,
        created_at=_FIXED_TIME,
    )
