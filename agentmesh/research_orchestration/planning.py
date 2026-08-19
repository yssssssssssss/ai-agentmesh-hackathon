from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from agents import Agent, RunConfig, Runner
from agents.models.interface import Model
from pydantic import BaseModel, ConfigDict, Field

from agentmesh.research_orchestration.contracts import (
    AmbiguityCode,
    ClarificationQuestion,
    EvidenceRequirement,
    ProblemContract,
    ProblemQuestion,
    RequirementVersion,
    ResearchAmbiguity,
    ResearchAssumption,
    ResearchTaskV2,
    SuccessCriterion,
    canonical_sha256,
)
from agentmesh.tool_runtime.guardrails import redact_sensitive_text

_PLANNING_INSTRUCTIONS = """Normalize one competitive-research request into ResearchTaskV2.
Do not perform the research and do not invent competitor names, private context, access, evidence, tools, or permissions.
The host fixes task_archetype=evidence_synthesis and task_type=competitive_research.
Only use the allowed ambiguity codes from the schema. A blocking ambiguity must have one matching clarification question.
Missing own-product context is an assumption, not a blocker. Missing or mutually exclusive competitor scope is blocking.
Return no more than three clarification questions.
"""

_GENERIC_REQUESTS = {
    "竞品分析",
    "帮我做竞品分析",
    "做一个竞品分析",
    "做份竞品分析",
    "分析一下竞品",
    "看看竞品",
}
_EXCLUDED_INTENTS = ("尼尔森", "启发式", "可用性问题", "严重度", "真人测试")
_KNOWN_COMPETITORS = ("淘宝", "拼多多", "京东", "抖音", "天猫", "Figma", "Miro")
_GENERIC_SCOPE_PARTS = {
    "竞品",
    "竞对",
    "产品",
    "工具",
    "平台",
    "助手",
    "方案",
    "能力",
    "功能",
    "场景",
    "局限",
    "差异",
    "用户体验",
}
_INVALID_SCOPE_ANSWERS = ("随便", "不知道", "不清楚", "你选", "都可以", "无所谓")
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


class RequirementPlanningResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement: ResearchTaskV2
    problem_contract: ProblemContract
    diagnostics: list[str] = Field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return any(item.blocking for item in self.requirement.ambiguities)


class RequirementPlanningError(RuntimeError):
    pass


def is_competitive_research_request(raw_input: str, *, explicit_skill_name: str | None = None) -> bool:
    explicit = (explicit_skill_name or "").removeprefix("$").strip()
    if explicit:
        return explicit == "competitive-analysis"
    text = raw_input.strip()
    if any(token in text for token in _EXCLUDED_INTENTS):
        return False
    has_subject = any(token in text for token in ("竞品", "竞对", "竞争产品", "对比", "比较"))
    has_goal = any(token in text for token in ("分析", "对比", "比较", "差异", "威胁", "能力", "场景", "局限", "建议"))
    return has_goal and (has_subject or _extract_competitor_scope(text) is not None)


def _redact_requirement_text(text: str) -> str:
    redacted = redact_sensitive_text(text)
    redacted = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)
    return _PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)


def _looks_like_named_list(candidate: str) -> bool:
    normalized = re.sub(r"^(?:请|帮我|帮忙|看看|分析|研究|对比|比较|选择)+", "", candidate.strip())
    normalized = re.split(r"的|，|,|。|；|;|重点|并(?:分析|比较|给出)", normalized, maxsplit=1)[0]
    parts = [part.strip(" \t：:（）()") for part in re.split(r"\s*(?:和|与|、|[vV][sS]\.?)\s*", normalized)]
    if len(parts) < 2:
        return False
    return all(1 <= len(part) <= 40 and part not in _GENERIC_SCOPE_PARTS for part in parts)


def _extract_competitor_scope(text: str, *, clarification_answer: bool = False) -> str | None:
    value = text.strip()
    compact = re.sub(r"[\s，。！？,.!?]", "", value).lower()
    if not compact or compact in _GENERIC_REQUESTS or any(token in compact for token in _INVALID_SCOPE_ANSWERS):
        return None

    category = re.search(
        r"[一二三四五六七八九十两\d]+(?:款|个|类)[^，。；;]{0,60}(?:助手|工具|平台|产品|方案|应用|服务)",
        value,
    )
    if category is not None:
        return category.group(0).strip()

    candidates = [value]
    after_verb = re.search(r"(?:对比|比较|研究|分析|看看)\s*(.{1,120})", value)
    if after_verb is not None:
        candidates.insert(0, after_verb.group(1))
    for candidate in candidates:
        if _looks_like_named_list(candidate):
            return re.split(r"的|，|,|。|；|;|重点", candidate.strip(), maxsplit=1)[0].strip()

    for competitor in _KNOWN_COMPETITORS:
        if competitor.lower() in value.lower():
            return competitor
    if clarification_answer and re.fullmatch(r"[A-Za-z][A-Za-z0-9 .+_-]{1,39}", value):
        return value
    return None


