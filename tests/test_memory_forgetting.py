from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from agentmesh.memory_facts import MemoryFactsService, document_evidence_hash
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.memory_lifecycle import MemoryForgetRequestV1, MemoryForgettingService, MemoryLifecycleError
from agentmesh.memory_payloads import FactAssertionV1, FactQueryV1, FactRememberV1
from agentmesh.models import (
    DocumentRecord,
    MemoryItem,
    MemoryLayer,
    MemoryProvenanceV1,
    Project,
    Source,
    User,
    UserMemoryItem,
)
from agentmesh.store import SQLiteStore

NOW = datetime(2026, 10, 4, tzinfo=UTC)


@pytest.fixture
def memory_source(tmp_path):
    store = SQLiteStore(tmp_path / 'memory.sqlite3')
    owner = store.save_user(User(id='owner', workspace_id='ws', default_project_id='project', name='Owner',
                                 role='user', personal_agent_id='agent'))
    peer = store.save_user(owner.model_copy(update={'id': 'peer'}))
    store.save_project(Project(id='project', workspace_id='ws', name='Pilot', goal='Deliver',
                               member_ids=[owner.id, peer.id]))
    source = store.add_source(Source(id='source', title='Assignments', source_type='document', reference='local://doc',
                                     workspace_id='ws', project_id='project', user_id=owner.id))
    doc = store.add_document(DocumentRecord(id='doc', title='Assignments', text='Bob owns the project.',
                                            file_name='assignments.txt', content_type='text/plain', source=source,
                                            workspace_id='ws', project_id='project', uploaded_by=owner.id))
    service = MemoryFactsService(store, clock=lambda: NOW)
    fact = service.remember(FactRememberV1(command_id='remember', title='Owner', summary='Confirmed assignment',
                                           project_id='project', source_document_id=doc.id, source_version=1,
                                           source_hash=document_evidence_hash(doc), facts=[FactAssertionV1(
                                               subject_type='project', subject_id='project', predicate='owner',
                                               value='Bob', valid_from=NOW,
                                           )]), owner)
    yield store, owner, peer, doc, fact
    store.close()


def test_forget_is_an_owned_private_versioned_barrier_and_survives_restart(memory_source):
    store, owner, peer, _, fact = memory_source
    service = MemoryForgettingService(store, clock=lambda: NOW)
    request = MemoryForgetRequestV1(command_id='forget', expected_version=1)
    with pytest.raises(MemoryLifecycleError, match='memory_not_found'):
        service.forget(fact.id, request, peer)
    with pytest.raises(MemoryLifecycleError, match='memory_version_conflict'):
        service.forget(fact.id, request.model_copy(update={'expected_version': 2}), owner)
    result = service.forget(fact.id, request, owner)
    assert result.invalidated_count == 1
    assert service.forget(fact.id, request, owner) == result
    forgotten = store.get_user_memory_item(fact.id)
    assert forgotten.status == 'forgotten'
    assert forgotten.summary == '' and forgotten.facts is None
    assert forgotten.version == 2
    store.close()
    reopened = SQLiteStore(store.db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match='memory_forgotten'):
            reopened.save_user_memory_item(fact)
        query = MemoryFactsService(reopened).query(FactQueryV1(project_id='project', subject_type='project',
                                                               subject_id='project', predicate='owner'), owner)
        assert query.outcome == 'unknown'
    finally:
        reopened.close()


def test_forget_invalidates_frozen_private_lineage_and_blocks_late_derived_writes(memory_source):
    store, owner, _, _, fact = memory_source
    derived = store.add_user_memory_item(UserMemoryItem(
        id='derived', user_id=owner.id, workspace_id='ws', project_id='project', layer=MemoryLayer.LONG_TERM,
        title='Summary', summary='Bob is owner.', source_kind='project_archive', provenance=MemoryProvenanceV1(
            source_kind='imported_document', created_by=owner.id, source_memory_ids=[fact.id],
            source_memory_versions=[fact.version], source_memory_hashes=[memory_content_hash(fact)],
        ),
    ))
    service = MemoryForgettingService(store, clock=lambda: NOW)
    assert service.forget(fact.id, MemoryForgetRequestV1(command_id='forget', expected_version=1), owner).invalidated_count == 2
    assert store.get_user_memory_item(derived.id).status == 'forgotten'
    with pytest.raises(sqlite3.IntegrityError, match='memory_source_withdrawn'), store._connect() as connection:
        store._upsert_plain_record(connection, 'user_memory_items', derived.model_copy(update={'id': 'late_summary'}))


def test_shared_memory_cannot_be_forgotten_by_its_original_author(memory_source):
    store, owner, _, _, _ = memory_source
    shared = store.add_memory_item(MemoryItem(id='shared', title='Team fact', summary='Governed team fact',
                                             memory_type='fact', scope='team_accepted', status='accepted',
                                             owner_user_id=owner.id, workspace_id='ws', project_id='project'))
    with pytest.raises(MemoryLifecycleError, match='memory_not_found'):
        MemoryForgettingService(store).forget(shared.id, MemoryForgetRequestV1(command_id='forget',
                                                                               expected_version=1), owner)
    assert store.get_memory_item(shared.id).status == 'accepted'


