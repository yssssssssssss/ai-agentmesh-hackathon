from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from agentmesh.deepsearch.contracts import (
    ClarificationQuestionDraftV1,
    RequirementAmbiguityV1,
    RequirementRefinementDraftV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    clarification_request_hash,
    materialize_requirement_payload,
    requirement_content_hash,
)
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    DeepSearchBudgetV1,
    SkillOrchestrationRequestMode,
)
from agentmesh.store import DeepSearchRequirementConflict, ResearchStoreConflict, SQLiteStore

_CREATED_AT = datetime.now(UTC).replace(microsecond=0)


def _run(run_id: str, *, status: AgentRunStatus = AgentRunStatus.PLANNING) -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id="user_deepsearch_requirement",
        workspace_id="workspace_deepsearch_requirement",
        project_id="project_deepsearch_requirement",
        input_text="Compare the market",
        client_turn_id=f"turn_{run_id}",
        status=status,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
        orchestration_version="v1",
        orchestration_mode="execute",
        deadline_at=None,
        absolute_expires_at=_CREATED_AT + timedelta(days=7),
        deepsearch_budget=DeepSearchBudgetV1(),
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _replace_run_fixture(repository: SQLiteStore, run: AgentRun) -> AgentRun:
    """Seed an otherwise unreachable persisted state without reopening production writers."""
    with repository._connect() as connection:
        cursor = connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), run.updated_at.isoformat(), run.id),
        )
    assert cursor.rowcount == 1
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    return persisted


def _claim_run_in_state(
    repository: SQLiteStore,
    run_id: str,
    *,
    status: AgentRunStatus,
    interaction_expires_at: datetime | None = None,
) -> AgentRun:
    run, created = repository.claim_new_agent_run(_run(run_id))
    assert created is True
    return _replace_run_fixture(
        repository,
        run.model_copy(
            update={
                "status": status,
                "interaction_expires_at": interaction_expires_at,
            }
        )
    )


def _requirement(
    run_id: str,
    *,
    version: int,
    request_key: str,
    request_hash: str | None = None,
    derived_from: str | None = None,
    goal: str = "Compare the market",
    previous: dict[str, object] | None = None,
    blocking: bool = False,
    question_prompt: str = "Which market should be compared?",
) -> dict[str, object]:
    previous_requirement = RequirementVersionV1.model_validate(previous) if previous is not None else None
    draft = RequirementRefinementDraftV1(
        goal=goal,
        scope=RequirementScopeV1(),
        constraints=[],
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_1",
                statement="Evidence-backed comparison",
            )
        ],
        deliverables=["report"],
        assumptions=[],
        ambiguities=(
            [
                RequirementAmbiguityV1(
                    id="ambiguity_1",
                    statement="The market is unresolved",
                    blocking=True,
                )
            ]
            if blocking
            else []
        ),
        clarification_questions=(
            [
                ClarificationQuestionDraftV1(
                    prompt=question_prompt,
                    required=True,
                    answer_kind="text",
                    options=[],
                )
            ]
            if blocking
            else []
        ),
    )
    answers = (
        {
            question.id: "Worldwide"
            for question in previous_requirement.payload.clarification_questions
        }
        if previous_requirement is not None
        else {}
    )
    payload = materialize_requirement_payload(
        previous=previous_requirement,
        draft=draft,
        answers=answers,
        target_version=version,
    )
    if request_hash is None:
        if previous_requirement is None:
            raise ValueError("initial Requirement needs its Run request hash")
        request_hash = clarification_request_hash(
            run_id=run_id,
            expected_requirement_version=previous_requirement.version,
            normalized_answers=answers,
        )
    schema_version = "deepsearch-requirement-v1"
    return RequirementVersionV1(
        id=f"requirement_{run_id}_v{version}",
        run_id=run_id,
        version=version,
        schema_version=schema_version,
        request_key=request_key,
        request_hash=request_hash,
        content_hash=requirement_content_hash(payload, schema_version=schema_version),
        derived_from_requirement_version_id=derived_from,
        payload=payload,
        created_at=_CREATED_AT,
    ).model_dump(mode="json")


def _initial_requirement(
    run: AgentRun,
    *,
    blocking: bool = False,
    question_prompt: str = "Which market should be compared?",
) -> dict[str, object]:
    assert run.client_turn_id is not None
    assert run.create_request_hash is not None
    return _requirement(
        run.id,
        version=1,
        request_key=run.client_turn_id,
        request_hash=run.create_request_hash,
        blocking=blocking,
        question_prompt=question_prompt,
    )


