from __future__ import annotations

import re
from dataclasses import dataclass

from agentmesh.task_routing.catalog import TaskCatalog, load_default_task_catalog
from agentmesh.task_routing.contracts import (
    CompletionCheckResult,
    EvidenceRequirement,
    ExecutionRelation,
    HumanConfirmationDecision,
    InputCheckResult,
    InputDecision,
    KnowledgeRoutingDecision,
    RoutingConfidence,
    RoutingContext,
    ScenarioCatalogEntry,
    ScenarioRoute,
    SkillRoutingDecision,
    TaskRoute,
    TaskRoutingResult,
)
from agentmesh.tool_runtime.guardrails import redact_sensitive_text

_SCENARIO_SIGNALS: dict[str, tuple[str, ...]] = {
    "trend-change-identification": ("趋势", "变化信号", "最近变化", "赛道变化", "新趋势"),
    "competitor-benchmark-research": (
        "竞品",
        "标杆",
        "成熟做法",
        "品牌app",
        "品牌 app",
        "品牌心智",
        "品类特色",
    ),
    "opportunity-direction-evaluation": ("机会方向", "机会点", "值得做", "收敛机会", "探索方向"),
    "user-material-synthesis": ("用户资料", "访谈材料", "已有研究", "整理访谈", "资料归纳"),
    "user-segmentation": ("用户分层", "重点人群", "用户类型", "哪类用户", "人群差异"),
    "user-journey-insight": (
        "用户旅程",
        "心智模型",
        "用户心智",
        "品牌心智",
        "品类心智",
        "场域心智",
        "全链路",
        "任务链路",
        "核心需求",
    ),
    "experience-walkthrough": ("走查", "页面问题", "链路哪里不顺", "体验问题", "上线前看看"),
    "feedback-issue-clustering": ("用户反馈", "voc", "抱怨", "反馈聚类", "评价聚类"),
    "data-behavior-diagnosis": ("数据异常", "转化", "点击低", "漏斗", "留存异常"),
    "root-cause-analysis": ("根因", "原因拆解", "为什么会", "为什么卡住"),
    "solution-generation": ("解决方案", "有哪些解法", "怎么改", "方案生成"),
    "solution-comparison": ("方案比较", "哪个方案", "风险评估", "方案风险", "方案取舍"),
    "strategy-synthesis": (
        "策略地图",
        "策略全景",
        "设计表达策略",
        "心智策略",
        "设计策略",
        "整理成策略",
        "设计原则",
        "策略方向",
    ),
    "priority-roadmap": ("p0", "p1", "p2", "优先级", "排期", "实施路径", "先做"),
    "metrics-validation": ("指标", "验证计划", "上线后看", "怎么验证", "实验计划"),
}
_PRESENTATION_SIGNALS: dict[str, tuple[str, ...]] = {
    "strategy_map": ("策略地图", "策略全景", "设计表达策略全景"),
    "mental_model": ("心智模型", "用户心智", "品牌心智", "品类心智", "场域心智"),
    "design_principles": ("设计原则",),
    "opportunity_list": ("机会点", "机会清单"),
    "prioritized_actions": ("p0", "p1", "p2", "优先级", "行动优先级"),
    "roadmap": ("路线图", "实施路径", "排期"),
    "metrics_plan": ("指标树", "验证计划", "指标体系"),
    "comparison_table": ("对比表", "比较表"),
    "report": ("报告", "汇报",),
}
_SCENARIO_SEQUENCE = {
    "trend-change-identification": 10,
    "competitor-benchmark-research": 20,
    "opportunity-direction-evaluation": 30,
    "user-material-synthesis": 40,
    "user-segmentation": 50,
    "user-journey-insight": 60,
    "experience-walkthrough": 70,
    "feedback-issue-clustering": 70,
    "data-behavior-diagnosis": 70,
    "root-cause-analysis": 80,
    "solution-generation": 90,
    "solution-comparison": 100,
    "strategy-synthesis": 110,
    "priority-roadmap": 120,
    "metrics-validation": 130,
}
_EXTERNAL_EVIDENCE_TERMS = (
    "公开资料",
    "外部资料",
    "最新",
    "今年",
    "市场",
    "行业",
    "竞品",
    "标杆",
    "品牌app",
    "品牌 app",
    "网页",
    "搜索",
    "调研",
)
_HIGH_RISK_TERMS = (
    "直接上线",
    "立即发布",
    "调整价格",
    "修改库存",
    "交易规则",
    "合规决策",
    "处理个人隐私",
    "删除数据",
)
_INPUT_HINTS: dict[str, tuple[str, ...]] = {
    "时间": ("年", "月", "季度", "最近", "最新", "时间"),
    "资料": ("资料", "报告", "截图", "数据", "反馈", "访谈", "公开"),
    "材料": ("资料", "材料", "报告", "截图", "数据", "反馈", "访谈"),
    "证据": ("证据", "资料", "报告", "数据", "反馈", "访谈", "公开"),
    "竞品": ("竞品", "标杆", "品牌", "平台"),
    "用户": ("用户", "人群", "消费者", "客户", "宠物主"),
    "场景": ("场景", "流程", "链路", "旅程", "购买", "使用"),
    "问题": ("问题", "目标", "研究", "分析", "判断"),
    "目标": ("目标", "希望", "需要", "输出", "研究", "分析"),
    "方案": ("方案", "策略", "方向", "动作"),
    "策略": ("策略", "方向", "原则", "机会"),
    "指标": ("指标", "转化", "点击", "留存", "满意度"),
    "约束": ("约束", "成本", "资源", "时间", "范围", "平台"),
    "范围": ("范围", "平台", "渠道", "品牌", "页面", "链路"),
}


