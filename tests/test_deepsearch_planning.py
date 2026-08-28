from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentmesh.artifacts import DeepSearchPlanSnapshotV1
from agentmesh.canonical_json import canonical_json_bytes, strict_json_loads
from agentmesh.deepsearch.contracts import (
    ClarificationQuestionDraftV1,
    ProblemGraphV1,
    ProblemQuestionV1,
    RequirementAmbiguityV1,
    RequirementPayloadV1,
    RequirementRefinementDraftV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    build_problem_graph,
    canonical_planning_input,
    materialize_requirement_payload,
    problem_graph_hash,
    problem_question_id,
    requirement_content_hash,
    validate_plan_question_coverage,
    validate_problem_graph_against_requirement,
)
from agentmesh.deepsearch.planning import (
    DeepSearchPlanCompiler,
    DeepSearchPlanningPipeline,
    build_deepsearch_plan_snapshot,
    deepsearch_frozen_plan,
    plan_content_hash,
)
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    ArtifactVerificationState,
    SkillCandidate,
    SkillCandidateScore,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillIntent,
    SkillLifecycleStage,
    SkillPlan,
    SkillPlanDraft,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSideEffect,
    SkillSourceScope,
    ToolDefinition,
    User,
)
from agentmesh.skill_runtime.plan_validation import PlanValidationError
from agentmesh.task_routing.router import TaskScenarioRouter

_EMPTY_SKILL_PATH = Path(__file__).resolve().parent / "fixtures" / "deepsearch_empty_skill" / "SKILL.md"


def test_problem_question_has_a_stable_server_id_and_is_strict_and_frozen() -> None:
    question = "Which competitors lead the market?"
    question_id = problem_question_id(question)

    first = ProblemQuestionV1(
        id=question_id,
        question=question,
        required=True,
        success_criterion_ids=["criterion_market"],
        evidence_requirements=["Current public market evidence"],
        acceptance_criteria=["Identify at least three competitors"],
        depends_on=[],
    )
    second = ProblemQuestionV1(
        id=problem_question_id("  Which competitors lead the market?  "),
        question="Which competitors lead the market?",
        required=True,
        success_criterion_ids=["criterion_market"],
        evidence_requirements=["Current public market evidence"],
        acceptance_criteria=["Identify at least three competitors"],
        depends_on=[],
    )

    assert first.id == second.id
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProblemQuestionV1.model_validate({**first.model_dump(), "invented": True})
    with pytest.raises(ValidationError, match="Instance is frozen"):
        first.question = "Changed"  # type: ignore[misc]

    with pytest.raises(ValidationError):
        ProblemQuestionV1(
            id=question_id,
            question=question,
            required=True,
            success_criterion_ids=[""],
            evidence_requirements=["Current public market evidence"],
            acceptance_criteria=["Identify at least three competitors"],
            depends_on=[],
        )


def _problem_questions() -> list[ProblemQuestionV1]:
    market = ProblemQuestionV1(
        id=problem_question_id("What is the market size?"),
        question="What is the market size?",
        required=True,
        success_criterion_ids=["criterion_market"],
        evidence_requirements=["Public market data"],
        acceptance_criteria=["State a sourced estimate"],
        depends_on=[],
    )
    recommendation = ProblemQuestionV1(
        id=problem_question_id("What should we build?"),
        question="What should we build?",
        required=True,
        success_criterion_ids=["criterion_recommendation"],
        evidence_requirements=["Findings from the market question"],
        acceptance_criteria=["Give an evidence-linked recommendation"],
        depends_on=[market.id],
    )
    return [market, recommendation]


def _complete_requirement() -> RequirementVersionV1:
    payload = RequirementPayloadV1(
        goal="Evaluate the collaboration software market",
        scope=RequirementScopeV1(regions=["China"], time_range="2025-2026"),
        constraints=[],
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_market",
                statement="Quantify the market",
            ),
            RequirementSuccessCriterionV1(
                id="criterion_recommendation",
                statement="Recommend a product direction",
            ),
        ],
        deliverables=["Research report"],
        assumptions=[],
        ambiguities=[],
        clarification_questions=[],
        clarification_history=[],
        clarification_round=0,
    )
    return RequirementVersionV1(
        id="requirement_1",
        run_id="run_1",
        version=1,
        request_key="turn_1",
        request_hash="1" * 64,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=datetime(2026, 8, 26, 8, 0, tzinfo=UTC),
    )


