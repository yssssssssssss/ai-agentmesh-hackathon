from __future__ import annotations

import pytest

from agentmesh.models import AgentToolGrant, SkillNodeResult, SkillPlan, SkillPlanNode, SkillResultSource
from agentmesh.seed import USER
from agentmesh.skill_runtime.plan_validation import validate_draft
from agentmesh.skill_runtime.planner import deterministic_intent, route_skill_draft
from agentmesh.skill_runtime.retrieval import SkillCandidateRetriever
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.skill_runtime.synthesis import deterministic_synthesis
from agentmesh.store import SQLiteStore
from agentmesh.task_routing.catalog import load_default_task_catalog
from agentmesh.task_routing.completion import evaluate_plan_completion
from agentmesh.task_routing.contracts import InputDecision, RoutingConfidence
from agentmesh.task_routing.router import TaskScenarioRouter, validate_routing_result
from agentmesh.tools import ensure_tool_seed_data


@pytest.mark.parametrize(
    ("scenario_id", "prompt"),
    [
        ("trend-change-identification", "最近有什么变化值得关注？"),
        ("competitor-benchmark-research", "帮我看看竞品怎么做"),
        ("opportunity-direction-evaluation", "这些机会哪个值得做？"),
        ("user-material-synthesis", "帮我整理这些用户资料"),
        ("user-segmentation", "用户可以分成几类？"),
        ("user-journey-insight", "帮我画用户旅程"),
        ("experience-walkthrough", "帮我走查这个页面"),
        ("feedback-issue-clustering", "这些反馈能归成几类？"),
        ("data-behavior-diagnosis", "转化异常帮我诊断一下"),
        ("root-cause-analysis", "这个问题根因是什么？"),
        ("solution-generation", "这个问题怎么改？"),
        ("solution-comparison", "两个方案哪个好？"),
        ("strategy-synthesis", "帮我把这些结论整理成策略"),
        ("priority-roadmap", "哪些先做哪些后做？"),
        ("metrics-validation", "上线后看什么指标？"),
    ],
)
def test_routes_each_catalog_scenario_from_its_trigger(scenario_id: str, prompt: str) -> None:
    result, diagnostics = TaskScenarioRouter().route(prompt)

    assert result.scenario.scenario_id == scenario_id
    assert result.task.task_id == load_default_task_catalog().get_scenario(scenario_id).parent_task
    assert result.scenario.confidence == RoutingConfidence.HIGH
    assert "deterministic_task_router" in diagnostics


def test_compound_strategy_request_routes_parallel_upstream_work() -> None:
    request = (
        "请基于2025-2026年公开资料，研究宠物主粮在品牌App、宠物App、淘宝、京东和抖音中的用户心智，"
        "输出策略地图、心智模型、5条设计原则、机会点，以及P0/P1/P2行动。"
    )

    result, diagnostics = TaskScenarioRouter().route(request, project_summary="宠物消费体验研究")

    selected = {result.scenario.scenario_id, *result.scenario.supporting_scenarios}
    assert result.task.task_id == "define-strategy"
    assert result.task.secondary_tasks == ["find-direction", "understand-users"]
    assert result.task.execution_relation == "parallel_then_merge"
    assert {
        "competitor-benchmark-research",
        "user-journey-insight",
        "strategy-synthesis",
        "priority-roadmap",
    }.issubset(selected)
    assert result.context.domain == "宠物主粮"
    assert result.context.data_scope == "2025-2026"
    assert result.evidence_requirement.external_evidence_required is True
    assert result.evidence_requirement.minimum_sources == 5
    assert "external_evidence" in result.analysis_requirements
    assert {
        "strategy_map",
        "mental_model",
        "design_principles",
        "opportunity_list",
        "prioritized_actions",
    }.issubset(result.presentation_requirements)
    assert result.input_check.input_decision in {InputDecision.CONTINUE, InputDecision.DEGRADE}
    assert diagnostics[0] == "deterministic_task_router"


