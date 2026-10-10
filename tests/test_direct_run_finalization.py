from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.models import AgentRunStatus, AgentToolGrant, ChatThread, SDKSessionCheckpointV1, now_utc
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SDKSessionConflict, SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


@pytest.fixture
def direct(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / "direct-finalization.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")
    thread = repository.add_chat_thread(
        ChatThread(
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            title="Current direct execution",
        )
    )
    monkeypatch.setenv("AGENTMESH_MEMORY_CONTEXT", "off")
    yield repository, thread
    repository.close()


def _paused_run(repository, thread):
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_direct_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel(
            [
                [function_call("web_research", {"query": "Approval"}, call_id="direct_approval")],
            ]
        ),
        enabled=True,
    )
    answer = runtime.run_sync(content="Request approval", user=USER, thread_id=thread.id, history=[])
    run = repository.get_agent_run(answer.run_id)
    assert run is not None and run.paused_state is not None
    return run


def _claimed_run(repository, thread):
    run = _paused_run(repository, thread)
    claimed = repository.claim_agent_run_for_resume(
        run.id,
        USER.id,
        inbox_id=f"inbox_tool_approval_{run.id}",
        call_ids={"direct_approval"},
        expected_session_checkpoint=SDKSessionCheckpointV1.model_validate(
            run.paused_state["agentmesh_session_checkpoint"],
        ),
    )
    assert claimed is not None
    return claimed


