from __future__ import annotations

from collections import Counter

from agentmesh.models import (
    SkillCandidate,
    SkillIntent,
    SkillPlan,
    SkillPlanDraft,
    SkillPlanNode,
    SkillPlanStatus,
    SkillPlanUpdateRequest,
    new_id,
)

MAX_CANDIDATES = 12
MAX_NODES = 6
MAX_PARALLEL = 3
MAX_DEPTH = 4
_SYNTHESIS_OUTPUTS = {"executive_summary", "summary", "synthesis"}


class PlanValidationError(ValueError):
    def __init__(self, codes: list[str]):
        unique = list(dict.fromkeys(codes))
        super().__init__(", ".join(unique))
        self.codes = unique


def _depths(nodes: list[SkillPlanNode]) -> tuple[dict[str, int], list[str]]:
    by_id = {node.id: node for node in nodes}
    visiting: set[str] = set()
    depths: dict[str, int] = {}
    errors: list[str] = []

    def visit(node_id: str) -> int:
        if node_id in depths:
            return depths[node_id]
        if node_id in visiting:
            errors.append("dag_cycle")
            return MAX_DEPTH + 1
        node = by_id.get(node_id)
        if node is None:
            errors.append("unknown_dependency")
            return MAX_DEPTH + 1
        visiting.add(node_id)
        depth = 1
        if node.depends_on:
            depth = 1 + max(visit(parent) for parent in node.depends_on)
        visiting.remove(node_id)
        depths[node_id] = depth
        return depth

    for item in nodes:
        visit(item.id)
    return depths, errors


def validate_draft(
    draft: SkillPlanDraft,
    candidates: list[SkillCandidate],
    *,
    intent: SkillIntent,
) -> None:
    errors: list[str] = []
    if not draft.nodes:
        errors.append("plan_empty")
    elif not any(node.required for node in draft.nodes):
        errors.append("plan_requires_required_node")
    if len(draft.nodes) > MAX_NODES:
        errors.append("node_limit_exceeded")
    node_ids = [node.id for node in draft.nodes]
    if len(set(node_ids)) != len(node_ids):
        errors.append("duplicate_node_id")
    skill_ids = [node.skill_id for node in draft.nodes]
    if len(set(skill_ids)) != len(skill_ids):
        errors.append("duplicate_skill")
    by_skill = {candidate.skill_id: candidate for candidate in candidates}
    for node in draft.nodes:
        candidate = by_skill.get(node.skill_id)
        if candidate is None:
            errors.append("unknown_skill")
            continue
        profile = candidate.profile
        if node.skill_version != profile.skill_version:
            errors.append("skill_version_mismatch")
        if node.skill_content_hash != profile.skill_content_hash:
            errors.append("skill_hash_mismatch")
        if node.side_effect != profile.side_effect:
            errors.append("side_effect_mismatch")
        if not set(node.output_contract).issubset(profile.output_kinds):
            errors.append("unsupported_node_output")
        if node.id in node.depends_on:
            errors.append("self_dependency")
    depths, depth_errors = _depths(draft.nodes)
    errors.extend(depth_errors)
    if depths and max(depths.values()) > MAX_DEPTH:
        errors.append("dag_depth_exceeded")
    groups = Counter(node.parallel_group for node in draft.nodes if node.parallel_group)
    if any(count > MAX_PARALLEL for count in groups.values()):
        errors.append("parallel_limit_exceeded")
    by_id = {node.id: node for node in draft.nodes}
    for node in draft.nodes:
        consumer = by_skill.get(node.skill_id)
        for dependency in node.depends_on:
            parent = by_id.get(dependency)
            if parent is None:
                continue
            if parent.parallel_group and parent.parallel_group == node.parallel_group:
                errors.append("parallel_dependency_conflict")
            if node.required and not parent.required:
                errors.append("required_depends_on_optional")
        ancestors = set(node.depends_on)
        for binding in node.input_bindings:
            if binding.startswith("user."):
                input_kind = binding.removeprefix("user.").removeprefix("current_")
                if input_kind != "request" and input_kind not in intent.input_kinds:
                    errors.append("unknown_user_input")
                if input_kind != "request" and consumer is not None and input_kind not in consumer.profile.input_kinds:
                    errors.append("unsupported_node_input")
                continue
            producer_id, separator, output_kind = binding.partition(".")
            producer = by_id.get(producer_id)
            if not separator or producer is None or producer_id not in ancestors:
                errors.append("invalid_input_binding")
            elif output_kind not in producer.output_contract:
                errors.append("input_output_mismatch")
            elif consumer is not None and output_kind not in consumer.profile.input_kinds:
                errors.append("unsupported_node_input")
    available_outputs = {output for node in draft.nodes for output in node.output_contract} | _SYNTHESIS_OUTPUTS
    if not set(draft.output_contract).issubset(available_outputs):
        errors.append("output_contract_unsatisfied")
    if errors:
        raise PlanValidationError(errors)


