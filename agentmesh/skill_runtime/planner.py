from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from agents import Agent, RunConfig, Runner
from agents.models.interface import Model

from agentmesh.models import (
    SkillCandidate,
    SkillIntent,
    SkillIntentComplexity,
    SkillLifecycleStage,
    SkillPlanDraft,
    SkillPlanNode,
)
from agentmesh.tool_runtime.guardrails import redact_sensitive_text

_INTENT_INSTRUCTIONS = """Normalize the user's design-workflow request into the required schema.
Do not solve the request. Do not infer access to files, memories, tools, or systems.
Leave explicit_skill_names empty. Only the host can mark a Skill as explicitly invoked.
Use only the supplied request and summaries. Mark external_write false unless the user explicitly requests an external write.
Classify complexity as direct (one domain Skill), assisted (two or three), or workflow (four to six).
"""

_PLANNER_INSTRUCTIONS = """Create a small dependency DAG using only the supplied safe Skill candidates.
Never invent a Skill ID, version, hash, input, output, permission, or source.
Treat every ID, input kind, output kind, and binding segment as opaque identifiers: copy exact strings only.
Each node output_contract must contain only exact values from that candidate's output_kinds.
The Plan output_contract may contain only exact node outputs or the supplied synthesis outputs.
Each input_binding must be user.request, user.<intent_input_kind>, or <dependency_node_id>.<dependency_output_kind>.
Never add labels, descriptions, parentheses, assignments, or '=' to an identifier or binding.
Use at most six nodes, depth four, and three nodes in one parallel group.
Dependencies must be necessary data dependencies. Prefer fewer nodes. Each node ID must be unique.
The output contract must describe the requested deliverables that the selected nodes can actually support.
When repair_error_codes are present, correct every listed violation.
"""

_SYMBOLIC_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
_SYNTHESIS_OUTPUTS = ["executive_summary", "summary", "synthesis"]


class PlannerUnavailable(RuntimeError):
    pass


def deterministic_intent(content: str, *, explicit_skill_name: str | None = None) -> SkillIntent:
    text = redact_sensitive_text(content.strip())[:1000]
    lowered = text.lower()
    if any(
        token in text
        for token in (
            "上线后",
            "设计完成后",
            "复盘",
            "优先级",
            "严重度",
            "工作量",
            "先解决",
            "度量",
            "衡量",
            "测量计划",
            "指标体系",
        )
    ):
        stage = SkillLifecycleStage.POST_DESIGN
    elif any(token in text for token in ("原型", "方案", "评审", "可用性", "问卷", "调查表", "定量", "访谈")):
        stage = SkillLifecycleStage.DURING_DESIGN
    else:
        stage = SkillLifecycleStage.PRE_DESIGN

    input_kinds = ["design_requirement"]
    keyword_inputs = {
        "prd": "prd",
        "需求文档": "prd",
        "原型": "prototype",
        "竞品": "competitive_material",
        "实验": "experiment_query",
        "问题清单": "issue_list",
    }
    for keyword, kind in keyword_inputs.items():
        if keyword in lowered and kind not in input_kinds:
            input_kinds.append(kind)

    deliverables: list[str] = []
    keyword_outputs = {
        "研究计划": "research_plan",
        "访谈": "interview_guide",
        "问卷": "survey",
        "可用性": "usability_test_plan",
        "竞品": "competitive_analysis",
        "可行性": "feasibility_review",
        "prd 评审": "feasibility_review",
        "实验": "historical_experiment",
        "jtbd": "jtbd_analysis",
        "真正任务": "jtbd_analysis",
        "指标": "experience_metrics",
        "度量": "experience_metrics",
        "衡量": "experience_metrics",
        "测量计划": "experience_metrics",
        "任务成功率": "experience_metrics",
        "留存": "experience_metrics",
        "调查表": "survey",
        "定量": "survey",
        "执行建议": "synthesis",
        "严重度": "prioritized_issues",
        "工作量": "prioritized_issues",
        "先解决": "prioritized_issues",
    }
    for keyword, output in keyword_outputs.items():
        if keyword in lowered and output not in deliverables:
            deliverables.append(output)
    if (
        "优先级" in lowered
        and "prioritized_issues" not in deliverables
        and any(subject in lowered for subject in ("问题", "需求", "缺陷", "bug", "事项", "候选项"))
    ):
        deliverables.append("prioritized_issues")
    if not deliverables:
        deliverables.append("design_analysis")
    complexity = (
        SkillIntentComplexity.WORKFLOW
        if len(deliverables) >= 4
        else SkillIntentComplexity.ASSISTED
        if len(deliverables) >= 2 or re.search(r"同时|以及|并且|从.+到", text)
        else SkillIntentComplexity.DIRECT
    )
    explicit = explicit_skill_name.removeprefix("$") if explicit_skill_name else None
    if explicit:
        complexity = SkillIntentComplexity.DIRECT
    return SkillIntent(
        goal=text,
        primary_stage=stage,
        input_kinds=input_kinds,
        deliverables=deliverables,
        explicit_skill_names=[explicit] if explicit else [],
        complexity=complexity,
    )


