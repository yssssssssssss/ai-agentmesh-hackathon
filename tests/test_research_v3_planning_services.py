from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import load_competitive_text_catalog
from agentmesh.research_orchestration.v3.common import ProblemGraphArtifactRefV3, SealedArtifactRefV3
from agentmesh.research_orchestration.v3.execution_plan import PlanInputBindingV3
from agentmesh.research_orchestration.v3.ports import CandidateCompilationRequestV3
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.requirement import ResearchTaskV3
from agentmesh.research_orchestration.v3.snapshots import FrozenModelPolicyV3, ResearchControlSnapshotV3
from agentmesh.research_orchestration.v3.planning.capabilities import CompetitiveTextCapabilityResolver
from agentmesh.research_orchestration.v3.planning.candidates import (
    CandidateGenerationError,
    CompetitiveTextCandidateGenerator,
)
from agentmesh.research_orchestration.v3.planning.compiler import (
    CandidateCompilationError,
    CompetitiveTextCandidateCompiler,
)
from agentmesh.research_orchestration.v3.planning.facade import CompetitiveTextPlanningFacade
from agentmesh.research_orchestration.v3.planning.models import ActorRuntimeDescriptorV3
from agentmesh.research_orchestration.v3.planning.problem_graphs import (
    CompetitiveTextProblemGraphPlanner,
    DeterministicProblemGraphProposalFake,
    ProblemGraphPlanningError,
)
from agentmesh.research_orchestration.v3.planning.requirements import (
    CompetitiveTextRequirementPlanner,
    DeterministicRequirementProposalFake,
    RequirementPlanningError,
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 21, tzinfo=UTC)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def new(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}_{self._next}"


class InMemoryPlanningArtifacts:
    def __init__(self) -> None:
        self.graphs: dict[str, ProblemGraphV1] = {}
        self.snapshots: dict[str, ResearchControlSnapshotV3] = {}

    def seal_problem_graph(self, *, run_id: str, graph: ProblemGraphV1) -> ProblemGraphArtifactRefV3:
        artifact_id = f"artifact_graph_{run_id}_{len(self.graphs) + 1}"
        self.graphs[artifact_id] = graph
        return ProblemGraphArtifactRefV3(
            artifact_id=artifact_id,
            kind="problem_graph",
            schema_version="problem-graph-v1",
            content_hash=canonical_json_v3_sha256(graph),
        )

    def seal_control_snapshot(
        self,
        *,
        run_id: str,
        snapshot: ResearchControlSnapshotV3,
    ) -> SealedArtifactRefV3:
        artifact_id = f"artifact_control_{run_id}_{len(self.snapshots) + 1}"
        self.snapshots[artifact_id] = snapshot
        return SealedArtifactRefV3(
            artifact_id=artifact_id,
            kind="research_control_snapshot",
            schema_version="research-control-snapshot-v3",
            content_hash=canonical_json_v3_sha256(snapshot),
        )

    def read_control_snapshot(self, artifact: SealedArtifactRefV3) -> ResearchControlSnapshotV3 | None:
        snapshot = self.snapshots.get(artifact.artifact_id)
        if snapshot is None or canonical_json_v3_sha256(snapshot) != artifact.content_hash:
            return None
        return snapshot


class AllowOwnerApproval:
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


