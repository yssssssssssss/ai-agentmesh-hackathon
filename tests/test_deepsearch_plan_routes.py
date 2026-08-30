from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi import HTTPException

import agentmesh.routes.agent_runs as agent_run_routes
import agentmesh.routes.chat as chat_routes
from agentmesh.artifacts import DeepSearchPlanSnapshotV1
from agentmesh.deepsearch.contracts import (
    ProblemQuestionV1,
    RequirementPayloadV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    build_problem_graph,
    problem_question_id,
    requirement_content_hash,
)
from agentmesh.deepsearch.planning import build_deepsearch_plan_snapshot, plan_content_hash
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatThread,
    DeepSearchBudgetV1,
    SkillCandidate,
    SkillCandidateScore,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillIntent,
    SkillLifecycleStage,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanStatus,
    SkillPlanUpdateRequest,
    SkillPlanVersionRequest,
    SkillSourceScope,
    ToolDefinition,
    now_utc,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.resources import build_skill_resource_manifest_snapshot
from agentmesh.store import SQLiteStore


def _save_candidate(
    repository: SQLiteStore,
    *,
    skill_id: str,
    tool_names: list[str],
) -> SkillCandidate:
    content_hash = ("a" if skill_id.endswith("primary") else "b") * 64
    name = skill_id.removeprefix("skill_").replace("_", "-")
    skill_path = repository.db_path.parent / "skills" / name / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text("test skill", encoding="utf-8")
    definition = SkillDefinition(
        id=skill_id,
        name=name,
        title=name.title(),
        description=f"Run {name}",
        instructions="Use trustworthy sources.",
        source_path=str(skill_path),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=content_hash,
        version="1",
    )
    profile = SkillCapabilityProfile(
        id=skill_id,
        skill_id=skill_id,
        skill_name=name,
        skill_version=definition.version,
        skill_content_hash=definition.content_hash,
        profile_version="1",
        profile_content_hash=content_hash,
        primary_stage=SkillLifecycleStage.PRE_DESIGN,
        capability_type=SkillCapabilityType.RESEARCH,
        input_kinds=["request"],
        output_kinds=["report"],
        required_tools=tool_names,
    )
    repository.save_skill_definition(definition, defer_vector=True)
    repository.save_skill_capability_profile(profile, defer_vector=True)
    return SkillCandidate(
        skill_id=definition.id,
        skill_name=definition.name,
        title=definition.title,
        description=definition.description,
        profile=profile,
        score=SkillCandidateScore(),
        reason=f"Use {definition.title}",
    )


def _prepare_deepsearch_plan(
    repository: SQLiteStore,
    *,
    suffix: str,
) -> tuple[AgentRun, SkillPlan, list[SkillCandidate]]:
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    created_at = now_utc()
    thread = repository.add_chat_thread(
        ChatThread(
            id=f"thread_deepsearch_plan_route_{suffix}",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="DeepSearch route test",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    for tool_name in ("web_research",):
        tool = repository.save_tool_definition(
            ToolDefinition(
                id=f"tool_{tool_name}",
                name=tool_name,
                external_name=tool_name,
                description=f"Read with {tool_name}",
                category="research",
                side_effect="read",
            )
        )
        repository.save_agent_tool_grant(
            AgentToolGrant(
                agent_id=USER.personal_agent_id,
                tool_id=tool.id,
                granted_by=USER.id,
            )
        )
    primary = _save_candidate(
        repository,
        skill_id="skill_primary",
        tool_names=["web_research"],
    )
    optional = _save_candidate(
        repository,
        skill_id="skill_optional",
        tool_names=["web_research"],
    )
    run, created = repository.claim_new_agent_run(
        AgentRun(
            id=f"run_deepsearch_plan_route_{suffix}",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Compare collaboration platforms",
            client_turn_id=f"turn_deepsearch_plan_route_{suffix}",
            status=AgentRunStatus.PLANNING,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_version="v1",
            orchestration_mode="execute",
            absolute_expires_at=created_at + timedelta(days=7),
            deepsearch_budget=DeepSearchBudgetV1(),
            created_at=created_at,
            updated_at=created_at,
        )
    )
    assert created
    assert run.client_turn_id is not None
    assert run.create_request_hash is not None
    payload = RequirementPayloadV1(
        goal="Compare collaboration platforms",
        scope=RequirementScopeV1(regions=["China"]),
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_comparison",
                statement="Compare the leading platforms",
            )
        ],
        deliverables=["Research report"],
    )
    requirement = RequirementVersionV1(
        id=f"requirement_{run.id}_v1",
        run_id=run.id,
        version=1,
        request_key=run.client_turn_id,
        request_hash=run.create_request_hash,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=created_at,
    )
    appended = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement.model_dump(mode="json"),
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
        checked_at=created_at,
    )
    assert appended is not None
    question = ProblemQuestionV1(
        id=problem_question_id("Which platforms lead the market?"),
        question="Which platforms lead the market?",
        required=True,
        success_criterion_ids=["criterion_comparison"],
        evidence_requirements=["Public market evidence"],
        acceptance_criteria=["Name and compare leading platforms"],
    )
    graph = build_problem_graph(requirement=requirement, questions=[question])
    primary_definition = repository.get_skill_definition(primary.skill_id)
    assert primary_definition is not None
    plan = SkillPlan(
        id=f"plan_{run.id}",
        run_id=run.id,
        status=SkillPlanStatus.WAITING_APPROVAL,
        intent=SkillIntent(
            goal=requirement.payload.goal,
            input_kinds=["request"],
            deliverables=["report"],
        ),
        candidate_skill_ids=[primary.skill_id, optional.skill_id],
        output_contract=["report"],
        preferred_order=[primary.skill_id],
        nodes=[
            SkillPlanNode(
                id="node_primary",
                skill_id=primary.skill_id,
                skill_version=primary.profile.skill_version,
                skill_content_hash=primary.profile.skill_content_hash,
                reason=primary.reason,
                question_ids=[question.id],
                input_bindings=["user.request"],
                output_contract=["report"],
                required_tool_names=["web_research"],
                resource_manifest=build_skill_resource_manifest_snapshot(
                    primary_definition,
                    primary.profile,
                ),
            )
        ],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph=graph.model_dump(mode="json"),
        problem_graph_hash=graph.content_hash,
        created_at=created_at,
        updated_at=created_at,
    )
    plan.plan_content_hash = plan_content_hash(plan)
    snapshot = build_deepsearch_plan_snapshot(run=run, plan=plan, created_at=created_at)
    committed = repository.save_deepsearch_plan_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        expected_requirement_version=requirement.version,
        plan=plan,
        plan_snapshot=snapshot,
        checked_at=created_at,
    )
    assert committed is not None
    saved_plan, saved_run, _saved_snapshot = committed
    return saved_run, saved_plan, [primary, optional]


