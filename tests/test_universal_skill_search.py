from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

import agentmesh.skill_runtime.recommendation as recommendation_module
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.models import (
    AgentToolGrant,
    SkillBinding,
    SkillDefinition,
    SkillIntent,
    SkillSourceScope,
    ToolDefinition,
)
from agentmesh.seed import USER
from agentmesh.skill_runtime.planner import deterministic_intent
from agentmesh.skill_runtime.profiles import (
    ProfileError,
    load_capability_profile_record,
)
from agentmesh.skill_runtime.readiness import ToolHealthProbeCoordinator
from agentmesh.skill_runtime.recommendation import (
    SkillRerankDecision,
    UniversalSkillSearchService,
    build_candidate_snapshot,
    candidate_snapshot_public_projection,
    recommend_skill_directory,
    revalidate_candidate_snapshot,
    skill_capability_card,
)
from agentmesh.skill_runtime.retrieval import SkillCandidateRetriever
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.task_routing.catalog import TaskCatalogV2, load_universal_task_catalog
from agentmesh.task_routing.contracts import ScenarioRoute, TaskRoute, TaskRoutingResult
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


@dataclass(frozen=True)
class _HealthDescriptor:
    implementation_id: str
    implementation_version: str
    health_state: str


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


def _controlled_universal_service(
    tmp_path: Path,
    profiles: list[tuple[str, list[str], str]],
) -> tuple[UniversalSkillSearchService, list[SkillDefinition], list[list[str]]]:
    repository = SQLiteStore(tmp_path / "controlled-universal.sqlite3")
    catalog = SkillCatalogService(repository)
    skills: list[SkillDefinition] = []
    for name, output_kinds, review_state in profiles:
        skill = _profile_skill(
            tmp_path,
            {
                "review_state": review_state,
                "planner_eligible": review_state == "approved",
                "display_description": f"Capability for {' '.join(output_kinds)}"[:100],
                "output_kinds": output_kinds,
                "examples": [f"Need {' '.join(output_kinds)}"],
                "negative_examples": ["Unrelated request"],
            },
            name=name,
        )
        repository.save_skill_definition(skill, defer_vector=True)
        repository.save_skill_capability_profile(
            load_capability_profile_record(skill).profile,
            defer_vector=True,
        )
        skills.append(skill)
    catalog._skills = {skill.name: skill for skill in skills}
    ranker_calls: list[list[str]] = []

    def ranker(queries: list[str], _allowed_ids: set[str]):  # noqa: ANN202
        ranker_calls.append(queries)
        ordered_ids = [skill.id for skill in skills]
        return [([], ordered_ids, []) for _query in queries]

    service = UniversalSkillSearchService(
        repository,
        catalog,
        profile_trust=lambda _skill, _loaded: True,
        profile_ranker=ranker,
    )
    return service, skills, ranker_calls


def _remote_tool_universal_service(
    tmp_path: Path,
    output_kinds: list[str],
    *,
    probe,
) -> tuple[UniversalSkillSearchService, list[str]]:  # noqa: ANN001
    repository = SQLiteStore(tmp_path / "remote-tool-universal.sqlite3")
    catalog = SkillCatalogService(repository)
    skills: list[SkillDefinition] = []
    tool_names: list[str] = []
    for index, output_kind in enumerate(output_kinds):
        tool_name = f"remote_tool_{index}"
        tool_names.append(tool_name)
        skill = _profile_skill(
            tmp_path,
            {
                "review_state": "approved",
                "planner_eligible": True,
                "display_description": f"Capability for {output_kind}",
                "output_kinds": [output_kind],
                "examples": [f"Need {output_kind}"],
                "negative_examples": ["Unrelated request"],
                "required_tools": [tool_name],
            },
            name=f"remote-candidate-{index}",
        )
        repository.save_skill_definition(skill, defer_vector=True)
        repository.save_skill_capability_profile(
            load_capability_profile_record(skill).profile,
            defer_vector=True,
        )
        definition = repository.save_tool_definition(
            ToolDefinition(
                id=f"tool_remote_{index}",
                name=tool_name,
                description="Remote test tool",
                category="test",
                implementation_id=f"implementation-{index}",
                implementation_version="1",
            )
        )
        repository.save_agent_tool_grant(
            AgentToolGrant(
                id=f"grant_remote_{index}",
                agent_id=USER.personal_agent_id,
                tool_id=definition.id,
                granted_by=USER.id,
            )
        )
        skills.append(skill)
    catalog._skills = {skill.name: skill for skill in skills}

    def ranker(queries: list[str], _allowed_ids: set[str]):  # noqa: ANN202
        ordered_ids = [skill.id for skill in skills]
        return [([], ordered_ids, []) for _query in queries]

    return (
        UniversalSkillSearchService(
            repository,
            catalog,
            profile_trust=lambda _skill, _loaded: True,
            profile_ranker=ranker,
            tool_health=ToolHealthProbeCoordinator(probe),
        ),
        tool_names,
    )