def test_problem_graph_verifies_canonical_hash_and_dependency_dag() -> None:
    questions = _problem_questions()
    graph = ProblemGraphV1(
        schema_version="deepsearch-problem-graph-v1",
        requirement_version_id="requirement_1",
        questions=questions,
        content_hash="5229db23523686046cc6ffec263d6d9aa08c8b5f0405a44c064cf60f03450810",
    )

    assert problem_graph_hash(graph) == graph.content_hash

    with pytest.raises(ValidationError, match="content_hash"):
        ProblemGraphV1.model_validate({**graph.model_dump(), "content_hash": "0" * 64})

    unknown_dependency = questions[1].model_copy(update={"depends_on": ["question_0000000000000000"]})
    with pytest.raises(ValidationError, match="unknown dependency"):
        ProblemGraphV1(
            schema_version="deepsearch-problem-graph-v1",
            requirement_version_id="requirement_1",
            questions=[questions[0], unknown_dependency],
            content_hash="0" * 64,
        )

    cyclic_market = questions[0].model_copy(update={"depends_on": [questions[1].id]})
    with pytest.raises(ValidationError, match="cycle"):
        ProblemGraphV1(
            schema_version="deepsearch-problem-graph-v1",
            requirement_version_id="requirement_1",
            questions=[cyclic_market, questions[1]],
            content_hash="0" * 64,
        )


def test_problem_graph_must_cover_the_current_requirements_success_criteria() -> None:
    requirement = _complete_requirement()
    graph = build_problem_graph(requirement=requirement, questions=_problem_questions())

    validate_problem_graph_against_requirement(graph=graph, requirement=requirement)
    assert graph.requirement_version_id == requirement.id

    incomplete_projection = {
        "schema_version": "deepsearch-problem-graph-v1",
        "requirement_version_id": requirement.id,
        "questions": _problem_questions()[:1],
    }
    incomplete = ProblemGraphV1(
        **incomplete_projection,
        content_hash=problem_graph_hash(incomplete_projection),
    )
    with pytest.raises(ValueError, match="not covered"):
        validate_problem_graph_against_requirement(graph=incomplete, requirement=requirement)

    unknown_reference = _problem_questions()[0].model_copy(
        update={"success_criterion_ids": ["criterion_unknown"]}
    )
    with pytest.raises(ValueError, match="unknown success criterion"):
        build_problem_graph(requirement=requirement, questions=[unknown_reference])


def test_canonical_planning_input_contains_clarification_history_and_rejects_incomplete_requirement() -> None:
    initial_draft = RequirementRefinementDraftV1(
        goal="Evaluate the collaboration software market",
        scope=RequirementScopeV1(),
        constraints=[],
        success_criteria=[
            RequirementSuccessCriterionV1(id="criterion_market", statement="Quantify the market")
        ],
        deliverables=["Research report"],
        assumptions=[],
        ambiguities=[
            RequirementAmbiguityV1(
                id="ambiguity_region",
                statement="Region is unresolved",
                blocking=True,
            )
        ],
        clarification_questions=[
            ClarificationQuestionDraftV1(
                prompt="Which region?",
                required=True,
                answer_kind="text",
                options=[],
            )
        ],
    )
    initial_payload = materialize_requirement_payload(
        previous=None,
        draft=initial_draft,
        answers={},
        target_version=1,
    )
    initial = RequirementVersionV1(
        id="requirement_initial",
        run_id="run_1",
        version=1,
        request_key="turn_1",
        request_hash="1" * 64,
        content_hash=requirement_content_hash(initial_payload),
        payload=initial_payload,
        created_at=datetime(2026, 8, 26, 8, 0, tzinfo=UTC),
    )
    answer = {initial.payload.clarification_questions[0].id: "China"}
    completed_payload = materialize_requirement_payload(
        previous=initial,
        draft=RequirementRefinementDraftV1(
            goal="Evaluate the collaboration software market in China",
            scope=RequirementScopeV1(regions=["China"]),
            constraints=[],
            success_criteria=initial.payload.success_criteria,
            deliverables=initial.payload.deliverables,
            assumptions=[],
            ambiguities=[],
            clarification_questions=[],
        ),
        answers=answer,
        target_version=2,
    )
    completed = RequirementVersionV1(
        id="requirement_completed",
        run_id="run_1",
        version=2,
        request_key="clarify_1",
        request_hash="2" * 64,
        content_hash=requirement_content_hash(completed_payload),
        derived_from_requirement_version_id=initial.id,
        payload=completed_payload,
        created_at=datetime(2026, 8, 26, 8, 1, tzinfo=UTC),
    )

    planning_input = canonical_planning_input(completed)
    decoded = strict_json_loads(planning_input)

    assert canonical_json_bytes(decoded).decode("utf-8") == planning_input
    assert decoded["requirement_version_id"] == completed.id
    assert decoded["requirement_content_hash"] == completed.content_hash
    assert decoded["requirement"]["clarification_history"][0]["answers"] == answer
    assert "request_key" not in planning_input
    assert canonical_planning_input(completed) == planning_input

    with pytest.raises(ValueError, match="complete"):
        canonical_planning_input(initial)


