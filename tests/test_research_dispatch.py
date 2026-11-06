from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import httpx
import pytest

from agentmesh.acquisition import AcquisitionResult
from agentmesh.agents import PersonalAgent
from agentmesh.models import BlackboardPost, ChatThread, Source, Task
from agentmesh.seed import PROJECT, USER, ensure_seed_data
from agentmesh.store import SQLiteStore


def _request(repository, suffix):
    thread = repository.save_chat_thread(
        ChatThread(id=f"thread_{suffix}", title=suffix, user_id=USER.id,
                   workspace_id=USER.workspace_id, project_id=PROJECT.id),
    )
    task = repository.save_task(
        Task(id=f"task_{suffix}", thread_id=thread.id, intent="ask_memory", status="waiting_external_agent", title=suffix),
    )
    return repository.add_blackboard_post(
        BlackboardPost(
            id=f"request_{suffix}", task_id=task.id, post_type="request", actor="personal_agent",
            title=suffix, content=suffix, scope="project", permission="project_visible",
        ),
    )


def _evidence():
    return AcquisitionResult(
        actor="research_connector", title="Verified document", content="The documented conclusion.",
        sources=[Source(title="Document", source_type="web_page", reference="https://example.invalid/document")],
        metadata={"actual_provider": "fixture", "data_mode": "real"},
    )


def test_transient_request_failure_survives_restart_and_does_not_hide_other_results(tmp_path):
    from agentmesh.research_dispatch import ResearchDispatchService

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    failed = _request(repository, "temporarily_unavailable")
    healthy = _request(repository, "available")
    clock = [datetime(2026, 10, 4, tzinfo=UTC)]

    class Provider:
        calls = []

        def acquire(self, request):
            self.calls.append(request.request_post_id)
            if request.request_post_id == failed.id and self.calls.count(failed.id) == 1:
                raise TimeoutError("secret provider URL and token must not be persisted")
            return _evidence()

    provider = Provider()
    service = ResearchDispatchService(
        repository, PersonalAgent(repository, acquisition_agent=provider), process_epoch="first", clock=lambda: clock[0],
    )
    first = service.drain("worker")
    assert first.dispatched == 1
    assert first.retrying == 1
    assert first.last_error_code == "research_read_timeout"
    state = repository.get_blackboard_post(failed.id).research_dispatch
    assert state.status == "retry_wait"
    assert state.attempts == 1
    assert state.next_retry_at == clock[0] + timedelta(seconds=5)
    assert "secret" not in state.model_dump_json()
    assert repository.get_task(healthy.task_id).status == "completed"

    reopened = SQLiteStore(repository.db_path)
    recovered = ResearchDispatchService(
        reopened, PersonalAgent(reopened, acquisition_agent=provider), process_epoch="second", clock=lambda: clock[0],
    )
    assert recovered.drain("worker").dispatched == 0
    clock[0] += timedelta(seconds=5)
    assert recovered.drain("worker").dispatched == 1
    state = reopened.get_blackboard_post(failed.id).research_dispatch
    assert state.status == "completed"
    assert state.attempts == 2
    assert state.next_retry_at is None
    assert recovered.drain("worker").dispatched == 0
    assert provider.calls == [failed.id, healthy.id, failed.id]


def test_revoked_project_membership_during_read_does_not_publish_evidence_or_answer(tmp_path):
    from agentmesh.research_dispatch import ResearchDispatchService

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    request = _request(repository, "permission_revoked")

    class Provider:
        def acquire(self, _request):
            project = repository.get_project(PROJECT.id)
            repository.save_project(project.model_copy(update={"member_ids": ["another_user"]}))
            return _evidence()

    result = ResearchDispatchService(
        repository, PersonalAgent(repository, acquisition_agent=Provider()), process_epoch="current",
    ).drain("worker")
    assert result.blocked == 1
    assert result.dispatched == 0
    assert result.last_error_code == "research_owner_not_authorized"
    assert repository.get_blackboard_post(request.id).research_dispatch.status == "blocked"
    assert not [post for post in repository.blackboard_posts if post.related_post_id == request.id]
    assert not repository.list_thread_messages(repository.get_task(request.task_id).thread_id)


