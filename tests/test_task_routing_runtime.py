from __future__ import annotations

import asyncio
from contextlib import suppress

from agents.testing import ScriptedModel

from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agent_runtime.settings import SkillOrchestrationMode
from agentmesh.llm import (
    llm_chat_timeout_seconds,
    research_skill_timeout_seconds,
    skill_match_llm_timeout_seconds,
)
from agentmesh.models import AgentRunStatus, AgentToolGrant, ChatThread, SkillPlanStatus
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.planner import deterministic_intent
from agentmesh.skill_runtime.resources import skill_resource_manifest
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


def test_orchestration_timeout_defaults_are_tiered(monkeypatch) -> None:
    monkeypatch.delenv("AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AGENTMESH_RESEARCH_SKILL_TIMEOUT_SECONDS", raising=False)

    assert llm_chat_timeout_seconds() == 120
    assert research_skill_timeout_seconds() == 180


def test_skill_match_llm_timeout_is_configurable(monkeypatch) -> None:
    monkeypatch.delenv("AGENTMESH_SKILL_MATCH_LLM_TIMEOUT_SECONDS", raising=False)
    assert skill_match_llm_timeout_seconds() == 8

    monkeypatch.setenv("AGENTMESH_SKILL_MATCH_LLM_TIMEOUT_SECONDS", "5.5")
    assert skill_match_llm_timeout_seconds() == 5.5

    monkeypatch.setenv("AGENTMESH_SKILL_MATCH_LLM_TIMEOUT_SECONDS", "invalid")
    assert skill_match_llm_timeout_seconds() == 8


def test_runtime_builds_route_bound_plan_without_llm_planner(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "true")
    configure_pilot_wiki(tmp_path / "routing-runtime-wiki")
    repository = SQLiteStore(tmp_path / "routing-runtime.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="test")
    repository.save_agent_tool_grant(
        AgentToolGrant(agent_id=USER.personal_agent_id, tool_id="tool_web_research", granted_by="test")
    )
    catalog = SkillCatalogService(repository)
    catalog.reload()
    request = (
        "基于2025-2026年公开资料研究竞品和用户心智，"
        "输出策略地图、设计原则、机会点和P0/P1/P2。"
    )

    class IntentAnalyzerStub:
        async def analyze(self, *_args, **_kwargs):
            return deterministic_intent(request), []

    class PlannerTrap:
        async def create_draft(self, *_args, **_kwargs):
            raise AssertionError("the LLM planner must not run for a catalog route")

    class ToolFactoryTrap:
        calls = 0

        def build(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("preview must not construct tools")

    tool_factory = ToolFactoryTrap()
    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        tool_factory=tool_factory,  # type: ignore[arg-type]
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzerStub(),  # type: ignore[arg-type]
        skill_planner=PlannerTrap(),  # type: ignore[arg-type]
    )
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_task_route_runtime",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Task route runtime",
        )
    )

    async def scenario():
        run = await runtime.start_orchestrated(
            content=request,
            user=USER,
            thread_id=thread.id,
            history=[],
            client_turn_id="turn_task_route_runtime",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        await runtime._tasks[run.id]
        return repository.get_agent_run(run.id), repository.get_skill_plan_for_run(run.id)

    run, plan = asyncio.run(scenario())

    assert run is not None and run.status == AgentRunStatus.WAITING_PLAN_APPROVAL
    assert plan is not None and plan.status == SkillPlanStatus.WAITING_APPROVAL
    assert plan.routing_result is not None
    assert plan.routing_result.task.task_id == "define-strategy"
    assert len(plan.nodes) >= 2
    assert all(node.task_id and node.scenario_id and node.skill_registry_id for node in plan.nodes)
    assert any(node.required_tool_names == ["web_research"] for node in plan.nodes)
    competitive = next(node for node in plan.nodes if node.scenario_id == "competitor-benchmark-research")
    competitive_skill = repository.get_skill_definition(competitive.skill_id)
    assert competitive_skill is not None
    knowledge_context = runtime._knowledge_context(skill=competitive_skill, node=competitive)
    resource_manifest = skill_resource_manifest(competitive_skill)
    assert "references/competitive-analysis-skeleton.md" in resource_manifest
    assert "03-knowledge-知识/方法知识/用户研究/方法工具箱/竞品分析.md" not in resource_manifest
    incompatible = next(
        item
        for item in knowledge_context
        if item.get("title") == "竞品分析"
    )
    assert incompatible["availability"] == "routing_metadata_only"
    assert "catalog_id" not in incompatible
    assert "resource_path" not in incompatible
    assert tool_factory.calls == 0
    event_types = [event.event_type for event in repository.list_agent_run_events(run.id)]
    assert event_types.index("task_scenario_routed") < event_types.index("skill_candidates_ranked")


def test_runtime_route_fails_closed_when_web_provider_is_not_real(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "true")
    configure_pilot_wiki(tmp_path / "routing-provider-wiki")
    repository = SQLiteStore(tmp_path / "routing-provider.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="test")
    repository.save_agent_tool_grant(
        AgentToolGrant(agent_id=USER.personal_agent_id, tool_id="tool_web_research", granted_by="test")
    )
    catalog = SkillCatalogService(repository)
    catalog.reload()

    class FakeGateway:
        @staticmethod
        def describe(_name: str):
            return type("Descriptor", (), {"execution_mode": "mock", "health_state": "healthy"})()

    class ToolFactoryStub:
        gateway = FakeGateway()

        def build(self, *_args, **_kwargs):
            raise AssertionError("tools must not be built when provider readiness fails")

    request = "基于最新公开资料研究竞品和用户心智，输出策略地图。"

    class IntentAnalyzerStub:
        async def analyze(self, *_args, **_kwargs):
            return deterministic_intent(request), []

    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        tool_factory=ToolFactoryStub(),  # type: ignore[arg-type]
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzerStub(),  # type: ignore[arg-type]
    )
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_task_route_provider",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Task route provider",
        )
    )

    async def scenario():
        run = await runtime.start_orchestrated(
            content=request,
            user=USER,
            thread_id=thread.id,
            history=[],
            client_turn_id="turn_task_route_provider",
            mode=SkillOrchestrationMode.EXECUTE,
        )
        with suppress(Exception):
            await runtime._tasks[run.id]
        return repository.get_agent_run(run.id)

    run = asyncio.run(scenario())

    assert run is not None and run.status == AgentRunStatus.FAILED
    assert run.error_code == "PlannerUnavailable"
    assert run.output_text is not None and "Web Research is not healthy in real mode" in run.output_text
    assert run.plan_id is None