def test_skill_plan_node_accepts_only_unique_stable_problem_question_ids() -> None:
    question_ids = [question.id for question in _problem_questions()]
    node = SkillPlanNode(
        id="node_market_research",
        skill_id="skill_market_research",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="Answer the frozen market questions",
        question_ids=question_ids,
    )

    assert node.question_ids == question_ids
    assert SkillPlanNode(
        skill_id="legacy_standard_skill",
        skill_version="1",
        skill_content_hash="legacy-hash",
        reason="Existing standard plan",
    ).question_ids == []

    with pytest.raises(ValidationError, match="question_ids"):
        SkillPlanNode(
            skill_id="skill_market_research",
            skill_version="1",
            skill_content_hash="a" * 64,
            reason="Duplicate assignment",
            question_ids=[question_ids[0], question_ids[0]],
        )
    with pytest.raises(ValidationError):
        SkillPlanNode(
            skill_id="skill_market_research",
            skill_version="1",
            skill_content_hash="a" * 64,
            reason="Unknown identifier shape",
            question_ids=["invented_question"],
        )


def test_required_problem_questions_must_be_covered_by_required_plan_nodes() -> None:
    graph = build_problem_graph(
        requirement=_complete_requirement(),
        questions=_problem_questions(),
    )
    first_id, second_id = (question.id for question in graph.questions)
    valid_nodes = [
        SkillPlanNode(
            id="node_market",
            skill_id="skill_market",
            skill_version="1",
            skill_content_hash="a" * 64,
            reason="Research the market",
            required=True,
            question_ids=[first_id],
        ),
        SkillPlanNode(
            id="node_recommendation",
            skill_id="skill_recommendation",
            skill_version="1",
            skill_content_hash="b" * 64,
            reason="Recommend a direction",
            required=True,
            question_ids=[second_id],
        ),
    ]

    validate_plan_question_coverage(graph=graph, nodes=valid_nodes)

    with pytest.raises(ValueError, match="not covered"):
        validate_plan_question_coverage(graph=graph, nodes=valid_nodes[:1])

    unknown = valid_nodes[0].model_copy(
        update={"question_ids": ["question_0000000000000000"]}
    )
    with pytest.raises(ValueError, match="unknown ProblemQuestion"):
        validate_plan_question_coverage(graph=graph, nodes=[unknown, valid_nodes[1]])


def _candidate(*, side_effect: SkillSideEffect = SkillSideEffect.READ) -> SkillCandidate:
    profile = SkillCapabilityProfile(
        id="profile_market_research",
        skill_id="skill_market_research",
        skill_name="market-research",
        skill_version="1",
        skill_content_hash="a" * 64,
        profile_version="1",
        profile_content_hash="b" * 64,
        primary_stage=SkillLifecycleStage.PRE_DESIGN,
        capability_type=SkillCapabilityType.RESEARCH,
        input_kinds=["design_requirement"],
        output_kinds=["research_report"],
        required_tools=["web_research"],
        side_effect=side_effect,
    )
    return SkillCandidate(
        skill_id=profile.skill_id,
        skill_name=profile.skill_name,
        title="Market research",
        description="Research a market",
        profile=profile,
        score=SkillCandidateScore(total=10),
        reason="Matches the research goal",
    )