def _retry_clone(
    source: dict[str, object],
    retry_run: AgentRun,
) -> dict[str, object]:
    assert retry_run.client_turn_id is not None
    assert retry_run.create_request_hash is not None
    cloned = {
        **source,
        "id": f"requirement_{retry_run.id}_v1",
        "run_id": retry_run.id,
        "version": 1,
        "request_key": retry_run.client_turn_id,
        "request_hash": retry_run.create_request_hash,
        "derived_from_requirement_version_id": source["id"],
        "created_at": _CREATED_AT.isoformat(),
    }
    return RequirementVersionV1.model_validate(cloned).model_dump(mode="json")


@pytest.mark.parametrize(
    "update",
    [
        {"absolute_expires_at": None},
        {"absolute_expires_at": _CREATED_AT + timedelta(days=8)},
        {"deadline_at": _CREATED_AT + timedelta(minutes=5)},
        {"deepsearch_budget": None},
    ],
)
def test_claim_rejects_a_deepsearch_run_without_lifetime_and_budget_guards(
    tmp_path,
    update: dict[str, object],
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-invalid-run-guards.sqlite3")
    invalid = _run("run_without_guards").model_copy(update=update)

    with pytest.raises(ResearchStoreConflict, match="persistence invariants"):
        repository.claim_new_agent_run(invalid)

    assert repository.get_agent_run("run_without_guards") is None


def test_append_requirement_atomically_transitions_run_and_records_event(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement.sqlite3")
    run, created = repository.claim_new_agent_run(_run("run_requirement"))
    assert created is True
    requirement = _initial_requirement(run, blocking=True)
    expires_at = _CREATED_AT + timedelta(hours=24)

    result = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        interaction_expires_at=expires_at,
        checked_at=_CREATED_AT,
        events=[],
    )

    assert result is not None
    assert result.replayed is False
    assert result.requirement == requirement
    assert result.run.status == AgentRunStatus.WAITING_CLARIFICATION
    assert result.run.interaction_expires_at == expires_at
    assert repository.get_active_deepsearch_requirement(run.id) == requirement
    assert repository.get_deepsearch_requirement(run.id, version=1) == requirement
    assert [event.event_type for event in repository.list_agent_run_events(run.id)] == [
        "deepsearch_requirement_created",
        "deepsearch_clarification_requested",
    ]

    snapshot = repository.get_deepsearch_state_snapshot(run.id)
    assert snapshot is not None
    assert snapshot.run == result.run
    assert snapshot.requirement == requirement
    assert snapshot.plan is None


def test_initial_append_rejects_request_identity_not_bound_to_the_run_claim(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-forged-identity.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_forged_requirement_identity"))
    requirement = _requirement(
        run.id,
        version=1,
        request_key="forged_turn",
        request_hash="f" * 64,
    )

    with pytest.raises(ResearchStoreConflict, match="request identity"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.PLANNING,
            events=[],
        )

    assert repository.get_active_deepsearch_requirement(run.id) is None


def test_prepare_returns_an_idempotent_replay_before_checking_a_stale_version(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-replay.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_replay"))
    requirement = _initial_requirement(run, blocking=True)
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )

    prepared = repository.prepare_deepsearch_requirement_append(
        run_id=run.id,
        user_id=run.user_id,
        request_key=str(requirement["request_key"]),
        request_hash=str(requirement["request_hash"]),
        expected_requirement_version=999,
        expected_run_status=AgentRunStatus.CREATED,
    )

    assert prepared is not None
    assert prepared.replayed is True
    assert prepared.requirement == requirement


def test_prepare_reports_request_conflict_before_a_stale_version(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-request-conflict.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_request_conflict"))
    requirement = _initial_requirement(run, blocking=True)
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )

    try:
        repository.prepare_deepsearch_requirement_append(
            run_id=run.id,
            user_id=run.user_id,
            request_key=str(requirement["request_key"]),
            request_hash="4" * 64,
            expected_requirement_version=999,
            expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        )
    except DeepSearchRequirementConflict as error:
        assert error.code == "deepsearch_requirement_idempotency_conflict"
        assert error.current_requirement_version == 1
    else:
        raise AssertionError("expected an idempotency conflict")


def test_prepare_rejects_an_initial_requirement_outside_planning(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-prepare-state.sqlite3")
    run = _claim_run_in_state(
        repository,
        "run_prepare_wrong_state",
        status=AgentRunStatus.CREATED,
    )

    with pytest.raises(DeepSearchRequirementConflict) as caught:
        repository.prepare_deepsearch_requirement_append(
            run_id=run.id,
            user_id=run.user_id,
            request_key=str(run.client_turn_id),
            request_hash=str(run.create_request_hash),
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.CREATED,
        )

    assert caught.value.code == "deepsearch_requirement_state_conflict"
    assert caught.value.current_requirement_version is None


def test_initial_prepare_rejects_request_identity_not_bound_to_the_run_claim(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-prepare-forged-identity.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_prepare_forged_identity"))

    with pytest.raises(ResearchStoreConflict, match="request identity"):
        repository.prepare_deepsearch_requirement_append(
            run_id=run.id,
            user_id=run.user_id,
            request_key="forged_turn",
            request_hash="e" * 64,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
        )

    assert repository.get_active_deepsearch_requirement(run.id) is None


def test_append_rejects_created_to_waiting_clarification(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-created-transition.sqlite3")
    run = _claim_run_in_state(
        repository,
        "run_created_transition",
        status=AgentRunStatus.CREATED,
    )
    requirement = _initial_requirement(run, blocking=True)

    with pytest.raises(DeepSearchRequirementConflict) as caught:
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.CREATED,
            next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            events=[],
        )

    assert caught.value.code == "deepsearch_requirement_state_conflict"
    assert repository.get_active_deepsearch_requirement(run.id) is None


def test_append_rejects_waiting_status_for_a_complete_requirement(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-complete-transition.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_complete_transition"))
    requirement = _initial_requirement(run)

    with pytest.raises(ResearchStoreConflict, match="transition"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            events=[],
        )

    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.status == AgentRunStatus.PLANNING
    assert repository.get_active_deepsearch_requirement(run.id) is None


def test_append_rejects_a_requirement_with_a_false_content_hash_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-invalid-hash.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_invalid_content_hash"))
    requirement = _initial_requirement(run, blocking=True)
    requirement["content_hash"] = "0" * 64

    with pytest.raises(ResearchStoreConflict, match="content hash"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            events=[("deepsearch_requirement_created", {"requirement_version": 1})],
        )

    persisted_run = repository.get_agent_run(run.id)
    assert persisted_run is not None
    assert persisted_run.status == AgentRunStatus.PLANNING
    assert repository.get_active_deepsearch_requirement(run.id) is None
    assert repository.list_agent_run_events(run.id) == []


def test_requirement_reads_fail_closed_when_the_persisted_payload_is_tampered(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-tampered.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_tampered_requirement"))
    requirement = _initial_requirement(run, blocking=True)
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )
    tampered = dict(requirement)
    tampered["payload"] = {**requirement["payload"], "goal": "tampered goal"}  # type: ignore[arg-type]
    with repository._connect() as connection:
        connection.execute(
            "UPDATE deepsearch_requirement_versions SET payload = ? WHERE id = ?",
            (json.dumps(tampered), requirement["id"]),
        )

    with pytest.raises(ResearchStoreConflict, match="integrity"):
        repository.get_active_deepsearch_requirement(run.id)


def test_requirement_versions_are_append_only_and_stale_cas_cannot_overwrite(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-cas.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_cas"))
    first = _initial_requirement(run, blocking=True)
    first_result = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=first,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )
    assert first_result is not None

    second = _requirement(
        run.id,
        version=2,
        request_key="clarification_1",
        derived_from=str(first["id"]),
        goal="Compare the mainland China market",
        previous=first,
    )
    second_result = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=second,
        expected_requirement_version=1,
        expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
    )
    assert second_result is not None

    stale = _requirement(
        run.id,
        version=2,
        request_key="stale_clarification",
        derived_from=str(first["id"]),
        goal="Stale overwrite",
        previous=first,
    )
    with pytest.raises(DeepSearchRequirementConflict) as caught:
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=stale,
            expected_requirement_version=1,
            expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            next_run_status=AgentRunStatus.PLANNING,
            events=[],
        )

    assert caught.value.code == "deepsearch_requirement_version_conflict"
    assert caught.value.current_requirement_version == 2
    with pytest.raises(DeepSearchRequirementConflict) as request_conflict:
        repository.prepare_deepsearch_requirement_append(
            run_id=run.id,
            user_id=run.user_id,
            request_key=str(first["request_key"]),
            request_hash="f" * 64,
            expected_requirement_version=1,
            expected_run_status=AgentRunStatus.PLANNING,
        )
    assert request_conflict.value.code == "deepsearch_requirement_idempotency_conflict"
    assert request_conflict.value.current_requirement_version == 2
    assert repository.get_deepsearch_requirement(run.id, version=1) == first
    assert repository.get_active_deepsearch_requirement(run.id) == second


def test_append_rejects_a_clarification_request_hash_not_derived_from_new_answers(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-answer-hash.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_answer_hash"))
    first = _initial_requirement(run, blocking=True)
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=first,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )
    second = _requirement(
        run.id,
        version=2,
        request_key="clarification_answer_hash",
        derived_from=str(first["id"]),
        previous=first,
    )
    forged = {**second, "request_hash": "f" * 64}

    with pytest.raises(ResearchStoreConflict, match="request identity"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=forged,
            expected_requirement_version=1,
            expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            next_run_status=AgentRunStatus.PLANNING,
            events=[],
        )

    assert repository.get_active_deepsearch_requirement(run.id) == first


def test_append_rejects_rewritten_clarification_history(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-history-prefix.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_history_prefix"))
    first = _initial_requirement(run, blocking=True)
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=first,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )
    second = _requirement(
        run.id,
        version=2,
        request_key="clarification_history_round_2",
        derived_from=str(first["id"]),
        previous=first,
        blocking=True,
        question_prompt="Which time range?",
    )
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=second,
        expected_requirement_version=1,
        expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )
    third = _requirement(
        run.id,
        version=3,
        request_key="clarification_history_round_3",
        derived_from=str(second["id"]),
        previous=second,
    )
    forged = json.loads(json.dumps(third))
    first_history_answers = forged["payload"]["clarification_history"][0]["answers"]
    first_question_id = next(iter(first_history_answers))
    first_history_answers[first_question_id] = "Tampered earlier answer"
    forged["content_hash"] = requirement_content_hash(forged["payload"])

    with pytest.raises(ResearchStoreConflict, match="history"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=forged,
            expected_requirement_version=2,
            expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            next_run_status=AgentRunStatus.PLANNING,
            events=[],
        )

    assert repository.get_active_deepsearch_requirement(run.id) == second


def test_concurrent_requirement_appends_have_one_cas_winner(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-race.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_race"))
    first = _initial_requirement(run, blocking=True)
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=first,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )
    candidates = [
        _requirement(
            run.id,
            version=2,
            request_key=f"clarification_race_{suffix}",
            derived_from=str(first["id"]),
            goal=f"Race candidate {suffix}",
            previous=first,
            blocking=True,
            question_prompt=f"Which market for candidate {suffix}?",
        )
        for suffix in ("a", "b")
    ]
    barrier = Barrier(2)

    def append(candidate: dict[str, object]) -> object:
        barrier.wait()
        try:
            return repository.append_deepsearch_requirement_and_transition(
                run_id=run.id,
                user_id=run.user_id,
                requirement=candidate,
                expected_requirement_version=1,
                expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
                next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
                events=[],
            )
        except DeepSearchRequirementConflict as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append, candidates))

    winners = [outcome for outcome in outcomes if not isinstance(outcome, DeepSearchRequirementConflict)]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, DeepSearchRequirementConflict)]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert conflicts[0].code == "deepsearch_requirement_version_conflict"
    assert repository.get_deepsearch_requirement(run.id, version=1) == first
    assert repository.get_active_deepsearch_requirement(run.id) in candidates


