from __future__ import annotations

from copy import deepcopy
from inspect import Signature, signature
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.common import EvidenceManifestArtifactRefV3, SealedArtifactRefV3
from agentmesh.research_orchestration.v3.deliverable import ResearchDeliverableV3
from agentmesh.research_orchestration.v3.evidence import (
    EvidenceManifestV3,
    VerifiedArtifactContentV3,
    verify_evidence_manifest_artifacts,
)
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanV3, ExecutionPlanVersionV3
from agentmesh.research_orchestration.v3.ports import (
    ActorExecutionRequestV3,
    ActorExecutionResultV3,
    ArtifactReadPort,
    DeliveryPort,
    ReportCompositionPort,
    ResearchV3RepositoryPort,
    ReviewPort,
    validate_actor_result_for_request,
    validate_delivery_inputs,
    validate_review_inputs,
)
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3
from agentmesh.research_orchestration.v3.review import PassedReportReviewV3
from research_v3_contract_samples import (
    artifact_ref,
    deliverable_body,
    evidence_artifact_content,
    evidence_body,
    plan_body,
    problem_graph_body,
    requirement_envelope,
)


def verified_evidence_artifact() -> VerifiedArtifactContentV3:
    content = evidence_artifact_content()
    plan = ExecutionPlanV3.model_validate(plan_body())
    return VerifiedArtifactContentV3(
        run_id="run_1",
        plan_version_id="plan_1",
        attempt_id="attempt_1",
        step_number=1,
        actor_type="tool",
        actor_id="tavily-web-search",
        step_contract_hash=plan.steps[0].contract_hash,
        receipt_id="receipt_tool_1",
        implementation_id="tavily-v1",
        execution_mode="real",
        artifact=artifact_ref(
            "artifact_tool_1",
            "actor_result",
            "tool-result-v1",
            canonical_json_v3_sha256(content),
        ),
        content=content,
    )


def test_evidence_manifest_is_same_execution_text_only_and_resolves_verified_pointer() -> None:
    manifest = EvidenceManifestV3.model_validate(evidence_body())
    verified = verified_evidence_artifact()

    verify_evidence_manifest_artifacts(manifest, (verified,))
    assert manifest.presentation_mode == "text"
    assert {item.evidence_class for item in manifest.evidence} == {"public_source"}
    assert manifest.evidence[0].pointer.artifact == verified.artifact

    wrong_attempt = deepcopy(evidence_body())
    wrong_attempt["evidence"][0]["proof"]["attempt_id"] = "attempt_other"
    with pytest.raises(ValidationError, match="Manifest run, plan, and attempt"):
        EvidenceManifestV3.model_validate(wrong_attempt)

    screenshot = deepcopy(evidence_body())
    screenshot["evidence"][0]["evidence_class"] = "screenshot"
    with pytest.raises(ValidationError):
        EvidenceManifestV3.model_validate(screenshot)


def test_verified_evidence_rejects_pointer_url_proof_and_content_drift() -> None:
    manifest_body = evidence_body()
    manifest_body["evidence"][0]["source"]["url"] = "https://example.test/other"
    manifest = EvidenceManifestV3.model_validate(manifest_body)
    with pytest.raises(ValueError, match="source URL"):
        verify_evidence_manifest_artifacts(manifest, (verified_evidence_artifact(),))

    manifest_body = evidence_body()
    manifest_body["evidence"][0]["source"]["quote"] = "Altered quote."
    manifest = EvidenceManifestV3.model_validate(manifest_body)
    with pytest.raises(ValueError, match="quote does not exactly match"):
        verify_evidence_manifest_artifacts(manifest, (verified_evidence_artifact(),))

    manifest = EvidenceManifestV3.model_validate(evidence_body())
    verified = verified_evidence_artifact()
    for update in (
        {"receipt_id": "receipt_other"},
        {"implementation_id": "other-implementation"},
        {"execution_mode": "deterministic"},
    ):
        forged = verified.model_copy(update=update)
        with pytest.raises(ValueError, match="execution identity and mode"):
            verify_evidence_manifest_artifacts(manifest, (forged,))

    with pytest.raises(ValidationError, match="sealed content hash"):
        VerifiedArtifactContentV3.model_validate(
            {
                **verified.model_dump(mode="python"),
                "content": {"output": {"results": []}, "redacted_output_hash": "f" * 64},
            }
        )


