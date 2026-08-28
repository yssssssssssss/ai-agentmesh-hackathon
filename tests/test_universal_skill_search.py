from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.models import (
    SkillBinding,
    SkillDefinition,
    SkillSourceScope,
)
from agentmesh.seed import USER
from agentmesh.skill_runtime.planner import deterministic_intent
from agentmesh.skill_runtime.profiles import (
    ProfileError,
    load_capability_profile_record,
)
from agentmesh.skill_runtime.recommendation import (
    SkillRerankDecision,
    UniversalSkillSearchService,
    recommend_skill_directory,
    skill_capability_card,
)
from agentmesh.skill_runtime.retrieval import SkillCandidateRetriever
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tools import ensure_tool_seed_data

DRAFT_PROFILE_NAMES = {
    "analyze-satisfaction",
    "conversion-funnel-analysis",
    "design-abtest-analysis",
    "feature-adoption-analysis",
    "feedback-insight",
    "generate-persona",
    "industry-market-analysis",
    "journey-map",
    "research-screenshot-analyzer",
    "structure-interview-transcript",
    "synthesize-qualitative-insights",
    "usability-review",
}


def _profile_skill(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    name: str = "bounded-profile",
) -> SkillDefinition:
    skill_dir = tmp_path / name
    profile_dir = skill_dir / "agents"
    profile_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Bounded profile\n", encoding="utf-8")
    skill = SkillDefinition(
        id=f"skill_{name}",
        name=name,
        title="Bounded profile",
        description="Profile boundary fixture",
        instructions="# Bounded profile",
        source_path=str(skill_file),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="a" * 64,
    )
    document = {
        "skill_id": "auto",
        "skill_version": "1",
        "skill_content_hash": skill.content_hash,
        "profile_version": "1",
        "display_description": "A bounded public profile",
        "primary_stage": "pre_design",
        "lifecycle_tags": ["pre_design"],
        "capability_type": "analysis",
        "input_kinds": ["research_material"],
        "output_kinds": ["research_insight"],
        "examples": ["提炼研究洞察"],
        "negative_examples": ["生成调查问卷"],
        "required_capabilities": [],
        "task_types": ["research-analysis"],
        "archetypes": ["analysis"],
        "required_tools": [],
        "required_resources": [],
        "review_state": "draft",
        "side_effect": "draft",
        "planner_eligible": False,
        **payload,
    }
    (profile_dir / "agentmesh.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return skill


def _catalog(tmp_path: Path, configure_pilot_wiki) -> tuple[SQLiteStore, SkillCatalogService]:
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "universal-search.sqlite3")
    ensure_tool_seed_data(repository, granted_by="universal-search-test")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    return repository, catalog


def test_profile_record_preserves_file_review_state_without_granting_planner_eligibility(tmp_path) -> None:
    skill = _profile_skill(tmp_path, {})

    loaded = load_capability_profile_record(skill)

    assert loaded.review_state == "draft"
    assert loaded.profile.planner_eligible is False
    assert loaded.profile.skill_id == skill.id


def test_explicit_draft_state_disables_a_legacy_pilot_profile(tmp_path) -> None:
    skill = _profile_skill(
        tmp_path,
        {"review_state": "draft", "planner_eligible": True},
        name="generate-research-plan",
    )

    loaded = load_capability_profile_record(skill)

    assert loaded.declared_planner_eligible is True
    assert loaded.profile.planner_eligible is False


@pytest.mark.parametrize(
    "override",
    [
        {"lifecycle_tags": ["pre_design"] * 9},
        {"input_kinds": [f"input_{index}" for index in range(21)]},
        {"examples": [f"example_{index}" for index in range(9)]},
        {"examples": ["x" * 301]},
        {"required_resources": ["x" * 241]},
    ],
)
def test_profile_contract_rejects_cardinality_and_item_length_overflow(
    tmp_path,
    override: dict[str, object],
) -> None:
    skill = _profile_skill(tmp_path, override)

    with pytest.raises(ProfileError, match="profile_invalid"):
        load_capability_profile_record(skill)


def test_profile_contract_rejects_raw_sidecar_over_32_kib(tmp_path) -> None:
    skill = _profile_skill(tmp_path, {})
    profile_path = Path(skill.source_path).parent / "agents" / "agentmesh.yaml"
    with profile_path.open("a", encoding="utf-8") as stream:
        stream.write("#" + "x" * (32 * 1024) + "\n")

    with pytest.raises(ProfileError, match="profile_too_large"):
        load_capability_profile_record(skill)