@dataclass(frozen=True)
class _ScenarioScore:
    scenario: ScenarioCatalogEntry
    score: float
    strong_match: bool


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"[a-z0-9][a-z0-9_-]*|[\u3400-\u9fff]+", text.lower()):
        terms.add(token)
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            terms.update(token[index : index + 2] for index in range(max(0, len(token) - 1)))
            terms.update(token[index : index + 3] for index in range(max(0, len(token) - 2)))
    return terms


def _overlap(query: set[str], value: str) -> float:
    target = _terms(value)
    if not query or not target:
        return 0.0
    return len(query & target) / max(1, len(target))


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _scenario_score(content: str, query_terms: set[str], scenario: ScenarioCatalogEntry) -> _ScenarioScore:
    score = 0.0
    strong_match = False
    for trigger in scenario.trigger_examples:
        normalized_trigger = _normalized(trigger)
        if normalized_trigger and normalized_trigger in content:
            score += 12.0
            strong_match = True
        else:
            score += _overlap(query_terms, trigger) * 2.5
    for signal in _SCENARIO_SIGNALS.get(scenario.id, ()):
        if signal in content:
            score += 5.0
            strong_match = True
    if _normalized(scenario.title) in content:
        score += 8.0
        strong_match = True
    score += _overlap(query_terms, scenario.definition) * 2.0
    score += max((_overlap(query_terms, output) for output in scenario.outputs), default=0.0) * 2.0
    return _ScenarioScore(scenario=scenario, score=round(score, 6), strong_match=strong_match)


def _presentation_requirements(content: str) -> list[str]:
    return [
        requirement
        for requirement, signals in _PRESENTATION_SIGNALS.items()
        if any(signal in content for signal in signals)
    ]


def _data_scope(content: str) -> str | None:
    year_ranges = re.findall(r"(?:20\d{2})(?:\s*[-—至到]\s*20\d{2})?", content)
    freshness = [term for term in ("最新", "最近", "今年") if term in content]
    values = _dedupe([*year_ranges, *freshness])
    return "、".join(values) if values else None


def _domain(content: str) -> str | None:
    quoted = re.search(r"[“\"《]([^”\"》]{2,30})[”\"》]", content)
    if quoted:
        return quoted.group(1).strip()
    match = re.search(r"(?:研究|分析|围绕|针对)([\u3400-\u9fffA-Za-z0-9-]{2,24}?)(?:在|的|用户|市场|品类|，|,)", content)
    return match.group(1).strip() if match else None