def test_verified_evidence_rejects_oss_url_fallback() -> None:
    verified_body = verified_evidence_artifact().model_dump(mode="json")
    resolved = verified_body["content"]["output"]["results"][0]
    resolved["oss_url"] = resolved.pop("url")
    content = verified_body["content"]
    output_hash = canonical_json_v3_sha256(content["output"])
    content["redacted_output_hash"] = output_hash
    content_hash = canonical_json_v3_sha256(content)
    verified_body["artifact"]["content_hash"] = content_hash
    verified = VerifiedArtifactContentV3.model_validate(verified_body)

    manifest_body = evidence_body()
    manifest_body["evidence"][0]["pointer"]["artifact"]["content_hash"] = content_hash
    manifest_body["evidence"][0]["quote_pointer"]["artifact"]["content_hash"] = content_hash
    manifest_body["evidence"][0]["proof"]["redacted_output_hash"] = output_hash
    manifest = EvidenceManifestV3.model_validate(manifest_body)
    with pytest.raises(ValueError, match="source URL"):
        verify_evidence_manifest_artifacts(manifest, (verified,))


def test_actor_results_retain_request_lineage_when_parallel_completion_is_reordered() -> None:
    plan = ExecutionPlanV3.model_validate(plan_body())
    requests = tuple(
        ActorExecutionRequestV3(
            run_id="run_1",
            plan_version_id="plan_1",
            attempt_id="attempt_1",
            step=step,
            resolved_input=step.input,
        )
        for step in plan.steps
    )
    results = tuple(
        ActorExecutionResultV3(
            run_id=request.run_id,
            plan_version_id=request.plan_version_id,
            attempt_id=request.attempt_id,
            step_number=request.step.step_number,
            actor_type=request.step.actor_type,
            actor_id=request.step.actor_id,
            step_contract_hash=request.step.contract_hash,
            result_artifact=artifact_ref(
                f"artifact_step_{request.step.step_number}",
                "actor_result",
                "actor-result-v1",
            ),
            receipt_id=f"receipt_{request.step.step_number}",
            implementation_id=f"{request.step.actor_id}-v1",
            execution_mode="real" if request.step.actor_type == "tool" else "deterministic",
        )
        for request in reversed(requests)
    )

    assert tuple(result.step_number for result in results) == (2, 1)
    requests_by_step = {request.step.step_number: request for request in requests}
    for result in results:
        validate_actor_result_for_request(requests_by_step[result.step_number], result)

    mismatched = results[0].model_copy(update={"plan_version_id": "plan_other"})
    with pytest.raises(ValueError, match="request lineage"):
        validate_actor_result_for_request(requests_by_step[mismatched.step_number], mismatched)


def test_ports_require_typed_repository_and_explicit_verified_review_inputs() -> None:
    delivery_parameters = signature(DeliveryPort.create_deliverable).parameters
    assert tuple(delivery_parameters) == (
        "self",
        "requirement",
        "plan",
        "attempt_id",
        "actor_results",
        "evidence_manifest",
        "evidence_manifest_artifact",
    )
    review_parameters = signature(ReviewPort.review).parameters
    assert tuple(review_parameters) == (
        "self",
        "requirement",
        "plan",
        "problem_graph",
        "deliverable",
        "deliverable_artifact",
        "actor_results",
        "evidence_manifest",
        "evidence_manifest_artifact",
        "evidence_artifacts",
        "revision_round",
    )
    assert get_type_hints(ReportCompositionPort.compose)["review"] is PassedReportReviewV3
    assert signature(ArtifactReadPort.read_verified_json).return_annotation != Signature.empty
    for method_name in (
        "get_candidate_set",
        "append_candidate_set",
        "get_control_snapshot",
        "append_control_snapshot",
        "get_actor_results",
        "append_actor_result",
        "get_evidence_manifest",
        "append_evidence_manifest",
        "get_deliverable",
        "append_deliverable",
        "get_review",
        "append_review",
        "get_report",
        "append_report",
    ):
        assert callable(getattr(ResearchV3RepositoryPort, method_name))


