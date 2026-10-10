from __future__ import annotations

import asyncio
import contextlib
import importlib
import threading
from dataclasses import dataclass

import pytest

from agentmesh.documents import DocumentIngestionRequest, ParsedDocument
from agentmesh.ingestion import BoundedIngestionExecutor, DocumentIngestionService, IngestionShutdownError
from agentmesh.models import Project, Scope, Source, User, now_utc
from agentmesh.store import SQLiteStore


@dataclass
class StaticParser:
    text: str

    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
        return ParsedDocument(
            title=request.file_name,
            text=self.text,
            source=Source(
                title=request.file_name,
                source_type="document",
                reference=f"document://{request.file_name}",
            ),
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            uploaded_by=request.uploaded_by,
            metadata={"parser": "test"},
        )


class FailingParser:
    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
        raise RuntimeError("unexpected parser failure")


def _request() -> DocumentIngestionRequest:
    return DocumentIngestionRequest(
        file_name="stability.md",
        content_type="text/markdown",
        content=b"ignored by test parser",
        workspace_id="ws_test",
        project_id="prj_test",
        uploaded_by="usr_test",
    )


def _repository(path) -> SQLiteStore:
    repository = SQLiteStore(path)
    value = _request()
    repository.save_user(User(id=value.uploaded_by, name='Owner', role='user', workspace_id=value.workspace_id,
                             default_project_id=value.project_id, personal_agent_id='agent_test'))
    repository.save_project(Project(id=value.project_id, workspace_id=value.workspace_id, name='Pilot', goal='Deliver',
                                    member_ids=[value.uploaded_by, 'peer']))
    return repository


def test_unexpected_parse_failure_makes_job_terminal(tmp_path) -> None:
    repository = _repository(tmp_path / "parse-failure.sqlite3")
    service = DocumentIngestionService(repository=repository, parser=FailingParser())
    request = _request()
    job = service.create_job(request)

    result = service.run_job(job.id, request)

    assert result.status == "failed"
    assert result.error == "document_ingestion_failed"
    assert repository.get_document_parse_job(job.id).status == "failed"


def test_unexpected_database_failure_makes_job_terminal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(tmp_path / "database-failure.sqlite3")
    service = DocumentIngestionService(repository=repository, parser=StaticParser("parse succeeds"))
    request = _request()
    job = service.create_job(request)

    original = repository._upsert_plain_record

    def fail_source_write(connection, collection, item):
        if collection == "sources":
            raise RuntimeError("unexpected database failure")
        return original(connection, collection, item)

    monkeypatch.setattr(repository, "_upsert_plain_record", fail_source_write)
    result = service.run_job(job.id, request)

    assert result.status == "failed"
    assert result.error == "document_ingestion_failed"
    assert repository.documents == repository.sources == repository.user_memory_items == []
    assert repository.get_document_parse_job(job.id).status == "failed"