def _routing_context(content: str, project_summary: str) -> RoutingContext:
    journeys = [
        stage
        for stage in ("认知", "种草", "搜索", "比较", "决策", "购买", "使用", "复购")
        if stage in content
    ]
    page = next(
        (
            value
            for value in ("商品详情页", "商详页", "首页", "搜索页", "列表页", "结算页", "支付页", "页面")
            if value in content
        ),
        None,
    )
    user_match = re.search(r"([\u3400-\u9fffA-Za-z0-9-]{2,16}(?:用户|人群|消费者|客户|宠物主))", content)
    return RoutingContext(
        domain=_domain(content),
        page=page,
        journey=journeys,
        project=project_summary.strip()[:500] or None,
        user_segment=user_match.group(1) if user_match else None,
        data_scope=_data_scope(content),
    )


def _input_available(label: str, content: str, context: RoutingContext, *, has_upstream: bool) -> bool:
    if has_upstream and any(term in label for term in ("结论", "证据", "问题", "方案", "策略")):
        return True
    if context.domain and any(term in label for term in ("业务", "对象", "品类", "场景", "本品")):
        return True
    if context.user_segment and "用户" in label:
        return True
    if context.data_scope and "时间" in label:
        return True
    return any(
        hint in content
        for key, hints in _INPUT_HINTS.items()
        if key in label
        for hint in hints
    )


def _input_check(
    content: str,
    selected: list[ScenarioCatalogEntry],
    context: RoutingContext,
    confidence: RoutingConfidence,
    human_confirmation: bool,
) -> InputCheckResult:
    required = _dedupe([value for scenario in selected for value in scenario.required_inputs])
    optional = _dedupe([value for scenario in selected for value in scenario.optional_inputs])
    has_upstream = len(selected) > 1
    available_required = [
        value for value in required if _input_available(value, content, context, has_upstream=has_upstream)
    ]
    available_optional = [
        value for value in optional if _input_available(value, content, context, has_upstream=has_upstream)
    ]
    missing_required = [value for value in required if value not in available_required]
    missing_optional = [value for value in optional if value not in available_optional]
    if human_confirmation:
        decision = InputDecision.HUMAN_CONFIRMATION
    elif confidence == RoutingConfidence.LOW:
        decision = InputDecision.CLARIFY
    elif missing_required:
        decision = InputDecision.DEGRADE if all(scenario.fallback for scenario in selected) else InputDecision.CLARIFY
    else:
        decision = InputDecision.CONTINUE
    return InputCheckResult(
        available_inputs=_dedupe(["user_request", *available_required, *available_optional]),
        missing_required_inputs=missing_required,
        missing_optional_inputs=missing_optional,
        input_decision=decision,
    )


def _execution_relation(selected: list[ScenarioCatalogEntry], primary: ScenarioCatalogEntry) -> ExecutionRelation:
    if len(selected) == 1:
        return ExecutionRelation.SERIAL
    upstream_tasks = {scenario.parent_task for scenario in selected if scenario.id != primary.id}
    if primary.parent_task == "define-strategy" and len(upstream_tasks) >= 2:
        return ExecutionRelation.PARALLEL_THEN_MERGE
    dependency_ids = {dependency for scenario in selected for dependency in scenario.dependencies}
    if dependency_ids & {scenario.id for scenario in selected}:
        return ExecutionRelation.SERIAL
    return ExecutionRelation.PARALLEL