def _skill_definition() -> SkillDefinition:
    return SkillDefinition(
        id="skill_market_research",
        name="market-research",
        title="Market research",
        description="Research a market",
        instructions="Use trustworthy sources.",
        source_path=str(_EMPTY_SKILL_PATH),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="a" * 64,
        version="1",
    )


def _compiler(tool: ToolDefinition | None) -> DeepSearchPlanCompiler:
    skill = _skill_definition()
    return DeepSearchPlanCompiler(
        tool_definition_lookup=lambda _reference: tool,
        skill_definition_lookup=lambda skill_id: skill if skill_id == skill.id else None,
    )


def _intent() -> SkillIntent:
    return SkillIntent(
        goal="Evaluate the collaboration software market in China",
        input_kinds=["design_requirement"],
        deliverables=["research_report"],
        external_evidence_required=True,
    )


def _draft(graph: ProblemGraphV1, candidate: SkillCandidate) -> SkillPlanDraft:
    return SkillPlanDraft(
        output_contract=["research_report"],
        nodes=[
            SkillPlanNode(
                id="node_market_research",
                skill_id=candidate.skill_id,
                skill_version=candidate.profile.skill_version,
                skill_content_hash=candidate.profile.skill_content_hash,
                reason="Answer every required research question",
                required=True,
                question_ids=[question.id for question in graph.questions],
                input_bindings=["user.design_requirement"],
                output_contract=["research_report"],
                required_tool_names=["web_research"],
                side_effect=candidate.profile.side_effect,
            )
        ],
    )


def _read_tool() -> ToolDefinition:
    return ToolDefinition(
        id="tool_web_research",
        name="web_research",
        external_name="web_research",
        description="Read public web sources",
        category="research",
        enabled=True,
        side_effect="read",
    )


def _compiled_deepsearch_plan(*, version: int = 1) -> SkillPlan:
    requirement = _complete_requirement()
    graph = build_problem_graph(requirement=requirement, questions=_problem_questions())
    candidate = _candidate()
    tool = _read_tool()
    compiler = _compiler(tool)
    plan = compiler.compile(
        run_id=requirement.run_id,
        requirement=requirement,
        graph=graph,
        intent=_intent(),
        routing_result=None,
        candidates=[candidate],
        draft=_draft(graph, candidate),
    ).model_copy(update={"id": "plan_1", "version": version})
    plan.plan_content_hash = plan_content_hash(plan)
    return plan


def _deepsearch_run(*, plan_id: str | None = None) -> AgentRun:
    return AgentRun(
        id="run_1",
        thread_id="thread_1",
        user_id="user_1",
        workspace_id="workspace_1",
        project_id="project_1",
        input_text="Evaluate the collaboration software market",
        plan_id=plan_id,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        orchestration_version="v1",
    )


def test_plan_snapshot_builder_is_deterministic_and_seals_canonical_content() -> None:
    run = _deepsearch_run()
    plan = _compiled_deepsearch_plan()
    created_at = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)

    first = build_deepsearch_plan_snapshot(run=run, plan=plan, created_at=created_at)
    replay = build_deepsearch_plan_snapshot(run=run, plan=plan, created_at=created_at)

    assert replay == first
    assert first.id == "artifact_0d95656694ed54b600d65086fd06c4dedd09711c2c37d31111b77a73848fbfbe"
    assert first.verification_state is ArtifactVerificationState.SEALED
    assert first.artifact_type == "deepsearch_plan_snapshot"
    assert first.schema_version == "deepsearch-plan-snapshot-v1"
    assert first.run_id == run.id
    assert (first.workspace_id, first.project_id, first.user_id) == (
        run.workspace_id,
        run.project_id,
        run.user_id,
    )
    assert first.requirement_version_id == plan.requirement_version_id
    assert first.plan_version_id == f"{plan.id}:v{plan.version}"
    assert first.created_at == created_at
    assert first.updated_at == created_at
    snapshot = DeepSearchPlanSnapshotV1.model_validate(strict_json_loads(first.content))
    assert snapshot.run_id == run.id
    assert snapshot.plan_id == plan.id
    assert snapshot.plan_version == plan.version
    assert snapshot.plan_content_hash == plan.plan_content_hash
    assert first.content == canonical_json_bytes(snapshot.model_dump(mode="python")).decode()
    assert first.content_hash == hashlib.sha256(first.content.encode()).hexdigest()
    assert first.size_bytes == len(first.content.encode())


