"""Tests for R1: layered retrieval strategy in _search_team_brain."""

from __future__ import annotations

from unittest.mock import patch

from agentmesh.agents import PersonalAgent
from agentmesh.models import (
    MemoryItem,
    MemoryLayer,
    MemoryStatus,
    Scope,
    UserMemoryItem,
)
from agentmesh.seed import PROJECT, USER, WORKSPACE
from agentmesh.store import store


def _reset_and_seed() -> None:
    store.reset()
    store.save_project(PROJECT)


class TestLayeredRetrieval:
    def setup_method(self) -> None:
        _reset_and_seed()

    def test_tier1_team_accepted_returns_without_drilling_down(self) -> None:
        """When TEAM_ACCEPTED has enough results, don't search lower tiers."""
        for i in range(4):
            store.add_memory_item(
                MemoryItem(
                    title=f"团队部署规范{i}",
                    summary=f"这是第{i}条关于部署的团队规范文档",
                    memory_type="standard",
                    scope=Scope.TEAM_ACCEPTED,
                    status=MemoryStatus.ACCEPTED,
                    workspace_id=WORKSPACE.id,
                    project_id=PROJECT.id,
                )
            )
        store.add_user_memory_item(
            UserMemoryItem(
                user_id=USER.id,
                layer=MemoryLayer.SHORT_TERM,
                title="个人部署笔记",
                summary="我的私人部署备忘",
                source_kind="note",
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            )
        )
        agent = PersonalAgent(repository=store)
        results = agent._search_team_brain("部署规范", USER)
        assert len(results) >= 3
        assert all(r.scope == Scope.TEAM_ACCEPTED for r in results)

    def test_tier2_project_supplements_when_tier1_insufficient(self) -> None:
        """When TEAM_ACCEPTED < 3 results, drill to PROJECT scope."""
        store.add_memory_item(
            MemoryItem(
                title="团队部署经验",
                summary="唯一一条团队级部署经验",
                memory_type="standard",
                scope=Scope.TEAM_ACCEPTED,
                status=MemoryStatus.ACCEPTED,
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            )
        )
        for i in range(3):
            store.add_memory_item(
                MemoryItem(
                    title=f"项目部署流程{i}",
                    summary=f"项目级部署流程第{i}步的详细说明",
                    memory_type="standard",
                    scope=Scope.PROJECT,
                    status=MemoryStatus.ACCEPTED,
                    workspace_id=WORKSPACE.id,
                    project_id=PROJECT.id,
                )
            )
        agent = PersonalAgent(repository=store)
        results = agent._search_team_brain("部署流程", USER)
        assert len(results) >= 3
        scopes = {r.scope for r in results}
        assert Scope.PROJECT in scopes or Scope.TEAM_ACCEPTED in scopes

    def test_tier3_private_reached_when_higher_tiers_empty(self) -> None:
        """When higher tiers have no results, personal memory is searched."""
        store.add_user_memory_item(
            UserMemoryItem(
                user_id=USER.id,
                layer=MemoryLayer.SHORT_TERM,
                title="个人独特部署问题",
                summary="我遇到的独特部署失败场景和解决方案",
                source_kind="note",
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            )
        )
        agent = PersonalAgent(repository=store)
        results = agent._search_team_brain("独特部署问题", USER)
        assert len(results) >= 1
        assert any(r.result_type == "user_memory_item" for r in results)

    def test_fallback_term_matching_when_all_tiers_empty(self) -> None:
        """When FTS/vector finds nothing, broad term matching is used."""
        store.add_memory_item(
            MemoryItem(
                title="会场设计规范要点总结",
                summary="大促会场首屏 Banner 比例为 16:9，配色不超过三种",
                memory_type="standard",
                scope=Scope.TEAM_ACCEPTED,
                status=MemoryStatus.ACCEPTED,
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            )
        )
        agent = PersonalAgent(repository=store)
        results = agent._search_team_brain("会场 Banner 配色", USER)
        assert len(results) >= 1

    def test_max_five_results_returned(self) -> None:
        """Never returns more than 5 results regardless of tier."""
        for i in range(10):
            store.add_memory_item(
                MemoryItem(
                    title=f"团队部署文档{i:02d}",
                    summary=f"第{i}份部署相关的团队规范文档",
                    memory_type="standard",
                    scope=Scope.TEAM_ACCEPTED,
                    status=MemoryStatus.ACCEPTED,
                    workspace_id=WORKSPACE.id,
                    project_id=PROJECT.id,
                )
            )
        agent = PersonalAgent(repository=store)
        results = agent._search_team_brain("部署文档", USER)
        assert len(results) <= 5
