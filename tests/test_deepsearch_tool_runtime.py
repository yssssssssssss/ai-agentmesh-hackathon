from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agentmesh.acquisition import AcquiredEvidenceItem
from agentmesh.agent_runtime.hooks import AgentMeshRunHooks
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.deepsearch.contracts import (
    ProblemGraphV1,
    ProblemQuestionV1,
    problem_graph_hash,
    problem_question_id,
)
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ArtifactVerificationState,
    DeepSearchBudgetReservationV1,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    DeepSearchEvidenceBindingDraft,
    DeepSearchEvidenceItemV1,
    SkillDefinition,
    SkillIntent,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNode,
    SkillResultSource,
    SkillSourceScope,
    Source,
    ToolDefinition,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.deepsearch import (
    DeepSearchToolRuntimeError,
    build_deepsearch_tool_invocation,
    normalize_deepsearch_evidence_bindings,
    normalize_deepsearch_tool_evidence,
)
from agentmesh.tool_runtime.factory import AgentMeshToolFactory
from agentmesh.tool_runtime.gateway import ToolGateway
from agentmesh.tools import ensure_tool_seed_data


def test_run_context_round_trips_deepsearch_node_lineage() -> None:
    context = AgentMeshRunContext(
        user_id="user_a",
        workspace_id="workspace_a",
        project_id="project_a",
        thread_id="thread_a",
        run_id="run_a",
        requirement_version_id="requirement_v1",
        plan_id="plan_a",
        plan_version=3,
        node_id="node_a",
        node_step_number=4,
        node_attempt=2,
        skill_id="skill_a",
    )

    restored = AgentMeshRunContext.model_validate(context.model_dump(mode="json"))

    assert restored.requirement_version_id == "requirement_v1"
    assert restored.plan_version == 3
    assert restored.node_step_number == 4
    assert restored.node_attempt == 2


def test_deepsearch_tool_hook_does_not_consume_the_generic_tool_counter() -> None:
    run = AgentRun(
        id="run_hook",
        thread_id="thread_hook",
        user_id="user_a",
        workspace_id="workspace_a",
        project_id="project_a",
        input_text="Research",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    )
    consumed: list[str] = []
    events: list[str] = []

    class Repository:
        @staticmethod
        def get_agent_run(_run_id: str) -> AgentRun:
            return run

        @staticmethod
        def consume_agent_run_tool_call(run_id: str) -> int:
            consumed.append(run_id)
            return 1

        @staticmethod
        def append_agent_run_event(_run_id: str, event_type: str, _payload: object) -> None:
            events.append(event_type)

    context = AgentMeshRunContext(
        user_id=run.user_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        thread_id=run.thread_id,
        run_id=run.id,
        requirement_version_id="requirement_hook",
    )

    asyncio.run(
        AgentMeshRunHooks(Repository()).on_tool_start(  # type: ignore[arg-type]
            SimpleNamespace(context=context),
            SimpleNamespace(name="agent"),
            SimpleNamespace(name="web_research"),
        )
    )

    assert consumed == []
    assert context.tool_call_count == 0
    assert events == ["sdk_tool_hook_started"]


def test_runtime_rejects_non_web_deepsearch_tool_before_repository_access() -> None:
    node = SkillPlanNode(
        id="node_forbidden_tool",
        skill_id="skill_forbidden_tool",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="Attempt an unsupported read",
        required_tool_names=["data_query"],
    )
    plan = SkillPlan(
        id="plan_forbidden_tool",
        run_id="run_forbidden_tool",
        intent=SkillIntent(goal="Research"),
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    )
    run = AgentRun(
        id=plan.run_id,
        thread_id="thread_forbidden_tool",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="Research",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        plan_id=plan.id,
    )

    with pytest.raises(RuntimeError, match="deepsearch_tool_policy_violation"):
        AgentRuntimeService._resolve_plan_node_security(
            object.__new__(AgentRuntimeService),
            plan=plan,
            node=node,
            run=run,
            user=USER,
        )


