from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from agentmesh.research_orchestration.v3.common import (
    FrozenJsonObject,
    NonBlankString,
    StrictFrozenModel,
    require_unique,
)

SourceEvidenceClass = Literal[
    "public_source",
    "screenshot",
    "user_input",
    "knowledge",
    "dataset",
    "simulation",
    "derived",
]
SourceActorType = Literal["tool", "skill", "llm", "reviewer"]
SourceApprovalRole = Literal["owner", "legal", "security"]
SourceReviewDimensionId = Literal[
    "requirement_coverage",
    "question_coverage",
    "evidence_coverage",
    "reasoning_quality",
    "recommendation_quality",
    "visual_quality",
    "risk_disclosure",
]
SOURCE_REVIEW_DIMENSIONS = frozenset(
    {
        "requirement_coverage",
        "question_coverage",
        "evidence_coverage",
        "reasoning_quality",
        "recommendation_quality",
        "visual_quality",
        "risk_disclosure",
    }
)
SourceCapabilityReasonCode = Literal[
    "skill_inactive",
    "task_type_mismatch",
    "required_tool_missing",
    "required_tool_inactive",
    "required_tool_health_unknown",
    "required_tool_unhealthy",
    "core_tool_real_adapter_unavailable",
    "approval_unavailable",
    "pending_input_required",
    "eligible",
]
SourceOptionalToolReasonCode = Literal[
    "optional_tool_health_unknown",
    "optional_tool_unhealthy",
    "optional_tool_real_adapter_unavailable",
]


class SourceStrictFrozenModel(StrictFrozenModel):
    """Source JSON Schema objects permit omission, but never explicit JSON null."""

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_properties(cls, value: object) -> object:
        if isinstance(value, Mapping):
            null_fields = sorted(key for key, item in value.items() if item is None)
            if null_fields:
                raise ValueError(f"source contract properties do not accept null: {null_fields!r}")
        return value


