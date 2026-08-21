from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import CompetitiveTextCatalog
from agentmesh.research_orchestration.v3.common import thaw_json_value
from agentmesh.research_orchestration.v3.execution_plan import (
    ExecutionPlanV3,
    ExecutionPlanVersionV3,
    PlanCandidateV3,
    PlanInputBindingV3,
    PlanStepProposalV3,
    PlanStepV3,
)
from agentmesh.research_orchestration.v3.ports import (
    CandidateCompilationRequestV3,
    ClockPort,
    IdGeneratorPort,
)
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.snapshots import ResearchControlSnapshotV3
from agentmesh.research_orchestration.v3.planning.models import PlanningArtifactPort
from agentmesh.research_orchestration.v3.planning.validation import validate_competitive_problem_graph


class CandidateCompilationError(ValueError):
    def __init__(self, *codes: str) -> None:
        self.codes = tuple(dict.fromkeys(codes))
        super().__init__(", ".join(self.codes))


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/"):
        raise CandidateCompilationError("json_pointer_invalid")
    tokens: list[str] = []
    for raw in pointer[1:].split("/"):
        index = 0
        while index < len(raw):
            if raw[index] == "~":
                if index + 1 >= len(raw) or raw[index + 1] not in {"0", "1"}:
                    raise CandidateCompilationError("json_pointer_invalid")
                index += 2
            else:
                index += 1
        tokens.append(raw.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


_MISSING = object()


def _resolve_pointer(document: object, pointer: str) -> object:
    current = document
    for token in _pointer_tokens(pointer):
        if isinstance(current, Mapping):
            current = current.get(token, _MISSING)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            if not token.isdigit():
                return _MISSING
            index = int(token)
            current = current[index] if index < len(current) else _MISSING
        else:
            return _MISSING
        if current is _MISSING:
            return _MISSING
    return current


def _topological_proposals(
    candidate: PlanCandidateV3,
) -> tuple[tuple[PlanStepProposalV3, ...], dict[int, int]]:
    by_proposed_number: dict[int, PlanStepProposalV3] = {}
    for step in candidate.proposed_steps:
        if step.proposed_step_number in by_proposed_number:
            raise CandidateCompilationError("candidate_step_identity_duplicate")
        by_proposed_number[step.proposed_step_number] = step
    known = set(by_proposed_number)
    for step in candidate.proposed_steps:
        if step.proposed_step_number in step.depends_on or not set(step.depends_on).issubset(known):
            raise CandidateCompilationError("candidate_dependency_invalid")

    remaining = list(candidate.proposed_steps)
    ordered: list[PlanStepProposalV3] = []
    emitted: set[int] = set()
    while remaining:
        ready = [step for step in remaining if set(step.depends_on).issubset(emitted)]
        if not ready:
            raise CandidateCompilationError("candidate_dependency_cycle")
        step = ready[0]
        ordered.append(step)
        emitted.add(step.proposed_step_number)
        remaining.remove(step)
    identity_map = {
        step.proposed_step_number: index
        for index, step in enumerate(ordered, start=1)
    }
    return tuple(ordered), identity_map


def _ancestors(steps: tuple[PlanStepV3, ...], step_number: int) -> set[int]:
    by_number = {step.step_number: step for step in steps}
    result: set[int] = set()
    pending = list(by_number[step_number].depends_on)
    while pending:
        dependency = pending.pop()
        if dependency in result:
            continue
        result.add(dependency)
        pending.extend(by_number[dependency].depends_on)
    return result


class CompetitiveTextCandidateCompiler:
    """Compiles non-authoritative proposals into immutable server-owned plans."""

    def __init__(
        self,
        *,
        catalog: CompetitiveTextCatalog,
        artifacts: PlanningArtifactPort,
        id_generator: IdGeneratorPort,
        clock: ClockPort,
    ) -> None:
        self._catalog = catalog
        self._artifacts = artifacts
        self._id_generator = id_generator
        self._clock = clock

    def _read_snapshot(self, request: CandidateCompilationRequestV3) -> ResearchControlSnapshotV3:
        reference = request.capabilities.control_snapshot_artifact
        snapshot = self._artifacts.read_control_snapshot(reference)
        if snapshot is None:
            raise CandidateCompilationError("control_snapshot_unavailable")
        if canonical_json_v3_sha256(snapshot) != reference.content_hash:
            raise CandidateCompilationError("control_snapshot_hash_mismatch")
        if snapshot.catalog_id != self._catalog.catalog_id or snapshot.catalog_hash != self._catalog.catalog_hash:
            raise CandidateCompilationError("control_snapshot_catalog_mismatch")
        return snapshot

    def _validate_resolution(self, request: CandidateCompilationRequestV3) -> None:
        required_gaps = [item.code for item in request.capabilities.gaps if item.required]
        if required_gaps:
            raise CandidateCompilationError(*required_gaps)
        expected_decisions = {
            *(('tool', item.id) for item in self._catalog.actors.tools),
            *(('skill', item.id) for item in self._catalog.actors.skills),
        }
        actual_decisions = {
            (item.actor_type, item.actor_id): item
            for item in request.capabilities.decisions
        }
        if set(actual_decisions) != expected_decisions:
            raise CandidateCompilationError("capability_decision_set_mismatch")
        tool_by_id = {item.id: item for item in self._catalog.actors.tools}
        for tool in self._catalog.actors.tools:
            decision = actual_decisions[("tool", tool.id)]
            approvals = tuple(
                (item.capability_type, item.capability_id, item.authority)
                for item in decision.required_approvals
            )
            if approvals != (("tool", tool.id, tool.approval_role),):
                raise CandidateCompilationError("capability_owner_approval_mismatch")
        for skill in self._catalog.actors.skills:
            decision = actual_decisions[("skill", skill.id)]
            expected_approvals = tuple(
                ("tool", tool_id, tool_by_id[tool_id].approval_role)
                for tool_id in skill.required_tools
            )
            actual_approvals = tuple(
                (item.capability_type, item.capability_id, item.authority)
                for item in decision.required_approvals
            )
            if actual_approvals != expected_approvals:
                raise CandidateCompilationError("capability_owner_approval_mismatch")
            optional_decisions = {
                item.tool_id: (item.status, item.reason_code)
                for item in decision.optional_tool_decisions
            }
            if optional_decisions != {
                tool_id: ("unavailable", "not_enabled_in_slice")
                for tool_id in skill.source_optional_tools
            }:
                raise CandidateCompilationError("optional_tool_decision_mismatch")
        excluded_ids = {item.id for item in self._catalog.excluded_source_capabilities}
        declared_exclusions = {
            item.capability_id
            for item in request.capabilities.gaps
            if not item.required
        }
        if declared_exclusions != excluded_ids:
            raise CandidateCompilationError("optional_capability_exclusions_missing")

    def _validate_coverage(
        self,
        candidate: PlanCandidateV3,
        graph: ProblemGraphV1,
    ) -> tuple[str, ...]:
        required = tuple(question.id for question in graph.questions if question.priority == "required")
        covered = {question_id for step in candidate.proposed_steps for question_id in step.question_ids}
        if covered != set(required):
            raise CandidateCompilationError("candidate_question_coverage_mismatch")
        tool_covered = {
            question_id
            for step in candidate.proposed_steps
            if step.actor_type == "tool" and step.actor_id == "tavily-web-search"
            for question_id in step.question_ids
        }
        if tool_covered != set(required):
            raise CandidateCompilationError("public_evidence_step_coverage_mismatch")
        return required

    @staticmethod
    def _expected_output_root(actor_type: str, actor_id: str, catalog: CompetitiveTextCatalog) -> str:
        if actor_type == "tool":
            return "/results"
        if actor_type == "skill":
            skill = next((item for item in catalog.actors.skills if item.id == actor_id), None)
            if skill is None:
                raise CandidateCompilationError("candidate_actor_unknown")
            return skill.output_root
        collection = catalog.actors.llm if actor_type == "llm" else catalog.actors.reviewers
        actor = next((item for item in collection if item.id == actor_id), None)
        if actor is None:
            raise CandidateCompilationError("candidate_actor_unknown")
        return actor.output_root

    def _compile_steps(
        self,
        request: CandidateCompilationRequestV3,
        snapshot: ResearchControlSnapshotV3,
    ) -> tuple[PlanStepV3, ...]:
        ordered, identity_map = _topological_proposals(request.candidate)
        actors = {(item.actor_type, item.actor_id): item for item in snapshot.actors}
        documents = {item.document_id: item for item in snapshot.documents}
        decisions = {
            (item.actor_type, item.actor_id): item
            for item in request.capabilities.decisions
        }
        excluded = {item.id for item in self._catalog.excluded_source_capabilities}
        compiled: list[PlanStepV3] = []
        for proposal in ordered:
            if proposal.actor_id in excluded:
                raise CandidateCompilationError("excluded_capability_in_candidate")
            actor = actors.get((proposal.actor_type, proposal.actor_id))
            if actor is None or not actor.enabled or not actor.eligible:
                raise CandidateCompilationError("candidate_actor_not_eligible")
            if proposal.actor_type in {"tool", "skill"}:
                decision = decisions.get((proposal.actor_type, proposal.actor_id))
                if decision is None or decision.status != "eligible":
                    raise CandidateCompilationError("candidate_actor_decision_not_eligible")
            if proposal.actor_type == "tool":
                tool = next((item for item in self._catalog.actors.tools if item.id == proposal.actor_id), None)
                if tool is None or actor.execution_mode != "real" or actor.tier != "core":
                    raise CandidateCompilationError("core_tool_real_adapter_unavailable")
                if (
                    not proposal.requires_approval
                    or proposal.approval_role != tool.approval_role
                    or actor.approval_role != tool.approval_role
                ):
                    raise CandidateCompilationError("tool_owner_approval_required")
            elif proposal.requires_approval:
                raise CandidateCompilationError("non_tool_step_cannot_replace_tool_approval")

            input_schema = documents.get(actor.input_schema_document_id)
            output_schema = documents.get(actor.output_schema_document_id)
            if input_schema is None or output_schema is None:
                raise CandidateCompilationError("actor_schema_snapshot_missing")
            expected_root = self._expected_output_root(
                proposal.actor_type,
                proposal.actor_id,
                self._catalog,
            )
            output_pointers = {item.pointer for item in proposal.expected_outputs}
            if expected_root not in output_pointers:
                raise CandidateCompilationError("actor_output_root_missing")
            for pointer in output_pointers:
                _pointer_tokens(pointer)

            mapped_dependencies = tuple(identity_map[item] for item in proposal.depends_on)
            mapped_bindings: list[PlanInputBindingV3] = []
            target_pointers: set[str] = set()
            for binding in proposal.input_bindings:
                _pointer_tokens(binding.source_pointer)
                _pointer_tokens(binding.target_pointer)
                if binding.source_step_number not in proposal.depends_on:
                    raise CandidateCompilationError("binding_source_not_direct_dependency")
                source_number = identity_map[binding.source_step_number]
                source = compiled[source_number - 1]
                if not any(
                    binding.source_pointer == output.pointer
                    or binding.source_pointer.startswith(f"{output.pointer}/")
                    for output in source.expected_outputs
                ):
                    raise CandidateCompilationError("binding_source_output_missing")
                if _resolve_pointer(thaw_json_value(proposal.input), binding.target_pointer) is _MISSING:
                    raise CandidateCompilationError("binding_target_missing")
                if binding.target_pointer in target_pointers:
                    raise CandidateCompilationError("binding_target_duplicate")
                target_pointers.add(binding.target_pointer)
                mapped_bindings.append(
                    PlanInputBindingV3(
                        source_step_number=source_number,
                        source_pointer=binding.source_pointer,
                        target_pointer=binding.target_pointer,
                    )
                )

            decision = decisions.get((proposal.actor_type, proposal.actor_id))
            if decision is not None:
                for pending in decision.pending_inputs:
                    target = f"/{pending.role.replace('~', '~0').replace('/', '~1')}"
                    value = _resolve_pointer(thaw_json_value(proposal.input), target)
                    if value is _MISSING or value is None:
                        raise CandidateCompilationError("pending_input_target_unresolved")

            values: dict[str, Any] = {
                "step_number": len(compiled) + 1,
                "name": proposal.name,
                "actor_type": proposal.actor_type,
                "actor_id": proposal.actor_id,
                "question_ids": proposal.question_ids,
                "depends_on": mapped_dependencies,
                "input": proposal.input,
                "input_bindings": tuple(mapped_bindings),
                "expected_outputs": proposal.expected_outputs,
                "acceptance_criteria": proposal.acceptance_criteria,
                "required": True,
                "requires_approval": proposal.requires_approval,
                "approval_role": proposal.approval_role,
                "timeout_seconds": 60 if proposal.actor_type == "tool" else 120,
                "max_sends": 2 if proposal.actor_type == "tool" else 1,
                "invocation_semantics": {
                    "tool": "tool_read",
                    "skill": "skill_once",
                    "llm": "llm_once",
                    "reviewer": "reviewer_once",
                }[proposal.actor_type],
                "actor_snapshot_hash": canonical_json_v3_sha256(actor),
                "input_schema_hash": input_schema.content_hash,
                "output_schema_hash": output_schema.content_hash,
            }
            values["contract_hash"] = canonical_json_v3_sha256(values)
            compiled.append(PlanStepV3.model_validate(values))
        return tuple(compiled)

    def _validate_required_tool_prerequisites(self, steps: tuple[PlanStepV3, ...]) -> None:
        skill_by_id = {item.id: item for item in self._catalog.actors.skills}
        by_number = {step.step_number: step for step in steps}
        for step in steps:
            if step.actor_type != "skill":
                continue
            skill = skill_by_id[step.actor_id]
            ancestors = _ancestors(steps, step.step_number)
            for tool_id in skill.required_tools:
                matching = {
                    number
                    for number in ancestors
                    if by_number[number].actor_type == "tool" and by_number[number].actor_id == tool_id
                }
                if not matching:
                    raise CandidateCompilationError("required_tool_prerequisite_missing")
                if not any(binding.source_step_number in matching for binding in step.input_bindings):
                    raise CandidateCompilationError("required_tool_binding_missing")

    @staticmethod
    def _validate_problem_dependencies(steps: tuple[PlanStepV3, ...], graph: ProblemGraphV1) -> None:
        question_steps: dict[str, set[int]] = defaultdict(set)
        for step in steps:
            for question_id in step.question_ids:
                question_steps[question_id].add(step.step_number)
        for question in graph.questions:
            for step_number in question_steps[question.id]:
                ancestors = _ancestors(steps, step_number)
                for dependency_id in question.depends_on:
                    if dependency_id in steps[step_number - 1].question_ids:
                        continue
                    if not (question_steps[dependency_id] & ancestors):
                        raise CandidateCompilationError("problem_dependency_not_preserved")

    def compile(self, request: CandidateCompilationRequestV3) -> ExecutionPlanV3:
        if request.requirement.payload.planning_blocked:
            raise CandidateCompilationError("requirement_clarification_required")
        self._validate_resolution(request)
        evidence_policy = validate_competitive_problem_graph(
            request.problem_graph,
            request.requirement.payload,
            self._catalog,
        )
        self._validate_coverage(request.candidate, request.problem_graph)
        snapshot = self._read_snapshot(request)
        steps = self._compile_steps(request, snapshot)
        self._validate_required_tool_prerequisites(steps)
        self._validate_problem_dependencies(steps, request.problem_graph)
        activated_nodes = tuple(item.id for item in self._catalog.decision_nodes)
        return ExecutionPlanV3(
            schema_version="execution-plan-v3",
            task_type="competitive_research",
            requirement_version_id=request.requirement.id,
            requirement_content_hash=request.requirement.content_hash,
            problem_graph_artifact=request.problem_graph_artifact,
            candidate_id=request.candidate.candidate_id,
            deliverable_type="competitive_analysis_report",
            payload_schema_version="competitive-analysis-text-v1",
            evidence_requirements=evidence_policy,
            capability_decisions=request.capabilities.decisions,
            capability_gaps=request.capabilities.gaps,
            steps=steps,
            candidate_title=request.candidate.title,
            candidate_rationale=request.candidate.rationale,
            candidate_tradeoffs=request.candidate.tradeoffs,
            activated_nodes=activated_nodes,
            control_snapshot_artifact=request.capabilities.control_snapshot_artifact,
        )

    def compile_version(
        self,
        *,
        run_id: str,
        version: int,
        request: CandidateCompilationRequestV3,
    ) -> ExecutionPlanVersionV3:
        if request.requirement.run_id != run_id:
            raise CandidateCompilationError("plan_run_mismatch")
        plan = self.compile(request)
        return ExecutionPlanVersionV3(
            id=self._id_generator.new("plan"),
            run_id=run_id,
            requirement_version_id=request.requirement.id,
            version=version,
            schema_version="execution-plan-v3",
            plan_hash=canonical_json_v3_sha256(plan),
            payload=plan,
            created_at=self._clock.now(),
        )