def test_runtime_derives_deepsearch_node_lineage_from_the_persisted_plan() -> None:
    node = SkillPlanNode(
        id="node_b",
        skill_id="skill_a",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="Collect evidence",
        attempt=2,
    )
    plan = SkillPlan(
        id="plan_a",
        run_id="run_a",
        version=3,
        intent=SkillIntent(goal="Research"),
        nodes=[
            node.model_copy(update={"id": "node_a"}),
            node,
        ],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id="requirement_v1",
    )
    run = AgentRun(
        id="run_a",
        thread_id="thread_a",
        user_id="user_a",
        workspace_id="workspace_a",
        project_id="project_a",
        input_text="Research",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        plan_id=plan.id,
    )

    assert AgentRuntimeService._deepsearch_node_lineage(
        plan=plan,
        node=node,
        run=run,
    ) == {
        "requirement_version_id": "requirement_v1",
        "plan_version": 3,
        "node_step_number": 2,
        "node_attempt": 2,
    }

    with pytest.raises(RuntimeError, match="deepsearch_tool_lineage_incomplete"):
        AgentRuntimeService._deepsearch_node_lineage(
            plan=plan,
            node=node.model_copy(update={"attempt": 0}),
            run=run,
        )


def test_runtime_rejects_model_owned_deepsearch_evidence_identity() -> None:
    node = SkillPlanNode(
        id="node_a",
        skill_id="skill_a",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="Collect evidence",
        question_ids=[],
        attempt=1,
    )
    plan = SkillPlan(
        id="plan_a",
        run_id="run_a",
        intent=SkillIntent(goal="Research"),
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id="requirement_v1",
    )
    run = AgentRun(
        id="run_a",
        thread_id="thread_a",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="Research",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        plan_id=plan.id,
    )
    output = SkillNodeResult(
        id="model_owned_result",
        node_id=node.id,
        skill_id=node.skill_id,
        summary="Model output",
        evidence_items=[
            DeepSearchEvidenceItemV1(
                id="model_owned_evidence",
                node_result_id="model_owned_result",
                source_id="source_a",
                evidence_artifact_id="artifact_a",
            )
        ],
    )

    with pytest.raises(ValueError, match="deepsearch_model_owned_evidence_forbidden"):
        AgentRuntimeService._normalize_skill_node_result(
            object.__new__(AgentRuntimeService),
            output,
            total_tokens=1,
            plan=plan,
            node=node,
            skill=SimpleNamespace(id=node.skill_id),
            run=run,
            user=USER,
            allowed_source_ids=set(),
            allowed_artifact_ids=set(),
            allowed_resource_references=set(),
            upstream_source_origins={},
        )


def _tool_definition() -> ToolDefinition:
    return ToolDefinition(
        id="tool_web_research",
        name="web_research",
        description="Search the web",
        category="research",
        implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
        implementation_version="1",
    )


def _deepsearch_context() -> AgentMeshRunContext:
    return AgentMeshRunContext(
        user_id="user_a",
        workspace_id="workspace_a",
        project_id="project_a",
        thread_id="thread_a",
        run_id="run_a",
        requirement_version_id="requirement_v1",
        plan_id="plan_a",
        plan_version=3,
        node_id="node_a",
        node_step_number=4,
        node_attempt=2,
        skill_id="skill_a",
    )


def test_tool_invocation_identity_is_server_derived_from_frozen_lineage() -> None:
    invocation = build_deepsearch_tool_invocation(
        context=_deepsearch_context(),
        definition=_tool_definition(),
        arguments={"query": "market", "limit": 3},
        tool_call_id="tool_call_a",
    )

    assert invocation.canonical_arguments_hash == (
        "15f51fed1cf6351a993a85a36f101cda8c1e4c0260e9cca1442e3ac64b14bd0c"
    )
    assert invocation.operation_key == (
        "0bbc69c2880a347bcdc29de9250223ebad1d2506e24220ad400b2ab6b15b99d7"
    )

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_tool_lineage_incomplete"):
        build_deepsearch_tool_invocation(
            context=_deepsearch_context().model_copy(update={"node_attempt": None}),
            definition=_tool_definition(),
            arguments={"query": "market"},
            tool_call_id="tool_call_b",
        )

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_tool_lineage_incomplete"):
        build_deepsearch_tool_invocation(
            context=_deepsearch_context().model_copy(update={"node_step_number": None}),
            definition=_tool_definition(),
            arguments={"query": "market"},
            tool_call_id="tool_call_c",
        )


