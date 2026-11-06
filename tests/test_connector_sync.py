from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256

import httpx
import pytest

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.datasources import DataSourceResult
from agentmesh.memory_context.service import MemoryContextService
from agentmesh.models import AgentRun, ChatThread, SkillNodeResult, SkillResultSource, Source, UserMemoryItem
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.sources import SynthesisSourceError
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.gateway import ToolGateway
from agentmesh.tools import ensure_tool_seed_data

AT = datetime(2026, 10, 7, tzinfo=UTC)


@pytest.fixture
def project(tmp_path):
    repository = SQLiteStore(tmp_path / 'connector-sync.sqlite3')
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by='system')
    yield repository
    repository.close()


def _root(repository):
    return repository.observe_source(Source(id='src_connector_original', title='Original issue evidence',
        source_type='github_issue', reference='https://github.com/example/pilot/issues/1', user_id=USER.id,
        workspace_id=USER.workspace_id, project_id=USER.default_project_id, created_at=AT,
        snapshot={'provider': 'github_issues', 'external_id': 'example/pilot:issue:1', 'version': 'issue-v1',
                  'body_sha256': sha256(b'Original issue evidence').hexdigest(), 'revision': 1, 'observed_at': AT}),
        body='Original issue evidence', user=USER, expected_revision=0)


@pytest.mark.parametrize('change', ['version', 'withdrawal'])
def test_data_query_reuses_canonical_source_and_invalidates_its_run_citation(project, monkeypatch, change):
    root = _root(project)
    thread = project.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, title='External evidence'))
    run = project.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, status='running', input_text='Original issue evidence'))
    context = AgentMeshRunContext(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, run_id=run.id)
    gateway = ToolGateway(project)

    def result(**kwargs):
        return DataSourceResult(connector_name='github_issues', title='Original issue evidence',
            records=[{'number': 1, 'state': 'open'}], source=root,
            metadata={'requested_provider': 'auto', 'actual_provider': 'github_issues', 'mode': 'real'})

    monkeypatch.setattr(gateway.data_registry, 'query_first_available', result)
    output = gateway.data_query(context, {'query': 'Original issue evidence'})
    citation = Source.model_validate(output['source'])
    assert citation.id != root.id and citation.run_id == run.id
    assert citation.reference == root.reference
    assert project.get_source(root.id) == root
    assert citation.origin.source_id == root.id and citation.origin.revision == root.snapshot.revision
    project.add_user_memory_item(UserMemoryItem(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, title='Original issue evidence', summary='Original issue evidence',
        layer='long_term', source_kind='manual', sources=[citation]))
    service = MemoryContextService(project)
    assert len(service.retrieve('Original issue evidence', user=USER, agent_id=USER.personal_agent_id,
                               project_id=USER.default_project_id).hits) == 1
    update = {'lifecycle': 'unavailable'} if change == 'withdrawal' else {
        'version': 'issue-v2', 'body_sha256': sha256(b'Changed issue evidence').hexdigest()}
    replacement = root.model_copy(update={'snapshot': root.snapshot.model_copy(update=update)})
    project.observe_source(replacement, body=None if change == 'withdrawal' else 'Changed issue evidence',
                           user=USER, expected_revision=1)
    assert not service.retrieve('Original issue evidence', user=USER, agent_id=USER.personal_agent_id,
                                project_id=USER.default_project_id).hits


def test_canonical_source_withdrawal_invalidates_prepared_synthesis(project, monkeypatch):
    root = _root(project)
    thread = project.add_chat_thread(ChatThread(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, title='External evidence'))
    run = project.save_agent_run(AgentRun(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, status='running', input_text='Original issue evidence'))
    context = AgentMeshRunContext(user_id=USER.id, workspace_id=USER.workspace_id,
        project_id=USER.default_project_id, thread_id=thread.id, run_id=run.id)
    gateway = ToolGateway(project)
    monkeypatch.setattr(gateway.data_registry, 'query_first_available', lambda **kwargs: DataSourceResult(
        connector_name='github_issues', title=root.title, records=[{'number': 1}], source=root))
    citation = Source.model_validate(gateway.data_query(context, {'query': 'Original issue evidence'})['source'])
    result = SkillNodeResult(node_id='node_evidence', skill_id='skill_evidence', summary='Original issue evidence',
        sources=[SkillResultSource(**citation.model_dump())])
    assert project.synthesis_source_snapshot(run, [result])
    withdrawn = root.model_copy(update={'snapshot': root.snapshot.model_copy(update={'lifecycle': 'unavailable'})})
    project.observe_source(withdrawn, body=None, user=USER, expected_revision=1)
    with pytest.raises(SynthesisSourceError, match='synthesis_sources_changed'):
        project.synthesis_source_snapshot(run, [result])


