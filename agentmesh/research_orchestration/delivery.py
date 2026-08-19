from __future__ import annotations

import html
import json
import re
from enum import StrEnum
from functools import cache
from typing import Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.research_orchestration.artifacts import (
    ArtifactDraft,
    ArtifactLease,
    ArtifactLineage,
    ArtifactRef,
    ArtifactStore,
    contains_sensitive_artifact_content,
)
from agentmesh.research_orchestration.compiler import PlanCompileError, validate_execution_plan_version
from agentmesh.research_orchestration.contracts import ExecutionPlanVersion, canonical_sha256
from agentmesh.research_orchestration.evidence import (
    EVIDENCE_MANIFEST_KIND,
    EVIDENCE_MANIFEST_SCHEMA,
    EVIDENCE_SOURCE_KIND,
    EVIDENCE_SOURCE_SCHEMA,
    EvidenceError,
    EvidenceManifest,
    EvidenceService,
    EvidenceSource,
    resolve_json_pointer,
)
from agentmesh.store import ResearchStoreConflict

SKILL_RESULT_KIND = "skill_result"
SKILL_RESULT_SCHEMA = "competitive-analysis-output-v1"
CLAIM_LEDGER_KIND = "claim_ledger"
CLAIM_LEDGER_SCHEMA = "claim-ledger-v1"
DELIVERABLE_KIND = "deliverable"
DELIVERABLE_SCHEMA = "deliverable-document-v1"
REVIEW_KIND = "review"
REVIEW_SCHEMA = "deterministic-review-v1"
REPORT_KIND = "report"
REPORT_SCHEMA = "report-document-v1"


class DeliveryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ClaimType(StrEnum):
    FACT = "fact"
    INFERENCE = "inference"
    RECOMMENDATION = "recommendation"


class ClaimConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SkillClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(pattern="^claim_[a-zA-Z0-9_-]+$", max_length=120)
    statement: str = Field(min_length=1, max_length=8000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    parent_claim_ids: list[str] = Field(default_factory=list, max_length=40)
    question_ids: list[str] = Field(min_length=1, max_length=20)
    success_criterion_ids: list[str] = Field(min_length=1, max_length=20)
    confidence: ClaimConfidence
    conflict_status: Literal["unknown", "none", "possible", "conflicting"]

    @model_validator(mode="after")
    def validate_unique_references(self) -> SkillClaim:
        for values in (
            self.evidence_ids,
            self.parent_claim_ids,
            self.question_ids,
            self.success_criterion_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("Claim references must be unique")
        return self


class CompetitiveSkillOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=12000)
    facts: list[SkillClaim] = Field(default_factory=list, max_length=100)
    inferences: list[SkillClaim] = Field(default_factory=list, max_length=100)
    recommendations: list[SkillClaim] = Field(default_factory=list, max_length=100)
    gaps: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_claim_ids(self) -> CompetitiveSkillOutput:
        claims = [*self.facts, *self.inferences, *self.recommendations]
        claim_ids = [claim.claim_id for claim in claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("Claim IDs must be unique")
        return self


class ClaimRecord(SkillClaim):
    claim_type: ClaimType
    recommendation: bool
    authoring_actor: Literal["competitive-analysis"] = "competitive-analysis"
    model_call_receipt_id: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_recommendation_flag(self) -> ClaimRecord:
        if self.recommendation != (self.claim_type == ClaimType.RECOMMENDATION):
            raise ValueError("recommendation flag differs from Claim type")
        return self


class ClaimLedger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=CLAIM_LEDGER_SCHEMA, pattern="^claim-ledger-v1$")
    source_skill_artifact: ArtifactRef
    model_call_receipt_id: str = Field(min_length=1, max_length=120)
    claims: list[ClaimRecord] = Field(max_length=300)
    gaps: list[str] = Field(default_factory=list, max_length=200)


class CompetitiveComparisonItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(pattern="^claim_[a-zA-Z0-9_-]+$", max_length=120)
    claim_type: Literal["fact", "inference"]
    statement: str = Field(min_length=1, max_length=8000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    parent_claim_ids: list[str] = Field(default_factory=list, max_length=40)
    confidence: ClaimConfidence
    conflict_status: Literal["unknown", "none", "possible", "conflicting"]


class CompetitiveRecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(pattern="^claim_[a-zA-Z0-9_-]+$", max_length=120)
    statement: str = Field(min_length=1, max_length=8000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    parent_claim_ids: list[str] = Field(min_length=1, max_length=40)
    confidence: ClaimConfidence
    conflict_status: Literal["unknown", "none", "possible", "conflicting"]


class CompetitiveAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=12000)
    summary_claim_ids: list[str] = Field(default_factory=list, max_length=20)
    comparison: list[CompetitiveComparisonItem] = Field(default_factory=list, max_length=200)
    recommendations: list[CompetitiveRecommendationItem] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=200)
    claim_ids: list[str] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def validate_claim_ids(self) -> CompetitiveAnalysisPayload:
        if (
            len(self.claim_ids) != len(set(self.claim_ids))
            or len(self.summary_claim_ids) != len(set(self.summary_claim_ids))
            or not set(self.summary_claim_ids).issubset(self.claim_ids)
        ):
            raise ValueError("Deliverable Claim IDs must be unique")
        return self


class CoverageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1, max_length=120)
    claim_ids: list[str] = Field(default_factory=list, max_length=300)


class DeliverableDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=DELIVERABLE_SCHEMA, pattern="^deliverable-document-v1$")
    task_type: Literal["competitive_research"] = "competitive_research"
    payload: CompetitiveAnalysisPayload
    source_skill_artifact: ArtifactRef
    evidence_manifest_artifact: ArtifactRef
    claim_ledger_artifact: ArtifactRef
    question_coverage: list[CoverageEntry]
    success_criterion_coverage: list[CoverageEntry]


class ReviewCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern="^[a-z0-9_]+$", max_length=120)
    passed: bool


class DeterministicReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=REVIEW_SCHEMA, pattern="^deterministic-review-v1$")
    rubric_version: str = Field(pattern="^competitive-analysis-review-v1$")
    deliverable_artifact: ArtifactRef
    status: Literal["pass", "block"]
    checks: list[ReviewCheck] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_status(self) -> DeterministicReview:
        codes = [check.code for check in self.checks]
        if len(codes) != len(set(codes)):
            raise ValueError("Review check codes must be unique")
        expected = "pass" if all(check.passed for check in self.checks) else "block"
        if self.status != expected:
            raise ValueError("Review status cannot override deterministic checks")
        return self


class ReportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=REPORT_SCHEMA, pattern="^report-document-v1$")
    renderer_version: Literal["competitive-markdown-html-v1"] = "competitive-markdown-html-v1"
    deliverable_artifact: ArtifactRef
    review_artifact: ArtifactRef
    title: str = Field(min_length=1, max_length=500)
    markdown: str = Field(min_length=1)
    html: str = Field(min_length=1)


class DeliveryOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_ledger_ref: ArtifactRef
    deliverable_ref: ArtifactRef
    review_ref: ArtifactRef
    report_ref: ArtifactRef | None = None
    status: Literal["pass", "block"]


def _stable_artifact_id(prefix: str, payload: object) -> str:
    return f"artifact_{prefix}_{canonical_sha256(payload)[:32]}"


def _markdown_escape(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|>\-])", r"\\\1", value)


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _claim_graph_is_acyclic(claims: list[ClaimRecord]) -> bool:
    parents = {claim.claim_id: set(claim.parent_claim_ids) for claim in claims}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(claim_id: str) -> bool:
        if claim_id in visiting:
            return False
        if claim_id in visited:
            return True
        visiting.add(claim_id)
        if any(not visit(parent_id) for parent_id in parents[claim_id]):
            return False
        visiting.remove(claim_id)
        visited.add(claim_id)
        return True

    return all(visit(claim_id) for claim_id in parents)


def _claim_evidence_map(claims: list[ClaimRecord]) -> dict[str, tuple[str, ...]]:
    by_id = {claim.claim_id: claim for claim in claims}

    @cache
    def evidence_for(claim_id: str) -> tuple[str, ...]:
        claim = by_id[claim_id]
        inherited = (
            evidence_id
            for parent_id in claim.parent_claim_ids
            for evidence_id in evidence_for(parent_id)
        )
        return tuple(_ordered_unique([*claim.evidence_ids, *inherited]))

    return {claim_id: evidence_for(claim_id) for claim_id in by_id}