def test_source_withdrawal_redacts_document_and_blocks_late_ingestion(memory_source):
    store, owner, peer, doc, fact = memory_source
    service = MemoryForgettingService(store, clock=lambda: NOW)
    request = MemoryForgetRequestV1(command_id='withdraw', expected_version=1)
    with pytest.raises(MemoryLifecycleError, match='source_not_found'):
        service.withdraw_document(doc.id, request, peer)
    result = service.withdraw_document(doc.id, request, owner)
    assert result.invalidated_count == 2
    assert store.get_document(doc.id).withdrawn_at == NOW
    assert store.get_document(doc.id).text == ''
    assert store.get_user_memory_item(fact.id).status == 'forgotten'
    with pytest.raises(sqlite3.IntegrityError, match='memory_forgotten'):
        store.save_document(doc)
    with pytest.raises(sqlite3.IntegrityError, match='memory_source_withdrawn'):
        store.add_user_memory_item(UserMemoryItem(
            id='late_chunk', user_id=owner.id, workspace_id='ws', project_id='project', layer=MemoryLayer.LONG_TERM,
            title='Late chunk', summary=doc.text, source_kind='document_import', sources=[Source(
                title=doc.file_name, source_type='document', reference=f'document://{doc.id}#v1/chunk_0',
            )],
        ))


def test_cleanup_is_persistent_bounded_and_does_not_erase_team_records(memory_source):
    store, owner, _, doc, fact = memory_source
    shared = store.add_memory_item(MemoryItem(id='shared', title='Governed', summary='Reviewed copy',
                                             memory_type='fact', scope='team_accepted', status='accepted',
                                             owner_user_id=owner.id, workspace_id='ws', project_id='project',
                                             sources=[doc.source], facts=fact.facts))
    service = MemoryForgettingService(store, clock=lambda: NOW)
    result = service.withdraw_document(doc.id, MemoryForgetRequestV1(command_id='withdraw', expected_version=1), owner)
    assert result.invalidated_count == 3
    assert store.get_memory_item(shared.id).status == 'disputed'
    assert store.get_memory_item(shared.id).summary == shared.summary
    assert service.cleanup(limit=1) == 1
    store.close()
    reopened = SQLiteStore(store.db_path)
    try:
        worker = MemoryForgettingService(reopened)
        assert worker.cleanup(limit=100) == 2
        assert worker.cleanup(limit=100) == 0
        with reopened._read_connect() as connection:
            for collection, record_id in [('documents', doc.id), ('user_memory_items', fact.id), ('memory_items', shared.id)]:
                assert connection.execute('SELECT 1 FROM records_fts WHERE collection = ? AND record_id = ?',
                                          (collection, record_id)).fetchone() is None
                assert connection.execute('SELECT 1 FROM vector_states WHERE collection = ? AND record_id = ?',
                                          (collection, record_id)).fetchone() is None
    finally:
        reopened.close()


def test_new_summary_records_frozen_lineage_and_is_invalidated_when_a_source_is_forgotten(memory_source, monkeypatch):
    from agentmesh.models import ProjectMemorySummaryRequest
    from agentmesh.routes import memory

    store, owner, _, _, _ = memory_source
    note = store.add_user_memory_item(UserMemoryItem(id='note', user_id=owner.id, workspace_id='ws', project_id='project',
                                                     layer=MemoryLayer.SHORT_TERM, title='Sprint risk',
                                                     summary='Waiting on an external dependency.', source_kind='manual'))
    monkeypatch.setattr(memory, 'store', store)
    summary = memory.create_project_memory_summary(ProjectMemorySummaryRequest(project_id='project'), owner).item
    assert summary.provenance.source_memory_ids == [note.id]
    assert summary.provenance.source_memory_versions == [note.version]
    assert summary.provenance.source_memory_hashes == [memory_content_hash(note)]
    MemoryForgettingService(store).forget(note.id, MemoryForgetRequestV1(command_id='forget-note', expected_version=1), owner)
    assert store.get_user_memory_item(summary.id).status == 'forgotten'