def _evidence(source_id: str, excerpt: str) -> AcquiredEvidenceItem:
    return AcquiredEvidenceItem(
        source_id=source_id,
        content_provider="tavily",
        excerpt=excerpt,
        retrieved_at=datetime(2026, 8, 27, tzinfo=UTC),
        content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    )


def test_evidence_normalization_is_stable_across_provider_result_order() -> None:
    context = _deepsearch_context()
    definition = _tool_definition()
    invocation = build_deepsearch_tool_invocation(
        context=context,
        definition=definition,
        arguments={"query": "market"},
        tool_call_id="tool_call_a",
    )
    rows = [
        (
            Source(id="provider_b", title="B", source_type="web_page", reference=" https://b.test "),
            _evidence("provider_b", "Evidence B"),
        ),
        (
            Source(id="provider_a", title="A", source_type="web_page", reference="https://a.test"),
            _evidence("provider_a", "Evidence A"),
        ),
    ]

    first = normalize_deepsearch_tool_evidence(
        context=context,
        definition=definition,
        invocation=invocation,
        value={
            "sources": [source.model_dump(mode="python") for source, _evidence_item in rows],
            "source_evidence": [evidence.model_dump(mode="python") for _source, evidence in rows],
        },
        execution_mode="real",
    )
    second = normalize_deepsearch_tool_evidence(
        context=context,
        definition=definition,
        invocation=invocation,
        value={
            "sources": [source.model_dump(mode="python") for source, _evidence_item in reversed(rows)],
            "source_evidence": [evidence.model_dump(mode="python") for _source, evidence in reversed(rows)],
        },
        execution_mode="real",
    )

    assert [source.id for source in first.sources] == [source.id for source in second.sources]
    assert [source.reference for source in first.sources] == ["https://a.test", "https://b.test"]
    assert [envelope.source_id for envelope in first.envelopes] == [source.id for source in first.sources]
    assert [item.source_id for item in first.source_evidence] == [source.id for source in first.sources]
    assert all(envelope.operation_key == invocation.operation_key for envelope in first.envelopes)
    assert all(artifact.verification_state is ArtifactVerificationState.SEALED for artifact in first.artifacts)
    assert all(artifact.step_number == context.node_step_number for artifact in first.artifacts)
    assert [artifact.id for artifact in first.artifacts] == [artifact.id for artifact in second.artifacts]

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_tool_execution_not_real"):
        normalize_deepsearch_tool_evidence(
            context=context,
            definition=definition,
            invocation=invocation,
            value={"sources": [], "source_evidence": []},
            execution_mode="fake",
        )


def test_evidence_normalization_rejects_ambiguous_sort_keys() -> None:
    context = _deepsearch_context()
    definition = _tool_definition()
    invocation = build_deepsearch_tool_invocation(
        context=context,
        definition=definition,
        arguments={"query": "market"},
        tool_call_id="tool_call_a",
    )
    rows = [
        (
            Source(id="provider_a", title="Same", source_type="web_page", reference="https://a.test"),
            _evidence("provider_a", "Same excerpt"),
        ),
        (
            Source(id="provider_b", title="Same", source_type="web_page", reference="https://a.test"),
            _evidence("provider_b", "Same excerpt"),
        ),
    ]

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_tool_evidence_invalid"):
        normalize_deepsearch_tool_evidence(
            context=context,
            definition=definition,
            invocation=invocation,
            value={
                "sources": [source.model_dump(mode="python") for source, _evidence_item in rows],
                "source_evidence": [
                    evidence.model_dump(mode="python") for _source, evidence in rows
                ],
            },
            execution_mode="real",
        )


