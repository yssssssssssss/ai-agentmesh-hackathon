from __future__ import annotations

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
    """Standalone ProblemGraph requirement; its source schema requires one or more items."""

    id: NonBlankString
    acceptedClasses: tuple[SourceEvidenceClass, ...] = Field(min_length=1)
    minimumCount: int = Field(ge=1)
    required: bool

    @model_validator(mode="after")
    def validate_classes(self) -> AiXEvidenceRequirementV1:
        require_unique(self.acceptedClasses, "source accepted evidence classes")
        return self


class AiXCurrentEvidenceRequirementV1(StrictFrozenModel):
    """CurrentExecutionPlan embeds a distinct source definition that permits zero."""

    id: NonBlankString
    acceptedClasses: tuple[SourceEvidenceClass, ...] = Field(min_length=1)
    minimumCount: int = Field(ge=0)
    required: bool

    @model_validator(mode="after")
    def validate_classes(self) -> AiXCurrentEvidenceRequirementV1:
        require_unique(self.acceptedClasses, "source accepted evidence classes")
        return self


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


class AiXCurrentProblemQuestionV1(StrictFrozenModel):
    id: NonBlankString
    statement: NonBlankString
    rationale: NonBlankString
    priority: Literal["required", "optional"]
    success_criterion_ids: tuple[NonBlankString, ...]
    evidence_requirements: tuple[AiXCurrentEvidenceRequirementV1, ...]
    acceptance_criteria: tuple[NonBlankString, ...] = Field(min_length=1)
    depends_on: tuple[NonBlankString, ...]


class AiXCurrentProblemGraphV1(StrictFrozenModel):
    version: Literal["problem-graph-v1"] = "problem-graph-v1"
    questions: tuple[AiXCurrentProblemQuestionV1, ...] = Field(min_length=1)


class AiXProblemGraphProvenance(StrictFrozenModel):
    receiptId: UUID
    modelName: NonBlankString
    modelVersion: NonBlankString
    promptHash: NonBlankString
    traceId: NonBlankString


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
        return self


class AiXCapabilitySkill(StrictFrozenModel):
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


class AiXCapabilityReason(StrictFrozenModel):
    code: SourceCapabilityReasonCode
    message: NonBlankString
    related_id: NonBlankString | None = None


class AiXCapabilityPendingInput(StrictFrozenModel):
    kind: Literal["value", "visual"]
    role: NonBlankString
    label: NonBlankString
    multiple: bool
    capability_id: NonBlankString


class AiXCapabilityApproval(StrictFrozenModel):
    capability_type: Literal["skill", "tool"]
    capability_id: NonBlankString
    authority: SourceApprovalRole


class AiXOptionalToolDecision(StrictFrozenModel):
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


class AiXCapabilityDecision(StrictFrozenModel):
    skill: AiXCapabilitySkill
    required_approvals: tuple[AiXCapabilityApproval, ...]
    reasons: tuple[AiXCapabilityReason, ...] = Field(min_length=1)
    pending_inputs: tuple[AiXCapabilityPendingInput, ...]
    optional_tool_decisions: tuple[AiXOptionalToolDecision, ...] = ()


class AiXCapabilityDecisions(StrictFrozenModel):
    eligible: tuple[AiXCapabilityDecision, ...]
    rejected: tuple[AiXCapabilityDecision, ...]


class AiXCapabilityGap(StrictFrozenModel):
    capability_type: Literal["tool"]
    capability_id: NonBlankString
    code: SourceOptionalToolReasonCode
    message: Annotated[NonBlankString, Field(max_length=300)]


class AiXCandidateMetadata(StrictFrozenModel):
    title: NonBlankString
    rationale: NonBlankString
    tradeoffs: NonBlankString


class AiXCurrentExecutionPlan(StrictFrozenModel):
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


class AiXFactFindingV1(StrictFrozenModel):
    id: NonBlankString
    kind: Literal["fact"] = "fact"
    evidenceIds: tuple[NonBlankString, ...]
    statement: NonBlankString


class AiXInferenceFindingV1(StrictFrozenModel):
    id: NonBlankString
    kind: Literal["inference"] = "inference"
    findingIds: tuple[NonBlankString, ...]
    statement: NonBlankString


