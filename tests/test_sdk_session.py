from __future__ import annotations

import asyncio

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.compaction import compact_session_if_needed
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agent_runtime.session import AgentMeshSession
from agentmesh.models import AgentToolGrant, ChatMessage, ChatRole, Scope
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


def test_agentmesh_session_supports_sdk_protocol_and_compaction(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "session.sqlite3")
    session = AgentMeshSession("thread_compact", repository)

    async def scenario() -> None:
        await session.add_items(
            [{"role": "user" if index % 2 == 0 else "assistant", "content": f"message {index} " + "x" * 50} for index in range(25)]
        )
        model = ScriptedModel([[assistant_message("Goal and decisions preserved.")]])
        compacted = await compact_session_if_needed(session, model, trigger_tokens=1, keep_recent_items=4)
        assert compacted is True
        items = await session.get_items()
        assert len(items) == 5
        assert "Previous conversation summary" in str(items[0])
        assert "message 24" in str(items[-1])
        model.assert_complete()

    asyncio.run(scenario())


def test_compaction_does_not_overwrite_concurrent_session_append(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "compaction-race.sqlite3")
    session = AgentMeshSession("thread_compaction_race", repository)

    async def slow_summary(_call):
        await asyncio.sleep(0.05)
        return [assistant_message("summary")]

    async def scenario() -> None:
        await session.add_items(
            [{"role": "user", "content": f"old-{index}" + "x" * 50} for index in range(25)]
        )
        model = ScriptedModel([ModelStep.respond(slow_summary)])
        compaction = asyncio.create_task(
            compact_session_if_needed(session, model, trigger_tokens=1, keep_recent_items=4)
        )
        await asyncio.sleep(0.01)
        await session.add_items([{"role": "user", "content": "concurrent-new-item"}])
        assert await compaction is False
        items = await session.get_items()
        assert any(item.get("content") == "concurrent-new-item" for item in items)

    asyncio.run(scenario())


def test_session_reconciles_legacy_messages_after_sdk_initialization(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "mixed-session.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")
    model = ScriptedModel(
        [
            [assistant_message("sdk first")],
            [assistant_message("sdk saw legacy")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    runtime.run_sync(content="sdk first question", user=USER, thread_id="thread_mixed", history=[])
    legacy_user = repository.add_chat_message(
        ChatMessage(thread_id="thread_mixed", role=ChatRole.USER, content="legacy question", scope=Scope.PRIVATE)
    )
    legacy_assistant = repository.add_chat_message(
        ChatMessage(thread_id="thread_mixed", role=ChatRole.ASSISTANT, content="legacy answer", scope=Scope.PRIVATE)
    )

    runtime.run_sync(
        content="sdk follow-up",
        user=USER,
        thread_id="thread_mixed",
        history=[legacy_user, legacy_assistant],
    )

    second_input = model.calls[1].input
    assert isinstance(second_input, list)
    assert any("legacy question" in str(item) for item in second_input)
    assert any("legacy answer" in str(item) for item in second_input)


def test_concurrent_bootstrap_deduplicates_authoritative_chat_messages(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "bootstrap-race.sqlite3")
    session = AgentMeshSession("thread_bootstrap_race", repository)
    message = ChatMessage(
        id="message_bootstrap_once",
        thread_id="thread_bootstrap_race",
        role=ChatRole.USER,
        content="legacy message",
        scope=Scope.PRIVATE,
    )

    async def scenario() -> None:
        await asyncio.gather(session.bootstrap([message]), session.bootstrap([message]))
        items = await session.get_items()
        assert [item.get("content") for item in items] == ["legacy message"]

    asyncio.run(scenario())


def test_session_appends_are_transactional_under_concurrency(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "concurrent-session.sqlite3")
    session = AgentMeshSession("thread_concurrent", repository)

    async def scenario() -> None:
        await asyncio.gather(
            *(
                session.add_items([{"role": "user", "content": f"message-{index}"}])
                for index in range(20)
            )
        )
        items = await session.get_items()
        assert len(items) == 20
        assert {item["content"] for item in items} == {f"message-{index}" for index in range(20)}

    asyncio.run(scenario())


def test_session_pop_and_clear_increment_versions_atomically(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "session-destructive.sqlite3")
    session = AgentMeshSession("thread_destructive", repository)

    async def scenario() -> None:
        await session.add_items([{"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}])
        _items, version_before_pop = await session.snapshot()
        popped = await session.pop_item()
        items_after_pop, version_after_pop = await session.snapshot()
        assert popped["content"] == "two"
        assert [item["content"] for item in items_after_pop] == ["one"]
        assert version_after_pop == version_before_pop + 1

        await session.clear_session()
        items_after_clear, version_after_clear = await session.snapshot()
        assert items_after_clear == []
        assert version_after_clear == version_after_pop + 1

    asyncio.run(scenario())


def test_background_approval_run_creates_inbox_item(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "background-approval.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_background_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    model = ScriptedModel(
        [
            [function_call("web_research", {"query": "background"}, call_id="background_web")],
            [assistant_message("approved background answer")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    async def scenario() -> None:
        run = await runtime.start(
            content="background external research",
            user=USER,
            thread_id="thread_background_approval",
            history=[],
        )
        for _ in range(50):
            current = repository.get_agent_run(run.id)
            if current is not None and current.status == "waiting_approval":
                break
            await asyncio.sleep(0.01)
        items = [item for item in repository.inbox_items if item.metadata.get("run_id") == run.id]
        assert len(items) == 1
        assert items[0].item_type == "sdk_tool_approval"
        assert [message.role for message in repository.list_thread_messages(run.thread_id)] == ["user"]

        resumed = await runtime.resume(run.id, user=USER, decisions={"background_web": True})
        assert resumed.content == "approved background answer"
        messages = repository.list_thread_messages(run.thread_id)
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[-1].content == "approved background answer"

    asyncio.run(scenario())


def test_background_run_can_be_cancelled(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "cancel.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")

    async def slow_response(_call):
        await asyncio.sleep(5)
        return [assistant_message("too late")]

    model = ScriptedModel([ModelStep.respond(slow_response)])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    async def scenario() -> None:
        run = await runtime.start(
            content="slow question",
            user=USER,
            thread_id="thread_cancel",
            history=[],
        )
        await asyncio.sleep(0.02)
        cancelled = await runtime.cancel(run.id, user=USER)
        assert cancelled.status == "cancelled"
        for _ in range(50):
            if run.id not in runtime._tasks:
                break
            await asyncio.sleep(0.01)
        current = repository.get_agent_run(run.id)
        assert current is not None
        assert current.status == "cancelled"
        assert [event.event_type for event in repository.list_agent_run_events(run.id)].count("run_cancelled") == 1

    asyncio.run(scenario())


def test_background_run_persists_stream_events(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "background.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")
    model = ScriptedModel([[assistant_message("background answer")]])
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    async def scenario() -> None:
        run = await runtime.start(
            content="background question",
            user=USER,
            thread_id="thread_background",
            history=[],
        )
        for _ in range(50):
            current = repository.get_agent_run(run.id)
            if current is not None and current.status in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.01)
        current = repository.get_agent_run(run.id)
        assert current is not None
        assert current.status == "completed"
        events = repository.list_agent_run_events(run.id)
        assert events[0].event_type == "run_started"
        assert any(event.event_type == "sdk_stream_event" for event in events)
        assert events[-1].event_type == "run_completed"

    asyncio.run(scenario())