def test_native_docs_sync_commits_versioned_mirrors_and_resumes_from_cursor(project, tmp_path):
    from agentmesh.connector_sync.readers import RepoDocsReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    root = tmp_path / 'docs'
    root.mkdir()
    (root / 'a.md').write_text('Original issue evidence')
    (root / 'b.md').write_text('Second issue evidence')
    reader = RepoDocsReader(root, namespace='pilot_docs', page_size=1)
    service = ConnectorSyncService(project, reader)
    first = service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
    assert first.next_position == 'a.md' and first.version == 1
    assert len(project.documents) == 1
    doc = project.documents[0]
    assert doc.text == 'Original issue evidence' and doc.source.snapshot.provider == 'repo_docs'
    assert doc.source.snapshot.body_sha256 == sha256(b'Original issue evidence').hexdigest()
    second = service.sync_page(USER, project_id=USER.default_project_id, expected_version=1)
    assert second.next_position is None and second.version == 2
    assert len(project.documents) == 2
    (root / 'a.md').write_text('Updated issue evidence')
    third = service.sync_page(USER, project_id=USER.default_project_id, expected_version=2)
    assert third.next_position == 'a.md'
    updated = project.get_document(doc.id)
    assert updated.version == 2 and updated.source.snapshot.revision == 2
    assert updated.text == 'Updated issue evidence'


