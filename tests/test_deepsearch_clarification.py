from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Response

import agentmesh.routes.deepsearch as deepsearch_routes
from agentmesh.app import app
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.deepsearch.contracts import (
    ClarificationAnswerValue,
    ClarificationQuestionDraftV1,
    DeepSearchClarifyRequestV1,
    DeepSearchRetryDisposition,
    ProblemQuestionV1,
    RequirementAmbiguityV1,
    RequirementRefinementDraftV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    build_problem_graph,
    materialize_requirement_payload,
    problem_question_id,
    requirement_content_hash,
)
from agentmesh.deepsearch.planning import plan_content_hash
from agentmesh.deepsearch.service import DeepSearchPlanningService, deepsearch_retry_disposition
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ChatThread,
    DeepSearchBudgetV1,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanStatus,
    SkillResourceManifestV1,
    User,
)
from agentmesh.routes.deepsearch import get_deepsearch_planning_service
from agentmesh.routes.deps import current_user
from agentmesh.runtime_capacity import RuntimeCapacityController
from agentmesh.seed import PROJECT, TEAM_LEAD, USER, WORKSPACE
from agentmesh.store import store

_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


class ScriptedRefiner:
    def __init__(
        self,
        drafts: list[RequirementRefinementDraftV1],
        *,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        self._drafts = drafts
        self._on_call = on_call
        self.calls: list[
            tuple[RequirementVersionV1 | None, str, dict[str, ClarificationAnswerValue]]
        ] = []

    async def refine(
        self,
        *,
        previous: RequirementVersionV1 | None,
        user_request: str,
        answers: dict[str, ClarificationAnswerValue],
    ) -> RequirementRefinementDraftV1:
        self.calls.append((previous, user_request, answers))
        if self._on_call is not None:
            self._on_call()
        call_index = len(self.calls) - 1
        if call_index >= len(self._drafts):
            raise AssertionError("Requirement Refiner was called more often than expected")
        return self._drafts[call_index]


@pytest.fixture(autouse=True)
def _isolated_deepsearch_routes() -> Iterator[None]:
    previous_overrides = app.dependency_overrides.copy()
    store.reset()
    store.save_workspace(WORKSPACE)
    store.save_project(PROJECT)
    store.save_user(USER)
    store.save_user(TEAM_LEAD)
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def _set_current_user(user: User) -> None:
    def provide_user() -> User:
        return user

    app.dependency_overrides[current_user] = provide_user


def _install_service(
    refiner: ScriptedRefiner,
    *,
    clock: Callable[[], datetime] = lambda: _NOW,
    can_refine: Callable[[], bool] = lambda: True,
    planning_pipeline: object | None = None,
) -> DeepSearchPlanningService:
    service = DeepSearchPlanningService(
        store,
        refiner,
        clock=clock,
        can_refine=can_refine,
        planning_pipeline=planning_pipeline,  # type: ignore[arg-type]
    )

    def provide_service() -> DeepSearchPlanningService:
        return service

    app.dependency_overrides[get_deepsearch_planning_service] = provide_service
    _set_current_user(USER)
    return service


def _run(
    run_id: str,
    *,
    planning_mode: AgentPlanningMode = AgentPlanningMode.DEEPSEARCH,
    status: AgentRunStatus = AgentRunStatus.PLANNING,
    error_code: str | None = None,
) -> AgentRun:
    is_deepsearch = planning_mode is AgentPlanningMode.DEEPSEARCH
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="Compare the collaboration software market",
        client_turn_id=f"turn_{run_id}",
        status=status,
        planning_mode=planning_mode,
        requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        orchestration_version="v1",
        orchestration_mode="execute",
        error_code=error_code,
        deadline_at=None,
        absolute_expires_at=_NOW + timedelta(days=7) if is_deepsearch else None,
        deepsearch_budget=DeepSearchBudgetV1() if is_deepsearch else None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _save_run(
    run_id: str,
    *,
    planning_mode: AgentPlanningMode = AgentPlanningMode.DEEPSEARCH,
) -> AgentRun:
    candidate = _run(run_id, planning_mode=planning_mode)
    store.add_chat_thread(
        ChatThread(
            id=candidate.thread_id,
            workspace_id=candidate.workspace_id,
            project_id=candidate.project_id,
            user_id=candidate.user_id,
            title="DeepSearch test thread",
            status="active",
        )
    )
    run, created = store.claim_new_agent_run(candidate)
    assert created is True
    return run


def _question(prompt: str) -> ClarificationQuestionDraftV1:
    return ClarificationQuestionDraftV1(
        prompt=prompt,
        required=True,
        answer_kind="text",
        options=[],
        max_length=2_000,
        default_value=None,
    )


def _draft(*, blocking: bool, prompt: str = "Which market should be compared?") -> RequirementRefinementDraftV1:
    return RequirementRefinementDraftV1(
        goal="Compare collaboration software",
        scope=RequirementScopeV1(objects=["collaboration software"]),
        constraints=[],
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_market",
                statement="Produce an evidence-backed comparison",
            )
        ],
        deliverables=["Research report"],
        assumptions=[],
        ambiguities=(
            [
                RequirementAmbiguityV1(
                    id="ambiguity_market",
                    statement="The comparison market remains unresolved",
                    blocking=True,
                )
            ]
            if blocking
            else []
        ),
        clarification_questions=[_question(prompt)] if blocking else [],
    )