def test_summary_cannot_commit_a_source_forgotten_during_generation(memory_source, monkeypatch):
    from fastapi import HTTPException

    from agentmesh.models import ProjectMemorySummaryRequest
    from agentmesh.routes import memory

    store, owner, _, _, _ = memory_source
    note = store.add_user_memory_item(UserMemoryItem(id='note', user_id=owner.id, workspace_id='ws', project_id='project',
                                                     layer=MemoryLayer.SHORT_TERM, title='Sprint risk',
                                                     summary='Waiting on an external dependency.', source_kind='manual'))
    monkeypatch.setattr(memory, 'store', store)

    def summarize(*args):
        MemoryForgettingService(store).forget(note.id, MemoryForgetRequestV1(command_id='forget-note', expected_version=1), owner)
        return 'Stale generated summary'

    monkeypatch.setattr(memory, '_summarize_project_memory', summarize)
    with pytest.raises(HTTPException) as error:
        memory.create_project_memory_summary(ProjectMemorySummaryRequest(project_id='project'), owner)
    assert error.value.status_code == 409
    assert not any(item.source_kind == 'short_term_rollup' for item in store.user_memory_items)


def test_withdrawal_expires_a_team_candidate_and_keeps_manager_archive_available(memory_source):
    from agentmesh.memory_governance.contracts import MemoryLifecycleAction
    from agentmesh.memory_governance.lifecycle import transition_memory_item

    store, owner, _, doc, _ = memory_source
    candidate = store.add_memory_item(MemoryItem(id='team_candidate', title='Candidate', summary='Suggested knowledge',
                                                memory_type='note', scope='team_candidate', status='proposed',
                                                owner_user_id=owner.id, workspace_id='ws', project_id='project',
                                                sources=[doc.source], provenance=MemoryProvenanceV1(
                                                    source_kind='imported_document', created_by=owner.id,
                                                )))
    MemoryForgettingService(store).withdraw_document(doc.id, MemoryForgetRequestV1(command_id='withdraw', expected_version=1), owner)
    invalidated = store.get_memory_item(candidate.id)
    assert invalidated.status == 'expired' and invalidated.evidence_withdrawn_at is not None
    archived = transition_memory_item(invalidated, action=MemoryLifecycleAction.ARCHIVE, actor_id='manager', changed_at=NOW)
    store.save_memory_item(archived)
    assert store.get_memory_item(candidate.id).status == 'archived'
    with pytest.raises(sqlite3.IntegrityError, match='memory_(forgotten|source_withdrawn)'):
        store.save_memory_item(MemoryItem.model_validate({**candidate.model_dump(mode='python'),
                                                        'status': 'accepted', 'scope': 'team_accepted'}))


def test_new_explicit_project_share_has_frozen_lineage_and_loses_source_eligibility_on_forget(memory_source, monkeypatch):
    from agentmesh.routes import memory

    store, owner, _, _, _ = memory_source
    note = store.add_user_memory_item(UserMemoryItem(id='share_note', user_id=owner.id, workspace_id='ws', project_id='project',
                                                     layer=MemoryLayer.MID_TERM, title='Project note', summary='Explicitly shared note.',
                                                     source_kind='manual'))
    monkeypatch.setattr(memory, 'store', store)
    shared = memory.share_user_memory_to_project(note.id, owner).item
    assert shared.metadata['source_memory_id'] == note.id
    assert shared.metadata['source_memory_version'] == str(note.version)
    assert shared.metadata['source_memory_hash'] == memory_content_hash(note)
    MemoryForgettingService(store).forget(note.id, MemoryForgetRequestV1(command_id='forget-shared-source', expected_version=1), owner)
    assert store.get_memory_item(shared.id).status == 'expired'
    assert store.get_memory_item(shared.id).summary == shared.summary


@pytest.mark.parametrize('kind', ['private_summary', 'project_share'])
def test_forget_follows_frozen_lineage_across_lifecycle_only_source_versions(memory_source, monkeypatch, kind):
    from agentmesh.routes import memory

    store, owner, _, _, _ = memory_source
    note = store.add_user_memory_item(UserMemoryItem(id='versioned_note', user_id=owner.id, workspace_id='ws', project_id='project',
                                                     layer=MemoryLayer.MID_TERM, title='Versioned note', summary='Unchanged content.',
                                                     source_kind='manual'))
    if kind == 'project_share':
        monkeypatch.setattr(memory, 'store', store)
        child = memory.share_user_memory_to_project(note.id, owner).item
    else:
        child = store.add_user_memory_item(UserMemoryItem(
            id='versioned_child', user_id=owner.id, workspace_id='ws', project_id='project', layer=MemoryLayer.LONG_TERM,
            title='Archive', summary=note.summary, source_kind='project_archive', provenance=MemoryProvenanceV1(
                source_kind='manual', created_by=owner.id, source_memory_ids=[note.id],
                source_memory_versions=[1], source_memory_hashes=[memory_content_hash(note)],
            ),
        ))
    store.save_user_memory_item(note.model_copy(update={'status': 'deprecated', 'version': 2}))
    result = MemoryForgettingService(store).forget(note.id, MemoryForgetRequestV1(command_id='forget-old-source', expected_version=2), owner)
    assert result.invalidated_count == 2
    if kind == 'project_share':
        assert store.get_memory_item(child.id).status == 'expired'
    else:
        assert store.get_user_memory_item(child.id).status == 'forgotten'