def test_expiration_checks_absolute_deadline_before_interaction_deadline(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-expiry.sqlite3")
    checked_at = _CREATED_AT + timedelta(days=8)
    run = _claim_run_in_state(
        repository,
        "run_requirement_expiry",
        status=AgentRunStatus.WAITING_CLARIFICATION,
        interaction_expires_at=checked_at - timedelta(hours=1),
    )

    expired = repository.expire_deepsearch_run_if_needed(
        run.id,
        user_id=run.user_id,
        checked_at=checked_at,
    )

    assert expired is not None
    assert expired.status == AgentRunStatus.CANCELLED
    assert expired.error_code == "deepsearch_run_expired"
    events = repository.list_agent_run_events(run.id)
    assert [(event.event_type, event.payload) for event in events] == [
        ("run_cancelled", {"reason": "deepsearch_run_expired"})
    ]


def test_interaction_expiry_applies_only_while_waiting_for_a_human(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-interaction-expiry.sqlite3")
    checked_at = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    waiting = _claim_run_in_state(
        repository,
        "run_interaction_expiry",
        status=AgentRunStatus.WAITING_CLARIFICATION,
        interaction_expires_at=checked_at,
    )

    expired = repository.expire_deepsearch_run_if_needed(
        waiting.id,
        user_id=waiting.user_id,
        checked_at=checked_at,
    )

    assert expired is not None
    assert expired.status == AgentRunStatus.CANCELLED
    assert expired.error_code == "deepsearch_interaction_expired"

    with pytest.raises(DeepSearchRequirementConflict) as replayed_expiry:
        repository.prepare_deepsearch_requirement_append(
            run_id=waiting.id,
            user_id=waiting.user_id,
            request_key=str(waiting.client_turn_id),
            request_hash=str(waiting.create_request_hash),
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            checked_at=checked_at + timedelta(seconds=1),
        )

    assert replayed_expiry.value.code == "deepsearch_interaction_expired"

    planning = _claim_run_in_state(
        repository,
        "run_planning_ignores_interaction",
        status=AgentRunStatus.PLANNING,
        interaction_expires_at=checked_at - timedelta(seconds=1),
    )
    unchanged = repository.expire_deepsearch_run_if_needed(
        planning.id,
        user_id=planning.user_id,
        checked_at=checked_at,
    )

    assert unchanged is not None
    assert unchanged.status == AgentRunStatus.PLANNING
    assert unchanged.error_code is None


def test_append_rejects_a_terminal_status_not_derived_from_the_requirement(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-unresolved.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_unresolved"))
    requirement = _initial_requirement(run)

    with pytest.raises(ResearchStoreConflict, match="transition"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.FAILED,
            error_code="deepsearch_clarification_unresolved",
            events=[("run_failed", {"error_code": "deepsearch_clarification_unresolved"})],
        )

    persisted_run = repository.get_agent_run(run.id)
    assert persisted_run is not None
    assert persisted_run.status == AgentRunStatus.PLANNING
    assert repository.get_active_deepsearch_requirement(run.id) is None


def test_prepare_lazily_expires_a_run_before_accepting_a_new_request(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-lazy-expiry.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_lazy_expiry"))
    first = _initial_requirement(run, blocking=True)
    initial = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=first,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )
    assert initial is not None
    checked_at = _CREATED_AT + timedelta(days=8)

    with pytest.raises(DeepSearchRequirementConflict) as caught:
        repository.prepare_deepsearch_requirement_append(
            run_id=run.id,
            user_id=run.user_id,
            request_key="new_after_expiry",
            request_hash="f" * 64,
            expected_requirement_version=1,
            expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            checked_at=checked_at,
        )

    assert caught.value.code == "deepsearch_run_expired"
    expired = repository.get_agent_run(run.id)
    assert expired is not None
    assert expired.status == AgentRunStatus.CANCELLED
    assert expired.error_code == "deepsearch_run_expired"
    events_after_expiry = repository.list_agent_run_events(run.id)

    with pytest.raises(DeepSearchRequirementConflict) as replayed_expiry:
        repository.prepare_deepsearch_requirement_append(
            run_id=run.id,
            user_id=run.user_id,
            request_key="another_request_after_expiry",
            request_hash="1" * 64,
            expected_requirement_version=1,
            expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            checked_at=checked_at + timedelta(seconds=1),
        )

    assert replayed_expiry.value.code == "deepsearch_run_expired"
    assert replayed_expiry.value.current_requirement_version == 1
    assert repository.get_agent_run(run.id) == expired
    assert repository.list_agent_run_events(run.id) == events_after_expiry


def test_append_rechecks_expiry_after_refinement_before_committing(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-append-expiry.sqlite3")
    checked_at = _CREATED_AT + timedelta(days=8)
    run, _created = repository.claim_new_agent_run(_run("run_requirement_append_expiry"))
    requirement = _initial_requirement(run, blocking=True)

    with pytest.raises(DeepSearchRequirementConflict) as caught:
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            checked_at=checked_at,
            events=[],
        )

    assert caught.value.code == "deepsearch_run_expired"
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None
    assert persisted.status == AgentRunStatus.CANCELLED
    assert repository.get_active_deepsearch_requirement(run.id) is None
    events_after_expiry = repository.list_agent_run_events(run.id)

    late_requirement = {
        **requirement,
        "request_key": "late_append_after_expiry",
        "request_hash": "2" * 64,
    }
    with pytest.raises(DeepSearchRequirementConflict) as late:
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=late_requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            checked_at=checked_at + timedelta(seconds=1),
            events=[],
        )

    assert late.value.code == "deepsearch_run_expired"
    assert repository.get_agent_run(run.id) == persisted
    assert repository.list_agent_run_events(run.id) == events_after_expiry


def test_requirement_events_reject_user_answer_content(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-event-content.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_event_content"))
    requirement = _initial_requirement(run, blocking=True)

    with pytest.raises(ResearchStoreConflict, match="event payload"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            events=[("deepsearch_clarification_answered", {"answer": "secret answer"})],
        )

    assert repository.get_active_deepsearch_requirement(run.id) is None
    assert repository.list_agent_run_events(run.id) == []


def test_requirement_events_reject_forged_allowlisted_values(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-event-forgery.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_event_forgery"))
    requirement = _initial_requirement(run)

    with pytest.raises(ResearchStoreConflict, match="event payload"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.PLANNING,
            events=[
                (
                    "deepsearch_requirement_created",
                    {
                        "requirement_version": 1,
                        "content_hash": "0" * 64,
                    },
                )
            ],
        )

    assert repository.get_active_deepsearch_requirement(run.id) is None
    assert repository.list_agent_run_events(run.id) == []


def test_requirement_events_reject_duplicate_canonical_events(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-event-duplicate.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_event_duplicate"))
    requirement = _initial_requirement(run)
    created_event = (
        "deepsearch_requirement_created",
        {
            "requirement_version_id": requirement["id"],
            "requirement_version": 1,
            "content_hash": requirement["content_hash"],
        },
    )

    with pytest.raises(ResearchStoreConflict, match="event payload"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.PLANNING,
            events=[created_event, created_event],
        )

    assert repository.get_active_deepsearch_requirement(run.id) is None
    assert repository.list_agent_run_events(run.id) == []


def test_requirement_events_require_exact_typed_payloads(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-event-shape.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_event_shape"))
    requirement = _initial_requirement(run)

    with pytest.raises(ResearchStoreConflict, match="event payload"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=requirement,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=AgentRunStatus.PLANNING,
            events=[
                (
                    "deepsearch_requirement_created",
                    {
                        "requirement_version_id": requirement["id"],
                        "requirement_version": True,
                        "content_hash": requirement["content_hash"],
                    },
                )
            ],
        )

    assert repository.get_active_deepsearch_requirement(run.id) is None


def test_clarification_events_reject_forged_derived_counts(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-event-count-forgery.sqlite3")
    run, _created = repository.claim_new_agent_run(_run("run_requirement_event_count_forgery"))
    first = _initial_requirement(run, blocking=True)
    repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=first,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )
    second = _requirement(
        run.id,
        version=2,
        request_key="event_count_forgery",
        derived_from=str(first["id"]),
        previous=first,
        blocking=True,
    )

    with pytest.raises(ResearchStoreConflict, match="event payload"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=run.id,
            user_id=run.user_id,
            requirement=second,
            expected_requirement_version=1,
            expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
            events=[
                (
                    "deepsearch_clarification_requested",
                    {
                        "requirement_version": 2,
                        "clarification_round": 2,
                        "question_count": 99,
                    },
                )
            ],
        )

    assert repository.get_active_deepsearch_requirement(run.id) == first


def test_new_run_claim_lazily_expires_an_old_deepsearch_gate(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-claim-expiry.sqlite3")
    expired_run = _claim_run_in_state(
        repository,
        "run_expired_before_claim",
        status=AgentRunStatus.WAITING_CLARIFICATION,
        interaction_expires_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    replacement = _run("run_after_expired", status=AgentRunStatus.PLANNING).model_copy(
        update={
            "thread_id": expired_run.thread_id,
            "client_turn_id": "turn_after_expired",
        }
    )

    claimed, created = repository.claim_new_agent_run(replacement)

    assert created is True
    assert claimed.id == replacement.id
    persisted_expired = repository.get_agent_run(expired_run.id)
    assert persisted_expired is not None
    assert persisted_expired.status == AgentRunStatus.CANCELLED
    assert persisted_expired.error_code == "deepsearch_interaction_expired"


def test_retry_run_can_clone_the_source_runs_latest_verified_requirement(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-requirement-retry-clone.sqlite3")
    source_run, _created = repository.claim_new_agent_run(_run("run_retry_source"))
    source_requirement = _initial_requirement(source_run)
    source_result = repository.append_deepsearch_requirement_and_transition(
        run_id=source_run.id,
        user_id=source_run.user_id,
        requirement=source_requirement,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
    )
    assert source_result is not None
    _replace_run_fixture(
        repository,
        source_result.run.model_copy(
            update={
                "status": AgentRunStatus.FAILED,
                "error_code": "deepsearch_execution_transient",
            }
        )
    )
    retry_run, _created = repository.claim_new_agent_run(
        _run("run_retry_clone", status=AgentRunStatus.PLANNING).model_copy(
            update={"retry_of_run_id": source_run.id}
        )
    )
    cloned = _retry_clone(source_requirement, retry_run)

    result = repository.append_deepsearch_requirement_and_transition(
        run_id=retry_run.id,
        user_id=retry_run.user_id,
        requirement=cloned,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
    )

    assert result is not None
    assert result.requirement["derived_from_requirement_version_id"] == source_requirement["id"]
    assert result.requirement["content_hash"] == source_requirement["content_hash"]


@pytest.mark.parametrize("invalidity", ["cross_owner", "cross_project", "nonlatest", "payload_drift"])
def test_retry_requirement_clone_rejects_invalid_source_or_payload(tmp_path, invalidity: str) -> None:
    repository = SQLiteStore(tmp_path / f"deepsearch-requirement-retry-{invalidity}.sqlite3")
    source_seed = _run(f"run_retry_source_{invalidity}")
    if invalidity == "cross_owner":
        source_seed = source_seed.model_copy(update={"user_id": "other_user"})
    source_run, _created = repository.claim_new_agent_run(source_seed)
    first = _initial_requirement(source_run, blocking=True)
    repository.append_deepsearch_requirement_and_transition(
        run_id=source_run.id,
        user_id=source_run.user_id,
        requirement=first,
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        events=[],
    )
    latest = _requirement(
        source_run.id,
        version=2,
        request_key=f"retry_{invalidity}_source_v2",
        derived_from=str(first["id"]),
        goal="Latest source goal",
        previous=first,
    )
    repository.append_deepsearch_requirement_and_transition(
        run_id=source_run.id,
        user_id=source_run.user_id,
        requirement=latest,
        expected_requirement_version=1,
        expected_run_status=AgentRunStatus.WAITING_CLARIFICATION,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
    )
    retry_seed = _run(f"run_retry_invalid_{invalidity}", status=AgentRunStatus.PLANNING).model_copy(
        update={"retry_of_run_id": source_run.id}
    )
    if invalidity == "cross_project":
        retry_seed = retry_seed.model_copy(update={"project_id": "other_project"})
    retry_run, _created = repository.claim_new_agent_run(retry_seed)
    cloned = _retry_clone(first if invalidity == "nonlatest" else latest, retry_run)
    if invalidity == "payload_drift":
        drifted_payload = {**cloned["payload"], "goal": "Drifted payload"}  # type: ignore[arg-type]
        cloned = {
            **cloned,
            "payload": drifted_payload,
            "content_hash": requirement_content_hash(drifted_payload),
        }

    with pytest.raises(ResearchStoreConflict, match="retry Requirement"):
        repository.append_deepsearch_requirement_and_transition(
            run_id=retry_run.id,
            user_id=retry_run.user_id,
            requirement=cloned,
            expected_requirement_version=None,
            expected_run_status=AgentRunStatus.PLANNING,
            next_run_status=(
                AgentRunStatus.WAITING_CLARIFICATION
                if invalidity == "nonlatest"
                else AgentRunStatus.PLANNING
            ),
            events=[],
        )

    assert repository.get_active_deepsearch_requirement(retry_run.id) is None
