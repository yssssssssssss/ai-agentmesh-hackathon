from __future__ import annotations

import asyncio
import json

import pytest
from agents.testing import ScriptedModel, assistant_message
from fastapi import HTTPException
from fastapi.testclient import TestClient

import agentmesh.routes.skills as skill_routes
from agentmesh.app import app
from agentmesh.models import Scope, SkillBinding, SkillRecommendationRequest, SkillSourceScope
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime import service as skill_service
from agentmesh.skill_runtime.plan_validation import validate_draft
from agentmesh.skill_runtime.planner import SkillIntentAnalyzer, SkillPlanner, deterministic_intent
from agentmesh.skill_runtime.retrieval import SkillCandidateRetriever
from agentmesh.skill_runtime.service import SkillCatalogService, catalog_service
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data


def _catalog(tmp_path, configure_pilot_wiki) -> tuple[SQLiteStore, SkillCatalogService]:
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "recommendations.sqlite3")
    ensure_tool_seed_data(repository, granted_by="test")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    return repository, catalog


def test_intent_analyzer_keeps_explicit_skill_selection_user_controlled() -> None:
    model = ScriptedModel(
        [
            [
                assistant_message(
                    json.dumps(
                        {
                            "goal": "制定研究计划并生成访谈提纲和问卷",
                            "primary_stage": "pre_design",
                            "input_kinds": ["结算页改版需求", "目标用户：首次下单新用户"],
                            "deliverables": [
                                "两周用户研究计划",
                                "首次下单新用户访谈提纲",
                                "定量问卷",
                                "综合执行建议",
                            ],
                            "constraints": {"external_write": False, "project_scope": "current"},
                            "explicit_skill_names": ["用户研究规划", "用户访谈设计", "问卷设计"],
                            "complexity": "workflow",
                        }
                    )
                )
            ]
        ]
    )

    natural_intent, diagnostics = asyncio.run(
        SkillIntentAnalyzer().analyze("制定研究计划并生成访谈提纲和问卷，最后给出执行建议", model=model)
    )
    explicit_intent, explicit_diagnostics = asyncio.run(
        SkillIntentAnalyzer().analyze(
            "生成问卷",
            model=None,
            explicit_skill_name="$generate-survey",
        )
    )

    assert diagnostics == []
    assert natural_intent.input_kinds == ["design_requirement"]
    assert natural_intent.deliverables == ["research_plan", "interview_guide", "survey", "synthesis"]
    assert natural_intent.explicit_skill_names == []
    assert explicit_diagnostics == []
    assert explicit_intent.explicit_skill_names == ["generate-survey"]
    model.assert_complete()


def test_planner_receives_the_exact_symbolic_contract_protocol(tmp_path, configure_pilot_wiki) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)
    intent = deterministic_intent("制定研究计划和访谈提纲")
    candidates, _diagnostics = SkillCandidateRetriever(repository, catalog).recommend(USER, intent)
    research = next(candidate for candidate in candidates if candidate.skill_name == "generate-research-plan")
    interview = next(candidate for candidate in candidates if candidate.skill_name == "generate-interview-guide")
    model = ScriptedModel(
        [
            [
                assistant_message(
                    json.dumps(
                        {
                            "output_contract": ["research_plan", "interview_guide", "synthesis"],
                            "nodes": [
                                {
                                    "id": "node_research",
                                    "skill_id": research.skill_id,
                                    "skill_version": research.profile.skill_version,
                                    "skill_content_hash": research.profile.skill_content_hash,
                                    "reason": "先制定研究计划",
                                    "input_bindings": ["user.design_requirement"],
                                    "output_contract": ["research_plan"],
                                    "side_effect": research.profile.side_effect.value,
                                },
                                {
                                    "id": "node_interview",
                                    "skill_id": interview.skill_id,
                                    "skill_version": interview.profile.skill_version,
                                    "skill_content_hash": interview.profile.skill_content_hash,
                                    "reason": "再生成访谈提纲",
                                    "depends_on": ["node_research"],
                                    "input_bindings": ["node_research.research_plan"],
                                    "output_contract": ["interview_guide"],
                                    "side_effect": interview.profile.side_effect.value,
                                },
                            ],
                        }
                    )
                )
            ]
        ]
    )

    draft = asyncio.run(SkillPlanner().create_draft(intent, candidates, model=model))
    validate_draft(draft, candidates, intent=intent)

    call = model.first_call
    assert call is not None and isinstance(call.input, list)
    assert "opaque identifiers" in (call.system_instructions or "")
    payload = json.loads(call.input[0]["content"])
    assert payload["contract_rules"]["input_bindings"] == [
        "user.request",
        "user.<intent_input_kind>",
        "<dependency_node_id>.<dependency_output_kind>",
    ]
    assert payload["contract_rules"]["synthesis_outputs"] == ["executive_summary", "summary", "synthesis"]
    model.assert_complete()


