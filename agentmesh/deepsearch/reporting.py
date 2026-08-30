"""Deterministic evidence finalization primitives for DeepSearch.

The model may propose semantic bindings and claims, but it never gets to mint
lineage, declare coverage, or publish a report.  This module keeps those
decisions pure so the Store can commit their outputs with a narrow CAS.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from agentmesh.artifacts import (
    ArtifactAccessError,
    DeepSearchArtifactSchemaRegistry,
    DeepSearchEvidenceManifestItemV1,
    DeepSearchEvidenceManifestV1,
    DeepSearchReportClaimV1,
    DeepSearchReportLimitationV1,
    DeepSearchReportSectionV1,
    DeepSearchReportSourceV1,
    DeepSearchReportV1,
    TrustedEvidenceEnvelopeV1,
)
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.deepsearch.contracts import (
    ProblemGraphV1,
    RequirementVersionV1,
    validate_problem_graph_against_requirement,
)
from agentmesh.deepsearch.planning import plan_content_hash
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    DeepSearchEvidenceCoverageV1,
    DeepSearchEvidenceItemV1,
    DeepSearchReportReviewDraftV1,
    DeepSearchReportReviewV1,
    DeepSearchReviewOutcomeV1,
    DeepSearchSynthesisClaimDraft,
    DeepSearchSynthesisClaimV1,
    DeepSearchSynthesisV1,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNodeStatus,
    Source,
)


class DeepSearchReportingError(RuntimeError):
    """Stable fail-closed error raised for untrusted finalization input."""

    def __init__(self, code: str = "deepsearch_evidence_integrity_failed") -> None:
        self.code = code
        super().__init__(code)


DEEPSEARCH_EVIDENCE_MANIFEST_MAX_BYTES = 131_072
DEEPSEARCH_REPORT_MAX_BYTES = 262_144


@dataclass(frozen=True, slots=True)
class DeepSearchTerminalDecision:
    status: AgentRunStatus
    error_code: str | None


_LIMITATION_DESCRIPTIONS = {
    "required_node_result_missing": "至少一个必需分析步骤没有可验证结果。",
    "claim_reference_invalid": "部分结论未通过证据引用完整性检查，已从报告中移除。",
    "question_uncovered": "部分必需研究问题尚无可信证据覆盖。",
    "success_criterion_uncovered": "部分成功标准尚无可信证据覆盖。",
    "external_evidence_not_real": "所需外部证据未由真实只读工具取得。",
    "deepsearch_budget_exhausted": "本次 DeepSearch 已达到预算上限。",
    "deepsearch_required_coverage_incomplete": "报告仅包含已验证部分，必需覆盖尚不完整。",
    "deepsearch_review_not_passed": "报告审核未通过，争议结论已移除。",
    "deepsearch_optional_node_failed": "至少一个可选分析步骤未完成。",
    "deepsearch_synthesis_fallback": "模型汇总不可用，报告由已封存证据逐字生成。",
    "coverage_failed": "证据覆盖检查未通过。",
    "budget_unavailable": "没有足够预算执行报告审核。",
    "deterministic_digest": "报告使用确定性证据摘要，未执行语义审核。",
    "deepsearch_review_invalid": "报告审核未能返回可验证的结构化结果。",
}


def _require_current_lineage(
    *,
    run: AgentRun,
    plan: SkillPlan,
    requirement: RequirementVersionV1,
    graph: ProblemGraphV1,
) -> None:
    try:
        validate_problem_graph_against_requirement(graph=graph, requirement=requirement)
        expected_plan_hash = plan_content_hash(plan)
    except (ArtifactAccessError, TypeError, ValueError) as error:
        raise DeepSearchReportingError() from error
    if (
        run.orchestration_version != "v1"
        or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
        or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
        or plan.run_id != run.id
        or run.plan_id != plan.id
        or requirement.run_id != run.id
        or plan.requirement_version_id != requirement.id
        or plan.requirement_content_hash != requirement.content_hash
        or plan.problem_graph_hash != graph.content_hash
        or plan.plan_content_hash != expected_plan_hash
    ):
        raise DeepSearchReportingError()


def _verified_evidence_envelope(
    *,
    run: AgentRun,
    plan: SkillPlan,
    artifact: Artifact,
) -> TrustedEvidenceEnvelopeV1:
    encoded = artifact.content.encode("utf-8")
    if (
        artifact.verification_state is not ArtifactVerificationState.SEALED
        or artifact.artifact_type
        not in {
            "deepsearch_tool_evidence",
            "deepsearch_user_evidence",
            "deepsearch_knowledge_evidence",
        }
        or artifact.run_id != run.id
        or artifact.workspace_id != run.workspace_id
        or artifact.project_id != run.project_id
        or artifact.user_id != run.user_id
        or artifact.requirement_version_id != plan.requirement_version_id
        or artifact.content_hash != hashlib.sha256(encoded).hexdigest()
        or artifact.size_bytes != len(encoded)
        or artifact.schema_version is None
    ):
        raise DeepSearchReportingError()
    try:
        parsed = DeepSearchArtifactSchemaRegistry.parse(
            artifact.artifact_type,
            artifact.schema_version,
            artifact.content,
        )
    except (TypeError, ValueError) as error:
        raise DeepSearchReportingError() from error
    if not isinstance(parsed, TrustedEvidenceEnvelopeV1):
        raise DeepSearchReportingError()
    if (
        parsed.run_id != run.id
        or parsed.requirement_version_id != plan.requirement_version_id
    ):
        raise DeepSearchReportingError()
    if parsed.origin_type == "tool":
        node_step_by_id = {
            node.id: step_number for step_number, node in enumerate(plan.nodes, start=1)
        }
        if (
            parsed.plan_id != plan.id
            or parsed.plan_version != plan.version
            or artifact.plan_version_id != f"{plan.id}:v{plan.version}"
            or artifact.attempt_id != f"{parsed.node_id}:attempt:{parsed.attempt}"
            or artifact.step_number != node_step_by_id.get(parsed.node_id or "")
            or parsed.execution_mode != "real"
        ):
            raise DeepSearchReportingError()
    elif artifact.plan_version_id is not None or artifact.attempt_id is not None:
        raise DeepSearchReportingError()
    return parsed


def build_evidence_manifest_artifact(
    *,
    run: AgentRun,
    plan: SkillPlan,
    requirement: RequirementVersionV1,
    graph: ProblemGraphV1,
    results: Sequence[SkillNodeResult],
    evidence_artifacts: Mapping[str, Artifact],
    created_at: datetime,
) -> tuple[DeepSearchEvidenceManifestV1, Artifact]:
    """Validate persisted bindings and build one canonical sealed manifest."""

    _require_current_lineage(run=run, plan=plan, requirement=requirement, graph=graph)
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise DeepSearchReportingError()
    node_by_id = {node.id: node for node in plan.nodes}
    question_by_id = {question.id: question for question in graph.questions}
    if len({result.id for result in results}) != len(results):
        raise DeepSearchReportingError()

    items: list[DeepSearchEvidenceManifestItemV1] = []
    for result in results:
        node = node_by_id.get(result.node_id)
        if node is None or result.attempt != node.attempt:
            raise DeepSearchReportingError()
        allowed_question_ids = set(node.question_ids)
        allowed_criterion_ids = {
            criterion_id
            for question_id in node.question_ids
            for criterion_id in question_by_id[question_id].success_criterion_ids
        }
        for binding in result.evidence_items:
            artifact = evidence_artifacts.get(binding.evidence_artifact_id)
            if artifact is None:
                raise DeepSearchReportingError()
            envelope = _verified_evidence_envelope(run=run, plan=plan, artifact=artifact)
            if (
                binding.node_result_id != result.id
                or not set(binding.question_ids).issubset(allowed_question_ids)
                or not set(binding.success_criterion_ids).issubset(allowed_criterion_ids)
                or binding.source_id != envelope.source_id
            ):
                raise DeepSearchReportingError()
            if envelope.origin_type == "tool" and (
                envelope.node_id != node.id or envelope.attempt != result.attempt
            ):
                raise DeepSearchReportingError()
            items.append(
                DeepSearchEvidenceManifestItemV1(
                    evidence_item_id=binding.id,
                    node_result_id=result.id,
                    evidence_artifact_id=artifact.id,
                    evidence_artifact_content_hash=artifact.content_hash or "",
                    source_id=binding.source_id,
                    origin_type=envelope.origin_type,
                    question_ids=sorted(binding.question_ids),
                    success_criterion_ids=sorted(binding.success_criterion_ids),
                )
            )
    items.sort(key=lambda item: item.evidence_item_id)
    if not items or len({item.evidence_item_id for item in items}) != len(items):
        raise DeepSearchReportingError()

    manifest = DeepSearchEvidenceManifestV1(
        schema_version="deepsearch-evidence-manifest-v1",
        run_id=run.id,
        requirement_version_id=requirement.id,
        plan_id=plan.id,
        plan_version=plan.version,
        plan_content_hash=plan.plan_content_hash or "",
        items=items,
    )
    content = canonical_json_bytes(manifest.model_dump(mode="python")).decode("utf-8")
    encoded = content.encode("utf-8")
    if len(encoded) > DEEPSEARCH_EVIDENCE_MANIFEST_MAX_BYTES:
        raise DeepSearchReportingError("deepsearch_delivery_unavailable")
    artifact_id = "artifact_deepsearch_manifest_" + canonical_json_sha256(
        {"run_id": run.id, "plan_id": plan.id, "plan_version": plan.version}
    )
    artifact = Artifact(
        id=artifact_id,
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="deepsearch_evidence_manifest",
        content_type="application/json",
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="deepsearch-evidence-manifest-v1",
        content_hash=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
        requirement_version_id=requirement.id,
        plan_version_id=f"{plan.id}:v{plan.version}",
        created_at=created_at,
        updated_at=created_at,
    )
    return manifest, artifact


def deepsearch_claim_id(
    *,
    run_id: str,
    plan_id: str,
    plan_version: int,
    revision_count: int,
    ordinal: int,
    claim: DeepSearchSynthesisClaimV1 | Mapping[str, object],
) -> str:
    payload = (
        claim.model_dump(mode="python", exclude={"id"})
        if isinstance(claim, DeepSearchSynthesisClaimV1)
        else {key: value for key, value in claim.items() if key != "id"}
    )
    return "claim_" + canonical_json_sha256(
        {
            "run_id": run_id,
            "plan_id": plan_id,
            "plan_version": plan_version,
            "revision_count": revision_count,
            "ordinal": ordinal,
            "claim": payload,
        }
    )


def materialize_deepsearch_synthesis(
    *,
    run: AgentRun,
    plan: SkillPlan,
    revision_count: int,
    drafts: Sequence[DeepSearchSynthesisClaimDraft | Mapping[str, object]],
) -> DeepSearchSynthesisV1:
    """Validate model output and attach deterministic server-owned claim IDs."""

    if (
        run.id != plan.run_id
        or run.plan_id != plan.id
        or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
        or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
        or revision_count not in {0, 1}
    ):
        raise DeepSearchReportingError()
    claims: list[DeepSearchSynthesisClaimV1] = []
    for ordinal, raw_draft in enumerate(drafts, start=1):
        try:
            draft = DeepSearchSynthesisClaimDraft.model_validate(raw_draft)
        except (TypeError, ValueError) as error:
            raise DeepSearchReportingError("deepsearch_synthesis_invalid") from error
        payload = draft.model_dump(mode="python")
        claims.append(
            DeepSearchSynthesisClaimV1(
                id=deepsearch_claim_id(
                    run_id=run.id,
                    plan_id=plan.id,
                    plan_version=plan.version,
                    revision_count=revision_count,
                    ordinal=ordinal,
                    claim=payload,
                ),
                **payload,
            )
        )
    try:
        return DeepSearchSynthesisV1(
            revision_count=revision_count,
            synthesis_mode="model",
            claims=claims,
        )
    except ValueError as error:
        raise DeepSearchReportingError("deepsearch_synthesis_invalid") from error


def build_deterministic_evidence_digest(
    *,
    run: AgentRun,
    plan: SkillPlan,
    manifest: DeepSearchEvidenceManifestV1,
    evidence_artifacts: Mapping[str, Artifact],
    revision_count: int = 0,
) -> DeepSearchSynthesisV1:
    """Use sealed excerpts verbatim; never infer or join new factual prose."""

    if (
        manifest.run_id != run.id
        or manifest.plan_id != plan.id
        or manifest.plan_version != plan.version
        or manifest.requirement_version_id != plan.requirement_version_id
        or manifest.plan_content_hash != plan.plan_content_hash
    ):
        raise DeepSearchReportingError()
    claims: list[DeepSearchSynthesisClaimV1] = []
    for ordinal, item in enumerate(manifest.items, start=1):
        artifact = evidence_artifacts.get(item.evidence_artifact_id)
        if artifact is None or artifact.content_hash != item.evidence_artifact_content_hash:
            raise DeepSearchReportingError()
        envelope = _verified_evidence_envelope(run=run, plan=plan, artifact=artifact)
        if not envelope.excerpt:
            raise DeepSearchReportingError()
        payload = {
            "text": envelope.excerpt,
            "question_ids": item.question_ids,
            "success_criterion_ids": item.success_criterion_ids,
            "node_result_ids": [item.node_result_id],
            "evidence_item_ids": [item.evidence_item_id],
            "source_ids": [item.source_id] if item.source_id is not None else [],
            "recommendation": False,
        }
        claims.append(
            DeepSearchSynthesisClaimV1(
                id=deepsearch_claim_id(
                    run_id=run.id,
                    plan_id=plan.id,
                    plan_version=plan.version,
                    revision_count=revision_count,
                    ordinal=ordinal,
                    claim=payload,
                ),
                **payload,
            )
        )
    return DeepSearchSynthesisV1(
        revision_count=revision_count,
        synthesis_mode="deterministic_evidence_digest",
        claims=claims,
    )


def evaluate_evidence_coverage(
    *,
    run: AgentRun,
    plan: SkillPlan,
    requirement: RequirementVersionV1,
    graph: ProblemGraphV1,
    results: Sequence[SkillNodeResult],
    manifest: DeepSearchEvidenceManifestV1,
    evidence_artifacts: Mapping[str, Artifact],
    synthesis: DeepSearchSynthesisV1,
) -> DeepSearchEvidenceCoverageV1:
    """Recompute claim-level coverage from current persisted identities."""

    _require_current_lineage(run=run, plan=plan, requirement=requirement, graph=graph)
    if (
        manifest.run_id != run.id
        or manifest.plan_id != plan.id
        or manifest.plan_version != plan.version
        or manifest.requirement_version_id != requirement.id
        or manifest.plan_content_hash != plan.plan_content_hash
    ):
        raise DeepSearchReportingError()

    result_by_id = {result.id: result for result in results}
    item_by_id: dict[str, DeepSearchEvidenceItemV1] = {
        item.id: item for result in results for item in result.evidence_items
    }
    manifest_by_id = {item.evidence_item_id: item for item in manifest.items}
    if len(result_by_id) != len(results) or len(item_by_id) != len(manifest_by_id):
        raise DeepSearchReportingError()
    if set(item_by_id) != set(manifest_by_id):
        raise DeepSearchReportingError()

    envelope_by_item_id: dict[str, TrustedEvidenceEnvelopeV1] = {}
    for item_id, manifest_item in manifest_by_id.items():
        binding = item_by_id[item_id]
        artifact = evidence_artifacts.get(manifest_item.evidence_artifact_id)
        if (
            artifact is None
            or binding.node_result_id != manifest_item.node_result_id
            or binding.evidence_artifact_id != manifest_item.evidence_artifact_id
            or binding.source_id != manifest_item.source_id
            or sorted(binding.question_ids) != manifest_item.question_ids
            or sorted(binding.success_criterion_ids)
            != manifest_item.success_criterion_ids
            or artifact.content_hash != manifest_item.evidence_artifact_content_hash
        ):
            raise DeepSearchReportingError()
        envelope_by_item_id[item_id] = _verified_evidence_envelope(
            run=run,
            plan=plan,
            artifact=artifact,
        )

    required_question_ids = [question.id for question in graph.questions if question.required]
    required_criterion_ids = [criterion.id for criterion in requirement.payload.success_criteria]
    valid_claims: list[DeepSearchSynthesisClaimV1] = []
    invalid_claim_ids: list[str] = []
    invalid_source_ids: set[str] = set()
    invalid_result_ids: set[str] = set()
    for ordinal, claim in enumerate(synthesis.claims, start=1):
        expected_claim_id = deepsearch_claim_id(
            run_id=run.id,
            plan_id=plan.id,
            plan_version=plan.version,
            revision_count=synthesis.revision_count,
            ordinal=ordinal,
            claim=claim,
        )
        referenced_items = [item_by_id.get(item_id) for item_id in claim.evidence_item_ids]
        known_items = [item for item in referenced_items if item is not None]
        supported_question_ids = {item_id for item in known_items for item_id in item.question_ids}
        supported_criterion_ids = {
            criterion_id for item in known_items for criterion_id in item.success_criterion_ids
        }
        supported_result_ids = {item.node_result_id for item in known_items}
        supported_source_ids = {item.source_id for item in known_items if item.source_id is not None}
        unknown_sources = set(claim.source_ids) - supported_source_ids
        unknown_results = set(claim.node_result_ids) - set(result_by_id)
        invalid = (
            claim.id != expected_claim_id
            or not claim.evidence_item_ids
            or not claim.question_ids
            or len(known_items) != len(claim.evidence_item_ids)
            or not set(claim.question_ids).issubset(supported_question_ids)
            or not set(claim.success_criterion_ids).issubset(supported_criterion_ids)
            or set(claim.node_result_ids) != supported_result_ids
            or set(claim.source_ids) != supported_source_ids
            or bool(unknown_results)
        )
        if invalid:
            invalid_claim_ids.append(claim.id)
            invalid_source_ids.update(unknown_sources)
            invalid_result_ids.update(unknown_results)
        else:
            valid_claims.append(claim)

    covered_question_ids = {
        question_id for claim in valid_claims for question_id in claim.question_ids
    }.intersection(required_question_ids)
    covered_criterion_ids = {
        criterion_id
        for claim in valid_claims
        for criterion_id in claim.success_criterion_ids
    }.intersection(required_criterion_ids)
    validated_source_ids = sorted(
        {source_id for claim in valid_claims for source_id in claim.source_ids}
    )
    validated_result_ids = sorted(
        {result_id for claim in valid_claims for result_id in claim.node_result_ids}
    )
    referenced_envelopes = {
        item_id: envelope_by_item_id[item_id]
        for claim in valid_claims
        for item_id in claim.evidence_item_ids
    }
    external_evidence_is_real = (
        not plan.intent.external_evidence_required
        or any(
            envelope.origin_type == "tool" and envelope.execution_mode == "real"
            for envelope in referenced_envelopes.values()
        )
    )
    required_node_ids = {node.id for node in plan.nodes if node.required}
    result_node_ids = {result.node_id for result in results}
    gap_codes: list[str] = []
    if required_node_ids - result_node_ids:
        gap_codes.append("required_node_result_missing")
    if invalid_claim_ids:
        gap_codes.append("claim_reference_invalid")
    if set(required_question_ids) - covered_question_ids:
        gap_codes.append("question_uncovered")
    if set(required_criterion_ids) - covered_criterion_ids:
        gap_codes.append("success_criterion_uncovered")
    if not external_evidence_is_real:
        gap_codes.append("external_evidence_not_real")

    synthesis_hash = canonical_json_sha256(synthesis.model_dump(mode="python"))
    return DeepSearchEvidenceCoverageV1(
        revision_count=synthesis.revision_count,
        synthesis_content_hash=synthesis_hash,
        required_question_ids=required_question_ids,
        covered_question_ids=[
            question_id for question_id in required_question_ids if question_id in covered_question_ids
        ],
        uncovered_question_ids=[
            question_id for question_id in required_question_ids if question_id not in covered_question_ids
        ],
        required_success_criterion_ids=required_criterion_ids,
        covered_success_criterion_ids=[
            criterion_id
            for criterion_id in required_criterion_ids
            if criterion_id in covered_criterion_ids
        ],
        uncovered_success_criterion_ids=[
            criterion_id
            for criterion_id in required_criterion_ids
            if criterion_id not in covered_criterion_ids
        ],
        validated_claim_ids=[claim.id for claim in valid_claims],
        invalid_claim_ids=invalid_claim_ids,
        validated_source_ids=validated_source_ids,
        invalid_source_ids=sorted(invalid_source_ids),
        validated_node_result_ids=validated_result_ids,
        invalid_node_result_ids=sorted(invalid_result_ids),
        external_evidence_is_real=external_evidence_is_real,
        passed=not gap_codes,
        gap_codes=gap_codes,
    )


def _require_manifest_artifact(
    *,
    run: AgentRun,
    plan: SkillPlan,
    manifest: DeepSearchEvidenceManifestV1,
    artifact: Artifact,
) -> None:
    content = canonical_json_bytes(manifest.model_dump(mode="python")).decode("utf-8")
    encoded = content.encode("utf-8")
    if (
        artifact.verification_state is not ArtifactVerificationState.SEALED
        or artifact.artifact_type != "deepsearch_evidence_manifest"
        or artifact.schema_version != "deepsearch-evidence-manifest-v1"
        or artifact.run_id != run.id
        or artifact.workspace_id != run.workspace_id
        or artifact.project_id != run.project_id
        or artifact.user_id != run.user_id
        or artifact.requirement_version_id != plan.requirement_version_id
        or artifact.plan_version_id != f"{plan.id}:v{plan.version}"
        or artifact.content != content
        or artifact.content_hash != hashlib.sha256(encoded).hexdigest()
        or artifact.size_bytes != len(encoded)
    ):
        raise DeepSearchReportingError()
    try:
        parsed = DeepSearchArtifactSchemaRegistry.parse(
            artifact.artifact_type,
            artifact.schema_version,
            artifact.content,
        )
    except (ArtifactAccessError, TypeError, ValueError) as error:
        raise DeepSearchReportingError() from error
    if parsed != manifest:
        raise DeepSearchReportingError()


def read_evidence_manifest_artifact(
    *,
    run: AgentRun,
    plan: SkillPlan,
    artifact: Artifact,
) -> DeepSearchEvidenceManifestV1:
    """Read and revalidate a sealed manifest through the strict v1 schema."""

    try:
        parsed = DeepSearchArtifactSchemaRegistry.parse(
            artifact.artifact_type,
            artifact.schema_version or "",
            artifact.content,
        )
    except (ArtifactAccessError, TypeError, ValueError) as error:
        raise DeepSearchReportingError() from error
    if not isinstance(parsed, DeepSearchEvidenceManifestV1):
        raise DeepSearchReportingError()
    _require_manifest_artifact(run=run, plan=plan, manifest=parsed, artifact=artifact)
    return parsed


def select_safe_claims(
    *,
    synthesis: DeepSearchSynthesisV1,
    coverage: DeepSearchEvidenceCoverageV1,
    review_outcome: DeepSearchReviewOutcomeV1,
) -> tuple[DeepSearchSynthesisClaimV1, ...]:
    """Return only claims that passed deterministic and semantic checks."""

    synthesis_hash = canonical_json_sha256(synthesis.model_dump(mode="python"))
    claim_ids = [claim.id for claim in synthesis.claims]
    checkpoint_ids = set(coverage.validated_claim_ids) | set(coverage.invalid_claim_ids)
    if (
        coverage.revision_count != synthesis.revision_count
        or coverage.synthesis_content_hash != synthesis_hash
        or review_outcome.revision_count != synthesis.revision_count
        or review_outcome.synthesis_content_hash != synthesis_hash
        or checkpoint_ids != set(claim_ids)
    ):
        raise DeepSearchReportingError()

    excluded_claim_ids: set[str] = set()
    review = review_outcome.review
    if review is not None:
        referenced_claim_ids = set(review.unsupported_claim_ids) | set(
            review.contradictory_claim_ids
        )
        if not referenced_claim_ids.issubset(claim_ids):
            raise DeepSearchReportingError()
        excluded_claim_ids.update(referenced_claim_ids)
        # A blocking semantic verdict without actionable claim IDs makes every
        # factual claim unsafe to publish.
        if review.verdict == "block" and not referenced_claim_ids:
            return ()

    validated = set(coverage.validated_claim_ids) - excluded_claim_ids
    return tuple(claim for claim in synthesis.claims if claim.id in validated)


def materialize_deepsearch_review(
    *,
    run: AgentRun,
    plan: SkillPlan,
    requirement: RequirementVersionV1,
    graph: ProblemGraphV1,
    synthesis: DeepSearchSynthesisV1,
    draft: DeepSearchReportReviewDraftV1 | Mapping[str, object],
    reviewer_type: str,
    reviewed_at: datetime,
) -> DeepSearchReviewOutcomeV1:
    """Validate reviewer references and attach immutable lineage server-side."""

    _require_current_lineage(run=run, plan=plan, requirement=requirement, graph=graph)
    if (
        not reviewer_type.strip()
        or reviewed_at.tzinfo is None
        or reviewed_at.utcoffset() is None
    ):
        raise DeepSearchReportingError("deepsearch_review_invalid")
    try:
        checked = DeepSearchReportReviewDraftV1.model_validate(draft)
    except (TypeError, ValueError) as error:
        raise DeepSearchReportingError("deepsearch_review_invalid") from error
    known_claim_ids = {claim.id for claim in synthesis.claims}
    reviewed_claim_ids = set(checked.unsupported_claim_ids) | set(
        checked.contradictory_claim_ids
    )
    known_section_ids = {question.id for question in graph.questions}
    if (
        not reviewed_claim_ids.issubset(known_claim_ids)
        or set(checked.unsupported_claim_ids).intersection(checked.contradictory_claim_ids)
        or not set(checked.missing_section_ids).issubset(known_section_ids)
        or any(code not in _LIMITATION_DESCRIPTIONS for code in checked.limitation_codes)
    ):
        raise DeepSearchReportingError("deepsearch_review_invalid")
    synthesis_hash = canonical_json_sha256(synthesis.model_dump(mode="python"))
    review = DeepSearchReportReviewV1(
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph_hash=graph.content_hash,
        plan_id=plan.id,
        plan_version=plan.version,
        plan_content_hash=plan.plan_content_hash or "",
        synthesis_content_hash=synthesis_hash,
        verdict=checked.verdict,
        unsupported_claim_ids=checked.unsupported_claim_ids,
        contradictory_claim_ids=checked.contradictory_claim_ids,
        missing_section_ids=checked.missing_section_ids,
        limitation_codes=checked.limitation_codes,
        revision_count=synthesis.revision_count,
        reviewer_type=reviewer_type.strip(),
        reviewed_at=reviewed_at,
    )
    return DeepSearchReviewOutcomeV1(
        revision_count=synthesis.revision_count,
        synthesis_content_hash=synthesis_hash,
        outcome=review.verdict,
        review=review,
    )


def _render_report_text(
    *,
    title: str,
    report_status: Literal["complete", "partial"],
    claims: Sequence[DeepSearchReportClaimV1],
    summary_claim_ids: Sequence[str],
    sections: Sequence[DeepSearchReportSectionV1],
    sources: Sequence[DeepSearchReportSourceV1],
    limitations: Sequence[DeepSearchReportLimitationV1],
) -> str:
    claim_by_id = {claim.id: claim for claim in claims}

    def render_claim(claim: DeepSearchReportClaimV1) -> str:
        evidence = ", ".join(claim.evidence_item_ids)
        source_suffix = f"；来源：{', '.join(claim.source_ids)}" if claim.source_ids else ""
        return f"- {claim.text}（证据：{evidence}{source_suffix}）"

    lines = [
        f"# {title}",
        "",
        f"状态：{'完整报告' if report_status == 'complete' else '部分报告'}",
        "",
        "## 执行摘要",
        "",
    ]
    lines.extend(render_claim(claim_by_id[claim_id]) for claim_id in summary_claim_ids)
    for section in sections:
        lines.extend(["", f"## {section.server_heading}", ""])
        if section.claim_ids:
            lines.extend(render_claim(claim_by_id[claim_id]) for claim_id in section.claim_ids)
        else:
            lines.append("暂无已验证结论。")
    lines.extend(["", "## 来源", ""])
    if sources:
        lines.extend(
            f"- {source.title}：{source.normalized_reference}（{source.source_id}）"
            for source in sources
        )
    else:
        lines.append("无外部来源。")
    lines.extend(["", "## 限制", ""])
    if limitations:
        lines.extend(
            f"- {item.description}"
            + (f"（关联：{', '.join(item.related_ids)}）" if item.related_ids else "")
            for item in limitations
        )
    else:
        lines.append("未发现阻塞性交付限制。")
    return "\n".join(lines).strip()


def build_deepsearch_report(
    *,
    run: AgentRun,
    plan: SkillPlan,
    requirement: RequirementVersionV1,
    graph: ProblemGraphV1,
    results: Sequence[SkillNodeResult],
    manifest: DeepSearchEvidenceManifestV1,
    manifest_artifact: Artifact,
    evidence_artifacts: Mapping[str, Artifact],
    sources: Mapping[str, Source],
    synthesis: DeepSearchSynthesisV1,
    coverage: DeepSearchEvidenceCoverageV1,
    review_outcome: DeepSearchReviewOutcomeV1,
    report_status: Literal["complete", "partial"],
    extra_limitation_codes: Sequence[str] = (),
) -> DeepSearchReportV1:
    """Build the only report shape that may be sealed and shown to a user."""

    _require_current_lineage(run=run, plan=plan, requirement=requirement, graph=graph)
    _require_manifest_artifact(
        run=run,
        plan=plan,
        manifest=manifest,
        artifact=manifest_artifact,
    )
    recomputed_coverage = evaluate_evidence_coverage(
        run=run,
        plan=plan,
        requirement=requirement,
        graph=graph,
        results=results,
        manifest=manifest,
        evidence_artifacts=evidence_artifacts,
        synthesis=synthesis,
    )
    if recomputed_coverage != coverage:
        raise DeepSearchReportingError()
    safe_claims = select_safe_claims(
        synthesis=synthesis,
        coverage=coverage,
        review_outcome=review_outcome,
    )

    question_ids = {question.id for question in graph.questions}
    safe_claims = tuple(
        claim for claim in safe_claims if set(claim.question_ids).issubset(question_ids)
    )
    covered_question_ids = {
        question_id for claim in safe_claims for question_id in claim.question_ids
    }
    covered_criterion_ids = {
        criterion_id for claim in safe_claims for criterion_id in claim.success_criterion_ids
    }
    required_question_ids = [question.id for question in graph.questions if question.required]
    required_criterion_ids = [criterion.id for criterion in requirement.payload.success_criteria]
    uncovered_question_ids = [
        question_id for question_id in required_question_ids if question_id not in covered_question_ids
    ]
    uncovered_criterion_ids = [
        criterion_id
        for criterion_id in required_criterion_ids
        if criterion_id not in covered_criterion_ids
    ]

    result_by_id = {result.id: result for result in results}
    required_node_ids = {node.id for node in plan.nodes if node.required}
    verified_required_result_exists = any(
        result_id in coverage.validated_node_result_ids
        and result_by_id.get(result_id) is not None
        and result_by_id[result_id].node_id in required_node_ids
        for result_id in result_by_id
    )
    if report_status == "partial" and (
        not safe_claims
        or not verified_required_result_exists
        or not set(required_question_ids).intersection(covered_question_ids)
    ):
        raise DeepSearchReportingError("deepsearch_delivery_unavailable")

    review = review_outcome.review
    excluded_claim_ids = (
        set(review.unsupported_claim_ids) | set(review.contradictory_claim_ids)
        if review is not None
        else set()
    )
    all_nodes_completed = all(
        node.status is SkillPlanNodeStatus.COMPLETED for node in plan.nodes
    )
    if report_status == "complete" and (
        not all_nodes_completed
        or not coverage.passed
        or uncovered_question_ids
        or uncovered_criterion_ids
        or review_outcome.outcome != "pass"
        or synthesis.synthesis_mode != "model"
        or excluded_claim_ids
    ):
        raise DeepSearchReportingError("deepsearch_delivery_unavailable")

    report_claims = [
        DeepSearchReportClaimV1(**claim.model_dump(mode="python")) for claim in safe_claims
    ]
    safe_claim_by_id = {claim.id: claim for claim in safe_claims}
    sections = [
        DeepSearchReportSectionV1(
            section_id=question.id,
            server_heading=question.question,
            claim_ids=[
                claim.id for claim in safe_claims if question.id in claim.question_ids
            ],
        )
        for question in graph.questions
    ]

    summary_claim_ids: list[str] = []
    for reference_id, attribute in [
        *((question_id, "question_ids") for question_id in required_question_ids),
        *((criterion_id, "success_criterion_ids") for criterion_id in required_criterion_ids),
    ]:
        selected = next(
            (
                claim.id
                for claim in safe_claims
                if claim.id not in summary_claim_ids
                and reference_id in getattr(claim, attribute)
            ),
            None,
        )
        if selected is not None:
            summary_claim_ids.append(selected)

    manifest_by_item_id = {item.evidence_item_id: item for item in manifest.items}
    referenced_source_ids = sorted(
        {source_id for claim in safe_claims for source_id in claim.source_ids}
    )
    source_projection: list[DeepSearchReportSourceV1] = []
    for source_id in referenced_source_ids:
        source = sources.get(source_id)
        matching_envelopes: list[TrustedEvidenceEnvelopeV1] = []
        for claim in safe_claims:
            if source_id not in claim.source_ids:
                continue
            for evidence_item_id in claim.evidence_item_ids:
                manifest_item = manifest_by_item_id.get(evidence_item_id)
                if manifest_item is None or manifest_item.source_id != source_id:
                    continue
                artifact = evidence_artifacts.get(manifest_item.evidence_artifact_id)
                if artifact is None:
                    raise DeepSearchReportingError()
                matching_envelopes.append(
                    _verified_evidence_envelope(run=run, plan=plan, artifact=artifact)
                )
        if (
            source is None
            or not source.title.strip()
            or source.run_id != run.id
            or source.workspace_id != run.workspace_id
            or source.project_id != run.project_id
            or source.user_id != run.user_id
            or not matching_envelopes
            or any(
                envelope.source_id != source_id
                or envelope.normalized_reference != source.reference
                for envelope in matching_envelopes
            )
            or len({envelope.content_hash for envelope in matching_envelopes}) != 1
        ):
            raise DeepSearchReportingError()
        source_projection.append(
            DeepSearchReportSourceV1(
                source_id=source_id,
                title=source.title.strip(),
                normalized_reference=source.reference,
                content_hash=matching_envelopes[0].content_hash,
            )
        )

    limitation_ids: dict[str, set[str]] = {}

    def add_limitation(code: str, related_ids: Sequence[str] = ()) -> None:
        if code not in _LIMITATION_DESCRIPTIONS:
            raise DeepSearchReportingError()
        limitation_ids.setdefault(code, set()).update(related_ids)

    if coverage.invalid_claim_ids:
        add_limitation("claim_reference_invalid", coverage.invalid_claim_ids)
    if uncovered_question_ids:
        add_limitation("question_uncovered", uncovered_question_ids)
    if uncovered_criterion_ids:
        add_limitation("success_criterion_uncovered", uncovered_criterion_ids)
    if not coverage.external_evidence_is_real:
        add_limitation("external_evidence_not_real")
    missing_required_node_ids = [
        node.id
        for node in plan.nodes
        if node.required and node.status is not SkillPlanNodeStatus.COMPLETED
    ]
    if missing_required_node_ids:
        add_limitation("required_node_result_missing", missing_required_node_ids)
    optional_failure_ids = [
        node.id
        for node in plan.nodes
        if not node.required and node.status is not SkillPlanNodeStatus.COMPLETED
    ]
    if optional_failure_ids:
        add_limitation("deepsearch_optional_node_failed", optional_failure_ids)
    if excluded_claim_ids or review_outcome.outcome in {"revise", "block", "error"}:
        add_limitation("deepsearch_review_not_passed", sorted(excluded_claim_ids))
    if review is not None:
        if any(code not in _LIMITATION_DESCRIPTIONS for code in review.limitation_codes):
            raise DeepSearchReportingError()
        for code in review.limitation_codes:
            add_limitation(code)
    if review_outcome.reason_code is not None:
        add_limitation(review_outcome.reason_code)
    if synthesis.synthesis_mode == "deterministic_evidence_digest":
        add_limitation("deepsearch_synthesis_fallback")
    for code in extra_limitation_codes:
        add_limitation(code)
    if report_status == "partial" and not limitation_ids:
        add_limitation("deepsearch_required_coverage_incomplete")
    if report_status == "complete" and limitation_ids:
        raise DeepSearchReportingError("deepsearch_delivery_unavailable")

    limitations = [
        DeepSearchReportLimitationV1(
            code=code,
            related_ids=sorted(related_ids),
            description=_LIMITATION_DESCRIPTIONS[code],
        )
        for code, related_ids in limitation_ids.items()
    ]
    suffix = " — DeepSearch 报告"
    goal = requirement.payload.goal.strip()
    title = goal[: 500 - len(suffix)] + suffix
    rendered_text = _render_report_text(
        title=title,
        report_status=report_status,
        claims=report_claims,
        summary_claim_ids=summary_claim_ids,
        sections=sections,
        sources=source_projection,
        limitations=limitations,
    )
    if any(claim_id not in safe_claim_by_id for claim_id in summary_claim_ids):
        raise DeepSearchReportingError()
    return DeepSearchReportV1(
        schema_version="deepsearch-report-v1",
        run_id=run.id,
        requirement_version_id=requirement.id,
        plan_id=plan.id,
        plan_version=plan.version,
        requirement_content_hash=requirement.content_hash,
        problem_graph_hash=graph.content_hash,
        plan_content_hash=plan.plan_content_hash or "",
        evidence_manifest_hash=manifest_artifact.content_hash or "",
        synthesis_content_hash=coverage.synthesis_content_hash,
        review_outcome=review_outcome.outcome,
        review_reason_code=review_outcome.reason_code,
        report_status=report_status,
        title=title,
        claims=report_claims,
        executive_summary_claim_ids=summary_claim_ids,
        sections=sections,
        sources=source_projection,
        limitations=limitations,
        rendered_text=rendered_text,
    )


def build_deepsearch_report_artifacts(
    *,
    run: AgentRun,
    plan: SkillPlan,
    report: DeepSearchReportV1,
    created_at: datetime,
) -> tuple[Artifact, Artifact]:
    """Build the STAGING/SEALED pair for one logical report identity."""

    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise DeepSearchReportingError()
    if (
        report.run_id != run.id
        or report.requirement_version_id != plan.requirement_version_id
        or report.plan_id != plan.id
        or report.plan_version != plan.version
        or report.plan_content_hash != plan.plan_content_hash
    ):
        raise DeepSearchReportingError()
    content = canonical_json_bytes(report.model_dump(mode="python")).decode("utf-8")
    encoded = content.encode("utf-8")
    if len(encoded) > DEEPSEARCH_REPORT_MAX_BYTES:
        raise DeepSearchReportingError("deepsearch_delivery_unavailable")
    artifact_id = "artifact_deepsearch_report_" + canonical_json_sha256(
        {
            "run_id": run.id,
            "plan_id": plan.id,
            "plan_version": plan.version,
            "stage": "terminal_committed",
            "revision_count": plan.report_revision_count,
            "kind": "deepsearch_report",
        }
    )
    common = {
        "id": artifact_id,
        "run_id": run.id,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "user_id": run.user_id,
        "artifact_type": "deepsearch_report",
        "content_type": "application/json",
        "schema_version": "deepsearch-report-v1",
        "requirement_version_id": report.requirement_version_id,
        "plan_version_id": f"{plan.id}:v{plan.version}",
        "created_at": created_at,
        "updated_at": created_at,
    }
    staging = Artifact(
        **common,
        content="",
        verification_state=ArtifactVerificationState.STAGING,
    )
    sealed = Artifact(
        **common,
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        content_hash=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
    )
    return staging, sealed


def decide_deepsearch_terminal(
    *,
    plan: SkillPlan,
    synthesis: DeepSearchSynthesisV1,
    coverage: DeepSearchEvidenceCoverageV1,
    review_outcome: DeepSearchReviewOutcomeV1 | None,
    safe_partial_report: bool,
    report_available: bool,
    budget_exhausted: bool = False,
    evidence_integrity_failed: bool = False,
    report_persistence_failed: bool = False,
    synthesis_failed: bool = False,
) -> DeepSearchTerminalDecision:
    """Apply the finalization portion of the terminal truth table in fixed order."""

    synthesis_hash = canonical_json_sha256(synthesis.model_dump(mode="python"))
    if (
        coverage.revision_count != synthesis.revision_count
        or coverage.synthesis_content_hash != synthesis_hash
        or (
            review_outcome is not None
            and (
                review_outcome.revision_count != synthesis.revision_count
                or review_outcome.synthesis_content_hash != synthesis_hash
            )
        )
    ):
        return DeepSearchTerminalDecision(
            status=AgentRunStatus.FAILED,
            error_code="deepsearch_evidence_integrity_failed",
        )
    if evidence_integrity_failed:
        return DeepSearchTerminalDecision(
            status=AgentRunStatus.FAILED,
            error_code="deepsearch_evidence_integrity_failed",
        )
    if report_persistence_failed:
        return DeepSearchTerminalDecision(
            status=AgentRunStatus.FAILED,
            error_code="deepsearch_report_persistence_failed",
        )

    can_publish_partial = safe_partial_report and report_available
    if budget_exhausted:
        return DeepSearchTerminalDecision(
            status=(AgentRunStatus.PARTIAL if can_publish_partial else AgentRunStatus.FAILED),
            error_code="deepsearch_budget_exhausted",
        )

    if plan.capability_gaps:
        return DeepSearchTerminalDecision(
            status=(AgentRunStatus.PARTIAL if can_publish_partial else AgentRunStatus.FAILED),
            error_code=(
                "deepsearch_required_coverage_incomplete"
                if can_publish_partial
                else "deepsearch_delivery_unavailable"
            ),
        )

    required_node_incomplete = any(
        node.required and node.status is not SkillPlanNodeStatus.COMPLETED
        for node in plan.nodes
    )
    if required_node_incomplete or not coverage.passed:
        return DeepSearchTerminalDecision(
            status=(AgentRunStatus.PARTIAL if can_publish_partial else AgentRunStatus.FAILED),
            error_code=(
                "deepsearch_required_coverage_incomplete"
                if can_publish_partial
                else "deepsearch_delivery_unavailable"
            ),
        )
    if review_outcome is None:
        return DeepSearchTerminalDecision(
            status=AgentRunStatus.FAILED,
            error_code="deepsearch_delivery_unavailable",
        )
    if (
        review_outcome.outcome == "revise"
        and synthesis.revision_count == 0
        and synthesis.synthesis_mode == "model"
    ):
        return DeepSearchTerminalDecision(status=AgentRunStatus.RUNNING, error_code=None)
    if review_outcome.outcome == "not_run" and review_outcome.reason_code == "deterministic_digest":
        return DeepSearchTerminalDecision(
            status=(AgentRunStatus.PARTIAL if can_publish_partial else AgentRunStatus.FAILED),
            error_code=(
                "deepsearch_synthesis_fallback"
                if can_publish_partial
                else "deepsearch_delivery_unavailable"
            ),
        )
    if review_outcome.outcome == "not_run" and review_outcome.reason_code == "budget_unavailable":
        return DeepSearchTerminalDecision(
            status=(AgentRunStatus.PARTIAL if can_publish_partial else AgentRunStatus.FAILED),
            error_code="deepsearch_budget_exhausted",
        )
    if review_outcome.outcome != "pass":
        return DeepSearchTerminalDecision(
            status=(AgentRunStatus.PARTIAL if can_publish_partial else AgentRunStatus.FAILED),
            error_code=(
                "deepsearch_review_not_passed"
                if can_publish_partial
                else "deepsearch_delivery_unavailable"
            ),
        )

    optional_node_failed = any(
        not node.required and node.status is not SkillPlanNodeStatus.COMPLETED
        for node in plan.nodes
    )
    if optional_node_failed:
        return DeepSearchTerminalDecision(
            status=(AgentRunStatus.PARTIAL if can_publish_partial else AgentRunStatus.FAILED),
            error_code=(
                "deepsearch_optional_node_failed"
                if can_publish_partial
                else "deepsearch_delivery_unavailable"
            ),
        )
    if synthesis.synthesis_mode == "deterministic_evidence_digest" or synthesis_failed:
        return DeepSearchTerminalDecision(
            status=(AgentRunStatus.PARTIAL if can_publish_partial else AgentRunStatus.FAILED),
            error_code=(
                "deepsearch_synthesis_fallback"
                if can_publish_partial
                else "deepsearch_delivery_unavailable"
            ),
        )
    if not report_available:
        return DeepSearchTerminalDecision(
            status=AgentRunStatus.FAILED,
            error_code="deepsearch_delivery_unavailable",
        )
    return DeepSearchTerminalDecision(status=AgentRunStatus.COMPLETED, error_code=None)