def build_plan(
    *,
    run_id: str,
    intent: SkillIntent,
    candidates: list[SkillCandidate],
    draft: SkillPlanDraft,
    status: SkillPlanStatus,
) -> SkillPlan:
    validate_draft(draft, candidates, intent=intent)
    return SkillPlan(
        id=new_id("plan"),
        run_id=run_id,
        status=status,
        intent=intent,
        candidate_skill_ids=[candidate.skill_id for candidate in candidates[:MAX_CANDIDATES]],
        output_contract=draft.output_contract,
        preferred_order=[node.skill_id for node in draft.nodes],
        nodes=draft.nodes,
    )


def _recompute_parallel_groups(nodes: list[SkillPlanNode]) -> list[SkillPlanNode]:
    depths, errors = _depths(nodes)
    if errors:
        raise PlanValidationError(errors)
    counts = Counter(depths.values())
    adjusted: list[SkillPlanNode] = []
    for node in nodes:
        group = f"level_{depths[node.id]}" if counts[depths[node.id]] > 1 else None
        adjusted.append(node.model_copy(update={"parallel_group": group}))
    return adjusted


def adjust_plan(
    plan: SkillPlan,
    request: SkillPlanUpdateRequest,
    candidates: list[SkillCandidate],
) -> SkillPlan:
    selected = list(dict.fromkeys(request.selected_skill_ids))
    candidate_by_id = {candidate.skill_id: candidate for candidate in candidates}
    if any(skill_id not in plan.candidate_skill_ids or skill_id not in candidate_by_id for skill_id in selected):
        raise PlanValidationError(["skill_not_in_candidate_set"])
    existing_by_skill = {node.skill_id: node for node in plan.nodes}
    missing_required = [
        node.skill_id for node in plan.nodes if node.required and node.skill_id not in selected
    ]
    if missing_required:
        raise PlanValidationError(["required_node_removed"])
    order = request.preferred_order or selected
    if len(order) != len(set(order)) or set(order) != set(selected):
        raise PlanValidationError(["preferred_order_mismatch"])

    nodes: list[SkillPlanNode] = []
    for skill_id in selected:
        existing = existing_by_skill.get(skill_id)
        if existing is not None:
            nodes.append(existing.model_copy(update={"depends_on": [], "parallel_group": None}))
            continue
        candidate = candidate_by_id[skill_id]
        profile = candidate.profile
        nodes.append(
            SkillPlanNode(
                skill_id=skill_id,
                skill_version=profile.skill_version,
                skill_content_hash=profile.skill_content_hash,
                reason=candidate.reason,
                required=False,
                input_bindings=[],
                output_contract=[
                    output for output in plan.intent.deliverables if output in profile.output_kinds
                ][:1] or profile.output_kinds[:1],
                side_effect=profile.side_effect,
            )
        )
    position = {skill_id: index for index, skill_id in enumerate(order)}
    nodes.sort(key=lambda node: position[node.skill_id])
    user_inputs = set(plan.intent.input_kinds)
    regenerated: list[SkillPlanNode] = []
    for node in nodes:
        profile = candidate_by_id[node.skill_id].profile
        direct_inputs = [input_kind for input_kind in profile.input_kinds if input_kind in user_inputs]
        dependencies: list[str] = []
        bindings = [f"user.{input_kind}" for input_kind in direct_inputs]
        if not bindings:
            producers = [
                candidate_node
                for candidate_node in nodes
                if candidate_node.id != node.id
                and (not node.required or candidate_node.required)
                and set(candidate_node.output_contract) & set(profile.input_kinds)
            ]
            if producers:
                producer = min(producers, key=lambda item: position[item.skill_id])
                if position[producer.skill_id] >= position[node.skill_id]:
                    raise PlanValidationError(["preferred_order_breaks_dependency"])
                output_kind = next(
                    output for output in producer.output_contract if output in profile.input_kinds
                )
                dependencies = [producer.id]
                bindings = [f"{producer.id}.{output_kind}"]
            else:
                bindings = ["user.request"]
        regenerated.append(
            node.model_copy(update={"depends_on": dependencies, "input_bindings": bindings})
        )
    nodes = regenerated
    nodes = _recompute_parallel_groups(nodes)
    adjusted = plan.model_copy(deep=True)
    adjusted.nodes = nodes
    adjusted.preferred_order = order
    draft = SkillPlanDraft(output_contract=adjusted.output_contract, nodes=nodes)
    validate_draft(
        draft,
        [candidate_by_id[skill_id] for skill_id in selected],
        intent=plan.intent,
    )
    return adjusted
