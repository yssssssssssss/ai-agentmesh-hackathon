from __future__ import annotations

import asyncio

import pytest
from agents.testing import ScriptedModel

from agentmesh.agent_runtime.service import AgentRuntimeService, _CapacityBoundModel
from agentmesh.models import ChatThread
from agentmesh.runtime_capacity import RuntimeCapacityController, RuntimeCapacityError
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore


def test_runtime_capacity_enforces_process_and_user_run_limits() -> None:
    capacity = RuntimeCapacityController(process_run_limit=3, user_run_limit=2, node_limit=1)

    assert capacity.reserve_run(operation_key="a", user_id="user-a") is True
    assert capacity.reserve_run(operation_key="b", user_id="user-a") is True
    assert capacity.reserve_run(operation_key="c", user_id="user-a") is False
    assert capacity.reserve_run(operation_key="c", user_id="user-b") is True
    assert capacity.reserve_run(operation_key="d", user_id="user-c") is False
    capacity.release_run("a")
    assert capacity.reserve_run(operation_key="d", user_id="user-c") is True
    assert capacity.snapshot()["active_runs"] == 3


def test_runtime_rejects_before_persisting_when_run_capacity_is_full(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "capacity-rejection.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_capacity_rejection",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Capacity",
        )
    )
    capacity = RuntimeCapacityController(
        process_run_limit=1,
        user_run_limit=1,
        node_limit=1,
    )
    assert capacity.reserve_run(operation_key="occupied", user_id=USER.id)
    runtime = AgentRuntimeService(
        repository=repository,
        model=ScriptedModel([]),
        enabled=True,
        capacity=capacity,
    )
    assert runtime.tool_factory.capacity is capacity
    assert runtime.mcp_factory.capacity is capacity

    with pytest.raises(RuntimeCapacityError, match="runtime_capacity_exceeded"):
        asyncio.run(
            runtime.start(
                content="must not persist",
                user=USER,
                thread_id=thread.id,
                history=[],
                client_turn_id="turn_capacity_rejection",
            )
        )

    assert repository.get_agent_run_by_client_turn(
        USER.id,
        "turn_capacity_rejection",
    ) is None


def test_runtime_capacity_serializes_llm_and_tool_provider_work() -> None:
    capacity = RuntimeCapacityController(
        process_run_limit=1,
        user_run_limit=1,
        node_limit=1,
        llm_limit=1,
        tool_limit=1,
    )
    active_llm = 0
    max_llm = 0
    active_tools = 0
    max_tools = 0

    class ModelStub:
        async def get_response(self, *_args, **_kwargs):
            nonlocal active_llm, max_llm
            active_llm += 1
            max_llm = max(max_llm, active_llm)
            await asyncio.sleep(0.02)
            active_llm -= 1
            return object()

    bounded_model = _CapacityBoundModel(ModelStub(), capacity)  # type: ignore[arg-type]

    async def tool_worker() -> None:
        nonlocal active_tools, max_tools
        async with capacity.tool_slot():
            active_tools += 1
            max_tools = max(max_tools, active_tools)
            await asyncio.sleep(0.02)
            active_tools -= 1

    async def scenario() -> None:
        await asyncio.gather(
            bounded_model.get_response(),
            bounded_model.get_response(),
        )
        await asyncio.gather(tool_worker(), tool_worker())

    asyncio.run(scenario())

    assert max_llm == 1
    assert max_tools == 1
    assert capacity.snapshot()["active_llm_calls"] == 0
    assert capacity.snapshot()["active_tool_calls"] == 0


def test_runtime_capacity_serializes_nodes_across_callers() -> None:
    capacity = RuntimeCapacityController(process_run_limit=1, user_run_limit=1, node_limit=1)
    active = 0
    maximum = 0
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def worker(index: int) -> None:
        nonlocal active, maximum
        async with capacity.node_slot():
            active += 1
            maximum = max(maximum, active)
            if index == 0:
                first_entered.set()
                await release_first.wait()
            active -= 1

    async def scenario() -> None:
        first = asyncio.create_task(worker(0))
        await first_entered.wait()
        second = asyncio.create_task(worker(1))
        await asyncio.sleep(0.03)
        assert capacity.snapshot()["active_nodes"] == 1
        release_first.set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())
    assert maximum == 1
    assert capacity.snapshot()["active_nodes"] == 0
