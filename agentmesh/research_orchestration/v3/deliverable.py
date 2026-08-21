from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from agentmesh.research_orchestration.v3.common import (
    ActorType,
    EvidenceManifestArtifactRefV3,
    FrozenJsonObject,
    Identifier,
    JsonDecimal,
    NonBlankString,
    SealedArtifactRefV3,
    StrictFrozenModel,
    require_unique,
)

Text = Annotated[NonBlankString, Field(max_length=4000)]


class FactFindingV3(StrictFrozenModel):
    id: Identifier
    kind: Literal["fact"]
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)
    statement: Text


class InferenceFindingV3(StrictFrozenModel):
    id: Identifier
    kind: Literal["inference"]
    finding_ids: tuple[Identifier, ...] = Field(min_length=1)
    statement: Text


FindingV3 = Annotated[FactFindingV3 | InferenceFindingV3, Field(discriminator="kind")]


class AnalysisNodeV3(StrictFrozenModel):
    id: Identifier
    finding_ids: tuple[Identifier, ...] = Field(min_length=1)
    statement: Text


class SummaryNodeV3(StrictFrozenModel):
    id: Identifier
    finding_ids: tuple[Identifier, ...]
    analysis_ids: tuple[Identifier, ...]
    summary: Text

    @model_validator(mode="after")
    def validate_roots(self) -> SummaryNodeV3:
        if not self.finding_ids and not self.analysis_ids:
            raise ValueError("summary nodes require at least one finding or analysis root")
        return self


class ConclusionNodeV3(StrictFrozenModel):
    id: Identifier
    summary_ids: tuple[Identifier, ...] = Field(min_length=1)
    statement: Text


class FindingGraphV3(StrictFrozenModel):
    findings: tuple[FindingV3, ...] = Field(min_length=1)
    analyses: tuple[AnalysisNodeV3, ...]
    sub_question_summaries: tuple[SummaryNodeV3, ...]
    overall_conclusions: tuple[ConclusionNodeV3, ...]

    @model_validator(mode="after")
    def validate_graph(self) -> FindingGraphV3:
        all_ids = tuple(
            [item.id for item in self.findings]
            + [item.id for item in self.analyses]
            + [item.id for item in self.sub_question_summaries]
            + [item.id for item in self.overall_conclusions]
        )
        require_unique(all_ids, "FindingGraph node IDs")
        finding_ids = {item.id for item in self.findings}
        analysis_ids = {item.id for item in self.analyses}
        summary_ids = {item.id for item in self.sub_question_summaries}
        dependencies: dict[str, set[str]] = {}
        for item in self.findings:
            dependencies[item.id] = set(item.finding_ids) if isinstance(item, InferenceFindingV3) else set()
        for item in self.analyses:
            if not set(item.finding_ids).issubset(finding_ids):
                raise ValueError("analysis references an unknown finding")
            dependencies[item.id] = set(item.finding_ids)
        for item in self.sub_question_summaries:
            if not set(item.finding_ids).issubset(finding_ids) or not set(item.analysis_ids).issubset(analysis_ids):
                raise ValueError("summary references an unknown finding or analysis")
            dependencies[item.id] = set(item.finding_ids) | set(item.analysis_ids)
        for item in self.overall_conclusions:
            if not set(item.summary_ids).issubset(summary_ids):
                raise ValueError("conclusion references an unknown summary")
            dependencies[item.id] = set(item.summary_ids)
        for item in self.findings:
            if isinstance(item, InferenceFindingV3) and not set(item.finding_ids).issubset(finding_ids):
                raise ValueError("inference references an unknown finding")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("FindingGraph contains a cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency_id in dependencies[node_id]:
                visit(dependency_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in dependencies:
            visit(node_id)
        return self


class CompetitorSampleV1(StrictFrozenModel):
    id: Identifier
    name: Annotated[NonBlankString, Field(max_length=240)]
    rationale: Text
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)


class DimensionValueV1(StrictFrozenModel):
    sample_id: Identifier
    value: Text
    score: Annotated[JsonDecimal, Field(ge=1, le=5)] | None = None
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)


class DimensionMatrixRowV1(StrictFrozenModel):
    dimension: Annotated[NonBlankString, Field(max_length=240)]
    weight: Annotated[JsonDecimal, Field(gt=0, le=1)] | None = None
    values: tuple[DimensionValueV1, ...] = Field(min_length=1)


class DifferenceV1(StrictFrozenModel):
    id: Identifier
    dimension: Annotated[NonBlankString, Field(max_length=240)]
    statement: Text
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)


class ImpactV1(StrictFrozenModel):
    difference_id: Identifier
    audience: Annotated[NonBlankString, Field(max_length=240)]
    statement: Text


class ActionRecommendationV1(StrictFrozenModel):
    id: Identifier
    difference_ids: tuple[Identifier, ...] = Field(min_length=1)
    priority: Literal["P0", "P1", "P2", "P3"]
    statement: Text


class RoadmapItemV1(StrictFrozenModel):
    priority: Literal["P0", "P1", "P2"]
    statement: Text
    metric: Text
    validation_method: Text