def _seed_waiting_requirement(
    run_id: str,
    *,
    interaction_expires_at: datetime | None = None,
) -> tuple[AgentRun, RequirementVersionV1]:
    run = _save_run(run_id)
    payload = materialize_requirement_payload(
        previous=None,
        draft=_draft(blocking=True, prompt="Which market should be compared?"),
        answers={},
        target_version=1,
    )
    assert run.client_turn_id is not None
    assert run.create_request_hash is not None
    requirement = RequirementVersionV1(
        id=f"requirement_{run_id}_v1",
        run_id=run.id,
        version=1,
        request_key=run.client_turn_id,
        request_hash=run.create_request_hash,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=_NOW,
    )
    result = store.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement.model_dump(mode="json"),
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        interaction_expires_at=interaction_expires_at or _NOW + timedelta(hours=24),
        error_code=None,
        events=[],
        checked_at=_NOW,
    )
    assert result is not None
    return result.run, requirement


def _clarification_payload(
    *,
    client_turn_id: str,
    expected_requirement_version: int,
    question_id: str,
    answer: object,
) -> dict[str, object]:
    return {
        "client_turn_id": client_turn_id,
        "expected_requirement_version": expected_requirement_version,
        "answers": {question_id: answer},
    }


def _post_streaming_json(
    path: str,
    payload: dict[str, object],
    *,
    content_length: str | None = None,
) -> Response:
    body = json.dumps(payload, separators=(",", ":")).encode()

    async def post_in_chunks() -> Response:
        async def chunks() -> AsyncIterator[bytes]:
            for offset in range(0, len(body), 4_096):
                yield body[offset : offset + 4_096]

        headers = {"content-type": "application/json"}
        if content_length is not None:
            headers["content-length"] = content_length
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(path, content=chunks(), headers=headers)

    return asyncio.run(post_in_chunks())


@pytest.mark.parametrize(
    ("blocking", "expected_status", "expected_round"),
    [
        (False, AgentRunStatus.PLANNING, 0),
        (True, AgentRunStatus.WAITING_CLARIFICATION, 1),
    ],
)
def test_initial_refinement_materializes_server_state_without_tools(
    blocking: bool,
    expected_status: AgentRunStatus,
    expected_round: int,
) -> None:
    run = _save_run(f"run_initial_refinement_{expected_round}")
    refiner = ScriptedRefiner([_draft(blocking=blocking)])
    service = _install_service(refiner)

    state = asyncio.run(service.refine_initial(run))
    replay = asyncio.run(service.refine_initial(run))

    assert state.run.status is expected_status
    assert state.active_requirement is not None
    assert state.active_requirement.version == 1
    assert state.active_requirement.payload.clarification_round == expected_round
    assert bool(state.active_requirement.payload.clarification_questions) is blocking
    assert (state.run.interaction_expires_at == _NOW + timedelta(hours=24)) is blocking
    assert replay.active_requirement == state.active_requirement
    assert len(refiner.calls) == 1


