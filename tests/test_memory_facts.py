from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_facts import MemoryFactsError, MemoryFactsService, document_evidence_hash
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.memory_payloads import FactAssertionV1, FactQueryV1, FactRememberV1, MemoryFactV1
from agentmesh.models import DocumentRecord, MemoryLayer, Project, Source, User, UserMemoryItem, Workspace
from agentmesh.store import SQLiteStore

NOW = datetime(2026, 10, 4, 1, 30, tzinfo=UTC)


@pytest.fixture
def fact_project(tmp_path):
    repository = SQLiteStore(tmp_path / "facts.sqlite3")
    repository.save_workspace(Workspace(id="ws", name="Pilot", description="Pilot"))
    owner = repository.save_user(
        User(id="owner", workspace_id="ws", default_project_id="project", name="Owner", role="user",
             personal_agent_id="owner_agent")
    )
    peer = repository.save_user(owner.model_copy(update={"id": "peer", "personal_agent_id": "peer_agent"}))
    repository.save_project(Project(id="project", workspace_id="ws", name="Pilot", goal="Deliver",
                                    member_ids=[owner.id, peer.id]))
    source = repository.add_source(Source(id="source", title="Confirmed assignments", source_type="manual",
                                          reference="local://assignments", workspace_id="ws", project_id="project",
                                          user_id=owner.id))
    document = repository.add_document(
        DocumentRecord(id="document", title=source.title, file_name="assignment.txt", content_type="text/plain",
                       text="Alice was owner until October 1. Bob is owner from October 1.", source=source,
                       workspace_id="ws", project_id="project", uploaded_by=owner.id)
    )
    yield repository, owner, peer, document, MemoryFactsService(repository, clock=lambda: NOW)
    repository.close()


def _assertion(value="Bob", *, start="2026-10-01T00:00:00+00:00", end=None, predicate="owner", **kwargs):
    return FactAssertionV1(subject_type="project", subject_id="project", predicate=predicate, value=value,
                           valid_from=start, valid_to=end, **kwargs)


def _remember(fixture, *facts, command="remember-owner"):
    _, owner, _, document, service = fixture
    return service.remember(FactRememberV1(command_id=command, title="Project ownership", summary="Assignment facts",
                                          project_id="project", source_document_id=document.id,
                                          source_version=document.version,
                                          source_hash=document_evidence_hash(document), facts=list(facts)), owner)


def _query(service, owner, **kwargs):
    return service.query(FactQueryV1(project_id="project", subject_type="project", subject_id="project",
                                     predicate="owner", **kwargs), owner)


def test_explicit_remember_is_private_persistent_idempotent_and_not_a_model_call(fact_project):
    repository, owner, peer, _, service = fact_project
    item = _remember(fact_project, _assertion())
    assert item.scope == "private"
    assert item.facts[0].source_classification == "human_confirmed"
    assert item.facts[0].observed_at == NOW
    assert item.facts[0].evidence_refs[0].record_id == "document"
    assert _remember(fact_project, _assertion()).id == item.id
    assert len(repository.user_memory_items) == 1
    assert _query(service, owner).outcome == "known"
    assert _query(service, peer).outcome == "unknown"
    repository.close()
    reopened = SQLiteStore(repository.db_path)
    try:
        result = _query(MemoryFactsService(reopened, clock=lambda: NOW), owner)
        assert result.facts[0].memory_id == item.id
        assert result.facts[0].memory_hash == memory_content_hash(item)
    finally:
        reopened.close()


def test_history_uses_current_eligible_memory_and_half_open_valid_intervals(fact_project):
    _, owner, _, _, service = fact_project
    item = _remember(fact_project, _assertion("Alice", start="2026-09-01T00:00:00+00:00",
                                             end="2026-10-01T00:00:00+00:00"), _assertion())
    past = _query(service, owner, as_of="2026-09-15T00:00:00+00:00")
    boundary = _query(service, owner, as_of="2026-10-01T00:00:00+00:00")
    assert [hit.fact.value for hit in past.facts] == ["Alice"]
    assert [hit.fact.value for hit in boundary.facts] == ["Bob"]
    period = _query(service, owner, interval_from="2026-09-01T00:00:00+00:00",
                    interval_to="2026-11-01T00:00:00+00:00")
    assert period.outcome == "known"
    assert len(period.facts) == 2
    assert all(hit.memory_id == item.id for hit in period.facts)


