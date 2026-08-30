from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import SkillBinding, SkillDefinition, SkillSourceScope
from agentmesh.routes import skills as skill_routes
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.matching import match_skill_directory
from agentmesh.skill_runtime.profiles import PILOT_BUILTIN_SKILL_NAMES
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore


def _skill(
    name: str,
    *,
    title: str = "Neutral title",
    description: str = "Neutral description",
    metadata: dict[str, str] | None = None,
    enabled: bool = True,
) -> SkillDefinition:
    return SkillDefinition(
        id=f"skilldef_{name}",
        name=name,
        title=title,
        description=description,
        instructions="# Instructions",
        source_path=f"/workspace/{name}/SKILL.md",
        source_scope=SkillSourceScope.WORKSPACE,
        content_hash=f"hash-{name}",
        metadata=metadata or {},
        enabled=enabled,
    )


@pytest.mark.parametrize(
    ("query", "expected_name"),
    [
        ("name-beacon", "name-beacon"),
        ("unique title beacon", "title-skill"),
        ("unique description beacon", "description-skill"),
        ("unique metadata beacon", "metadata-skill"),
    ],
)
def test_directory_matcher_searches_each_catalog_field(query: str, expected_name: str) -> None:
    skills = [
        _skill("name-beacon"),
        _skill("title-skill", title="Unique title beacon"),
        _skill("description-skill", description="Unique description beacon"),
        _skill("metadata-skill", metadata={"short-description": "unique metadata beacon"}),
    ]

    matches = match_skill_directory(query, skills, limit=4)

    assert matches[0].skill.name == expected_name
    assert matches[0].score > 0
    assert "beacon" in matches[0].reason


def test_directory_matcher_is_deterministic_and_ignores_provenance_metadata() -> None:
    alpha = _skill("alpha-skill", description="shared signal")
    beta = _skill("beta-skill", description="shared signal")
    provenance_only = _skill(
        "unrelated-skill",
        metadata={
            "author": "design-review",
            "secret-note": "private-token",
            "source": "wiki/design-review/SKILL.md",
        },
    )

    first = match_skill_directory("shared signal", [beta, alpha, provenance_only], limit=1)
    second = match_skill_directory("shared signal", [alpha, beta, provenance_only], limit=1)

    assert [item.skill.name for item in first] == ["alpha-skill"]
    assert [item.skill.name for item in second] == ["alpha-skill"]
    assert match_skill_directory("design-review", [provenance_only], limit=1) == []
    assert match_skill_directory("private-token", [provenance_only], limit=1) == []


@pytest.mark.parametrize(
    ("query", "expected_name"),
    [
        ("创建问卷调研用户需求", "generate-survey"),
        ("看转化漏斗哪里流失", "conversion-funnel-analysis"),
        ("生成筛选组件", "filter-tabs-design-skill"),
        ("分析 AB 测试结果", "design-abtest-analysis"),
        ("分析京东和淘宝的竞品策略", "competitive-analysis"),
        ("根据 PRD 生成高保真原型", "prototype-generation"),
        ("评审这份商品详情页方案，并给出可执行的体验优化建议", "usability-review"),
        ("上线前做无障碍检查", "accessibility-review"),
        ("design-review", "design-review"),
    ],
)
def test_directory_matcher_returns_the_expected_top_skill_for_real_tasks(
    tmp_path,
    query: str,
    expected_name: str,
) -> None:
    catalog = SkillCatalogService(SQLiteStore(tmp_path / "real-skill-matches.sqlite3"))
    catalog.reload()
    skills = [skill for skill, _enabled in catalog.list_for_agent(USER.personal_agent_id)]

    matches = match_skill_directory(query, skills, limit=5)

    assert matches[0].skill.name == expected_name


def test_directory_matcher_does_not_treat_boundary_examples_as_positive_evidence() -> None:
    skill = _skill(
        "positive-skill",
        description="Handles the primary workflow. Boundary: boundary-only-signal belongs elsewhere.",
    )

    assert match_skill_directory("boundary-only-signal", [skill], limit=5) == []


