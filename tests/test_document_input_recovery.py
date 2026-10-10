from __future__ import annotations

from agentmesh.documents import PlainTextDocumentParser
from agentmesh.ingestion import DocumentIngestionService
from agentmesh.models import Project, User
from agentmesh.store import SQLiteStore
from tests.test_document_staging import request


def seed_owner(repository):
    value = request()
    user = repository.save_user(User(id=value.uploaded_by, name='Owner', role='user',
        workspace_id=value.workspace_id, default_project_id=value.project_id, personal_agent_id='agent'))
    repository.save_project(Project(id=value.project_id, name='Pilot', goal='Deliver',
        workspace_id=value.workspace_id, member_ids=[user.id, 'peer']))
    return user


def test_persisted_upload_can_parse_after_reopen_without_original_future(tmp_path):
    repository = SQLiteStore(tmp_path / 'ingestion.sqlite3')
    seed_owner(repository)
    first = DocumentIngestionService(repository, PlainTextDocumentParser())
    job = first.create_job(request())
    first.shutdown()
    reopened = SQLiteStore(repository.db_path)
    resumed = DocumentIngestionService(reopened, PlainTextDocumentParser())
    try:
        completed = resumed.run_job(job.id)
        assert completed.status == 'completed'
        document = reopened.get_document(completed.document_id)
        assert '冻结的原始资料' in document.text
        assert document.uploaded_by == request().uploaded_by
        assert not (resumed.staging.root / job.input_staging_ref).exists()
        assert resumed.run_job(job.id).status == 'completed'
    finally:
        resumed.shutdown()


def test_corrupted_staged_input_never_reaches_parser_or_source_commit(tmp_path):
    class ForbiddenParser:
        calls = 0

        def parse(self, request):
            self.calls += 1
            raise AssertionError('parser must not run')

    repository = SQLiteStore(tmp_path / 'corrupt.sqlite3')
    seed_owner(repository)
    parser = ForbiddenParser()
    service = DocumentIngestionService(repository, parser)
    try:
        job = service.create_job(request())
        (service.staging.root / job.input_staging_ref).write_bytes(b'changed bytes')
        result = service.run_job(job.id)
        assert result.status == 'failed' and result.error == 'document_input_integrity_failed'
        assert parser.calls == 0 and repository.documents == [] and repository.sources == []
    finally:
        service.shutdown()


def test_input_cleanup_failure_does_not_turn_a_committed_import_into_a_failure(tmp_path, monkeypatch):
    from agentmesh.document_staging import DocumentStagingError

    repository = SQLiteStore(tmp_path / 'cleanup.sqlite3')
    seed_owner(repository)
    service = DocumentIngestionService(repository, PlainTextDocumentParser())
    original_delete = service.staging.delete
    try:
        job = service.create_job(request())

        def unavailable(_job):
            raise DocumentStagingError('document_input_delete_failed')

        monkeypatch.setattr(service.staging, 'delete', unavailable)
        completed = service.run_job(job.id)
        assert completed.status == 'completed'
        assert completed.input_cleanup_pending
        assert all(item.status == 'active' for item in repository.user_memory_items)
        monkeypatch.setattr(service.staging, 'delete', original_delete)
        cleaned = service.run_job(job.id)
        assert cleaned.status == 'completed' and not cleaned.input_cleanup_pending
        assert not (service.staging.root / job.input_staging_ref).exists()
    finally:
        service.shutdown()


def test_recovery_rechecks_owner_and_project_before_parsing(tmp_path):
    class ForbiddenParser:
        def parse(self, _request):
            raise AssertionError('revoked owner must not parse')

    repository = SQLiteStore(tmp_path / 'revoked.sqlite3')
    owner = seed_owner(repository)
    service = DocumentIngestionService(repository, ForbiddenParser())
    try:
        job = service.create_job(request())
        repository.save_user(owner.model_copy(update={'status': 'inactive'}))
        result = service.run_job(job.id)
        assert result.status == 'failed' and result.error == 'document_authority_unavailable'
        assert repository.documents == [] and repository.sources == []
    finally:
        service.shutdown()


def test_two_reopened_services_share_one_live_parser_claim(tmp_path):
    import threading

    started, release = threading.Event(), threading.Event()

    class BlockingParser(PlainTextDocumentParser):
        calls = 0

        def parse(self, value):
            self.calls += 1
            started.set()
            assert release.wait(5)
            return super().parse(value)

    repository = SQLiteStore(tmp_path / 'concurrent.sqlite3')
    seed_owner(repository)
    parser = BlockingParser()
    first = DocumentIngestionService(repository, parser)
    second = DocumentIngestionService(SQLiteStore(repository.db_path), parser)
    try:
        job = first.create_job(request())
        future = first.submit(job.id)
        assert started.wait(5)
        duplicate = second.run_job(job.id)
        assert duplicate.status == 'running' and parser.calls == 1
        release.set()
        assert future.result(5).status == 'completed'
        assert len(repository.documents) == len(repository.sources) == 1
    finally:
        release.set()
        first.shutdown()
        second.shutdown()