class CompetitiveAnalysisTextPayloadV1(StrictFrozenModel):
    competitor_samples: tuple[CompetitorSampleV1, ...] = Field(min_length=1)
    dimension_matrix: tuple[DimensionMatrixRowV1, ...] = Field(min_length=1)
    differences: tuple[DifferenceV1, ...] = Field(min_length=1)
    impacts: tuple[ImpactV1, ...] = Field(min_length=1)
    action_recommendations: tuple[ActionRecommendationV1, ...] = Field(min_length=1)
    management_summary: tuple[Text, ...] | None = Field(default=None, min_length=1)
    scoring_method: tuple[Text, ...] | None = Field(default=None, min_length=1)
    roadmap: tuple[RoadmapItemV1, ...] | None = Field(default=None, min_length=1)
    instrumentation_plan: tuple[Text, ...] | None = Field(default=None, min_length=1)
    user_test_script: tuple[Text, ...] | None = Field(default=None, min_length=1)
    visual_evidence: tuple[FrozenJsonObject, ...] = Field(max_length=0)
    screenshot_comparisons: tuple[FrozenJsonObject, ...] = Field(max_length=0)

    @model_validator(mode="after")
    def validate_text_payload(self) -> CompetitiveAnalysisTextPayloadV1:
        if self.visual_evidence or self.screenshot_comparisons:
            raise ValueError("Competitive Text does not permit visual payload entries")
        sample_ids = tuple(item.id for item in self.competitor_samples)
        require_unique(sample_ids, "competitor sample IDs")
        known_samples = set(sample_ids)
        for row in self.dimension_matrix:
            row_sample_ids = tuple(item.sample_id for item in row.values)
            require_unique(row_sample_ids, f"sample IDs in dimension {row.dimension}")
            if set(row_sample_ids) != known_samples:
                raise ValueError("every dimension row must compare every competitor sample")
        difference_ids = tuple(item.id for item in self.differences)
        require_unique(difference_ids, "difference IDs")
        known_differences = set(difference_ids)
        if any(item.difference_id not in known_differences for item in self.impacts):
            raise ValueError("impact references an unknown difference")
        if any(not set(item.difference_ids).issubset(known_differences) for item in self.action_recommendations):
            raise ValueError("action recommendation references an unknown difference")
        return self


class RecommendationV3(StrictFrozenModel):
    id: Identifier
    priority: Literal["P0", "P1", "P2", "P3"]
    statement: Text
    finding_ids: tuple[Identifier, ...] = Field(min_length=1)


class QuestionCoverageV3(StrictFrozenModel):
    question_id: Identifier
    summary_ids: tuple[Identifier, ...] = Field(min_length=1)


class SuccessCriterionCoverageV3(StrictFrozenModel):
    success_criterion_id: Identifier
    conclusion_or_recommendation_ids: tuple[Identifier, ...] = Field(min_length=1)


class ResearchDeliverableCoverageV3(StrictFrozenModel):
    question_coverage: tuple[QuestionCoverageV3, ...]
    success_criterion_coverage: tuple[SuccessCriterionCoverageV3, ...]

    @model_validator(mode="after")
    def validate_bindings(self) -> ResearchDeliverableCoverageV3:
        require_unique(tuple(item.question_id for item in self.question_coverage), "question coverage IDs")
        require_unique(
            tuple(item.success_criterion_id for item in self.success_criterion_coverage),
            "success criterion coverage IDs",
        )
        return self


class CapabilityProvenanceV3(StrictFrozenModel):
    actor_type: ActorType
    actor_id: Identifier
    result_artifact: SealedArtifactRefV3


class ResearchDeliverableV3(StrictFrozenModel):
    schema_version: Literal["research-deliverable-v3"]
    run_id: Identifier
    requirement_version_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    deliverable_type: Literal["competitive_analysis_report"]
    payload_schema_version: Literal["competitive-analysis-text-v1"]
    evidence_manifest_artifact: EvidenceManifestArtifactRefV3
    method_summary: Text
    finding_graph: FindingGraphV3
    payload: CompetitiveAnalysisTextPayloadV1
    recommendations: tuple[RecommendationV3, ...]
    coverage: ResearchDeliverableCoverageV3
    risks_and_open_issues: tuple[Text, ...]
    capability_provenance: tuple[CapabilityProvenanceV3, ...]

    @model_validator(mode="after")
    def validate_deliverable(self) -> ResearchDeliverableV3:
        recommendation_ids = tuple(item.id for item in self.recommendations)
        require_unique(recommendation_ids, "recommendation IDs")
        finding_ids = {item.id for item in self.finding_graph.findings}
        if any(not set(item.finding_ids).issubset(finding_ids) for item in self.recommendations):
            raise ValueError("recommendation references an unknown finding")
        summary_ids = {item.id for item in self.finding_graph.sub_question_summaries}
        if any(not set(item.summary_ids).issubset(summary_ids) for item in self.coverage.question_coverage):
            raise ValueError("question coverage references an unknown summary")
        conclusion_or_recommendation_ids = {
            *(item.id for item in self.finding_graph.overall_conclusions),
            *recommendation_ids,
        }
        if any(
            not set(item.conclusion_or_recommendation_ids).issubset(conclusion_or_recommendation_ids)
            for item in self.coverage.success_criterion_coverage
        ):
            raise ValueError("success criterion coverage references an unknown conclusion or recommendation")
        return self