def test_retry_atomically_replaces_a_rolled_back_import(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(tmp_path / "retry.sqlite3")
    text = "\n\n".join(f"section {index} " + ("x" * 450) for index in range(4))
    service = DocumentIngestionService(repository=repository, parser=StaticParser(text))
    request = _request()
    job = service.create_job(request)
    original_add = repository._sync_fts
    imported = 0

    def fail_after_first_chunk(connection, collection, item):
        nonlocal imported
        if collection == "user_memory_items" and item.source_kind == "document_import":
            imported += 1
            if imported == 2:
                raise RuntimeError("chunk write interrupted")
        return original_add(connection, collection, item)

    monkeypatch.setattr(repository, "_sync_fts", fail_after_first_chunk)
    failed = service.run_job(job.id, request)

    assert failed.status == "failed"
    assert failed.completed_chunks == 0
    assert repository.documents == repository.sources == repository.user_memory_items == []

    monkeypatch.setattr(repository, "_sync_fts", original_add)
    completed = service.run_job(job.id, request)
    document = repository.get_document(completed.document_id)
    chunks = service.current_version_chunks(document)

    assert completed.status == "completed"
    assert completed.completed_chunks == completed.expected_chunks
    assert len(chunks) == completed.expected_chunks
    assert len({chunk.id for chunk in chunks}) == len(chunks)


def test_completed_current_version_is_idempotent(tmp_path) -> None:
    repository = _repository(tmp_path / "idempotent.sqlite3")
    service = DocumentIngestionService(
        repository=repository,
        parser=StaticParser("first paragraph\n\nsecond paragraph"),
    )
    request = _request()
    job = service.create_job(request)

    first = service.run_job(job.id, request)
    document = repository.get_document(first.document_id)
    before_ids = {chunk.id for chunk in service.current_version_chunks(document)}
    second = service.run_job(job.id, request)
    after_ids = {chunk.id for chunk in service.current_version_chunks(document)}

    assert first.status == "completed"
    assert second.status == "completed"
    assert after_ids == before_ids
    assert len(after_ids) == second.expected_chunks



def test_completed_job_does_not_restore_a_later_document_edit(tmp_path) -> None:
    repository = _repository(tmp_path / "patch-after-job.sqlite3")
    service = DocumentIngestionService(repository=repository, parser=StaticParser("old parsed body"))
    request = _request()
    job = service.run_job(service.create_job(request).id)
    document = repository.get_document(job.document_id)
    updated = document.model_copy(update={'version': 2, 'text': 'newer patched body',
                                         'completed_chunks': 0, 'expected_chunks': 0, 'updated_at': now_utc()})
    assert repository.save_document_if_version(updated, 1)
    assert service.run_job(job.id).status == 'completed'
    persisted = repository.get_document(job.document_id)
    assert persisted.version == 2 and persisted.text == 'newer patched body'
    assert persisted.completed_chunks == persisted.expected_chunks == 0
    service.shutdown()


def test_failed_atomic_import_is_not_searchable_and_retry_imports_once(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path / "failed-search.sqlite3")
    text = "unique partial phrase " + ("x" * 900)
    service = DocumentIngestionService(repository=repository, parser=StaticParser(text))
    request = _request()
    job = service.create_job(request)
    original_add = repository._sync_fts
    writes = 0

    def fail_after_first_chunk(connection, collection, item):
        nonlocal writes
        if collection == "user_memory_items" and item.source_kind == "document_import":
            writes += 1
            if writes == 2:
                raise RuntimeError("chunk write interrupted")
        return original_add(connection, collection, item)

    monkeypatch.setattr(repository, "_sync_fts", fail_after_first_chunk)
    failed = service.run_job(job.id, request)
    partial_ids = {
        item.id for item in repository.user_memory_items if item.source_kind == "document_import"
    }
    failed_results = repository.search(
        "unique partial phrase",
        {Scope.PRIVATE},
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        user_id=request.uploaded_by,
    )

    assert failed.status == "failed"
    assert not partial_ids
    assert repository.documents == repository.sources == []
    assert partial_ids.isdisjoint(result.id for result in failed_results)
    assert all(repository.get_user_memory_item(item_id).status == "stale" for item_id in partial_ids)

    monkeypatch.setattr(repository, "_sync_fts", original_add)
    completed = service.run_job(job.id, request)
    completed_results = repository.search(
        "unique partial phrase",
        {Scope.PRIVATE},
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        user_id=request.uploaded_by,
    )

    assert completed.status == "completed"
    assert partial_ids <= {
        item.id for item in service.current_version_chunks(repository.get_document(completed.document_id))
    }
    chunk_ids = {item.id for item in service.current_version_chunks(repository.get_document(completed.document_id))}
    assert chunk_ids & {result.id for result in completed_results}


def test_shutdown_finishes_running_job_and_fails_canceled_queue_for_retry(tmp_path) -> None:
    parser_started = threading.Event()
    release_parser = threading.Event()

    class BlockingFirstParser(StaticParser):
        calls = 0

        def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
            self.calls += 1
            if self.calls == 1:
                parser_started.set()
                assert release_parser.wait(timeout=5)
            return super().parse(request)

    repository = _repository(tmp_path / "shutdown.sqlite3")
    service = DocumentIngestionService(
        repository=repository,
        parser=BlockingFirstParser("shutdown body"),
        executor=BoundedIngestionExecutor(max_workers=1, max_queue_size=1),
    )
    first_job = service.create_job(_request())
    second_job = service.create_job(_request())
    first_future = service.submit(first_job.id, _request())
    assert parser_started.wait(timeout=5)
    second_future = service.submit(second_job.id, _request())
    second_settled = threading.Event()
    second_future.add_done_callback(lambda _: second_settled.set())

    shutdown_thread = threading.Thread(target=service.shutdown)
    shutdown_thread.start()
    assert second_settled.wait(timeout=5)
    assert second_future.cancelled()
    release_parser.set()
    shutdown_thread.join(timeout=5)
    service.shutdown()

    assert first_future.result().status == "completed"
    canceled = repository.get_document_parse_job(second_job.id)
    assert canceled.status == "failed"
    assert canceled.error_type == IngestionShutdownError.__name__


def test_app_lifespan_always_shuts_down_ingestion_service(monkeypatch: pytest.MonkeyPatch) -> None:
    import agentmesh.app as application

    async def no_op() -> None:
        return None

    monkeypatch.setattr(application, "initialize_application_data", lambda repository: None)
    for name in (
        "start_auto_post_worker",
        "start_daily_memory_worker",
        "start_research_dispatch_worker",
        "start_market_publish_worker",
        "start_market_scout_worker",
        "stop_market_scout_worker",
        "stop_market_publish_worker",
        "stop_research_dispatch_worker",
        "stop_daily_memory_worker",
        "stop_auto_post_worker",
    ):
        monkeypatch.setattr(application, name, no_op)
    shutdown_called = threading.Event()
    monkeypatch.setattr(application.ingestion_service, "shutdown", shutdown_called.set)

    async def exercise_lifespan() -> None:
        with pytest.raises(RuntimeError, match="lifespan failure"):
            async with application.lifespan(application.app):
                raise RuntimeError("lifespan failure")

    asyncio.run(exercise_lifespan())

    assert shutdown_called.is_set()


@pytest.mark.parametrize(
    ("module_name", "interval_name", "step_name", "loop_name", "step_result"),
    [
        pytest.param(
            "agentmesh.marketplace",
            "MARKET_PUBLISH_INTERVAL_SECONDS",
            "publish_all_signals",
            "publish_worker_loop",
            0,
            id="market-publish",
        ),
        pytest.param(
            "agentmesh.marketplace",
            "MARKET_SCOUT_INTERVAL_SECONDS",
            "scout_all",
            "scout_worker_loop",
            0,
            id="market-scout",
        ),
        pytest.param(
            "agentmesh.routes.blackboard",
            "AUTO_POST_WORKER_INTERVAL_SECONDS",
            "drain_queued_auto_blackboard_posts",
            "auto_post_worker_loop",
            {"posted": 0},
            id="auto-post",
        ),
        pytest.param(
            "agentmesh.routes.blackboard",
            "RESEARCH_DISPATCH_WORKER_INTERVAL_SECONDS",
            "drain_dispatchable_research_requests",
            "research_dispatch_worker_loop",
            {"dispatched": 0},
            id="research-dispatch",
        ),
        pytest.param(
            "agentmesh.routes.memory",
            None,
            "generate_daily_memory_summaries",
            "daily_memory_worker_loop",
            {"created": 0, "skipped_existing": 0, "skipped_empty": 0},
            id="daily-memory",
        ),
    ],
)
def test_background_worker_keeps_event_loop_responsive_during_blocking_step(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    interval_name: str | None,
    step_name: str,
    loop_name: str,
    step_result: object,
) -> None:
    module = importlib.import_module(module_name)
    started = threading.Event()
    release = threading.Event()

    def blocking_step(*_args: object, **_kwargs: object) -> object:
        started.set()
        release.wait(timeout=1.0)
        return step_result

    if interval_name is None:
        monkeypatch.setattr(module, "next_daily_memory_run", now_utc)
    else:
        monkeypatch.setattr(module, interval_name, 0)
    monkeypatch.setattr(module, step_name, blocking_step)

    async def exercise() -> float:
        worker = asyncio.create_task(getattr(module, loop_name)())
        loop = asyncio.get_running_loop()
        begin = loop.time()
        try:
            while not started.is_set():
                await asyncio.sleep(0)
            return loop.time() - begin
        finally:
            release.set()
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker

    assert asyncio.run(exercise()) < 0.5