def test_mindset_strategy_panorama_routes_research_and_user_analysis() -> None:
    request = "创建一个调研任务，核心解决‘宠物心智的设计表达策略全景，包含：全链路业务品牌心智、品类特色心智、场域心智策略’"

    result, _ = TaskScenarioRouter().route(request)

    selected = {result.scenario.scenario_id, *result.scenario.supporting_scenarios}
    assert result.task.task_id == "define-strategy"
    assert result.scenario.confidence == RoutingConfidence.HIGH
    assert "competitor-benchmark-research" in selected
    assert "user-journey-insight" in selected
    assert "strategy-synthesis" in selected
    assert "mental_model" in result.presentation_requirements
    assert "strategy_map" in result.presentation_requirements
    assert result.evidence_requirement.external_evidence_required is True


def test_planned_skills_are_reported_but_not_executable() -> None:
    result, _ = TaskScenarioRouter().route("请评估这些机会点哪个值得做，并给出探索优先级。")

    assert "planned-opportunity-evaluation-skill" in result.skill_routing.planned_skills
    assert "planned-opportunity-evaluation-skill" not in result.skill_routing.default_skills
    assert "planned-opportunity-evaluation-skill" not in result.skill_routing.optional_skills


def test_unknown_request_requests_clarification_without_inventing_ids() -> None:
    catalog = load_default_task_catalog()

    result, diagnostics = TaskScenarioRouter(catalog).route("帮我看看")

    assert result.scenario.confidence == RoutingConfidence.LOW
    assert result.input_check.input_decision == InputDecision.CLARIFY
    assert catalog.get_task(result.task.task_id) is not None
    assert catalog.get_scenario(result.scenario.scenario_id) is not None
    assert "routing_low_confidence" in diagnostics


def test_high_risk_action_is_the_only_normal_human_confirmation_path() -> None:
    result, _ = TaskScenarioRouter().route("请直接上线这个方案并调整价格，给出优先级。")

    assert result.human_confirmation.required is True
    assert result.input_check.input_decision == InputDecision.HUMAN_CONFIRMATION


def test_read_only_draft_route_does_not_require_human_confirmation() -> None:
    result, _ = TaskScenarioRouter().route("帮我看看竞品怎么做，并总结标杆模式。")

    assert result.human_confirmation.required is False
    assert result.skill_routing.default_skills == ["ds-skill-competitor-strategy-analysis"]


def test_routing_result_validation_rejects_unknown_scenario() -> None:
    catalog = load_default_task_catalog()
    result, _ = TaskScenarioRouter(catalog).route("帮我看看竞品怎么做")
    invalid = result.model_copy(deep=True)
    invalid.scenario.scenario_id = "invented-scenario"

    with pytest.raises(ValueError, match="routing_primary_scenario_invalid"):
        validate_routing_result(invalid, catalog)


def test_legacy_skill_intent_keeps_analysis_and_presentation_separate(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "true")
    intent = deterministic_intent(
        "基于2025-2026年公开资料研究竞品和用户心智，输出策略地图、设计原则和P0/P1/P2。"
    )

    assert intent.external_evidence_required is True
    assert intent.deliverables != ["design_analysis"]
    assert "external_evidence" in intent.analysis_requirements
    assert "strategy-synthesis" in intent.analysis_requirements
    assert "strategy_map" in intent.presentation_requirements
    assert "design_principles" in intent.presentation_requirements
    assert "prioritized_actions" in intent.presentation_requirements