def test_later_observation_does_not_replace_an_overlapping_value(fact_project):
    repository, owner, _, _, service = fact_project
    first = _remember(fact_project, _assertion("Alice"), command="first")
    second = _remember(fact_project, _assertion("Bob"), command="second")
    result = _query(service, owner)
    assert result.outcome == "conflict"
    assert {hit.memory_id for hit in result.facts} == {first.id, second.id}
    assert len(result.conflicts) == 1
    assert result.automatic_context_eligible is False
    assert repository.get_user_memory_item(first.id).status == "active"
    assert repository.get_user_memory_item(second.id).status == "active"


def test_multi_value_predicate_is_not_reported_as_an_owner_conflict(fact_project):
    _, owner, _, _, service = fact_project
    _remember(fact_project, _assertion("Alice", predicate="participant"),
              _assertion("Bob", predicate="participant"))
    result = service.query(FactQueryV1(project_id="project", subject_type="project", subject_id="project",
                                     predicate="participant"), owner)
    assert result.outcome == "known"
    assert len(result.facts) == 2
    assert result.conflicts == []


def test_source_update_invalidates_old_evidence_even_for_historical_question(fact_project):
    repository, owner, _, document, service = fact_project
    _remember(fact_project, _assertion())
    assert _query(service, owner).outcome == "known"
    document.text = "Changed after capture"
    document.version += 1
    repository.save_document(document)
    result = _query(service, owner, as_of="2026-10-02T00:00:00+00:00")
    assert result.outcome == "insufficient_evidence"
    assert result.facts == []
    assert result.missing_data == ["fact_evidence_unavailable"]


def test_archived_or_superseded_personal_memory_is_not_reactivated_by_history(fact_project):
    repository, owner, _, _, service = fact_project
    item = _remember(fact_project, _assertion())
    item.status = "archived"
    item.archived_at = NOW
    repository.save_user_memory_item(item)
    assert _query(service, owner, as_of="2026-10-02T00:00:00+00:00").outcome == "unknown"


@pytest.mark.parametrize("change", ["membership", "workspace", "disabled", "project_archived"])
def test_fresh_actor_and_project_authorization_are_required(fact_project, change):
    repository, owner, _, _, service = fact_project
    _remember(fact_project, _assertion())
    if change in {"membership", "project_archived"}:
        project = repository.get_project("project")
        project.member_ids = ["peer"] if change == "membership" else project.member_ids
        project.status = "archived" if change == "project_archived" else project.status
        repository.save_project(project)
    else:
        updated = owner.model_copy(update={"workspace_id": "foreign"} if change == "workspace"
                                   else {"status": "disabled"})
        repository.save_user(updated)
    with pytest.raises(MemoryFactsError, match="project_not_found"):
        _query(service, owner)
    with pytest.raises(MemoryFactsError, match="project_not_found"):
        _remember(fact_project, _assertion())


def test_remember_rejects_source_owned_by_another_person_and_forged_entity(fact_project):
    _, owner, peer, document, service = fact_project
    request = FactRememberV1(command_id="forge", title="Fact", summary="Fact", project_id="project",
                             source_document_id=document.id, source_version=1,
                             source_hash=document_evidence_hash(document), facts=[_assertion()])
    with pytest.raises(MemoryFactsError, match="fact_source_not_found"):
        service.remember(request, peer)
    with pytest.raises(MemoryFactsError, match="fact_subject_not_found"):
        service.remember(request.model_copy(update={"facts": [_assertion().model_copy(
            update={"subject_id": "foreign_project"})]}), owner)


def test_command_replay_cannot_change_input(fact_project):
    _remember(fact_project, _assertion())
    with pytest.raises(MemoryFactsError, match="fact_command_conflict"):
        _remember(fact_project, _assertion("Charlie"))