def test_server_normalizes_binding_draft_against_sealed_tool_evidence() -> None:
    context = _deepsearch_context()
    definition = _tool_definition()
    invocation = build_deepsearch_tool_invocation(
        context=context,
        definition=definition,
        arguments={"query": "market"},
        tool_call_id="tool_call_a",
    )
    source = Source(
        id="provider_a",
        title="A",
        source_type="web_page",
        reference="https://a.test",
    )
    batch = normalize_deepsearch_tool_evidence(
        context=context,
        definition=definition,
        invocation=invocation,
        value={
            "sources": [source.model_dump(mode="python")],
            "source_evidence": [_evidence(source.id, "Evidence A").model_dump(mode="python")],
        },
        execution_mode="real",
    )
    draft = DeepSearchEvidenceBindingDraft(
        question_ids=["question_a"],
        success_criterion_ids=["criterion_a"],
        source_id=batch.sources[0].id,
        evidence_artifact_id=batch.artifacts[0].id,
    )

    items = normalize_deepsearch_evidence_bindings(
        context=context,
        invocation=invocation,
        node_result_id="result_a",
        drafts=[draft],
        node_question_ids={"question_a"},
        allowed_success_criterion_ids={"criterion_a"},
        artifacts={batch.artifacts[0].id: batch.artifacts[0]},
    )

    assert len(items) == 1
    assert items[0].node_result_id == "result_a"
    assert items[0].evidence_artifact_id == batch.artifacts[0].id
    assert items[0].source_id == batch.sources[0].id

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_evidence_binding_invalid"):
        normalize_deepsearch_evidence_bindings(
            context=context,
            invocation=invocation,
            node_result_id="result_a",
            drafts=[draft.model_copy(update={"question_ids": ["question_other"]})],
            node_question_ids={"question_a"},
            allowed_success_criterion_ids={"criterion_a"},
            artifacts={batch.artifacts[0].id: batch.artifacts[0]},
        )

    invalid_content = "{}"
    invalid_artifact = batch.artifacts[0].model_copy(
        update={
            "content": invalid_content,
            "content_hash": hashlib.sha256(invalid_content.encode("utf-8")).hexdigest(),
            "size_bytes": len(invalid_content.encode("utf-8")),
        }
    )
    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_evidence_binding_invalid"):
        normalize_deepsearch_evidence_bindings(
            context=context,
            invocation=invocation,
            node_result_id="result_a",
            drafts=[draft],
            node_question_ids={"question_a"},
            allowed_success_criterion_ids={"criterion_a"},
            artifacts={invalid_artifact.id: invalid_artifact},
        )


class _BindingRepository:
    def __init__(self, *, run: AgentRun, source: Source, artifact) -> None:  # noqa: ANN001
        self.run = run
        self.sources = {source.id: source}
        self.artifacts = {artifact.id: artifact}

    def get_agent_run(self, _run_id: str) -> AgentRun:
        return self.run

    def get_source(self, source_id: str):  # noqa: ANN201
        return self.sources.get(source_id)

    def get_artifact(self, artifact_id: str):  # noqa: ANN201
        return self.artifacts.get(artifact_id)


