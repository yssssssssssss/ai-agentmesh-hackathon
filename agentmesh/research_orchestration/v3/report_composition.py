from __future__ import annotations

from collections.abc import Mapping

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import (
    CompetitiveTextCatalog,
    load_catalog_document,
)
from agentmesh.research_orchestration.v3.common import SealedArtifactRefV3, Sha256Hex
from agentmesh.research_orchestration.v3.deliverable import FactFindingV3, ResearchDeliverableV3
from agentmesh.research_orchestration.v3.report_document import (
    COMPETITIVE_TEXT_SECTION_ORDER,
    FactBlockV3,
    ListBlockV3,
    ParagraphBlockV3,
    ReportBlockV3,
    ReportDocumentV3,
    ReportSectionV3,
)
from agentmesh.research_orchestration.v3.review import PassedReportReviewV3


class ReportCompositionError(ValueError):
    pass


class CompetitiveTextReportCompositionService:
    """Compose a pass-only, text-only ReportDocument from the frozen report template."""

    def __init__(
        self,
        *,
        template_snapshot_hash: Sha256Hex,
        sections: tuple[tuple[str, str], ...],
    ) -> None:
        if tuple(section_id for section_id, _ in sections) != COMPETITIVE_TEXT_SECTION_ORDER:
            raise ReportCompositionError("report template section order is not the frozen Competitive Text order")
        self._template_snapshot_hash = template_snapshot_hash
        self._sections = sections

    @classmethod
    def from_catalog(
        cls,
        catalog: CompetitiveTextCatalog,
    ) -> CompetitiveTextReportCompositionService:
        deliverable = next(
            (item for item in catalog.deliverables if item.id == "competitive_analysis_report"),
            None,
        )
        if deliverable is None:
            raise ReportCompositionError("Competitive Text catalog lacks its Deliverable definition")
        document = next(
            (item for item in catalog.documents if item.id == deliverable.report_template),
            None,
        )
        if document is None:
            raise ReportCompositionError("Competitive Text catalog lacks its frozen report template")
        raw = load_catalog_document(catalog, document.id)
        if not isinstance(raw, Mapping):
            raise ReportCompositionError("frozen report template is not an object")
        if (
            raw.get("schema_version") != "report-template-v3"
            or raw.get("presentation_mode") != "text"
        ):
            raise ReportCompositionError("frozen report template has an unexpected identity or mode")
        raw_sections = raw.get("sections")
        if not isinstance(raw_sections, list):
            raise ReportCompositionError("frozen report template sections are absent")
        sections: list[tuple[str, str]] = []
        for raw_section in raw_sections:
            if not isinstance(raw_section, Mapping):
                raise ReportCompositionError("frozen report template section is not an object")
            section_id = raw_section.get("id")
            title = raw_section.get("title")
            if not isinstance(section_id, str) or not isinstance(title, str):
                raise ReportCompositionError("frozen report template section identity is invalid")
            sections.append((section_id, title))
        return cls(
            template_snapshot_hash=document.sha256,
            sections=tuple(sections),
        )

    def compose(
        self,
        *,
        deliverable: ResearchDeliverableV3,
        deliverable_artifact: SealedArtifactRefV3,
        review: PassedReportReviewV3,
        review_artifact: SealedArtifactRefV3,
    ) -> ReportDocumentV3:
        if not isinstance(review, PassedReportReviewV3) or review.verdict != "pass":
            raise ReportCompositionError("report composition accepts only a pass-typed Review")
        if (
            deliverable_artifact.kind != "research_deliverable"
            or deliverable_artifact.schema_version != "research-deliverable-v3"
            or canonical_json_v3_sha256(deliverable) != deliverable_artifact.content_hash
        ):
            raise ReportCompositionError("Deliverable Artifact does not verify")
        if (
            review_artifact.kind != "report_review"
            or review_artifact.schema_version != "report-review-v3"
            or canonical_json_v3_sha256(review) != review_artifact.content_hash
        ):
            raise ReportCompositionError("Review Artifact does not verify")
        if review.deliverable_artifact != deliverable_artifact:
            raise ReportCompositionError("Review does not bind the composed Deliverable")
        if (
            review.run_id,
            review.requirement_version_id,
            review.plan_version_id,
            review.attempt_id,
        ) != (
            deliverable.run_id,
            deliverable.requirement_version_id,
            deliverable.plan_version_id,
            deliverable.attempt_id,
        ):
            raise ReportCompositionError("Review and Deliverable lineage do not agree")

        sample_names = tuple(item.name for item in deliverable.payload.competitor_samples)
        title = " vs ".join(sample_names) + " — Competitive Analysis"
        executive_summary = _executive_summary(deliverable)
        content = _section_content(deliverable, title, executive_summary)
        sections = tuple(
            ReportSectionV3(
                id=section_id,
                title=section_title,
                question_ids=content[section_id][0],
                blocks=content[section_id][1],
            )
            for section_id, section_title in self._sections
        )
        return ReportDocumentV3(
            schema_version="report-document-v3",
            presentation_mode="text",
            review_verdict="pass",
            run_id=deliverable.run_id,
            requirement_version_id=deliverable.requirement_version_id,
            plan_version_id=deliverable.plan_version_id,
            attempt_id=deliverable.attempt_id,
            deliverable_artifact=deliverable_artifact,
            review_artifact=review_artifact,
            template_snapshot_hash=self._template_snapshot_hash,
            title=title,
            subtitle="Evidence-backed Competitive Text research",
            executive_summary=executive_summary,
            sections=sections,
        )