def _summary_from_claims(claims: list[ClaimRecord]) -> tuple[str, list[str]]:
    candidates = [claim for claim in claims if claim.claim_type != ClaimType.RECOMMENDATION] or claims
    selected: list[ClaimRecord] = []
    current_length = 0
    for claim in candidates:
        added = len(claim.statement) + (1 if selected else 0)
        if current_length + added > 12_000:
            continue
        selected.append(claim)
        current_length += added
    if not selected:
        return "No verified claims were produced.", []
    return " ".join(claim.statement for claim in selected), [claim.claim_id for claim in selected]


class ResultPipeline:
    def __init__(self, artifacts: ArtifactStore):
        self.artifacts = artifacts

    def finalize(
        self,
        *,
        plan: ExecutionPlanVersion,
        skill_artifact_ref: ArtifactRef,
        skill_lineage: ArtifactLineage,
        evidence_manifest_ref: ArtifactRef,
        evidence_lineage: ArtifactLineage,
        lease: ArtifactLease,
        model_call_receipt_id: str,
    ) -> DeliveryOutcome:
        try:
            persisted_plan = self.artifacts.repository.get_research_plan_version(plan.id)
        except ResearchStoreConflict:
            raise DeliveryError("delivery_plan_invalid") from None
        if persisted_plan != plan:
            raise DeliveryError("delivery_plan_not_persisted")
        try:
            plan_body = validate_execution_plan_version(plan)
        except PlanCompileError:
            raise DeliveryError("delivery_plan_invalid") from None
        if (
            plan.id != skill_lineage.plan_version_id
            or plan.id != evidence_lineage.plan_version_id
            or plan.run_id != skill_lineage.run_id
            or plan.run_id != evidence_lineage.run_id
            or plan.requirement_version_id != skill_lineage.requirement_version_id
            or plan.requirement_version_id != evidence_lineage.requirement_version_id
            or skill_lineage.attempt_id != evidence_lineage.attempt_id
            or skill_lineage.step_number != 2
            or evidence_lineage.step_number != 1
        ):
            raise DeliveryError("delivery_lineage_invalid")
        receipt = self.artifacts.repository.get_research_model_call_receipt(model_call_receipt_id)
        if (
            receipt is None
            or receipt.run_id != plan.run_id
            or receipt.owner_kind != "attempt"
            or receipt.owner_id != skill_lineage.attempt_id
            or receipt.stage != "competitive-analysis"
        ):
            raise DeliveryError("delivery_model_receipt_invalid")

        evidence_manifest, evidence_sources = self._load_evidence(
            evidence_manifest_ref,
            plan=plan,
            evidence_lineage=evidence_lineage,
        )
        skill_artifact = self.artifacts.read_verified(
            skill_artifact_ref,
            scope=skill_lineage,
            expected_kind=SKILL_RESULT_KIND,
            expected_schema_version=SKILL_RESULT_SCHEMA,
        )
        try:
            skill_payload = json.loads(skill_artifact.content)
            Draft202012Validator(plan_body.control_snapshot.skill.output_schema.content).validate(skill_payload)
            skill_output = CompetitiveSkillOutput.model_validate(skill_payload)
        except (json.JSONDecodeError, JsonSchemaValidationError, RecursionError, TypeError, ValueError):
            raise DeliveryError("delivery_skill_output_invalid") from None

        claims = self._claims(
            skill_output,
            model_call_receipt_id=model_call_receipt_id,
            evidence_sources=evidence_sources,
            evidence_policy=plan_body.control_snapshot.evidence_policy.content,
            plan=plan_body.problem_contract,
        )
        ledger_gaps = _ordered_unique(
            [
                *(gap.value for gap in evidence_manifest.gap_codes),
                *(
                    ["source_conflict"]
                    if any(claim.conflict_status in {"possible", "conflicting"} for claim in claims)
                    else []
                ),
            ]
        )
        ledger = ClaimLedger(
            source_skill_artifact=skill_artifact_ref,
            model_call_receipt_id=model_call_receipt_id,
            claims=claims,
            gaps=ledger_gaps,
        )
        ledger_id = _stable_artifact_id(
            "claims",
            {
                "plan_id": plan.id,
                "skill_artifact": skill_artifact_ref.model_dump(mode="json"),
                "evidence_manifest": evidence_manifest_ref.model_dump(mode="json"),
            },
        )
        ledger_ref = ArtifactRef(
            artifact_id=ledger_id,
            content_hash=canonical_sha256(ledger.model_dump(mode="json")),
        )
        deliverable = self._deliverable(
            skill_output,
            claims=claims,
            gaps=ledger_gaps,
            skill_artifact_ref=skill_artifact_ref,
            evidence_manifest_ref=evidence_manifest_ref,
            ledger_ref=ledger_ref,
            plan=plan_body.problem_contract,
        )
        try:
            Draft202012Validator(plan_body.control_snapshot.deliverable_contract.content).validate(
                deliverable.payload.model_dump(mode="json")
            )
        except JsonSchemaValidationError:
            raise DeliveryError("delivery_payload_invalid") from None
        deliverable_id = _stable_artifact_id(
            "deliverable",
            {
                "plan_id": plan.id,
                "ledger": ledger_ref.model_dump(mode="json"),
                "payload": deliverable.payload.model_dump(mode="json"),
            },
        )
        deliverable_ref = ArtifactRef(
            artifact_id=deliverable_id,
            content_hash=canonical_sha256(deliverable.model_dump(mode="json")),
        )
        review = self._review(
            deliverable,
            deliverable_ref=deliverable_ref,
            claims=claims,
            evidence_sources=evidence_sources,
            evidence_manifest=evidence_manifest,
            plan=plan_body.problem_contract,
            evidence_policy=plan_body.control_snapshot.evidence_policy.content,
            review_rubric=plan_body.control_snapshot.review_rubric.content,
        )
        review_id = _stable_artifact_id(
            "review",
            {
                "deliverable": deliverable_ref.model_dump(mode="json"),
                "rubric": review.rubric_version,
            },
        )
        review_ref = ArtifactRef(
            artifact_id=review_id,
            content_hash=canonical_sha256(review.model_dump(mode="json")),
        )
        report: ReportDocument | None = None
        report_ref: ArtifactRef | None = None
        if review.status == "pass":
            report = self._render_report(deliverable, deliverable_ref=deliverable_ref, review_ref=review_ref)
            report_id = _stable_artifact_id(
                "report",
                {
                    "deliverable": deliverable_ref.model_dump(mode="json"),
                    "review": review_ref.model_dump(mode="json"),
                },
            )
            report_ref = ArtifactRef(
                artifact_id=report_id,
                content_hash=canonical_sha256(report.model_dump(mode="json")),
            )

        drafts = [
            ArtifactDraft(
                artifact_id=ledger_ref.artifact_id,
                kind=CLAIM_LEDGER_KIND,
                schema_version=CLAIM_LEDGER_SCHEMA,
                content=ledger,
            ),
            ArtifactDraft(
                artifact_id=deliverable_ref.artifact_id,
                kind=DELIVERABLE_KIND,
                schema_version=DELIVERABLE_SCHEMA,
                content=deliverable,
            ),
            ArtifactDraft(
                artifact_id=review_ref.artifact_id,
                kind=REVIEW_KIND,
                schema_version=REVIEW_SCHEMA,
                content=review,
            ),
        ]
        expected_refs = [ledger_ref, deliverable_ref, review_ref]
        if report is not None and report_ref is not None:
            drafts.append(
                ArtifactDraft(
                    artifact_id=report_ref.artifact_id,
                    kind=REPORT_KIND,
                    schema_version=REPORT_SCHEMA,
                    content=report,
                )
            )
            expected_refs.append(report_ref)
        actual_refs = self.artifacts.seal_bundle(skill_lineage, drafts, lease=lease)
        if actual_refs != expected_refs:
            raise DeliveryError("delivery_artifact_hash_mismatch")
        return DeliveryOutcome(
            claim_ledger_ref=ledger_ref,
            deliverable_ref=deliverable_ref,
            review_ref=review_ref,
            report_ref=report_ref,
            status=review.status,
        )

    def _load_evidence(
        self,
        manifest_ref: ArtifactRef,
        *,
        plan: ExecutionPlanVersion,
        evidence_lineage: ArtifactLineage,
    ) -> tuple[EvidenceManifest, dict[str, EvidenceSource]]:
        manifest_artifact = self.artifacts.read_verified(
            manifest_ref,
            scope=evidence_lineage,
            expected_kind=EVIDENCE_MANIFEST_KIND,
            expected_schema_version=EVIDENCE_MANIFEST_SCHEMA,
        )
        try:
            manifest = EvidenceManifest.model_validate_json(manifest_artifact.content)
        except (TypeError, ValueError):
            raise DeliveryError("delivery_evidence_manifest_invalid") from None
        sources: dict[str, EvidenceSource] = {}
        evidence_service = EvidenceService(self.artifacts)
        for entry in manifest.entries:
            entry_ref = ArtifactRef(artifact_id=entry.artifact_id, content_hash=entry.content_hash)
            artifact = self.artifacts.read_verified(
                entry_ref,
                scope=evidence_lineage,
                expected_kind=EVIDENCE_SOURCE_KIND,
                expected_schema_version=EVIDENCE_SOURCE_SCHEMA,
            )
            try:
                source = EvidenceSource.model_validate_json(artifact.content)
            except (RecursionError, TypeError, ValueError):
                raise DeliveryError("delivery_evidence_source_invalid") from None
            expected_scope = {
                "user_id": evidence_lineage.user_id,
                "workspace_id": evidence_lineage.workspace_id,
                "project_id": evidence_lineage.project_id,
                "run_id": evidence_lineage.run_id,
            }
            try:
                resolved_quote = resolve_json_pointer(
                    source.model_dump(mode="json"),
                    entry.evidence_pointer,
                )
            except (EvidenceError, RecursionError, TypeError, ValueError):
                raise DeliveryError("delivery_evidence_source_invalid") from None
            if (
                source.evidence_id != entry.evidence_id
                or source.evidence_id in sources
                or source.evidence_pointer != entry.evidence_pointer
                or resolved_quote != source.quote
                or source.applicable_scope != expected_scope
            ):
                raise DeliveryError("delivery_evidence_source_invalid")
            try:
                evidence_service.verify_source_provenance(
                    plan=plan,
                    source_ref=entry_ref,
                    source=source,
                    lineage=evidence_lineage,
                )
            except EvidenceError:
                raise DeliveryError("delivery_evidence_provenance_invalid") from None
            sources[source.evidence_id] = source
        try:
            evidence_service.verify_manifest_provenance(
                plan=plan,
                manifest_ref=manifest_ref,
                manifest=manifest,
                sources=list(sources.values()),
                lineage=evidence_lineage,
            )
        except EvidenceError:
            raise DeliveryError("delivery_evidence_provenance_invalid") from None
        return manifest, sources

    @staticmethod
    def _claims(
        output: CompetitiveSkillOutput,
        *,
        model_call_receipt_id: str,
        evidence_sources: dict[str, EvidenceSource],
        evidence_policy: object,
        plan,
    ) -> list[ClaimRecord]:
        if not isinstance(evidence_policy, dict):
            raise DeliveryError("delivery_evidence_policy_invalid")
        provider_summary_policy = evidence_policy.get("provider_summary")
        if (
            evidence_policy.get("version") != "evidence-policy-v1"
            or not isinstance(provider_summary_policy, dict)
            or provider_summary_policy.get("maximum_confidence") != ClaimConfidence.MEDIUM.value
        ):
            raise DeliveryError("delivery_evidence_policy_invalid")
        claims = [
            *(
                ClaimRecord(
                    **claim.model_dump(),
                    claim_type=ClaimType.FACT,
                    recommendation=False,
                    model_call_receipt_id=model_call_receipt_id,
                )
                for claim in output.facts
            ),
            *(
                ClaimRecord(
                    **claim.model_dump(),
                    claim_type=ClaimType.INFERENCE,
                    recommendation=False,
                    model_call_receipt_id=model_call_receipt_id,
                )
                for claim in output.inferences
            ),
            *(
                ClaimRecord(
                    **claim.model_dump(),
                    claim_type=ClaimType.RECOMMENDATION,
                    recommendation=True,
                    model_call_receipt_id=model_call_receipt_id,
                )
                for claim in output.recommendations
            ),
        ]
        by_id = {claim.claim_id: claim for claim in claims}
        if len(by_id) != len(claims):
            raise DeliveryError("delivery_claim_id_duplicate")
        known_questions = {question.id: question for question in plan.questions}
        known_criteria = set(plan.success_criterion_ids)
        for claim in claims:
            if not set(claim.evidence_ids).issubset(evidence_sources):
                raise DeliveryError("delivery_unknown_evidence")
            if not set(claim.parent_claim_ids).issubset(by_id) or claim.claim_id in claim.parent_claim_ids:
                raise DeliveryError("delivery_claim_graph_invalid")
            if not set(claim.question_ids).issubset(known_questions):
                raise DeliveryError("delivery_claim_coverage_invalid")
            if not set(claim.success_criterion_ids).issubset(known_criteria):
                raise DeliveryError("delivery_claim_coverage_invalid")
            allowed_criteria = {
                criterion_id
                for question_id in claim.question_ids
                for criterion_id in known_questions[question_id].success_criterion_ids
            }
            if not set(claim.success_criterion_ids).issubset(allowed_criteria):
                raise DeliveryError("delivery_claim_coverage_invalid")
            if claim.claim_type == ClaimType.FACT and (not claim.evidence_ids or claim.parent_claim_ids):
                raise DeliveryError("delivery_claim_evidence_invalid")
            if claim.claim_type == ClaimType.INFERENCE and not (claim.evidence_ids or claim.parent_claim_ids):
                raise DeliveryError("delivery_claim_evidence_invalid")
            if claim.claim_type == ClaimType.RECOMMENDATION and not claim.parent_claim_ids:
                raise DeliveryError("delivery_recommendation_parent_missing")
        if not _claim_graph_is_acyclic(claims):
            raise DeliveryError("delivery_claim_graph_invalid")
        for claim in claims:
            parent_types = {by_id[parent_id].claim_type for parent_id in claim.parent_claim_ids}
            if claim.claim_type == ClaimType.RECOMMENDATION and not parent_types.issubset(
                {ClaimType.FACT, ClaimType.INFERENCE}
            ):
                raise DeliveryError("delivery_claim_graph_invalid")
            if claim.claim_type == ClaimType.INFERENCE and ClaimType.RECOMMENDATION in parent_types:
                raise DeliveryError("delivery_claim_graph_invalid")

        conflict_rank = {"none": 0, "unknown": 1, "possible": 2, "conflicting": 3}

        @cache
        def effective_conflict(claim_id: str) -> str:
            claim = by_id[claim_id]
            values = [
                claim.conflict_status,
                *(["unknown"] if claim.evidence_ids else []),
                *(effective_conflict(parent_id) for parent_id in claim.parent_claim_ids),
            ]
            return max(values, key=conflict_rank.__getitem__)

        claims = [
            claim.model_copy(update={"conflict_status": effective_conflict(claim.claim_id)})
            for claim in claims
        ]
        evidence_by_claim = _claim_evidence_map(claims)
        return [
            claim.model_copy(update={"confidence": ClaimConfidence.MEDIUM})
            if claim.confidence == ClaimConfidence.HIGH
            and evidence_by_claim[claim.claim_id]
            and all(
                evidence_sources[evidence_id].source_tier == "provider_summary"
                for evidence_id in evidence_by_claim[claim.claim_id]
            )
            else claim
            for claim in claims
        ]

    @staticmethod
    def _deliverable(
        output: CompetitiveSkillOutput,
        *,
        claims: list[ClaimRecord],
        gaps: list[str],
        skill_artifact_ref: ArtifactRef,
        evidence_manifest_ref: ArtifactRef,
        ledger_ref: ArtifactRef,
        plan,
    ) -> DeliverableDocument:
        evidence_by_claim = _claim_evidence_map(claims)
        summary, summary_claim_ids = _summary_from_claims(claims)
        payload = CompetitiveAnalysisPayload(
            summary=summary,
            summary_claim_ids=summary_claim_ids,
            comparison=[
                CompetitiveComparisonItem(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type.value,
                    statement=claim.statement,
                    evidence_ids=list(evidence_by_claim[claim.claim_id]),
                    parent_claim_ids=claim.parent_claim_ids,
                    confidence=claim.confidence,
                    conflict_status=claim.conflict_status,
                )
                for claim in claims
                if claim.claim_type in {ClaimType.FACT, ClaimType.INFERENCE}
            ],
            recommendations=[
                CompetitiveRecommendationItem(
                    claim_id=claim.claim_id,
                    statement=claim.statement,
                    evidence_ids=list(evidence_by_claim[claim.claim_id]),
                    parent_claim_ids=claim.parent_claim_ids,
                    confidence=claim.confidence,
                    conflict_status=claim.conflict_status,
                )
                for claim in claims
                if claim.claim_type == ClaimType.RECOMMENDATION
            ],
            limitations=gaps,
            claim_ids=[claim.claim_id for claim in claims],
        )
        return DeliverableDocument(
            payload=payload,
            source_skill_artifact=skill_artifact_ref,
            evidence_manifest_artifact=evidence_manifest_ref,
            claim_ledger_artifact=ledger_ref,
            question_coverage=[
                CoverageEntry(
                    target_id=question.id,
                    claim_ids=[claim.claim_id for claim in claims if question.id in claim.question_ids],
                )
                for question in plan.questions
            ],
            success_criterion_coverage=[
                CoverageEntry(
                    target_id=criterion_id,
                    claim_ids=[
                        claim.claim_id
                        for claim in claims
                        if criterion_id in claim.success_criterion_ids
                    ],
                )
                for criterion_id in plan.success_criterion_ids
            ],
        )

    @staticmethod
    def _review(
        deliverable: DeliverableDocument,
        *,
        deliverable_ref: ArtifactRef,
        claims: list[ClaimRecord],
        evidence_sources: dict[str, EvidenceSource],
        evidence_manifest: EvidenceManifest,
        plan,
        evidence_policy: object,
        review_rubric: object,
    ) -> DeterministicReview:
        if not isinstance(review_rubric, dict) or review_rubric.get("version") != "competitive-analysis-review-v1":
            raise DeliveryError("delivery_review_rubric_invalid")
        deterministic = review_rubric.get("deterministic")
        semantic = review_rubric.get("semantic")
        if not isinstance(deterministic, dict) or semantic != {"enabled": False}:
            raise DeliveryError("delivery_review_rubric_invalid")
        if not isinstance(evidence_policy, dict):
            raise DeliveryError("delivery_evidence_policy_invalid")
        provider_summary = evidence_policy.get("provider_summary")
        if not isinstance(provider_summary, dict):
            raise DeliveryError("delivery_evidence_policy_invalid")
        minimum_sources = provider_summary.get("minimum_sources")
        independent_required = provider_summary.get("independent_sources")
        if (
            evidence_policy.get("version") != "evidence-policy-v1"
            or not isinstance(minimum_sources, int)
            or isinstance(minimum_sources, bool)
            or not isinstance(independent_required, bool)
            or provider_summary.get("maximum_confidence") != "medium"
        ):
            raise DeliveryError("delivery_evidence_policy_invalid")
        evidence_by_claim = _claim_evidence_map(claims)

        required_question_coverage = all(
            any(
                question.id in claim.question_ids
                and (not question.factual or claim.claim_type == ClaimType.FACT)
                for claim in claims
            )
            for question in plan.questions
            if question.required
        )
        success_coverage = all(
            any(criterion_id in claim.success_criterion_ids for claim in claims)
            for criterion_id in plan.success_criterion_ids
        )
        evidence_policy_passed = True
        for question in plan.questions:
            if not question.required or not question.factual:
                continue
            question_claims = [
                claim
                for claim in claims
                if question.id in claim.question_ids and claim.claim_type == ClaimType.FACT
            ]
            evidence_ids = {
                evidence_id
                for claim in question_claims
                for evidence_id in evidence_by_claim[claim.claim_id]
            }
            source_urls = {
                source.canonical_url
                for evidence_id in evidence_ids
                for source in evidence_sources[evidence_id].sources
            }
            independent_groups = {
                source.independent_group
                for evidence_id in evidence_ids
                for source in evidence_sources[evidence_id].sources
            }
            if len(source_urls) < minimum_sources or (
                independent_required and len(independent_groups) < minimum_sources
            ):
                evidence_policy_passed = False
                break
        confidence_cap_passed = all(
            claim.confidence != ClaimConfidence.HIGH or not evidence_by_claim[claim.claim_id]
            for claim in claims
        )
        conflict_confidence_passed = all(
            claim.conflict_status not in {"possible", "conflicting"}
            or claim.confidence == ClaimConfidence.LOW
            for claim in claims
        )
        disclosed_gaps = set(deliverable.payload.limitations)
        required_gaps = {gap.value for gap in evidence_manifest.gap_codes}
        if any(claim.conflict_status in {"possible", "conflicting"} for claim in claims):
            required_gaps.add("source_conflict")
        gap_disclosure_passed = required_gaps.issubset(disclosed_gaps)
        privacy_scope_passed = not contains_sensitive_artifact_content(deliverable.model_dump_json())
        artifact_hash_passed = deliverable_ref.content_hash == canonical_sha256(
            deliverable.model_dump(mode="json")
        )
        checks = [
            ReviewCheck(code="schema_valid", passed=True),
            ReviewCheck(code="claim_graph_valid", passed=True),
            ReviewCheck(code="claim_evidence_valid", passed=True),
            ReviewCheck(code="required_question_coverage", passed=required_question_coverage),
            ReviewCheck(code="success_criterion_coverage", passed=success_coverage),
            ReviewCheck(code="evidence_policy", passed=evidence_policy_passed),
            ReviewCheck(code="provider_summary_confidence_cap", passed=confidence_cap_passed),
            ReviewCheck(code="conflict_confidence_cap", passed=conflict_confidence_passed),
            ReviewCheck(code="gap_disclosure", passed=gap_disclosure_passed),
            ReviewCheck(code="privacy_scope", passed=privacy_scope_passed),
            ReviewCheck(code="artifact_hash", passed=artifact_hash_passed),
        ]
        return DeterministicReview(
            rubric_version=str(review_rubric["version"]),
            deliverable_artifact=deliverable_ref,
            status="pass" if all(check.passed for check in checks) else "block",
            checks=checks,
        )

    @staticmethod
    def _render_report(
        deliverable: DeliverableDocument,
        *,
        deliverable_ref: ArtifactRef,
        review_ref: ArtifactRef,
    ) -> ReportDocument:
        payload = deliverable.payload
        markdown_lines = [
            "# Competitive Analysis Report",
            "",
            "## Summary",
            "",
            _markdown_escape(payload.summary),
            "",
            "Claims: "
            + ", ".join(f"`{_markdown_escape(value)}`" for value in payload.summary_claim_ids),
            "",
            "## Comparison",
            "",
        ]
        for item in payload.comparison:
            markdown_lines.extend(
                [
                    f"### {_markdown_escape(item.claim_type)} · `{_markdown_escape(item.claim_id)}`",
                    "",
                    _markdown_escape(item.statement),
                    "",
                    "Evidence: " + ", ".join(f"`{_markdown_escape(value)}`" for value in item.evidence_ids),
                    "",
                ]
            )
        markdown_lines.extend(["## Recommendations", ""])
        for item in payload.recommendations:
            markdown_lines.extend(
                [
                    f"- `{_markdown_escape(item.claim_id)}` · {_markdown_escape(item.statement)}",
                    "  Evidence: "
                    + ", ".join(f"`{_markdown_escape(value)}`" for value in item.evidence_ids),
                ]
            )
        markdown_lines.extend(["", "## Limitations", ""])
        markdown_lines.extend(f"- {_markdown_escape(value)}" for value in payload.limitations)
        markdown = "\n".join(markdown_lines).strip() + "\n"

        comparison_html = "".join(
            "<section><h3>"
            + html.escape(item.claim_type)
            + " · <code>"
            + html.escape(item.claim_id)
            + "</code></h3><p>"
            + html.escape(item.statement)
            + "</p><p>Evidence: "
            + ", ".join(f"<code>{html.escape(value)}</code>" for value in item.evidence_ids)
            + "</p></section>"
            for item in payload.comparison
        )
        recommendations_html = "".join(
            "<li><code>"
            + html.escape(item.claim_id)
            + "</code> · "
            + html.escape(item.statement)
            + "<br>Evidence: "
            + ", ".join(f"<code>{html.escape(value)}</code>" for value in item.evidence_ids)
            + "</li>"
            for item in payload.recommendations
        )
        limitations_html = "".join(f"<li>{html.escape(value)}</li>" for value in payload.limitations)
        html_document = (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta http-equiv=\"Content-Security-Policy\" "
            "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            "<title>Competitive Analysis Report</title></head><body>"
            "<h1>Competitive Analysis Report</h1><h2>Summary</h2><p>"
            + html.escape(payload.summary)
            + "</p><p>Claims: "
            + ", ".join(f"<code>{html.escape(value)}</code>" for value in payload.summary_claim_ids)
            + "</p><h2>Comparison</h2>"
            + comparison_html
            + "<h2>Recommendations</h2><ul>"
            + recommendations_html
            + "</ul><h2>Limitations</h2><ul>"
            + limitations_html
            + "</ul></body></html>"
        )
        return ReportDocument(
            deliverable_artifact=deliverable_ref,
            review_artifact=review_ref,
            title="Competitive Analysis Report",
            markdown=markdown,
            html=html_document,
        )
