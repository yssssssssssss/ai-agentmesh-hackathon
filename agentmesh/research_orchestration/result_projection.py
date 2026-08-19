"""Build the user-facing research result from verified sealed Artifacts."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from agentmesh.models import Artifact
from agentmesh.research_orchestration.api import (
    ResearchArtifactProjection,
    ResearchClaimProjection,
    ResearchDeliverableProjection,
    ResearchEvidenceProjection,
    ResearchReportProjection,
    ResearchResultProjection,
    ResearchReviewCheckProjection,
    ResearchReviewProjection,
    ResearchSourceLinkProjection,
)
from agentmesh.research_orchestration.artifacts import (
    ArtifactReaderScope,
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    ResearchResultSnapshot,
)
from agentmesh.research_orchestration.delivery import (
    ClaimLedger,
    ClaimRecord,
    DeliverableDocument,
    DeterministicReview,
    ReportDocument,
)
from agentmesh.research_orchestration.evidence import EvidenceManifest, EvidenceSource


@dataclass(frozen=True, slots=True)
class VerifiedResearchResult:
    artifacts: ResearchArtifactProjection
    result: ResearchResultProjection
    integrity_errors: tuple[str, ...]


class _ResultProjectionError(RuntimeError):
    pass


def _read_artifact(
    artifacts: ArtifactStore,
    artifact_id: str,
    *,
    reader_scope: ArtifactReaderScope,
    run_id: str,
    attempt_id: str,
    expected_kind: str,
    expected_reference: ArtifactRef | None = None,
) -> Artifact:
    try:
        artifact = artifacts.read_verified_for_owner(
            artifact_id,
            reader_scope=reader_scope,
            expected_reference=expected_reference,
            invalidate_corrupt=False,
        )
    except ArtifactStoreError as error:
        raise _ResultProjectionError(error.code) from error
    if (
        artifact.run_id != run_id
        or artifact.attempt_id != attempt_id
        or artifact.artifact_type != expected_kind
    ):
        raise _ResultProjectionError("artifact_reference_mismatch")
    return artifact


def _read_model[ModelT: BaseModel](
    artifacts: ArtifactStore,
    artifact_id: str,
    model: type[ModelT],
    *,
    reader_scope: ArtifactReaderScope,
    run_id: str,
    attempt_id: str,
    expected_kind: str,
    expected_reference: ArtifactRef | None = None,
) -> tuple[Artifact, ModelT]:
    artifact = _read_artifact(
        artifacts,
        artifact_id,
        reader_scope=reader_scope,
        run_id=run_id,
        attempt_id=attempt_id,
        expected_kind=expected_kind,
        expected_reference=expected_reference,
    )
    try:
        return artifact, model.model_validate_json(artifact.content)
    except (RecursionError, TypeError, ValueError) as error:
        raise _ResultProjectionError("artifact_payload_invalid") from error


def _reference_matches(reference: ArtifactRef, artifact: Artifact | None) -> bool:
    return bool(
        artifact is not None
        and reference.artifact_id == artifact.id
        and reference.content_hash == artifact.content_hash
    )


def _claim_projection(claim: ClaimRecord) -> ResearchClaimProjection:
    return ResearchClaimProjection(
        claim_id=claim.claim_id,
        claim_type=claim.claim_type.value,
        statement=claim.statement,
        evidence_ids=claim.evidence_ids,
        parent_claim_ids=claim.parent_claim_ids,
        confidence=claim.confidence.value,
        conflict_status=claim.conflict_status,
    )


def build_verified_research_result(
    artifacts: ArtifactStore,
    snapshot: ResearchResultSnapshot,
    *,
    run_id: str,
    attempt_id: str | None,
    reader_scope: ArtifactReaderScope,
) -> VerifiedResearchResult:
    """Parse the sealed result chain once and expose no unverified presentation content."""

    artifact_projection = ResearchArtifactProjection(
        evidence_manifest_id=snapshot.evidence_manifest_id,
        claim_ledger_id=snapshot.claim_ledger_id,
        deliverable_id=snapshot.deliverable_id,
        review_id=snapshot.review_id,
        report_id=snapshot.report_id,
    )
    errors = list(snapshot.integrity_errors)
    if attempt_id is None:
        return VerifiedResearchResult(
            artifacts=artifact_projection,
            result=ResearchResultProjection(),
            integrity_errors=tuple(dict.fromkeys(errors)),
        )

    scoped_reader = reader_scope.model_copy(update={"run_id": run_id})

    def record(kind: str, error: _ResultProjectionError) -> None:
        errors.append(f"{kind}:{error}")

    manifest_artifact: Artifact | None = None
    manifest: EvidenceManifest | None = None
    evidence: list[ResearchEvidenceProjection] = []
    evidence_ids: set[str] = set()
    if snapshot.evidence_manifest_id is not None:
        try:
            manifest_artifact, manifest = _read_model(
                artifacts,
                snapshot.evidence_manifest_id,
                EvidenceManifest,
                reader_scope=scoped_reader,
                run_id=run_id,
                attempt_id=attempt_id,
                expected_kind="evidence_manifest",
            )
            for entry in manifest.entries:
                source_artifact, source = _read_model(
                    artifacts,
                    entry.artifact_id,
                    EvidenceSource,
                    reader_scope=scoped_reader,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    expected_kind="evidence_source",
                    expected_reference=ArtifactRef(
                        artifact_id=entry.artifact_id,
                        content_hash=entry.content_hash,
                    ),
                )
                if source.evidence_id != entry.evidence_id or source.evidence_pointer != entry.evidence_pointer:
                    raise _ResultProjectionError("evidence_manifest_reference_mismatch")
                _read_artifact(
                    artifacts,
                    source.origin_artifact.artifact_id,
                    reader_scope=scoped_reader,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    expected_kind="tool_result",
                    expected_reference=source.origin_artifact,
                )
                if source_artifact.id != entry.artifact_id:
                    raise _ResultProjectionError("evidence_manifest_reference_mismatch")
                evidence_ids.add(source.evidence_id)
                evidence.append(
                    ResearchEvidenceProjection(
                        evidence_id=source.evidence_id,
                        quote=source.quote,
                        sources=[
                            ResearchSourceLinkProjection(
                                source_id=item.source_id,
                                title=item.title,
                                url=item.url,
                                retrieved_at=item.retrieved_at,
                            )
                            for item in source.sources
                        ],
                        conflict_status=source.conflict_status,
                        risk_flags=[item.value for item in source.risk_flags],
                    )
                )
        except _ResultProjectionError as error:
            record("evidence", error)
            manifest = None
            evidence = []
            evidence_ids.clear()
        except (RecursionError, TypeError, ValueError):
            record("evidence", _ResultProjectionError("evidence_presentation_invalid"))
            manifest = None
            evidence = []
            evidence_ids.clear()

    ledger_artifact: Artifact | None = None
    skill_artifact: Artifact | None = None
    ledger: ClaimLedger | None = None
    claims: list[ResearchClaimProjection] = []
    if snapshot.claim_ledger_id is not None:
        try:
            ledger_artifact, ledger = _read_model(
                artifacts,
                snapshot.claim_ledger_id,
                ClaimLedger,
                reader_scope=scoped_reader,
                run_id=run_id,
                attempt_id=attempt_id,
                expected_kind="claim_ledger",
            )
            skill_artifact = _read_artifact(
                artifacts,
                ledger.source_skill_artifact.artifact_id,
                reader_scope=scoped_reader,
                run_id=run_id,
                attempt_id=attempt_id,
                expected_kind="skill_result",
                expected_reference=ledger.source_skill_artifact,
            )
            if any(not set(claim.evidence_ids).issubset(evidence_ids) for claim in ledger.claims):
                raise _ResultProjectionError("claim_evidence_reference_invalid")
            claims = [_claim_projection(claim) for claim in ledger.claims]
        except _ResultProjectionError as error:
            record("claim_ledger", error)
            ledger = None
            claims = []
        except (RecursionError, TypeError, ValueError):
            record("claim_ledger", _ResultProjectionError("claim_presentation_invalid"))
            ledger = None
            claims = []

    deliverable_artifact: Artifact | None = None
    deliverable_projection: ResearchDeliverableProjection | None = None
    if snapshot.deliverable_id is not None:
        try:
            deliverable_artifact, deliverable = _read_model(
                artifacts,
                snapshot.deliverable_id,
                DeliverableDocument,
                reader_scope=scoped_reader,
                run_id=run_id,
                attempt_id=attempt_id,
                expected_kind="deliverable",
            )
            claim_ids = {claim.claim_id for claim in ledger.claims} if ledger is not None else set()
            if (
                manifest is None
                or ledger is None
                or not _reference_matches(deliverable.source_skill_artifact, skill_artifact)
                or not _reference_matches(deliverable.evidence_manifest_artifact, manifest_artifact)
                or not _reference_matches(deliverable.claim_ledger_artifact, ledger_artifact)
                or not set(deliverable.payload.claim_ids).issubset(claim_ids)
            ):
                raise _ResultProjectionError("deliverable_lineage_invalid")
            deliverable_projection = ResearchDeliverableProjection(
                summary=deliverable.payload.summary,
                summary_claim_ids=deliverable.payload.summary_claim_ids,
                comparison=[
                    ResearchClaimProjection(
                        claim_id=item.claim_id,
                        claim_type=item.claim_type,
                        statement=item.statement,
                        evidence_ids=item.evidence_ids,
                        parent_claim_ids=item.parent_claim_ids,
                        confidence=item.confidence.value,
                        conflict_status=item.conflict_status,
                    )
                    for item in deliverable.payload.comparison
                ],
                recommendations=[
                    ResearchClaimProjection(
                        claim_id=item.claim_id,
                        claim_type="recommendation",
                        statement=item.statement,
                        evidence_ids=item.evidence_ids,
                        parent_claim_ids=item.parent_claim_ids,
                        confidence=item.confidence.value,
                        conflict_status=item.conflict_status,
                    )
                    for item in deliverable.payload.recommendations
                ],
                limitations=deliverable.payload.limitations,
            )
        except _ResultProjectionError as error:
            record("deliverable", error)
            deliverable_projection = None
        except (RecursionError, TypeError, ValueError):
            record("deliverable", _ResultProjectionError("deliverable_presentation_invalid"))
            deliverable_projection = None

    review_artifact: Artifact | None = None
    review_projection: ResearchReviewProjection | None = None
    if snapshot.review_id is not None:
        try:
            review_artifact, review = _read_model(
                artifacts,
                snapshot.review_id,
                DeterministicReview,
                reader_scope=scoped_reader,
                run_id=run_id,
                attempt_id=attempt_id,
                expected_kind="review",
            )
            if deliverable_projection is None or not _reference_matches(
                review.deliverable_artifact,
                deliverable_artifact,
            ):
                raise _ResultProjectionError("review_lineage_invalid")
            review_projection = ResearchReviewProjection(
                status=review.status,
                checks=[
                    ResearchReviewCheckProjection(code=check.code, passed=check.passed)
                    for check in review.checks
                ],
            )
        except _ResultProjectionError as error:
            record("review", error)
            review_projection = None
        except (RecursionError, TypeError, ValueError):
            record("review", _ResultProjectionError("review_presentation_invalid"))
            review_projection = None

    report_projection: ResearchReportProjection | None = None
    if snapshot.report_id is not None:
        try:
            _report_artifact, report = _read_model(
                artifacts,
                snapshot.report_id,
                ReportDocument,
                reader_scope=scoped_reader,
                run_id=run_id,
                attempt_id=attempt_id,
                expected_kind="report",
            )
            if (
                deliverable_projection is None
                or review_projection is None
                or not _reference_matches(report.deliverable_artifact, deliverable_artifact)
                or not _reference_matches(report.review_artifact, review_artifact)
            ):
                raise _ResultProjectionError("report_lineage_invalid")
            report_projection = ResearchReportProjection(title=report.title, markdown=report.markdown)
        except _ResultProjectionError as error:
            record("report", error)
            report_projection = None
        except (RecursionError, TypeError, ValueError):
            record("report", _ResultProjectionError("report_presentation_invalid"))
            report_projection = None

    unique_errors = tuple(dict.fromkeys(errors))
    if unique_errors:
        report_projection = None
    safe_artifacts = ResearchArtifactProjection(
        evidence_manifest_id=(snapshot.evidence_manifest_id if manifest is not None else None),
        claim_ledger_id=(snapshot.claim_ledger_id if ledger is not None else None),
        deliverable_id=(snapshot.deliverable_id if deliverable_projection is not None else None),
        review_id=(snapshot.review_id if review_projection is not None else None),
        report_id=(snapshot.report_id if report_projection is not None else None),
    )
    result = (
        ResearchResultProjection(
            evidence=evidence if manifest is not None else [],
            claims=claims if manifest is not None and ledger is not None else [],
            deliverable=deliverable_projection,
            review=review_projection,
            report=report_projection,
        )
        if not unique_errors
        else ResearchResultProjection()
    )
    return VerifiedResearchResult(
        artifacts=safe_artifacts,
        result=result,
        integrity_errors=unique_errors,
    )
