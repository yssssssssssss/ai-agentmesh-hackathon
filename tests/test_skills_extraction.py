"""Tests for P3: Skills auto-extraction from workflow traces."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import (
    LearnedSkill,
    MemoryLayer,
    Scope,
    SkillStatus,
    UserMemoryItem,
)
from agentmesh.seed import PROJECT, USER, WORKSPACE
from agentmesh.skill_extractor import (
    detect_recurring_patterns,
    extract_workflow_pattern,
    match_skill,
    normalize_query,
    propose_skill_from_pattern,
    try_extract_skills,
)
from agentmesh.store import store


def _password() -> str:
    return "designer123"


def _authenticated_client() -> TestClient:
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"user_id": USER.id, "password": _password()})
    assert resp.status_code == 200
    return client


def _workflow_memory(query: str, result: str, intent: str = "ask_memory") -> UserMemoryItem:
    return UserMemoryItem(
        user_id=USER.id,
        layer=MemoryLayer.SHORT_TERM,
        title="记忆检索",
        summary=f"用户请求：{query}；处理结果：{result}",
        source_kind=f"chat_workflow:{intent}",
        workspace_id=WORKSPACE.id,
        project_id=PROJECT.id,
    )


class TestPatternDetection:
    def test_extract_workflow_pattern(self) -> None:
        item = _workflow_memory("查竞品数据", "已找到3条")
        assert extract_workflow_pattern(item) == "ask_memory"

    def test_non_workflow_item_returns_none(self) -> None:
        item = UserMemoryItem(
            user_id=USER.id,
            layer=MemoryLayer.SHORT_TERM,
            title="普通记忆",
            summary="无 workflow",
            source_kind="note",
            workspace_id=WORKSPACE.id,
        )
        assert extract_workflow_pattern(item) is None

    def test_normalize_query_removes_numbers(self) -> None:
        assert "N" in normalize_query("618 家电会场")
        assert normalize_query("  多余空格  ") == "多余空格"

    def test_detect_recurring_patterns_threshold(self) -> None:
        items = [
            _workflow_memory("查竞品首屏数据", "找到竞品A数据"),
            _workflow_memory("查竞品首屏指标", "找到竞品B数据"),
            _workflow_memory("查竞品首屏对比", "对比完成"),
        ]
        patterns = detect_recurring_patterns(items, threshold=3)
        assert len(patterns) >= 1
        assert patterns[0]["count"] >= 3

    def test_below_threshold_not_detected(self) -> None:
        items = [
            _workflow_memory("查竞品首屏数据", "找到竞品A数据"),
            _workflow_memory("查竞品首屏指标", "找到竞品B数据"),
        ]
        patterns = detect_recurring_patterns(items, threshold=3)
        assert len(patterns) == 0


class TestSkillProposal:
    def test_propose_skill_creates_draft(self) -> None:
        items = [
            _workflow_memory("查竞品首屏数据", "检索到竞品数据并分析"),
            _workflow_memory("查竞品首屏指标", "检索到指标并对比"),
            _workflow_memory("查竞品首屏表现", "检索到数据并生成报告"),
        ]
        patterns = detect_recurring_patterns(items, threshold=3)
        assert len(patterns) >= 1
        skill = propose_skill_from_pattern(patterns[0], USER.id, WORKSPACE.id, PROJECT.id)
        assert skill.status == SkillStatus.DRAFT
        assert skill.user_id == USER.id
        assert skill.occurrence_count == 3
        assert len(skill.steps) >= 2
        assert len(skill.source_workflow_ids) == 3


class TestSkillMatching:
    def test_match_active_skill(self) -> None:
        skill = LearnedSkill(
            title="查竞品数据",
            trigger_pattern="ask_memory 相关：竞品、首屏、数据",
            steps=["检索记忆", "对比"],
            status=SkillStatus.ACTIVE,
            scope=Scope.PRIVATE,
        )
        matched = match_skill("帮我查竞品首屏数据", [skill])
        assert matched is not None
        assert matched.id == skill.id

    def test_no_match_for_unrelated_query(self) -> None:
        skill = LearnedSkill(
            title="查竞品数据",
            trigger_pattern="ask_memory 相关：竞品、首屏、数据",
            steps=["检索记忆"],
            status=SkillStatus.ACTIVE,
            scope=Scope.PRIVATE,
        )
        matched = match_skill("今天天气怎么样", [skill])
        assert matched is None

    def test_draft_skills_not_matched(self) -> None:
        skill = LearnedSkill(
            title="草稿技能",
            trigger_pattern="ask_memory 相关：部署",
            steps=["检索"],
            status=SkillStatus.DRAFT,
            scope=Scope.PRIVATE,
        )
        matched = match_skill("部署相关问题", [skill])
        assert matched is None


class TestTryExtractSkills:
    def test_skips_already_extracted(self) -> None:
        items = [
            _workflow_memory("查竞品首屏数据", "找到"),
            _workflow_memory("查竞品首屏指标", "找到"),
            _workflow_memory("查竞品首屏对比", "找到"),
        ]
        for item in items:
            store.add_user_memory_item(item)
        existing_skill = LearnedSkill(
            title="已提炼",
            trigger_pattern="test",
            source_workflow_ids=[items[0].id],
            status=SkillStatus.ACTIVE,
            user_id=USER.id,
        )
        new_skills = try_extract_skills(
            user_memory_items=items,
            existing_skills=[existing_skill],
            user_id=USER.id,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )
        assert len(new_skills) == 0


class TestSkillsAPI:
    def setup_method(self) -> None:
        store.reset()

    def test_list_skills_empty(self) -> None:
        client = _authenticated_client()
        resp = client.get("/api/memory/skills")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_activate_skill(self) -> None:
        skill = store.add_learned_skill(
            LearnedSkill(
                title="测试技能",
                trigger_pattern="部署",
                steps=["step1"],
                status=SkillStatus.DRAFT,
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
            )
        )
        client = _authenticated_client()
        resp = client.post(f"/api/memory/skills/{skill.id}/activate")
        assert resp.status_code == 200
        assert resp.json()["item"]["status"] == "active"
        definition = resp.json()["skill_definition"]
        assert definition["metadata"]["learned_skill_id"] == skill.id
        assert definition["source_path"].startswith("learned://")
        catalog = client.get("/api/skills")
        assert catalog.status_code == 200
        assert any(item["id"] == definition["id"] for item in catalog.json()["items"])

    def test_share_skill(self) -> None:
        skill = store.add_learned_skill(
            LearnedSkill(
                title="分享技能",
                trigger_pattern="部署",
                steps=["step1"],
                status=SkillStatus.ACTIVE,
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
            )
        )
        client = _authenticated_client()
        resp = client.post(f"/api/memory/skills/{skill.id}/share")
        assert resp.status_code == 200
        assert resp.json()["item"]["scope"] == "project"

    def test_deprecate_skill(self) -> None:
        skill = store.add_learned_skill(
            LearnedSkill(
                title="废弃技能",
                trigger_pattern="过时流程",
                steps=["old_step"],
                status=SkillStatus.ACTIVE,
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
            )
        )
        client = _authenticated_client()
        resp = client.post(f"/api/memory/skills/{skill.id}/deprecate")
        assert resp.status_code == 200
        assert resp.json()["item"]["status"] == "deprecated"

    def test_cannot_activate_non_draft(self) -> None:
        skill = store.add_learned_skill(
            LearnedSkill(
                title="已激活",
                trigger_pattern="test",
                steps=["step"],
                status=SkillStatus.ACTIVE,
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
            )
        )
        client = _authenticated_client()
        resp = client.post(f"/api/memory/skills/{skill.id}/activate")
        assert resp.status_code == 400
