"""Tests for P3: Skills auto-extraction from workflow traces."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.auth import issue_session
from agentmesh.models import (
    LearnedSkill,
    MemoryLayer,
    Project,
    Scope,
    SkillStatus,
    User,
    UserMemoryItem,
    Workspace,
)
from agentmesh.seed import PROJECT, TEAM_LEAD, USER, WORKSPACE
from agentmesh.skill_extractor import (
    detect_recurring_patterns,
    extract_workflow_pattern,
    match_skill,
    normalize_query,
    propose_skill_from_pattern,
    try_extract_skills,
)
from agentmesh.skill_runtime.materialize import materialize_learned_skill
from agentmesh.skill_runtime.service import catalog_service
from agentmesh.store import store


def _password() -> str:
    return "designer123"


def _authenticated_client() -> TestClient:
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"user_id": USER.id, "password": _password()})
    assert resp.status_code == 200
    return client


def _client_for(user: User) -> TestClient:
    store.save_user(user)
    _session, token = issue_session(store, user)
    client = TestClient(app)
    client.headers["authorization"] = f"Bearer {token}"
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

    def test_project_skills_are_listed_only_for_project_members(self) -> None:
        owner_client = _authenticated_client()
        project_skill = store.add_learned_skill(
            LearnedSkill(
                id="skill_project_visible",
                title="项目内流程",
                trigger_pattern="项目内触发词",
                steps=["project step"],
                status=SkillStatus.ACTIVE,
                scope=Scope.PROJECT,
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            )
        )
        team_skill = store.add_learned_skill(
            LearnedSkill(
                id="skill_team_without_identity",
                title="缺少团队身份的流程",
                trigger_pattern="团队触发词",
                steps=["team step"],
                status=SkillStatus.ACTIVE,
                scope=Scope.TEAM_ACCEPTED,
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            )
        )
        same_workspace_other_project = Project(
            id="prj_other",
            workspace_id=WORKSPACE.id,
            name="Other project",
            goal="Isolation",
            member_ids=["usr_other_project"],
        )
        store.save_project(same_workspace_other_project)
        other_project_user = User(
            id="usr_other_project",
            workspace_id=WORKSPACE.id,
            default_project_id=same_workspace_other_project.id,
            name="Other project user",
            role="user",
            personal_agent_id="agent_other_project",
        )
        foreign_workspace = Workspace(id="ws_foreign", name="Foreign", description="Isolation")
        foreign_project = Project(
            id="prj_foreign",
            workspace_id=foreign_workspace.id,
            name="Foreign project",
            goal="Isolation",
            member_ids=["usr_foreign"],
        )
        store.save_workspace(foreign_workspace)
        store.save_project(foreign_project)
        foreign_user = User(
            id="usr_foreign",
            workspace_id=foreign_workspace.id,
            default_project_id=foreign_project.id,
            name="Foreign user",
            role="user",
            personal_agent_id="agent_foreign",
        )

        def listed_ids(client: TestClient) -> set[str]:
            response = client.get("/api/memory/skills")
            assert response.status_code == 200
            return {item["id"] for item in response.json()["items"]}

        assert listed_ids(owner_client) == {project_skill.id, team_skill.id}
        assert listed_ids(_client_for(TEAM_LEAD)) == {project_skill.id}
        assert project_skill.id not in listed_ids(_client_for(other_project_user))
        assert project_skill.id not in listed_ids(_client_for(foreign_user))

    def test_project_skill_catalog_and_resolution_are_project_scoped(self) -> None:
        _authenticated_client()
        learned = store.add_learned_skill(
            LearnedSkill(
                id="skill_project_catalog",
                title="项目目录能力",
                trigger_pattern="project-catalog-secret",
                steps=["project-only step"],
                status=SkillStatus.ACTIVE,
                scope=Scope.PROJECT,
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            )
        )
        definition = materialize_learned_skill(store, learned)
        catalog = catalog_service()
        catalog.reload()
        other_project_user = User(
            id="usr_catalog_other_project",
            workspace_id=WORKSPACE.id,
            default_project_id="prj_catalog_other",
            name="Catalog outsider",
            role="user",
            personal_agent_id="agent_catalog_other_project",
        )
        foreign_user = User(
            id="usr_catalog_foreign",
            workspace_id="ws_catalog_foreign",
            default_project_id="prj_catalog_foreign",
            name="Catalog foreign user",
            role="user",
            personal_agent_id="agent_catalog_foreign",
        )

        def catalog_ids(client: TestClient) -> set[str]:
            response = client.get("/api/skills")
            assert response.status_code == 200
            return {item["id"] for item in response.json()["items"]}

        assert definition.id in catalog_ids(_client_for(TEAM_LEAD))
        for outsider in (other_project_user, foreign_user):
            assert definition.id not in catalog_ids(_client_for(outsider))
            assert catalog.get_by_name(definition.name, outsider.personal_agent_id) is None

    def test_project_skill_catalog_uses_the_owners_current_project(self) -> None:
        _authenticated_client()
        learned = store.add_learned_skill(
            LearnedSkill(
                id="skill_owner_project_catalog",
                title="原项目目录能力",
                trigger_pattern="owner-project-secret",
                steps=["project-only step"],
                status=SkillStatus.ACTIVE,
                scope=Scope.PROJECT,
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
            )
        )
        definition = materialize_learned_skill(store, learned)
        other_project = Project(
            id="prj_owner_switched",
            workspace_id=WORKSPACE.id,
            name="Owner switched project",
            goal="Isolation",
            member_ids=[USER.id],
        )
        store.save_project(other_project)
        switched_user = USER.model_copy(update={"default_project_id": other_project.id})
        catalog = catalog_service()
        catalog.reload()

        response = _client_for(switched_user).get("/api/skills")

        assert response.status_code == 200
        assert definition.id not in {item["id"] for item in response.json()["items"]}
        assert catalog.get_by_name(definition.name, switched_user.personal_agent_id) is None

    def test_project_skill_catalog_requires_the_owner_to_remain_a_project_member(self) -> None:
        _authenticated_client()
        former_project = Project(
            id="prj_former_owner",
            workspace_id=WORKSPACE.id,
            name="Former owner project",
            goal="Membership isolation",
            member_ids=["usr_someone_else"],
        )
        store.save_project(former_project)
        removed_owner = USER.model_copy(update={"default_project_id": former_project.id})
        learned = store.add_learned_skill(
            LearnedSkill(
                id="skill_removed_project_owner",
                title="已移出项目的流程",
                trigger_pattern="removed-owner-secret",
                steps=["project-only step"],
                status=SkillStatus.ACTIVE,
                scope=Scope.PROJECT,
                user_id=removed_owner.id,
                workspace_id=WORKSPACE.id,
                project_id=former_project.id,
            )
        )
        definition = materialize_learned_skill(store, learned)
        catalog = catalog_service()
        catalog.reload()

        response = _client_for(removed_owner).get("/api/skills")

        assert response.status_code == 200
        assert definition.id not in {item["id"] for item in response.json()["items"]}
        assert catalog.get_by_name(definition.name, removed_owner.personal_agent_id) is None

    def test_activate_share_and_deprecate_update_catalog_visibility_immediately(self) -> None:
        owner_client = _authenticated_client()
        learned = store.add_learned_skill(
            LearnedSkill(
                id="skill_lifecycle_visibility",
                title="生命周期可见性",
                trigger_pattern="lifecycle-visibility-trigger",
                steps=["lifecycle step"],
                status=SkillStatus.DRAFT,
                scope=Scope.PRIVATE,
                user_id=USER.id,
                workspace_id=WORKSPACE.id,
            )
        )
        activated = owner_client.post(f"/api/memory/skills/{learned.id}/activate")
        assert activated.status_code == 200
        definition = activated.json()["skill_definition"]
        member_client = _client_for(TEAM_LEAD)

        def member_catalog_ids() -> set[str]:
            response = member_client.get("/api/skills")
            assert response.status_code == 200
            return {item["id"] for item in response.json()["items"]}

        assert definition["id"] not in member_catalog_ids()

        shared = owner_client.post(f"/api/memory/skills/{learned.id}/share")
        assert shared.status_code == 200
        assert shared.json()["item"]["workspace_id"] == WORKSPACE.id
        assert shared.json()["item"]["project_id"] == PROJECT.id
        assert definition["id"] in member_catalog_ids()

        deprecated = owner_client.post(f"/api/memory/skills/{learned.id}/deprecate")
        assert deprecated.status_code == 200
        assert definition["id"] not in member_catalog_ids()
        assert catalog_service().get_by_name(definition["name"], TEAM_LEAD.personal_agent_id) is None

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