def test_public_capability_card_is_bounded_and_omits_instructions_and_private_resources(tmp_path) -> None:
    skill = _profile_skill(
        tmp_path,
        {
            "review_state": "approved",
            "planner_eligible": True,
            "required_tools": ["web_research"],
            "required_resources": ["private/internal/path.md"],
        },
    )
    loaded = load_capability_profile_record(skill)

    card = skill_capability_card(skill, loaded.profile)
    encoded = canonical_json_bytes(card)

    assert len(encoded) <= 4 * 1024
    assert card["required_tools"] == ["web_research"]
    assert "instructions" not in card
    assert "required_resources" not in card
    assert "private/internal/path.md" not in encoded.decode("utf-8")


def test_profile_contract_rejects_capability_card_over_four_kib(tmp_path) -> None:
    values = [f"kind_{index}_" + "x" * 110 for index in range(20)]
    skill = _profile_skill(
        tmp_path,
        {
            "input_kinds": values,
            "output_kinds": values,
            "required_tools": values,
        },
    )
    with pytest.raises(ProfileError, match="profile_invalid"):
        load_capability_profile_record(skill)


def test_directory_reranker_does_not_receive_draft_profile_fields(tmp_path) -> None:
    skill = _profile_skill(tmp_path, {})
    repository = SQLiteStore(tmp_path / "draft-card-leak.sqlite3")
    repository.save_skill_definition(skill, defer_vector=True)
    repository.save_skill_capability_profile(
        load_capability_profile_record(skill).profile,
        defer_vector=True,
    )
    captured: list[dict[str, object]] = []

    async def rerank(task, cards, limit, model):  # noqa: ANN001
        del task, limit, model
        captured.extend(cards)
        return SkillRerankDecision(skill_ids=[skill.id])

    asyncio.run(
        recommend_skill_directory(
            "先分析 profile boundary signal，然后输出结论",
            [skill],
            repository=repository,
            limit=1,
            model=object(),  # type: ignore[arg-type]
            rerank=rerank,
        )
    )

    assert len(captured) == 1
    assert "capability_type" not in captured[0]
    assert "required_tools" not in captured[0]


def test_phase1a_catalog_loads_twelve_complete_draft_profiles_without_expanding_legacy_planner(
    tmp_path,
    configure_pilot_wiki,
) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)
    draft_names: set[str] = set()
    draft_cards: list[dict[str, object]] = []
    legacy_planner_names: set[str] = set()

    for skill, _enabled in catalog.list_for_agent(USER.personal_agent_id):
        profile_path = Path(skill.source_path).parent / "agents" / "agentmesh.yaml"
        if not profile_path.is_file():
            continue
        loaded = load_capability_profile_record(skill)
        if loaded.review_state == "draft":
            draft_names.add(skill.name)
            draft_cards.append(skill_capability_card(skill, loaded.profile))
        if loaded.profile.planner_eligible:
            legacy_planner_names.add(skill.name)

    assert draft_names == DRAFT_PROFILE_NAMES
    assert len(canonical_json_bytes(draft_cards)) <= 32 * 1024
    assert len(legacy_planner_names) == 10
    draft_skill = catalog.get_by_name("journey-map", USER.personal_agent_id)
    assert draft_skill is not None
    assert repository.get_vector_state(
        "skill_capability_profiles",
        draft_skill.id,
    ) is None
    public_item = catalog.to_chat_skill(draft_skill)
    assert public_item["planner_eligible"] is False
    assert "capability_type" not in public_item
    assert "input_kinds" not in public_item
    assert "output_kinds" not in public_item
    assert not [diagnostic for diagnostic in catalog.diagnostics if diagnostic.level == "error"]


def test_catalog_does_not_queue_draft_profile_text_for_external_embedding(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def embed(text: str, **_kwargs) -> list[float]:
        captured.append(text)
        return [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    repository = SQLiteStore(tmp_path / "draft-profile-vector.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    worker = repository._skill_vector_thread
    assert worker is not None
    worker.join(timeout=10)

    draft = next(
        skill
        for skill, _enabled in catalog.list_for_agent(USER.personal_agent_id)
        if skill.name == "journey-map"
    )
    assert repository.get_vector_state("skill_capability_profiles", draft.id) is None
    assert not any(text.startswith("journey-map ") for text in captured)


def test_universal_search_ranks_draft_profiles_only_in_explicit_offline_mode(
    tmp_path,
    configure_pilot_wiki,
) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)
    service = UniversalSkillSearchService(repository, catalog)
    intent = deterministic_intent("把多场用户访谈横向归纳成主题、结论和洞察")

    trusted = service.search(USER, intent)
    offline = service.search_for_evaluation(USER, intent)

    assert "synthesize-qualitative-insights" not in {
        candidate.skill_name for candidate in trusted.ranked_matches
    }
    assert offline.ranked_matches[0].skill_name == "synthesize-qualitative-insights"
    assert offline.ranked_matches[0].ready is False
    assert "profile_unapproved" in offline.ranked_matches[0].diagnostics
    assert offline.selectable_candidates == ()


def test_universal_search_removes_disabled_binding_before_offline_ranking(
    tmp_path,
    configure_pilot_wiki,
) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)
    target = catalog.get_by_name("journey-map", USER.personal_agent_id)
    assert target is not None
    repository.save_skill_binding(
        SkillBinding(
            id="disable_draft_journey_map",
            agent_id=USER.personal_agent_id,
            skill_id=target.id,
            enabled=False,
            granted_by=USER.id,
        )
    )

    result = UniversalSkillSearchService(repository, catalog).search_for_evaluation(
        USER,
        deterministic_intent("根据访谈材料画用户旅程图和情绪曲线"),
    )

    assert "journey-map" not in {candidate.skill_name for candidate in result.ranked_matches}


def test_universal_search_ignores_skill_instructions_as_retrieval_text(
    tmp_path,
    configure_pilot_wiki,
) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)
    target = catalog.get_by_name("generate-persona", USER.personal_agent_id)
    assert target is not None
    catalog._skills[target.name] = target.model_copy(
        update={"instructions": target.instructions + "\nUNIQUE_PRIVATE_INSTRUCTION_BEACON"}
    )

    result = UniversalSkillSearchService(repository, catalog).search_for_evaluation(
        USER,
        deterministic_intent("UNIQUE_PRIVATE_INSTRUCTION_BEACON"),
    )

    assert result.ranked_matches == ()