def test_intent_distinguishes_design_decision_priority_from_issue_prioritization() -> None:
    design_decision = deterministic_intent("确定结算页改版优先级，最后给出执行建议")
    issue_ranking = deterministic_intent("给这些问题排优先级，结合严重度和工作量决定先解决哪个")

    assert "synthesis" in design_decision.deliverables
    assert "prioritized_issues" not in design_decision.deliverables
    assert "prioritized_issues" in issue_ranking.deliverables


def test_builtin_and_legacy_profiles_are_persisted_and_current(tmp_path, configure_pilot_wiki) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)
    domain_profiles = [profile for profile in repository.skill_capability_profiles if profile.planner_eligible]
    legacy_profiles = [profile for profile in repository.skill_capability_profiles if not profile.planner_eligible]

    assert len(domain_profiles) == 10
    assert len(legacy_profiles) == 11
    assert not [diagnostic for diagnostic in catalog.diagnostics if diagnostic.level == "error"]
    for profile in domain_profiles:
        skill = repository.get_skill_definition(profile.skill_id)
        assert skill is not None
        assert profile.skill_version == skill.version
        assert profile.skill_content_hash == skill.content_hash


def test_recommendation_ranks_profiles_and_filters_disabled_binding(tmp_path, configure_pilot_wiki) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)
    retriever = SkillCandidateRetriever(repository, catalog)
    intent = deterministic_intent("请评审这份 PRD 的业务可行性、方案风险和上线影响")

    candidates, diagnostics = retriever.recommend(USER, intent)

    assert candidates[0].skill_name == "prd-feasibility"
    assert len(candidates) <= 12
    assert "embedding_unavailable" in diagnostics

    repository.save_skill_binding(
        SkillBinding(
            id="disable_prd_for_recommendation",
            agent_id=USER.personal_agent_id,
            skill_id=candidates[0].skill_id,
            enabled=False,
            granted_by=USER.id,
        )
    )
    filtered, _ = retriever.recommend(USER, intent)
    assert "prd-feasibility" not in {candidate.skill_name for candidate in filtered}