def test_runtime_route_fails_closed_without_research_grant(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "true")
    configure_pilot_wiki(tmp_path / "routing-no-grant-wiki")
    repository = SQLiteStore(tmp_path / "routing-no-grant.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="test")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    request = "基于最新公开资料研究竞品，输出策略地图。"

    class IntentAnalyzerStub:
        async def analyze(self, *_args, **_kwargs):
            return deterministic_intent(request), []

    runtime = AgentRuntimeService(
        repository,
        model=ScriptedModel([]),
        enabled=True,
        skill_catalog=catalog,
        intent_analyzer=IntentAnalyzerStub(),  # type: ignore[arg-type]
    )
    thread = repository.add_chat_thread(
        ChatThread(
            id="thread_task_route_no_grant",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Task route no grant",
        )
    )

    async def scenario():
        run = await runtime.start_orchestrated(
            content=request,
            user=USER,
            thread_id=thread.id,
            history=[],
            client_turn_id="turn_task_route_no_grant",
            mode=SkillOrchestrationMode.PREVIEW,
        )
        with suppress(Exception):
            await runtime._tasks[run.id]
        return repository.get_agent_run(run.id), repository.list_agent_run_events(run.id)

    run, events = asyncio.run(scenario())

    assert run is not None and run.status == AgentRunStatus.FAILED
    assert run.error_code == "PlannerUnavailable"
    assert run.output_text is not None and "没有降级为无工具普通回答" in run.output_text
    ranked = next(event for event in events if event.event_type == "skill_candidates_ranked")
    assert "external_evidence_capability_missing" in ranked.payload["diagnostics"]
    assert run.plan_id is None