def test_universal_search_can_select_an_approved_builtin_profile(tmp_path) -> None:
    skill = _profile_skill(
        tmp_path,
        {"review_state": "approved", "planner_eligible": True},
    )
    repository = SQLiteStore(tmp_path / "approved-universal.sqlite3")
    repository.save_skill_definition(skill, defer_vector=True)
    repository.save_skill_capability_profile(
        load_capability_profile_record(skill).profile,
        defer_vector=True,
    )
    catalog = SkillCatalogService(repository)
    catalog._skills = {skill.name: skill}

    denied_service = UniversalSkillSearchService(repository, catalog)
    denied = denied_service.search(
        USER,
        deterministic_intent("请提炼这批研究材料里的用户洞察"),
    )
    untrusted_offline = denied_service.search_for_evaluation(
        USER,
        deterministic_intent("请提炼这批研究材料里的用户洞察"),
    )
    result = UniversalSkillSearchService(
        repository,
        catalog,
        profile_trust=lambda _skill, _loaded: True,
    ).search(
        USER,
        deterministic_intent("请提炼这批研究材料里的用户洞察"),
    )

    assert denied.ranked_matches == ()
    assert untrusted_offline.ranked_matches[0].diagnostics == [
        "skill_profile_trust_unavailable"
    ]
    assert [candidate.skill_name for candidate in result.selectable_candidates] == [
        skill.name
    ]
    assert result.searchable_count == 1


@pytest.mark.parametrize(
    "query",
    [
        "帮我查询明天的天气",
        "预订一张去上海的机票",
        "给我推荐一道晚餐菜谱",
        "预测下周黄金价格",
        "帮我生成一份晚餐菜谱",
        "Generate a dinner recipe",
    ],
)
def test_universal_search_returns_no_match_for_out_of_domain_requests(
    tmp_path,
    configure_pilot_wiki,
    query: str,
) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)

    result = UniversalSkillSearchService(repository, catalog).search_for_evaluation(
        USER,
        deterministic_intent(query),
    )

    assert result.ranked_matches == ()


def test_universal_search_excludes_non_builtin_profiles_before_ranking(tmp_path) -> None:
    skill = _profile_skill(
        tmp_path,
        {"review_state": "approved", "planner_eligible": True},
    ).model_copy(update={"source_scope": SkillSourceScope.WORKSPACE})
    repository = SQLiteStore(tmp_path / "workspace-universal.sqlite3")
    repository.save_skill_definition(skill, defer_vector=True)
    repository.save_skill_capability_profile(
        load_capability_profile_record(skill).profile,
        defer_vector=True,
    )
    catalog = SkillCatalogService(repository)
    catalog._skills = {skill.name: skill}

    result = UniversalSkillSearchService(repository, catalog).search_for_evaluation(
        USER,
        deterministic_intent("请提炼这批研究材料里的用户洞察"),
    )

    assert result.ranked_matches == ()
    assert result.security_filtered_count == 1


def test_legacy_agent_run_retriever_still_exposes_only_ten_pilot_profiles(
    tmp_path,
    configure_pilot_wiki,
) -> None:
    repository, catalog = _catalog(tmp_path, configure_pilot_wiki)

    candidates, _diagnostics = SkillCandidateRetriever(repository, catalog).recommend(
        USER,
        deterministic_intent("根据访谈材料提炼用户洞察"),
    )

    assert len({candidate.skill_name for candidate in candidates}) <= 10
    assert not ({candidate.skill_name for candidate in candidates} & DRAFT_PROFILE_NAMES)