def test_empty_wiki_is_not_planner_ready(tmp_path, monkeypatch) -> None:
    wiki = tmp_path / "empty-wiki"
    wiki.mkdir()
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    repository = SQLiteStore(tmp_path / "empty.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()

    candidates, diagnostics = SkillCandidateRetriever(repository, catalog).recommend(
        USER,
        deterministic_intent("生成用户访谈提纲"),
    )

    assert "generate-interview-guide" not in {candidate.skill_name for candidate in candidates}
    assert any(item.endswith("wiki.corpus_unavailable") for item in diagnostics)


def test_unrelated_wiki_files_do_not_make_domain_skills_ready(tmp_path, monkeypatch) -> None:
    wiki = tmp_path / "unrelated-wiki"
    wiki.mkdir()
    (wiki / "unrelated.md").write_text("not part of an approved Skill subtree", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    repository = SQLiteStore(tmp_path / "unrelated.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()

    candidates, diagnostics = SkillCandidateRetriever(repository, catalog).recommend(
        USER,
        deterministic_intent("评审这份 PRD 的可行性"),
    )

    assert "prd-feasibility" not in {candidate.skill_name for candidate in candidates}
    assert any(item.endswith("wiki.corpus_unavailable") for item in diagnostics)


def test_reload_removes_profile_when_its_file_disappears(tmp_path, monkeypatch, configure_pilot_wiki) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)
    skill = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert skill is not None
    assert repository.get_skill_capability_profile(skill.id) is not None
    original_profile_path = skill_service.profile_path
    missing = tmp_path / "missing-agentmesh.yaml"
    monkeypatch.setattr(
        skill_service,
        "profile_path",
        lambda item: missing if item.id == skill.id else original_profile_path(item),
    )

    catalog.reload()
    candidates, _diagnostics = SkillCandidateRetriever(repository, catalog).recommend(
        USER,
        deterministic_intent("评审这份 PRD 的可行性"),
    )

    assert repository.get_skill_capability_profile(skill.id) is None
    assert skill.id not in {candidate.skill_id for candidate in candidates}


def test_unconnected_legacy_capability_is_not_treated_as_ready(tmp_path, configure_pilot_wiki) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)
    skill = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert skill is not None
    profile = repository.get_skill_capability_profile(skill.id)
    assert profile is not None
    repository.save_skill_capability_profile(
        profile.model_copy(update={"required_capabilities": ["brief.create"]})
    )

    candidates, diagnostics = SkillCandidateRetriever(repository, catalog).recommend(
        USER,
        deterministic_intent("评审这份 PRD 的可行性"),
    )

    assert skill.id not in {candidate.skill_id for candidate in candidates}
    assert "prd-feasibility:brief.create_not_granted" in diagnostics


def test_skill_profile_search_does_not_leak_into_memory_search(tmp_path, configure_pilot_wiki) -> None:
    repository, _catalog_service = _catalog(tmp_path, configure_pilot_wiki)

    results = repository.search(
        "用户访谈提纲",
        allowed_scopes={Scope.PRIVATE, Scope.PROJECT, Scope.TEAM_ACCEPTED},
        user_id=USER.id,
    )

    assert results == []


def test_recommendations_api_returns_only_safe_profile_metadata(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path / "api-wiki")
    catalog_service().reload()
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"}).status_code == 200

    response = client.post(
        "/api/skills/recommendations",
        json={"content": "评审这份 PRD 的产品可行性和业务风险"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidates"][0]["skill_name"] == "prd-feasibility"
    assert "instructions" not in response.text
    assert len(payload["candidates"]) <= 12


@pytest.mark.parametrize("project_state", ["missing", "wrong_workspace", "revoked"])
def test_recommendations_reject_invalid_default_project_before_intent(
    tmp_path,
    monkeypatch,
    project_state: str,
) -> None:
    repository = SQLiteStore(tmp_path / f"recommendation-project-{project_state}.sqlite3")
    ensure_base_workspace_data(repository)
    user = USER
    project = repository.get_project(USER.default_project_id)
    assert project is not None
    if project_state == "missing":
        user = USER.model_copy(update={"default_project_id": "prj_missing"})
    elif project_state == "wrong_workspace":
        repository.save_project(project.model_copy(update={"workspace_id": "ws_foreign"}))
    else:
        repository.save_project(project.model_copy(update={"member_ids": ["usr_someone_else"]}))
    repository.save_user(user)

    class IntentTrap:
        calls = 0

        async def analyze(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("Intent must not run without project access")

    trap = IntentTrap()
    monkeypatch.setattr(skill_routes, "store", repository)
    monkeypatch.setattr(skill_routes, "_intent_analyzer", trap)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            skill_routes.recommend_skills(
                SkillRecommendationRequest(content="生成研究计划"),
                user=user,
            )
        )

    assert error.value.status_code == 404
    assert trap.calls == 0


def test_recommendations_recheck_project_access_after_intent(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "recommendation-project-revoked-during-intent.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)

    class RevokingIntentAnalyzer:
        calls = 0

        async def analyze(self, content, **_kwargs):
            self.calls += 1
            project = repository.get_project(USER.default_project_id)
            assert project is not None
            repository.save_project(project.model_copy(update={"member_ids": ["usr_someone_else"]}))
            return deterministic_intent(content), []

    analyzer = RevokingIntentAnalyzer()
    monkeypatch.setattr(skill_routes, "store", repository)
    monkeypatch.setattr(skill_routes, "_intent_analyzer", analyzer)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            skill_routes.recommend_skills(
                SkillRecommendationRequest(content="生成研究计划"),
                user=USER,
            )
        )

    assert error.value.status_code == 404
    assert analyzer.calls == 1


def test_workspace_skill_remains_explicit_but_is_excluded_from_orchestration(
    tmp_path,
    monkeypatch,
    configure_pilot_wiki,
) -> None:
    configure_pilot_wiki(tmp_path / "wiki")
    skill_root = tmp_path / "workspace-skills"
    skill_dir = skill_root / "workspace-review"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: workspace-review\ndescription: Review a workspace draft.\n---\n\n# Review\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTMESH_SKILL_PATHS", str(skill_root))
    repository = SQLiteStore(tmp_path / "workspace-skill.sqlite3")
    ensure_tool_seed_data(repository, granted_by="test")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    workspace_skill = catalog.get_by_name("workspace-review", USER.personal_agent_id)
    assert workspace_skill is not None and workspace_skill.source_scope == SkillSourceScope.WORKSPACE
    profile_dir = skill_dir / "agents"
    profile_dir.mkdir()
    (profile_dir / "agentmesh.yaml").write_text(
        "\n".join(
            [
                "skill_id: auto",
                f"skill_version: '{workspace_skill.version}'",
                f"skill_content_hash: '{workspace_skill.content_hash}'",
                "profile_version: '1'",
                "primary_stage: pre_design",
                "capability_type: review",
                "input_kinds: [design_requirement]",
                "output_kinds: [workspace_review]",
                "planner_eligible: true",
            ]
        ),
        encoding="utf-8",
    )

    catalog.reload()
    explicit_skill = catalog.get_by_name("workspace-review", USER.personal_agent_id)
    profile = repository.get_skill_capability_profile(workspace_skill.id)
    candidates, _diagnostics = SkillCandidateRetriever(repository, catalog).recommend(
        USER,
        deterministic_intent("Review this workspace draft", explicit_skill_name="workspace-review"),
    )

    assert explicit_skill is not None
    assert profile is not None and profile.planner_eligible is False
    assert candidates == []