def test_observed_before_is_separate_from_valid_time(fact_project):
    _, owner, _, _, service = fact_project
    _remember(fact_project, _assertion("Alice", start="2026-09-01T00:00:00+00:00"))
    assert _query(service, owner, as_of="2026-09-02T00:00:00+00:00").outcome == "known"
    assert _query(service, owner, as_of="2026-09-02T00:00:00+00:00",
                  observed_before="2026-09-02T00:00:00+00:00").outcome == "unknown"


def test_model_inference_cannot_be_returned_as_confirmed_fact(fact_project):
    repository, owner, _, _, service = fact_project
    item = _remember(fact_project, _assertion())
    item.facts = [item.facts[0].model_copy(update={"source_classification": "model_inference"})]
    repository.save_user_memory_item(item)
    result = _query(service, owner)
    assert result.outcome == "insufficient_evidence"
    assert result.automatic_context_eligible is False
    assert result.missing_data == ["fact_requires_confirmation"]


def test_payload_hash_is_versioned_and_legacy_personal_hash_is_unchanged(fact_project):
    _, owner, _, _, _ = fact_project
    legacy = UserMemoryItem(id="legacy", user_id=owner.id, workspace_id="ws", project_id="project",
                            layer=MemoryLayer.MID_TERM, title="Legacy", summary="Unchanged", source_kind="manual")
    expected = canonical_json_sha256({"schema_version": "user-memory-content-v1", "id": legacy.id,
                                     "title": legacy.title, "summary": legacy.summary,
                                     "memory_type": legacy.memory_type, "user_id": owner.id,
                                     "workspace_id": "ws", "project_id": "project", "layer": legacy.layer,
                                     "sources": [], "provenance": None, "created_at": legacy.created_at})
    assert memory_content_hash(legacy) == expected
    item = _remember(fact_project, _assertion())
    assert memory_content_hash(item) != memory_content_hash(item.model_copy(update={"facts": None}))
    assert memory_content_hash(item) != memory_content_hash(item.model_copy(update={"facts": [
        item.facts[0].model_copy(update={"value": "Charlie"})]}))
    assert memory_content_hash(item.model_copy(update={"version": 2, "status": "archived"})) == memory_content_hash(item)


@pytest.mark.parametrize("patch", [
    {"valid_to": "2026-09-01T00:00:00+00:00"},
    {"valid_from": "2026-10-01T00:00:00"},
    {"time_precision": "unknown"},
])
def test_fact_time_contract_rejects_invalid_or_invented_precision(patch):
    with pytest.raises(ValidationError):
        FactAssertionV1.model_validate({**_assertion().model_dump(mode="json"), **patch})


def test_fact_contract_requires_versioned_evidence(fact_project):
    item = _remember(fact_project, _assertion())
    raw = item.facts[0].model_dump(mode="json")
    raw["evidence_refs"] = []
    with pytest.raises(ValidationError):
        MemoryFactV1.model_validate(raw)


def test_personal_correction_keeps_approved_history_on_the_new_eligible_record(fact_project):
    repository, owner, peer, document, service = fact_project
    old = _remember(fact_project, _assertion("Alice", start="2026-09-01T00:00:00+00:00"))
    request = FactRememberV1(command_id="correct-owner", title="Corrected owners", summary="Confirmed history",
                             project_id="project", source_document_id=document.id, source_version=1,
                             source_hash=document_evidence_hash(document), supersedes_memory_id=old.id,
                             expected_memory_version=1, facts=[
                                 _assertion("Alice", start="2026-09-01T00:00:00+00:00",
                                            end="2026-10-01T00:00:00+00:00"), _assertion(),
                             ])
    with pytest.raises(MemoryFactsError, match="fact_memory_not_found"):
        service.remember(request, peer)
    updated = service.remember(request, owner)
    assert updated.supersedes_memory_id == old.id
    assert updated.provenance.source_memory_hashes == [memory_content_hash(old)]
    assert repository.get_user_memory_item(old.id).status == "deprecated"
    assert repository.get_user_memory_item(old.id).version == 2
    assert _query(service, owner).outcome == "known"
    assert [hit.fact.value for hit in _query(service, owner).facts] == ["Bob"]
    assert [hit.fact.value for hit in _query(service, owner, as_of="2026-09-15T00:00:00+00:00").facts] == ["Alice"]
    assert service.remember(request, owner).id == updated.id
    with pytest.raises(MemoryFactsError, match="fact_memory_version_conflict"):
        service.remember(request.model_copy(update={"command_id": "stale-correction"}), owner)