def _runtime_binding_fixture():  # noqa: ANN202
    question_text = "Which product leads the market?"
    question = ProblemQuestionV1(
        id=problem_question_id(question_text),
        question=question_text,
        required=True,
        success_criterion_ids=["criterion_market"],
        evidence_requirements=["Use traceable market evidence"],
        acceptance_criteria=["Identify the market leader"],
    )
    graph_content = {
        "requirement_version_id": "requirement_binding_v1",
        "questions": [question],
    }
    graph = ProblemGraphV1(
        **graph_content,
        content_hash=problem_graph_hash(graph_content),
    )
    node = SkillPlanNode(
        id="node_binding",
        skill_id="skill_binding",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="Collect evidence",
        question_ids=[question.id],
        required_tool_names=["web_research"],
        attempt=1,
    )
    plan = SkillPlan(
        id="plan_binding",
        run_id="run_binding",
        version=2,
        intent=SkillIntent(goal="Research the market"),
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id=graph.requirement_version_id,
        problem_graph=graph.model_dump(mode="json"),
        problem_graph_hash=graph.content_hash,
    )
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_binding",
        run_id=plan.run_id,
        requirement_version_id=graph.requirement_version_id,
        plan_id=plan.id,
        plan_version=plan.version,
        node_id=node.id,
        node_step_number=1,
        node_attempt=node.attempt,
        skill_id=node.skill_id,
    )
    definition = _tool_definition()
    invocation = build_deepsearch_tool_invocation(
        context=context,
        definition=definition,
        arguments={"query": "market leader"},
        tool_call_id="tool_call_binding",
    )
    provider_source = Source(
        id="provider_binding",
        title="Market source",
        source_type="web_page",
        reference="https://market.test",
    )
    batch = normalize_deepsearch_tool_evidence(
        context=context,
        definition=definition,
        invocation=invocation,
        value={
            "sources": [provider_source.model_dump(mode="python")],
            "source_evidence": [
                _evidence(provider_source.id, "Product A leads the market.").model_dump(
                    mode="python"
                )
            ],
        },
        execution_mode="real",
    )
    maximum = DeepSearchBudgetUsageV1(
        active_seconds=definition.timeout_seconds,
        tool_calls=1,
    )
    actual = DeepSearchBudgetUsageV1(active_seconds=1, tool_calls=1)
    reservation = DeepSearchBudgetReservationV1(
        logical_operation_key=invocation.operation_key,
        invocation_key=invocation.operation_key,
        physical_attempt=1,
        resource_maxima=maximum,
        status="settled",
        actual_usage=actual,
        tool_invocation=invocation,
    )
    run = AgentRun(
        id=plan.run_id,
        thread_id=context.thread_id,
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="Research the market",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        plan_id=plan.id,
        deepsearch_budget=DeepSearchBudgetV1(
            version=2,
            consumed=actual,
            reservations=[reservation],
        ),
    )
    skill = SkillDefinition(
        id=node.skill_id,
        name="binding-research",
        title="Binding research",
        description="Research with evidence",
        instructions="Research",
        source_path="/tmp/binding-research/SKILL.md",
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=node.skill_content_hash,
    )
    source = batch.sources[0]
    artifact = batch.artifacts[0]
    repository = _BindingRepository(run=run, source=source, artifact=artifact)
    runtime = object.__new__(AgentRuntimeService)
    runtime.repository = repository  # type: ignore[assignment]
    draft = DeepSearchEvidenceBindingDraft(
        question_ids=[question.id],
        success_criterion_ids=["criterion_market"],
        source_id=source.id,
        evidence_artifact_id=artifact.id,
    )
    output = {
        "node_id": node.id,
        "skill_id": skill.id,
        "summary": "Product A leads the market.",
        "sources": [
            SkillResultSource(
                id=source.id,
                title=source.title,
                source_type=source.source_type,
                reference=source.reference,
            ).model_dump(mode="python")
        ],
        "evidence_bindings": [draft.model_dump(mode="python")],
        "artifact_ids": [artifact.id],
    }
    return runtime, repository, run, plan, node, skill, context, source, artifact, output


def _normalize_runtime_binding(fixture: tuple, output: dict[str, object]) -> SkillNodeResult:
    runtime, _repository, run, plan, node, skill, context, source, artifact, _output = fixture
    return runtime._normalize_skill_node_result(
        output,
        total_tokens=7,
        plan=plan,
        node=node,
        skill=skill,
        run=run,
        user=USER,
        allowed_source_ids={source.id},
        allowed_artifact_ids={artifact.id},
        allowed_resource_references=set(),
        upstream_source_origins={},
        runtime_context=context,
    )


def test_runtime_materializes_server_owned_evidence_from_binding_draft() -> None:
    fixture = _runtime_binding_fixture()
    output = fixture[-1]

    result = _normalize_runtime_binding(fixture, output)

    assert result.id == "node_result_plan_binding_node_binding_1"
    assert len(result.evidence_items) == 1
    evidence = result.evidence_items[0]
    assert evidence.id.startswith("evidence_")
    assert evidence.node_result_id == result.id
    assert evidence.source_id == result.sources[0].id
    assert evidence.evidence_artifact_id == result.artifact_ids[0]