def test_initial_refinement_uses_the_persisted_run_goal() -> None:
    run = _save_run("run_initial_refinement_authority")
    refiner = ScriptedRefiner([_draft(blocking=False)])
    service = _install_service(refiner)
    caller_copy = run.model_copy(update={"input_text": "Ignore the persisted goal"})

    state = asyncio.run(service.refine_initial(caller_copy))

    assert state.active_requirement is not None
    assert refiner.calls[0][1] == run.input_text


def test_complete_requirement_continues_into_one_atomic_plan_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _save_run("run_initial_planning_continuation")
    pipeline_calls: list[tuple[AgentRun, RequirementVersionV1, User, datetime]] = []
    commit_calls: list[dict[str, object]] = []

    class RecordingPipeline:
        async def create_plan(
            self,
            *,
            run: AgentRun,
            requirement: RequirementVersionV1,
            user: User,
            created_at: datetime,
        ) -> tuple[SkillPlan, Artifact]:
            pipeline_calls.append((run, requirement, user, created_at))
            question = ProblemQuestionV1(
                id=problem_question_id("What evidence supports the market comparison?"),
                question="What evidence supports the market comparison?",
                required=True,
                success_criterion_ids=[requirement.payload.success_criteria[0].id],
                evidence_requirements=["Current public market evidence"],
                acceptance_criteria=["Cite evidence for the comparison"],
            )
            graph = build_problem_graph(requirement=requirement, questions=[question])
            resource_manifest_payload = {
                "schema_version": "skill-resource-manifest-v1",
                "required_resources": [],
                "resource_hashes": {},
            }
            plan = SkillPlan(
                id="plan_initial_planning_continuation",
                run_id=run.id,
                status=SkillPlanStatus.WAITING_APPROVAL,
                intent=SkillIntent(goal=requirement.payload.goal),
                candidate_skill_ids=["skill_market_research"],
                nodes=[
                    SkillPlanNode(
                        id="node_market_research",
                        skill_id="skill_market_research",
                        skill_version="1",
                        skill_content_hash="a" * 64,
                        reason="Answer the required market question",
                        question_ids=[question.id],
                        resource_manifest=SkillResourceManifestV1(
                            **resource_manifest_payload,
                            content_hash=canonical_json_sha256(resource_manifest_payload),
                        ),
                    )
                ],
                planning_mode=AgentPlanningMode.DEEPSEARCH,
                requirement_version_id=requirement.id,
                requirement_content_hash=requirement.content_hash,
                problem_graph=graph.model_dump(mode="json"),
                problem_graph_hash=graph.content_hash,
            )
            plan.plan_content_hash = plan_content_hash(plan)
            snapshot = Artifact(
                id="artifact_initial_planning_continuation",
                run_id=run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                user_id=run.user_id,
                artifact_type="deepsearch_plan_snapshot",
                content_type="application/json",
                content="{}",
            )
            return plan, snapshot

    def commit_plan(**kwargs: object):
        commit_calls.append(kwargs)
        plan = kwargs["plan"]
        snapshot = kwargs["plan_snapshot"]
        assert isinstance(plan, SkillPlan)
        assert isinstance(snapshot, Artifact)
        current = store.get_agent_run(run.id)
        assert current is not None
        transitioned = current.model_copy(
            update={
                "plan_id": plan.id,
                "status": AgentRunStatus.WAITING_PLAN_APPROVAL,
                "interaction_expires_at": _NOW + timedelta(hours=24),
            }
        )
        return plan, transitioned, snapshot

    monkeypatch.setattr(store, "save_deepsearch_plan_and_transition", commit_plan)
    service = _install_service(
        ScriptedRefiner([_draft(blocking=False)]),
        planning_pipeline=RecordingPipeline(),
    )

    state = asyncio.run(service.refine_initial(run))

    assert state.run.status is AgentRunStatus.WAITING_PLAN_APPROVAL
    assert state.plan is not None
    assert state.plan.id == "plan_initial_planning_continuation"
    assert state.problem_graph is not None
    assert state.problem_graph.content_hash == state.plan.problem_graph_hash
    public_plan = state.model_dump(mode="json")["plan"]
    assert "deepsearch_syntheses" not in public_plan
    assert "review_outcomes" not in public_plan
    assert "finalization_input_hashes" not in public_plan
    assert "resource_manifest" not in public_plan["nodes"][0]
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0][0].id == run.id
    assert pipeline_calls[0][1] == state.active_requirement
    assert pipeline_calls[0][2] == USER
    assert commit_calls[0]["expected_requirement_version"] == 1
    assert commit_calls[0]["checked_at"] == _NOW