def _analysis_dimensions(text: str) -> list[str]:
    match = re.search(r"重点(?:分析|对比|比较)([^。；;]+)", text)
    if match is None:
        return ["capabilities", "applicable_scenarios", "limitations"]
    segment = re.split(r"给出|并给|以及给", match.group(1), maxsplit=1)[0]
    items = [item.strip(" ，、和及") for item in re.split(r"[、,，]|和|及", segment)]
    return list(dict.fromkeys(item for item in items if item))[:20]


def _deterministic_task(
    raw_input: str,
    *,
    clarification_answers: dict[str, str],
    capability_blocker: AmbiguityCode | None,
) -> ResearchTaskV2:
    raw_goal = raw_input.strip()
    goal = _redact_requirement_text(raw_goal)[:4000] or "开展竞品分析"
    raw_scope_answer = clarification_answers.get("clarify_competitor_scope", "").strip()
    scope_answer = _redact_requirement_text(raw_scope_answer)[:2000]
    competitor_scope = (
        _extract_competitor_scope(scope_answer, clarification_answer=True)
        if scope_answer
        else _extract_competitor_scope(goal)
    )
    ambiguities: list[ResearchAmbiguity] = []
    questions: list[ClarificationQuestion] = []
    if competitor_scope is None:
        ambiguities.append(
            ResearchAmbiguity(
                code=AmbiguityCode.MISSING_COMPETITOR_SCOPE,
                blocking=True,
                rationale="没有可执行的竞品名称或竞品类别范围。",
            )
        )
        questions.append(
            ClarificationQuestion(
                id="clarify_competitor_scope",
                ambiguity_code=AmbiguityCode.MISSING_COMPETITOR_SCOPE,
                prompt="请给出要比较的具体产品，或明确希望系统选择的产品类别与数量。",
            )
        )
    if capability_blocker is not None:
        ambiguities.append(
            ResearchAmbiguity(
                code=capability_blocker,
                blocking=True,
                rationale="当前授权或 Provider 状态不足以获取 required evidence。",
            )
        )
        questions.append(
            ClarificationQuestion(
                id="clarify_capability_access",
                ambiguity_code=capability_blocker,
                prompt="当前无法在授权范围内获取必需证据；请调整授权或稍后重试。",
            )
        )
    assumptions: list[ResearchAssumption] = []
    if not any(token in goal for token in ("我方", "我们", "本产品", "自家")):
        assumptions.append(
            ResearchAssumption(
                id="assumption_no_own_product",
                statement="未提供我方产品背景；先按同类产品选型视角比较，不推断我方内部战略。",
            )
        )
    criteria = [
        SuccessCriterion(id="sc_evidence_comparison", statement="关键能力差异均能追溯到外部证据。"),
        SuccessCriterion(id="sc_scenarios", statement="说明各产品的适用场景与明确局限。"),
        SuccessCriterion(id="sc_recommendations", statement="建议与事实或推断链路对应且披露资料缺口。"),
    ]
    scope_context = f"{goal} {competitor_scope or ''}"
    audience = ["enterprise_product_team"] if "企业" in scope_context and "产品" in scope_context else ["product_team"]
    business_domain = "enterprise_ai_research" if "AI" in scope_context.upper() else "competitive_product_research"
    pii_detected = bool(
        _PHONE_PATTERN.search(" ".join([raw_input, *clarification_answers.values()]))
        or _EMAIL_PATTERN.search(" ".join([raw_input, *clarification_answers.values()]))
    )
    return ResearchTaskV2(
        business_domain=business_domain,
        research_goal=goal,
        target_audience=audience,
        competitor_scope=competitor_scope,
        analysis_dimensions=_analysis_dimensions(goal),
        success_criteria=criteria,
        expected_deliverables=["competitive_analysis", "markdown_report", "html_report"],
        assumptions=assumptions,
        ambiguities=ambiguities,
        clarification_questions=questions[:3],
        sensitivity="internal" if "内部" in goal else "public",
        pii_detected=pii_detected,
    )