AiXFindingV1 = Annotated[AiXFactFindingV1 | AiXInferenceFindingV1, Field(discriminator="kind")]


class AiXAnalysisNodeV1(StrictFrozenModel):
    id: NonBlankString
    findingIds: tuple[NonBlankString, ...]
    statement: NonBlankString


class AiXSummaryNodeV1(StrictFrozenModel):
    id: NonBlankString
    findingIds: tuple[NonBlankString, ...]
    analysisIds: tuple[NonBlankString, ...]
    summary: NonBlankString


class AiXConclusionNodeV1(StrictFrozenModel):
    id: NonBlankString
    summaryIds: tuple[NonBlankString, ...]
    statement: NonBlankString


class AiXFindingGraphV1(StrictFrozenModel):
    findings: tuple[AiXFindingV1, ...]
    analyses: tuple[AiXAnalysisNodeV1, ...]
    subQuestionSummaries: tuple[AiXSummaryNodeV1, ...]
    overallConclusions: tuple[AiXConclusionNodeV1, ...]


class AiXRecommendationV1(StrictFrozenModel):
    id: NonBlankString
    summaryIds: tuple[NonBlankString, ...]
    statement: NonBlankString


class AiXQuestionCoverageBindingV1(StrictFrozenModel):
    questionId: NonBlankString
    summaryIds: tuple[NonBlankString, ...]


class AiXSuccessCriterionCoverageBindingV1(StrictFrozenModel):
    successCriterionId: NonBlankString
    conclusionIds: tuple[NonBlankString, ...]
    recommendationIds: tuple[NonBlankString, ...]


class AiXResearchDeliverableCoverageV1(StrictFrozenModel):
    questionBindings: tuple[AiXQuestionCoverageBindingV1, ...]
    successCriterionBindings: tuple[AiXSuccessCriterionCoverageBindingV1, ...]


class AiXCapabilityProvenanceV1(StrictFrozenModel):
    id: NonBlankString
    type: NonBlankString


class AiXCompetitorSampleV1(StrictFrozenModel):
    id: NonBlankString
    name: NonBlankString
    rationale: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXDimensionValueV1(StrictFrozenModel):
    sampleId: NonBlankString
    value: NonBlankString
    score: Decimal | None = Field(default=None, ge=1, le=5)
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXDimensionMatrixRowV1(StrictFrozenModel):
    dimension: NonBlankString
    weight: Decimal | None = Field(default=None, gt=0, le=1)
    values: tuple[AiXDimensionValueV1, ...] = Field(min_length=1)


class AiXDifferenceV1(StrictFrozenModel):
    id: NonBlankString
    dimension: NonBlankString
    statement: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXImpactV1(StrictFrozenModel):
    differenceId: NonBlankString
    audience: NonBlankString
    statement: NonBlankString


class AiXActionRecommendationV1(StrictFrozenModel):
    id: NonBlankString
    differenceIds: tuple[NonBlankString, ...] = Field(min_length=1)
    priority: Literal["P0", "P1", "P2", "P3"]
    statement: NonBlankString


class AiXRoadmapItemV1(StrictFrozenModel):
    priority: Literal["P0", "P1", "P2"]
    statement: NonBlankString
    metric: NonBlankString
    validationMethod: NonBlankString


class AiXVisualEvidenceV1(StrictFrozenModel):
    id: NonBlankString
    sampleIds: tuple[NonBlankString, ...] = Field(min_length=1)
    dimension: NonBlankString
    assetId: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)
    caption: NonBlankString


class AiXScreenshotComparisonV1(StrictFrozenModel):
    id: NonBlankString
    dimension: NonBlankString
    sampleIds: tuple[NonBlankString, ...] = Field(min_length=1)
    assetIds: tuple[NonBlankString, NonBlankString]
    caption: NonBlankString

    @model_validator(mode="after")
    def validate_assets(self) -> AiXScreenshotComparisonV1:
        require_unique(self.assetIds, "source screenshot comparison Asset IDs")
        return self