class DescriptorRegistry:
    def __init__(self, *, real_tool: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.descriptors = {
            ("tool", "tavily-web-search"): ActorRuntimeDescriptorV3(
                actor_type="tool",
                actor_id="tavily-web-search",
                implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
                implementation_version="1",
                execution_mode="real" if real_tool else "deterministic",
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
                implementation_id="competitive-web-research-v1",
                implementation_version="1",
                execution_mode="model",
                health_state="healthy",
                enabled=True,
                authorized=True,
                input_schema_document_id="source-research-task-v2-schema",
                output_schema_document_id="source-skill-result-envelope-schema",
                instruction_document_id="competitive-web-research-instructions",
            ),
            ("skill", "competitive-analysis"): ActorRuntimeDescriptorV3(
                actor_type="skill",
                actor_id="competitive-analysis",
                implementation_id="competitive-analysis-v1",
                implementation_version="1",
                execution_mode="model",
                health_state="healthy",
                enabled=True,
                authorized=True,
                input_schema_document_id="source-research-task-v2-schema",
                output_schema_document_id="source-skill-result-envelope-schema",
                instruction_document_id="competitive-analysis-instructions",
            ),
            ("llm", "competitive-text-synthesis-v1"): ActorRuntimeDescriptorV3(
                actor_type="llm",
                actor_id="competitive-text-synthesis-v1",
                implementation_id="structured-model-fake",
                implementation_version="1",
                execution_mode="model",
                health_state="healthy",
                enabled=True,
                authorized=True,
                input_schema_document_id="source-skill-result-envelope-schema",
                output_schema_document_id="source-report-document-schema",
                instruction_document_id="competitive-text-synthesis-prompt",
            ),
            ("reviewer", "competitive-text-quality-reviewer-v1"): ActorRuntimeDescriptorV3(
                actor_type="reviewer",
                actor_id="competitive-text-quality-reviewer-v1",
                implementation_id="structured-reviewer-fake",
                implementation_version="1",
                execution_mode="model",
                health_state="healthy",
                enabled=True,
                authorized=True,
                input_schema_document_id="source-competitive-report-schema",
                output_schema_document_id="source-report-review-schema",
                instruction_document_id="competitive-analysis-review-v3",
            ),
        }

    def describe(self, actor_type: str, actor_id: str) -> ActorRuntimeDescriptorV3 | None:
        self.calls.append((actor_type, actor_id))
        return self.descriptors.get((actor_type, actor_id))


def research_task(*, blocked: bool = False, two_criteria: bool = False) -> ResearchTaskV3:
    criteria = [
        {"id": "criterion_traceable", "statement": "Every material difference is traceable."},
    ]
    if two_criteria:
        criteria.append({"id": "criterion_actionable", "statement": "Recommendations are actionable."})
    return ResearchTaskV3.model_validate(
        {
            "schema_version": "research-task-v3",
            "task_type": "competitive_research",
            "business_domain": "productivity_software",
            "research_goal": "Compare Alpha and Beta for team adoption.",
            "comparison_dimensions": ["capabilities", "limitations"],
            "target_audience": ["product_team"],
            "scope": [] if blocked else ["Alpha", "Beta"],
            "constraints": [
                {"id": "constraint_public", "statement": "Use public evidence.", "source": "user"}
            ],
            "success_criteria": criteria,
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


def services(*, task: ResearchTaskV3, real_tool: bool = True):
    catalog = load_competitive_text_catalog()
    clock = FixedClock()
    ids = SequentialIds()
    artifacts = InMemoryPlanningArtifacts()
    requirement_fake = DeterministicRequirementProposalFake(task)
    graph_fake = DeterministicProblemGraphProposalFake()
    descriptors = DescriptorRegistry(real_tool=real_tool)
    requirement_planner = CompetitiveTextRequirementPlanner(
        proposal_port=requirement_fake,
        id_generator=ids,
        clock=clock,
    )
    graph_planner = CompetitiveTextProblemGraphPlanner(
        proposal_port=graph_fake,
        artifacts=artifacts,
    )
    resolver = CompetitiveTextCapabilityResolver(
        descriptors=descriptors,
        approvals=AllowOwnerApproval(),
        artifacts=artifacts,
        clock=clock,
        resolved_for_agent_id="agent_planner",
        model_policy=FrozenModelPolicyV3(
            requested_provider="fake",
            requested_model="structured-planning-fake",
            structured_output_mode="json_schema",
            adapter_compatibility_id="deterministic-test-v1",
        ),
    )
    generator = CompetitiveTextCandidateGenerator()
    compiler = CompetitiveTextCandidateCompiler(
        catalog=catalog,
        artifacts=artifacts,
        id_generator=ids,
        clock=clock,
    )
    facade = CompetitiveTextPlanningFacade(
        catalog=catalog,
        requirements=requirement_planner,
        problem_graphs=graph_planner,
        capabilities=resolver,
        candidates=generator,
        compiler=compiler,
    )
    return (
        catalog,
        artifacts,
        requirement_fake,
        graph_fake,
        descriptors,
        requirement_planner,
        graph_planner,
        resolver,
        generator,
        compiler,
        facade,
    )


def test_requirement_planner_uses_receipt_backed_fake_and_versions_clarifications() -> None:
    blocked = research_task(blocked=True)
    resolved = research_task()
    fake = DeterministicRequirementProposalFake(blocked, resolved)
    planner = CompetitiveTextRequirementPlanner(
        proposal_port=fake,
        id_generator=SequentialIds(),
        clock=FixedClock(),
    )

    first = asyncio.run(planner.refine_version(run_id="run_1", user_request="Compare products", previous=None))
    second = asyncio.run(
        planner.refine_version(
            run_id="run_1",
            user_request="Compare Alpha and Beta",
            previous=first.requirement,
        )
    )

    assert first.requirement.version == 1
    assert first.requirement.payload.planning_blocked is True
    assert second.requirement.version == 2
    assert second.requirement.payload.planning_blocked is False
    assert first.receipt.output_hash == first.requirement.content_hash
    assert second.receipt.output_hash == second.requirement.content_hash
    assert len(fake.calls) == 2

    stale_blocker = blocked.model_copy(update={"ambiguities": (), "clarification_questions": (), "blocking_issues": (
        {"key": "scope", "reason": "Scope is unknown.", "kind": "missing_scope"},
    )})
    invalid_planner = CompetitiveTextRequirementPlanner(
        proposal_port=DeterministicRequirementProposalFake(stale_blocker),
        id_generator=SequentialIds(),
        clock=FixedClock(),
    )
    with pytest.raises(RequirementPlanningError, match="blocking_requirement_requires_clarification"):
        asyncio.run(invalid_planner.refine(run_id="run_2", user_request="Compare products", previous=None))


def test_problem_graph_planner_seals_artifact_and_rejects_policy_drift() -> None:
    (
        catalog,
        artifacts,
        _,
        _,
        _,
        requirement_planner,
        graph_planner,
        *_,
    ) = services(task=research_task(two_criteria=True))
    requirement = asyncio.run(
        requirement_planner.refine_version(run_id="run_graph", user_request="Compare Alpha and Beta", previous=None)
    ).requirement
    result = asyncio.run(graph_planner.plan_and_seal(requirement=requirement, catalog=catalog))

    assert result.graph.requirement_version_id == requirement.id
    assert result.artifact.content_hash == canonical_json_v3_sha256(result.graph)
    assert {item.id for item in result.graph.questions} == {"question_1", "question_2"}
    assert artifacts.graphs[result.artifact.artifact_id] == result.graph

    class PolicyDriftFake(DeterministicProblemGraphProposalFake):
        async def propose(self, *, requirement, catalog):
            proposal = await super().propose(requirement=requirement, catalog=catalog)
            question = proposal.graph.questions[0]
            bad_requirement = question.evidence_requirements[0].model_copy(
                update={"accepted_classes": ("user_input",)}
            )
            bad_graph = proposal.graph.model_copy(
                update={
                    "questions": (
                        question.model_copy(update={"evidence_requirements": (bad_requirement,)}),
                        *proposal.graph.questions[1:],
                    )
                }
            )
            return proposal.model_copy(
                update={
                    "graph": bad_graph,
                    "receipt": proposal.receipt.model_copy(
                        update={"output_hash": canonical_json_v3_sha256(bad_graph)}
                    ),
                }
            )

    rejecting = CompetitiveTextProblemGraphPlanner(
        proposal_port=PolicyDriftFake(),
        artifacts=artifacts,
    )
    with pytest.raises(ProblemGraphPlanningError, match="evidence classes"):
        asyncio.run(rejecting.plan(requirement=requirement, catalog=catalog))


def test_capability_resolution_requires_real_core_tool_and_records_owner_and_exclusions() -> None:
    catalog, artifacts, _, _, _, requirement_planner, graph_planner, resolver, generator, *_ = services(
        task=research_task()
    )
    requirement = asyncio.run(
        requirement_planner.refine_version(run_id="run_caps", user_request="Compare Alpha and Beta", previous=None)
    ).requirement
    graph = asyncio.run(graph_planner.plan_and_seal(requirement=requirement, catalog=catalog)).graph
    result = resolver.resolve_with_snapshot(
        run_id="run_caps",
        requirement=requirement,
        problem_graph=graph,
        catalog=catalog,
    )

    tool = next(item for item in result.resolution.decisions if item.actor_type == "tool")
    web_skill = next(item for item in result.resolution.decisions if item.actor_id == "competitive-web-research")
    assert tool.status == "eligible"
    assert [(item.capability_id, item.authority) for item in tool.required_approvals] == [
        ("tavily-web-search", "owner")
    ]
    assert web_skill.optional_tool_decisions[0].tool_id == "playwright-page-capture"
    assert web_skill.optional_tool_decisions[0].reason_code == "not_enabled_in_slice"
    assert {item.capability_id for item in result.resolution.gaps if not item.required} == {
        "competitive-app-analysis",
        "digital-human-competitive-analysis",
        "playwright-page-capture",
    }
    assert result.resolution.control_snapshot_artifact.content_hash == canonical_json_v3_sha256(result.snapshot)
    assert artifacts.read_control_snapshot(result.resolution.control_snapshot_artifact) == result.snapshot

    bad_services = services(task=research_task(), real_tool=False)
    bad_catalog, _, _, _, _, bad_requirement_planner, bad_graph_planner, bad_resolver, bad_generator, *_ = bad_services
    bad_requirement = asyncio.run(
        bad_requirement_planner.refine_version(
            run_id="run_fake_tool",
            user_request="Compare Alpha and Beta",
            previous=None,
        )
    ).requirement
    bad_graph = asyncio.run(
        bad_graph_planner.plan_and_seal(requirement=bad_requirement, catalog=bad_catalog)
    ).graph
    bad_resolution = bad_resolver.resolve(
        run_id="run_fake_tool",
        requirement=bad_requirement,
        problem_graph=bad_graph,
        catalog=bad_catalog,
    )
    rejected_tool = next(item for item in bad_resolution.decisions if item.actor_type == "tool")
    assert rejected_tool.status == "rejected"
    assert "core_tool_real_adapter_unavailable" in {item.code for item in rejected_tool.reasons}
    with pytest.raises(CandidateGenerationError, match="core_tool_real_adapter_unavailable"):
        asyncio.run(
            bad_generator.generate(
                requirement=bad_requirement,
                problem_graph=bad_graph,
                capabilities=bad_resolution,
            )
        )


def test_facade_builds_ordered_candidates_and_compiler_assigns_frozen_server_steps() -> None:
    *_, facade = services(task=research_task(two_criteria=True))
    bundle = asyncio.run(
        facade.prepare(run_id="run_full", user_request="Compare Alpha and Beta", previous_requirement=None)
    )

    assert bundle.candidates is not None
    assert tuple(item.candidate_id for item in bundle.candidates.candidates) == ("depth", "speed")
    assert [len(item.proposed_steps) for item in bundle.candidates.candidates] == [4, 3]
    depth = facade.compile_selected(bundle=bundle, candidate_id="depth")
    speed = facade.compile_selected(bundle=bundle, candidate_id="speed", plan_version=2)

    assert tuple(step.step_number for step in depth.payload.steps) == (1, 2, 3, 4)
    assert tuple(step.step_number for step in speed.payload.steps) == (1, 2, 3)
    assert depth.payload.steps[0].requires_approval is True
    assert depth.payload.steps[0].approval_role == "owner"
    assert depth.payload.steps[1].depends_on == (1,)
    assert depth.payload.steps[1].input_bindings[0].source_step_number == 1
    assert all(step.contract_hash == canonical_json_v3_sha256(
        step.model_dump(mode="python", exclude={"contract_hash"})
    ) for step in depth.payload.steps)
    assert depth.plan_hash == canonical_json_v3_sha256(depth.payload)
    with pytest.raises(ValidationError):
        depth.payload.steps[0].name = "client overwrite"  # type: ignore[misc]


def test_compiler_rejects_client_approval_binding_and_coverage_drift() -> None:
    *_, compiler, facade = services(task=research_task())
    bundle = asyncio.run(
        facade.prepare(run_id="run_reject", user_request="Compare Alpha and Beta", previous_requirement=None)
    )
    assert bundle.candidates is not None
    assert bundle.problem_graph is not None
    assert bundle.problem_graph_artifact is not None
    assert bundle.capabilities is not None
    candidate = bundle.candidates.candidates[0]

    def request_with(candidate_value):
        return CandidateCompilationRequestV3(
            requirement=bundle.requirement,
            problem_graph=bundle.problem_graph,
            problem_graph_artifact=bundle.problem_graph_artifact,
            capabilities=bundle.capabilities,
            candidate=candidate_value,
        )

    no_approval_step = candidate.proposed_steps[0].model_copy(
        update={"requires_approval": False, "approval_role": None}
    )
    no_approval = candidate.model_copy(
        update={"proposed_steps": (no_approval_step, *candidate.proposed_steps[1:])}
    )
    with pytest.raises(CandidateCompilationError, match="tool_owner_approval_required"):
        compiler.compile(request_with(no_approval))

    analysis = candidate.proposed_steps[2]
    bad_binding = analysis.model_copy(
        update={
            "input_bindings": (
                PlanInputBindingV3(
                    source_step_number=4,
                    source_pointer="/missing",
                    target_pointer="/evidence",
                ),
            )
        }
    )
    binding_drift = candidate.model_copy(
        update={"proposed_steps": (*candidate.proposed_steps[:2], bad_binding, candidate.proposed_steps[3])}
    )
    with pytest.raises(CandidateCompilationError, match="binding_source_output_missing"):
        compiler.compile(request_with(binding_drift))

    uncovered_search = candidate.proposed_steps[0].model_copy(update={"question_ids": ()})
    uncovered = candidate.model_copy(
        update={"proposed_steps": (uncovered_search, *candidate.proposed_steps[1:])}
    )
    with pytest.raises(CandidateCompilationError, match="public_evidence_step_coverage_mismatch"):
        compiler.compile(request_with(uncovered))

    cyclic_search = candidate.proposed_steps[0].model_copy(update={"depends_on": (4,)})
    cyclic = candidate.model_copy(
        update={"proposed_steps": (cyclic_search, *candidate.proposed_steps[1:])}
    )
    with pytest.raises(CandidateCompilationError, match="candidate_dependency_cycle"):
        compiler.compile(request_with(cyclic))


def test_blocking_requirement_stops_facade_before_graph_capability_or_candidate_work() -> None:
    service_set = services(task=research_task(blocked=True))
    requirement_fake = service_set[2]
    graph_fake = service_set[3]
    descriptors = service_set[4]
    facade = service_set[10]
    bundle = asyncio.run(
        facade.prepare(run_id="run_blocked", user_request="Compare products", previous_requirement=None)
    )

    assert bundle.requirement.payload.planning_blocked is True
    assert bundle.problem_graph is None
    assert bundle.capabilities is None
    assert bundle.candidates is None
    assert len(requirement_fake.calls) == 1
    assert graph_fake.calls == []
    assert descriptors.calls == []
    with pytest.raises(ValueError, match="requirement_clarification_required"):
        facade.compile_selected(bundle=bundle, candidate_id="depth")