def test_get_state_is_owner_scoped_rejects_non_deepsearch_and_is_read_only() -> None:
    run, requirement = _seed_waiting_requirement("run_deepsearch_get_state")
    standard = _save_run("run_standard_get_state", planning_mode=AgentPlanningMode.STANDARD)
    refiner = ScriptedRefiner([])
    _install_service(refiner)
    client = TestClient(app)

    with sqlite3.connect(store.db_path) as observer:
        before_version = int(observer.execute("PRAGMA data_version").fetchone()[0])
        before_runs = observer.execute(
            "SELECT id, payload, updated_at FROM agent_runs ORDER BY id"
        ).fetchall()
        before_requirements = observer.execute(
            "SELECT id, payload, created_at FROM deepsearch_requirement_versions ORDER BY id"
        ).fetchall()

        response = client.get(f"/api/agent/runs/{run.id}/deepsearch")

        after_version = int(observer.execute("PRAGMA data_version").fetchone()[0])
        after_runs = observer.execute(
            "SELECT id, payload, updated_at FROM agent_runs ORDER BY id"
        ).fetchall()
        after_requirements = observer.execute(
            "SELECT id, payload, created_at FROM deepsearch_requirement_versions ORDER BY id"
        ).fetchall()

    assert response.status_code == 200
    assert response.json()["run"]["id"] == run.id
    assert response.json()["active_requirement"]["id"] == requirement.id
    assert refiner.calls == []
    assert after_version == before_version
    assert after_runs == before_runs
    assert after_requirements == before_requirements

    _set_current_user(TEAM_LEAD)
    hidden = client.get(f"/api/agent/runs/{run.id}/deepsearch")
    assert hidden.status_code == 404

    _set_current_user(USER)
    wrong_mode = client.get(f"/api/agent/runs/{standard.id}/deepsearch")
    assert wrong_mode.status_code == 409
    assert wrong_mode.json()["detail"] == {"code": "deepsearch_mode_required"}


def test_get_state_preserves_questions_for_a_cancelled_run_but_hides_a_deleted_thread() -> None:
    run, requirement = _seed_waiting_requirement("run_cancelled_state")
    refiner = ScriptedRefiner([])
    _install_service(refiner)
    client = TestClient(app)
    cancelled = store.cancel_agent_run_tree(run.id, user_id=run.user_id)
    assert cancelled is not None

    response = client.get(f"/api/agent/runs/{run.id}/deepsearch")

    assert response.status_code == 200
    assert response.json()["run"]["status"] == "cancelled"
    assert response.json()["active_requirement"]["id"] == requirement.id

    store.add_chat_thread(
        ChatThread(
            id=run.thread_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            user_id=run.user_id,
            title="Deleted DeepSearch thread",
            status="deleted",
        )
    )

    hidden = client.get(f"/api/agent/runs/{run.id}/deepsearch")
    assert hidden.status_code == 404


def test_get_state_hides_a_run_whose_parent_thread_is_missing() -> None:
    run, _requirement = _seed_waiting_requirement("run_missing_parent_thread")
    refiner = ScriptedRefiner([])
    _install_service(refiner)
    client = TestClient(app)
    with store._connect() as connection:
        connection.execute(
            "DELETE FROM records WHERE collection = 'chat_threads' AND id = ?",
            (run.thread_id,),
        )

    response = client.get(f"/api/agent/runs/{run.id}/deepsearch")

    assert response.status_code == 404