def test_terminal_failure_remains_visible_in_queue_health_after_restart(tmp_path):
    from agentmesh.research_dispatch import ResearchDispatchService

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    request = _request(repository, "failed")

    class Provider:
        def acquire(self, _request):
            raise RuntimeError("sensitive provider details")

    service = ResearchDispatchService(repository, PersonalAgent(repository, acquisition_agent=Provider()), process_epoch="a")
    assert service.drain("worker").failed == 1
    reopened = SQLiteStore(repository.db_path)
    restarted = ResearchDispatchService(reopened, PersonalAgent(reopened, acquisition_agent=Provider()), process_epoch="b")
    assert restarted.drain("worker").failed == 0
    health = restarted.queue_health(workspace_id=USER.workspace_id)
    assert health["counts"]["failed"] == 1
    assert health["last_error_code"] == "research_dispatch_failed"
    assert reopened.get_task(request.task_id).status == "failed"
    assert "sensitive provider details" not in str(health)


def test_read_retry_budget_is_three_attempts_with_five_and_thirty_second_backoff(tmp_path):
    from agentmesh.o2 import O2CommandError
    from agentmesh.research_dispatch import ResearchDispatchService

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    request = _request(repository, "timeout")
    clock = [datetime(2026, 10, 4, tzinfo=UTC)]

    class Provider:
        calls = 0

        def acquire(self, _request):
            self.calls += 1
            raise O2CommandError("timeout", "private URL")

    provider = Provider()
    service = ResearchDispatchService(
        repository, PersonalAgent(repository, acquisition_agent=provider), process_epoch="a", clock=lambda: clock[0],
    )
    assert service.drain("worker").retrying == 1
    clock[0] += timedelta(seconds=5)
    assert service.drain("worker").retrying == 1
    assert repository.get_blackboard_post(request.id).research_dispatch.next_retry_at == clock[0] + timedelta(seconds=30)
    clock[0] += timedelta(seconds=29)
    assert service.drain("worker").dispatched == 0
    assert provider.calls == 2
    clock[0] += timedelta(seconds=1)
    assert service.drain("worker").failed == 1
    assert repository.get_blackboard_post(request.id).research_dispatch.attempts == 3
    assert repository.get_task(request.task_id).status == "failed"
    assert service.drain("worker").retrying == 0
    assert provider.calls == 3


def test_manual_and_background_delivery_share_one_claim(tmp_path):
    from agentmesh.research_dispatch import ResearchDispatchService, ResearchRequestBlockedError

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    request = _request(repository, "concurrent")
    started, release = Event(), Event()

    class Provider:
        calls = 0

        def acquire(self, _request):
            self.calls += 1
            started.set()
            assert release.wait(5)
            return _evidence()

    provider = Provider()
    service = ResearchDispatchService(repository, PersonalAgent(repository, acquisition_agent=provider), process_epoch="a")
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(service.drain, "worker")
        assert started.wait(5)
        try:
            with pytest.raises(ResearchRequestBlockedError, match="research_request_already_claimed"):
                service.dispatch(request.id, USER)
            assert service.drain("worker").dispatched == 0
        finally:
            release.set()
        assert running.result().dispatched == 1
    assert provider.calls == 1
    assert len(repository.list_thread_messages(repository.get_task(request.task_id).thread_id)) == 1


@pytest.mark.parametrize("retry_after", ["8", "Sun, 04 Oct 2026 00:00:08 GMT"])
def test_provider_retry_after_is_honored_without_persisting_headers(tmp_path, retry_after):
    from agentmesh.research_dispatch import ResearchDispatchService

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    request = _request(repository, "limited")
    at = datetime(2026, 10, 4, tzinfo=UTC)

    class Provider:
        def acquire(self, _request):
            response = httpx.Response(429, headers={"Retry-After": retry_after}, request=httpx.Request("GET", "https://secret.invalid"))
            raise httpx.HTTPStatusError("private URL", request=response.request, response=response)

    result = ResearchDispatchService(
        repository, PersonalAgent(repository, acquisition_agent=Provider()), process_epoch="a", clock=lambda: at,
    ).drain("worker")
    assert result.retrying == 1
    state = repository.get_blackboard_post(request.id).research_dispatch
    assert state.next_retry_at == at + timedelta(seconds=8)
    assert "secret.invalid" not in state.model_dump_json()