class AiXCompetitiveAnalysisPayloadV1(StrictFrozenModel):
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


class AiXResearchDeliverableV1(StrictFrozenModel):
    version: Literal["research-deliverable-v1"] = "research-deliverable-v1"
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


class AiXReviewDimensionV1(StrictFrozenModel):
    id: SourceReviewDimensionId
    passed: bool
    issues: tuple[str, ...]


class AiXReportReviewV1(StrictFrozenModel):
    version: Literal["report-review-v1"] = "report-review-v1"
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


class AiXAssetRefV1(StrictFrozenModel):
    assetId: NonBlankString
    manifestArtifactId: NonBlankString


class AiXChartRefV1(StrictFrozenModel):
    chartId: NonBlankString
    assetId: NonBlankString
    manifestArtifactId: NonBlankString


class AiXParagraphBlockV1(StrictFrozenModel):
    id: NonBlankString
    type: Literal["paragraph"] = "paragraph"
    text: NonBlankString


class AiXFactBlockV1(StrictFrozenModel):
    id: NonBlankString
    type: Literal["fact"] = "fact"
    text: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXMetricBlockV1(StrictFrozenModel):
    id: NonBlankString
    type: Literal["metric"] = "metric"
    label: NonBlankString
    value: Decimal
    evidenceIds: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXListBlockV1(StrictFrozenModel):
    id: NonBlankString
    type: Literal["list"] = "list"
    items: tuple[NonBlankString, ...] = Field(min_length=1)


class AiXImageBlockV1(StrictFrozenModel):
    id: NonBlankString
    type: Literal["image"] = "image"
    assetRef: AiXAssetRefV1
    caption: NonBlankString
    altText: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] | None = Field(default=None, min_length=1)


class AiXImageComparisonBlockV1(StrictFrozenModel):
    id: NonBlankString
    type: Literal["image-comparison"] = "image-comparison"
    beforeAssetRef: AiXAssetRefV1
    afterAssetRef: AiXAssetRefV1
    caption: NonBlankString
    altText: NonBlankString
    evidenceIds: tuple[NonBlankString, ...] | None = Field(default=None, min_length=1)


class AiXChartSeriesV1(StrictFrozenModel):
    key: NonBlankString
    label: NonBlankString
    values: tuple[Decimal | None, ...] = Field(min_length=1)
    evidenceIds: tuple[tuple[NonBlankString, ...], ...] = Field(min_length=1)


class AiXChartYAxisV1(StrictFrozenModel):
    min: Decimal


class AiXChartSpecV1(StrictFrozenModel):
    version: Literal["chart-spec-v1"] = "chart-spec-v1"
    chartId: NonBlankString
    type: Literal["comparison", "trend", "heatmap"]
    title: NonBlankString
    categories: tuple[NonBlankString, ...] = Field(min_length=1)
    series: tuple[AiXChartSeriesV1, ...] = Field(min_length=1)
    yAxis: AiXChartYAxisV1 | None = None


class AiXChartTableRowV1(StrictFrozenModel):
    key: NonBlankString
    label: NonBlankString
    cells: tuple[Decimal | None, ...] = Field(min_length=1)
    evidenceIds: tuple[tuple[NonBlankString, ...], ...] = Field(min_length=1)


class AiXChartTableV1(StrictFrozenModel):
    caption: NonBlankString
    columns: tuple[NonBlankString, ...] = Field(min_length=2)
    rows: tuple[AiXChartTableRowV1, ...] = Field(min_length=1)


class AiXChartBlockV1(StrictFrozenModel):
    id: NonBlankString
    type: Literal["chart"] = "chart"
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


class AiXReportSectionV1(StrictFrozenModel):
    id: NonBlankString
    title: NonBlankString
    questionIds: tuple[NonBlankString, ...]
    blocks: tuple[AiXReportBlockV1, ...]


class AiXReportDocumentV1(StrictFrozenModel):
    version: Literal["report-document-v1"] = "report-document-v1"
    title: NonBlankString
    subtitle: NonBlankString
    executiveSummary: NonBlankString
    sections: tuple[AiXReportSectionV1, ...] = Field(min_length=1)