def test_permission_revoked_during_parse_prevents_every_output_commit(tmp_path):
    repository = SQLiteStore(tmp_path / 'revoked-during-parse.sqlite3')
    owner = seed_owner(repository)

    class RevokingParser(PlainTextDocumentParser):
        def parse(self, value):
            parsed = super().parse(value)
            repository.save_project(repository.get_project(owner.default_project_id).model_copy(update={'member_ids': ['peer']}))
            return parsed

    service = DocumentIngestionService(repository, RevokingParser())
    try:
        result = service.run_job(service.create_job(request()).id)
        assert result.status == 'failed' and result.error == 'document_authority_unavailable'
        assert repository.sources == repository.documents == repository.user_memory_items == []
    finally:
        service.shutdown()


def test_expired_parser_cannot_commit_or_overwrite_the_replacement_worker(tmp_path):
    from datetime import timedelta

    from agentmesh.models import now_utc

    repository = SQLiteStore(tmp_path / 'late.sqlite3')
    seed_owner(repository)
    old = DocumentIngestionService(repository, PlainTextDocumentParser())
    replacement = DocumentIngestionService(SQLiteStore(repository.db_path), PlainTextDocumentParser())

    class ReplacedParser(PlainTextDocumentParser):
        def parse(self, value):
            current = repository.get_document_parse_job(job.id)
            repository.save_document_parse_job(current.model_copy(update={'lease_expires_at': now_utc() - timedelta(seconds=1)}))
            assert replacement.run_job(job.id).status == 'completed'
            return super().parse(value)

    old.parser = ReplacedParser()
    try:
        job = old.create_job(request())
        result = old.run_job(job.id)
        assert result.status == 'completed' and result.attempt_count == 2
        assert len(repository.documents) == len(repository.sources) == 1
        assert all(item.status == 'active' for item in repository.user_memory_items)
    finally:
        old.shutdown()
        replacement.shutdown()


def test_restart_recovery_discovers_only_durable_queued_inputs(tmp_path):
    repository = SQLiteStore(tmp_path / 'startup.sqlite3')
    seed_owner(repository)
    first = DocumentIngestionService(repository, PlainTextDocumentParser())
    job = first.create_job(request())
    first.shutdown()
    recovered = DocumentIngestionService(SQLiteStore(repository.db_path), PlainTextDocumentParser())
    try:
        assert recovered.recover_once(limit=2) == 1
        recovered.shutdown()
        assert repository.get_document_parse_job(job.id).status == 'completed'
        assert len(repository.documents) == len(repository.sources) == 1
    finally:
        recovered.shutdown()


def test_expired_input_is_removed_without_calling_the_parser(tmp_path):
    from datetime import timedelta

    from agentmesh.models import now_utc

    repository = SQLiteStore(tmp_path / 'expiry.sqlite3')
    seed_owner(repository)

    class ForbiddenParser:
        def parse(self, _value):
            raise AssertionError('expired input must not parse')

    service = DocumentIngestionService(repository, ForbiddenParser())
    try:
        job = service.create_job(request())
        repository.save_document_parse_job(job.model_copy(update={'input_retained_until': now_utc() - timedelta(seconds=1)}))
        service.recover_once()
        service.shutdown()
        expired = repository.get_document_parse_job(job.id)
        assert expired.status == 'failed' and expired.error == 'document_input_expired'
        assert expired.input_purged and not (service.staging.root / job.input_staging_ref).exists()
        assert repository.documents == repository.sources == []
    finally:
        service.shutdown()


def test_a_renewed_claim_remains_exclusive_after_the_original_deadline(tmp_path):
    from datetime import timedelta

    from agentmesh.models import now_utc

    repository = SQLiteStore(tmp_path / 'heartbeat.sqlite3')
    seed_owner(repository)
    service = DocumentIngestionService(repository, PlainTextDocumentParser())
    current_time = [now_utc()]
    service.jobs.clock = lambda: current_time[0]
    try:
        job = service.create_job(request())
        claimed, acquired = service.jobs.claim(job.id)
        assert acquired
        current_time[0] += timedelta(seconds=90)
        service.jobs.renew(claimed)
        current_time[0] += timedelta(seconds=60)
        _, acquired_again = service.jobs.claim(job.id)
        assert not acquired_again
        current_time[0] += timedelta(seconds=61)
        replacement, acquired_after_expiry = service.jobs.claim(job.id)
        assert acquired_after_expiry and replacement.claim_id != claimed.claim_id
    finally:
        service.shutdown()