def test_directory_matcher_returns_no_out_of_domain_results(tmp_path) -> None:
    catalog = SkillCatalogService(SQLiteStore(tmp_path / "out-of-domain-skill-matches.sqlite3"))
    catalog.reload()
    skills = [skill for skill, _enabled in catalog.list_for_agent(USER.personal_agent_id)]

    assert match_skill_directory("今天天气怎么样", skills, limit=5) == []
    assert match_skill_directory("帮我订一张机票", skills, limit=5) == []


def test_skill_matches_route_filters_private_and_disabled_skills(tmp_path, monkeypatch) -> None:
    repository = SQLiteStore(tmp_path / "skill-matches.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    visible = _skill(
        "visible-skill",
        description="directory signal",
        metadata={"owner_user_id": USER.id, "learned_scope": "private"},
    )
    hidden = _skill(
        "hidden-skill",
        description="directory signal",
        metadata={"owner_user_id": "usr_someone_else", "learned_scope": "private"},
    )
    disabled = _skill("disabled-skill", description="directory signal")
    unavailable = _skill("unavailable-skill", description="directory signal", enabled=False)
    catalog = SkillCatalogService(repository)
    catalog._skills = {skill.name: skill for skill in (visible, hidden, disabled, unavailable)}
    repository.save_skill_binding(
        SkillBinding(
            id="binding_disabled_skill",
            agent_id=USER.personal_agent_id,
            skill_id=disabled.id,
            enabled=False,
            granted_by=USER.id,
        )
    )
    monkeypatch.setattr(skill_routes, "catalog_service", lambda: catalog)
    client = TestClient(app)

    assert client.post("/api/skills/matches", json={"content": "directory signal"}).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"user_id": USER.id, "password": "designer123"},
    ).status_code == 200

    response = client.post("/api/skills/matches", json={"content": "directory signal", "limit": 5})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "skill_id": visible.id,
                "skill_name": visible.name,
                "command": "$visible-skill",
                "title": visible.title,
                "description": visible.description,
                "primary_stage": None,
                "score": response.json()["items"][0]["score"],
                "reason": "匹配：描述（directory、signal）",
                "planner_eligible": False,
                "readiness": "ready",
                "execution_readiness": "complete",
                "missing_tools": [],
            }
        ],
        "mode": "lexical",
        "clarification": None,
        "diagnostics": ["embedding_unavailable"],
    }
    assert response.json()["items"][0]["score"] > 0


@pytest.mark.parametrize("limit", [0, 6])
def test_skill_matches_route_validates_limit(limit: int) -> None:
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"user_id": USER.id, "password": "designer123"},
    ).status_code == 200

    response = client.post("/api/skills/matches", json={"content": "竞品分析", "limit": limit})

    assert response.status_code == 422


def test_skill_matches_route_rejects_blank_content() -> None:
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"user_id": USER.id, "password": "designer123"},
    ).status_code == 200

    response = client.post("/api/skills/matches", json={"content": " \n\t"})

    assert response.status_code == 422


def test_skill_matches_openapi_contract_and_planner_whitelist() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/api/skills/matches"]["post"]

    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SkillMatchRequest"
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SkillMatchResponse"
    )
    request_schema = schema["components"]["schemas"]["SkillMatchRequest"]
    response_item_schema = schema["components"]["schemas"]["SkillMatchItem"]
    assert set(request_schema["properties"]) == {"content", "limit"}
    assert request_schema["additionalProperties"] is False
    response_schema = schema["components"]["schemas"]["SkillMatchResponse"]
    assert {"items", "mode", "clarification", "diagnostics"} <= set(response_schema["properties"])
    assert {
        "command",
        "title",
        "description",
        "primary_stage",
        "score",
        "reason",
        "planner_eligible",
        "execution_readiness",
        "missing_tools",
    }.issubset(response_item_schema["properties"])
    assert len(PILOT_BUILTIN_SKILL_NAMES) == 10
