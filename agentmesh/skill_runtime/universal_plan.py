"""Server-owned materialization and coverage checks for Universal Skill plans."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from agentmesh.models import (
    Artifact,
    ArtifactVerificationState,
    CandidateIdentityV1,
    CandidateSnapshotV1,
    DeliverableAtomV1,
    EvidenceAtomV1,
    ScenarioOutputAtomV1,
    SkillCandidate,
    SkillDefinition,
    SkillIntent,
    SkillNodeResult,
    SkillPlan,
    SkillPlanDraft,
    SkillPlanKnowledgeBindings,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillSynthesisResult,
)
from agentmesh.skill_runtime.plan_validation import PlanValidationError, validate_draft
from agentmesh.skill_runtime.profiles import tool_names_for_profile
from agentmesh.skill_runtime.resources import build_skill_resource_manifest_snapshot
from agentmesh.task_routing.catalog import TaskCatalogV2
from agentmesh.task_routing.contracts import CompletionCheckResult, TaskRoutingResult


def _route_scenario_ids(routing: TaskRoutingResult | None) -> tuple[str, ...]:
    if routing is None:
        return ()
    return tuple(
        dict.fromkeys(
            [routing.scenario.scenario_id, *routing.scenario.supporting_scenarios]
        )
    )


def scenario_assignment_options(
    *,
    node: SkillPlanNode,
    routing: TaskRoutingResult | None,
    catalog: TaskCatalogV2,
) -> tuple[str, ...]:
    node_outputs = set(node.output_contract)
    options: list[str] = []
    for scenario_id in _route_scenario_ids(routing):
        scenario = catalog.get_scenario(scenario_id)
        if scenario is None:
            continue
        if any(node_outputs.intersection(output.compatible_output_kinds) for output in scenario.outputs):
            options.append(scenario.id)
    return tuple(options)


def _candidate_identity(snapshot: CandidateSnapshotV1, skill_id: str) -> CandidateIdentityV1:
    candidate = next((item for item in snapshot.candidates if item.skill_id == skill_id), None)
    if candidate is None:
        raise PlanValidationError(["unknown_skill"])
    return candidate


def _node_possible_coverage(
    node: SkillPlanNode,
    snapshot: CandidateSnapshotV1,
    catalog: TaskCatalogV2,
    routing: TaskRoutingResult | None,
) -> set[str]:
    identity = _candidate_identity(snapshot, node.skill_id)
    node_outputs = set(node.output_contract)
    covered: set[str] = set()
    options = scenario_assignment_options(node=node, routing=routing, catalog=catalog)
    allowed_scenarios = {node.scenario_id} if node.scenario_id is not None else set(options)
    for atom in snapshot.required_coverage_atoms:
        covers_deliverable = (
            isinstance(atom, DeliverableAtomV1) and atom.output_kind in node_outputs
        )
        covers_scenario = (
            isinstance(atom, ScenarioOutputAtomV1)
            and atom.scenario_id in allowed_scenarios
            and bool(node_outputs.intersection(atom.compatible_output_kinds))
        )
        covers_evidence = isinstance(atom, EvidenceAtomV1) and any(
            witness.atom_id == atom.id for witness in identity.evidence_path_witnesses
        )
        if covers_deliverable or covers_scenario or covers_evidence:
            covered.add(atom.id)
    return covered


def validate_universal_plan(
    *,
    plan: SkillPlan,
    candidates: list[SkillCandidate],
    catalog: TaskCatalogV2,
    require_concrete_assignments: bool,
) -> None:  # noqa: ANN001
    snapshot = plan.candidate_snapshot
    if snapshot is None:
        raise PlanValidationError(["candidate_snapshot_missing"])
    errors: list[str] = []
    candidate_by_id = {candidate.skill_id: candidate for candidate in candidates}
    for node in plan.nodes:
        candidate = candidate_by_id.get(node.skill_id)
        identity = next(
            (item for item in snapshot.candidates if item.skill_id == node.skill_id),
            None,
        )
        if candidate is None or identity is None:
            errors.append("unknown_skill")
            continue
        if (
            node.skill_version != identity.skill_version
            or node.skill_content_hash != identity.skill_content_hash
            or candidate.profile.profile_version != identity.profile_version
            or candidate.profile.profile_content_hash != identity.profile_content_hash
        ):
            errors.append("candidate_snapshot_stale")
        if node.skill_registry_id is not None or node.skill_status is not None:
            errors.append("universal_registry_metadata_forbidden")
        if node.knowledge_bindings != SkillPlanKnowledgeBindings():
            errors.append("universal_knowledge_binding_forbidden")
        if node.resource_manifest is None:
            errors.append("resource_manifest_missing")
        if set(node.required_tool_names) != tool_names_for_profile(candidate.profile):
            errors.append("required_tool_mismatch")
        options = scenario_assignment_options(
            node=node,
            routing=plan.routing_result,
            catalog=catalog,
        )
        if node.scenario_id is not None and node.scenario_id not in options:
            errors.append("scenario_assignment_invalid")
        if require_concrete_assignments and len(options) > 1 and node.scenario_id is None:
            errors.append("scenario_assignment_required")
    if not set(snapshot.required_synthesis_output_ids).issubset(plan.synthesis_output_contract):
        errors.append("required_synthesis_output_missing")
    strict_coverage = {
        atom_id
        for node in plan.nodes
        for atom_id in _node_possible_coverage(node, snapshot, catalog, plan.routing_result)
        if node.scenario_id is not None
        or atom_id
        not in {
            atom.id
            for atom in snapshot.required_coverage_atoms
            if isinstance(atom, ScenarioOutputAtomV1)
        }
    }
    expected_gaps = [
        atom.id for atom in snapshot.required_coverage_atoms if atom.id not in strict_coverage
    ]
    expected_gaps.extend(
        f"scenario_assignment_required:{node.skill_id}"
        for node in plan.nodes
        if len(
            scenario_assignment_options(
                node=node,
                routing=plan.routing_result,
                catalog=catalog,
            )
        )
        > 1
        and node.scenario_id is None
    )
    if plan.capability_gaps != list(dict.fromkeys(expected_gaps)):
        errors.append("capability_gaps_mismatch")
    if errors:
        raise PlanValidationError(errors)


def covered_result_atom_ids(
    *,
    plan: SkillPlan,
    results: list[SkillNodeResult],
    evidence_artifact_valid: Callable[[str], bool] = lambda _artifact_id: False,
) -> tuple[str, ...]:
    snapshot = plan.candidate_snapshot
    if snapshot is None:
        return ()
    node_by_id = {node.id: node for node in plan.nodes}
    candidate_by_skill = {candidate.skill_id: candidate for candidate in snapshot.candidates}
    covered: set[str] = set()
    for result in results:
        node = node_by_id.get(result.node_id)
        identity = candidate_by_skill.get(result.skill_id)
        if (
            node is None
            or identity is None
            or node.skill_id != result.skill_id
            or node.status is not SkillPlanNodeStatus.COMPLETED
            or result.delivered_output_kinds is None
            or (not result.deliverable_markdown.strip() and not result.artifact_ids)
        ):
            continue
        delivered = set(result.delivered_output_kinds)
        for atom in snapshot.required_coverage_atoms:
            covers_deliverable = (
                isinstance(atom, DeliverableAtomV1) and atom.output_kind in delivered
            )
            covers_scenario = (
                isinstance(atom, ScenarioOutputAtomV1)
                and node.scenario_id == atom.scenario_id
                and atom.output_id in result.scenario_outputs
                and bool(delivered.intersection(atom.compatible_output_kinds))
            )
            covers_evidence = isinstance(atom, EvidenceAtomV1) and any(
                witness.atom_id == atom.id for witness in identity.evidence_path_witnesses
            ) and any(
                evidence.artifact_id in result.artifact_ids
                and evidence_artifact_valid(evidence.artifact_id)
                for evidence in result.evidence_items
            )
            if covers_deliverable or covers_scenario or covers_evidence:
                covered.add(atom.id)
    return tuple(
        atom.id for atom in snapshot.required_coverage_atoms if atom.id in covered
    )


def _evidence_policy_satisfied(
    *,
    plan: SkillPlan,
    results: list[SkillNodeResult],
    evidence_artifact_valid: Callable[[str], bool],
    evidence_source_identity: Callable[[str], str | None],
    evidence_freshness_valid: Callable[[str, str], bool],
) -> bool:
    requirement = (
        plan.routing_result.evidence_requirement
        if plan.routing_result is not None
        else None
    )
    valid_evidence_items = [
        item
        for result in results
        for item in result.evidence_items
        if item.source_id is not None
        and item.source_id in {source.id for source in result.sources}
        and evidence_artifact_valid(item.evidence_artifact_id)
        and (
            requirement is None
            or requirement.freshness is None
            or evidence_freshness_valid(
                item.evidence_artifact_id,
                requirement.freshness,
            )
        )
    ]
    valid_source_ids = {item.source_id for item in valid_evidence_items}
    independent_origins = {
        identity
        for source_id in valid_source_ids
        if (identity := evidence_source_identity(source_id)) is not None
    }
    return bool(
        len(valid_source_ids)
        >= max(1, requirement.minimum_sources if requirement is not None else 0)
        and len(independent_origins)
        >= max(1, requirement.independent_sources if requirement is not None else 0)
    )


def evaluate_universal_completion(
    *,
    plan: SkillPlan,
    results: list[SkillNodeResult],
    synthesis: SkillSynthesisResult | None,
    synthesis_artifacts_sealed: bool,
    evidence_artifact_valid: Callable[[str], bool] = lambda _artifact_id: False,
    evidence_source_identity: Callable[[str], str | None] = lambda source_id: source_id,
    evidence_freshness_valid: Callable[[str, str], bool] = lambda _artifact_id, _freshness: False,
) -> CompletionCheckResult:
    if plan.candidate_snapshot is None:
        raise ValueError("candidate_snapshot_missing")
    snapshot = plan.candidate_snapshot
    covered = set(
        covered_result_atom_ids(
            plan=plan,
            results=results,
            evidence_artifact_valid=evidence_artifact_valid,
        )
    )
    if (
        any(isinstance(atom, EvidenceAtomV1) for atom in snapshot.required_coverage_atoms)
        and not _evidence_policy_satisfied(
            plan=plan,
            results=results,
            evidence_artifact_valid=evidence_artifact_valid,
            evidence_source_identity=evidence_source_identity,
            evidence_freshness_valid=evidence_freshness_valid,
        )
    ):
        covered.discard("evidence:trusted_external_path")
    missing = [
        atom.id for atom in snapshot.required_coverage_atoms if atom.id not in covered
    ]
    produced_synthesis = set(synthesis.presentation_outputs) if synthesis is not None else set()
    missing_synthesis = [
        output_id
        for output_id in snapshot.required_synthesis_output_ids
        if output_id not in produced_synthesis or not synthesis_artifacts_sealed
    ]
    assignment_gaps = [
        gap for gap in plan.capability_gaps if gap.startswith("scenario_assignment_required:")
    ]
    gaps = [*missing, *[f"synthesis:{value}" for value in missing_synthesis], *assignment_gaps]
    required_nodes = [node for node in plan.nodes if node.required]
    required_nodes_complete = bool(required_nodes) and all(
        node.status is SkillPlanNodeStatus.COMPLETED for node in required_nodes
    )
    criteria_specs: dict[str, tuple[str | None, str, str]] = {}
    for node in plan.nodes:
        for index, criterion in enumerate(node.completion_criteria):
            key = (
                f"scenario:{node.scenario_id}:criterion:{index}"
                if node.scenario_id is not None
                else f"node:{node.id}:criterion:{index}"
            )
            criteria_specs[key] = (node.scenario_id, node.id, criterion)
    criteria_results = {
        key: any(
            criterion in result.completion_criteria_met
            and (
                scenario_id is None
                and result.node_id == node_id
                or scenario_id is not None
                and any(
                    candidate.id == result.node_id
                    and candidate.scenario_id == scenario_id
                    for candidate in plan.nodes
                )
            )
            for result in results
        )
        for key, (scenario_id, node_id, criterion) in criteria_specs.items()
    }
    gaps.extend(
        f"completion_criterion_unmet:{key}"
        for key, satisfied in criteria_results.items()
        if not satisfied
    )
    return CompletionCheckResult(
        completed=required_nodes_complete and not gaps,
        scenario_outputs={atom_id: True for atom_id in covered if atom_id.startswith("scenario:")},
        missing_outputs=gaps,
        criteria_results=criteria_results,
        evidence_sufficient=not any(isinstance(atom, EvidenceAtomV1) for atom in snapshot.required_coverage_atoms)
        or "evidence:trusted_external_path" in covered,
        confidence=(
            "high"
            if required_nodes_complete and not gaps
            else "medium"
            if covered or produced_synthesis
            else "low"
        ),
        gaps=gaps,
        reason="all universal obligations satisfied" if required_nodes_complete and not gaps else "universal obligations incomplete",
    )


def has_valid_partial_delivery(
    *,
    plan: SkillPlan,
    results: list[SkillNodeResult],
    synthesis: SkillSynthesisResult | None = None,
    synthesis_artifacts_sealed: bool = False,
    evidence_artifact_valid: Callable[[str], bool] = lambda _artifact_id: False,
    evidence_source_identity: Callable[[str], str | None] = lambda source_id: source_id,
    evidence_freshness_valid: Callable[[str, str], bool] = lambda _artifact_id, _freshness: False,
) -> bool:
    snapshot = plan.candidate_snapshot
    covered = set(
        covered_result_atom_ids(
            plan=plan,
            results=results,
            evidence_artifact_valid=evidence_artifact_valid,
        )
    )
    if (
        snapshot is not None
        and any(isinstance(atom, EvidenceAtomV1) for atom in snapshot.required_coverage_atoms)
        and not _evidence_policy_satisfied(
            plan=plan,
            results=results,
            evidence_artifact_valid=evidence_artifact_valid,
            evidence_source_identity=evidence_source_identity,
            evidence_freshness_valid=evidence_freshness_valid,
        )
    ):
        covered.discard("evidence:trusted_external_path")
    if covered:
        return True
    return bool(
        synthesis is not None
        and synthesis_artifacts_sealed
        and set(synthesis.presentation_outputs).intersection(
            plan.candidate_snapshot.required_synthesis_output_ids
            if plan.candidate_snapshot is not None
            else ()
        )
        and results
    )


def persisted_universal_partial_delivery(
    *,
    plan: SkillPlan,
    results: list[SkillNodeResult],
    synthesis: SkillSynthesisResult | None,
    artifact_lookup: Callable[[str], Artifact | None],
) -> bool:
    def artifact_valid(
        artifact: Artifact | None,
        *,
        artifact_type: str,
        schema_version: str,
    ) -> bool:
        if (
            artifact is None
            or artifact.run_id != plan.run_id
            or artifact.plan_version_id != f"{plan.id}:v{plan.version}"
            or artifact.artifact_type != artifact_type
            or artifact.schema_version != schema_version
            or artifact.verification_state is not ArtifactVerificationState.SEALED
        ):
            return False
        content_bytes = artifact.content.encode()
        if (
            artifact.content_hash != hashlib.sha256(content_bytes).hexdigest()
            or artifact.size_bytes != len(content_bytes)
        ):
            return False
        try:
            from agentmesh.artifacts import DeepSearchArtifactSchemaRegistry

            parsed = DeepSearchArtifactSchemaRegistry.parse(
                artifact.artifact_type,
                artifact.schema_version,
                artifact.content,
            )
        except (TypeError, ValueError, RuntimeError):
            return False
        return bool(
            getattr(parsed, "run_id", None) == plan.run_id
            and getattr(parsed, "plan_id", None) == plan.id
            and getattr(parsed, "plan_version", None) == plan.version
        )

    def evidence_valid(artifact_id: str) -> bool:
        return artifact_valid(
            artifact_lookup(artifact_id),
            artifact_type="universal_tool_evidence",
            schema_version="universal-tool-evidence-v1",
        )

    synthesis_sealed = bool(
        synthesis is not None
        and any(
            artifact_valid(
                artifact_lookup(artifact_id),
                artifact_type="universal_synthesis",
                schema_version="universal-synthesis-v1",
            )
            for artifact_id in synthesis.artifact_ids
        )
    )
    return has_valid_partial_delivery(
        plan=plan,
        results=results,
        synthesis=synthesis,
        synthesis_artifacts_sealed=synthesis_sealed,
        evidence_artifact_valid=evidence_valid,
    )


def materialize_universal_draft(
    *,
    draft: SkillPlanDraft,
    intent: SkillIntent,
    candidates: list[SkillCandidate],
    snapshot: CandidateSnapshotV1,
    routing: TaskRoutingResult | None,
    catalog: TaskCatalogV2,
    skill_lookup: Callable[[str], SkillDefinition | None],
    scenario_assignments: dict[str, str | None] | None = None,
) -> SkillPlanDraft:
    validate_draft(draft, candidates, intent=intent, universal=True)
    candidate_by_id = {candidate.skill_id: candidate for candidate in candidates}
    requested_assignments = scenario_assignments or {}
    if set(requested_assignments) - {node.skill_id for node in draft.nodes}:
        raise PlanValidationError(["scenario_assignment_unknown_skill"])
    nodes: list[SkillPlanNode] = []
    assignment_gaps: list[str] = []
    for proposed in draft.nodes:
        candidate = candidate_by_id.get(proposed.skill_id)
        skill = skill_lookup(proposed.skill_id)
        if candidate is None or skill is None:
            raise PlanValidationError(["unknown_skill"])
        profile = candidate.profile
        current_manifest = build_skill_resource_manifest_snapshot(skill, profile)
        if proposed.resource_manifest is not None:
            if proposed.resource_manifest != current_manifest:
                raise PlanValidationError(["skill_resource_changed"])
            resource_manifest = proposed.resource_manifest
        else:
            resource_manifest = current_manifest
        node = proposed.model_copy(
            deep=True,
            update={
                "skill_version": skill.version,
                "skill_content_hash": skill.content_hash,
                "skill_registry_id": None,
                "skill_status": None,
                "knowledge_bindings": SkillPlanKnowledgeBindings(),
                "required_tool_names": sorted(tool_names_for_profile(profile)),
                "resource_manifest": resource_manifest,
                "side_effect": profile.side_effect,
                "task_id": None,
                "scenario_id": None,
                "completion_criteria": [],
            },
        )
        options = scenario_assignment_options(node=node, routing=routing, catalog=catalog)
        requested_assignment = requested_assignments.get(node.skill_id)
        if requested_assignment is not None:
            if requested_assignment not in options:
                raise PlanValidationError(["scenario_assignment_invalid"])
            options = (requested_assignment,)
        if len(options) == 1:
            scenario = catalog.get_scenario(options[0])
            assert scenario is not None
            node = node.model_copy(
                update={
                    "task_id": scenario.parent_task,
                    "scenario_id": scenario.id,
                    "completion_criteria": list(scenario.completion_criteria),
                }
            )
        elif len(options) > 1:
            assignment_gaps.append(f"scenario_assignment_required:{node.skill_id}")
        nodes.append(node)

    possible_coverage = {
        atom_id
        for node in nodes
        for atom_id in _node_possible_coverage(node, snapshot, catalog, routing)
    }
    if not set(snapshot.plannable_coverage_atom_ids).issubset(possible_coverage):
        raise PlanValidationError(["planner_coverage_unresolved"])
    strict_coverage: set[str] = set()
    scenario_atom_ids = {
        atom.id for atom in snapshot.required_coverage_atoms if isinstance(atom, ScenarioOutputAtomV1)
    }
    for node in nodes:
        node_coverage = _node_possible_coverage(node, snapshot, catalog, routing)
        if node.scenario_id is None and scenario_assignment_options(
            node=node,
            routing=routing,
            catalog=catalog,
        ):
            node_coverage -= scenario_atom_ids
        strict_coverage.update(node_coverage)
    capability_gaps = [
        atom.id
        for atom in snapshot.required_coverage_atoms
        if atom.id not in strict_coverage
    ]
    capability_gaps.extend(assignment_gaps)
    return draft.model_copy(
        update={
            "nodes": nodes,
            "synthesis_output_contract": list(
                dict.fromkeys(
                    [
                        *snapshot.required_synthesis_output_ids,
                        *draft.synthesis_output_contract,
                    ]
                )
            ),
            "capability_gaps": list(dict.fromkeys(capability_gaps)),
        }
    )
