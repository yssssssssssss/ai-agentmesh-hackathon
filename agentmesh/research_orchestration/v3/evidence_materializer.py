from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from urllib.parse import urlsplit

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.common import Identifier
from agentmesh.research_orchestration.v3.evidence import (
    EvidenceItemV3,
    EvidenceManifestV3,
    EvidenceProofV3,
    EvidenceSourceV3,
    VerifiedArtifactContentV3,
    VerifiedArtifactPointerV3,
    VerifiedQuotePointerV3,
    verify_evidence_manifest_artifacts,
)
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanVersionV3
from agentmesh.research_orchestration.v3.ports import (
    ActorExecutionRequestV3,
    ActorExecutionResultV3,
    ArtifactReadPort,
    validate_actor_result_for_request,
)


class EvidenceMaterializationError(ValueError):
    pass


def read_verified_actor_artifacts(
    artifacts: ArtifactReadPort,
    actor_results: tuple[ActorExecutionResultV3, ...],
) -> tuple[VerifiedArtifactContentV3, ...]:
    """Read back and verify every Actor Artifact against its immutable result envelope."""

    step_numbers = tuple(result.step_number for result in actor_results)
    artifact_ids = tuple(result.result_artifact.artifact_id for result in actor_results)
    if len(set(step_numbers)) != len(step_numbers):
        raise EvidenceMaterializationError("Actor results contain duplicate Step completions")
    if len(set(artifact_ids)) != len(artifact_ids):
        raise EvidenceMaterializationError("Actor results must reference distinct Artifacts")
    verified_artifacts: list[VerifiedArtifactContentV3] = []
    for result in sorted(actor_results, key=lambda item: item.step_number):
        verified = artifacts.read_verified_json(
            run_id=result.run_id,
            plan_version_id=result.plan_version_id,
            attempt_id=result.attempt_id,
            step_number=result.step_number,
            artifact=result.result_artifact,
        )
        if verified is None:
            raise EvidenceMaterializationError(
                f"Actor result Artifact for Step {result.step_number} failed verified readback"
            )
        validate_verified_actor_artifact(result, verified)
        verified_artifacts.append(verified)
    return tuple(verified_artifacts)


def validate_verified_actor_artifact(
    result: ActorExecutionResultV3,
    verified: VerifiedArtifactContentV3,
) -> None:
    if (
        verified.run_id,
        verified.plan_version_id,
        verified.attempt_id,
        verified.step_number,
        verified.actor_type,
        verified.actor_id,
        verified.step_contract_hash,
        verified.receipt_id,
        verified.implementation_id,
        verified.execution_mode,
        verified.artifact,
    ) != (
        result.run_id,
        result.plan_version_id,
        result.attempt_id,
        result.step_number,
        result.actor_type,
        result.actor_id,
        result.step_contract_hash,
        result.receipt_id,
        result.implementation_id,
        result.execution_mode,
        result.result_artifact,
    ):
        raise EvidenceMaterializationError(
            "verified Actor Artifact identity does not match its Actor result"
        )


