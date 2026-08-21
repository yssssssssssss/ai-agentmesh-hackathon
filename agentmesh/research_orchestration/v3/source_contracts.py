from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from agentmesh.research_orchestration.v3.common import NonBlankString, StrictFrozenModel


class AiXConstraintV2(StrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString
    source: Literal["user", "policy"]


class AiXSuccessCriterionV2(StrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString


class AiXAssumptionV2(StrictFrozenModel):
    key: NonBlankString
    value: str
    editable: bool


class AiXAmbiguityV2(StrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString
    blocking: bool


class AiXClarificationQuestionV2(StrictFrozenModel):
    key: NonBlankString
    question: NonBlankString
    rationale: NonBlankString


class AiXBlockingIssueV2(StrictFrozenModel):
    key: NonBlankString
    reason: NonBlankString
    kind: NonBlankString


class AiXResearchTaskV2(StrictFrozenModel):
    """Frozen ai-x input shape; this is never a target registry contract."""

    version: Literal["research-task-v2"] = "research-task-v2"
    task_type: Literal[
        "competitive_research",
        "user_research_planning",
        "voc_diagnosis",
        "design_audit",
        "a11y_audit",
    ]
    business_domain: NonBlankString
    research_goal: NonBlankString
    comparison_dimensions: tuple[NonBlankString, ...] | None = Field(default=None, min_length=2)
    target_audience: tuple[NonBlankString, ...]
    scope: tuple[NonBlankString, ...]
    constraints: tuple[AiXConstraintV2, ...]
    success_criteria: tuple[AiXSuccessCriterionV2, ...] = Field(min_length=1)
    expected_deliverables: tuple[NonBlankString, ...] = Field(min_length=1)
    assumptions: tuple[AiXAssumptionV2, ...]
    ambiguities: tuple[AiXAmbiguityV2, ...]
    clarification_questions: tuple[AiXClarificationQuestionV2, ...]
    blocking_issues: tuple[AiXBlockingIssueV2, ...]
    sensitivity: Literal["public", "internal", "confidential"]
    pii_detected: bool


class AiXEvidenceRequirementV1(StrictFrozenModel):
    id: NonBlankString
    acceptedClasses: tuple[
        Literal[
            "public_source",
            "screenshot",
            "user_input",
            "knowledge",
            "dataset",
            "simulation",
            "derived",
        ],
        ...,
    ] = Field(min_length=1)
    minimumCount: int = Field(ge=1)
    required: bool


class AiXProblemQuestionV1(StrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString
    rationale: NonBlankString
    priority: Literal["required", "optional"]
    success_criterion_ids: tuple[NonBlankString, ...]
    evidence_requirements: tuple[AiXEvidenceRequirementV1, ...]
    acceptance_criteria: tuple[NonBlankString, ...] = Field(min_length=1)
    depends_on: tuple[NonBlankString, ...]


class AiXProblemGraphV1(StrictFrozenModel):
    version: Literal["problem-graph-v1"] = "problem-graph-v1"
    questions: tuple[AiXProblemQuestionV1, ...] = Field(min_length=1)


class AiXPlanInputBinding(StrictFrozenModel):
    target_pointer: str = Field(pattern=r"^/")
    source_step_no: int = Field(ge=1)
    source_pointer: str = Field(pattern=r"^/")


class AiXExpectedOutput(StrictFrozenModel):
    pointer: str = Field(pattern=r"^/")
    description: NonBlankString


class AiXCurrentPlanStep(StrictFrozenModel):
    step_no: int = Field(ge=1)
    step_name: NonBlankString
    actor_type: Literal["tool", "skill", "llm", "reviewer"]
    actor_id: NonBlankString
    question_ids: tuple[NonBlankString, ...] = Field(min_length=1)
    depends_on: tuple[int, ...]
    input: dict[str, Any]
    input_bindings: tuple[AiXPlanInputBinding, ...]
    expected_outputs: tuple[AiXExpectedOutput, ...] = Field(min_length=1)
    acceptance_criteria: tuple[NonBlankString, ...] = Field(min_length=1)
    requires_approval: bool
    approval_role: Literal["owner", "legal", "security"] | None = None
    fallback_actor_ids: tuple[NonBlankString, ...]


class AiXCandidateMetadata(StrictFrozenModel):
    title: NonBlankString
    rationale: NonBlankString
    tradeoffs: NonBlankString


class AiXCurrentExecutionPlan(StrictFrozenModel):
    """Source proposal shape, deliberately not accepted as an executable target plan."""

    task_id: str
    deliverable_type: NonBlankString
    evidence_requirements: tuple[AiXEvidenceRequirementV1, ...]
    problem_graph: AiXProblemGraphV1
    problem_graph_provenance: dict[str, Any]
    capability_decisions: dict[str, Any]
    capability_gaps: tuple[dict[str, Any], ...] = ()
    steps: tuple[AiXCurrentPlanStep, ...] = Field(min_length=1)
    candidate_metadata: AiXCandidateMetadata
    activated_nodes: tuple[NonBlankString, ...]


class AiXResearchDeliverableV1(StrictFrozenModel):
    version: Literal["research-deliverable-v1"] = "research-deliverable-v1"
    taskId: NonBlankString
    planVersionId: NonBlankString
    attemptId: NonBlankString
    deliverableType: NonBlankString
    evidenceManifestArtifactId: NonBlankString
    methodSummary: NonBlankString
    findingGraph: dict[str, Any]
    payload: dict[str, Any]
    recommendations: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]
    risksAndOpenIssues: tuple[str, ...]
    capabilityProvenance: tuple[dict[str, Any], ...]


class AiXReviewDimensionV1(StrictFrozenModel):
    id: NonBlankString
    passed: bool
    issues: tuple[str, ...]


class AiXReportReviewV1(StrictFrozenModel):
    version: Literal["report-review-v1"] = "report-review-v1"
    taskId: NonBlankString
    planVersionId: NonBlankString
    attemptId: NonBlankString
    deliverableArtifactId: NonBlankString
    verdict: Literal["pass", "revise", "block"]
    dimensions: tuple[AiXReviewDimensionV1, ...]
    revisionRound: Literal[0, 1]


class AiXReportDocumentV1(StrictFrozenModel):
    version: Literal["report-document-v1"] = "report-document-v1"
    title: NonBlankString
    subtitle: NonBlankString
    executiveSummary: NonBlankString
    sections: tuple[dict[str, Any], ...]