def test_runtime_rejects_binding_to_unregistered_artifact() -> None:
    fixture = _runtime_binding_fixture()
    repository = fixture[1]
    output = fixture[-1]
    repository.artifacts.clear()

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_evidence_binding_invalid"):
        _normalize_runtime_binding(fixture, output)


def test_runtime_rejects_binding_from_unsettled_tool_invocation() -> None:
    fixture = _runtime_binding_fixture()
    repository = fixture[1]
    output = fixture[-1]
    settled = repository.run.deepsearch_budget.reservations[0]
    reserved = DeepSearchBudgetReservationV1(
        **settled.model_dump(mode="python", exclude={"status", "actual_usage"}),
        status="reserved",
    )
    repository.run = repository.run.model_copy(
        update={
            "deepsearch_budget": DeepSearchBudgetV1(
                version=2,
                consumed=reserved.resource_maxima,
                reservations=[reserved],
            )
        }
    )

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_evidence_binding_invalid"):
        _normalize_runtime_binding(fixture, output)


@pytest.mark.parametrize(
    "binding_update",
    [
        {"question_ids": ["question_0000000000000000"]},
        {"success_criterion_ids": ["criterion_other"]},
    ],
)
def test_runtime_rejects_binding_outside_node_question_scope(
    binding_update: dict[str, object],
) -> None:
    fixture = _runtime_binding_fixture()
    output = dict(fixture[-1])
    binding = dict(output["evidence_bindings"][0])
    binding.update(binding_update)
    output["evidence_bindings"] = [binding]

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_evidence_binding_invalid"):
        _normalize_runtime_binding(fixture, output)


def test_gateway_fails_closed_before_handler_without_real_runtime_descriptor() -> None:
    calls: list[str] = []

    class Gateway(ToolGateway):
        def __init__(self) -> None:
            self.repository = object()  # type: ignore[assignment]

        def handlers(self):  # noqa: ANN201
            return {"web_research": lambda _context, _arguments: calls.append("handler")}

        def describe(self, _tool_name):  # noqa: ANN001, ANN201
            return None

    context = _deepsearch_context()
    definition = _tool_definition()
    invocation = build_deepsearch_tool_invocation(
        context=context,
        definition=definition,
        arguments={"query": "market"},
        tool_call_id="tool_call_a",
    )

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_tool_policy_violation"):
        Gateway().invoke(
            context=context,
            definition=definition,
            arguments={"query": "market"},
            invocation=invocation,
        )

    assert calls == []


def test_factory_routes_deepsearch_through_gateway_invocation_seam_before_handler(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-tools.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_deepsearch_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by=USER.id,
        )
    )
    run = AgentRun(
        id="run_a",
        thread_id="thread_a",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="Research",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    )
    repository.save_agent_run(run.model_copy(update={"planning_mode": AgentPlanningMode.STANDARD}))
    monkeypatch.setattr(repository, "get_agent_run", lambda _run_id: run)
    monkeypatch.setattr(repository, "user_can_execute_agent_run", lambda *_args, **_kwargs: True)
    handler_calls: list[str] = []
    invocations = []

    class Gateway(ToolGateway):
        def handlers(self):  # noqa: ANN201
            return {"web_research": lambda _context, _arguments: handler_calls.append("handler")}

        def invoke(self, **kwargs):  # noqa: ANN003, ANN201
            invocations.append(kwargs["invocation"])
            raise DeepSearchToolRuntimeError("deepsearch_tool_persistence_unavailable")

    tool = AgentMeshToolFactory(repository, gateway=Gateway(repository)).build(
        USER,
        allowed_tool_names={"web_research"},
    )[0]
    context = _deepsearch_context().model_copy(
        update={
            "user_id": USER.id,
            "workspace_id": USER.workspace_id,
            "project_id": USER.default_project_id,
        }
    )

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_tool_persistence_unavailable"):
        asyncio.run(
            tool.on_invoke_tool(
                SimpleNamespace(context=context, tool_call_id="sdk_tool_call_a"),
                json.dumps({"query": "market"}),
            )
        )

    assert len(invocations) == 1
    assert invocations[0].tool_call_id == "sdk_tool_call_a"
    assert invocations[0].plan_version == context.plan_version
    assert handler_calls == []