def test_delivery_and_review_boundary_validators_reject_selected_lineage_drift() -> None:
    requirement = RequirementVersionV3.model_validate(requirement_envelope())
    plan_payload = ExecutionPlanV3.model_validate(plan_body())
    plan = ExecutionPlanVersionV3(
        id="plan_1",
        run_id="run_1",
        requirement_version_id="requirement_1",
        version=1,
        schema_version="execution-plan-v3",
        plan_hash=canonical_json_v3_sha256(plan_payload),
        payload=plan_payload,
        created_at="2026-08-21T00:05:00Z",
    )
    manifest = EvidenceManifestV3.model_validate(evidence_body())
    manifest_artifact = EvidenceManifestArtifactRefV3(
        artifact_id="artifact_evidence",
        kind="evidence_manifest",
        schema_version="evidence-manifest-v3",
        content_hash=canonical_json_v3_sha256(manifest),
    )
    verified = verified_evidence_artifact()
    results = tuple(
        ActorExecutionResultV3(
            run_id="run_1",
            plan_version_id="plan_1",
            attempt_id="attempt_1",
            step_number=step.step_number,
            actor_type=step.actor_type,
            actor_id=step.actor_id,
            step_contract_hash=step.contract_hash,
            result_artifact=(
                verified.artifact
                if step.step_number == 1
                else SealedArtifactRefV3(
                    artifact_id="artifact_skill",
                    kind="actor_result",
                    schema_version="skill-result-v1",
                    content_hash="a" * 64,
                )
            ),
            receipt_id="receipt_tool_1" if step.step_number == 1 else "receipt_skill_2",
            implementation_id="tavily-v1" if step.step_number == 1 else "competitive-analysis-v1",
            execution_mode="real" if step.step_number == 1 else "deterministic",
        )
        for step in plan.payload.steps
    )
    validate_delivery_inputs(
        requirement=requirement,
        plan=plan,
        attempt_id="attempt_1",
        actor_results=results,
        evidence_manifest=manifest,
        evidence_manifest_artifact=manifest_artifact,
    )

    drifted_results = (results[0].model_copy(update={"actor_id": "other-tool"}), results[1])
    with pytest.raises(ValueError, match="selected Plan"):
        validate_delivery_inputs(
            requirement=requirement,
            plan=plan,
            attempt_id="attempt_1",
            actor_results=drifted_results,
            evidence_manifest=manifest,
            evidence_manifest_artifact=manifest_artifact,
        )

    drifted_manifest_value = evidence_body()
    drifted_manifest_value["evidence"][0]["proof"]["receipt_id"] = "receipt_drifted"
    drifted_manifest = EvidenceManifestV3.model_validate(drifted_manifest_value)
    drifted_manifest_artifact = manifest_artifact.model_copy(
        update={"content_hash": canonical_json_v3_sha256(drifted_manifest)}
    )
    with pytest.raises(ValueError, match="Actor execution result"):
        validate_delivery_inputs(
            requirement=requirement,
            plan=plan,
            attempt_id="attempt_1",
            actor_results=results,
            evidence_manifest=drifted_manifest,
            evidence_manifest_artifact=drifted_manifest_artifact,
        )

    deliverable_value = deliverable_body()
    deliverable_value["evidence_manifest_artifact"] = manifest_artifact.model_dump(mode="python")
    deliverable = ResearchDeliverableV3.model_validate(deliverable_value)
    deliverable_artifact = SealedArtifactRefV3(
        artifact_id="artifact_deliverable",
        kind="research_deliverable",
        schema_version="research-deliverable-v3",
        content_hash=canonical_json_v3_sha256(deliverable),
    )
    validate_review_inputs(
        requirement=requirement,
        plan=plan,
        problem_graph=ProblemGraphV1.model_validate(problem_graph_body()),
        deliverable=deliverable,
        deliverable_artifact=deliverable_artifact,
        actor_results=results,
        evidence_manifest=manifest,
        evidence_manifest_artifact=manifest_artifact,
        evidence_artifacts=(verified,),
    )

    pair_drift_deliverable = deliverable.model_copy(
        update={"evidence_manifest_artifact": drifted_manifest_artifact}
    )
    pair_drift_deliverable_artifact = deliverable_artifact.model_copy(
        update={"content_hash": canonical_json_v3_sha256(pair_drift_deliverable)}
    )
    pair_drift_verified = verified.model_copy(update={"receipt_id": "receipt_drifted"})
    with pytest.raises(ValueError, match="Actor execution result"):
        validate_review_inputs(
            requirement=requirement,
            plan=plan,
            problem_graph=ProblemGraphV1.model_validate(problem_graph_body()),
            deliverable=pair_drift_deliverable,
            deliverable_artifact=pair_drift_deliverable_artifact,
            actor_results=results,
            evidence_manifest=drifted_manifest,
            evidence_manifest_artifact=drifted_manifest_artifact,
            evidence_artifacts=(pair_drift_verified,),
        )

    drifted_deliverable = deliverable.model_copy(update={"requirement_version_id": "requirement_other"})
    drifted_artifact = deliverable_artifact.model_copy(
        update={"content_hash": canonical_json_v3_sha256(drifted_deliverable)}
    )
    with pytest.raises(ValueError, match="Requirement and selected Plan lineage"):
        validate_review_inputs(
            requirement=requirement,
            plan=plan,
            problem_graph=ProblemGraphV1.model_validate(problem_graph_body()),
            deliverable=drifted_deliverable,
            deliverable_artifact=drifted_artifact,
            actor_results=results,
            evidence_manifest=manifest,
            evidence_manifest_artifact=manifest_artifact,
            evidence_artifacts=(verified,),
        )


def test_deliverable_requires_the_exact_evidence_manifest_artifact_contract() -> None:
    deliverable = ResearchDeliverableV3.model_validate(deliverable_body())
    assert deliverable.evidence_manifest_artifact.kind == "evidence_manifest"
    assert deliverable.evidence_manifest_artifact.schema_version == "evidence-manifest-v3"

    malformed = deliverable_body()
    malformed["evidence_manifest_artifact"]["schema_version"] = "evidence-manifest-v1"
    with pytest.raises(ValidationError):
        ResearchDeliverableV3.model_validate(malformed)