def test_plan_snapshot_artifact_identity_isolated_by_plan_version() -> None:
    run = _deepsearch_run(plan_id="plan_1")
    first_plan = _compiled_deepsearch_plan(version=1)
    second_plan = _compiled_deepsearch_plan(version=2)
    created_at = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)

    first = build_deepsearch_plan_snapshot(run=run, plan=first_plan, created_at=created_at)
    second = build_deepsearch_plan_snapshot(run=run, plan=second_plan, created_at=created_at)

    assert first.id == "artifact_0d95656694ed54b600d65086fd06c4dedd09711c2c37d31111b77a73848fbfbe"
    assert second.id == "artifact_0411fb90d0d9a4c1c33829fd2111f5a4bbcef50f9174e582af8e74c7e51bcf8d"
    assert second.id != first.id
    assert first.plan_version_id == "plan_1:v1"
    assert second.plan_version_id == "plan_1:v2"


@pytest.mark.parametrize(
    ("run_update", "plan_update", "message"),
    [
        ({"orchestration_version": "research-v2"}, {}, "v1 DeepSearch Run"),
        ({"planning_mode": AgentPlanningMode.STANDARD}, {}, "v1 DeepSearch Run"),
        ({}, {"planning_mode": AgentPlanningMode.STANDARD}, "DeepSearch Plan"),
        ({}, {"run_id": "run_other"}, "lineage"),
        ({"plan_id": "plan_other"}, {}, "lineage"),
        ({}, {"requirement_version_id": None}, "lineage"),
        ({}, {"requirement_content_hash": None}, "lineage"),
        ({}, {"problem_graph_hash": None}, "lineage"),
    ],
)
def test_plan_snapshot_builder_rejects_wrong_modes_or_lineage(
    run_update: dict[str, object],
    plan_update: dict[str, object],
    message: str,
) -> None:
    run = _deepsearch_run(plan_id="plan_1").model_copy(update=run_update)
    plan = _compiled_deepsearch_plan().model_copy(update=plan_update)

    with pytest.raises(ValueError, match=message):
        build_deepsearch_plan_snapshot(run=run, plan=plan, created_at=datetime.now(UTC))


@pytest.mark.parametrize("plan_content_hash", [None, "0" * 64])
def test_plan_snapshot_builder_rejects_missing_or_stale_plan_content_hash(
    plan_content_hash: str | None,
) -> None:
    run = _deepsearch_run(plan_id="plan_1")
    plan = _compiled_deepsearch_plan().model_copy(
        update={"plan_content_hash": plan_content_hash}
    )

    with pytest.raises(ValueError, match="content hash"):
        build_deepsearch_plan_snapshot(run=run, plan=plan, created_at=datetime.now(UTC))


def test_plan_snapshot_builder_requires_an_explicit_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        build_deepsearch_plan_snapshot(
            run=_deepsearch_run(plan_id="plan_1"),
            plan=_compiled_deepsearch_plan(),
            created_at=datetime(2026, 8, 26, 9, 0),
        )