def _problem_contract(task: ResearchTaskV2) -> ProblemContract:
    evidence = EvidenceRequirement(evidence_class="provider_summary", minimum_sources=2, independent_sources=True)
    return ProblemContract(
        success_criterion_ids=[criterion.id for criterion in task.success_criteria],
        questions=[
            ProblemQuestion(
                id="q_evidence_comparison",
                statement="目标竞品在指定分析维度上的可观察能力与差异是什么？",
                rationale="先建立可追溯的事实基线，避免直接生成战略判断。",
                success_criterion_ids=["sc_evidence_comparison"],
                evidence_requirement=evidence,
                acceptance_criteria=["每个核心事实引用已验证 evidence", "明确 provider summary 的证据等级"],
            ),
            ProblemQuestion(
                id="q_scenarios",
                statement="各竞品适合哪些使用场景，存在哪些明确局限？",
                rationale="用户需要可执行的选型边界，而不是功能列表。",
                success_criterion_ids=["sc_scenarios"],
                depends_on=["q_evidence_comparison"],
                evidence_requirement=evidence,
                acceptance_criteria=["场景与局限均由事实或标注清楚的推断支持"],
            ),
            ProblemQuestion(
                id="q_recommendations",
                statement="基于事实与推断，可以给出哪些适用建议和后续验证动作？",
                rationale="将比较结果转成决策，同时披露证据缺口。",
                factual=False,
                success_criterion_ids=["sc_recommendations"],
                depends_on=["q_evidence_comparison", "q_scenarios"],
                acceptance_criteria=["建议引用父 Claim", "缺失证据形成 gap 而非事实"],
            ),
        ],
    )


class CompetitiveRequirementPlanner:
    def __init__(
        self,
        draft_factory: Callable[[str], Awaitable[ResearchTaskV2]] | None = None,
    ):
        self._draft_factory = draft_factory

    async def plan(
        self,
        raw_input: str,
        *,
        explicit_skill_name: str | None = None,
        clarification_answers: dict[str, str] | None = None,
        capability_blocker: AmbiguityCode | None = None,
        model: Model | None = None,
    ) -> RequirementPlanningResult:
        if not is_competitive_research_request(raw_input, explicit_skill_name=explicit_skill_name):
            raise RequirementPlanningError("not_competitive_research")
        answers = clarification_answers or {}
        fallback = _deterministic_task(
            raw_input,
            clarification_answers=answers,
            capability_blocker=capability_blocker,
        )
        diagnostics: list[str] = []
        task = fallback
        safe_request = _redact_requirement_text(raw_input) or "开展竞品分析"
        safe_answers = {key: _redact_requirement_text(value) for key, value in answers.items()}
        try:
            if self._draft_factory is not None:
                proposed = await self._draft_factory(safe_request)
                task = self._bound_model_task(proposed, fallback)
            elif model is not None:
                agent = Agent(
                    name="AgentMesh Competitive Requirement Planner",
                    instructions=_PLANNING_INSTRUCTIONS,
                    model=model,
                    tools=[],
                    output_type=ResearchTaskV2,
                )
                result = await Runner.run(
                    agent,
                    json.dumps(
                        {
                            "request": safe_request,
                            "clarification_answers": safe_answers,
                        },
                        ensure_ascii=False,
                    ),
                    max_turns=2,
                    run_config=RunConfig(
                        workflow_name="competitive_requirement_planning",
                        trace_include_sensitive_data=False,
                    ),
                )
                proposed = ResearchTaskV2.model_validate(result.final_output)
                task = self._bound_model_task(proposed, fallback)
            else:
                diagnostics.append("requirement_model_unavailable")
        except Exception:
            diagnostics.append("requirement_schema_fallback")
            task = fallback
        try:
            problem_contract = _problem_contract(task)
        except (TypeError, ValueError):
            diagnostics.append("requirement_contract_fallback")
            task = fallback
            problem_contract = _problem_contract(fallback)
        return RequirementPlanningResult(
            requirement=task,
            problem_contract=problem_contract,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _bound_model_task(proposed: ResearchTaskV2, fallback: ResearchTaskV2) -> ResearchTaskV2:
        payload = fallback.model_dump()
        business_domain = _redact_requirement_text(proposed.business_domain).strip()[:240]
        target_audience = [
            value
            for item in proposed.target_audience
            if (value := _redact_requirement_text(item).strip()[:240])
        ][:20]
        dimensions = [
            value
            for item in proposed.analysis_dimensions
            if (value := _redact_requirement_text(item).strip()[:240])
        ][:20]
        if business_domain:
            payload["business_domain"] = business_domain
        if target_audience:
            payload["target_audience"] = target_audience
        if dimensions:
            payload["analysis_dimensions"] = list(dict.fromkeys(dimensions))
        return ResearchTaskV2.model_validate(payload)


def requirement_version_from_result(
    run_id: str,
    version: int,
    result: RequirementPlanningResult,
) -> RequirementVersion:
    payload = {
        "requirement": result.requirement.model_dump(mode="json"),
        "problem_contract": result.problem_contract.model_dump(mode="json"),
    }
    return RequirementVersion(
        run_id=run_id,
        version=version,
        schema_version=result.requirement.schema_version,
        task_type=result.requirement.task_type,
        payload=payload,
        content_hash=canonical_sha256(payload),
    )