def validate_routing_result(result: TaskRoutingResult, catalog: TaskCatalog) -> None:
    if result.catalog_version != catalog.manifest.catalog_version or result.catalog_hash != catalog.manifest.catalog_hash:
        raise ValueError("routing_catalog_mismatch")
    task = catalog.get_task(result.task.task_id)
    scenario = catalog.get_scenario(result.scenario.scenario_id)
    if task is None:
        raise ValueError("routing_task_unknown")
    if scenario is None or scenario.parent_task != task.id:
        raise ValueError("routing_primary_scenario_invalid")
    selected_ids = [scenario.id, *result.scenario.supporting_scenarios]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("routing_scenario_duplicate")
    selected = [catalog.get_scenario(scenario_id) for scenario_id in selected_ids]
    if any(item is None for item in selected):
        raise ValueError("routing_supporting_scenario_unknown")
    expected_secondary = _dedupe(
        [item.parent_task for item in selected[1:] if item is not None and item.parent_task != task.id]
    )
    if result.task.secondary_tasks != expected_secondary:
        raise ValueError("routing_secondary_tasks_mismatch")
    if any(catalog.get_scenario(scenario_id) is None for scenario_id in result.scenario.alternative_scenarios):
        raise ValueError("routing_alternative_scenario_unknown")
    selected_mappings = [catalog.get_mapping(scenario_id) for scenario_id in selected_ids]
    if any(mapping is None for mapping in selected_mappings):
        raise ValueError("routing_mapping_missing")
    allowed_skills = {
        skill_id
        for mapping in selected_mappings
        if mapping is not None
        for skill_id in [*mapping.default_skill_ids, *mapping.optional_skill_ids]
    }
    allowed_planned = {
        skill_id
        for mapping in selected_mappings
        if mapping is not None
        for skill_id in mapping.planned_skill_ids
    }
    routed_skills = {
        *result.skill_routing.default_skills,
        *result.skill_routing.optional_skills,
    }
    if not routed_skills.issubset(allowed_skills):
        raise ValueError("routing_skill_unknown")
    if not set(result.skill_routing.planned_skills).issubset(allowed_planned):
        raise ValueError("routing_planned_skill_unknown")
    allowed_knowledge = {
        value
        for mapping in selected_mappings
        if mapping is not None
        for value in [
            *mapping.required_knowledge_ids,
            *mapping.optional_knowledge_ids,
            *mapping.required_knowledge_descriptors,
            *mapping.optional_knowledge_descriptors,
        ]
    }
    routed_knowledge = {
        *result.knowledge_routing.required_knowledge,
        *result.knowledge_routing.optional_knowledge,
    }
    if not routed_knowledge.issubset(allowed_knowledge):
        raise ValueError("routing_knowledge_unknown")