def test_deepsearch_plan_compiler_builds_a_waiting_plan_with_a_stable_content_hash() -> None:
    requirement = _complete_requirement()
    graph = build_problem_graph(requirement=requirement, questions=_problem_questions())
    candidate = _candidate()
    tool = _read_tool()
    compiler = DeepSearchPlanCompiler(
        tool_definition_lookup=lambda reference: tool
        if reference in {tool.id, tool.name, tool.external_name}
        else None,
        skill_definition_lookup=lambda skill_id: (
            _skill_definition() if skill_id == "skill_market_research" else None
        ),
    )

    plan = compiler.compile(
        run_id=requirement.run_id,
        requirement=requirement,
        graph=graph,
        intent=_intent(),
        routing_result=None,
        candidates=[candidate],
        draft=_draft(graph, candidate),
    )

    assert plan.status is SkillPlanStatus.WAITING_APPROVAL
    assert plan.planning_mode is AgentPlanningMode.DEEPSEARCH
    assert plan.requirement_version_id == requirement.id
    assert plan.requirement_content_hash == requirement.content_hash
    assert plan.problem_graph == graph.model_dump(mode="json")
    assert plan.problem_graph_hash == graph.content_hash
    assert plan.plan_content_hash == plan_content_hash(plan)
    assert plan.approved_plan_artifact_id is None
    assert plan.capability_check is None
    assert plan.nodes[0].resource_manifest is not None
    assert plan.nodes[0].resource_manifest.required_resources == []
    assert plan.nodes[0].resource_manifest.resource_hashes == {}

    runtime_copy = plan.model_copy(deep=True)
    runtime_copy.status = SkillPlanStatus.RUNNING
    runtime_copy.nodes[0].status = SkillPlanNodeStatus.RUNNING
    runtime_copy.nodes[0].attempt = 1
    assert plan_content_hash(runtime_copy) == plan.plan_content_hash

    standard = SkillPlan(run_id="run_standard", intent=SkillIntent(goal="standard"))
    assert standard.planning_mode is AgentPlanningMode.STANDARD
    assert standard.requirement_version_id is None
    assert standard.plan_content_hash is None

    frozen = deepsearch_frozen_plan(plan)
    assert frozen.requirement_version_id == requirement.id
    assert frozen.requirement_content_hash == requirement.content_hash
    assert frozen.problem_graph_hash == graph.content_hash
    assert frozen.nodes[0].resource_manifest == plan.nodes[0].resource_manifest
    snapshot = DeepSearchPlanSnapshotV1(
        schema_version="deepsearch-plan-snapshot-v1",
        run_id=plan.run_id,
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        plan_id=plan.id,
        plan_version=plan.version,
        plan_content_hash=plan.plan_content_hash,
        frozen_plan=frozen,
    )
    with pytest.raises(ValidationError, match="plan_content_hash"):
        DeepSearchPlanSnapshotV1.model_validate(
            {**snapshot.model_dump(mode="python"), "plan_content_hash": "0" * 64}
        )
    with pytest.raises(ValidationError, match="requirement_version_id"):
        DeepSearchPlanSnapshotV1.model_validate(
            {**snapshot.model_dump(mode="python"), "requirement_version_id": "requirement_other"}
        )
    with pytest.raises(ValidationError, match="requirement_content_hash"):
        DeepSearchPlanSnapshotV1.model_validate(
            {**snapshot.model_dump(mode="python"), "requirement_content_hash": "0" * 64}
        )


def test_deepsearch_plan_compiler_freezes_resource_bytes_into_the_plan_hash(tmp_path) -> None:
    skill_root = tmp_path / "market-research"
    skill_root.mkdir()
    skill_path = skill_root / "SKILL.md"
    skill_path.write_text("skill", encoding="utf-8")
    resource_path = skill_root / "guide.md"
    resource_path.write_text("first", encoding="utf-8")
    skill = _skill_definition().model_copy(
        update={
            "instructions": "Read `guide.md`.",
            "source_path": str(skill_path),
            "source_scope": SkillSourceScope.WORKSPACE,
        }
    )
    tool = _read_tool()
    compiler = DeepSearchPlanCompiler(
        tool_definition_lookup=lambda _reference: tool,
        skill_definition_lookup=lambda skill_id: skill if skill_id == skill.id else None,
    )
    requirement = _complete_requirement()
    graph = build_problem_graph(requirement=requirement, questions=_problem_questions())
    candidate = _candidate()

    first = compiler.compile(
        run_id=requirement.run_id,
        requirement=requirement,
        graph=graph,
        intent=_intent(),
        routing_result=None,
        candidates=[candidate],
        draft=_draft(graph, candidate),
    )
    resource_path.write_text("second", encoding="utf-8")
    second = compiler.compile(
        run_id=requirement.run_id,
        requirement=requirement,
        graph=graph,
        intent=_intent(),
        routing_result=None,
        candidates=[candidate],
        draft=_draft(graph, candidate),
    )

    assert first.nodes[0].resource_manifest is not None
    assert second.nodes[0].resource_manifest is not None
    assert first.nodes[0].resource_manifest.resource_hashes != second.nodes[0].resource_manifest.resource_hashes
    assert first.nodes[0].resource_manifest.content_hash != second.nodes[0].resource_manifest.content_hash
    assert first.plan_content_hash != second.plan_content_hash


