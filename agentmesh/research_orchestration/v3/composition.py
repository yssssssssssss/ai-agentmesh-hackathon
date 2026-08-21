"""Dormant, provider-free composition for research-v3 preview planning."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import uuid4

from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatMessage,
    ChatRole,
    Scope,
    SkillDefinition,
    SkillOrchestrationRequestMode,
    User,
    now_utc,
)
from agentmesh.provider_status import redact_sensitive_text
from agentmesh.research_orchestration.current import (
    ResearchRolloutDecision,
    ResearchRunCreationCoordinator,
)
from agentmesh.research_orchestration.v3.adapter_registry import (
    COMPETITIVE_TEXT_ADAPTER_DECLARATIONS_V3,
)
from agentmesh.research_orchestration.v3.api import (
    ResearchV3AggregateReadRequest,
    ResearchV3CommandType,
    ResearchV3MutationReceipt,
    ResearchV3MutationRequest,
    ResearchV3OwnerScope,
    ResearchV3ReviseRequest,
)
from agentmesh.research_orchestration.v3.canonical import (
    canonical_json_v3_bytes,
    canonical_json_v3_sha256,
)
from agentmesh.research_orchestration.v3.catalog import (
    load_competitive_text_catalog,
)
from agentmesh.research_orchestration.v3.common import (
    ProblemGraphArtifactRefV3,
    SealedArtifactRefV3,
)
from agentmesh.research_orchestration.v3.execution_plan import (
    CapabilityResolutionV3,
    ExecutionPlanVersionV3,
    PlanCandidateSetV3,
)
from agentmesh.research_orchestration.v3.planning.candidates import CompetitiveTextCandidateGenerator
from agentmesh.research_orchestration.v3.planning.capabilities import CompetitiveTextCapabilityResolver
from agentmesh.research_orchestration.v3.planning.compiler import CompetitiveTextCandidateCompiler
from agentmesh.research_orchestration.v3.planning.facade import CompetitiveTextPlanningFacade
from agentmesh.research_orchestration.v3.planning.models import (
    ActorRuntimeDescriptorV3,
    PlanningModelCallReceiptV3,
    RequirementProposalRequestV3,
    RequirementProposalV3,
)
from agentmesh.research_orchestration.v3.planning.problem_graphs import (
    CompetitiveTextProblemGraphPlanner,
    DeterministicProblemGraphProposalFake,
)
from agentmesh.research_orchestration.v3.planning.requirements import (
    CompetitiveTextRequirementPlanner,
    requirement_context_manifest_hash,
)
from agentmesh.research_orchestration.v3.ports import CandidateCompilationRequestV3
from agentmesh.research_orchestration.v3.preview_workflow import (
    PreviewPlanningMutationV3,
    ResearchV3PreviewWorkflow,
)
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.repository_projector import ResearchV3RepositoryProjector
from agentmesh.research_orchestration.v3.requirement import (
    ClarificationQuestionV3,
    RequirementVersionV3,
    ResearchAmbiguityV3,
    ResearchAssumptionV3,
    ResearchConstraintV3,
    ResearchTaskV3,
    SuccessCriterionV3,
)
from agentmesh.research_orchestration.v3.snapshots import (
    FrozenDocumentV3,
    FrozenModelPolicyV3,
    ResearchControlSnapshotV3,
)
from agentmesh.research_orchestration.v3.sqlite_repository import (
    PreviewRecordAppendV3,
    RepositoryScopeV3,
    SQLiteResearchV3Repository,
    _sealed_ref,
)
from agentmesh.store import SQLiteStore

_SCOPE_SPLIT = re.compile(r"\s*(?:,|，|、|\band\b|\bvs\.?\b|和|与)\s*", re.IGNORECASE)
_ENGLISH_COMPARE = re.compile(
    r"(?i)(?:compare|comparison of|versus)\s+([^\n,.;]{1,80}?)\s+(?:and|vs\.?)\s+([^\n,.;]{1,80})"
)
_CHINESE_COMPARE = re.compile(r"(?:对比|比较|分析)\s*([^，。；\n]{1,60}?)\s*(?:和|与|、|vs\.?)\s*([^，。；\n]{1,60})", re.IGNORECASE)
_CLARIFICATION_SCOPE = re.compile(r"(?im)^(?:competitors|竞品|竞争产品)\s*[:：]\s*(.+)$")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


class _Clock:
    def now(self) -> datetime:
        return now_utc()


class _Ids:
    def new(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:24]}"


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


class _DeterministicPreviewRequirementProposal:
    """Local structured proposal used only for preview planning; it calls no model."""

    @staticmethod
    def _scope(value: str, previous: RequirementVersionV3 | None) -> tuple[str, ...]:
        clarification = _CLARIFICATION_SCOPE.search(value)
        candidates: list[str] = []
        if clarification is not None:
            candidates.extend(_SCOPE_SPLIT.split(clarification.group(1).strip()))
        for pattern in (_ENGLISH_COMPARE, _CHINESE_COMPARE):
            match = pattern.search(value)
            if match is not None:
                candidates.extend((match.group(1), match.group(2)))
                break
        normalized = tuple(
            dict.fromkeys(
                item.strip(" \t:：()（）[]")[:1000]
                for item in candidates
                if item.strip(" \t:：()（）[]")
            )
        )
        if len(normalized) >= 2:
            return normalized[:20]
        if previous is not None and previous.payload.scope:
            return previous.payload.scope
        return ()

    async def propose(self, request: RequirementProposalRequestV3) -> RequirementProposalV3:
        raw = request.user_request.strip()
        redacted = redact_sensitive_text(raw)
        redacted = _EMAIL.sub("[REDACTED_EMAIL]", redacted)
        redacted = _PHONE.sub("[REDACTED_PHONE]", redacted)
        scope = self._scope(redacted, request.previous)
        blocked = len(scope) < 2
        prior_assumptions = request.previous.payload.assumptions if request.previous is not None else ()
        task = ResearchTaskV3(
            schema_version="research-task-v3",
            task_type="competitive_research",
            business_domain=(
                request.previous.payload.business_domain
                if request.previous is not None
                else "competitive_product_research"
            ),
            research_goal=redacted[:4000],
            comparison_dimensions=("capabilities", "applicable_scenarios", "limitations"),
            target_audience=("product_team",),
            scope=scope,
            constraints=(
                ResearchConstraintV3(
                    id="constraint_public_sources",
                    statement="Use public-source evidence and disclose evidence gaps.",
                    source="policy",
                ),
            ),
            success_criteria=(
                SuccessCriterionV3(
                    id="criterion_traceable_differences",
                    statement="Every material competitive difference is traceable to evidence.",
                ),
                SuccessCriterionV3(
                    id="criterion_actionable_recommendation",
                    statement="Recommendations identify applicable scenarios, limitations, and gaps.",
                ),
            ),
            expected_deliverables=("competitive_analysis_report",),
            assumptions=prior_assumptions
            or (
                ResearchAssumptionV3(
                    key="preview_only",
                    value="No external Provider is executed during preview planning.",
                    editable=False,
                ),
            ),
            ambiguities=(
                (
                    ResearchAmbiguityV3(
                        id="ambiguity_competitor_scope",
                        statement="At least two concrete competitors are required.",
                        blocking=True,
                    ),
                )
                if blocked
                else ()
            ),
            clarification_questions=(
                (
                    ClarificationQuestionV3(
                        key="competitors",
                        question="Which two or more competitors should be compared?",
                        rationale="A concrete comparison scope is required before planning.",
                    ),
                )
                if blocked
                else ()
            ),
            blocking_issues=(),
            sensitivity="internal" if "内部" in redacted else "public",
            pii_detected=bool(_EMAIL.search(raw) or _PHONE.search(raw)),
        )
        context_hash = requirement_context_manifest_hash(request)
        output_hash = canonical_json_v3_sha256(task)
        call_hash = canonical_json_v3_sha256(
            {
                "stage": "requirement_refinement",
                "context": context_hash,
                "output": output_hash,
            }
        )
        receipt = PlanningModelCallReceiptV3(
            id=f"receipt_requirement_{call_hash[:24]}",
            run_id=request.run_id,
            stage="requirement_refinement",
            model_name="deterministic-preview-requirement",
            model_version="1",
            prompt_hash=canonical_json_v3_sha256(
                {"stage": "requirement_refinement", "schema": "research-task-v3"}
            ),
            trace_id=f"trace_requirement_{call_hash[24:48]}",
            context_manifest_hash=context_hash,
            output_hash=output_hash,
        )
        return RequirementProposalV3(task=task, receipt=receipt)


def _schema_document(document_id: str, content: dict[str, object]) -> FrozenDocumentV3:
    return FrozenDocumentV3(
        document_id=document_id,
        kind="json_schema",
        media_type="application/json",
        content_hash=canonical_json_v3_sha256(content),
        size_bytes=len(canonical_json_v3_bytes(content)),
        content=content,
    )


_WEB_INPUT = _schema_document(
    "preview-web-research-input-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence", "research_goal"],
        "properties": {
            "evidence": {"type": ["array", "null"]},
            "research_goal": {"type": "string", "minLength": 1},
        },
    },
)
_ANALYSIS_INPUT = _schema_document(
    "preview-competitive-analysis-input-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["evidence", "dimensions"],
        "properties": {
            "evidence": {"type": ["array", "object", "null"]},
            "dimensions": {"type": "array", "items": {"type": "string"}},
        },
    },
)
_SYNTHESIS_INPUT = _schema_document(
    "preview-competitive-synthesis-input-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["analysis"],
        "properties": {"analysis": {"type": ["object", "null"]}},
    },
)
_SYNTHESIS_OUTPUT = _schema_document(
    "preview-competitive-synthesis-output-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["text"],
        "properties": {"text": {"type": "string", "minLength": 1}},
    },
)
_REVIEW_INPUT = _schema_document(
    "preview-competitive-review-input-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["report"],
        "properties": {"report": {"type": ["object", "null"]}},
    },
)
_REVIEW_OUTPUT = _schema_document(
    "preview-competitive-review-output-schema",
    {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["review"],
        "properties": {"review": {"type": "object"}},
    },
)


class _PreviewDescriptorRegistry:
    def __init__(self) -> None:
        declarations = {
            (item.actor_type, item.actor_id): item
            for item in COMPETITIVE_TEXT_ADAPTER_DECLARATIONS_V3
        }
        self._descriptors = {
            ("tool", "tavily-web-search"): ActorRuntimeDescriptorV3(
                actor_type="tool",
                actor_id="tavily-web-search",
                implementation_id=declarations[("tool", "tavily-web-search")].implementation_id,
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
                implementation_id=declarations[("skill", "competitive-web-research")].implementation_id,
                implementation_version="1",
                execution_mode="model",
                health_state="healthy",
                enabled=True,
                authorized=True,
                input_schema_document_id=_WEB_INPUT.document_id,
                output_schema_document_id="source-skill-result-envelope-schema",
                instruction_document_id="competitive-web-research-instructions",
                documents=(_WEB_INPUT,),
            ),
            ("skill", "competitive-analysis"): ActorRuntimeDescriptorV3(
                actor_type="skill",
                actor_id="competitive-analysis",
                implementation_id=declarations[("skill", "competitive-analysis")].implementation_id,
                implementation_version="1",
                execution_mode="model",
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
                implementation_id=declarations[("llm", "competitive-text-synthesis-v1")].implementation_id,
                implementation_version="1",
                execution_mode="model",
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
                implementation_id=declarations[("reviewer", "competitive-text-quality-reviewer-v1")].implementation_id,
                implementation_version="1",
                execution_mode="model",
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


class _StagedPlanningArtifacts:
    def __init__(self, repository: SQLiteResearchV3Repository) -> None:
        self._repository = repository
        self.records: list[PreviewRecordAppendV3] = []
        self._snapshots: dict[str, ResearchControlSnapshotV3] = {}

    def seal_problem_graph(self, *, run_id: str, graph) -> ProblemGraphArtifactRefV3:  # noqa: ANN001
        artifact = ProblemGraphArtifactRefV3.model_validate(
            _sealed_ref(
                run_id=run_id,
                kind="problem_graph",
                schema_version="problem-graph-v1",
                value=graph,
            ).model_dump(mode="python")
        )
        self.records.append(
            PreviewRecordAppendV3(
                record_kind="problem_graph",
                natural_key=artifact.artifact_id,
                schema_version="problem-graph-v1",
                value=graph,
                requirement_version_id=graph.requirement_version_id,
                artifact=artifact,
            )
        )
        return artifact

    def seal_control_snapshot(
        self,
        *,
        run_id: str,
        snapshot: ResearchControlSnapshotV3,
    ) -> SealedArtifactRefV3:
        artifact = _sealed_ref(
            run_id=run_id,
            kind="research_control_snapshot",
            schema_version="research-control-snapshot-v3",
            value=snapshot,
        )
        self._snapshots[artifact.artifact_id] = snapshot
        self.records.append(
            PreviewRecordAppendV3(
                record_kind="control_snapshot",
                natural_key=artifact.artifact_id,
                schema_version="research-control-snapshot-v3",
                value=snapshot,
                artifact=artifact,
            )
        )
        return artifact

    def read_control_snapshot(
        self,
        artifact: SealedArtifactRefV3,
    ) -> ResearchControlSnapshotV3 | None:
        return self._snapshots.get(artifact.artifact_id) or self._repository.get_control_snapshot(artifact)


class PreviewPlanningEngineV3:
    def __init__(
        self,
        repository: SQLiteResearchV3Repository,
        *,
        resolved_for_agent_id: str,
    ) -> None:
        self._repository = repository
        self._catalog = load_competitive_text_catalog()
        self._ids = _Ids()
        self._clock = _Clock()
        self._resolved_for_agent_id = resolved_for_agent_id

    def _components(self, artifacts: _StagedPlanningArtifacts):
        requirements = CompetitiveTextRequirementPlanner(
            proposal_port=_DeterministicPreviewRequirementProposal(),
            id_generator=self._ids,
            clock=self._clock,
        )
        problem_graphs = CompetitiveTextProblemGraphPlanner(
            proposal_port=DeterministicProblemGraphProposalFake(),
            artifacts=artifacts,
        )
        capabilities = CompetitiveTextCapabilityResolver(
            descriptors=_PreviewDescriptorRegistry(),
            approvals=_OwnerApprovalAvailable(),
            artifacts=artifacts,
            clock=self._clock,
            resolved_for_agent_id=self._resolved_for_agent_id,
            model_policy=FrozenModelPolicyV3(
                requested_provider="preview_disabled",
                requested_model="preview_no_provider",
                structured_output_mode="json_schema",
                adapter_compatibility_id="research-v3-preview-no-provider:v1",
            ),
        )
        candidates = CompetitiveTextCandidateGenerator()
        compiler = CompetitiveTextCandidateCompiler(
            catalog=self._catalog,
            artifacts=artifacts,
            id_generator=self._ids,
            clock=self._clock,
        )
        facade = CompetitiveTextPlanningFacade(
            catalog=self._catalog,
            requirements=requirements,
            problem_graphs=problem_graphs,
            capabilities=capabilities,
            candidates=candidates,
            compiler=compiler,
        )
        return facade, problem_graphs, capabilities, candidates, compiler

    @staticmethod
    def _requirement_record(requirement: RequirementVersionV3) -> PreviewRecordAppendV3:
        return PreviewRecordAppendV3(
            record_kind="requirement",
            natural_key=requirement.id,
            schema_version="research-task-v3",
            value=requirement,
            sequence_number=requirement.version,
            requirement_version_id=requirement.id,
        )

    @staticmethod
    def _candidate_record(
        requirement: RequirementVersionV3,
        candidates: PlanCandidateSetV3,
    ) -> PreviewRecordAppendV3:
        return PreviewRecordAppendV3(
            record_kind="candidate_set",
            natural_key=requirement.id,
            schema_version="plan-candidates-v3",
            value=candidates,
            requirement_version_id=requirement.id,
        )

    @staticmethod
    def _plan_record(plan: ExecutionPlanVersionV3) -> PreviewRecordAppendV3:
        return PreviewRecordAppendV3(
            record_kind="plan",
            natural_key=plan.id,
            schema_version="execution-plan-v3",
            value=plan,
            sequence_number=plan.version,
            requirement_version_id=plan.requirement_version_id,
            plan_version_id=plan.id,
        )

    async def prepare(
        self,
        *,
        run_id: str,
        user_request: str,
        previous_requirement_id: str | None = None,
    ) -> PreviewPlanningMutationV3:
        previous = (
            self._repository.get_requirement(run_id, previous_requirement_id)
            if previous_requirement_id is not None
            else None
        )
        if previous_requirement_id is not None and previous is None:
            raise ValueError("previous Requirement is not visible")
        artifacts = _StagedPlanningArtifacts(self._repository)
        facade, _graphs, _capabilities, _candidates, _compiler = self._components(artifacts)
        bundle = await facade.prepare(
            run_id=run_id,
            user_request=user_request,
            previous_requirement=previous,
        )
        records = [self._requirement_record(bundle.requirement), *artifacts.records]
        state = "clarify"
        if bundle.candidates is not None:
            records.append(self._candidate_record(bundle.requirement, bundle.candidates))
            state = "candidates"
        return PreviewPlanningMutationV3(
            records=tuple(records),
            response_payload={
                "accepted": True,
                "preview_only": True,
                "planning_state": state,
                "requirement_version_id": bundle.requirement.id,
            },
        )

    def _planning_state(
        self,
        *,
        run_id: str,
        artifacts: _StagedPlanningArtifacts,
    ) -> tuple[
        RequirementVersionV3,
        ProblemGraphArtifactRefV3,
        ProblemGraphV1,
        CapabilityResolutionV3,
        PlanCandidateSetV3,
        CompetitiveTextCandidateCompiler,
    ]:
        snapshot = self._repository.projection_snapshot(run_id)
        if snapshot is None or snapshot.requirement is None or snapshot.candidates is None:
            raise ValueError("candidate selection requires a persisted planning bundle")
        graph_pair = self._repository.get_problem_graph_for_requirement(
            run_id,
            snapshot.requirement.id,
        )
        if graph_pair is None:
            raise ValueError("candidate selection requires a persisted ProblemGraph")
        graph_artifact, graph = graph_pair
        _facade, _graphs, capability_resolver, _candidates, compiler = self._components(artifacts)
        capability_result = capability_resolver.resolve_with_snapshot(
            run_id=run_id,
            requirement=snapshot.requirement,
            problem_graph=graph,
            catalog=self._catalog,
        )
        return (
            snapshot.requirement,
            graph_artifact,
            graph,
            capability_result.resolution,
            snapshot.candidates,
            compiler,
        )

    def select_candidate(
        self,
        *,
        run_id: str,
        candidate_id: str,
        plan_version: int,
    ) -> PreviewPlanningMutationV3:
        artifacts = _StagedPlanningArtifacts(self._repository)
        (
            requirement,
            graph_artifact,
            graph,
            capabilities,
            persisted_candidates,
            compiler,
        ) = self._planning_state(run_id=run_id, artifacts=artifacts)
        candidate = next(
            (item for item in persisted_candidates.candidates if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("unknown candidate")
        plan = compiler.compile_version(
            run_id=run_id,
            version=plan_version,
            request=CandidateCompilationRequestV3(
                requirement=requirement,
                problem_graph=graph,
                problem_graph_artifact=graph_artifact,
                capabilities=capabilities,
                candidate=candidate,
            ),
        )
        return PreviewPlanningMutationV3(
            records=tuple([*artifacts.records, self._plan_record(plan)]),
            response_payload={
                "accepted": True,
                "preview_only": True,
                "candidate_id": candidate_id,
                "plan_version_id": plan.id,
            },
        )

    async def revise(
        self,
        *,
        run_id: str,
        request: ResearchV3ReviseRequest,
        user_request: str,
        plan_version: int,
    ) -> PreviewPlanningMutationV3:
        snapshot = self._repository.projection_snapshot(run_id)
        if snapshot is None or snapshot.requirement is None or snapshot.selected_plan is None:
            raise ValueError("plan revision requires a selected Plan")
        if request.remove_optional_step_numbers:
            steps = {item.step_number: item for item in snapshot.selected_plan.payload.steps}
            if any(
                number not in steps or steps[number].required
                for number in request.remove_optional_step_numbers
            ):
                raise ValueError("requested optional step is not removable")
        candidate_id = request.candidate_id or snapshot.selected_plan.payload.candidate_id
        if request.assumptions or request.revision_note is not None:
            assumptions = {item.key: item for item in snapshot.requirement.payload.assumptions}
            for item in request.assumptions:
                assumptions[item.key] = ResearchAssumptionV3(
                    key=item.key,
                    value=item.value,
                    editable=True,
                )
            if request.revision_note is not None:
                assumptions["revision_note"] = ResearchAssumptionV3(
                    key="revision_note",
                    value=request.revision_note,
                    editable=True,
                )
            revised_task = snapshot.requirement.payload.model_copy(
                update={"assumptions": tuple(assumptions.values())}
            )
            revised_requirement = RequirementVersionV3(
                id=self._ids.new("requirement"),
                run_id=run_id,
                version=snapshot.requirement.version + 1,
                schema_version="research-task-v3",
                task_type="competitive_research",
                payload=revised_task,
                content_hash=canonical_json_v3_sha256(revised_task),
                created_at=self._clock.now(),
            )
            artifacts = _StagedPlanningArtifacts(self._repository)
            _facade, graphs, capabilities, candidates, compiler = self._components(artifacts)
            graph_result = await graphs.plan_and_seal(
                requirement=revised_requirement,
                catalog=self._catalog,
            )
            capability_result = capabilities.resolve_with_snapshot(
                run_id=run_id,
                requirement=revised_requirement,
                problem_graph=graph_result.graph,
                catalog=self._catalog,
            )
            candidate_set = await candidates.generate(
                requirement=revised_requirement,
                problem_graph=graph_result.graph,
                capabilities=capability_result.resolution,
            )
            candidate = next(
                (item for item in candidate_set.candidates if item.candidate_id == candidate_id),
                None,
            )
            if candidate is None:
                raise ValueError("unknown candidate")
            plan = compiler.compile_version(
                run_id=run_id,
                version=plan_version,
                request=CandidateCompilationRequestV3(
                    requirement=revised_requirement,
                    problem_graph=graph_result.graph,
                    problem_graph_artifact=graph_result.artifact,
                    capabilities=capability_result.resolution,
                    candidate=candidate,
                ),
            )
            records = (
                self._requirement_record(revised_requirement),
                *artifacts.records,
                self._candidate_record(revised_requirement, candidate_set),
                self._plan_record(plan),
            )
            return PreviewPlanningMutationV3(
                records=records,
                response_payload={
                    "accepted": True,
                    "preview_only": True,
                    "candidate_id": candidate_id,
                    "plan_version_id": plan.id,
                    "requirement_version_id": revised_requirement.id,
                },
            )
        return self.select_candidate(
            run_id=run_id,
            candidate_id=candidate_id,
            plan_version=plan_version,
        )


class ResearchV3PreviewComposition:
    """Per-request owner scoping over the shared SQLite database."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def _repository(self, owner: ResearchV3OwnerScope) -> SQLiteResearchV3Repository:
        return SQLiteResearchV3Repository(
            self._store.db_path,
            owner_id=owner.user_id,
            workspace_id=owner.workspace_id,
            project_id=owner.project_id,
        )

    def _workflow(
        self,
        owner: ResearchV3OwnerScope,
        repository: SQLiteResearchV3Repository,
    ) -> ResearchV3PreviewWorkflow:
        return ResearchV3PreviewWorkflow(
            repository=repository,
            owner=owner,
            planner=PreviewPlanningEngineV3(
                repository,
                resolved_for_agent_id=owner.user_id,
            ),
            input_reader=lambda run_id: (
                run.input_text
                if (run := self._store.get_agent_run(run_id)) is not None
                and run.user_id == owner.user_id
                and run.workspace_id == owner.workspace_id
                and run.project_id == owner.project_id
                else None
            ),
        )

    async def start_run(
        self,
        *,
        content: str,
        user: User,
        thread_id: str,
        client_turn_id: str,
        mode: SkillOrchestrationMode,
        requested_orchestration_mode: SkillOrchestrationRequestMode,
        explicit_skill: SkillDefinition | None = None,
    ) -> AgentRun:
        if mode != SkillOrchestrationMode.PREVIEW:
            raise RuntimeError("research-v3 Gate 2 permits preview mode only")
        owner = ResearchV3OwnerScope(
            user_id=user.id,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
        )
        proposed = AgentRun(
            thread_id=thread_id,
            user_id=user.id,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            input_text=content,
            client_turn_id=client_turn_id,
            status=AgentRunStatus.PLANNING,
            skill_id=explicit_skill.id if explicit_skill is not None else None,
            skill_name=explicit_skill.name if explicit_skill is not None else None,
            requested_orchestration_mode=requested_orchestration_mode,
            project_chat=True,
            deadline_at=now_utc() + timedelta(minutes=30),
        )
        claimed, created = ResearchRunCreationCoordinator(self._store).claim(
            proposed,
            decision=ResearchRolloutDecision(
                target="research-v3",
                mode="preview",
                reason="v3_preview_allowlisted",
            ),
            initialize_version_state=lambda connection, run: (
                SQLiteResearchV3Repository.initialize_run_in_transaction(
                    connection,
                    run_id=run.id,
                    scope=RepositoryScopeV3(
                        owner_id=run.user_id,
                        workspace_id=run.workspace_id,
                        project_id=run.project_id,
                    ),
                    created_at=run.created_at,
                )
            ),
        )
        if not created:
            return claimed
        self._store.add_chat_message(
            ChatMessage(
                thread_id=thread_id,
                role=ChatRole.USER,
                content=content,
                scope=Scope.PRIVATE,
            )
        )
        try:
            await self.initialize_run(
                run_id=claimed.id,
                owner=owner,
                user_request=content,
            )
        except Exception as error:
            failed = claimed.model_copy(
                update={
                    "status": AgentRunStatus.FAILED,
                    "error_code": type(error).__name__,
                    "updated_at": now_utc(),
                }
            )
            self._store.save_agent_run(failed)
            raise
        ready = claimed.model_copy(
            update={
                "status": AgentRunStatus.WAITING_PLAN_APPROVAL,
                "output_text": "Preview planning is ready; no external Provider was executed.",
                "updated_at": now_utc(),
            }
        )
        return self._store.save_agent_run(ready)

    async def initialize_run(
        self,
        *,
        run_id: str,
        owner: ResearchV3OwnerScope,
        user_request: str,
    ) -> None:
        repository = self._repository(owner)
        try:
            await self._workflow(owner, repository).initialize(
                run_id=run_id,
                user_request=user_request,
            )
        finally:
            repository.close()

    async def apply(
        self,
        run_id: str,
        command_type: ResearchV3CommandType,
        request: ResearchV3MutationRequest,
        *,
        owner: ResearchV3OwnerScope,
        idempotency_key: str,
    ) -> ResearchV3MutationReceipt:
        repository = self._repository(owner)
        try:
            receipt = await self._workflow(owner, repository).apply(
                run_id,
                command_type,
                request,
                owner=owner,
                idempotency_key=idempotency_key,
            )
        finally:
            repository.close()
        if command_type == "confirm_plan":
            run = self._store.get_agent_run(run_id)
            if run is not None and (
                run.user_id,
                run.workspace_id,
                run.project_id,
                run.orchestration_version,
            ) == (
                owner.user_id,
                owner.workspace_id,
                owner.project_id,
                "research-v3",
            ):
                self._store.save_agent_run(
                    run.model_copy(
                        update={
                            "status": AgentRunStatus.COMPLETED,
                            "output_text": (
                                "Preview Plan confirmed; no external Provider was executed."
                            ),
                            "updated_at": now_utc(),
                        }
                    )
                )
        elif command_type in {"cancel", "purge"}:
            self._store.cancel_agent_run_tree(run_id, user_id=owner.user_id)
        return receipt

    def project_authoritative(self, request: ResearchV3AggregateReadRequest):  # noqa: ANN201
        repository = self._repository(request.owner)
        try:
            return ResearchV3RepositoryProjector(repository).project_authoritative(request)
        finally:
            repository.close()
