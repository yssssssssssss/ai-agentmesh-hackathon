from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from agents import Agent, RunConfig, Runner
from agents.models.interface import Model
from pydantic import BaseModel, ConfigDict, Field

from agentmesh.agent_runtime.settings import task_scenario_routing_enabled
from agentmesh.models import (
    SkillCandidate,
    SkillIntent,
    SkillIntentComplexity,
    SkillLifecycleStage,
    SkillPlanDraft,
    SkillPlanNode,
    SkillSideEffect,
)
from agentmesh.skill_runtime.profiles import kinds_compatible
from agentmesh.skill_runtime.retrieval import tool_names_for_profile
from agentmesh.task_routing.catalog import TaskCatalog
from agentmesh.task_routing.contracts import TaskRoutingResult
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
_SYNTHESIS_SCENARIO_PRESENTATIONS = {
    "opportunity-direction-evaluation": {"opportunity_list"},
    "strategy-synthesis": {"strategy_map", "design_principles", "report"},
    "priority-roadmap": {"prioritized_actions", "roadmap"},
    "metrics-validation": {"metrics_plan"},
    "solution-comparison": {"comparison_table"},
}


class PlannerUnavailable(RuntimeError):
    pass


class _PlannerNodeDraft(BaseModel):
    """Only fields the model is allowed to choose while drafting a Plan."""

    model_config = ConfigDict(extra="forbid")

    id: str
    skill_id: str
    skill_version: str
    skill_content_hash: str
    reason: str = Field(min_length=1, max_length=1000)
    required: bool = True
    depends_on: list[str] = Field(default_factory=list, max_length=6)
    parallel_group: str | None = Field(default=None, max_length=120)
    input_bindings: list[str] = Field(default_factory=list, max_length=20)
    output_contract: list[str] = Field(default_factory=list, max_length=20)
    side_effect: SkillSideEffect = SkillSideEffect.READ


