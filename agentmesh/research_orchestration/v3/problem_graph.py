from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from agentmesh.research_orchestration.v3.common import (
    EvidenceClass,
    Identifier,
    NonBlankString,
    Sha256Hex,
    StrictFrozenModel,
    require_unique,
)
from agentmesh.research_orchestration.v3.requirement import ResearchTaskV3


class EvidenceRequirementV1(StrictFrozenModel):
    id: Identifier
    accepted_classes: tuple[EvidenceClass, ...] = Field(min_length=1, max_length=7)
    minimum_count: Annotated[int, Field(ge=1, le=20)]
    required: bool

    @model_validator(mode="after")
    def validate_classes(self) -> EvidenceRequirementV1:
        require_unique(self.accepted_classes, "accepted evidence classes")
        return self


class ProblemQuestionV1(StrictFrozenModel):
    id: Identifier
    statement: Annotated[NonBlankString, Field(max_length=2000)]
    rationale: Annotated[NonBlankString, Field(max_length=2000)]
    priority: Literal["required", "optional"]
    success_criterion_ids: tuple[Identifier, ...] = Field(max_length=20)
    evidence_requirements: tuple[EvidenceRequirementV1, ...] = Field(max_length=20)
    acceptance_criteria: tuple[Annotated[NonBlankString, Field(max_length=1000)], ...] = Field(
        min_length=1,
        max_length=20,
    )
    depends_on: tuple[Identifier, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_question(self) -> ProblemQuestionV1:
        require_unique(self.success_criterion_ids, "question success criterion IDs")
        require_unique(tuple(item.id for item in self.evidence_requirements), "question evidence requirement IDs")
        require_unique(self.acceptance_criteria, "question acceptance criteria")
        require_unique(self.depends_on, "question dependencies")
        if self.priority == "required" and not self.success_criterion_ids:
            raise ValueError("required questions must reference a success criterion")
        if self.priority == "required" and not any(item.required for item in self.evidence_requirements):
            raise ValueError("required questions must contain a required evidence requirement")
        return self


class ProblemGraphProvenanceV1(StrictFrozenModel):
    model_call_receipt_id: Identifier
    model_name: Annotated[NonBlankString, Field(max_length=120)]
    model_version: Annotated[NonBlankString, Field(max_length=120)]
    prompt_hash: Sha256Hex
    trace_id: Identifier
    context_manifest_hash: Sha256Hex


class ProblemGraphV1(StrictFrozenModel):
    model_config = ConfigDict(json_schema_extra={"$id": "problem-graph-v1"})

    schema_version: Literal["problem-graph-v1"] = "problem-graph-v1"
    requirement_version_id: Identifier
    questions: tuple[ProblemQuestionV1, ...] = Field(min_length=1, max_length=20)
    provenance: ProblemGraphProvenanceV1

    @model_validator(mode="after")
    def validate_graph(self) -> ProblemGraphV1:
        question_ids = tuple(question.id for question in self.questions)
        require_unique(question_ids, "problem question IDs")
        known = set(question_ids)
        dependencies = {question.id: set(question.depends_on) for question in self.questions}
        for question_id, dependency_ids in dependencies.items():
            if question_id in dependency_ids or not dependency_ids.issubset(known):
                raise ValueError("problem question dependencies must reference other graph questions")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(question_id: str) -> None:
            if question_id in visiting:
                raise ValueError("problem question dependencies contain a cycle")
            if question_id in visited:
                return
            visiting.add(question_id)
            for dependency_id in dependencies[question_id]:
                visit(dependency_id)
            visiting.remove(question_id)
            visited.add(question_id)

        for question_id in question_ids:
            visit(question_id)
        return self


def validate_problem_graph_for_task(
    graph: ProblemGraphV1,
    task: ResearchTaskV3,
    *,
    policy_requirements: tuple[EvidenceRequirementV1, ...] = (),
) -> None:
    """Validate coverage that needs both immutable contracts.

    Receipt ownership/stage checks remain a repository responsibility because those
    records are intentionally not reachable from this foundation package.
    """

    criterion_ids = {criterion.id for criterion in task.success_criteria}
    referenced = {
        criterion_id
        for question in graph.questions
        for criterion_id in question.success_criterion_ids
    }
    required_coverage = {
        criterion_id
        for question in graph.questions
        if question.priority == "required"
        for criterion_id in question.success_criterion_ids
    }
    if not referenced.issubset(criterion_ids):
        raise ValueError("problem graph references an unknown success criterion")
    if required_coverage != criterion_ids:
        raise ValueError("required questions must cover every success criterion")

    graph_requirements = {
        requirement.id: requirement
        for question in graph.questions
        if question.priority == "required"
        for requirement in question.evidence_requirements
        if requirement.required
    }
    for policy in policy_requirements:
        matched = graph_requirements.get(policy.id)
        if matched is None:
            raise ValueError(f"problem graph does not cover required evidence policy {policy.id}")
        if set(matched.accepted_classes) != set(policy.accepted_classes):
            raise ValueError(f"evidence classes do not match policy {policy.id}")
        if matched.minimum_count < policy.minimum_count:
            raise ValueError(f"evidence minimum is below policy {policy.id}")