def _executive_summary(deliverable: ResearchDeliverableV3) -> str:
    if deliverable.payload.management_summary:
        return " ".join(deliverable.payload.management_summary)
    conclusions = tuple(item.statement for item in deliverable.finding_graph.overall_conclusions)
    if conclusions:
        return " ".join(conclusions)
    return deliverable.method_summary


def _section_content(
    deliverable: ResearchDeliverableV3,
    title: str,
    executive_summary: str,
) -> dict[str, tuple[tuple[str, ...], tuple[ReportBlockV3, ...]]]:
    payload = deliverable.payload
    findings: list[ReportBlockV3] = []
    for index, finding in enumerate(deliverable.finding_graph.findings, start=1):
        if isinstance(finding, FactFindingV3):
            findings.append(
                FactBlockV3(
                    id=f"finding-fact-{index}",
                    type="fact",
                    text=finding.statement,
                    evidence_ids=_stable_unique(finding.evidence_ids),
                )
            )
        else:
            findings.append(
                ParagraphBlockV3(
                    id=f"finding-inference-{index}",
                    type="paragraph",
                    text=finding.statement,
                )
            )
    for index, difference in enumerate(payload.differences, start=1):
        findings.append(
            FactBlockV3(
                id=f"finding-difference-{index}",
                type="fact",
                text=f"{difference.dimension}: {difference.statement}",
                evidence_ids=_stable_unique(difference.evidence_ids),
            )
        )

    summaries = {
        item.id: item.summary for item in deliverable.finding_graph.sub_question_summaries
    }
    question_blocks: list[ReportBlockV3] = []
    question_ids: list[str] = []
    for index, coverage in enumerate(deliverable.coverage.question_coverage, start=1):
        question_ids.append(coverage.question_id)
        text = " ".join(summaries[summary_id] for summary_id in coverage.summary_ids)
        question_blocks.append(
            ParagraphBlockV3(
                id=f"question-analysis-{index}",
                type="paragraph",
                text=text,
            )
        )

    sample_blocks: tuple[ReportBlockV3, ...] = tuple(
        FactBlockV3(
            id=f"scope-sample-{index}",
            type="fact",
            text=f"{sample.name}: {sample.rationale}",
            evidence_ids=_stable_unique(sample.evidence_ids),
        )
        for index, sample in enumerate(payload.competitor_samples, start=1)
    )
    matrix_blocks: tuple[ReportBlockV3, ...] = tuple(
        FactBlockV3(
            id=f"comparison-metric-{row_index}-{value_index}",
            type="fact",
            text=(
                f"{row.dimension}: {value.sample_id}={value.value}"
                + (f" (score {value.score})" if value.score is not None else "")
                + (f"; weight={row.weight}" if row.weight is not None else "")
            ),
            evidence_ids=_stable_unique(value.evidence_ids),
        )
        for row_index, row in enumerate(payload.dimension_matrix, start=1)
        for value_index, value in enumerate(row.values, start=1)
    )
    evidence_ids = sorted(_deliverable_evidence_ids(deliverable))

    return {
        "cover": (
            (),
            (
                ParagraphBlockV3(id="cover-title", type="paragraph", text=title),
                ParagraphBlockV3(
                    id="cover-subtitle",
                    type="paragraph",
                    text="Evidence-backed Competitive Text research",
                ),
            ),
        ),
        "executive-summary": (
            (),
            (
                ParagraphBlockV3(
                    id="executive-summary-text",
                    type="paragraph",
                    text=executive_summary,
                ),
            ),
        ),
        "background": (
            (),
            (
                ParagraphBlockV3(
                    id="background-method",
                    type="paragraph",
                    text=deliverable.method_summary,
                ),
            ),
        ),
        "scope-method": ((), sample_blocks),
        "key-metrics": ((), matrix_blocks),
        "findings": (tuple(question_ids), tuple(findings)),
        "question-analysis": (tuple(question_ids), tuple(question_blocks)),
        "visual-evidence": (
            (),
            (
                ParagraphBlockV3(
                    id="visual-evidence-omission",
                    type="paragraph",
                    text="Visual evidence is intentionally omitted in the Competitive Text slice.",
                ),
            ),
        ),
        "comparison": (
            (),
            (
                ListBlockV3(
                    id="competitive-impacts",
                    type="list",
                    items=_stable_unique(
                        tuple(
                            f"{impact.audience}: {impact.statement}"
                            for impact in payload.impacts
                        )
                    ),
                ),
            ),
        ),
        "conclusion": (
            (),
            _list_or_fallback(
                block_id="overall-conclusions",
                items=tuple(
                    item.statement
                    for item in deliverable.finding_graph.overall_conclusions
                ),
                fallback="No separate overall conclusion was produced.",
            ),
        ),
        "recommendations": (
            (),
            _list_or_fallback(
                block_id="prioritized-actions",
                items=tuple(
                    f"{item.priority}: {item.statement}"
                    for item in deliverable.recommendations
                ),
                fallback="No additional prioritized action was produced.",
            ),
        ),
        "risks": (
            (),
            _risks_blocks(deliverable),
        ),
        "appendix": (
            (),
            (
                ListBlockV3(
                    id="source-evidence-ids",
                    type="list",
                    items=tuple(evidence_ids),
                ),
            ),
        ),
    }