class _PlannerDraft(BaseModel):
    """Strict LLM output contract, separate from persisted runtime state."""

    model_config = ConfigDict(extra="forbid")

    output_contract: list[str] = Field(default_factory=list, max_length=20)
    synthesis_output_contract: list[str] = Field(default_factory=list, max_length=20)
    capability_gaps: list[str] = Field(default_factory=list, max_length=100)
    nodes: list[_PlannerNodeDraft] = Field(default_factory=list, max_length=6)

    def to_skill_plan_draft(self) -> SkillPlanDraft:
        return SkillPlanDraft.model_validate(self.model_dump(mode="python"))


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
    from agentmesh.task_routing.catalog import TaskCatalogLoadError
    from agentmesh.task_routing.router import TaskScenarioRouter

    try:
        if not task_scenario_routing_enabled():
            raise TaskCatalogLoadError("task_scenario_routing_disabled")
        routing_result, _routing_diagnostics = TaskScenarioRouter().route(text)
        analysis_requirements = routing_result.analysis_requirements
        presentation_requirements = routing_result.presentation_requirements
        external_evidence_required = routing_result.evidence_requirement.external_evidence_required
        if not explicit and deliverables == ["design_analysis"] and presentation_requirements:
            deliverables = ["synthesis"]
            if len(analysis_requirements) >= 2:
                complexity = SkillIntentComplexity.WORKFLOW
    except TaskCatalogLoadError:
        analysis_requirements = []
        presentation_requirements = []
        external_evidence_required = False
    return SkillIntent(
        goal=text,
        primary_stage=stage,
        input_kinds=input_kinds,
        deliverables=deliverables,
        analysis_requirements=analysis_requirements,
        presentation_requirements=presentation_requirements,
        external_evidence_required=external_evidence_required,
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
                    "analysis_requirements": canonical.analysis_requirements,
                    "presentation_requirements": canonical.presentation_requirements,
                    "external_evidence_required": canonical.external_evidence_required,
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


def route_skill_draft(
    intent: SkillIntent,
    candidates: list[SkillCandidate],
    routing_result: TaskRoutingResult,
    task_catalog: TaskCatalog,
) -> SkillPlanDraft:
    candidate_by_name = {candidate.skill_name: candidate for candidate in candidates}
    scenario_order = [*routing_result.scenario.supporting_scenarios, routing_result.scenario.scenario_id]
    assignments: dict[str, tuple[int, str, str]] = {}
    for position, scenario_id in enumerate(scenario_order):
        mapping = task_catalog.get_mapping(scenario_id)
        if mapping is None:
            continue
        registry_skill_ids = [*mapping.default_skill_ids, *mapping.optional_skill_ids]
        for registry_skill_id in registry_skill_ids:
            catalog_skill = task_catalog.get_skill(registry_skill_id)
            if catalog_skill is None or catalog_skill.runtime_skill_name not in candidate_by_name:
                continue
            runtime_name = catalog_skill.runtime_skill_name
            assignments[runtime_name] = (position, scenario_id, registry_skill_id)
            break
    selected: list[tuple[str, tuple[int, str | None, str]]] = sorted(
        assignments.items(),
        key=lambda item: (item[1][0], item[0]),
    )[:6]
    selected_names = {name for name, _assignment in selected}
    covered_deliverables = {
        output
        for name in selected_names
        for output in candidate_by_name[name].profile.output_kinds
    }
    registry_by_runtime_name = {
        skill.runtime_skill_name: skill
        for skill in task_catalog.skills
        if skill.runtime_skill_name is not None
    }
    requested_node_deliverables = [
        deliverable
        for deliverable in intent.deliverables
        if deliverable not in {*_SYNTHESIS_OUTPUTS, "design_analysis"}
    ]
    for deliverable in requested_node_deliverables:
        if deliverable in covered_deliverables or len(selected) >= 6:
            continue
        candidate = next(
            (
                item
                for item in candidates
                if item.skill_name not in selected_names
                and item.skill_name in registry_by_runtime_name
                and deliverable in item.profile.output_kinds
            ),
            None,
        )
        if candidate is None:
            continue
        registry_skill = registry_by_runtime_name[candidate.skill_name]
        selected.append(
            (
                candidate.skill_name,
                (len(scenario_order) + len(selected), None, registry_skill.id),
            )
        )
        selected_names.add(candidate.skill_name)
        covered_deliverables.update(candidate.profile.output_kinds)
    if not selected:
        raise PlannerUnavailable("No executable Skill is bound to the selected Scenarios")
    if routing_result.evidence_requirement.external_evidence_required and not any(
        "web_research" in tool_names_for_profile(candidate_by_name[name].profile)
        for name, _assignment in selected
    ):
        raise PlannerUnavailable("External evidence is required but no authorized research Skill is available")

    provisional: list[tuple[SkillPlanNode, SkillCandidate, str]] = []
    for index, (runtime_name, (_position, scenario_id, registry_skill_id)) in enumerate(selected, start=1):
        candidate = candidate_by_name[runtime_name]
        profile = candidate.profile
        scenario = task_catalog.get_scenario(scenario_id) if scenario_id is not None else None
        mapping = task_catalog.get_mapping(scenario_id) if scenario_id is not None else None
        catalog_skill = task_catalog.get_skill(registry_skill_id)
        if catalog_skill is None or (scenario_id is not None and (scenario is None or mapping is None)):
            raise PlannerUnavailable("The selected Scenario mapping is incomplete")
        direct_inputs = [kind for kind in intent.input_kinds if kind in profile.input_kinds]
        node_outputs = (
            profile.output_kinds
            if scenario is not None
            else [output for output in requested_node_deliverables if output in profile.output_kinds]
        )
        requested_outputs = "、".join(node_outputs)
        provisional.append(
            (
                SkillPlanNode(
                    id=f"node_{index}_{runtime_name.replace('-', '_')}",
                    skill_id=candidate.skill_id,
                    skill_version=profile.skill_version,
                    skill_content_hash=profile.skill_content_hash,
                    reason=(
                        f"{scenario.title}：{candidate.reason}"
                        if scenario is not None
                        else f"明确请求交付物 {requested_outputs}：{candidate.reason}"
                    ),
                    task_id=scenario.parent_task if scenario is not None else routing_result.task.task_id,
                    scenario_id=scenario.id if scenario is not None else None,
                    skill_registry_id=registry_skill_id,
                    skill_status=catalog_skill.status.value,
                    required=True,
                    input_bindings=[f"user.{kind}" for kind in direct_inputs] or ["user.request"],
                    output_contract=node_outputs,
                    knowledge_bindings=(
                        {
                            "required": [*mapping.required_knowledge_ids, *mapping.required_knowledge_descriptors],
                            "optional": [*mapping.optional_knowledge_ids, *mapping.optional_knowledge_descriptors],
                            "excluded": routing_result.knowledge_routing.excluded_knowledge,
                        }
                        if mapping is not None
                        else {}
                    ),
                    required_tool_names=sorted(tool_names_for_profile(profile)),
                    completion_criteria=list(scenario.completion_criteria) if scenario is not None else [],
                    side_effect=profile.side_effect,
                ),
                candidate,
                scenario_id,
            )
        )

    primary_scenario_id = routing_result.scenario.scenario_id
    node_by_scenario = {
        scenario_id: node
        for node, _candidate, scenario_id in provisional
        if scenario_id is not None
    }
    nodes: list[SkillPlanNode] = []
    for provisional_index, (node, candidate, scenario_id) in enumerate(provisional):
        scenario = task_catalog.get_scenario(scenario_id) if scenario_id is not None else None
        if scenario is None:
            dependencies = []
            bindings = [binding for binding in node.input_bindings if binding != "user.request"]
            if not bindings:
                for producer, _producer_candidate, _producer_scenario_id in reversed(
                    provisional[:provisional_index]
                ):
                    output_kind = next(
                        (
                            output
                            for output in producer.output_contract
                            if any(
                                kinds_compatible(output, input_kind)
                                for input_kind in candidate.profile.input_kinds
                            )
                        ),
                        None,
                    )
                    if output_kind is not None:
                        dependencies = [producer.id]
                        bindings = [f"{producer.id}.{output_kind}"]
                        break
            nodes.append(
                node.model_copy(
                    update={
                        "depends_on": dependencies,
                        "input_bindings": bindings or ["user.request"],
                    }
                )
            )
            continue
        if scenario_id == primary_scenario_id or scenario.parent_task == "define-strategy":
            dependencies = [
                other.id
                for other, _other_candidate, other_scenario_id in provisional
                if other.id != node.id
                and other_scenario_id is not None
                and scenario_order.index(other_scenario_id) < scenario_order.index(scenario_id)
            ]
        else:
            dependencies = [
                node_by_scenario[dependency].id
                for dependency in scenario.dependencies
                if dependency in node_by_scenario
            ]
        bindings: list[str] = []
        for dependency_id in dependencies:
            producer = next(item for item, _item_candidate, _scenario_id in provisional if item.id == dependency_id)
            output_kind = next(
                (
                    output
                    for output in producer.output_contract
                    if any(kinds_compatible(output, input_kind) for input_kind in candidate.profile.input_kinds)
                ),
                None,
            )
            if output_kind is not None:
                bindings.append(f"{dependency_id}.{output_kind}")
        if not bindings:
            bindings = node.input_bindings
        nodes.append(node.model_copy(update={"depends_on": dependencies, "input_bindings": bindings}))

    root_nodes = [node for node in nodes if not node.depends_on]
    if len(root_nodes) > 1:
        root_ids = {node.id for node in root_nodes[:3]}
        nodes = [
            node.model_copy(update={"parallel_group": "upstream_1"}) if node.id in root_ids else node
            for node in nodes
        ]
    produced_outputs = {output for node in nodes for output in node.output_contract}
    output_contract = list(
        dict.fromkeys(
            [
                *(output for output in intent.deliverables if output in produced_outputs),
                *(intent.presentation_requirements or ["synthesis"]),
            ]
        )
    )
    covered_scenarios = {
        scenario_id
        for _name, (_position, scenario_id, _skill_id) in selected
        if scenario_id is not None
    }
    requested_presentations = set(intent.presentation_requirements)
    capability_gaps = [
        f"runtime_skill_unbound:{scenario_id}"
        for scenario_id in scenario_order
        if scenario_id not in covered_scenarios
        and not (
            requested_presentations
            & _SYNTHESIS_SCENARIO_PRESENTATIONS.get(scenario_id, set())
        )
    ]
    capability_gaps.extend(
        f"deliverable_uncovered:{deliverable}"
        for deliverable in requested_node_deliverables
        if deliverable not in produced_outputs
    )
    return SkillPlanDraft(
        output_contract=output_contract,
        synthesis_output_contract=list(intent.presentation_requirements),
        capability_gaps=capability_gaps,
        nodes=nodes,
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
            output_type=_PlannerDraft,
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
        return _PlannerDraft.model_validate(result.final_output).to_skill_plan_draft()