class AiXConstraintV2(SourceStrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString
    source: Literal["user", "policy"]


class AiXSuccessCriterionV2(SourceStrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString


class AiXAssumptionV2(SourceStrictFrozenModel):
    key: NonBlankString
    value: str
    editable: bool


class AiXAmbiguityV2(SourceStrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString
    blocking: bool


class AiXClarificationQuestionV2(SourceStrictFrozenModel):
    key: NonBlankString
    question: NonBlankString
    rationale: NonBlankString


class AiXBlockingIssueV2(SourceStrictFrozenModel):
    key: NonBlankString
    reason: NonBlankString
    kind: NonBlankString


class AiXResearchTaskV2(SourceStrictFrozenModel):
    """Frozen ai-x input shape; this is never a target registry contract."""

    version: Literal["research-task-v2"]
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

    @model_validator(mode="after")
    def validate_requirement(self) -> AiXResearchTaskV2:
        if self.comparison_dimensions is not None:
            require_unique(self.comparison_dimensions, "source comparison dimensions")
        return self


class AiXEvidenceRequirementV1(SourceStrictFrozenModel):
    """Standalone ProblemGraph requirement; its source schema requires one or more items."""

    id: NonBlankString
    acceptedClasses: tuple[SourceEvidenceClass, ...] = Field(min_length=1)
    minimumCount: int = Field(ge=1)
    required: bool

    @model_validator(mode="after")
    def validate_classes(self) -> AiXEvidenceRequirementV1:
        require_unique(self.acceptedClasses, "source accepted evidence classes")
        return self


class AiXCurrentEvidenceRequirementV1(SourceStrictFrozenModel):
    """CurrentExecutionPlan embeds a distinct source definition that permits zero."""

    id: NonBlankString
    acceptedClasses: tuple[SourceEvidenceClass, ...] = Field(min_length=1)
    minimumCount: int = Field(ge=0)
    required: bool

    @model_validator(mode="after")
    def validate_classes(self) -> AiXCurrentEvidenceRequirementV1:
        require_unique(self.acceptedClasses, "source accepted evidence classes")
        return self


class AiXProblemQuestionV1(SourceStrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString
    rationale: NonBlankString
    priority: Literal["required", "optional"]
    success_criterion_ids: tuple[NonBlankString, ...]
    evidence_requirements: tuple[AiXEvidenceRequirementV1, ...]
    acceptance_criteria: tuple[NonBlankString, ...] = Field(min_length=1)
    depends_on: tuple[NonBlankString, ...]

    @model_validator(mode="after")
    def validate_unique_lists(self) -> AiXProblemQuestionV1:
        require_unique(self.success_criterion_ids, "source success criterion IDs")
        require_unique(self.acceptance_criteria, "source acceptance criteria")
        require_unique(self.depends_on, "source question dependencies")
        return self


class AiXProblemGraphV1(SourceStrictFrozenModel):
    version: Literal["problem-graph-v1"]
    questions: tuple[AiXProblemQuestionV1, ...] = Field(min_length=1)


class AiXCurrentProblemQuestionV1(SourceStrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString
    rationale: NonBlankString
    priority: Literal["required", "optional"]
    success_criterion_ids: tuple[NonBlankString, ...]
    evidence_requirements: tuple[AiXCurrentEvidenceRequirementV1, ...]
    acceptance_criteria: tuple[NonBlankString, ...] = Field(min_length=1)
    depends_on: tuple[NonBlankString, ...]

    @model_validator(mode="after")
    def validate_unique_lists(self) -> AiXCurrentProblemQuestionV1:
        require_unique(self.success_criterion_ids, "source success criterion IDs")
        require_unique(self.depends_on, "source question dependencies")
        return self


class AiXCurrentProblemGraphV1(SourceStrictFrozenModel):
    version: Literal["problem-graph-v1"]
    questions: tuple[AiXCurrentProblemQuestionV1, ...] = Field(min_length=1)


class AiXProblemGraphProvenance(SourceStrictFrozenModel):
    receiptId: UUID
    modelName: NonBlankString
    modelVersion: NonBlankString
    promptHash: NonBlankString
    traceId: NonBlankString


class AiXPlanInputBinding(SourceStrictFrozenModel):
    target_pointer: str = Field(pattern=r"^/")
    source_step_no: int = Field(ge=1)
    source_pointer: str = Field(pattern=r"^/")


class AiXExpectedOutput(SourceStrictFrozenModel):
    pointer: str = Field(pattern=r"^/")
    description: NonBlankString


class AiXCurrentPlanStep(SourceStrictFrozenModel):
    step_no: int = Field(ge=1)
    step_name: NonBlankString
    actor_type: SourceActorType
    actor_id: NonBlankString
    question_ids: tuple[NonBlankString, ...] = Field(min_length=1)
    depends_on: tuple[int, ...]
    input: FrozenJsonObject
    input_bindings: tuple[AiXPlanInputBinding, ...]
    expected_outputs: tuple[AiXExpectedOutput, ...] = Field(min_length=1)
    acceptance_criteria: tuple[NonBlankString, ...] = Field(min_length=1)
    requires_approval: bool
    approval_role: SourceApprovalRole | None = None
    fallback_actor_ids: tuple[NonBlankString, ...]

    @model_validator(mode="after")
    def validate_approval(self) -> AiXCurrentPlanStep:
        if self.requires_approval != (self.approval_role is not None):
            raise ValueError("source approval_role must be present exactly when approval is required")
        require_unique(self.question_ids, "source step question IDs")
        require_unique(self.depends_on, "source step dependencies")
        require_unique(self.fallback_actor_ids, "source fallback actor IDs")
        return self


class AiXCapabilitySkill(SourceStrictFrozenModel):
    id: NonBlankString | None = None
    name: NonBlankString | None = None
    path: NonBlankString | None = None
    when_to_use: str | None = None
    owner: str | None = None
    status: Literal["draft", "active", "deprecated"]
    task_types: tuple[str, ...]
    intent_tags: tuple[str, ...] | None = None
    inputs: tuple[str, ...]
    visual_inputs: tuple[NonBlankString, ...] | None = None
    multiple_visual_inputs: tuple[NonBlankString, ...] | None = None
    outputs: tuple[str, ...]
    input_schema: str | None = None
    output_schema: str | None = None
    payload_schema: str | None = None
    entry: str | None = None
    required_tools: tuple[str, ...]
    optional_tools: tuple[NonBlankString, ...] | None = None
    cost_level: str | None = None
    risk_level: Literal["low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def validate_unique_lists(self) -> AiXCapabilitySkill:
        if self.visual_inputs is not None:
            require_unique(self.visual_inputs, "source visual inputs")
        if self.multiple_visual_inputs is not None:
            require_unique(self.multiple_visual_inputs, "source multiple visual inputs")
        if self.optional_tools is not None:
            require_unique(self.optional_tools, "source optional Tool IDs")
        return self


class AiXCapabilityReason(SourceStrictFrozenModel):
    code: SourceCapabilityReasonCode
    message: NonBlankString
    related_id: NonBlankString | None = None


class AiXCapabilityPendingInput(SourceStrictFrozenModel):
    kind: Literal["value", "visual"]
    role: NonBlankString
    label: NonBlankString
    multiple: bool
    capability_id: NonBlankString


class AiXCapabilityApproval(SourceStrictFrozenModel):
    capability_type: Literal["skill", "tool"]
    capability_id: NonBlankString
    authority: SourceApprovalRole


class AiXOptionalToolDecision(SourceStrictFrozenModel):
    tool_id: NonBlankString
    status: Literal["available", "unavailable"]
    reason_code: SourceOptionalToolReasonCode | None = None
    message: Annotated[NonBlankString, Field(max_length=300)] | None = None

    @model_validator(mode="after")
    def validate_status(self) -> AiXOptionalToolDecision:
        if self.status == "available" and (self.reason_code is not None or self.message is not None):
            raise ValueError("available source optional Tools cannot include an unavailability reason")
        if self.status == "unavailable" and (self.reason_code is None or self.message is None):
            raise ValueError("unavailable source optional Tools require a reason and message")
        return self


class AiXCapabilityDecision(SourceStrictFrozenModel):
    skill: AiXCapabilitySkill
    required_approvals: tuple[AiXCapabilityApproval, ...]
    reasons: tuple[AiXCapabilityReason, ...] = Field(min_length=1)
    pending_inputs: tuple[AiXCapabilityPendingInput, ...]
    optional_tool_decisions: tuple[AiXOptionalToolDecision, ...] = ()

    @model_validator(mode="after")
    def validate_optional_tool_decisions(self) -> AiXCapabilityDecision:
        require_unique(self.optional_tool_decisions, "source optional Tool decisions")
        return self


class AiXCapabilityDecisions(SourceStrictFrozenModel):
    eligible: tuple[AiXCapabilityDecision, ...]
    rejected: tuple[AiXCapabilityDecision, ...]


class AiXCapabilityGap(SourceStrictFrozenModel):
    capability_type: Literal["tool"]
    capability_id: NonBlankString
    code: SourceOptionalToolReasonCode
    message: Annotated[NonBlankString, Field(max_length=300)]


class AiXCandidateMetadata(SourceStrictFrozenModel):
    title: NonBlankString
    rationale: NonBlankString
    tradeoffs: NonBlankString


class AiXCurrentExecutionPlan(SourceStrictFrozenModel):
    """Source proposal shape, deliberately not accepted as an executable target plan."""

    task_id: str
    deliverable_type: NonBlankString
    evidence_requirements: tuple[AiXCurrentEvidenceRequirementV1, ...]
    problem_graph: AiXCurrentProblemGraphV1
    problem_graph_provenance: AiXProblemGraphProvenance
    capability_decisions: AiXCapabilityDecisions
    capability_gaps: tuple[AiXCapabilityGap, ...] = ()
    steps: tuple[AiXCurrentPlanStep, ...] = Field(min_length=1)
    candidate_metadata: AiXCandidateMetadata
    activated_nodes: tuple[NonBlankString, ...]

    @model_validator(mode="after")
    def validate_unique_lists(self) -> AiXCurrentExecutionPlan:
        require_unique(self.capability_gaps, "source capability gaps")
        require_unique(self.activated_nodes, "source activated decision nodes")
        return self


class AiXFactFindingV1(SourceStrictFrozenModel):
    id: NonBlankString
    kind: Literal["fact"]
    evidenceIds: tuple[NonBlankString, ...]
    statement: NonBlankString


class AiXInferenceFindingV1(SourceStrictFrozenModel):
    id: NonBlankString
    kind: Literal["inference"]
    findingIds: tuple[NonBlankString, ...]
    statement: NonBlankString


AiXFindingV1 = Annotated[AiXFactFindingV1 | AiXInferenceFindingV1, Field(discriminator="kind")]


class AiXAnalysisNodeV1(SourceStrictFrozenModel):
    id: NonBlankString
    findingIds: tuple[NonBlankString, ...]
    statement: NonBlankString


class AiXSummaryNodeV1(SourceStrictFrozenModel):
    id: NonBlankString
    findingIds: tuple[NonBlankString, ...]
    analysisIds: tuple[NonBlankString, ...]
    summary: NonBlankString


class AiXConclusionNodeV1(SourceStrictFrozenModel):
    id: NonBlankString
    summaryIds: tuple[NonBlankString, ...]
    statement: NonBlankString


class AiXFindingGraphV1(SourceStrictFrozenModel):
    findings: tuple[AiXFindingV1, ...]
    analyses: tuple[AiXAnalysisNodeV1, ...]
    subQuestionSummaries: tuple[AiXSummaryNodeV1, ...]
    overallConclusions: tuple[AiXConclusionNodeV1, ...]


class AiXRecommendationV1(SourceStrictFrozenModel):
    id: NonBlankString
    summaryIds: tuple[NonBlankString, ...]
    statement: NonBlankString


class AiXQuestionCoverageBindingV1(SourceStrictFrozenModel):
    questionId: NonBlankString
    summaryIds: tuple[NonBlankString, ...]


class AiXSuccessCriterionCoverageBindingV1(SourceStrictFrozenModel):
    successCriterionId: NonBlankString
    conclusionIds: tuple[NonBlankString, ...]
    recommendationIds: tuple[NonBlankString, ...]


class AiXResearchDeliverableCoverageV1(SourceStrictFrozenModel):
    questionBindings: tuple[AiXQuestionCoverageBindingV1, ...]
    successCriterionBindings: tuple[AiXSuccessCriterionCoverageBindingV1, ...]


class AiXCapabilityProvenanceV1(SourceStrictFrozenModel):
    id: NonBlankString
    type: NonBlankString


class AiXCompetitorSampleV1(SourceStrictFrozenModel):
    id: NonBlankString
    name: NonBlankString
    rationale: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXDimensionValueV1(SourceStrictFrozenModel):
    sampleId: NonBlankString
    value: NonBlankString
    score: Decimal | None = Field(default=None, ge=1, le=5)
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXDimensionMatrixRowV1(SourceStrictFrozenModel):
    dimension: NonBlankString
    weight: Decimal | None = Field(default=None, gt=0, le=1)
    values: tuple[AiXDimensionValueV1, ...] = Field(min_length=1)


class AiXDifferenceV1(SourceStrictFrozenModel):
    id: NonBlankString
    dimension: NonBlankString
    statement: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXImpactV1(SourceStrictFrozenModel):
    differenceId: NonBlankString
    audience: NonBlankString
    statement: NonBlankString


class AiXActionRecommendationV1(SourceStrictFrozenModel):
    id: NonBlankString
    differenceIds: tuple[NonBlankString, ...] = Field(min_length=1)
    priority: Literal["P0", "P1", "P2", "P3"]
    statement: NonBlankString


class AiXRoadmapItemV1(SourceStrictFrozenModel):
    priority: Literal["P0", "P1", "P2"]
    statement: NonBlankString
    metric: NonBlankString
    validationMethod: NonBlankString


class AiXVisualEvidenceV1(SourceStrictFrozenModel):
    id: NonBlankString
    sampleIds: tuple[NonBlankString, ...] = Field(min_length=1)
    dimension: NonBlankString
    assetId: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)
    caption: NonBlankString


class AiXScreenshotComparisonV1(SourceStrictFrozenModel):
    id: NonBlankString
    dimension: NonBlankString
    sampleIds: tuple[NonBlankString, ...] = Field(min_length=1)
    assetIds: tuple[NonBlankString, NonBlankString]
    caption: NonBlankString

    @model_validator(mode="after")
    def validate_assets(self) -> AiXScreenshotComparisonV1:
        require_unique(self.assetIds, "source screenshot comparison Asset IDs")
        return self


class AiXCompetitiveAnalysisPayloadV1(SourceStrictFrozenModel):
    competitorSamples: tuple[AiXCompetitorSampleV1, ...] = Field(min_length=1)
    dimensionMatrix: tuple[AiXDimensionMatrixRowV1, ...] = Field(min_length=1)
    differences: tuple[AiXDifferenceV1, ...] = Field(min_length=1)
    impacts: tuple[AiXImpactV1, ...] = Field(min_length=1)
    actionRecommendations: tuple[AiXActionRecommendationV1, ...] = Field(min_length=1)
    managementSummary: tuple[NonBlankString, ...] | None = Field(default=None, min_length=1)
    scoringMethod: tuple[NonBlankString, ...] | None = Field(default=None, min_length=1)
    roadmap: tuple[AiXRoadmapItemV1, ...] | None = Field(default=None, min_length=1)
    instrumentationPlan: tuple[NonBlankString, ...] | None = Field(default=None, min_length=1)
    userTestScript: tuple[NonBlankString, ...] | None = Field(default=None, min_length=1)
    visualEvidence: tuple[AiXVisualEvidenceV1, ...] = ()
    screenshotComparisons: tuple[AiXScreenshotComparisonV1, ...]


class AiXResearchDeliverableV1(SourceStrictFrozenModel):
    version: Literal["research-deliverable-v1"]
    taskId: NonBlankString
    planVersionId: NonBlankString
    attemptId: NonBlankString
    deliverableType: Literal["competitive_analysis_report"]
    evidenceManifestArtifactId: NonBlankString
    methodSummary: NonBlankString
    findingGraph: AiXFindingGraphV1
    payload: AiXCompetitiveAnalysisPayloadV1
    recommendations: tuple[AiXRecommendationV1, ...]
    coverage: AiXResearchDeliverableCoverageV1
    risksAndOpenIssues: tuple[NonBlankString, ...]
    capabilityProvenance: tuple[AiXCapabilityProvenanceV1, ...]


class AiXReviewDimensionV1(SourceStrictFrozenModel):
    id: SourceReviewDimensionId
    passed: bool
    issues: tuple[str, ...]


class AiXReportReviewV1(SourceStrictFrozenModel):
    version: Literal["report-review-v1"]
    taskId: NonBlankString
    planVersionId: NonBlankString
    attemptId: NonBlankString
    deliverableArtifactId: NonBlankString
    verdict: Literal["pass", "revise", "block"]
    dimensions: tuple[AiXReviewDimensionV1, ...] = Field(min_length=7, max_length=7)
    revisionRound: Literal[0, 1]

    @model_validator(mode="after")
    def validate_review(self) -> AiXReportReviewV1:
        ids = tuple(item.id for item in self.dimensions)
        if set(ids) != SOURCE_REVIEW_DIMENSIONS or len(ids) != len(set(ids)):
            raise ValueError("source review must contain every dimension exactly once")
        if self.verdict == "pass" and any(not item.passed or item.issues for item in self.dimensions):
            raise ValueError("source pass verdict requires all dimensions to pass without issues")
        return self


class AiXAssetRefV1(SourceStrictFrozenModel):
    assetId: NonBlankString
    manifestArtifactId: NonBlankString


class AiXChartRefV1(SourceStrictFrozenModel):
    chartId: NonBlankString
    assetId: NonBlankString
    manifestArtifactId: NonBlankString


class AiXParagraphBlockV1(SourceStrictFrozenModel):
    id: NonBlankString
    type: Literal["paragraph"]
    text: NonBlankString


class AiXFactBlockV1(SourceStrictFrozenModel):
    id: NonBlankString
    type: Literal["fact"]
    text: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> AiXFactBlockV1:
        require_unique(self.evidenceIds, "source fact Evidence IDs")
        return self


class AiXMetricBlockV1(SourceStrictFrozenModel):
    id: NonBlankString
    type: Literal["metric"]
    label: NonBlankString
    value: Decimal
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> AiXMetricBlockV1:
        require_unique(self.evidenceIds, "source metric Evidence IDs")
        return self


class AiXListBlockV1(SourceStrictFrozenModel):
    id: NonBlankString
    type: Literal["list"]
    items: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXImageBlockV1(SourceStrictFrozenModel):
    id: NonBlankString
    type: Literal["image"]
    assetRef: AiXAssetRefV1
    caption: NonBlankString
    altText: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> AiXImageBlockV1:
        if self.evidenceIds is not None:
            require_unique(self.evidenceIds, "source image Evidence IDs")
        return self


class AiXImageComparisonBlockV1(SourceStrictFrozenModel):
    id: NonBlankString
    type: Literal["image-comparison"]
    beforeAssetRef: AiXAssetRefV1
    afterAssetRef: AiXAssetRefV1
    caption: NonBlankString
    altText: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> AiXImageComparisonBlockV1:
        if self.evidenceIds is not None:
            require_unique(self.evidenceIds, "source image-comparison Evidence IDs")
        return self


class AiXChartSeriesV1(SourceStrictFrozenModel):
    key: NonBlankString
    label: NonBlankString
    values: tuple[Decimal | None, ...] = Field(min_length=1)
    evidenceIds: tuple[tuple[NonBlankString, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> AiXChartSeriesV1:
        for evidence_ids in self.evidenceIds:
            require_unique(evidence_ids, "source chart-series Evidence IDs")
        return self


class AiXChartYAxisV1(SourceStrictFrozenModel):
    min: Decimal


class AiXChartSpecV1(SourceStrictFrozenModel):
    version: Literal["chart-spec-v1"]
    chartId: NonBlankString
    type: Literal["comparison", "trend", "heatmap"]
    title: NonBlankString
    categories: tuple[NonBlankString, ...] = Field(min_length=1)
    series: tuple[AiXChartSeriesV1, ...] = Field(min_length=1)
    yAxis: AiXChartYAxisV1 | None = None

    @model_validator(mode="after")
    def validate_categories(self) -> AiXChartSpecV1:
        require_unique(self.categories, "source chart categories")
        return self


class AiXChartTableRowV1(SourceStrictFrozenModel):
    key: NonBlankString
    label: NonBlankString
    cells: tuple[Decimal | None, ...] = Field(min_length=1)
    evidenceIds: tuple[tuple[NonBlankString, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> AiXChartTableRowV1:
        for evidence_ids in self.evidenceIds:
            require_unique(evidence_ids, "source chart-table Evidence IDs")
        return self


class AiXChartTableV1(SourceStrictFrozenModel):
    caption: NonBlankString
    columns: tuple[NonBlankString, ...] = Field(min_length=2)
    rows: tuple[AiXChartTableRowV1, ...] = Field(min_length=1)


class AiXChartBlockV1(SourceStrictFrozenModel):
    id: NonBlankString
    type: Literal["chart"]
    chartRef: AiXChartRefV1
    specHash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    spec: AiXChartSpecV1
    table: AiXChartTableV1
    caption: NonBlankString
    altText: NonBlankString


AiXReportBlockV1 = Annotated[
    AiXParagraphBlockV1
    | AiXFactBlockV1
    | AiXMetricBlockV1
    | AiXListBlockV1
    | AiXImageBlockV1
    | AiXImageComparisonBlockV1
    | AiXChartBlockV1,
    Field(discriminator="type"),
]


class AiXReportSectionV1(SourceStrictFrozenModel):
    id: NonBlankString
    title: NonBlankString
    questionIds: tuple[NonBlankString, ...]
    blocks: tuple[AiXReportBlockV1, ...]

    @model_validator(mode="after")
    def validate_question_ids(self) -> AiXReportSectionV1:
        require_unique(self.questionIds, "source report question IDs")
        return self


class AiXReportDocumentV1(SourceStrictFrozenModel):
    version: Literal["report-document-v1"]
    title: NonBlankString
    subtitle: NonBlankString
    executiveSummary: NonBlankString
    sections: tuple[AiXReportSectionV1, ...] = Field(min_length=1)