def _deliverable_evidence_ids(deliverable: ResearchDeliverableV3) -> set[str]:
    identifiers = {
        evidence_id
        for finding in deliverable.finding_graph.findings
        if isinstance(finding, FactFindingV3)
        for evidence_id in finding.evidence_ids
    }
    identifiers.update(
        evidence_id
        for sample in deliverable.payload.competitor_samples
        for evidence_id in sample.evidence_ids
    )
    identifiers.update(
        evidence_id
        for row in deliverable.payload.dimension_matrix
        for value in row.values
        for evidence_id in value.evidence_ids
    )
    identifiers.update(
        evidence_id
        for difference in deliverable.payload.differences
        for evidence_id in difference.evidence_ids
    )
    return identifiers


def _list_or_fallback(
    *,
    block_id: str,
    items: tuple[str, ...],
    fallback: str,
) -> tuple[ReportBlockV3, ...]:
    if items:
        return (ListBlockV3(id=block_id, type="list", items=_stable_unique(items)),)
    return (
        ParagraphBlockV3(
            id=f"{block_id}-empty",
            type="paragraph",
            text=fallback,
        ),
    )


def _risks_blocks(deliverable: ResearchDeliverableV3) -> tuple[ReportBlockV3, ...]:
    if deliverable.risks_and_open_issues:
        return (
            ListBlockV3(
                id="risks-and-open-issues",
                type="list",
                items=_stable_unique(deliverable.risks_and_open_issues),
            ),
        )
    return (
        ParagraphBlockV3(
            id="risks-none-declared",
            type="paragraph",
            text="No additional risks or open issues were declared.",
        ),
    )


def _stable_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
