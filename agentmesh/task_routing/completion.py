from __future__ import annotations

from urllib.parse import urlparse

from agentmesh.models import SkillNodeResult, SkillPlan, SkillSynthesisResult
from agentmesh.task_routing.catalog import TaskCatalog, load_default_task_catalog
from agentmesh.task_routing.contracts import CompletionCheckResult, RoutingConfidence, TaskRoutingResult

_SYNTHESIS_SCENARIO_PRESENTATIONS = {
    "opportunity-direction-evaluation": {"opportunity_list"},
    "strategy-synthesis": {"strategy_map", "design_principles", "report"},
    "priority-roadmap": {"prioritized_actions", "roadmap"},
    "metrics-validation": {"metrics_plan"},
    "solution-comparison": {"comparison_table"},
}


def _external_sources(results: list[SkillNodeResult]):  # noqa: ANN202
    return [
        source
        for result in results
        for source in result.sources
        if source.source_type in {"web_page", "provider_summary", "page_observation"}
    ]


def _independent_source_keys(results: list[SkillNodeResult]) -> set[str]:
    keys: set[str] = set()
    for source in _external_sources(results):
        parsed = urlparse(source.reference)
        key = parsed.hostname or source.reference or source.id
        if key:
            keys.add(key.lower())
    return keys


def evaluate_plan_completion(
    plan: SkillPlan,
    results: list[SkillNodeResult],
    *,
    synthesis: SkillSynthesisResult | None = None,
    catalog: TaskCatalog | None = None,
) -> CompletionCheckResult | None:
    if plan.routing_result is None:
        return None
    routing = TaskRoutingResult.model_validate(plan.routing_result)
    task_catalog = catalog or load_default_task_catalog()
    if routing.catalog_hash != task_catalog.manifest.catalog_hash:
        raise ValueError("completion_catalog_mismatch")

    selected_scenarios = [routing.scenario.scenario_id, *routing.scenario.supporting_scenarios]
    results_by_node = {result.node_id: result for result in results}
    nodes_by_scenario: dict[str, list[str]] = {}
    for node in plan.nodes:
        if node.scenario_id:
            nodes_by_scenario.setdefault(node.scenario_id, []).append(node.id)

    missing_outputs: list[str] = []
    criteria_results: dict[str, bool] = {}
    gaps: list[str] = list(plan.capability_gaps)
    synthesis_owned_scenarios: set[str] = set()
    for scenario_id in selected_scenarios:
        scenario = task_catalog.get_scenario(scenario_id)
        if scenario is None:
            gaps.append(f"scenario_missing:{scenario_id}")
            continue
        node_ids = nodes_by_scenario.get(scenario_id, [])
        scenario_results = [results_by_node[node_id] for node_id in node_ids if node_id in results_by_node]
        rendered_presentations = set(synthesis.presentation_outputs) if synthesis is not None else set()
        synthesis_owned = bool(
            synthesis is not None
            and synthesis.claims
            and rendered_presentations & _SYNTHESIS_SCENARIO_PRESENTATIONS.get(scenario_id, set())
        )
        covered_outputs = {
            output
            for result in scenario_results
            for output in result.scenario_outputs
            if output in scenario.outputs
        }
        covered_criteria = {
            criterion
            for result in scenario_results
            for criterion in result.completion_criteria_met
            if criterion in scenario.completion_criteria
        }
        if synthesis_owned:
            synthesis_owned_scenarios.add(scenario_id)
            covered_outputs.update(scenario.outputs)
            covered_criteria.update(scenario.completion_criteria)
        scenario_missing_outputs = [output for output in scenario.outputs if output not in covered_outputs]
        missing_outputs.extend(scenario_missing_outputs)
        if not node_ids and not synthesis_owned:
            gaps.append(f"scenario_unexecuted:{scenario_id}")
        elif scenario_missing_outputs:
            gaps.append(f"scenario_outputs_incomplete:{scenario_id}")
        for criterion in scenario.completion_criteria:
            passed = criterion in covered_criteria
            criteria_results[f"{scenario_id}:{criterion}"] = passed
            if not passed:
                gaps.append(f"scenario_criterion_unmet:{scenario_id}:{criterion}")

    source_ids = {source.id for source in _external_sources(results)}
    independent_sources = _independent_source_keys(results)
    requirement = routing.evidence_requirement
    evidence_sufficient = not requirement.external_evidence_required or (
        len(source_ids) >= requirement.minimum_sources
        and len(independent_sources) >= requirement.independent_sources
    )
    if not evidence_sufficient:
        gaps.append(
            "external_evidence_insufficient:"
            f"sources={len(source_ids)}/{requirement.minimum_sources},"
            f"independent={len(independent_sources)}/{requirement.independent_sources}"
        )

    missing_outputs = list(dict.fromkeys(missing_outputs))
    gaps = list(dict.fromkeys(gaps))
    human_confirmation_pending = (
        routing.human_confirmation.required and plan.status.value != "running"
    )
    completed = (
        not missing_outputs
        and all(criteria_results.values())
        and evidence_sufficient
        and not human_confirmation_pending
        and not plan.capability_gaps
    )
    confidence = (
        RoutingConfidence.HIGH
        if completed
        else RoutingConfidence.MEDIUM
        if results
        else RoutingConfidence.LOW
    )
    return CompletionCheckResult(
        completed=completed,
        scenario_outputs={
            scenario_id: (
                [result.id for result in results if result.node_id in nodes_by_scenario.get(scenario_id, [])]
                or (["synthesis"] if scenario_id in synthesis_owned_scenarios else [])
            )
            for scenario_id in selected_scenarios
        },
        missing_outputs=missing_outputs,
        criteria_results=criteria_results,
        evidence_sufficient=evidence_sufficient,
        confidence=confidence,
        gaps=gaps,
        human_confirmation_required=human_confirmation_pending,
        reason="自动检查 Scenario 节点、输出血缘和外部证据覆盖。",
    )