def test_clarification_rejects_an_oversized_body_before_request_validation() -> None:
    run, requirement = _seed_waiting_requirement("run_oversized_clarification")
    question_id = requirement.payload.clarification_questions[0].id
    refiner = ScriptedRefiner([])
    _install_service(refiner)
    client = TestClient(app)

    response = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json=_clarification_payload(
            client_turn_id="clarify_oversized_body",
            expected_requirement_version=requirement.version,
            question_id=question_id,
            answer="x" * (16 * 1_024),
        ),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == {
        "code": "deepsearch_clarification_payload_too_large"
    }
    assert refiner.calls == []


def test_clarification_rejects_capacity_before_refinement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, requirement = _seed_waiting_requirement("run_clarification_capacity")
    question_id = requirement.payload.clarification_questions[0].id
    refiner = ScriptedRefiner([])
    _install_service(refiner)
    capacity = RuntimeCapacityController(
        process_run_limit=1,
        user_run_limit=1,
        node_limit=1,
    )
    assert capacity.reserve_run(operation_key="occupied", user_id=USER.id)
    monkeypatch.setattr(
        deepsearch_routes,
        "current_runtime_capacity",
        lambda: capacity,
    )
    client = TestClient(app)

    response = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json=_clarification_payload(
            client_turn_id="clarify_capacity",
            expected_requirement_version=requirement.version,
            question_id=question_id,
            answer="Keep the original scope.",
        ),
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.json()["detail"] == {"code": "runtime_capacity_exceeded"}
    assert refiner.calls == []
    persisted = store.get_active_deepsearch_requirement(run.id)
    assert persisted is not None
    assert persisted["id"] == requirement.id
    assert persisted["version"] == requirement.version


