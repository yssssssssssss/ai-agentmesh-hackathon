from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Literal, cast

from agentmesh.research_orchestration.v3.common import (
    ActorType,
    EvidenceManifestArtifactRefV3,
    SealedArtifactRefV3,
)
from agentmesh.research_orchestration.v3.deliverable import (
    ActionRecommendationV1,
    AnalysisNodeV3,
    CapabilityProvenanceV3,
    CompetitiveAnalysisTextPayloadV1,
    CompetitorSampleV1,
    ConclusionNodeV3,
    DifferenceV1,
    DimensionMatrixRowV1,
    DimensionValueV1,
    FactFindingV3,
    FindingGraphV3,
    ImpactV1,
    InferenceFindingV3,
    QuestionCoverageV3,
    RecommendationV3,
    ResearchDeliverableCoverageV3,
    ResearchDeliverableV3,
    RoadmapItemV1,
    SuccessCriterionCoverageV3,
    SummaryNodeV3,
)
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
from agentmesh.research_orchestration.v3.report_document import (
    AssetRefV3,
    ChartBlockV3,
    ChartRefV3,
    FactBlockV3,
    ImageBlockV3,
    ImageComparisonBlockV3,
    ListBlockV3,
    MetricBlockV3,
    ParagraphBlockV3,
    ReportBlockV3,
    ReportDocumentV3,
    ReportSectionV3,
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
from agentmesh.research_orchestration.v3.review import (
    DeterministicReviewCheckV3,
    ReportReviewV3,
    ReviewDimensionV3,
)
from agentmesh.research_orchestration.v3.source_contracts import (
    AiXAssetRefV1,
    AiXChartBlockV1,
    AiXCurrentExecutionPlan,
    AiXFactBlockV1,
    AiXFactFindingV1,
    AiXImageBlockV1,
    AiXImageComparisonBlockV1,
    AiXInferenceFindingV1,
    AiXListBlockV1,
    AiXMetricBlockV1,
    AiXParagraphBlockV1,
    AiXProblemGraphV1,
    AiXReportBlockV1,
    AiXReportDocumentV1,
    AiXReportReviewV1,
    AiXResearchDeliverableV1,
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


def _artifact_ref(
    value: SealedArtifactRefV3 | Mapping[str, Any],
    *,
    kind: str,
    schema_version: str,
) -> SealedArtifactRefV3:
    artifact = _source(value, SealedArtifactRefV3)
    if artifact.kind != kind or artifact.schema_version != schema_version:
        raise ValueError(f"expected a sealed {schema_version} {kind} Artifact")
    return artifact


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


def _translate_competitive_payload(item: AiXResearchDeliverableV1) -> CompetitiveAnalysisTextPayloadV1:
    payload = item.payload
    return CompetitiveAnalysisTextPayloadV1(
        competitor_samples=tuple(
            CompetitorSampleV1(
                id=_identifier(value.id, "sample"),
                name=value.name,
                rationale=value.rationale,
                evidence_ids=tuple(_identifier(item, "evidence") for item in value.evidenceIds),
            )
            for value in payload.competitorSamples
        ),
        dimension_matrix=tuple(
            DimensionMatrixRowV1(
                dimension=value.dimension,
                weight=value.weight,
                values=tuple(
                    DimensionValueV1(
                        sample_id=_identifier(cell.sampleId, "sample"),
                        value=cell.value,
                        score=cell.score,
                        evidence_ids=tuple(_identifier(item, "evidence") for item in cell.evidenceIds),
                    )
                    for cell in value.values
                ),
            )
            for value in payload.dimensionMatrix
        ),
        differences=tuple(
            DifferenceV1(
                id=_identifier(value.id, "difference"),
                dimension=value.dimension,
                statement=value.statement,
                evidence_ids=tuple(_identifier(item, "evidence") for item in value.evidenceIds),
            )
            for value in payload.differences
        ),
        impacts=tuple(
            ImpactV1(
                difference_id=_identifier(value.differenceId, "difference"),
                audience=value.audience,
                statement=value.statement,
            )
            for value in payload.impacts
        ),
        action_recommendations=tuple(
            ActionRecommendationV1(
                id=_identifier(value.id, "action"),
                difference_ids=tuple(_identifier(item, "difference") for item in value.differenceIds),
                priority=value.priority,
                statement=value.statement,
            )
            for value in payload.actionRecommendations
        ),
        management_summary=payload.managementSummary,
        scoring_method=payload.scoringMethod,
        roadmap=(
            tuple(
                RoadmapItemV1(
                    priority=value.priority,
                    statement=value.statement,
                    metric=value.metric,
                    validation_method=value.validationMethod,
                )
                for value in payload.roadmap
            )
            if payload.roadmap is not None
            else None
        ),
        instrumentation_plan=payload.instrumentationPlan,
        user_test_script=payload.userTestScript,
        visual_evidence=tuple(value.model_dump(mode="python") for value in payload.visualEvidence),
        screenshot_comparisons=tuple(
            value.model_dump(mode="python") for value in payload.screenshotComparisons
        ),
    )


def translate_ai_x_research_deliverable_v1(
    source: AiXResearchDeliverableV1 | Mapping[str, Any],
    *,
    requirement_version_id: str,
    evidence_manifest_artifact: SealedArtifactRefV3 | Mapping[str, Any],
    capability_result_artifacts: Mapping[str, SealedArtifactRefV3 | Mapping[str, Any]],
    recommendation_priorities: Mapping[str, Literal["P0", "P1", "P2", "P3"]],
) -> ResearchDeliverableV3:
    """Translate the complete Competitive source envelope with explicit sealed references."""

    item = _source(source, AiXResearchDeliverableV1)
    manifest = _artifact_ref(
        evidence_manifest_artifact,
        kind="evidence_manifest",
        schema_version="evidence-manifest-v3",
    )
    if manifest.artifact_id != item.evidenceManifestArtifactId:
        raise ValueError("source deliverable Evidence Manifest ID does not match the sealed Artifact")

    finding_id_map = {value.id: _identifier(value.id, "finding") for value in item.findingGraph.findings}
    analysis_id_map = {value.id: _identifier(value.id, "analysis") for value in item.findingGraph.analyses}
    summary_id_map = {
        value.id: _identifier(value.id, "summary") for value in item.findingGraph.subQuestionSummaries
    }
    conclusion_id_map = {
        value.id: _identifier(value.id, "conclusion") for value in item.findingGraph.overallConclusions
    }
    finding_graph = FindingGraphV3(
        findings=tuple(
            FactFindingV3(
                id=finding_id_map[value.id],
                evidence_ids=tuple(_identifier(item, "evidence") for item in value.evidenceIds),
                statement=value.statement,
            )
            if isinstance(value, AiXFactFindingV1)
            else InferenceFindingV3(
                id=finding_id_map[value.id],
                finding_ids=tuple(finding_id_map[item] for item in value.findingIds),
                statement=value.statement,
            )
            for value in item.findingGraph.findings
        ),
        analyses=tuple(
            AnalysisNodeV3(
                id=analysis_id_map[value.id],
                finding_ids=tuple(finding_id_map[item] for item in value.findingIds),
                statement=value.statement,
            )
            for value in item.findingGraph.analyses
        ),
        sub_question_summaries=tuple(
            SummaryNodeV3(
                id=summary_id_map[value.id],
                finding_ids=tuple(finding_id_map[item] for item in value.findingIds),
                analysis_ids=tuple(analysis_id_map[item] for item in value.analysisIds),
                summary=value.summary,
            )
            for value in item.findingGraph.subQuestionSummaries
        ),
        overall_conclusions=tuple(
            ConclusionNodeV3(
                id=conclusion_id_map[value.id],
                summary_ids=tuple(summary_id_map[item] for item in value.summaryIds),
                statement=value.statement,
            )
            for value in item.findingGraph.overallConclusions
        ),
    )

    expected_priority_ids = {value.id for value in item.recommendations}
    if set(recommendation_priorities) != expected_priority_ids:
        raise ValueError("recommendation priorities must cover exactly the source recommendations")
    summaries = {value.id: value for value in item.findingGraph.subQuestionSummaries}
    analyses = {value.id: value for value in item.findingGraph.analyses}
    recommendations: list[RecommendationV3] = []
    for value in item.recommendations:
        rooted_source_ids: set[str] = set()
        for summary_id in value.summaryIds:
            summary = summaries.get(summary_id)
            if summary is None:
                raise ValueError(f"source recommendation references unknown Summary {summary_id}")
            rooted_source_ids.update(summary.findingIds)
            for analysis_id in summary.analysisIds:
                analysis = analyses.get(analysis_id)
                if analysis is None:
                    raise ValueError(f"source Summary references unknown Analysis {analysis_id}")
                rooted_source_ids.update(analysis.findingIds)
        ordered_roots = tuple(
            finding_id_map[source_id] for source_id in finding_id_map if source_id in rooted_source_ids
        )
        if not ordered_roots:
            raise ValueError("source recommendations must resolve to at least one Finding")
        recommendations.append(
            RecommendationV3(
                id=_identifier(value.id, "recommendation"),
                priority=recommendation_priorities[value.id],
                statement=value.statement,
                finding_ids=ordered_roots,
            )
        )

    capability_provenance: list[CapabilityProvenanceV3] = []
    for value in item.capabilityProvenance:
        if value.type not in {"tool", "skill", "llm", "reviewer"}:
            raise ValueError(f"unsupported source capability type: {value.type}")
        artifact_value = capability_result_artifacts.get(value.id)
        if artifact_value is None:
            raise ValueError(f"missing sealed result Artifact for source capability {value.id}")
        artifact = _source(artifact_value, SealedArtifactRefV3)
        capability_provenance.append(
            CapabilityProvenanceV3(
                actor_type=cast(ActorType, value.type),
                actor_id=_identifier(value.id, "actor"),
                result_artifact=artifact,
            )
        )

    recommendation_id_map = {
        value.id: _identifier(value.id, "recommendation") for value in item.recommendations
    }
    return ResearchDeliverableV3(
        schema_version="research-deliverable-v3",
        run_id=_identifier(item.taskId, "run"),
        requirement_version_id=requirement_version_id,
        plan_version_id=_identifier(item.planVersionId, "plan"),
        attempt_id=_identifier(item.attemptId, "attempt"),
        deliverable_type="competitive_analysis_report",
        payload_schema_version="competitive-analysis-text-v1",
        evidence_manifest_artifact=EvidenceManifestArtifactRefV3.model_validate(
            manifest.model_dump(mode="python")
        ),
        method_summary=item.methodSummary,
        finding_graph=finding_graph,
        payload=_translate_competitive_payload(item),
        recommendations=tuple(recommendations),
        coverage=ResearchDeliverableCoverageV3(
            question_coverage=tuple(
                QuestionCoverageV3(
                    question_id=_identifier(value.questionId, "question"),
                    summary_ids=tuple(summary_id_map[item] for item in value.summaryIds),
                )
                for value in item.coverage.questionBindings
            ),
            success_criterion_coverage=tuple(
                SuccessCriterionCoverageV3(
                    success_criterion_id=_identifier(value.successCriterionId, "criterion"),
                    conclusion_or_recommendation_ids=tuple(
                        [conclusion_id_map[item] for item in value.conclusionIds]
                        + [recommendation_id_map[item] for item in value.recommendationIds]
                    ),
                )
                for value in item.coverage.successCriterionBindings
            ),
        ),
        risks_and_open_issues=item.risksAndOpenIssues,
        capability_provenance=tuple(capability_provenance),
    )


def translate_ai_x_report_review_v1(
    source: AiXReportReviewV1 | Mapping[str, Any],
    *,
    deliverable_artifact: SealedArtifactRefV3 | Mapping[str, Any],
    rubric_snapshot_hash: str,
    deterministic_checks: tuple[DeterministicReviewCheckV3, ...],
    semantic_model_call_receipt_id: str | None,
) -> ReportReviewV3:
    item = _source(source, AiXReportReviewV1)
    artifact = _artifact_ref(
        deliverable_artifact,
        kind="research_deliverable",
        schema_version="research-deliverable-v3",
    )
    if artifact.artifact_id != item.deliverableArtifactId:
        raise ValueError("source review Deliverable ID does not match the sealed Artifact")
    return ReportReviewV3(
        schema_version="report-review-v3",
        run_id=_identifier(item.taskId, "run"),
        plan_version_id=_identifier(item.planVersionId, "plan"),
        attempt_id=_identifier(item.attemptId, "attempt"),
        deliverable_artifact=artifact,
        rubric_snapshot_hash=rubric_snapshot_hash,
        deterministic_checks=deterministic_checks,
        semantic_model_call_receipt_id=semantic_model_call_receipt_id,
        verdict=item.verdict,
        dimensions=tuple(
            ReviewDimensionV3(id=value.id, passed=value.passed, issues=value.issues)
            for value in item.dimensions
        ),
        revision_round=item.revisionRound,
    )


def _asset_ref(value: AiXAssetRefV1) -> AssetRefV3:
    return AssetRefV3(
        asset_id=_identifier(value.assetId, "asset"),
        manifest_artifact_id=_identifier(value.manifestArtifactId, "artifact"),
    )


def _translate_report_block(value: AiXReportBlockV1) -> ReportBlockV3:
    if isinstance(value, AiXParagraphBlockV1):
        return ParagraphBlockV3(id=_identifier(value.id, "block"), text=value.text)
    if isinstance(value, AiXFactBlockV1):
        return FactBlockV3(
            id=_identifier(value.id, "block"),
            text=value.text,
            evidence_ids=tuple(_identifier(item, "evidence") for item in value.evidenceIds),
        )
    if isinstance(value, AiXMetricBlockV1):
        return MetricBlockV3(
            id=_identifier(value.id, "block"),
            label=value.label,
            value=value.value,
            evidence_ids=tuple(_identifier(item, "evidence") for item in value.evidenceIds),
        )
    if isinstance(value, AiXListBlockV1):
        return ListBlockV3(id=_identifier(value.id, "block"), items=value.items)
    if isinstance(value, AiXImageBlockV1):
        if value.evidenceIds is None:
            raise ValueError("source image blocks require Evidence IDs for research-v3")
        return ImageBlockV3(
            id=_identifier(value.id, "block"),
            asset_ref=_asset_ref(value.assetRef),
            caption=value.caption,
            alt_text=value.altText,
            evidence_ids=tuple(_identifier(item, "evidence") for item in value.evidenceIds),
        )
    if isinstance(value, AiXImageComparisonBlockV1):
        if value.evidenceIds is None:
            raise ValueError("source image-comparison blocks require Evidence IDs for research-v3")
        return ImageComparisonBlockV3(
            id=_identifier(value.id, "block"),
            before_asset_ref=_asset_ref(value.beforeAssetRef),
            after_asset_ref=_asset_ref(value.afterAssetRef),
            caption=value.caption,
            alt_text=value.altText,
            evidence_ids=tuple(_identifier(item, "evidence") for item in value.evidenceIds),
        )
    if isinstance(value, AiXChartBlockV1):
        return ChartBlockV3(
            id=_identifier(value.id, "block"),
            chart_ref=ChartRefV3(
                chart_id=_identifier(value.chartRef.chartId, "chart"),
                asset_id=_identifier(value.chartRef.assetId, "asset"),
                manifest_artifact_id=_identifier(value.chartRef.manifestArtifactId, "artifact"),
            ),
            spec_hash=value.specHash.removeprefix("sha256:"),
            spec=value.spec.model_dump(mode="python"),
            table=value.table.model_dump(mode="python"),
            caption=value.caption,
            alt_text=value.altText,
        )
    raise TypeError(f"unsupported source report block: {type(value).__name__}")


def translate_ai_x_report_document_v1(
    source: AiXReportDocumentV1 | Mapping[str, Any],
    *,
    presentation_mode: Literal["text", "multimodal"],
    run_id: str,
    requirement_version_id: str,
    plan_version_id: str,
    attempt_id: str,
    deliverable_artifact: SealedArtifactRefV3 | Mapping[str, Any],
    review_artifact: SealedArtifactRefV3 | Mapping[str, Any],
    template_snapshot_hash: str,
) -> ReportDocumentV3:
    item = _source(source, AiXReportDocumentV1)
    return ReportDocumentV3(
        schema_version="report-document-v3",
        presentation_mode=presentation_mode,
        run_id=run_id,
        requirement_version_id=requirement_version_id,
        plan_version_id=plan_version_id,
        attempt_id=attempt_id,
        deliverable_artifact=_artifact_ref(
            deliverable_artifact,
            kind="research_deliverable",
            schema_version="research-deliverable-v3",
        ),
        review_artifact=_artifact_ref(
            review_artifact,
            kind="report_review",
            schema_version="report-review-v3",
        ),
        template_snapshot_hash=template_snapshot_hash,
        title=item.title,
        subtitle=item.subtitle,
        executive_summary=item.executiveSummary,
        sections=tuple(
            ReportSectionV3(
                id=_identifier(section.id, "section"),
                title=section.title,
                question_ids=tuple(_identifier(value, "question") for value in section.questionIds),
                blocks=tuple(_translate_report_block(value) for value in section.blocks),
            )
            for section in item.sections
        ),
    )