def _routing_result_for(scenario_id: str) -> tuple[TaskRoutingResult, TaskCatalogV2]:
    catalog = load_universal_task_catalog()
    scenario = catalog.get_scenario(scenario_id)
    assert scenario is not None
    return (
        TaskRoutingResult(
            catalog_version=catalog.manifest.catalog_version,
            catalog_hash=catalog.manifest.catalog_hash,
            task=TaskRoute(task_id=scenario.parent_task, confidence="high"),
            scenario=ScenarioRoute(scenario_id=scenario.id, confidence="high"),
        ),
        catalog,
    )


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


def test_catalog_loads_all_draft_profiles_without_expanding_legacy_planner(
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

    assert draft_names >= DRAFT_PROFILE_NAMES
    assert len(draft_names) == 74
    assert all(len(canonical_json_bytes(card)) <= 4 * 1024 for card in draft_cards)
    largest_cards = sorted(draft_cards, key=lambda card: len(canonical_json_bytes(card)), reverse=True)[:12]
    assert len(canonical_json_bytes(largest_cards)) <= 32 * 1024
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
    coverage_evaluation = service.search_for_coverage_evaluation(USER, intent)

    assert "synthesize-qualitative-insights" not in {
        candidate.skill_name for candidate in trusted.ranked_matches
    }
    assert offline.ranked_matches[0].skill_name == "synthesize-qualitative-insights"
    assert offline.ranked_matches[0].ready is False
    assert "profile_unapproved" in offline.ranked_matches[0].diagnostics
    assert offline.selectable_candidates == ()
    assert coverage_evaluation.selectable_candidates[0].skill_name == "synthesize-qualitative-insights"


def test_universal_search_rejects_unknown_deliverable_before_ranking(tmp_path) -> None:
    service, _skills, ranker_calls = _controlled_universal_service(
        tmp_path,
        [("known-candidate", ["known_output"], "approved")],
    )

    result = service.search(
        USER,
        SkillIntent(goal="Need an unknown output", deliverables=["invented_output"]),
    )

    assert result.outcome_code == "unsupported_requirement"
    assert result.ranked_matches == ()
    assert ranker_calls == []


def test_pure_synthesis_requirement_does_not_create_a_fake_coverage_atom(tmp_path) -> None:
    service, _skills, _calls = _controlled_universal_service(
        tmp_path,
        [("synthesis-input-candidate", ["research_report"], "approved")],
    )

    result = service.search(
        USER,
        SkillIntent(goal="Summarize the available findings", deliverables=["executive_summary"]),
    )

    assert result.outcome_code == "ok"
    assert result.required_coverage_atoms == ()
    assert result.required_synthesis_output_ids == ("executive_summary",)
    assert result.coverage_witness_skill_ids == ()
    assert result.selectable_candidates


def test_universal_search_builds_assignment_aware_coverage_witnesses(tmp_path) -> None:
    service, skills, ranker_calls = _controlled_universal_service(
        tmp_path,
        [
            ("metrics-candidate", ["experience_metrics"], "approved"),
            ("measurement-candidate", ["measurement_plan"], "approved"),
        ],
    )
    routing_result, task_catalog = _routing_result_for("metrics-validation")

    result = service.search(
        USER,
        SkillIntent(goal="建立体验指标并制定验证方案", deliverables=["experience_metrics"]),
        routing_result=routing_result,
        task_catalog=task_catalog,
    )

    assert result.outcome_code == "ok"
    assert len(ranker_calls) == 1
    assert len(result.required_coverage_atoms) == 5
    assert result.plannable_coverage_atom_ids == tuple(atom.id for atom in result.required_coverage_atoms)
    assert set(result.coverage_witness_skill_ids) == {skill.id for skill in skills}
    assert {candidate.coverage_witness_scenario_id for candidate in result.selectable_candidates} == {
        "metrics-validation"
    }
    assert not result.capability_gaps


def test_candidate_snapshot_freezes_ranked_identity_and_public_projection(tmp_path) -> None:
    service, skills, _calls = _controlled_universal_service(
        tmp_path,
        [
            ("metrics-candidate", ["experience_metrics"], "approved"),
            ("measurement-candidate", ["measurement_plan"], "approved"),
        ],
    )
    routing_result, task_catalog = _routing_result_for("metrics-validation")
    result = service.search(
        USER,
        SkillIntent(goal="建立体验指标并制定验证方案", deliverables=["experience_metrics"]),
        routing_result=routing_result,
        task_catalog=task_catalog,
    )

    snapshot = build_candidate_snapshot(result, service._repository)
    public = candidate_snapshot_public_projection(snapshot)

    assert [candidate.skill_id for candidate in snapshot.candidates] == [
        candidate.skill_id for candidate in result.selectable_candidates
    ]
    assert set(snapshot.coverage_witness_skill_ids) == {skill.id for skill in skills}
    assert snapshot.content_hash
    serialized = canonical_json_bytes(public)
    assert b"evidence_path_witnesses" not in serialized
    assert b"tool_implementation_id" not in serialized
    assert b"resource_or_adapter_identity" not in serialized
    with pytest.raises(ValueError, match="content_hash"):
        type(snapshot).model_validate(
            {**snapshot.model_dump(mode="python"), "content_hash": "0" * 64}
        )


def test_candidate_snapshot_freezes_evidence_path_without_exposing_it_publicly(tmp_path) -> None:
    skill = _profile_skill(
        tmp_path,
        {
            "review_state": "approved",
            "planner_eligible": True,
            "required_tools": ["web_research"],
        },
        name="evidence-candidate",
    )
    repository = SQLiteStore(tmp_path / "evidence-snapshot.sqlite3")
    ensure_tool_seed_data(repository, granted_by="evidence-snapshot")
    repository.save_skill_definition(skill, defer_vector=True)
    repository.save_skill_capability_profile(load_capability_profile_record(skill).profile, defer_vector=True)
    catalog = SkillCatalogService(repository)
    catalog._skills = {skill.name: skill}
    definition = next(tool for tool in repository.tool_definitions if tool.name == "web_research")
    assert definition.implementation_id is not None
    health = ToolHealthProbeCoordinator(
        lambda _name: _HealthDescriptor(
            definition.implementation_id or "",
            definition.implementation_version,
            "healthy",
        )
    )
    service = UniversalSkillSearchService(
        repository,
        catalog,
        profile_trust=lambda _skill, _loaded: True,
        profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
        tool_health=health,
    )

    result = service.search(
        USER,
        SkillIntent(
            goal="Research this topic with external evidence",
            deliverables=["research_insight"],
            external_evidence_required=True,
        ),
    )
    snapshot = build_candidate_snapshot(result, repository)
    public = candidate_snapshot_public_projection(snapshot)

    assert result.outcome_code == "ok"
    assert snapshot.candidates[0].evidence_path_witnesses
    serialized = canonical_json_bytes(public)
    assert b"evidence_path_witnesses" not in serialized
    assert definition.implementation_id.encode() not in serialized

    revalidated = revalidate_candidate_snapshot(
        snapshot=snapshot,
        repository=repository,
        catalog=catalog,
        user=USER,
        intent=SkillIntent(
            goal="Research this topic with external evidence",
            deliverables=["research_insight"],
            external_evidence_required=True,
        ),
        profile_trust=lambda _skill, _loaded: True,
    )
    assert [candidate.skill_id for candidate in revalidated] == [skill.id]
    repository.save_tool_definition(
        definition.model_copy(update={"implementation_version": "2"})
    )
    with pytest.raises(ValueError, match="candidate_snapshot_stale"):
        revalidate_candidate_snapshot(
            snapshot=snapshot,
            repository=repository,
            catalog=catalog,
            user=USER,
            intent=SkillIntent(
                goal="Research this topic with external evidence",
                deliverables=["research_insight"],
                external_evidence_required=True,
            ),
            profile_trust=lambda _skill, _loaded: True,
        )

    stale_body = snapshot.model_dump(mode="python", exclude={"content_hash"})
    stale_body["required_coverage_atoms"] = [
        atom.model_copy(update={"evidence_policy_version": "stale"})
        if atom.kind == "evidence"
        else atom
        for atom in snapshot.required_coverage_atoms
    ]
    stale_policy_snapshot = type(snapshot)(
        **stale_body,
        content_hash=canonical_json_sha256(stale_body),
    )
    with pytest.raises(ValueError, match="evidence_policy_changed"):
        revalidate_candidate_snapshot(
            snapshot=stale_policy_snapshot,
            repository=repository,
            catalog=catalog,
            user=USER,
            intent=SkillIntent(goal="Research", external_evidence_required=True),
            profile_trust=lambda _skill, _loaded: True,
        )


def test_snapshot_revalidation_limits_dynamic_readiness_to_selected_candidates(
    tmp_path,
    monkeypatch,
) -> None:
    service, skills, _calls = _controlled_universal_service(
        tmp_path,
        [
            ("selected-candidate", ["analysis_result"], "approved"),
            ("unused-candidate", ["analysis_result"], "approved"),
        ],
    )
    intent = SkillIntent(goal="Need analysis_result", deliverables=["analysis_result"])
    result = service.search(USER, intent)
    assert len(result.selectable_candidates) == 2
    snapshot = build_candidate_snapshot(result, service._repository)
    selected_id = skills[0].id
    unused_id = skills[1].id

    def readiness(_repository, _user, skill, *_args, **_kwargs):  # noqa: ANN001, ANN202
        return ["required_tool_not_granted"] if skill.id == unused_id else []

    monkeypatch.setattr(
        recommendation_module,
        "_universal_readiness_diagnostics",
        readiness,
    )

    candidates = revalidate_candidate_snapshot(
        snapshot=snapshot,
        repository=service._repository,
        catalog=service._catalog,
        user=USER,
        intent=intent,
        profile_trust=lambda _skill, _loaded: True,
        dynamic_skill_ids={selected_id},
    )
    assert [candidate.skill_id for candidate in candidates] == [
        candidate.skill_id for candidate in snapshot.candidates
    ]

    with pytest.raises(ValueError, match="required_tool_not_granted"):
        revalidate_candidate_snapshot(
            snapshot=snapshot,
            repository=service._repository,
            catalog=service._catalog,
            user=USER,
            intent=intent,
            profile_trust=lambda _skill, _loaded: True,
        )


def test_universal_search_keeps_blocked_matches_out_of_ready_shortlist_and_builds_gaps(tmp_path) -> None:
    service, _skills, _calls = _controlled_universal_service(
        tmp_path,
        [
            ("ready-metrics", ["experience_metrics"], "approved"),
            ("draft-measurement", ["measurement_plan"], "draft"),
        ],
    )
    routing_result, task_catalog = _routing_result_for("metrics-validation")

    result = service.search_for_evaluation(
        USER,
        SkillIntent(goal="建立体验指标并制定验证方案", deliverables=["experience_metrics"]),
        routing_result=routing_result,
        task_catalog=task_catalog,
    )

    assert result.outcome_code == "ok"
    assert [candidate.skill_name for candidate in result.selectable_candidates] == ["ready-metrics"]
    assert [candidate.skill_name for candidate in result.blocked_matches] == ["draft-measurement"]
    assert {gap.requirement_id for gap in result.capability_gaps} == {
        "scenario:metrics-validation:output:validation_plan",
        "scenario:metrics-validation:output:observation_window",
    }


def test_universal_search_enforces_six_skill_coverage_witness_budget(tmp_path) -> None:
    output_kinds = [f"output_{index}" for index in range(7)]
    service, _skills, _calls = _controlled_universal_service(
        tmp_path,
        [(f"coverage-candidate-{index}", [output_kind], "approved") for index, output_kind in enumerate(output_kinds)],
    )

    result = service.search(
        USER,
        SkillIntent(goal="Produce all required outputs", deliverables=output_kinds),
    )

    assert result.outcome_code == "coverage_search_exhausted"
    assert len(result.coverage_witness_skill_ids) == 6
    assert "coverage_search_exhausted" in result.diagnostics
    assert any(item.startswith("uncovered_requirement:") for item in result.diagnostics)


def test_universal_search_accepts_twenty_four_ordered_coverage_atoms(tmp_path) -> None:
    output_kinds = [f"output_{index}" for index in range(19)]
    service, _skills, ranker_calls = _controlled_universal_service(
        tmp_path,
        [("budget-candidate", output_kinds, "approved")],
    )
    routing_result, task_catalog = _routing_result_for("trend-change-identification")

    result = service.search(
        USER,
        SkillIntent(goal="Produce every output", deliverables=output_kinds),
        routing_result=routing_result,
        task_catalog=task_catalog,
    )

    assert result.outcome_code == "ok"
    assert len(result.required_coverage_atoms) == 24
    assert len({atom.id for atom in result.required_coverage_atoms}) == 24
    assert len(ranker_calls) == 1


def test_universal_search_rejects_twenty_fifth_coverage_atom_before_ranking(tmp_path) -> None:
    output_kinds = [f"output_{index}" for index in range(20)]
    service, _skills, ranker_calls = _controlled_universal_service(
        tmp_path,
        [("budget-candidate", output_kinds, "approved")],
    )
    routing_result, task_catalog = _routing_result_for("trend-change-identification")

    result = service.search(
        USER,
        SkillIntent(goal="Produce every output", deliverables=output_kinds),
        routing_result=routing_result,
        task_catalog=task_catalog,
    )

    assert result.outcome_code == "requirement_budget_exceeded"
    assert result.ranked_matches == ()
    assert ranker_calls == []


def test_one_skill_cannot_cover_two_scenario_assignments(tmp_path) -> None:
    service, _skills, _calls = _controlled_universal_service(
        tmp_path,
        [("research-plan-candidate", ["research_plan"], "approved")],
    )
    routing_result, task_catalog = _routing_result_for("metrics-validation")
    routing_result.scenario.supporting_scenarios = ["trend-change-identification"]

    result = service.search(
        USER,
        SkillIntent(goal="Plan validation for metrics and trends", deliverables=["research_plan"]),
        routing_result=routing_result,
        task_catalog=task_catalog,
    )

    assert result.outcome_code == "coverage_search_exhausted"
    assert result.coverage_witness_skill_ids
    uncovered = [item for item in result.diagnostics if item.startswith("uncovered_requirement:")]
    assert len(uncovered) == 1
    assert result.selectable_candidates[0].coverage_witness_scenario_id in {
        "metrics-validation",
        "trend-change-identification",
    }


def test_blocked_matches_do_not_consume_the_twelve_ready_slots(tmp_path) -> None:
    profiles = [("highest-blocked", ["unrelated_output"], "draft")]
    profiles.extend(
        (f"ready-candidate-{index}", ["target_output"], "approved")
        for index in range(12)
    )
    service, _skills, _calls = _controlled_universal_service(tmp_path, profiles)

    result = service.search_for_evaluation(
        USER,
        SkillIntent(goal="Need a target output", deliverables=["target_output"]),
    )

    assert result.outcome_code == "ok"
    assert len(result.selectable_candidates) == 12
    assert len(result.blocked_matches) == 1
    assert result.blocked_matches[0].skill_name == "highest-blocked"


def test_tool_probe_budget_does_not_fail_when_ready_coverage_is_already_known(tmp_path) -> None:
    output_kinds = ["target_output", *[f"unrelated_{index}" for index in range(8)]]

    def probe(tool_name: str) -> _HealthDescriptor:
        index = tool_name.removeprefix("remote_tool_")
        return _HealthDescriptor(f"implementation-{index}", "1", "healthy")

    service, _tool_names = _remote_tool_universal_service(tmp_path, output_kinds, probe=probe)

    result = service.search(
        USER,
        SkillIntent(goal="Need target output", deliverables=["target_output"]),
    )

    assert result.outcome_code == "ok"
    assert result.selectable_candidates
    assert all("readiness_unprobed" not in candidate.diagnostics for candidate in result.blocked_matches)


def test_tool_probe_budget_fails_when_required_coverage_depends_on_unprobed_tail(tmp_path) -> None:
    output_kinds = [f"target_{index}" for index in range(9)]

    def probe(tool_name: str) -> _HealthDescriptor:
        index = tool_name.removeprefix("remote_tool_")
        return _HealthDescriptor(f"implementation-{index}", "1", "healthy")

    service, _tool_names = _remote_tool_universal_service(tmp_path, output_kinds, probe=probe)

    result = service.search(
        USER,
        SkillIntent(goal="Need every target output", deliverables=output_kinds),
    )

    assert result.outcome_code == "readiness_probe_budget_exceeded"
    assert "readiness_probe_budget_exceeded" in result.diagnostics
    assert all("readiness_unprobed" not in candidate.diagnostics for candidate in result.blocked_matches)


def test_tool_health_timeout_is_a_confirmed_blocked_match(tmp_path) -> None:
    def probe(_tool_name: str):  # noqa: ANN202
        raise TimeoutError("probe timed out")

    service, _tool_names = _remote_tool_universal_service(tmp_path, ["target_output"], probe=probe)

    result = service.search(
        USER,
        SkillIntent(goal="Need target output", deliverables=["target_output"]),
    )

    assert result.outcome_code == "no_executable_skill"
    assert result.selectable_candidates == ()
    assert result.blocked_matches[0].diagnostics == ["tool_health_timeout"]


def test_universal_search_marks_missing_declared_resource_as_blocked(tmp_path) -> None:
    skill = _profile_skill(
        tmp_path,
        {
            "review_state": "approved",
            "planner_eligible": True,
            "output_kinds": ["research_insight"],
            "required_resources": ["wiki.corpus"],
        },
        name="resource-candidate",
    )
    repository = SQLiteStore(tmp_path / "resource-universal.sqlite3")
    repository.save_skill_definition(skill, defer_vector=True)
    repository.save_skill_capability_profile(load_capability_profile_record(skill).profile, defer_vector=True)
    catalog = SkillCatalogService(repository)
    catalog._skills = {skill.name: skill}

    result = UniversalSkillSearchService(
        repository,
        catalog,
        profile_trust=lambda _skill, _loaded: True,
        profile_ranker=lambda queries, _ids: [([], [skill.id], []) for _query in queries],
    ).search(
        USER,
        SkillIntent(goal="Need a research insight", deliverables=["research_insight"]),
    )

    assert result.outcome_code == "no_executable_skill"
    assert result.blocked_matches[0].diagnostics == ["public_resource_unavailable"]


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
