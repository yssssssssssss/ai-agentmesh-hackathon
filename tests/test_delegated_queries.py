from __future__ import annotations

import pytest

from agentmesh.delegated_queries import (
    DelegatedQueryCreate,
    DelegatedQueryError,
    DelegatedQueryService,
    QueryAdoptRequest,
    QueryConsentRequest,
)
from agentmesh.models import MemoryLayer, Scope, Source, UserMemoryItem
from agentmesh.seed import PROJECT, TEAM_LEAD, USER, ensure_seed_data
from agentmesh.store import SQLiteStore


class RecordingLLM:
    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def complete(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if self.callback:
            self.callback()
        return "建议分级控制触发阈值，并检查购物车链路。"


@pytest.fixture
def query_setup(tmp_path):
    repository = SQLiteStore(tmp_path / "queries.sqlite3")
    ensure_seed_data(repository)
    memory = repository.add_user_memory_item(UserMemoryItem(
        id="query-evidence", user_id=USER.id, workspace_id=USER.workspace_id, project_id=PROJECT.id,
        layer=MemoryLayer.MID_TERM, source_kind="note", title="降级预案内部开关", summary="按业务等级设置阈值。",
        sources=[Source(title="PRIVATE_SOURCE_TITLE", reference="private://SECRET_LINK", source_type="note")],
    ))
    model = RecordingLLM()
    return repository, memory, model, DelegatedQueryService(repository, llm_client=model)


def create_query(service, *, command="ask-1"):
    return service.create(TEAM_LEAD, DelegatedQueryCreate(
        project_id=PROJECT.id, target_id=USER.id, question="降级预案如何做", command_id=command,
    ))


def approve(service, query):
    return service.resolve(USER, query.id, action="approve", expected_version=query.version)


def test_confirmation_result_survives_database_reopen_with_restricted_citations(query_setup):
    repository, memory, model, service = query_setup
    pending = create_query(service)
    assert pending.status == "awaiting_confirm" and pending.answer is None
    assert len(model.calls) == 0
    inbox = repository.get_inbox_item(pending.inbox_item_id)
    assert inbox.user_id == USER.id and inbox.project_id == PROJECT.id and inbox.scope is Scope.PRIVATE
    answered = approve(service, pending)
    assert answered.status == "answered" and answered.current_available
    assert len(model.calls) == 1

    reopened = DelegatedQueryService(SQLiteStore(repository.db_path), llm_client=model)
    found = reopened.get(TEAM_LEAD, answered.id)
    assert found.answer == answered.answer and found.artifact_hash == answered.artifact_hash
    assert len(model.calls) == 1
    serialized = found.model_dump_json()
    assert memory.summary not in serialized and memory.id not in serialized
    assert "PRIVATE_SOURCE_TITLE" not in serialized and "SECRET_LINK" not in serialized
    assert found.citations and found.citations[0].reference.startswith("delegated-query://")


def test_adopted_memory_is_withheld_when_helper_evidence_changes(query_setup):
    from contextlib import closing

    from agentmesh.memory_context.origin import memory_origin_available

    repository, evidence, _, service = query_setup
    answered = approve(service, create_query(service))
    adoption = service.adopt(TEAM_LEAD, answered.id, QueryAdoptRequest(
        command_id="adopt", expected_version=answered.version, artifact_hash=answered.artifact_hash,
    ))
    memory = repository.get_user_memory_item(adoption.memory_id)
    with closing(repository._read_connect()) as connection:
        assert memory_origin_available(connection, memory)
    repository.add_user_memory_item(evidence.model_copy(update={"summary": "另一个秘密正文", "version": 2}))
    with closing(repository._read_connect()) as connection:
        assert not memory_origin_available(connection, memory)
    found = service.get(TEAM_LEAD, answered.id)
    assert found.status == "answered" and not found.current_available
    assert found.answer is None and found.citations == []


def test_query_create_command_deduplicates_and_rejects_changed_question(query_setup):
    _, _, model, service = query_setup
    first = create_query(service)
    assert create_query(service).id == first.id
    with pytest.raises(DelegatedQueryError, match="query_command_conflict"):
        service.create(TEAM_LEAD, DelegatedQueryCreate(
            project_id=PROJECT.id, target_id=USER.id, question="另一个问题", command_id="ask-1",
        ))
    assert not model.calls


def test_verified_adoption_is_atomic_and_idempotent_after_reopen(query_setup):
    repository, _, model, service = query_setup
    answered = approve(service, create_query(service))
    request = QueryAdoptRequest(command_id="adopt-1", expected_version=answered.version,
                               artifact_hash=answered.artifact_hash)
    first = service.adopt(TEAM_LEAD, answered.id, request)
    reopened = DelegatedQueryService(SQLiteStore(repository.db_path), llm_client=model)
    assert reopened.adopt(TEAM_LEAD, answered.id, request) == first
    another = request.model_copy(update={"command_id": "adopt-2"})
    assert reopened.adopt(TEAM_LEAD, answered.id, another) == first
    memory = repository.get_user_memory_item(first.memory_id)
    assert memory.user_id == TEAM_LEAD.id and memory.scope is Scope.PRIVATE
    assert memory.summary == answered.answer
    assert len(repository.contribution_points) == 1 and len(repository.memory_relations) == 1
    assert len(model.calls) == 1


def enable_automatic(repository, service):
    repository.set_market_participation(USER.id, True)
    repository.set_market_participation(TEAM_LEAD.id, True)
    service.set_consent(USER, QueryConsentRequest(project_id=PROJECT.id, grantee_id=TEAM_LEAD.id,
        enabled=True, expected_version=0, command_id="consent-1"))


def test_scoped_consent_requires_both_participations_and_sensitive_confirmation(query_setup):
    repository, evidence, model, service = query_setup
    enable_automatic(repository, service)
    answered = create_query(service)
    assert answered.status == "answered" and len(model.calls) == 1
    repository.set_market_participation(TEAM_LEAD.id, False)
    pending = create_query(service, command="ask-2")
    assert pending.status == "awaiting_confirm" and len(model.calls) == 1
    repository.set_market_participation(TEAM_LEAD.id, True)
    repository.add_user_memory_item(evidence.model_copy(update={"sensitivity": "high"}))
    sensitive = create_query(service, command="ask-3")
    assert sensitive.status == "awaiting_confirm" and len(model.calls) == 1


def test_global_legacy_consent_cannot_authorize_new_project_queries(query_setup):
    from agentmesh.agents import PersonalAgent

    repository, _, model, service = query_setup
    repository.set_market_participation(USER.id, True)
    repository.set_market_participation(TEAM_LEAD.id, True)
    PersonalAgent(repository).grant_consent(USER, TEAM_LEAD)
    assert create_query(service).status == "awaiting_confirm"
    assert not model.calls


@pytest.mark.parametrize("mutation", ["evidence", "consent", "participation", "membership"])
def test_current_changes_during_model_call_discard_answer_without_artifact(query_setup, mutation):
    repository, evidence, model, service = query_setup
    enable_automatic(repository, service)

    def mutate():
        if mutation == "evidence":
            repository.add_user_memory_item(evidence.model_copy(update={"summary": "更改后的依据", "version": 2}))
        elif mutation == "consent":
            service.set_consent(USER, QueryConsentRequest(project_id=PROJECT.id, grantee_id=TEAM_LEAD.id,
                enabled=False, expected_version=1, command_id="revoke"))
        elif mutation == "participation":
            repository.set_market_participation(USER.id, False)
        else:
            project = repository.get_project(PROJECT.id)
            repository.save_project(project.model_copy(update={"member_ids": [USER.id]}))

    model.callback = mutate
    if mutation == "membership":
        with pytest.raises(DelegatedQueryError, match="delegated_query_not_found"):
            create_query(service)
    else:
        result = create_query(service)
        assert result.status == "blocked" and result.answer is None
    with repository._connect() as connection:
        assert connection.execute("SELECT count(*) FROM artifacts WHERE artifact_type = 'delegated_answer'").fetchone()[0] == 0
    assert len(model.calls) == 1


def test_stale_confirmation_does_not_consume_inbox_or_call_model(query_setup):
    repository, evidence, model, service = query_setup
    pending = create_query(service)
    repository.add_user_memory_item(evidence.model_copy(update={"sensitivity": "high"}))
    with pytest.raises(DelegatedQueryError, match="query_evidence_changed"):
        approve(service, pending)
    assert repository.get_inbox_item(pending.inbox_item_id).status == "open"
    assert not model.calls


def test_third_party_admin_cannot_read_resolve_or_adopt(query_setup):
    from agentmesh.seed import ADMIN

    _, _, model, service = query_setup
    query = create_query(service)
    with pytest.raises(DelegatedQueryError, match="not_found"):
        service.get(ADMIN, query.id)
    with pytest.raises(DelegatedQueryError, match="not_found"):
        service.resolve(ADMIN, query.id, action="approve", expected_version=query.version)
    assert service.list(ADMIN, PROJECT.id).items == []
    assert not model.calls


def test_revocation_hides_result_and_prevents_even_replayed_adoption(query_setup):
    repository, _, _, service = query_setup
    enable_automatic(repository, service)
    answered = create_query(service)
    request = QueryAdoptRequest(command_id="adopt", expected_version=answered.version, artifact_hash=answered.artifact_hash)
    service.adopt(TEAM_LEAD, answered.id, request)
    service.set_consent(USER, QueryConsentRequest(project_id=PROJECT.id, grantee_id=TEAM_LEAD.id,
        enabled=False, expected_version=1, command_id="revoke"))
    current = service.get(TEAM_LEAD, answered.id)
    assert not current.current_available and current.answer is None and current.citations == []
    with pytest.raises(DelegatedQueryError, match="query_consent_changed"):
        service.adopt(TEAM_LEAD, answered.id, request)
    assert len(repository.contribution_points) == 1


@pytest.mark.parametrize(('column', 'value'), [('content_hash', '0' * 64), ('content_type', 'text/html'), ('user_id', USER.id)])
def test_answer_artifact_hash_and_index_tampering_cannot_be_adopted(query_setup, column, value):
    repository, _, _, service = query_setup
    answered = approve(service, create_query(service))
    with repository._connect() as connection:
        connection.execute(f"UPDATE artifacts SET {column} = ? WHERE run_id = ?", (value, answered.id))
    current = service.get(TEAM_LEAD, answered.id)
    assert not current.current_available and current.answer is None
    with pytest.raises(DelegatedQueryError, match="query_artifact_unavailable"):
        service.adopt(TEAM_LEAD, answered.id, QueryAdoptRequest(
            command_id="adopt", expected_version=answered.version, artifact_hash=answered.artifact_hash,
        ))
    assert not repository.contribution_points


def test_interrupted_model_claim_is_visible_after_restart_and_never_retried(query_setup, monkeypatch):
    from datetime import timedelta

    from agentmesh.models import now_utc

    repository, _, model, service = query_setup
    pending = create_query(service)

    def crash():
        raise KeyboardInterrupt('simulate process interruption')

    model.callback = crash
    with pytest.raises(KeyboardInterrupt):
        approve(service, pending)
    reopened = DelegatedQueryService(SQLiteStore(repository.db_path), llm_client=model)
    assert reopened.get(TEAM_LEAD, pending.id).status == 'pending'
    future = now_utc() + timedelta(minutes=2)
    monkeypatch.setattr('agentmesh.delegated_queries.now_utc', lambda: future)
    failed = reopened.resume(TEAM_LEAD, pending.id)
    assert failed.status == 'failed' and failed.answer is None
    assert failed.unavailable_reason == 'query_interrupted_requires_new_request'
    assert len(model.calls) == 1


def test_helper_memory_binding_revocation_hides_delivered_answer(query_setup):
    from agentmesh.models import AgentMemoryBinding

    repository, _, _, service = query_setup
    answered = approve(service, create_query(service))
    binding = repository.get_binding_for_agent(USER.personal_agent_id)
    if binding is None:
        binding = AgentMemoryBinding(agent_id=USER.personal_agent_id)
    repository.save_agent_memory_binding(binding.model_copy(update={'allowed_scopes': [Scope.PROJECT]}))
    current = service.get(TEAM_LEAD, answered.id)
    assert not current.current_available and current.answer is None and current.citations == []


def test_unconfirmed_helper_type_policy_hides_already_delivered_answer(query_setup):
    from agentmesh.models import AgentMemoryBinding

    repository, memory, model, service = query_setup
    binding = repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=[memory.memory_type], type_policy_version=1))
    answered = approve(service, create_query(service))
    assert answered.current_available and len(model.calls) == 1
    repository.save_agent_memory_binding(binding.model_copy(update={'type_policy_version': None}))
    current = service.get(TEAM_LEAD, answered.id)
    assert not current.current_available and current.answer is None and current.citations == []
    assert len(model.calls) == 1


def test_helper_content_types_filter_before_the_match_candidate_budget(query_setup):
    from agentmesh.models import AgentMemoryBinding

    repository, memory, model, service = query_setup
    for index in range(205):
        repository.add_user_memory_item(memory.model_copy(update={
            'id': f'query_excluded_type_{index}', 'memory_type': 'decision'}))
    repository.save_agent_memory_binding(AgentMemoryBinding(
        agent_id=USER.personal_agent_id, allowed_memory_types=[memory.memory_type], type_policy_version=1))
    answered = approve(service, create_query(service))
    assert answered.status == 'answered' and answered.current_available and len(model.calls) == 1