def test_direct_terminal_event_failure_rolls_back_run_and_inbox_then_allows_retry(direct):
    repository, thread = direct
    claimed = _claimed_run(repository, thread)
    completed = claimed.model_copy(
        update={
            "status": AgentRunStatus.COMPLETED,
            "output_text": "Committed output",
            "paused_state": None,
        }
    )
    inbox_id = f"inbox_tool_approval_{claimed.id}"
    before_inbox = repository.get_inbox_item(inbox_id)
    before_events = repository.list_agent_run_events(claimed.id)
    with repository._connect() as connection:
        connection.execute("""CREATE TRIGGER fail_direct_terminal_event BEFORE INSERT ON agent_run_events
            WHEN json_extract(NEW.payload, '$.event_type') = 'run_completed'
            BEGIN SELECT RAISE(ABORT, 'controlled_terminal_failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="controlled_terminal_failure"):
        repository.save_agent_run_with_event(completed, "run_completed", expected_statuses={AgentRunStatus.RUNNING})
    assert repository.get_agent_run(claimed.id) == claimed
    assert repository.get_inbox_item(inbox_id) == before_inbox
    assert repository.list_agent_run_events(claimed.id) == before_events
    with repository._connect() as connection:
        connection.execute("DROP TRIGGER fail_direct_terminal_event")
    assert repository.save_agent_run_with_event(completed, "run_completed", expected_statuses={AgentRunStatus.RUNNING})
    assert repository.get_agent_run(claimed.id).output_text == "Committed output"
    assert repository.get_inbox_item(inbox_id).status == "resolved"
    assert sum(event.event_type == "run_completed" for event in repository.list_agent_run_events(claimed.id)) == 1


def test_duplicate_direct_completion_commits_one_terminal_event(direct):
    repository, thread = direct
    claimed = _claimed_run(repository, thread)

    def commit(_index):
        completed = claimed.model_copy(
            update={
                "status": AgentRunStatus.COMPLETED,
                "output_text": "One committed output",
                "paused_state": None,
            }
        )
        return repository.save_agent_run_with_event(
            completed, "run_completed", expected_statuses={AgentRunStatus.RUNNING}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        events = list(executor.map(commit, range(2)))
    assert sum(event is not None for event in events) == 1
    assert repository.get_agent_run(claimed.id).status is AgentRunStatus.COMPLETED
    assert repository.get_inbox_item(f"inbox_tool_approval_{claimed.id}").status == "resolved"
    assert sum(event.event_type == "run_completed" for event in repository.list_agent_run_events(claimed.id)) == 1


def test_expected_execution_snapshot_cannot_transfer_the_writer(direct):
    repository, thread = direct
    claimed = _claimed_run(repository, thread)
    before_inbox = repository.get_inbox_item(f"inbox_tool_approval_{claimed.id}")
    before_events = repository.list_agent_run_events(claimed.id)
    replaced = claimed.model_copy(
        update={
            "status": AgentRunStatus.FAILED,
            "error_code": "reported_failure",
            "writer_generation_epoch": 2,
        }
    )
    assert (
        repository.save_agent_run_with_event(
            replaced,
            "run_failed",
            expected_statuses={AgentRunStatus.RUNNING},
            expected_run=claimed,
        )
        is None
    )
    assert repository.get_agent_run(claimed.id) == claimed
    assert repository.get_inbox_item(f"inbox_tool_approval_{claimed.id}") == before_inbox
    assert repository.list_agent_run_events(claimed.id) == before_events


@pytest.mark.parametrize("mode", ["direct", "resume"])
def test_current_sdk_writer_can_complete_or_resume(direct, mode):
    repository, thread = direct
    steps = [[assistant_message("Current execution output")]]
    if mode == "resume":
        repository.save_agent_tool_grant(
            AgentToolGrant(
                id="grant_direct_web",
                agent_id=USER.personal_agent_id,
                tool_id="tool_web_research",
                granted_by="test",
            )
        )
        steps.insert(0, [function_call("web_research", {"query": "Approval"}, call_id="direct_approval")])
    model = ScriptedModel(steps)
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    answer = runtime.run_sync(content="Current request", user=USER, thread_id=thread.id, history=[])
    if mode == "resume":
        assert answer.waiting_approval
        answer = runtime.resume_sync(answer.run_id, user=USER, decisions={"direct_approval": False})
    current = repository.get_agent_run(answer.run_id)
    assert answer.content == "Current execution output" and not answer.waiting_approval
    assert current.status is AgentRunStatus.COMPLETED
    assert current.output_text == answer.content and current.paused_state is None and current.error_code is None
    if mode == "resume":
        assert repository.get_inbox_item(f"inbox_tool_approval_{current.id}").status == "resolved"
    assert sum(event.event_type == "run_completed" for event in repository.list_agent_run_events(current.id)) == 1
    model.assert_complete()


def test_replaced_writer_cannot_be_failed_by_old_stream_session_commit(direct):
    repository, thread = direct

    def replace_writer(_call):
        (run,) = repository.list_agent_runs(USER.id)
        repository.save_agent_run(run.model_copy(update={"writer_generation_epoch": 2}))
        return [assistant_message("Old execution result")]

    model = ScriptedModel([ModelStep(responder=replace_writer)])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(SDKSessionConflict, match="sdk_session_writer_changed"):
        runtime.run_sync(content="Keep current execution alive", user=USER, thread_id=thread.id, history=[])

    (current,) = repository.list_agent_runs(USER.id)
    assert current.writer_generation_epoch == 2
    assert current.status is AgentRunStatus.RUNNING
    assert current.error_code is None and current.output_text is None
    assert len(model.calls) == 1
    assert not any(
        event.event_type in {"run_failed", "run_cancelled", "run_completed"}
        for event in repository.list_agent_run_events(current.id)
    )


def test_replaced_writer_cannot_receive_old_tool_approval_state(direct, monkeypatch):
    repository, thread = direct
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_direct_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    pause = repository.pause_agent_run_with_inbox

    def replace_before_pause(**kwargs):
        current = repository.get_agent_run(kwargs["run_id"])
        assert current is not None
        repository.save_agent_run(current.model_copy(update={"writer_generation_epoch": 2}))
        return pause(**kwargs)

    monkeypatch.setattr(repository, "pause_agent_run_with_inbox", replace_before_pause)
    model = ScriptedModel([[function_call("web_research", {"query": "Approval"}, call_id="direct_approval")]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(RuntimeError, match="changed while pausing"):
        runtime.run_sync(content="Request external approval", user=USER, thread_id=thread.id, history=[])
    (current,) = repository.list_agent_runs(USER.id)
    assert current.writer_generation_epoch == 2
    assert current.status is AgentRunStatus.RUNNING
    assert current.output_text is None and current.error_code is None and current.paused_state is None
    assert repository.get_inbox_item(f"inbox_tool_approval_{current.id}") is None
    assert not any(
        event.event_type in {"run_failed", "run_cancelled", "run_completed", "approval_requested"}
        for event in repository.list_agent_run_events(current.id)
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ("owner_disabled", "sdk_session_not_authorized"),
        ("deadline_expired", "sdk_session_deadline_exceeded"),
        ("session_changed", "sdk_session_checkpoint_changed"),
        ("session_foreign_owner", "sdk_session_not_authorized"),
        ("session_withdrawn", "sdk_session_source_withdrawn"),
        ("checkpoint_missing", "sdk_session_checkpoint_missing"),
    ],
)
def test_tool_pause_rechecks_current_admission_and_its_checkpoint(direct, monkeypatch, change, code):
    repository, thread = direct
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_direct_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    pause = repository.pause_agent_run_with_inbox

    def change_before_pause(**kwargs):
        run = repository.get_agent_run(kwargs["run_id"])
        assert run is not None
        if change == "owner_disabled":
            repository.save_user(USER.model_copy(update={"status": "disabled"}))
        elif change == "deadline_expired":
            repository.save_agent_run(run.model_copy(update={"deadline_at": now_utc() - timedelta(seconds=1)}))
        elif change == "checkpoint_missing":
            kwargs["paused_state"].pop("agentmesh_session_checkpoint")
        else:
            session = repository.get_sdk_session(thread.id)
            assert session is not None
            update = (
                {"version": session.version + 1}
                if change == "session_changed"
                else {"user_id": "other_user"}
                if change == "session_foreign_owner"
                else {"source_status": "withdrawn"}
            )
            repository.save_sdk_session(session.model_copy(update=update))
        return pause(**kwargs)

    monkeypatch.setattr(repository, "pause_agent_run_with_inbox", change_before_pause)
    model = ScriptedModel([[function_call("web_research", {"query": "Approval"}, call_id="direct_approval")]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    with pytest.raises(SDKSessionConflict, match=code):
        runtime.run_sync(content="Request external approval", user=USER, thread_id=thread.id, history=[])
    (current,) = repository.list_agent_runs(USER.id)
    assert current.status is AgentRunStatus.FAILED
    assert current.error_code == code
    assert current.paused_state is None and current.output_text is None
    assert repository.get_inbox_item(f"inbox_tool_approval_{current.id}") is None
    events = repository.list_agent_run_events(current.id)
    assert sum(event.event_type == "run_failed" for event in events) == 1
    assert not any(
        event.event_type in {"approval_requested", "run_completed", "run_output_projected"} for event in events
    )


def test_direct_result_cannot_overwrite_a_new_plan_link(direct):
    repository, thread = direct

    def replace_plan(_call):
        (run,) = repository.list_agent_runs(USER.id)
        repository.save_agent_run(run.model_copy(update={"plan_id": "new_plan"}))
        return [assistant_message("Old execution result")]

    runtime = AgentRuntimeService(repository, model=ScriptedModel([ModelStep(responder=replace_plan)]), enabled=True)
    with pytest.raises(RuntimeError, match="completion conflicted"):
        runtime.run_sync(content="Keep current plan alive", user=USER, thread_id=thread.id, history=[])
    (current,) = repository.list_agent_runs(USER.id)
    assert current.plan_id == "new_plan"
    assert current.status is AgentRunStatus.RUNNING
    assert current.output_text is None and current.error_code is None
    assert not any(
        event.event_type in {"run_failed", "run_cancelled", "run_completed"}
        for event in repository.list_agent_run_events(current.id)
    )


@pytest.mark.parametrize(
    "change",
    [
        {"writer_generation_epoch": 2},
        {"agent_definition_version": "2"},
        {"plan_id": "replacement_plan"},
        {"runner_id": "replacement_runner"},
    ],
)
@pytest.mark.parametrize("mode", ["direct", "resume"])
def test_writer_replaced_after_sdk_return_keeps_its_current_state(direct, monkeypatch, change, mode):
    repository, thread = direct
    save = repository.save_agent_run_with_event
    replacement = None

    def replace_before_commit(run, event_type, payload=None, **kwargs):
        nonlocal replacement
        if event_type == "run_completed":
            current = repository.get_agent_run(run.id)
            assert current is not None
            replacement = repository.save_agent_run(current.model_copy(update=change))
        return save(run, event_type, payload, **kwargs)

    monkeypatch.setattr(repository, "save_agent_run_with_event", replace_before_commit)
    steps = [[assistant_message("Old execution result")]]
    if mode == "resume":
        repository.save_agent_tool_grant(
            AgentToolGrant(
                id="grant_direct_web",
                agent_id=USER.personal_agent_id,
                tool_id="tool_web_research",
                granted_by="test",
            )
        )
        steps.insert(0, [function_call("web_research", {"query": "Approval"}, call_id="direct_approval")])
    model = ScriptedModel(steps)
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    paused = (
        runtime.run_sync(content="Request approval", user=USER, thread_id=thread.id, history=[])
        if mode == "resume"
        else None
    )
    with pytest.raises(RuntimeError, match="completion conflicted"):
        if paused is not None:
            runtime.resume_sync(paused.run_id, user=USER, decisions={"direct_approval": False})
        else:
            runtime.run_sync(content="Finish this execution", user=USER, thread_id=thread.id, history=[])
    (current,) = repository.list_agent_runs(USER.id)
    assert current == replacement
    assert current.status is AgentRunStatus.RUNNING
    assert current.output_text is None and current.error_code is None
    if mode == "resume":
        inbox = repository.get_inbox_item(f"inbox_tool_approval_{current.id}")
        assert inbox is not None and inbox.status == "open"
    assert not any(
        event.event_type in {"run_failed", "run_cancelled", "run_completed", "run_output_projected"}
        for event in repository.list_agent_run_events(current.id)
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ("owner_disabled", "sdk_session_not_authorized"),
        ("project_archived", "sdk_session_not_authorized"),
        ("member_removed", "sdk_session_not_authorized"),
        ("thread_archived", "sdk_session_not_authorized"),
        ("thread_reassigned", "sdk_session_not_authorized"),
        ("deadline_expired", "sdk_session_deadline_exceeded"),
    ],
)
@pytest.mark.parametrize("mode", ["direct", "resume"])
def test_sdk_completion_rechecks_admission_in_its_write_transaction(direct, monkeypatch, change, code, mode):
    repository, thread = direct
    save = repository.save_agent_run_with_event

    def revoke_before_commit(run, event_type, payload=None, **kwargs):
        if event_type == "run_completed":
            if change == "owner_disabled":
                repository.save_user(USER.model_copy(update={"status": "disabled"}))
            elif change in {"project_archived", "member_removed"}:
                project = repository.get_project(run.project_id)
                assert project is not None
                update = {"status": "archived"} if change == "project_archived" else {"member_ids": ["other_user"]}
                repository.save_project(project.model_copy(update=update))
            elif change in {"thread_archived", "thread_reassigned"}:
                update = {"status": "archived"} if change == "thread_archived" else {"user_id": "other_user"}
                repository.save_chat_thread(thread.model_copy(update=update))
            else:
                current = repository.get_agent_run(run.id)
                assert current is not None
                repository.save_agent_run(current.model_copy(update={"deadline_at": now_utc() - timedelta(seconds=1)}))
        return save(run, event_type, payload, **kwargs)

    monkeypatch.setattr(repository, "save_agent_run_with_event", revoke_before_commit)
    steps = [[assistant_message("No late completion")]]
    if mode == "resume":
        repository.save_agent_tool_grant(
            AgentToolGrant(
                id="grant_direct_web",
                agent_id=USER.personal_agent_id,
                tool_id="tool_web_research",
                granted_by="test",
            )
        )
        steps.insert(0, [function_call("web_research", {"query": "Approval"}, call_id="direct_approval")])
    model = ScriptedModel(steps)
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    paused = (
        runtime.run_sync(content="Request approval", user=USER, thread_id=thread.id, history=[])
        if mode == "resume"
        else None
    )
    with pytest.raises(SDKSessionConflict, match=code):
        if paused is not None:
            runtime.resume_sync(paused.run_id, user=USER, decisions={"direct_approval": False})
        else:
            runtime.run_sync(content="Finish with current authority", user=USER, thread_id=thread.id, history=[])
    (current,) = repository.list_agent_runs(USER.id)
    assert current.status is AgentRunStatus.FAILED
    assert current.error_code == code
    assert current.output_text is None and current.paused_state is None
    assert len(model.calls) == (2 if mode == "resume" else 1)
    if mode == "resume":
        inbox = repository.get_inbox_item(f"inbox_tool_approval_{current.id}")
        assert inbox is not None and inbox.status == "resolved"
        assert inbox.metadata["approval_failure"] == code
    events = repository.list_agent_run_events(current.id)
    assert sum(event.event_type == "run_failed" for event in events) == 1
    assert not any(event.event_type in {"run_completed", "run_output_projected"} for event in events)


@pytest.mark.parametrize("mode", ["direct", "resume"])
def test_replaced_writer_cannot_be_cancelled_by_old_model_request(direct, mode):
    repository, thread = direct

    async def scenario():
        entered = asyncio.Event()

        async def hold_model(_call):
            entered.set()
            await asyncio.Event().wait()

        steps = [ModelStep(responder=hold_model)]
        if mode == "resume":
            repository.save_agent_tool_grant(
                AgentToolGrant(
                    id="grant_direct_web",
                    agent_id=USER.personal_agent_id,
                    tool_id="tool_web_research",
                    granted_by="test",
                )
            )
            steps.insert(0, [function_call("web_research", {"query": "Approval"}, call_id="direct_approval")])
        model = ScriptedModel(steps)
        runtime = AgentRuntimeService(repository, model=model, enabled=True)
        if mode == "resume":
            paused = await runtime.run(content="Request approval", user=USER, thread_id=thread.id, history=[])
            operation = runtime.resume(paused.run_id, user=USER, decisions={"direct_approval": False})
        else:
            operation = runtime.run(content="Keep current execution alive", user=USER, thread_id=thread.id, history=[])
        pending = asyncio.create_task(operation)
        try:
            async with asyncio.timeout(10):
                await entered.wait()
            (run,) = repository.list_agent_runs(USER.id)
            repository.save_agent_run(run.model_copy(update={"writer_generation_epoch": 2}))
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(scenario())

    (current,) = repository.list_agent_runs(USER.id)
    assert current.writer_generation_epoch == 2
    assert current.status is AgentRunStatus.RUNNING
    assert current.error_code is None and current.output_text is None
    assert not any(
        event.event_type in {"run_failed", "run_cancelled", "run_completed"}
        for event in repository.list_agent_run_events(current.id)
    )
