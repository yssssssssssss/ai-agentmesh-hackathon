from __future__ import annotations

import asyncio
from datetime import timedelta

from agents.testing import ScriptedModel

from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatThread,
    Scope,
    SkillDefinition,
    SkillIntent,
    SkillPlan,
    SkillPlanNode,
    SkillSourceScope,
    now_utc,
)
from agentmesh.runner_contracts import RunnerNodeCompletionRequest, RunnerNodeDispatchStatus
from agentmesh.seed import PROJECT, USER, WORKSPACE
from agentmesh.store import SQLiteStore


def test_runtime_waits_for_runner_node_result(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "runner-node-service.sqlite3")
    repository.save_workspace(WORKSPACE)
    repository.save_project(PROJECT)
    repository.save_user(USER)
    thread = repository.save_chat_thread(
        ChatThread(
            id="thread_runner_node_service",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            user_id=USER.id,
            title="Runner node service",
            scope=Scope.PRIVATE,
        )
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_runner_node_service",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
            input_text="Build a report",
            status=AgentRunStatus.RUNNING,
            execution_location="runner",
            plan_id="plan_runner_node_service",
            deadline_at=now_utc() + timedelta(minutes=5),
        )
    )
    skill = SkillDefinition(
        id="skill_runner_node_service",
        name="runner-node-service",
        title="Runner Node Service",
        description="Runner node service test",
        instructions="Build the requested report.",
        source_path="builtin/runner-node-service",
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="runner-node-service-hash",
    )
    plan = SkillPlan(
        id="plan_runner_node_service",
        run_id=run.id,
        intent=SkillIntent(goal="Build a report"),
    )
    node = SkillPlanNode(
        id="node_runner_node_service",
        skill_id=skill.id,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        reason="test",
        attempt=1,
    )
    selected = SelectedSDKModel(
        model=ScriptedModel([]),
        requested_model="default",
        actual_model="server-planner-model",
    )
    runtime = AgentRuntimeService(repository, model=selected.model, enabled=True)

    async def scenario():
        waiting = asyncio.create_task(
            runtime._dispatch_standard_node_to_runner(
                plan=plan,
                node=node,
                run=run,
                user=USER,
                skill=skill,
                selected=selected,
                allowed_tool_names=set(),
                node_prompt={"goal": "Build a report"},
                additional_instructions="Return structured output.",
                timeout_seconds=10,
            )
        )
        await asyncio.sleep(0.05)
        claimed = repository.claim_runner_node_dispatch(
            runner_id="runner_test",
            owner_user_id=USER.id,
            workspace_id=WORKSPACE.id,
            available_tool_names=set(),
        )
        assert claimed is not None
        lease, _run, dispatch = claimed
        repository.complete_runner_node_dispatch(
            lease_id=lease.id,
            runner_id="runner_test",
            request=RunnerNodeCompletionRequest(
                command_id="node-command-1",
                result_payload={
                    "node_id": node.id,
                    "skill_id": skill.id,
                    "summary": "Completed",
                    "deliverable_markdown": "# Report",
                },
                requested_model="default",
                actual_model="local-model",
                total_tokens=12,
            ),
        )
        return await waiting, dispatch

    completed, claimed_dispatch = asyncio.run(scenario())

    assert claimed_dispatch.status is RunnerNodeDispatchStatus.LEASED
    assert completed.status is RunnerNodeDispatchStatus.COMPLETED
    assert completed.result_payload["summary"] == "Completed"