def test_clarification_counts_chunked_body_without_content_length() -> None:
    run, requirement = _seed_waiting_requirement("run_chunked_oversized_clarification")
    question_id = requirement.payload.clarification_questions[0].id
    refiner = ScriptedRefiner([])
    _install_service(refiner)
    response = _post_streaming_json(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        _clarification_payload(
            client_turn_id="clarify_chunked_oversized_body",
            expected_requirement_version=requirement.version,
            question_id=question_id,
            answer="x" * (16 * 1_024),
        ),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == {
        "code": "deepsearch_clarification_payload_too_large"
    }
    assert refiner.calls == []


def test_clarification_counts_actual_body_when_content_length_is_forged_small() -> None:
    run, requirement = _seed_waiting_requirement("run_forged_length_clarification")
    question_id = requirement.payload.clarification_questions[0].id
    refiner = ScriptedRefiner([])
    _install_service(refiner)

    response = _post_streaming_json(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        _clarification_payload(
            client_turn_id="clarify_forged_length_body",
            expected_requirement_version=requirement.version,
            question_id=question_id,
            answer="x" * (16 * 1_024),
        ),
        content_length="1",
    )

    assert response.status_code == 413
    assert response.json()["detail"] == {
        "code": "deepsearch_clarification_payload_too_large"
    }
    assert refiner.calls == []


def test_clarification_body_limit_does_not_apply_to_other_agent_run_routes() -> None:
    _set_current_user(USER)
    client = TestClient(app)

    response = client.post(
        "/api/agent/runs",
        json={
            "content": "x" * (16 * 1_024),
            "client_turn_id": "oversized_standard_run",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_long"


def test_stale_version_wins_over_semantically_invalid_answers_without_refining() -> None:
    run, _requirement = _seed_waiting_requirement("run_stale_invalid_priority")
    refiner = ScriptedRefiner([])
    _install_service(refiner)
    client = TestClient(app)

    response = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json={
            "client_turn_id": "clarify_stale_invalid",
            "expected_requirement_version": 999,
            "answers": {"unknown_question": []},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "deepsearch_requirement_version_conflict",
        "current_requirement_version": 1,
    }
    assert refiner.calls == []


def test_invalid_answers_return_422_without_calling_the_refiner() -> None:
    run, requirement = _seed_waiting_requirement("run_invalid_answers")
    refiner = ScriptedRefiner([])
    _install_service(refiner)
    client = TestClient(app)

    response = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json={
            "client_turn_id": "clarify_invalid_answers",
            "expected_requirement_version": requirement.version,
            "answers": {},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "deepsearch_clarification_invalid"
    assert refiner.calls == []
    assert store.get_deepsearch_requirement(run.id, version=2) is None
    persisted_run = store.get_agent_run(run.id)
    assert persisted_run is not None
    assert persisted_run.status is AgentRunStatus.WAITING_CLARIFICATION


def test_noncanonical_answer_keys_return_422_without_calling_the_refiner() -> None:
    run, requirement = _seed_waiting_requirement("run_noncanonical_answer_keys")
    refiner = ScriptedRefiner([])
    _install_service(refiner)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json={
            "client_turn_id": "clarify_noncanonical_answer_keys",
            "expected_requirement_version": requirement.version,
            "answers": {"é": "one", "e\u0301": "two"},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "deepsearch_clarification_invalid"
    assert refiner.calls == []


def test_successful_clarification_advances_one_round_and_identical_replay_is_model_free() -> None:
    run, requirement = _seed_waiting_requirement("run_clarification_replay")
    question_id = requirement.payload.clarification_questions[0].id
    refiner = ScriptedRefiner([_draft(blocking=True, prompt="Which time range should be used?")])
    _install_service(refiner)
    client = TestClient(app)
    request = _clarification_payload(
        client_turn_id="clarify_replay_key",
        expected_requirement_version=1,
        question_id=question_id,
        answer="  Worldwide  ",
    )

    first = client.post(f"/api/agent/runs/{run.id}/deepsearch/clarify", json=request)
    replay = client.post(f"/api/agent/runs/{run.id}/deepsearch/clarify", json=request)

    assert first.status_code == 202
    assert replay.status_code == 202
    first_requirement = first.json()["active_requirement"]
    assert first_requirement["version"] == 2
    assert first_requirement["payload"]["clarification_round"] == 2
    assert first_requirement["payload"]["clarification_history"][0]["answers"] == {
        question_id: "Worldwide"
    }
    assert replay.json()["active_requirement"]["id"] == first_requirement["id"]
    assert len(refiner.calls) == 1
    assert refiner.calls[0][2] == {question_id: "Worldwide"}
    assert store.get_deepsearch_requirement(run.id, version=3) is None


def test_historical_idempotency_replay_returns_the_current_authoritative_aggregate() -> None:
    run, requirement = _seed_waiting_requirement("run_historical_clarification_replay")
    first_question_id = requirement.payload.clarification_questions[0].id
    refiner = ScriptedRefiner(
        [
            _draft(blocking=True, prompt="Which time range should be used?"),
            _draft(blocking=False),
        ]
    )
    _install_service(refiner)
    client = TestClient(app)
    first_request = _clarification_payload(
        client_turn_id="clarify_historical_first",
        expected_requirement_version=1,
        question_id=first_question_id,
        answer="Worldwide",
    )

    first = client.post(f"/api/agent/runs/{run.id}/deepsearch/clarify", json=first_request)
    second_requirement = RequirementVersionV1.model_validate(first.json()["active_requirement"])
    second_question_id = second_requirement.payload.clarification_questions[0].id
    second = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json=_clarification_payload(
            client_turn_id="clarify_historical_second",
            expected_requirement_version=2,
            question_id=second_question_id,
            answer="Last 24 months",
        ),
    )
    replay = client.post(f"/api/agent/runs/{run.id}/deepsearch/clarify", json=first_request)

    assert second.status_code == 202
    assert second.json()["active_requirement"]["version"] == 3
    assert replay.status_code == 202
    assert replay.json()["run"]["status"] == "planning"
    assert replay.json()["active_requirement"]["version"] == 3
    assert len(refiner.calls) == 2


def test_same_request_key_with_a_different_hash_is_a_conflict() -> None:
    run, requirement = _seed_waiting_requirement("run_clarification_key_conflict")
    question_id = requirement.payload.clarification_questions[0].id
    refiner = ScriptedRefiner([_draft(blocking=True, prompt="Which time range should be used?")])
    _install_service(refiner)
    client = TestClient(app)
    original = _clarification_payload(
        client_turn_id="clarify_conflicting_key",
        expected_requirement_version=1,
        question_id=question_id,
        answer="Worldwide",
    )

    accepted = client.post(f"/api/agent/runs/{run.id}/deepsearch/clarify", json=original)
    conflicting = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json={**original, "answers": {question_id: "China"}},
    )

    assert accepted.status_code == 202
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"] == {
        "code": "deepsearch_requirement_idempotency_conflict",
        "current_requirement_version": 2,
    }
    assert len(refiner.calls) == 1
    assert store.get_deepsearch_requirement(run.id, version=3) is None


def test_idempotent_replay_precedes_current_execution_readiness() -> None:
    run, requirement = _seed_waiting_requirement("run_clarification_readiness_replay")
    question_id = requirement.payload.clarification_questions[0].id
    readiness = {"available": True}
    refiner = ScriptedRefiner([_draft(blocking=True, prompt="Which time range should be used?")])
    _install_service(refiner, can_refine=lambda: readiness["available"])
    client = TestClient(app)
    request = _clarification_payload(
        client_turn_id="clarify_readiness_replay",
        expected_requirement_version=1,
        question_id=question_id,
        answer="Worldwide",
    )

    accepted = client.post(f"/api/agent/runs/{run.id}/deepsearch/clarify", json=request)
    readiness["available"] = False
    replay = client.post(f"/api/agent/runs/{run.id}/deepsearch/clarify", json=request)

    assert accepted.status_code == 202
    assert replay.status_code == 202
    assert len(refiner.calls) == 1

    next_question_id = replay.json()["active_requirement"]["payload"]["clarification_questions"][0]["id"]
    blocked = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json=_clarification_payload(
            client_turn_id="clarify_readiness_new",
            expected_requirement_version=2,
            question_id=next_question_id,
            answer="Last 24 months",
        ),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == {"code": "deepsearch_execution_unavailable"}
    assert len(refiner.calls) == 1


def test_third_unresolved_round_atomically_appends_the_requirement_and_fails_the_run() -> None:
    run, requirement = _seed_waiting_requirement("run_three_rounds_unresolved")
    refiner = ScriptedRefiner(
        [
            _draft(blocking=True, prompt="Round two question?"),
            _draft(blocking=True, prompt="Round three question?"),
            _draft(blocking=True, prompt="A forbidden round four question?"),
        ]
    )
    _install_service(refiner)
    client = TestClient(app)
    active_requirement = requirement

    for round_number in range(1, 4):
        question_id = active_requirement.payload.clarification_questions[0].id
        response = client.post(
            f"/api/agent/runs/{run.id}/deepsearch/clarify",
            json=_clarification_payload(
                client_turn_id=f"clarify_round_{round_number}",
                expected_requirement_version=active_requirement.version,
                question_id=question_id,
                answer=f"Answer {round_number}",
            ),
        )
        assert response.status_code == 202
        active_requirement = RequirementVersionV1.model_validate(response.json()["active_requirement"])

    assert active_requirement.version == 4
    assert active_requirement.payload.clarification_round == 3
    assert len(active_requirement.payload.clarification_history) == 3
    assert active_requirement.payload.clarification_questions == []
    persisted_run = store.get_agent_run(run.id)
    assert persisted_run is not None
    assert persisted_run.status is AgentRunStatus.FAILED
    assert persisted_run.error_code == "deepsearch_clarification_unresolved"
    assert response.json()["run"]["status"] == "failed"
    assert response.json()["retry_disposition"] == "revise_goal"
    assert store.get_deepsearch_requirement(run.id, version=4) == active_requirement.model_dump(mode="json")
    assert [event.event_type for event in store.list_agent_run_events(run.id)][-2:] == [
        "deepsearch_clarification_answered",
        "run_failed",
    ]
    assert len(refiner.calls) == 3


def test_expired_interaction_is_cancelled_before_refiner_invocation() -> None:
    run, requirement = _seed_waiting_requirement(
        "run_expired_clarification",
        interaction_expires_at=_NOW - timedelta(seconds=1),
    )
    question_id = requirement.payload.clarification_questions[0].id
    refiner = ScriptedRefiner([_draft(blocking=False)])
    _install_service(refiner)
    client = TestClient(app)

    response = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json=_clarification_payload(
            client_turn_id="clarify_after_expiry",
            expected_requirement_version=1,
            question_id=question_id,
            answer="Worldwide",
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "deepsearch_interaction_expired",
        "current_requirement_version": 1,
    }
    assert refiner.calls == []
    persisted_run = store.get_agent_run(run.id)
    assert persisted_run is not None
    assert persisted_run.status is AgentRunStatus.CANCELLED
    assert persisted_run.error_code == "deepsearch_interaction_expired"
    assert store.get_deepsearch_requirement(run.id, version=2) is None


def test_refiner_runs_after_the_sqlite_prepare_transaction_has_been_released() -> None:
    run, requirement = _seed_waiting_requirement("run_refiner_transaction_release")
    question_id = requirement.payload.clarification_questions[0].id

    def write_probe_event() -> None:
        store.append_agent_run_event(run.id, "refiner_transaction_probe", {"writable": True})

    refiner = ScriptedRefiner([_draft(blocking=False)], on_call=write_probe_event)
    _install_service(refiner)
    client = TestClient(app)

    response = client.post(
        f"/api/agent/runs/{run.id}/deepsearch/clarify",
        json=_clarification_payload(
            client_turn_id="clarify_transaction_release",
            expected_requirement_version=1,
            question_id=question_id,
            answer="Worldwide",
        ),
    )

    assert response.status_code == 202
    assert response.json()["run"]["status"] == "planning"
    assert len(refiner.calls) == 1
    assert "refiner_transaction_probe" in [
        event.event_type for event in store.list_agent_run_events(run.id)
    ]


def test_refiner_cannot_mutate_authoritative_requirement_or_answers() -> None:
    run, requirement = _seed_waiting_requirement("run_refiner_input_isolation")
    question_id = requirement.payload.clarification_questions[0].id

    class MutatingRefiner:
        async def refine(
            self,
            *,
            previous: RequirementVersionV1 | None,
            user_request: str,
            answers: dict[str, ClarificationAnswerValue],
        ) -> RequirementRefinementDraftV1:
            assert previous is not None
            previous.payload.clarification_questions.clear()
            previous.payload.scope.objects.append("poisoned scope")
            answers[question_id] = "poisoned answer"
            return _draft(blocking=False)

    service = DeepSearchPlanningService(store, MutatingRefiner(), clock=lambda: _NOW)

    state = asyncio.run(
        service.clarify(
            run=run,
            request=DeepSearchClarifyRequestV1(
                client_turn_id="clarify_refiner_input_isolation",
                expected_requirement_version=1,
                answers={question_id: "Worldwide"},
            ),
        )
    )

    assert state.active_requirement is not None
    assert state.active_requirement.payload.clarification_history[0].questions == (
        requirement.payload.clarification_questions
    )
    assert state.active_requirement.payload.clarification_history[0].answers == {
        question_id: "Worldwide"
    }
    assert store.get_deepsearch_requirement(run.id, version=1) == requirement.model_dump(mode="json")


@pytest.mark.parametrize(
    ("status", "error_code", "expected"),
    [
        (AgentRunStatus.COMPLETED, "deepsearch_execution_transient", DeepSearchRetryDisposition.NONE),
        (AgentRunStatus.FAILED, "permission_denied", DeepSearchRetryDisposition.NONE),
        (
            AgentRunStatus.FAILED,
            "deepsearch_execution_transient",
            DeepSearchRetryDisposition.RETRY_RUN,
        ),
        (
            AgentRunStatus.FAILED,
            "deepsearch_clarification_unresolved",
            DeepSearchRetryDisposition.REVISE_GOAL,
        ),
        (AgentRunStatus.FAILED, "unknown_failure", DeepSearchRetryDisposition.NONE),
    ],
)
def test_retry_disposition_is_a_pure_projection(
    status: AgentRunStatus,
    error_code: str,
    expected: DeepSearchRetryDisposition,
) -> None:
    run = _run(
        f"run_retry_disposition_{status.value}_{expected.value}",
        status=status,
        error_code=error_code,
    )
    before = run.model_dump(mode="python")

    first = deepsearch_retry_disposition(run)
    second = deepsearch_retry_disposition(run)

    assert first is expected
    assert second is expected
    assert run.model_dump(mode="python") == before