class _HealthyGateway:
    @staticmethod
    def describe(_tool_name: str):  # noqa: ANN205
        return type(
            "Descriptor",
            (),
            {"execution_mode": "real", "health_state": "healthy"},
        )()


class _RuntimeSpy:
    enabled = True

    def __init__(self, repository: SQLiteStore, *, start_error: Exception | None = None) -> None:
        self.repository = repository
        self.started: list[SkillPlan] = []
        self.start_error = start_error
        self.tool_factory = type("ToolFactory", (), {"gateway": _HealthyGateway()})()

    async def start_approved_skill_plan(self, plan_id: str, *, user) -> None:  # noqa: ANN001
        assert user.id == USER.id
        plan = self.repository.get_skill_plan(plan_id)
        assert plan is not None
        self.started.append(plan)
        if self.start_error is not None:
            raise self.start_error


def _install_route_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    repository: SQLiteStore,
    candidates: list[SkillCandidate],
) -> None:
    monkeypatch.setenv("AGENTMESH_SKILL_ORCHESTRATION", "execute")
    monkeypatch.setattr(agent_run_routes, "store", repository)
    monkeypatch.setattr(agent_run_routes, "_current_plan_candidates", lambda *_args: candidates)


def test_deepsearch_plan_patch_writes_authoritative_next_snapshot_and_renews_ttl(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-route-patch.sqlite3")
    run, plan, candidates = _prepare_deepsearch_plan(repository, suffix="patch")
    _install_route_dependencies(monkeypatch, repository, candidates)

    response = agent_run_routes.update_agent_run_plan(
        run.id,
        SkillPlanUpdateRequest(
            expected_version=plan.version,
            selected_skill_ids=[candidate.skill_id for candidate in candidates],
            preferred_order=[candidate.skill_id for candidate in candidates],
        ),
        user=USER,
    )

    saved_plan = repository.get_skill_plan(plan.id)
    saved_run = repository.get_agent_run(run.id)
    assert saved_plan is not None and saved_run is not None
    assert response.plan.id == saved_plan.id
    public_plan = response.plan.model_dump(mode="json")
    assert "deepsearch_syntheses" not in public_plan
    assert "review_outcomes" not in public_plan
    assert "finalization_input_hashes" not in public_plan
    assert "resource_manifest" not in public_plan["nodes"][0]
    assert saved_plan.version == plan.version + 1
    assert saved_plan.plan_content_hash == plan_content_hash(saved_plan)
    optional_node = next(node for node in saved_plan.nodes if node.skill_id == "skill_optional")
    assert optional_node.required_tool_names == ["web_research"]
    expected_snapshot = build_deepsearch_plan_snapshot(
        run=saved_run,
        plan=saved_plan,
        created_at=saved_plan.updated_at,
    )
    saved_snapshot = repository.get_artifact(expected_snapshot.id)
    assert saved_snapshot is not None
    assert saved_snapshot.plan_version_id == f"{plan.id}:v{plan.version + 1}"
    assert DeepSearchPlanSnapshotV1.model_validate_json(saved_snapshot.content).plan_content_hash == (
        saved_plan.plan_content_hash
    )
    assert saved_run.interaction_expires_at == saved_plan.updated_at + timedelta(hours=24)
    assert saved_run.interaction_expires_at > run.interaction_expires_at  # type: ignore[operator]


def test_deepsearch_plan_approve_freezes_n_plus_one_before_starting_runtime(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-route-approve.sqlite3")
    run, plan, candidates = _prepare_deepsearch_plan(repository, suffix="approve")
    runtime = _RuntimeSpy(repository)
    _install_route_dependencies(monkeypatch, repository, candidates)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)

    response = asyncio.run(
        agent_run_routes.approve_agent_run_plan(
            run.id,
            SkillPlanVersionRequest(expected_version=plan.version),
            user=USER,
        )
    )

    assert response.plan.version == plan.version + 1
    assert response.plan.status is SkillPlanStatus.APPROVED
    assert response.plan.plan_content_hash == plan.plan_content_hash
    assert response.plan.approved_plan_artifact_id is not None
    snapshot = repository.get_artifact(response.plan.approved_plan_artifact_id)
    assert snapshot is not None
    assert snapshot.plan_version_id == f"{plan.id}:v{plan.version + 1}"
    assert DeepSearchPlanSnapshotV1.model_validate_json(snapshot.content).plan_version == plan.version + 1
    assert response.run.status is AgentRunStatus.RUNNING
    assert response.run.interaction_expires_at is None
    assert len(runtime.started) == 1
    assert runtime.started[0].id == response.plan.id
    assert runtime.started[0].version == response.plan.version


def test_deepsearch_plan_get_uses_public_projection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-route-get.sqlite3")
    run, plan, candidates = _prepare_deepsearch_plan(repository, suffix="get")
    _install_route_dependencies(monkeypatch, repository, candidates)

    response = agent_run_routes.get_agent_run_plan(run.id, user=USER)

    assert response.plan.id == plan.id
    public_plan = response.plan.model_dump(mode="json")
    assert "deepsearch_syntheses" not in public_plan
    assert "review_outcomes" not in public_plan
    assert "finalization_input_hashes" not in public_plan
    assert "resource_manifest" not in public_plan["nodes"][0]


def test_deepsearch_plan_approval_conflict_does_not_start_runtime(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-route-conflict.sqlite3")
    run, plan, candidates = _prepare_deepsearch_plan(repository, suffix="conflict")
    runtime = _RuntimeSpy(repository)
    _install_route_dependencies(monkeypatch, repository, candidates)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            agent_run_routes.approve_agent_run_plan(
                run.id,
                SkillPlanVersionRequest(expected_version=plan.version + 1),
                user=USER,
            )
        )

    assert error.value.status_code == 409
    assert runtime.started == []
    assert repository.get_agent_run(run.id).status is AgentRunStatus.WAITING_PLAN_APPROVAL  # type: ignore[union-attr]
    assert repository.get_skill_plan(plan.id).status is SkillPlanStatus.WAITING_APPROVAL  # type: ignore[union-attr]


def test_deepsearch_plan_approval_runtime_unavailable_keeps_waiting_state(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-route-runtime-off.sqlite3")
    run, plan, candidates = _prepare_deepsearch_plan(repository, suffix="runtime_off")
    _install_route_dependencies(monkeypatch, repository, candidates)

    class DisabledRuntime:
        enabled = False

    monkeypatch.setattr(chat_routes.agent, "agent_runtime", DisabledRuntime())

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            agent_run_routes.approve_agent_run_plan(
                run.id,
                SkillPlanVersionRequest(expected_version=plan.version),
                user=USER,
            )
        )

    assert error.value.status_code == 409
    assert error.value.detail == {"code": "deepsearch_execution_unavailable"}
    assert repository.get_agent_run(run.id).status is AgentRunStatus.WAITING_PLAN_APPROVAL  # type: ignore[union-attr]
    assert repository.get_skill_plan(plan.id).status is SkillPlanStatus.WAITING_APPROVAL  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("execution_mode", "health_state"),
    [("fake", "healthy"), ("real", "unavailable")],
)
def test_deepsearch_plan_approval_requires_healthy_real_tool_runtime(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    execution_mode: str,
    health_state: str,
) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-plan-route-tool-{execution_mode}-{health_state}.sqlite3")
    run, plan, candidates = _prepare_deepsearch_plan(
        repository,
        suffix=f"tool_{execution_mode}_{health_state}",
    )
    runtime = _RuntimeSpy(repository)
    runtime.tool_factory.gateway = type(
        "Gateway",
        (),
        {
            "describe": lambda _self, _name: type(
                "Descriptor",
                (),
                {"execution_mode": execution_mode, "health_state": health_state},
            )()
        },
    )()
    _install_route_dependencies(monkeypatch, repository, candidates)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            agent_run_routes.approve_agent_run_plan(
                run.id,
                SkillPlanVersionRequest(expected_version=plan.version),
                user=USER,
            )
        )

    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "deepsearch_tool_runtime_unavailable",
        "tools": ["web_research"],
    }
    assert runtime.started == []
    assert repository.get_agent_run(run.id).status is AgentRunStatus.WAITING_PLAN_APPROVAL  # type: ignore[union-attr]
    assert repository.get_skill_plan(plan.id).status is SkillPlanStatus.WAITING_APPROVAL  # type: ignore[union-attr]