def test_structured_memory_does_not_enter_the_legacy_summary_context(fact_project):
    from agentmesh.memory_context.service import MemoryContextService

    repository, owner, _, _, _ = fact_project
    item = _remember(fact_project, _assertion())
    bundle = MemoryContextService(repository).retrieve("Assignment facts Project ownership", user=owner,
                                                      agent_id=owner.personal_agent_id, record_metrics=False)
    assert item.id not in {hit.memory_id for hit in bundle.hits}


def test_fact_http_routes_validate_input_and_return_authorized_records(fact_project, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from agentmesh.routes import memory_facts
    from agentmesh.routes.deps import current_user

    repository, owner, _, _, _ = fact_project
    item = _remember(fact_project, _assertion())
    monkeypatch.setattr(memory_facts, "store", repository)
    app = FastAPI()
    app.include_router(memory_facts.router)
    app.dependency_overrides[current_user] = lambda: owner
    client = TestClient(app)
    response = client.post("/api/memory/facts/query", json={"project_id": "project", "subject_type": "project",
                                                           "subject_id": "project", "predicate": "owner"})
    assert response.status_code == 200, response.text
    assert response.json()["facts"][0]["memory_id"] == item.id
    assert client.post("/api/memory/facts/query", json={"project_id": "project"}).status_code == 422
    owner.status = "disabled"
    repository.save_user(owner)
    assert client.post("/api/memory/facts/query", json={"project_id": "project", "subject_type": "project",
                                                       "subject_id": "project", "predicate": "owner"}).status_code == 404


def test_document_evidence_identity_is_available_only_to_its_current_owner(fact_project):
    repository, owner, peer, document, service = fact_project
    ref = service.document_evidence(document.id, owner)
    assert ref.record_type == "document"
    assert ref.record_id == document.id
    assert ref.version == document.version
    assert ref.content_hash == document_evidence_hash(document)
    with pytest.raises(MemoryFactsError, match="fact_source_not_found"):
        service.document_evidence(document.id, peer)
    project = repository.get_project("project")
    project.member_ids = [peer.id]
    repository.save_project(project)
    with pytest.raises(MemoryFactsError, match="project_not_found"):
        service.document_evidence(document.id, owner)


def test_legacy_summary_cannot_copy_structured_facts_into_unchecked_automatic_memory(fact_project, monkeypatch):
    from fastapi import HTTPException

    from agentmesh.models import ProjectArchiveRequest
    from agentmesh.routes import memory

    repository, owner, _, _, _ = fact_project
    _remember(fact_project, _assertion())
    monkeypatch.setattr(memory, "store", repository)
    with pytest.raises(HTTPException) as error:
        memory.archive_project_memory(ProjectArchiveRequest(project_id="project"), owner)
    assert error.value.status_code == 400
    assert len(repository.user_memory_items) == 1


def test_context_filter_does_not_load_each_unmatched_memory_again(fact_project, monkeypatch):
    from agentmesh.memory_context.service import MemoryContextService

    repository, owner, _, _, _ = fact_project
    for index in range(100):
        repository.add_user_memory_item(UserMemoryItem(
            id=f"bulk_{index}", user_id=owner.id, workspace_id="ws", project_id="project", layer=MemoryLayer.MID_TERM,
            title="Unrelated note", summary="Background context only", source_kind="manual",
        ))
    point_reads = 0
    original = repository.get_user_memory_item

    def counted(memory_id):
        nonlocal point_reads
        point_reads += 1
        return original(memory_id)

    monkeypatch.setattr(repository, "get_user_memory_item", counted)
    MemoryContextService(repository).retrieve("missingtermxyz", user=owner, agent_id=owner.personal_agent_id,
                                              record_metrics=False)
    assert point_reads < 40


@pytest.mark.parametrize("patch", [
    {"time_precision": "day", "valid_from": "2026-10-01T12:00:00+00:00"},
    {"time_precision": "month", "valid_from": "2026-10-04T00:00:00+00:00"},
    {"time_precision": "month", "valid_to": "2026-11-04T00:00:00+00:00"},
])
def test_coarse_fact_precision_requires_matching_calendar_bounds(patch):
    with pytest.raises(ValidationError):
        FactAssertionV1.model_validate({**_assertion().model_dump(mode="json"), **patch})


def test_unicode_equivalent_values_are_not_a_false_conflict(fact_project):
    _, owner, _, _, service = fact_project
    _remember(fact_project, _assertion("Caf\u00e9"), command="nfc")
    _remember(fact_project, _assertion("Cafe\u0301"), command="nfd")
    assert _query(service, owner).outcome == "known"


@pytest.mark.parametrize("departure", ["disable", "leave", "transfer"])
def test_inactive_subject_does_not_erase_authorized_historical_facts(fact_project, departure):
    repository, owner, peer, document, service = fact_project
    request = FactRememberV1(command_id="peer-history", title="Past role", summary="Confirmed past role",
                             project_id="project", source_document_id=document.id, source_version=1,
                             source_hash=document_evidence_hash(document), facts=[FactAssertionV1(
                                 subject_type="user", subject_id=peer.id, predicate="role", value="Reviewer",
                                 valid_from="2026-09-01T00:00:00+00:00", valid_to="2026-10-01T00:00:00+00:00",
                             )])
    service.remember(request, owner)
    if departure == "disable":
        repository.save_user(peer.model_copy(update={"status": "disabled"}))
    elif departure == "leave":
        repository.save_project(repository.get_project("project").model_copy(update={"member_ids": [owner.id]}))
    else:
        repository.save_user(peer.model_copy(update={"workspace_id": "other_workspace"}))
    result = service.query(FactQueryV1(project_id="project", subject_type="user", subject_id=peer.id,
                                      predicate="role", as_of="2026-09-15T00:00:00+00:00"), owner)
    assert result.outcome == "known"
    assert result.facts[0].fact.value == "Reviewer"


def test_archived_shared_task_does_not_erase_its_approved_fact_history(fact_project, monkeypatch):
    from agentmesh.task_management.contracts import TaskArchiveRequest, TaskCreateRequest, TaskTransitionRequest
    from agentmesh.task_management.service import TaskManagementService

    repository, owner, _, document, service = fact_project
    monkeypatch.setenv("AGENTMESH_TASK_MANAGEMENT", "write")
    owner = repository.save_user(owner.model_copy(update={"role": "admin"}))
    tasks = TaskManagementService(repository)
    task = tasks.create_task(TaskCreateRequest(command_id="create-history", title="Shared task"), owner).task
    service.remember(FactRememberV1(command_id="task-history", title="Task history", summary="Confirmed past owner",
                                    project_id="project", source_document_id=document.id, source_version=1,
                                    source_hash=document_evidence_hash(document), facts=[FactAssertionV1(
                                        subject_type="task", subject_id=task.id, predicate="owner", value="Alice",
                                        valid_from="2026-09-01T00:00:00+00:00", valid_to="2026-10-01T00:00:00+00:00",
                                    )]), owner)
    cancelled = tasks.transition_task(task.id, TaskTransitionRequest(
        command_id="cancel-history", expected_version=1, action="cancel",
    ), owner)
    tasks.archive_task(task.id, TaskArchiveRequest(command_id="archive-history",
                                                  expected_version=cancelled.management.version), owner)
    result = service.query(FactQueryV1(project_id="project", subject_type="task", subject_id=task.id, predicate="owner",
                                      as_of="2026-09-15T00:00:00+00:00"), owner)
    assert result.outcome == "known"