def test_sync_audit_failure_rolls_back_source_document_indexes_and_cursor(project, tmp_path):
    from agentmesh.connector_sync.readers import RepoDocsReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    root = tmp_path / 'docs'
    root.mkdir()
    (root / 'a.md').write_text('Original evidence')
    service = ConnectorSyncService(project, RepoDocsReader(root, namespace='pilot_docs'))
    with project._connect() as connection:
        connection.execute("""CREATE TRIGGER refuse_connector_audit BEFORE INSERT ON records
            WHEN NEW.collection = 'audit_events' AND json_extract(NEW.payload, '$.action') = 'observe_source'
            BEGIN SELECT RAISE(ABORT, 'controlled_connector_audit_failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='controlled_connector_audit_failure'):
        service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
    failed = service.cursor(USER, project_id=USER.default_project_id)
    assert failed.status == 'failed' and failed.read_claim_id is None
    assert not project.documents
    assert not project.sources
    with project._connect() as connection:
        connection.execute('DROP TRIGGER refuse_connector_audit')
    assert service.sync_page(USER, project_id=USER.default_project_id, expected_version=failed.version).version == 2


def test_sync_rechecks_actor_after_reader_returns(project, tmp_path):
    from agentmesh.connector_sync.contracts import ConnectorSyncError
    from agentmesh.connector_sync.readers import RepoDocsReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    root = tmp_path / 'docs'
    root.mkdir()
    (root / 'a.md').write_text('Original evidence')

    class Reader(RepoDocsReader):
        def read_page(self, position, *, since=None):
            page = super().read_page(position, since=since)
            project.save_user(USER.model_copy(update={'status': 'disabled'}))
            return page

    service = ConnectorSyncService(project, Reader(root, namespace='pilot_docs'))
    with pytest.raises(ConnectorSyncError, match='connector_not_found'):
        service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
    assert not project.documents


def test_symlink_outside_doc_root_never_becomes_a_mirror(project, tmp_path):
    from agentmesh.connector_sync.contracts import ConnectorSyncError
    from agentmesh.connector_sync.readers import RepoDocsReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    root = tmp_path / 'docs'
    root.mkdir()
    private = tmp_path / 'private.txt'
    private.write_text('Private material outside authorized root')
    (root / 'a.md').symlink_to(private)
    service = ConnectorSyncService(project, RepoDocsReader(root, namespace='pilot_docs'))
    with pytest.raises(ConnectorSyncError, match='connector_document_unavailable'):
        service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
    assert not project.documents


def test_sync_preserves_user_withdrawal_when_external_body_changes(project, tmp_path):
    from agentmesh.connector_sync.readers import RepoDocsReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    root = tmp_path / 'docs'
    root.mkdir()
    path = root / 'a.md'
    path.write_text('Original evidence')
    service = ConnectorSyncService(project, RepoDocsReader(root, namespace='pilot_docs'))
    service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
    document = project.documents[0]
    project.save_document(document.model_copy(update={'withdrawn_at': AT, 'withdrawn_by': USER.id}))
    path.write_text('Changed external evidence')
    service.sync_page(USER, project_id=USER.default_project_id, expected_version=1)
    current = project.get_document(document.id)
    assert current.withdrawn_at == AT and current.withdrawn_by == USER.id
    assert current.text == 'Original evidence'


def test_native_reader_rejects_fifo_without_waiting_for_a_writer(tmp_path):
    root = tmp_path / 'docs'
    root.mkdir()
    os.mkfifo(root / 'a.md')
    script = '''
import sys
from pathlib import Path
from agentmesh.connector_sync.readers import RepoDocsReader
from agentmesh.connector_sync.contracts import ConnectorSyncError
try:
    RepoDocsReader(Path(sys.argv[1]), namespace='pilot_docs').read_page(None)
except ConnectorSyncError as error:
    assert error.code == 'connector_document_unavailable'
else:
    raise SystemExit('FIFO accepted')
'''
    try:
        result = subprocess.run([sys.executable, '-c', script, str(root)], capture_output=True, timeout=3)
    except subprocess.TimeoutExpired:
        pytest.fail('document reader blocked on a FIFO')
    assert result.returncode == 0, result.stderr.decode()


def test_native_inventory_limit_includes_files_with_unrecognized_extensions(tmp_path):
    from agentmesh.connector_sync.contracts import ConnectorSyncError
    from agentmesh.connector_sync.readers import RepoDocsReader

    for number in range(1001):
        (tmp_path / f'{number}.bin').touch()
    with pytest.raises(ConnectorSyncError, match='connector_inventory_limit'):
        RepoDocsReader(tmp_path, namespace='pilot_docs').read_page(None)


def test_cursor_with_foreign_owner_is_not_returned_or_resumed(project, tmp_path):
    from agentmesh.connector_sync.contracts import ConnectorSyncError
    from agentmesh.connector_sync.readers import RepoDocsReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    service = ConnectorSyncService(project, RepoDocsReader(tmp_path, namespace='pilot_docs'))
    cursor = service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
    with project._connect() as connection:
        connection.execute("UPDATE records SET payload = json_set(payload, '$.owner_user_id', 'foreign_owner') "
                           "WHERE collection = 'connector_sync_cursors' AND id = ?", (cursor.id,))
    with pytest.raises(ConnectorSyncError, match='connector_cursor_conflict'):
        service.cursor(USER, project_id=USER.default_project_id)
    with pytest.raises(ConnectorSyncError, match='connector_cursor_conflict'):
        service.sync_page(USER, project_id=USER.default_project_id, expected_version=1)


def test_github_sync_advances_watermark_only_after_all_pages_and_reuses_it(project, monkeypatch):
    from agentmesh.connector_sync import service as module
    from agentmesh.connector_sync.readers import GitHubIssuesReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    clock = [AT]
    monkeypatch.setattr(module, 'now_utc', lambda: clock[0])
    requests = []

    def respond(request):
        requests.append(request)
        if 'since' not in request.url.params and request.url.params['page'] == '1':
            return httpx.Response(200, json=[], headers={'Link':
                '<https://api.github.com/repos/example/pilot/issues?page=2>; rel="next"'})
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = ConnectorSyncService(project, GitHubIssuesReader('example/pilot', client=client))
        first = service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
        assert first.watermark_at is None
        clock[0] = datetime(2026, 10, 7, 0, 5, tzinfo=UTC)
        second = service.sync_page(USER, project_id=USER.default_project_id, expected_version=1)
        assert second.watermark_at == AT
        clock[0] = datetime(2026, 10, 7, 0, 10, tzinfo=UTC)
        service.sync_page(USER, project_id=USER.default_project_id, expected_version=2)
        assert requests[-1].url.params['since'] == '2026-10-06T23:59:00Z'


@pytest.mark.parametrize('status, available', [(500, True), (403, False)])
def test_github_failure_persists_safe_status_and_only_access_failure_withholds_memory(project, status, available):
    from agentmesh.connector_sync.contracts import ConnectorSyncError
    from agentmesh.connector_sync.readers import GitHubIssuesReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    response_status = [200]
    issue = {'number': 1, 'title': 'Original issue evidence', 'body': 'Original issue evidence', 'state': 'open',
             'updated_at': '2026-10-07T00:00:00Z', 'html_url': 'https://github.com/example/pilot/issues/1'}

    def respond(request):
        return httpx.Response(response_status[0], json=[issue] if response_status[0] == 200 else
                              {'message': 'synthetic-private-upstream-diagnostic'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = ConnectorSyncService(project, GitHubIssuesReader('example/pilot', client=client))
        original = service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
        source = project.documents[0].source
        project.add_user_memory_item(UserMemoryItem(user_id=USER.id, workspace_id=USER.workspace_id,
            project_id=USER.default_project_id, title='Original issue evidence', summary='Original issue evidence',
            layer='long_term', source_kind='manual', sources=[source]))
        response_status[0] = status
        with pytest.raises(ConnectorSyncError):
            service.sync_page(USER, project_id=USER.default_project_id, expected_version=1)
        failed = service.cursor(USER, project_id=USER.default_project_id)
        assert failed.version == 2 and failed.status == 'failed' and failed.consecutive_failures == 1
        assert failed.last_successful_at == original.last_successful_at and failed.watermark_at == original.watermark_at
        assert 'synthetic-private' not in failed.model_dump_json()
        hits = MemoryContextService(project).retrieve('Original issue evidence', user=USER,
            agent_id=USER.personal_agent_id, project_id=USER.default_project_id).hits
        assert bool(hits) == available
        response_status[0] = 200
        recovered = service.sync_page(USER, project_id=USER.default_project_id, expected_version=2)
        assert recovered.status == 'idle' and recovered.last_error_code is None and recovered.consecutive_failures == 0


def test_full_doc_rescan_withholds_missing_sources_only_after_its_last_page(project, tmp_path):
    from agentmesh.connector_sync.readers import RepoDocsReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    for name in ('a.md', 'b.md', 'c.md'):
        (tmp_path / name).write_text('Original issue evidence ' + name)
    service = ConnectorSyncService(project, RepoDocsReader(tmp_path, namespace='pilot_docs', page_size=1))
    for version in range(3):
        service.sync_page(USER, project_id=USER.default_project_id, expected_version=version)
    missing = next(doc for doc in project.documents if doc.title == 'c.md')
    (tmp_path / 'c.md').unlink()
    first = service.sync_page(USER, project_id=USER.default_project_id, expected_version=3)
    assert first.next_position is not None
    assert project.get_source(missing.source.id).snapshot.lifecycle == 'active'
    last = service.sync_page(USER, project_id=USER.default_project_id, expected_version=4)
    assert last.next_position is None
    assert project.get_source(missing.source.id).snapshot.lifecycle == 'unavailable'


def test_access_failure_restarts_full_scan_and_restores_sources_from_earlier_pages(project):
    from agentmesh.connector_sync.contracts import ConnectorSyncError
    from agentmesh.connector_sync.readers import GitHubIssuesReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    inaccessible = [False]
    pages = []

    def respond(request):
        page = request.url.params['page']
        pages.append(page)
        if inaccessible[0]:
            return httpx.Response(403, json={'message': 'unavailable'})
        issue = {'number': int(page), 'title': 'Evidence ' + page, 'body': 'Issue evidence', 'state': 'open',
                 'updated_at': '2026-10-07T00:00:00Z',
                 'html_url': 'https://github.com/example/pilot/issues/' + page}
        headers = {'Link': '<https://api.github.com/repos/example/pilot/issues?page=2>; rel="next"'} if page == '1' else {}
        return httpx.Response(200, json=[issue], headers=headers)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = ConnectorSyncService(project, GitHubIssuesReader('example/pilot', client=client))
        service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
        source_id = project.documents[0].source.id
        inaccessible[0] = True
        with pytest.raises(ConnectorSyncError):
            service.sync_page(USER, project_id=USER.default_project_id, expected_version=1)
        assert project.get_source(source_id).snapshot.lifecycle == 'unavailable'
        inaccessible[0] = False
        restarted = service.sync_page(USER, project_id=USER.default_project_id, expected_version=2)
        assert pages == ['1', '2', '1']
        assert restarted.scan_mode == 'full' and restarted.next_position is not None
        assert project.get_source(source_id).snapshot.lifecycle == 'active'


def test_expired_claim_survives_reopening_and_startup_recovers_it(tmp_path, monkeypatch):
    from datetime import timedelta

    from agentmesh.connector_sync import service as module
    from agentmesh.connector_sync.readers import RepoDocsReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    class ProcessLost(BaseException):
        pass

    class InterruptedReader(RepoDocsReader):
        def read_page(self, position, *, since=None):
            raise ProcessLost

    clock = [AT]
    monkeypatch.setattr(module, 'now_utc', lambda: clock[0])
    root = tmp_path / 'docs'
    root.mkdir()
    (root / 'a.md').write_text('Recovered evidence')
    monkeypatch.setenv('AGENTMESH_CONNECTOR_PROJECT_ID', USER.default_project_id)
    monkeypatch.setenv('AGENTMESH_REPO_DOCS_ROOT', str(root))
    monkeypatch.delenv('AGENTMESH_GITHUB_REPOSITORY', raising=False)
    path = tmp_path / 'recovered-claim.sqlite3'
    repository = SQLiteStore(path)
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    reader = InterruptedReader(root, namespace='project_docs')
    service = ConnectorSyncService(repository, reader, current_configuration_hash=reader.configuration_hash)
    try:
        with pytest.raises(ProcessLost):
            service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
        assert service.cursor(USER, project_id=USER.default_project_id).status == 'reading'
    finally:
        repository.close()
    reopened = SQLiteStore(path)
    try:
        clock[0] += timedelta(seconds=91)
        assert ConnectorSyncService.reconcile_startup_bindings(reopened) == 1
        reader = RepoDocsReader(root, namespace='project_docs')
        service = ConnectorSyncService(reopened, reader, current_configuration_hash=reader.configuration_hash)
        failed = service.cursor(USER, project_id=USER.default_project_id)
        assert failed.status == 'failed' and failed.read_claim_id is None
        assert failed.last_error_code == 'connector_read_expired'
        result = service.sync_page(USER, project_id=USER.default_project_id, expected_version=failed.version)
        assert result.status == 'idle' and reopened.documents[0].text == 'Recovered evidence'
    finally:
        reopened.close()


def test_expired_old_reader_cannot_replace_a_recovered_successful_page(project, tmp_path, monkeypatch):
    from datetime import timedelta

    from agentmesh.connector_sync import service as module
    from agentmesh.connector_sync.contracts import ConnectorSyncError
    from agentmesh.connector_sync.readers import RepoDocsReader
    from agentmesh.connector_sync.service import ConnectorSyncService

    clock = [AT]
    monkeypatch.setattr(module, 'now_utc', lambda: clock[0])
    (tmp_path / 'a.md').write_text('Original evidence')

    class LateReader(RepoDocsReader):
        def read_page(self, position, *, since=None):
            old_page = super().read_page(position, since=since)
            clock[0] += timedelta(seconds=91)
            assert ConnectorSyncService.reconcile_bindings(project, USER, project_id=USER.default_project_id) == 1
            (tmp_path / 'a.md').write_text('Replacement evidence')
            replacement = ConnectorSyncService(project, RepoDocsReader(tmp_path, namespace='pilot_docs'))
            cursor = replacement.cursor(USER, project_id=USER.default_project_id)
            assert replacement.sync_page(USER, project_id=USER.default_project_id,
                                         expected_version=cursor.version).status == 'idle'
            return old_page

    service = ConnectorSyncService(project, LateReader(tmp_path, namespace='pilot_docs'))
    with pytest.raises(ConnectorSyncError, match='connector_cursor_conflict'):
        service.sync_page(USER, project_id=USER.default_project_id, expected_version=0)
    assert project.documents[0].text == 'Replacement evidence'
    assert service.cursor(USER, project_id=USER.default_project_id).status == 'idle'
