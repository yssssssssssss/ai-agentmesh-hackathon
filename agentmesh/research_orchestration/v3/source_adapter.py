from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Literal

from agentmesh.research_orchestration.v3.execution_plan import (
    ExpectedOutputV3,
    PlanCandidateV3,
    PlanInputBindingV3,
    PlanStepProposalV3,
)
from agentmesh.research_orchestration.v3.problem_graph import (
    EvidenceRequirementV1,
    ProblemGraphProvenanceV1,
    ProblemGraphV1,
    ProblemQuestionV1,
)
from agentmesh.research_orchestration.v3.requirement import (
    BlockingIssueV3,
    ClarificationQuestionV3,
    ResearchAmbiguityV3,
    ResearchAssumptionV3,
    ResearchConstraintV3,
    ResearchTaskV3,
    SuccessCriterionV3,
)
from agentmesh.research_orchestration.v3.source_contracts import (
    AiXCurrentExecutionPlan,
    AiXProblemGraphV1,
    AiXResearchTaskV2,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


def _source(value: Any, model_type: type[Any]) -> Any:
    if isinstance(value, model_type):
        return value
    return model_type.model_validate(value)


def _identifier(value: str, prefix: str) -> str:
    if _IDENTIFIER.fullmatch(value):
        return value
    slug = re.sub(r"[^A-Za-z0-9._:-]+", "-", value.strip()).strip("-._:").lower()
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    candidate = f"{prefix}_{slug[:80]}_{digest}" if slug else f"{prefix}_{digest}"
    return candidate[:120]


def translate_ai_x_research_task_v2(source: AiXResearchTaskV2 | Mapping[str, Any]) -> ResearchTaskV3:
    """Translate the colliding ai-x research-task-v2 name before target validation."""

    item = _source(source, AiXResearchTaskV2)
    if item.task_type != "competitive_research":
        raise ValueError("Slice 1 accepts only competitive_research source tasks")
    return ResearchTaskV3(
        schema_version="research-task-v3",
        task_type="competitive_research",
        business_domain=item.business_domain,
        research_goal=item.research_goal,
        comparison_dimensions=item.comparison_dimensions,
        target_audience=item.target_audience,
        scope=item.scope,
        constraints=tuple(
            ResearchConstraintV3(
                id=_identifier(value.id, "constraint"),
                statement=value.statement,
                source=value.source,
            )
            for value in item.constraints
        ),
        success_criteria=tuple(
            SuccessCriterionV3(
                id=_identifier(value.id, "criterion"),
                statement=value.statement,
            )
            for value in item.success_criteria
        ),
        expected_deliverables=tuple(item.expected_deliverables),
        assumptions=tuple(
            ResearchAssumptionV3(
                key=_identifier(value.key, "assumption"),
                value=value.value,
                editable=value.editable,
            )
            for value in item.assumptions
        ),
        ambiguities=tuple(
            ResearchAmbiguityV3(
                id=_identifier(value.id, "ambiguity"),
                statement=value.statement,
                blocking=value.blocking,
            )
            for value in item.ambiguities
        ),
        clarification_questions=tuple(
            ClarificationQuestionV3(
                key=_identifier(value.key, "clarification"),
                question=value.question,
                rationale=value.rationale,
            )
            for value in item.clarification_questions
        ),
        blocking_issues=tuple(
            BlockingIssueV3(
                key=_identifier(value.key, "blocking"),
                reason=value.reason,
                kind=_identifier(value.kind, "kind"),
            )
            for value in item.blocking_issues
        ),
        sensitivity=item.sensitivity,
        pii_detected=item.pii_detected,
    )


def translate_ai_x_problem_graph_v1(
    source: AiXProblemGraphV1 | Mapping[str, Any],
    *,
    requirement_version_id: str,
    model_call_receipt_id: str,
    model_name: str,
    model_version: str,
    prompt_hash: str,
    trace_id: str,
    context_manifest_hash: str,
) -> ProblemGraphV1:
    item = _source(source, AiXProblemGraphV1)
    question_id_map = {value.id: _identifier(value.id, "question") for value in item.questions}
    return ProblemGraphV1(
        schema_version="problem-graph-v1",
        requirement_version_id=requirement_version_id,
        questions=tuple(
            ProblemQuestionV1(
                id=question_id_map[value.id],
                statement=value.statement,
                rationale=value.rationale,
                priority=value.priority,
                success_criterion_ids=tuple(
                    _identifier(criterion_id, "criterion") for criterion_id in value.success_criterion_ids
                ),
                evidence_requirements=tuple(
                    EvidenceRequirementV1(
                        id=_identifier(requirement.id, "evidence"),
                        accepted_classes=requirement.acceptedClasses,
                        minimum_count=requirement.minimumCount,
                        required=requirement.required,
                    )
                    for requirement in value.evidence_requirements
                ),
                acceptance_criteria=value.acceptance_criteria,
                depends_on=tuple(question_id_map[dependency_id] for dependency_id in value.depends_on),
            )
            for value in item.questions
        ),
        provenance=ProblemGraphProvenanceV1(
            model_call_receipt_id=model_call_receipt_id,
            model_name=model_name,
            model_version=model_version,
            prompt_hash=prompt_hash,
            trace_id=trace_id,
            context_manifest_hash=context_manifest_hash,
        ),
    )


def translate_ai_x_current_execution_plan(
    source: AiXCurrentExecutionPlan | Mapping[str, Any],
    *,
    candidate_id: Literal["depth", "speed"],
) -> PlanCandidateV3:
    """Translate a source plan into a non-authoritative candidate proposal.

    Server-owned compilation, actor resolution, numbering, snapshots, and hashes happen
    behind the later CandidateCompilerPort; this adapter cannot create a persisted plan.
    """

    item = _source(source, AiXCurrentExecutionPlan)
    if item.deliverable_type != "competitive_analysis_report":
        raise ValueError("Slice 1 accepts only the competitive_analysis_report deliverable")
    if any(step.fallback_actor_ids for step in item.steps):
        raise ValueError("source fallback actor lists are not legal in research-v3")
    return PlanCandidateV3(
        candidate_id=candidate_id,
        title=item.candidate_metadata.title,
        rationale=item.candidate_metadata.rationale,
        tradeoffs=item.candidate_metadata.tradeoffs,
        assumptions=(),
        proposed_steps=tuple(
            PlanStepProposalV3(
                proposed_step_number=step.step_no,
                name=step.step_name,
                actor_type=step.actor_type,
                actor_id=_identifier(step.actor_id, "actor"),
                question_ids=tuple(_identifier(value, "question") for value in step.question_ids),
                depends_on=step.depends_on,
                input=step.input,
                input_bindings=tuple(
                    PlanInputBindingV3(
                        source_step_number=binding.source_step_no,
                        source_pointer=binding.source_pointer,
                        target_pointer=binding.target_pointer,
                    )
                    for binding in step.input_bindings
                ),
                expected_outputs=tuple(
                    ExpectedOutputV3(pointer=output.pointer, description=output.description)
                    for output in step.expected_outputs
                ),
                acceptance_criteria=step.acceptance_criteria,
                requires_approval=step.requires_approval,
                approval_role=step.approval_role,
            )
            for step in item.steps
        ),
    )
