#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from agents.testing import ScriptedModel, assistant_message

from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.memory_context.service import MemoryContextService
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    ChatThread,
    SkillDefinition,
    SkillIntent,
    SkillMemoryWritePolicy,
    SkillPlan,
    SkillPlanNode,
    SkillPlanStatus,
    SkillSourceScope,
    SkillSynthesisResult,
    run_output_memory_id,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.store import SQLiteStore


async def _smoke(root: Path) -> dict[str, object]:
    os.environ["AGENTMESH_MEMORY_CONTEXT"] = "inject"
    repository = SQLiteStore(root / "workspace-memory-smoke.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_workspace_memory_smoke",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Workspace Memory Smoke",
        )
    )
    skill = repository.save_skill_definition(
        SkillDefinition(
            id="skill_workspace_memory_smoke",
            name="workspace-memory-smoke",
            title="Workspace Memory Smoke Skill",
            description="Produce reusable checkout guidance",
            instructions="Produce reusable checkout guidance.",
            source_path="/virtual/workspace-memory-smoke/SKILL.md",
            source_scope=SkillSourceScope.BUILTIN,
            content_hash="a" * 64,
            memory_write_policy=SkillMemoryWritePolicy.PRIVATE_SHORT_TERM,
        ),
        defer_vector=True,
    )
    source_run = repository.save_agent_run(
        AgentRun(
            id="run_workspace_memory_source",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="总结结算页地址编辑经验",
            status=AgentRunStatus.COMPLETED,
            output_text="结算确认页必须保留地址编辑入口。",
            plan_id="plan_workspace_memory_source",
            planning_mode=AgentPlanningMode.STANDARD,
            project_chat=True,
        )
    )
    synthesis = SkillSynthesisResult(summary="结算确认页必须保留地址编辑入口。")
    repository.save_skill_plan(
        SkillPlan(
            id=source_run.plan_id,
            run_id=source_run.id,
            status=SkillPlanStatus.COMPLETED,
            intent=SkillIntent(goal=source_run.input_text),
            candidate_skill_ids=[skill.id],
            nodes=[
                SkillPlanNode(
                    id="node_workspace_memory_source",
                    skill_id=skill.id,
                    skill_version=skill.version,
                    skill_content_hash=skill.content_hash,
                    reason="沉淀结算经验",
                )
            ],
            synthesis=synthesis.model_dump(mode="json"),
        )
    )
    source_model = ScriptedModel([])
    runtime = AgentRuntimeService(repository=repository, model=source_model, enabled=True)
    runtime.project_orchestration_output(
        source_run,
        source_run.output_text or "",
        selected=SelectedSDKModel(
            model=source_model,
            requested_model="scripted",
            actual_model="scripted",
        ),
    )
    memory_id = run_output_memory_id(source_run.id)
    memory = repository.get_user_memory_item(memory_id)
    if memory is None or memory.source_kind != "sdk_skill_plan":
        raise RuntimeError("workspace_memory_projection_failed")

    reuse_run = repository.save_agent_run(
        AgentRun(
            id="run_workspace_memory_reuse",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="结算页地址编辑应该怎么处理",
            status=AgentRunStatus.RUNNING,
            project_chat=True,
        )
    )
    reuse_model = ScriptedModel([[assistant_message("复用既有结论：保留地址编辑入口 [P1]")]])
    reuse_runtime = AgentRuntimeService(repository=repository, model=reuse_model, enabled=True)
    selected = reuse_runtime._select_model(USER)
    if selected is None:
        raise RuntimeError("workspace_memory_model_unavailable")
    answer = await reuse_runtime._execute_run(
        run=reuse_run,
        selected=selected,
        content=reuse_run.input_text,
        user=USER,
        history=[],
        skill=None,
        project_chat=True,
    )
    receipts = repository.list_memory_use_receipts_for_run(reuse_run.id)
    uses = MemoryContextService(repository).usage_for_run(
        repository.get_agent_run(reuse_run.id) or reuse_run,
        USER,
    )
    if (
        answer.content != "复用既有结论：保留地址编辑入口 [P1]"
        or len(receipts) != 1
        or receipts[0].memory_id != memory.id
        or not uses
        or not uses[0].cited_in_output
    ):
        raise RuntimeError("workspace_memory_reuse_failed")

    manual_run = repository.save_agent_run(
        AgentRun(
            id="run_workspace_memory_manual_smoke",
            thread_id=thread.id,
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="普通讨论结果",
            status=AgentRunStatus.COMPLETED,
            output_text="普通讨论默认不自动写入，但可以由用户确认保存。",
            project_chat=True,
        )
    )
    manual = repository.save_terminal_run_memory(
        run_id=manual_run.id,
        user_id=USER.id,
        title="普通讨论记忆",
    )
    if manual is None or manual.source_kind != "agent_run_manual":
        raise RuntimeError("workspace_manual_memory_save_failed")

    result = {
        "source_run": source_run.id,
        "memory_id": memory.id,
        "reuse_run": reuse_run.id,
        "memory_receipt_id": receipts[0].id,
        "citation": receipts[0].citation_label,
        "cited_in_output": uses[0].cited_in_output,
        "manual_memory_id": manual.id,
        "memory_count": len(repository.user_memory_items),
    }
    repository.close()
    return result


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentmesh-workspace-memory-smoke-") as directory:
        result = asyncio.run(_smoke(Path(directory)))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