class EvidenceManifestMaterializer:
    """Materialize public text Evidence only after exact Actor Artifact readback."""

    def __init__(self, artifacts: ArtifactReadPort) -> None:
        self._artifacts = artifacts

    def materialize(
        self,
        *,
        plan: ExecutionPlanVersionV3,
        attempt_id: Identifier,
        actor_results: tuple[ActorExecutionResultV3, ...],
        collected_at: datetime,
    ) -> tuple[EvidenceManifestV3, tuple[VerifiedArtifactContentV3, ...]]:
        steps = {step.step_number: step for step in plan.payload.steps}
        seen_steps: set[int] = set()
        evidence: list[EvidenceItemV3] = []
        verified_artifacts: list[VerifiedArtifactContentV3] = []
        seen_source_ids: set[str] = set()

        for result in sorted(actor_results, key=lambda item: item.step_number):
            if result.step_number in seen_steps:
                raise EvidenceMaterializationError("Actor results contain a duplicate Step completion")
            seen_steps.add(result.step_number)
            step = steps.get(result.step_number)
            if step is None:
                raise EvidenceMaterializationError("Actor result references a Step outside the selected Plan")
            request = ActorExecutionRequestV3(
                run_id=plan.run_id,
                plan_version_id=plan.id,
                attempt_id=attempt_id,
                control_snapshot_artifact=plan.payload.control_snapshot_artifact,
                step=step,
                resolved_input=step.input,
            )
            validate_actor_result_for_request(request, result)
            if result.actor_type != "tool":
                continue
            if result.execution_mode != "real":
                raise EvidenceMaterializationError("public Evidence requires a real Tool execution")
            verified = self._artifacts.read_verified_json(
                run_id=result.run_id,
                plan_version_id=result.plan_version_id,
                attempt_id=result.attempt_id,
                step_number=result.step_number,
                artifact=result.result_artifact,
            )
            if verified is None:
                raise EvidenceMaterializationError("Tool result Artifact failed verified readback")
            self._validate_verified_result(result, verified)
            artifact_evidence = self._materialize_artifact_sources(
                result=result,
                verified=verified,
                collected_at=collected_at,
                seen_source_ids=seen_source_ids,
            )
            if artifact_evidence:
                verified_artifacts.append(verified)
                evidence.extend(artifact_evidence)

        if not evidence:
            raise EvidenceMaterializationError("no verified public Tool evidence was available")
        manifest = EvidenceManifestV3(
            schema_version="evidence-manifest-v3",
            presentation_mode="text",
            payload_schema_version="competitive-analysis-text-v1",
            run_id=plan.run_id,
            plan_version_id=plan.id,
            attempt_id=attempt_id,
            collected_at=collected_at,
            evidence=tuple(sorted(evidence, key=lambda item: item.id)),
        )
        verified_tuple = tuple(
            sorted(verified_artifacts, key=lambda item: (item.step_number, item.artifact.artifact_id))
        )
        verify_evidence_manifest_artifacts(manifest, verified_tuple)
        return manifest, verified_tuple

    @staticmethod
    def _validate_verified_result(
        result: ActorExecutionResultV3,
        verified: VerifiedArtifactContentV3,
    ) -> None:
        validate_verified_actor_artifact(result, verified)

    @staticmethod
    def _materialize_artifact_sources(
        *,
        result: ActorExecutionResultV3,
        verified: VerifiedArtifactContentV3,
        collected_at: datetime,
        seen_source_ids: set[str],
    ) -> list[EvidenceItemV3]:
        if not isinstance(verified.content, Mapping):
            raise EvidenceMaterializationError("Tool result Artifact must contain a JSON object")
        output = verified.content.get("output")
        output_hash = verified.content.get("redacted_output_hash")
        if not isinstance(output, Mapping) or not isinstance(output_hash, str):
            raise EvidenceMaterializationError("Tool result Artifact lacks its redacted output proof")
        if canonical_json_v3_sha256(output) != output_hash:
            raise EvidenceMaterializationError("Tool result redacted output proof does not verify")
        sources = output.get("results")
        if not isinstance(sources, tuple):
            raise EvidenceMaterializationError("Tool result output must contain a results array")

        items: list[EvidenceItemV3] = []
        for index, raw_source in enumerate(sources):
            if not isinstance(raw_source, Mapping):
                raise EvidenceMaterializationError("Tool result source entries must be objects")
            source_id = raw_source.get("source_id")
            title = raw_source.get("title")
            url = raw_source.get("url")
            quote_field = "quote" if isinstance(raw_source.get("quote"), str) else "snippet"
            quote = raw_source.get(quote_field)
            if not all(isinstance(value, str) and value.strip() for value in (source_id, title, url, quote)):
                raise EvidenceMaterializationError(
                    "Tool result sources require source_id, title, HTTPS URL, and quote text"
                )
            if source_id in seen_source_ids:
                raise EvidenceMaterializationError("Tool result source IDs must be unique across the execution")
            seen_source_ids.add(source_id)
            domain = raw_source.get("registrable_domain")
            if not isinstance(domain, str):
                domain = (urlsplit(url).hostname or "").lower().rstrip(".")
            independence_group = raw_source.get("independence_group", domain)
            retrieved_at = raw_source.get("retrieved_at", collected_at)
            conflict_status = raw_source.get("conflict_status", "none")
            risk_flags = raw_source.get("risk_flags", ())
            truncated = raw_source.get("truncated", False)
            redaction = raw_source.get("redaction", "masked")
            pointer = f"/output/results/{index}"
            source = EvidenceSourceV3.model_validate(
                {
                    "source_kind": "public_web",
                    "source_id": source_id,
                    "title": title,
                    "url": url,
                    "quote": quote,
                    "retrieved_at": retrieved_at,
                    "registrable_domain": domain,
                    "independence_group": independence_group,
                    "conflict_status": conflict_status,
                    "risk_flags": risk_flags,
                    "truncated": truncated,
                }
            )
            evidence_id = "evidence_" + canonical_json_v3_sha256(
                {
                    "artifact_id": verified.artifact.artifact_id,
                    "pointer": pointer,
                    "source_id": source_id,
                }
            )[:24]
            items.append(
                EvidenceItemV3(
                    id=evidence_id,
                    kind="tool_output",
                    evidence_class="public_source",
                    pointer=VerifiedArtifactPointerV3(
                        artifact=verified.artifact,
                        json_pointer=pointer,
                    ),
                    quote_pointer=VerifiedQuotePointerV3(
                        artifact=verified.artifact,
                        json_pointer=f"{pointer}/{quote_field}",
                    ),
                    source=source,
                    proof=EvidenceProofV3(
                        run_id=result.run_id,
                        plan_version_id=result.plan_version_id,
                        attempt_id=result.attempt_id,
                        step_number=result.step_number,
                        actor_type="tool",
                        actor_id=result.actor_id,
                        step_contract_hash=result.step_contract_hash,
                        receipt_id=result.receipt_id,
                        implementation_id=result.implementation_id,
                        execution_mode="real",
                        redacted_output_hash=output_hash,
                    ),
                    sensitivity="public",
                    redaction=redaction,
                )
            )
        return items
