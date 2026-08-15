"""Tests for A2: project member validation on search."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agentmesh.models import (
    MemoryItem,
    MemoryStatus,
    Project,
    Scope,
    User,
    UserRole,
)
from agentmesh.store import SQLiteStore


def _fresh_store() -> SQLiteStore:
    db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
    return SQLiteStore(db_path=db_path)


def _setup_project_with_members(store: SQLiteStore) -> tuple[str, str, str]:
    """Create a project with user_a as member, user_b excluded. Returns (project_id, user_a_id, user_b_id)."""
    project = Project(
        workspace_id="ws1",
        name="测试项目",
        goal="测试成员校验",
        member_ids=["user_a"],
    )
    store.save_project(project)

    user_a = User(
        id="user_a",
        workspace_id="ws1",
        default_project_id=project.id,
        name="成员A",
        role=UserRole.USER,
        personal_agent_id="agent_a",
    )
    user_b = User(
        id="user_b",
        workspace_id="ws1",
        default_project_id=project.id,
        name="非成员B",
        role=UserRole.USER,
        personal_agent_id="agent_b",
    )
    store._upsert("users", user_a)
    store._upsert("users", user_b)

    return project.id, user_a.id, user_b.id


class TestProjectMemberValidation:
    def test_member_can_search_project_memory(self) -> None:
        s = _fresh_store()
        project_id, user_a, _ = _setup_project_with_members(s)
        s.add_memory_item(
            MemoryItem(
                title="项目部署规范",
                summary="仅项目成员可见的部署规范文档",
                memory_type="note",
                scope=Scope.PROJECT,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws1",
                project_id=project_id,
            )
        )
        results = s.search(
            "部署规范", {Scope.PROJECT}, workspace_id="ws1", project_id=project_id, user_id=user_a
        )
        assert len(results) == 1
        assert results[0].scope == Scope.PROJECT

    def test_non_member_cannot_search_project_memory(self) -> None:
        s = _fresh_store()
        project_id, _, user_b = _setup_project_with_members(s)
        s.add_memory_item(
            MemoryItem(
                title="项目部署规范",
                summary="仅项目成员可见的部署规范文档",
                memory_type="note",
                scope=Scope.PROJECT,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws1",
                project_id=project_id,
            )
        )
        results = s.search(
            "部署规范", {Scope.PROJECT}, workspace_id="ws1", project_id=project_id, user_id=user_b
        )
        project_results = [r for r in results if r.scope == Scope.PROJECT]
        assert len(project_results) == 0

    def test_admin_requires_project_membership(self) -> None:
        s = _fresh_store()
        project_id, _, _ = _setup_project_with_members(s)
        admin = User(
            id="admin_user",
            workspace_id="ws1",
            default_project_id=project_id,
            name="管理员",
            role=UserRole.ADMIN,
            personal_agent_id="agent_admin",
        )
        s._upsert("users", admin)
        s.add_memory_item(
            MemoryItem(
                title="项目部署规范",
                summary="仅项目成员可见的部署规范文档",
                memory_type="note",
                scope=Scope.PROJECT,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws1",
                project_id=project_id,
            )
        )
        results = s.search(
            "部署规范", {Scope.PROJECT}, workspace_id="ws1", project_id=project_id, user_id=admin.id
        )
        assert results == []

    def test_team_lead_requires_project_membership(self) -> None:
        s = _fresh_store()
        project_id, _, _ = _setup_project_with_members(s)
        lead = User(
            id="lead_user",
            workspace_id="ws1",
            default_project_id=project_id,
            name="组长",
            role=UserRole.TEAM_LEAD,
            personal_agent_id="agent_lead",
        )
        s._upsert("users", lead)
        s.add_memory_item(
            MemoryItem(
                title="项目部署规范",
                summary="仅项目成员可见的部署规范文档",
                memory_type="note",
                scope=Scope.PROJECT,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws1",
                project_id=project_id,
            )
        )
        results = s.search(
            "部署规范", {Scope.PROJECT}, workspace_id="ws1", project_id=project_id, user_id=lead.id
        )
        assert results == []


    def test_empty_member_ids_allows_all(self) -> None:
        """Projects without member_ids (legacy) allow all users."""
        s = _fresh_store()
        project = Project(
            workspace_id="ws1",
            name="开放项目",
            goal="无成员限制",
            member_ids=[],
        )
        s.save_project(project)
        user = User(
            id="any_user",
            workspace_id="ws1",
            default_project_id=project.id,
            name="任意用户",
            role=UserRole.USER,
            personal_agent_id="agent_any",
        )
        s._upsert("users", user)
        s.add_memory_item(
            MemoryItem(
                title="开放项目部署文档",
                summary="所有人可见",
                memory_type="note",
                scope=Scope.PROJECT,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws1",
                project_id=project.id,
            )
        )
        results = s.search(
            "部署", {Scope.PROJECT}, workspace_id="ws1", project_id=project.id, user_id=user.id
        )
        assert len(results) == 1

    def test_no_user_id_skips_member_check(self) -> None:
        """System-level search without user_id bypasses member validation."""
        s = _fresh_store()
        project_id, _, _ = _setup_project_with_members(s)
        s.add_memory_item(
            MemoryItem(
                title="项目部署规范",
                summary="系统级搜索不校验成员",
                memory_type="note",
                scope=Scope.PROJECT,
                status=MemoryStatus.ACCEPTED,
                workspace_id="ws1",
                project_id=project_id,
            )
        )
        results = s.search(
            "部署规范", {Scope.PROJECT}, workspace_id="ws1", project_id=project_id, user_id=None
        )
        assert len(results) == 1