def test_route_constrained_candidates_build_compatible_dag(tmp_path, monkeypatch, configure_pilot_wiki) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "true")
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "route-plan.sqlite3")
    ensure_tool_seed_data(repository, granted_by="test")
    repository.save_agent_tool_grant(
        AgentToolGrant(agent_id=USER.personal_agent_id, tool_id="tool_web_research", granted_by="test")
    )
    skill_catalog = SkillCatalogService(repository)
    skill_catalog.reload()
    task_catalog = load_default_task_catalog()
    request = (
        "基于2025-2026年公开资料研究竞品和用户心智，"
        "输出策略地图、设计原则、机会点和P0/P1/P2。"
    )
    routing_result, _ = TaskScenarioRouter(task_catalog).route(request)
    intent = deterministic_intent(request)
    retriever = SkillCandidateRetriever(repository, skill_catalog)

    candidates, diagnostics = retriever.recommend_for_route(USER, intent, routing_result, task_catalog)
    draft = route_skill_draft(intent, candidates, routing_result, task_catalog)
    validate_draft(draft, candidates, intent=intent)

    names_by_id = {candidate.skill_id: candidate.skill_name for candidate in candidates}
    planned_names = [names_by_id[node.skill_id] for node in draft.nodes]
    assert "competitive-analysis" in planned_names
    assert "jobs-to-be-done" in planned_names
    assert "issue-prioritization" in planned_names
    competitive = next(node for node in draft.nodes if names_by_id[node.skill_id] == "competitive-analysis")
    prioritization = next(node for node in draft.nodes if names_by_id[node.skill_id] == "issue-prioritization")
    assert competitive.required_tool_names == ["web_research"]
    assert competitive.parallel_group == "upstream_1"
    assert prioritization.depends_on
    assert "strategy_map" in draft.output_contract
    assert any(item.startswith("runtime_skill_unbound:") for item in diagnostics)


def test_route_draft_persists_unbound_required_scenario_gap(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path / "gap-wiki")
    repository = SQLiteStore(tmp_path / "gap-plan.sqlite3")
    ensure_tool_seed_data(repository, granted_by="test")
    repository.save_agent_tool_grant(
        AgentToolGrant(agent_id=USER.personal_agent_id, tool_id="tool_web_research", granted_by="test")
    )
    skill_catalog = SkillCatalogService(repository)
    skill_catalog.reload()
    task_catalog = load_default_task_catalog()
    request = "对比竞品，并走查页面体验问题，最后输出综合报告。"
    routing_result, _ = TaskScenarioRouter(task_catalog).route(request)
    intent = deterministic_intent(request)
    intent.presentation_requirements = ["report"]
    candidates, _ = SkillCandidateRetriever(repository, skill_catalog).recommend_for_route(
        USER,
        intent,
        routing_result,
        task_catalog,
    )

    draft = route_skill_draft(intent, candidates, routing_result, task_catalog)

    assert "runtime_skill_unbound:experience-walkthrough" in draft.capability_gaps


def test_deterministic_synthesis_uses_requested_presentation_sections() -> None:
    result = SkillNodeResult(
        id="result_synthesis",
        node_id="node_synthesis",
        skill_id="skill_synthesis",
        summary="用户先判断可信度，再比较营养和价格。",
        findings=["可信度是首要判断"],
        recommendations=["前置原料与检测信息"],
    )

    synthesis = deterministic_synthesis(
        [result],
        degradation=None,
        presentation_requirements=["mental_model", "design_principles"],
    )

    assert synthesis.sections[0].startswith("用户心智模型")
    assert synthesis.sections[1].startswith("设计原则")
    assert "可信度是首要判断" in synthesis.sections[0]
    assert synthesis.claims[0].node_result_ids == [result.id]