class TaskScenarioRouter:
    def __init__(self, catalog: TaskCatalog | None = None):
        self.catalog = catalog or load_default_task_catalog()

    def route(
        self,
        content: str,
        *,
        project_summary: str = "",
        thread_summary: str = "",
    ) -> tuple[TaskRoutingResult, list[str]]:
        request = redact_sensitive_text(content.strip())[:4000]
        normalized = _normalized(request)
        context_text = _normalized(" ".join([request, project_summary[:500], thread_summary[:1000]]))
        query_terms = _terms(context_text)
        scores = sorted(
            (_scenario_score(normalized, query_terms, scenario) for scenario in self.catalog.scenarios),
            key=lambda item: (-item.score, item.scenario.id),
        )
        strong = [item for item in scores if item.strong_match]
        selected_scores = strong or scores[:1]
        selected_ids = {item.scenario.id for item in selected_scores}
        selected_scores = [item for item in scores if item.scenario.id in selected_ids]
        primary_score = max(
            selected_scores,
            key=lambda item: (_SCENARIO_SEQUENCE.get(item.scenario.id, 0), item.score),
        )
        primary = primary_score.scenario
        supporting_scores = [item for item in selected_scores if item.scenario.id != primary.id]
        supporting_scores.sort(key=lambda item: (_SCENARIO_SEQUENCE.get(item.scenario.id, 0), -item.score))
        supporting = [item.scenario for item in supporting_scores]
        selected = [primary, *supporting]
        alternatives = [
            item.scenario.id
            for item in scores
            if item.scenario.id not in selected_ids and item.score > 0
        ][:3]
        confidence = (
            RoutingConfidence.HIGH
            if primary_score.strong_match
            else RoutingConfidence.MEDIUM
            if primary_score.score >= 2.0
            else RoutingConfidence.LOW
        )
        secondary_tasks = _dedupe(
            [scenario.parent_task for scenario in supporting if scenario.parent_task != primary.parent_task]
        )
        relation = _execution_relation(selected, primary)
        high_risk_terms = [term for term in _HIGH_RISK_TERMS if term in normalized]
        human_confirmation = bool(high_risk_terms)
        context = _routing_context(request, project_summary)
        input_check = _input_check(normalized, selected, context, confidence, human_confirmation)

        mappings = [self.catalog.get_mapping(scenario.id) for scenario in selected]
        default_skills = _dedupe(
            [skill_id for mapping in mappings if mapping for skill_id in mapping.default_skill_ids]
        )
        optional_skills = _dedupe(
            [skill_id for mapping in mappings if mapping for skill_id in mapping.optional_skill_ids]
        )
        planned_skills = _dedupe(
            [skill_id for mapping in mappings if mapping for skill_id in mapping.planned_skill_ids]
        )
        required_knowledge = _dedupe(
            [
                value
                for mapping in mappings
                if mapping
                for value in [*mapping.required_knowledge_ids, *mapping.required_knowledge_descriptors]
            ]
        )
        optional_knowledge = _dedupe(
            [
                value
                for mapping in mappings
                if mapping
                for value in [*mapping.optional_knowledge_ids, *mapping.optional_knowledge_descriptors]
            ]
        )
        external_required = any(term in normalized for term in _EXTERNAL_EVIDENCE_TERMS) or any(
            scenario.id in {"trend-change-identification", "competitor-benchmark-research"}
            for scenario in selected
        )
        years = re.findall(r"20\d{2}", normalized)
        freshness = f"{'-'.join(_dedupe(years))} public sources" if years else "current public sources" if external_required else None
        missing_outputs = _dedupe([output for scenario in selected for output in scenario.outputs])
        presentation = _presentation_requirements(normalized)
        analysis = _dedupe(
            (["external_evidence"] if external_required else []) + [scenario.id for scenario in selected]
        )
        result = TaskRoutingResult(
            catalog_version=self.catalog.manifest.catalog_version,
            catalog_hash=self.catalog.manifest.catalog_hash,
            task=TaskRoute(
                task_id=primary.parent_task,
                confidence=confidence,
                reason="按最终交付物和 Scenario 触发词选择主任务。",
                secondary_tasks=secondary_tasks,
                execution_relation=relation,
            ),
            scenario=ScenarioRoute(
                scenario_id=primary.id,
                confidence=confidence,
                supporting_scenarios=[scenario.id for scenario in supporting],
                alternative_scenarios=alternatives,
            ),
            context=context,
            input_check=input_check,
            skill_routing=SkillRoutingDecision(
                default_skills=default_skills,
                optional_skills=optional_skills,
                planned_skills=planned_skills,
                execution_mode=relation,
            ),
            knowledge_routing=KnowledgeRoutingDecision(
                required_knowledge=required_knowledge,
                optional_knowledge=optional_knowledge,
                excluded_knowledge=[],
            ),
            evidence_requirement=EvidenceRequirement(
                external_evidence_required=external_required,
                freshness=freshness,
                minimum_sources=5 if external_required else 0,
                independent_sources=3 if external_required else 0,
            ),
            analysis_requirements=analysis,
            presentation_requirements=presentation,
            completion_check=CompletionCheckResult(
                completed=False,
                missing_outputs=missing_outputs,
                evidence_sufficient=not external_required,
                confidence=confidence,
                human_confirmation_required=human_confirmation,
                reason="等待 Skill 执行和自动完成度检查。",
            ),
            human_confirmation=HumanConfirmationDecision(
                required=human_confirmation,
                reason="、".join(high_risk_terms),
            ),
        )
        validate_routing_result(result, self.catalog)
        diagnostics = ["deterministic_task_router"]
        if confidence == RoutingConfidence.LOW:
            diagnostics.append("routing_low_confidence")
        if planned_skills:
            diagnostics.extend(f"planned_skill_unavailable:{skill_id}" for skill_id in planned_skills)
        return result, diagnostics