def test_deepsearch_executor_start_failure_leaves_approved_run_for_recovery(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-plan-route-start-failure.sqlite3")
    run, plan, candidates = _prepare_deepsearch_plan(repository, suffix="start_failure")
    runtime = _RuntimeSpy(repository, start_error=RuntimeError("executor unavailable"))
    _install_route_dependencies(monkeypatch, repository, candidates)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            agent_run_routes.approve_agent_run_plan(
                run.id,
                SkillPlanVersionRequest(expected_version=plan.version),
                user=USER,
            )
        )

    assert error.value.status_code == 503
    assert error.value.detail == {"code": "deepsearch_runtime_unavailable"}
    saved_run = repository.get_agent_run(run.id)
    saved_plan = repository.get_skill_plan(plan.id)
    assert saved_run is not None and saved_run.status is AgentRunStatus.RUNNING
    assert saved_plan is not None and saved_plan.status is SkillPlanStatus.APPROVED
    assert saved_plan.version == plan.version + 1
    assert saved_run.interaction_expires_at is None


def test_standard_plan_routes_keep_generic_update_and_approval_behavior(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "standard-plan-route-regression.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    primary = _save_candidate(repository, skill_id="skill_primary", tool_names=[])
    optional = _save_candidate(repository, skill_id="skill_optional", tool_names=["web_research"])
    run = repository.save_agent_run(
        AgentRun(
            id="run_standard_plan_route",
            thread_id="thread_standard_plan_route",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="Create a report",
            status=AgentRunStatus.WAITING_PLAN_APPROVAL,
            orchestration_mode="execute",
        )
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_standard_plan_route",
            run_id=run.id,
            status=SkillPlanStatus.WAITING_APPROVAL,
            intent=SkillIntent(
                goal="Create a report",
                input_kinds=["request"],
                deliverables=["report"],
            ),
            candidate_skill_ids=[primary.skill_id, optional.skill_id],
            output_contract=["report"],
            preferred_order=[primary.skill_id],
            nodes=[
                SkillPlanNode(
                    id="node_standard_primary",
                    skill_id=primary.skill_id,
                    skill_version=primary.profile.skill_version,
                    skill_content_hash=primary.profile.skill_content_hash,
                    reason=primary.reason,
                    input_bindings=["user.request"],
                    output_contract=["report"],
                )
            ],
        )
    )
    run.plan_id = plan.id
    repository.save_agent_run(run)
    candidates = [primary, optional]
    _install_route_dependencies(monkeypatch, repository, candidates)
    runtime = _RuntimeSpy(repository)
    monkeypatch.setattr(chat_routes.agent, "agent_runtime", runtime)

    updated = agent_run_routes.update_agent_run_plan(
        run.id,
        SkillPlanUpdateRequest(
            expected_version=plan.version,
            selected_skill_ids=[candidate.skill_id for candidate in candidates],
            preferred_order=[candidate.skill_id for candidate in candidates],
        ),
        user=USER,
    )
    optional_node = next(node for node in updated.plan.nodes if node.skill_id == optional.skill_id)
    assert updated.plan.version == plan.version + 1
    assert optional_node.required_tool_names == []

    approved = asyncio.run(
        agent_run_routes.approve_agent_run_plan(
            run.id,
            SkillPlanVersionRequest(expected_version=updated.plan.version),
            user=USER,
        )
    )
    assert approved.plan.version == updated.plan.version + 1
    assert approved.plan.status is SkillPlanStatus.APPROVED
    assert approved.run.status is AgentRunStatus.RUNNING
    assert runtime.started == [approved.plan]