def test_deepsearch_plan_compiler_rejects_broken_lineage_and_question_coverage() -> None:
    requirement = _complete_requirement()
    graph = build_problem_graph(requirement=requirement, questions=_problem_questions())
    candidate = _candidate()
    tool = _read_tool()
    compiler = _compiler(tool)

    wrong_graph_projection = {
        "schema_version": "deepsearch-problem-graph-v1",
        "requirement_version_id": "requirement_other",
        "questions": graph.questions,
    }
    wrong_graph = ProblemGraphV1(
        **wrong_graph_projection,
        content_hash=problem_graph_hash(wrong_graph_projection),
    )
    with pytest.raises(PlanValidationError) as lineage_error:
        compiler.compile(
            run_id=requirement.run_id,
            requirement=requirement,
            graph=wrong_graph,
            intent=_intent(),
            routing_result=None,
            candidates=[candidate],
            draft=_draft(graph, candidate),
        )
    assert lineage_error.value.codes == ["problem_graph_invalid"]

    incomplete_draft = _draft(graph, candidate)
    incomplete_draft.nodes[0].question_ids = [graph.questions[0].id]
    with pytest.raises(PlanValidationError) as coverage_error:
        compiler.compile(
            run_id=requirement.run_id,
            requirement=requirement,
            graph=graph,
            intent=_intent(),
            routing_result=None,
            candidates=[candidate],
            draft=incomplete_draft,
        )
    assert coverage_error.value.codes == ["problem_graph_invalid"]

    stale_draft = _draft(graph, candidate)
    stale_draft.nodes[0].skill_content_hash = "c" * 64
    with pytest.raises(PlanValidationError) as skill_error:
        compiler.compile(
            run_id=requirement.run_id,
            requirement=requirement,
            graph=graph,
            intent=_intent(),
            routing_result=None,
            candidates=[candidate],
            draft=stale_draft,
        )
    assert skill_error.value.codes == ["skill_hash_mismatch"]

    stale_version_draft = _draft(graph, candidate)
    stale_version_draft.nodes[0].skill_version = "2"
    with pytest.raises(PlanValidationError) as version_error:
        compiler.compile(
            run_id=requirement.run_id,
            requirement=requirement,
            graph=graph,
            intent=_intent(),
            routing_result=None,
            candidates=[candidate],
            draft=stale_version_draft,
        )
    assert version_error.value.codes == ["skill_version_mismatch"]

    unknown_skill_draft = _draft(graph, candidate)
    unknown_skill_draft.nodes[0].skill_id = "skill_not_in_shortlist"
    with pytest.raises(PlanValidationError) as unknown_skill_error:
        compiler.compile(
            run_id=requirement.run_id,
            requirement=requirement,
            graph=graph,
            intent=_intent(),
            routing_result=None,
            candidates=[candidate],
            draft=unknown_skill_draft,
        )
    assert unknown_skill_error.value.codes == ["unknown_skill"]


@pytest.mark.parametrize(
    ("case", "candidate_side_effect", "tool", "omit_tool", "expected_code"),
    [
        ("node-write", SkillSideEffect.LOCAL_WRITE, _read_tool(), False, "deepsearch_node_side_effect_not_allowed"),
        ("tool-missing", SkillSideEffect.READ, None, False, "deepsearch_tool_missing"),
        (
            "tool-disabled",
            SkillSideEffect.READ,
            _read_tool().model_copy(update={"enabled": False}),
            False,
            "deepsearch_tool_disabled",
        ),
        (
            "tool-write",
            SkillSideEffect.READ,
            _read_tool().model_copy(update={"side_effect": "write"}),
            False,
            "deepsearch_tool_not_read_only",
        ),
        ("tool-omitted", SkillSideEffect.READ, _read_tool(), True, "required_tool_mismatch"),
    ],
)
def test_deepsearch_plan_compiler_rejects_unsafe_or_unresolved_tools(
    case: str,
    candidate_side_effect: SkillSideEffect,
    tool: ToolDefinition | None,
    omit_tool: bool,
    expected_code: str,
) -> None:
    del case
    requirement = _complete_requirement()
    graph = build_problem_graph(requirement=requirement, questions=_problem_questions())
    candidate = _candidate(side_effect=candidate_side_effect)
    draft = _draft(graph, candidate)
    if omit_tool:
        draft.nodes[0].required_tool_names = []
    compiler = _compiler(tool)

    with pytest.raises(PlanValidationError) as caught:
        compiler.compile(
            run_id=requirement.run_id,
            requirement=requirement,
            graph=graph,
            intent=_intent(),
            routing_result=None,
            candidates=[candidate],
            draft=draft,
        )

    assert expected_code in caught.value.codes


