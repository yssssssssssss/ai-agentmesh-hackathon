from __future__ import annotations

import asyncio
from threading import Event
from types import SimpleNamespace

import pytest
from agents.testing import ScriptedModel, assistant_message

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.models import AgentRun, AgentRunStatus, SkillIntent, SkillPlan, SkillPlanNode
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.executor import BoundedDAGExecutor
from agentmesh.skill_runtime.quiesce import (
    OrchestrationQuiesceController,
    OrchestrationQuiescingError,
)
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.factory import AgentMeshToolFactory
from agentmesh.tools import ensure_tool_seed_data


def test_quiesce_waits_for_inflight_permit_and_rejects_new_work() -> None:
    controller = OrchestrationQuiesceController()
    entered = Event()
    release = Event()
    recovery_stopped = Event()

    def admitted_work() -> None:
        with controller.permit():
            entered.set()
            assert release.wait(timeout=2)

    async def stop_recovery() -> None:
        recovery_stopped.set()

    async def exercise() -> None:
        worker = asyncio.create_task(asyncio.to_thread(admitted_work))
        assert await asyncio.to_thread(entered.wait, 2)
        quiesce = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        assert await asyncio.to_thread(controller.wait_until_quiescing, 2)

        assert not quiesce.done()
        assert not recovery_stopped.is_set()
        with pytest.raises(OrchestrationQuiescingError) as error, controller.permit():
            raise AssertionError("quiescing controller admitted new work")
        assert error.value.code == "orchestration_quiescing"

        release.set()
        await worker
        await asyncio.wait_for(quiesce, timeout=2)

    asyncio.run(exercise())

    assert recovery_stopped.is_set()
    assert controller.is_quiesced
    assert controller.active_permits == 0


def test_concurrent_quiesce_callers_share_one_completion() -> None:
    controller = OrchestrationQuiesceController()
    recovery_entered = asyncio.Event()
    release_recovery = asyncio.Event()
    calls = 0

    async def stop_recovery() -> None:
        nonlocal calls
        calls += 1
        recovery_entered.set()
        await release_recovery.wait()

    async def exercise() -> None:
        first = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        await recovery_entered.wait()
        second = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        await asyncio.sleep(0)

        assert not first.done()
        assert not second.done()
        assert calls == 1

        release_recovery.set()
        await asyncio.gather(first, second)

    asyncio.run(exercise())

    assert calls == 1
    assert controller.is_quiesced


def test_cancelling_one_quiesce_waiter_does_not_cancel_shared_completion() -> None:
    controller = OrchestrationQuiesceController()
    entered = Event()
    release = Event()
    recovery_calls = 0

    def admitted_work() -> None:
        with controller.permit():
            entered.set()
            assert release.wait(timeout=2)

    async def stop_recovery() -> None:
        nonlocal recovery_calls
        recovery_calls += 1

    async def exercise() -> None:
        worker = asyncio.create_task(asyncio.to_thread(admitted_work))
        assert await asyncio.to_thread(entered.wait, 2)
        leader = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        assert await asyncio.to_thread(controller.wait_until_quiescing, 2)
        follower = asyncio.create_task(controller.begin_quiesce(stop_recovery))
        await asyncio.sleep(0)
        follower.cancel()
        with pytest.raises(asyncio.CancelledError):
            await follower

        release.set()
        await worker
        await asyncio.wait_for(leader, timeout=2)
        await controller.begin_quiesce(stop_recovery)

    asyncio.run(exercise())

    assert recovery_calls == 1
    assert controller.is_quiesced


def test_runtime_creation_uses_shared_admission_gate(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "quiesced-runtime.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    controller = OrchestrationQuiesceController()
    asyncio.run(controller.begin_quiesce())
    model = ScriptedModel([[assistant_message("must not run")]])
    runtime = AgentRuntimeService(
        repository,
        model=model,
        enabled=True,
        admission=controller,
    )

    with pytest.raises(OrchestrationQuiescingError):
        runtime.run_sync(
            content="blocked",
            user=USER,
            thread_id="thread_quiesced_runtime",
            history=[],
        )

    assert repository.list_agent_runs() == []


def test_executor_does_not_claim_a_ready_node_after_quiesce() -> None:
    controller = OrchestrationQuiesceController()
    asyncio.run(controller.begin_quiesce())
    claims = 0

    class Repository:
        def claim_skill_plan_node(self, _plan_id, _node_id):  # noqa: ANN001, ANN202
            nonlocal claims
            claims += 1
            raise AssertionError("node claim crossed quiesce")

    async def node_runner(*_args):  # noqa: ANN202
        raise AssertionError("node runner crossed quiesce")

    executor = BoundedDAGExecutor(
        Repository(),  # type: ignore[arg-type]
        node_runner=node_runner,
        finalization_strategy=SimpleNamespace(),  # type: ignore[arg-type]
        admission=controller,
    )
    plan = SkillPlan(
        id="plan_quiesced_node",
        run_id="run_quiesced_node",
        intent=SkillIntent(goal="test"),
        nodes=[],
    )
    run = AgentRun(
        id=plan.run_id,
        thread_id="thread_quiesced_node",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="test",
        status=AgentRunStatus.RUNNING,
    )
    node = SkillPlanNode(
        id="node_quiesced",
        skill_id="skill_quiesced",
        skill_version="1",
        skill_content_hash="hash",
        reason="test",
    )

    with pytest.raises(OrchestrationQuiescingError):
        asyncio.run(executor._execute_one(plan, run, node, []))
    assert claims == 0


def test_tool_dispatch_does_not_create_claim_after_quiesce(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "quiesced-tool.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="test")
    run = repository.save_agent_run(
        AgentRun(
            id="run_quiesced_tool",
            thread_id="thread_quiesced_tool",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="search",
            status=AgentRunStatus.RUNNING,
        )
    )
    calls = 0

    class Gateway:
        @staticmethod
        def handlers():
            def memory_search(_context, _arguments):  # noqa: ANN001, ANN202
                nonlocal calls
                calls += 1
                return {"results": []}

            return {"memory_search": memory_search}

    controller = OrchestrationQuiesceController()
    factory = AgentMeshToolFactory(
        repository,
        gateway=Gateway(),  # type: ignore[arg-type]
        admission=controller,
    )
    tool = next(item for item in factory.build(USER) if item.name == "memory_search")
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id=run.thread_id,
        run_id=run.id,
    )
    asyncio.run(controller.begin_quiesce())

    with pytest.raises(OrchestrationQuiescingError):
        asyncio.run(
            tool.on_invoke_tool(
                SimpleNamespace(context=context, tool_call_id="blocked_tool_call"),
                '{"query":"test"}',
            )
        )

    assert calls == 0
    assert repository.list_runtime_tool_call_history(run.id) == ([], [])


@pytest.mark.parametrize("action", ["resume_sync", "node_claim", "tool_claim"])
def test_sync_claims_used_from_to_thread_observe_quiesce_latch(action: str) -> None:
    controller = OrchestrationQuiesceController()
    claims: list[str] = []

    async def exercise() -> str:
        await controller.begin_quiesce()

        def claim() -> None:
            with controller.permit():
                claims.append(action)

        with pytest.raises(OrchestrationQuiescingError) as error:
            await asyncio.to_thread(claim)
        return error.value.code

    assert asyncio.run(exercise()) == "orchestration_quiescing"
    assert claims == []
