from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator

from agentmesh.research_orchestration.v3.common import (
    Identifier,
    JsonDecimal,
    NonBlankString,
    Sha256Hex,
    StrictFrozenModel,
    SealedArtifactRefV3,
    require_unique,
)

Text = Annotated[NonBlankString, Field(max_length=20_000)]
COMPETITIVE_TEXT_SECTION_ORDER = (
    "cover",
    "executive-summary",
    "background",
    "scope-method",
    "key-metrics",
    "findings",
    "question-analysis",
    "visual-evidence",
    "comparison",
    "conclusion",
    "recommendations",
    "risks",
    "appendix",
)


class AssetRefV3(StrictFrozenModel):
    asset_id: Identifier
    manifest_artifact_id: Identifier


class ChartRefV3(StrictFrozenModel):
    chart_id: Identifier
    asset_id: Identifier
    manifest_artifact_id: Identifier


class ParagraphBlockV3(StrictFrozenModel):
    id: Identifier
    type: Literal["paragraph"] = "paragraph"
    text: Text


class FactBlockV3(StrictFrozenModel):
    id: Identifier
    type: Literal["fact"] = "fact"
    text: Text
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)


class MetricBlockV3(StrictFrozenModel):
    id: Identifier
    type: Literal["metric"] = "metric"
    label: Annotated[NonBlankString, Field(max_length=500)]
    value: JsonDecimal
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)


class ListBlockV3(StrictFrozenModel):
    id: Identifier
    type: Literal["list"] = "list"
    items: tuple[Text, ...] = Field(min_length=1)


class ImageBlockV3(StrictFrozenModel):
    id: Identifier
    type: Literal["image"] = "image"
    asset_ref: AssetRefV3
    caption: Text
    alt_text: Text
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)


class ImageComparisonBlockV3(StrictFrozenModel):
    id: Identifier
    type: Literal["image-comparison"] = "image-comparison"
    before_asset_ref: AssetRefV3
    after_asset_ref: AssetRefV3
    caption: Text
    alt_text: Text
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)


class ChartBlockV3(StrictFrozenModel):
    id: Identifier
    type: Literal["chart"] = "chart"
    chart_ref: ChartRefV3
    spec_hash: Sha256Hex
    spec: dict[str, Any]
    table: dict[str, Any]
    caption: Text
    alt_text: Text


ReportBlockV3 = Annotated[
    ParagraphBlockV3
    | FactBlockV3
    | MetricBlockV3
    | ListBlockV3
    | ImageBlockV3
    | ImageComparisonBlockV3
    | ChartBlockV3,
    Field(discriminator="type"),
]


class ReportSectionV3(StrictFrozenModel):
    id: Identifier
    title: Annotated[NonBlankString, Field(max_length=500)]
    question_ids: tuple[Identifier, ...]
    blocks: tuple[ReportBlockV3, ...]

    @model_validator(mode="after")
    def validate_section(self) -> ReportSectionV3:
        require_unique(self.question_ids, "section question IDs")
        require_unique(tuple(block.id for block in self.blocks), "section block IDs")
        return self


class ReportDocumentV3(StrictFrozenModel):
    model_config = ConfigDict(json_schema_extra={"$id": "report-document-v3"})

    schema_version: Literal["report-document-v3"] = "report-document-v3"
    presentation_mode: Literal["text", "multimodal"]
    run_id: Identifier
    requirement_version_id: Identifier
    plan_version_id: Identifier
    attempt_id: Identifier
    deliverable_artifact: SealedArtifactRefV3
    review_artifact: SealedArtifactRefV3
    template_snapshot_hash: Sha256Hex
    title: Annotated[NonBlankString, Field(max_length=500)]
    subtitle: Annotated[NonBlankString, Field(max_length=1000)]
    executive_summary: Text
    sections: tuple[ReportSectionV3, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_document(self) -> ReportDocumentV3:
        if self.deliverable_artifact.kind != "research_deliverable" or (
            self.deliverable_artifact.schema_version != "research-deliverable-v3"
        ):
            raise ValueError("report must bind a research-deliverable-v3 Artifact")
        if self.review_artifact.kind != "report_review" or self.review_artifact.schema_version != "report-review-v3":
            raise ValueError("report must bind a report-review-v3 Artifact")
        section_ids = tuple(section.id for section in self.sections)
        require_unique(section_ids, "report section IDs")
        block_ids = tuple(block.id for section in self.sections for block in section.blocks)
        require_unique(block_ids, "report block IDs")
        if self.presentation_mode == "text":
            if section_ids != COMPETITIVE_TEXT_SECTION_ORDER:
                raise ValueError("Competitive Text report sections must follow the frozen template order")
            visual_types = (ImageBlockV3, ImageComparisonBlockV3, ChartBlockV3)
            if any(isinstance(block, visual_types) for section in self.sections for block in section.blocks):
                raise ValueError("Competitive Text reports cannot contain visual blocks")
        return self