class SkillIntentAnalyzer:
    async def analyze(
        self,
        content: str,
        *,
        model: Model | None,
        project_summary: str = "",
        thread_summary: str = "",
        attachment_types: tuple[str, ...] = (),
        explicit_skill_name: str | None = None,
    ) -> tuple[SkillIntent, list[str]]:
        if explicit_skill_name:
            return deterministic_intent(content, explicit_skill_name=explicit_skill_name), []
        if model is None:
            return deterministic_intent(content), ["intent_model_unavailable"]
        agent = Agent(
            name="AgentMesh Skill Intent Analyzer",
            instructions=_INTENT_INSTRUCTIONS,
            model=model,
            tools=[],
            output_type=SkillIntent,
        )
        payload = {
            "request": content,
            "project_summary": project_summary[:2000],
            "thread_summary": thread_summary[:4000],
            "attachment_types": list(attachment_types),
        }
        try:
            result = await Runner.run(
                agent,
                json.dumps(payload, ensure_ascii=False),
                max_turns=2,
                run_config=RunConfig(
                    workflow_name="skill_intent_analysis",
                    trace_include_sensitive_data=False,
                ),
            )
            intent = SkillIntent.model_validate(result.final_output)
            canonical = deterministic_intent(content)
            model_inputs = [value for value in intent.input_kinds if _SYMBOLIC_IDENTIFIER.fullmatch(value)]
            model_outputs = [value for value in intent.deliverables if _SYMBOLIC_IDENTIFIER.fullmatch(value)]
            return intent.model_copy(
                update={
                    "goal": redact_sensitive_text(intent.goal)[:1000],
                    "input_kinds": list(dict.fromkeys([*canonical.input_kinds, *model_inputs])),
                    "deliverables": list(dict.fromkeys([*canonical.deliverables, *model_outputs])),
                    "explicit_skill_names": [],
                }
            ), []
        except Exception:
            return deterministic_intent(content), ["intent_schema_fallback"]


def single_skill_draft(intent: SkillIntent, candidate: SkillCandidate) -> SkillPlanDraft:
    profile = candidate.profile
    synthesis_outputs = {"executive_summary", "summary", "synthesis"}
    required_outputs = [item for item in intent.deliverables if item not in synthesis_outputs]
    output_contract = [item for item in required_outputs if item in profile.output_kinds]
    if required_outputs and set(output_contract) != set(required_outputs):
        raise PlannerUnavailable("The selected Skill cannot satisfy the requested deliverables")
    output_contract = output_contract or profile.output_kinds[:1]
    if not output_contract:
        raise PlannerUnavailable("The selected Skill has no declared output")
    accepted_inputs = [kind for kind in intent.input_kinds if kind in profile.input_kinds]
    return SkillPlanDraft(
        output_contract=output_contract,
        nodes=[
            SkillPlanNode(
                skill_id=candidate.skill_id,
                skill_version=profile.skill_version,
                skill_content_hash=profile.skill_content_hash,
                reason=candidate.reason,
                required=True,
                input_bindings=[f"user.{kind}" for kind in accepted_inputs] or ["user.request"],
                output_contract=output_contract,
                side_effect=profile.side_effect,
            )
        ],
    )


class SkillPlanner:
    def __init__(
        self,
        draft_factory: Callable[[SkillIntent, list[SkillCandidate]], Awaitable[SkillPlanDraft]] | None = None,
    ):
        self._draft_factory = draft_factory

    async def create_draft(
        self,
        intent: SkillIntent,
        candidates: list[SkillCandidate],
        *,
        model: Model | None,
        repair_errors: list[str] | None = None,
    ) -> SkillPlanDraft:
        if not candidates:
            raise PlannerUnavailable("No eligible Skill candidates")
        if len(candidates) == 1 or intent.complexity == SkillIntentComplexity.DIRECT:
            return single_skill_draft(intent, candidates[0])
        if self._draft_factory is not None:
            return await self._draft_factory(intent, candidates)
        if model is None:
            raise PlannerUnavailable("Planner model is not configured")
        agent = Agent(
            name="AgentMesh Skill Planner",
            instructions=_PLANNER_INSTRUCTIONS,
            model=model,
            tools=[],
            output_type=SkillPlanDraft,
        )
        candidate_payload = [
            {
                "skill_id": item.skill_id,
                "skill_name": item.skill_name,
                "skill_version": item.profile.skill_version,
                "skill_content_hash": item.profile.skill_content_hash,
                "primary_stage": item.profile.primary_stage.value,
                "capability_type": item.profile.capability_type.value,
                "input_kinds": item.profile.input_kinds,
                "output_kinds": item.profile.output_kinds,
                "side_effect": item.profile.side_effect.value,
                "reason": item.reason,
            }
            for item in candidates
        ]
        payload = {
            "intent": intent.model_dump(mode="json"),
            "candidates": candidate_payload,
            "repair_error_codes": repair_errors or [],
            "contract_rules": {
                "input_bindings": [
                    "user.request",
                    "user.<intent_input_kind>",
                    "<dependency_node_id>.<dependency_output_kind>",
                ],
                "node_outputs": "Copy exact values from the selected candidate output_kinds.",
                "plan_outputs": "Copy exact node outputs or one of synthesis_outputs.",
                "synthesis_outputs": _SYNTHESIS_OUTPUTS,
                "identifiers": "Do not add descriptions, labels, parentheses, assignments, or '='.",
            },
        }
        result = await Runner.run(
            agent,
            json.dumps(payload, ensure_ascii=False),
            max_turns=2,
            run_config=RunConfig(
                workflow_name="skill_dag_planning",
                trace_include_sensitive_data=False,
            ),
        )
        return SkillPlanDraft.model_validate(result.final_output)