def test_deepsearch_plan_compiler_rejects_non_web_tools() -> None:
    requirement = _complete_requirement()
    graph = build_problem_graph(requirement=requirement, questions=_problem_questions())
    candidate = _candidate()
    candidate.profile.required_tools = ["data_query"]
    draft = _draft(graph, candidate)
    draft.nodes[0].required_tool_names = ["data_query"]
    compiler = _compiler(
        ToolDefinition(
            id="tool_data_query",
            name="data_query",
            description="Read an internal data source",
            category="data",
            side_effect="read",
        )
    )

    with pytest.raises(PlanValidationError) as caught:
        compiler.compile(
            run_id=requirement.run_id,
            requirement=requirement,
            graph=graph,
            intent=_intent(),
            routing_result=None,
            candidates=[candidate],
            draft=draft,
        )

    assert caught.value.codes == ["deepsearch_tool_not_supported"]


def test_planning_pipeline_uses_one_canonical_requirement_input_and_builds_one_waiting_plan() -> None:
    requirement = _complete_requirement()
    graph = build_problem_graph(requirement=requirement, questions=_problem_questions())
    candidate = _candidate()
    draft = _draft(graph, candidate)
    tool = _read_tool()
    expected_input = canonical_planning_input(requirement)
    calls: dict[str, object] = {}

    class RecordingRouter:
        catalog = TaskScenarioRouter().catalog

        def route(
            self,
            content: str,
            *,
            project_summary: str = "",
            thread_summary: str = "",
        ):
            calls["router"] = (content, project_summary, thread_summary)
            return TaskScenarioRouter(self.catalog).route(content)

    class RecordingIntentAnalyzer:
        async def analyze(self, content: str, **kwargs: object):
            calls["intent"] = (content, kwargs)
            return _intent(), []

    class RecordingProblemGraphPlanner:
        async def build(
            self,
            *,
            requirement: RequirementVersionV1,
            planning_input: str,
            model: object | None,
        ) -> ProblemGraphV1:
            calls["graph"] = (requirement, planning_input, model)
            return graph

    class RecordingRetriever:
        def retrieve(self, **kwargs: object):
            calls["retriever"] = kwargs
            return [candidate], []

    class RecordingDraftPlanner:
        async def create_draft(self, **kwargs: object) -> SkillPlanDraft:
            calls["draft"] = kwargs
            return draft

    model = object()
    pipeline = DeepSearchPlanningPipeline(
        task_router=RecordingRouter(),
        intent_analyzer=RecordingIntentAnalyzer(),
        problem_graph_planner=RecordingProblemGraphPlanner(),
        candidate_retriever=RecordingRetriever(),
        draft_planner=RecordingDraftPlanner(),
        compiler=_compiler(tool),
        model=model,
    )
    run = _deepsearch_run()
    user = User(
        id=run.user_id,
        workspace_id=run.workspace_id,
        default_project_id=run.project_id,
        name="DeepSearch owner",
        role="user",
        personal_agent_id="agent_1",
    )
    created_at = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)

    plan, snapshot = asyncio.run(
        pipeline.create_plan(
            run=run,
            requirement=requirement,
            user=user,
            created_at=created_at,
        )
    )

    assert calls["router"] == (expected_input, "", "")
    assert calls["intent"][0] == expected_input  # type: ignore[index]
    assert calls["graph"] == (requirement, expected_input, model)
    assert calls["retriever"]["planning_input"] == expected_input  # type: ignore[index]
    assert calls["retriever"]["requirement"] == requirement  # type: ignore[index]
    assert calls["retriever"]["graph"] == graph  # type: ignore[index]
    assert calls["draft"]["planning_input"] == expected_input  # type: ignore[index]
    assert calls["draft"]["graph"] == graph  # type: ignore[index]
    assert plan.status is SkillPlanStatus.WAITING_APPROVAL
    assert plan.routing_result is not None
    assert plan.plan_content_hash == plan_content_hash(plan)
    assert snapshot.plan_version_id == f"{plan.id}:v1"
