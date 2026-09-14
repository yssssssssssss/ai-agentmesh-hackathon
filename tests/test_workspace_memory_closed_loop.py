from __future__ import annotations

from agents.testing import ScriptedModel

from agentmesh.agent_runtime.model_factory import SelectedSDKModel
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    ChatThread,
    MemoryLayer,
    Scope,
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


def _repository(tmp_path) -> SQLiteStore:
    repository = SQLiteStore(tmp_path / "workspace-memory.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    repository.add_chat_thread(
        ChatThread(
            id="thread_workspace_memory",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Workspace memory",
        )
    )
    return repository


def _selected(model: ScriptedModel) -> SelectedSDKModel:
    return SelectedSDKModel(
        model=model,
        requested_model="scripted",
        actual_model="scripted",
    )


def test_standard_skill_plan_projects_one_private_short_term_memory(tmp_path) -> None:
    repository = _repository(tmp_path)
    skill = repository.save_skill_definition(
        SkillDefinition(
            id="skill_memory_plan",
            name="memory-plan",
            title="Memory Plan Skill",
            description="Produce a reusable plan result",
            instructions="Produce the plan.",
            source_path="/virtual/memory-plan/SKILL.md",
            source_scope=SkillSourceScope.BUILTIN,
            content_hash="a" * 64,
            memory_write_policy=SkillMemoryWritePolicy.PRIVATE_SHORT_TERM,
        ),
        defer_vector=True,
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_workspace_memory_plan",
            thread_id="thread_workspace_memory",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="为结算流程制定体验指标",
            status=AgentRunStatus.COMPLETED,
            output_text="完整的计划输出",
            plan_id="plan_workspace_memory",
            planning_mode=AgentPlanningMode.STANDARD,
            project_chat=True,
        )
    )
    synthesis = SkillSynthesisResult(summary="结算体验指标与护栏方案")
    repository.save_skill_plan(
        SkillPlan(
            id=run.plan_id,
            run_id=run.id,
            status=SkillPlanStatus.COMPLETED,
            intent=SkillIntent(goal=run.input_text),
            candidate_skill_ids=[skill.id],
            nodes=[
                SkillPlanNode(
                    id="node_workspace_memory",
                    skill_id=skill.id,
                    skill_version=skill.version,
                    skill_content_hash=skill.content_hash,
                    reason="生成指标方案",
                )
            ],
            synthesis=synthesis.model_dump(mode="json"),
        )
    )
    model = ScriptedModel([])
    runtime = AgentRuntimeService(repository=repository, model=model, enabled=True)

    runtime.project_orchestration_output(run, run.output_text or "", selected=_selected(model))
    runtime.project_orchestration_output(run, run.output_text or "", selected=_selected(model))

    memories = repository.list_user_memory_items(USER.id, MemoryLayer.SHORT_TERM)
    projected = [item for item in memories if item.id == run_output_memory_id(run.id)]
    assert len(projected) == 1
    assert projected[0].summary == synthesis.summary
    assert projected[0].source_kind == "sdk_skill_plan"
    assert projected[0].scope is Scope.PRIVATE
    receipt = repository.get_run_output_projection(run.id)
    assert receipt is not None
    assert receipt.memory_item_id == projected[0].id
    assert receipt.memory_disposition == "projected"
    repository.close()


def test_preview_only_plan_does_not_create_memory(tmp_path) -> None:
    repository = _repository(tmp_path)
    skill = repository.save_skill_definition(
        SkillDefinition(
            id="skill_memory_preview",
            name="memory-preview",
            title="Memory Preview Skill",
            description="Preview only",
            instructions="Preview.",
            source_path="/virtual/memory-preview/SKILL.md",
            source_scope=SkillSourceScope.BUILTIN,
            content_hash="b" * 64,
            memory_write_policy=SkillMemoryWritePolicy.PRIVATE_SHORT_TERM,
        ),
        defer_vector=True,
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_workspace_memory_preview",
            thread_id="thread_workspace_memory",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="预览计划",
            status=AgentRunStatus.COMPLETED,
            output_text="计划已确认；预览模式未执行。",
            plan_id="plan_workspace_memory_preview",
            project_chat=True,
        )
    )
    repository.save_skill_plan(
        SkillPlan(
            id=run.plan_id,
            run_id=run.id,
            status=SkillPlanStatus.APPROVED,
            intent=SkillIntent(goal=run.input_text),
            candidate_skill_ids=[skill.id],
            nodes=[
                SkillPlanNode(
                    skill_id=skill.id,
                    skill_version=skill.version,
                    skill_content_hash=skill.content_hash,
                    reason="只预览",
                )
            ],
        )
    )
    model = ScriptedModel([])
    AgentRuntimeService(repository=repository, model=model, enabled=True).project_orchestration_output(
        run,
        run.output_text or "",
        selected=_selected(model),
    )

    assert repository.get_user_memory_item(run_output_memory_id(run.id)) is None
    receipt = repository.get_run_output_projection(run.id)
    assert receipt is not None and receipt.memory_disposition == "policy_skipped"
    repository.close()


def test_general_workspace_run_is_policy_skipped_until_user_saves_it(tmp_path) -> None:
    repository = _repository(tmp_path)
    run = repository.save_agent_run(
        AgentRun(
            id="run_workspace_memory_manual",
            thread_id="thread_workspace_memory",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="整理今天的设计讨论",
            status=AgentRunStatus.COMPLETED,
            output_text="今天确认了首屏入口优先级。",
            project_chat=True,
        )
    )
    model = ScriptedModel([])
    runtime = AgentRuntimeService(repository=repository, model=model, enabled=True)
    runtime.project_orchestration_output(run, run.output_text or "", selected=_selected(model))

    receipt = repository.get_run_output_projection(run.id)
    assert receipt is not None
    assert receipt.memory_item_id is None
    assert receipt.memory_disposition == "policy_skipped"

    first = repository.save_terminal_run_memory(
        run_id=run.id,
        user_id=USER.id,
        title="今日设计讨论",
    )
    second = repository.save_terminal_run_memory(
        run_id=run.id,
        user_id=USER.id,
        title="重复请求不会改写",
    )

    assert first is not None and second is not None
    assert first.id == second.id == run_output_memory_id(run.id)
    assert first.title == "今日设计讨论"
    assert first.source_kind == "agent_run_manual"
    assert len([
        item
        for item in repository.user_memory_items
        if item.id == run_output_memory_id(run.id)
    ]) == 1
    repository.close()