def test_completion_check_enforces_external_source_coverage() -> None:
    routing_result, _ = TaskScenarioRouter().route("帮我看看竞品怎么做")
    node = SkillPlanNode(
        id="node_competitive",
        skill_id="skill_runtime_competitive",
        skill_version="1",
        skill_content_hash="hash",
        reason="竞品研究",
        scenario_id="competitor-benchmark-research",
        output_contract=["competitive_analysis"],
    )
    plan = SkillPlan(
        id="plan_completion",
        run_id="run_completion",
        intent=deterministic_intent("帮我看看竞品怎么做"),
        routing_result=routing_result.model_dump(mode="json"),
        nodes=[node],
    )
    sources = [
        SkillResultSource(
            id=f"source_{index}",
            title=f"Source {index}",
            source_type="web_page",
            reference=f"https://source{index % 3}.example.com/page/{index}",
        )
        for index in range(5)
    ]
    scenario = load_default_task_catalog().get_scenario("competitor-benchmark-research")
    assert scenario is not None
    result = SkillNodeResult(
        id="result_competitive",
        node_id=node.id,
        skill_id=node.skill_id,
        summary="竞品模式结论",
        scenario_outputs=list(scenario.outputs),
        completion_criteria_met=list(scenario.completion_criteria),
        sources=sources,
    )

    completed = evaluate_plan_completion(plan, [result])
    insufficient = evaluate_plan_completion(plan, [result.model_copy(update={"sources": sources[:2]})])
    internal_only = evaluate_plan_completion(
        plan,
        [
            result.model_copy(
                update={
                    "sources": [
                        source.model_copy(
                            update={"source_type": "skill_resource", "reference": f"methods/{index}.md"}
                        )
                        for index, source in enumerate(sources)
                    ]
                }
            )
        ],
    )

    assert completed is not None and completed.completed is True
    assert completed.evidence_sufficient is True
    assert insufficient is not None and insufficient.completed is False
    assert insufficient.evidence_sufficient is False
    assert internal_only is not None and internal_only.evidence_sufficient is False
    assert any(gap.startswith("external_evidence_insufficient") for gap in insufficient.gaps)


def test_completion_check_does_not_treat_summary_as_output_coverage() -> None:
    routing_result, _ = TaskScenarioRouter().route("帮我看看竞品怎么做")
    node = SkillPlanNode(
        id="node_summary_only",
        skill_id="skill_runtime_competitive",
        skill_version="1",
        skill_content_hash="hash",
        reason="竞品研究",
        scenario_id="competitor-benchmark-research",
        output_contract=["competitive_analysis"],
    )
    plan = SkillPlan(
        id="plan_summary_only",
        run_id="run_summary_only",
        status="running",
        intent=deterministic_intent("帮我看看竞品怎么做"),
        routing_result=routing_result.model_dump(mode="json"),
        nodes=[node],
    )
    result = SkillNodeResult(
        id="result_summary_only",
        node_id=node.id,
        skill_id=node.skill_id,
        summary="只有一段摘要",
    )

    completion = evaluate_plan_completion(plan, [result])

    assert completion is not None and completion.completed is False
    assert set(completion.missing_outputs) == {
        "竞品选择逻辑",
        "模式对比",
        "标杆启发",
        "风险与限制",
    }
    assert any(gap.startswith("scenario_outputs_incomplete") for gap in completion.gaps)


def test_completion_check_reports_unexecuted_scenario_outputs() -> None:
    routing_result, _ = TaskScenarioRouter().route("帮我画用户旅程")
    plan = SkillPlan(
        id="plan_missing_scenario",
        run_id="run_missing_scenario",
        intent=deterministic_intent("帮我画用户旅程"),
        routing_result=routing_result.model_dump(mode="json"),
        nodes=[],
    )

    completion = evaluate_plan_completion(plan, [])

    assert completion is not None and completion.completed is False
    assert "用户旅程" in completion.missing_outputs
    assert "scenario_unexecuted:user-journey-insight" in completion.gaps


def test_disabled_task_router_preserves_legacy_intent(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMESH_TASK_SCENARIO_ROUTING", "false")

    intent = deterministic_intent("输出策略地图和用户心智模型")

    assert intent.deliverables == ["design_analysis"]
    assert intent.analysis_requirements == []
    assert intent.presentation_requirements == []
    assert intent.external_evidence_required is False


def test_route_freezes_catalog_identity() -> None:
    catalog = load_default_task_catalog()

    result, _ = TaskScenarioRouter(catalog).route("帮我画用户旅程")

    assert result.catalog_version == catalog.manifest.catalog_version
    assert result.catalog_hash == catalog.manifest.catalog_hash