def test_task_settled_while_provider_fails_is_not_overwritten(tmp_path):
    from agentmesh.models import TaskStatus
    from agentmesh.provider_status import ProviderQueryError
    from agentmesh.research_dispatch import ResearchDispatchService

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    request = _request(repository, "settled")

    class Provider:
        def acquire(self, _request):
            task = repository.get_task(request.task_id)
            repository.save_task(task.model_copy(update={"status": TaskStatus.COMPLETED}))
            raise ProviderQueryError("no_data_source_result", requested_provider="research")

    result = ResearchDispatchService(
        repository, PersonalAgent(repository, acquisition_agent=Provider()), process_epoch="a",
    ).drain("worker")
    assert repository.get_task(request.task_id).status == "completed"
    assert result.dispatched == 0
    assert result.last_error_code == "research_task_not_dispatchable"


@pytest.mark.parametrize("partial_evidence", [False, True])
def test_restart_retries_interrupted_read_but_requires_reconciliation_for_partial_publication(tmp_path, partial_evidence):
    from agentmesh.research_dispatch import ResearchDispatchService

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    request = _request(repository, "interrupted")

    class ProcessStopped(BaseException):
        pass

    class Provider:
        calls = 0

        def acquire(self, _request):
            self.calls += 1
            if self.calls == 1:
                if partial_evidence:
                    repository.add_blackboard_post(
                        BlackboardPost(
                            task_id=request.task_id, post_type="evidence", actor="research_connector", title="Partial result",
                            content="Result recorded before interruption", scope="project", permission="project_visible",
                            related_post_id=request.id, sources=_evidence().sources, metadata=_evidence().metadata,
                        ),
                    )
                raise ProcessStopped
            return _evidence()

    provider = Provider()
    service = ResearchDispatchService(repository, PersonalAgent(repository, acquisition_agent=provider), process_epoch="old")
    with pytest.raises(ProcessStopped):
        service.drain("worker")
    reopened = SQLiteStore(repository.db_path)
    resumed = ResearchDispatchService(reopened, PersonalAgent(reopened, acquisition_agent=provider), process_epoch="new")
    result = resumed.drain("worker")
    state = reopened.get_blackboard_post(request.id).research_dispatch
    if partial_evidence:
        assert result.indeterminate == 1
        assert state.status == "indeterminate"
        assert state.last_error_code == "research_result_requires_reconciliation"
        assert state.attempts == 1
        assert provider.calls == 1
        assert reopened.get_task(request.task_id).status == "waiting_external_agent"
        assert not reopened.list_thread_messages(reopened.get_task(request.task_id).thread_id)
    else:
        assert result.dispatched == 1
        assert state.status == "completed"
        assert state.attempts == 2
        assert provider.calls == 2


@pytest.mark.parametrize("status", [401, 403])
def test_provider_authentication_failure_is_terminal_and_not_retried(tmp_path, status):
    from agentmesh.research_dispatch import ResearchDispatchService

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    request = _request(repository, "unauthorized")

    class Provider:
        calls = 0

        def acquire(self, _request):
            self.calls += 1
            response = httpx.Response(status, request=httpx.Request("GET", "https://secret.invalid"))
            raise httpx.HTTPStatusError("private details", request=response.request, response=response)

    provider = Provider()
    service = ResearchDispatchService(repository, PersonalAgent(repository, acquisition_agent=provider), process_epoch="a")
    assert service.drain("worker").failed == 1
    assert service.drain("worker").failed == 0
    assert provider.calls == 1
    assert repository.get_blackboard_post(request.id).research_dispatch.last_error_code == "research_provider_unauthorized"


def test_research_drain_is_bounded_and_project_tasks_cannot_bypass_runtime_or_review(tmp_path):
    from agentmesh.models import ChatThreadKind
    from agentmesh.research_dispatch import ResearchDispatchService

    repository = SQLiteStore(tmp_path / "research.sqlite3")
    ensure_seed_data(repository)
    requests = [_request(repository, str(index)) for index in range(3)]
    task = repository.get_task(requests[0].task_id)
    thread = repository.get_chat_thread(task.thread_id)
    repository.save_chat_thread(thread.model_copy(update={"kind": ChatThreadKind.TASK}))

    class Provider:
        calls = 0

        def acquire(self, _request):
            self.calls += 1
            return _evidence()

    provider = Provider()
    service = ResearchDispatchService(repository, PersonalAgent(repository, acquisition_agent=provider), process_epoch="a")
    first = service.drain("worker", limit=1)
    assert first.has_more is True
    assert first.blocked == 1
    assert provider.calls == 0
    assert repository.get_task(task.id).status == "waiting_external_agent"
    assert service.drain("worker", limit=1).dispatched == 1
    assert provider.calls == 1
    assert service.drain("worker", limit=1).dispatched == 1
    assert provider.calls == 2
