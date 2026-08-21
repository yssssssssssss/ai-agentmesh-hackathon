from __future__ import annotations

from copy import deepcopy

from research_v3_contract_samples import (
    artifact_ref,
    candidate_set_body,
    deliverable_body,
    evidence_artifact_content,
    evidence_body,
    plan_body,
    report_body,
    requirement_envelope,
    review_body,
)

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.common import EvidenceManifestArtifactRefV3
from agentmesh.research_orchestration.v3.evidence import EvidenceManifestV3, VerifiedArtifactContentV3
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanV3
from agentmesh.research_orchestration.v3.web_projection import project_verified_evidence_for_workbench

WORKBENCH_STATES = (
    "idle",
    "clarify",
    "candidates",
    "plan",
    "approval",
    "dag_or_executing",
    "paused",
    "text_report",
)


def workbench_fixture_bodies() -> dict[str, dict]:
    requirement = requirement_envelope()
    plan_payload = ExecutionPlanV3.model_validate(plan_body()).model_dump(mode="python")
    plan = {
        "id": "plan_1",
        "run_id": "run_1",
        "requirement_version_id": "requirement_1",
        "version": 1,
        "schema_version": "execution-plan-v3",
        "plan_hash": canonical_json_v3_sha256(plan_payload),
        "payload": plan_payload,
        "created_at": "2026-08-21T00:05:00Z",
    }
    candidates = candidate_set_body()

    artifact_1_content = evidence_artifact_content()
    artifact_1 = artifact_ref(
        "artifact_tool_1",
        "actor_result",
        "tool-result-v1",
        canonical_json_v3_sha256(artifact_1_content),
    )
    artifact_2_content = {"payload": deepcopy(deliverable_body()["payload"])}
    artifact_2 = artifact_ref(
        "artifact_skill_2",
        "skill_result",
        "competitive-analysis-text-v1",
        canonical_json_v3_sha256(artifact_2_content),
    )
    step_1, step_2 = plan_payload["steps"]
    result_1 = _result(step_1, artifact_1, "receipt_tool_1")
    result_2 = _result(step_2, artifact_2, "receipt_skill_2")

    pending_approvals = [
        {
            "gate_key": "public_sources_only",
            "plan_version_id": "plan_1",
            "role": "owner",
            "decision": "pending",
            "receipt_id": None,
        }
    ]
    approved = [
        {
            **pending_approvals[0],
            "decision": "approved",
            "receipt_id": "approval_receipt_1",
        }
    ]

    manifest = evidence_body()
    manifest_artifact = artifact_ref(
        "artifact_evidence",
        "evidence_manifest",
        "evidence-manifest-v3",
        canonical_json_v3_sha256(manifest),
    )
    verified = {
        "run_id": "run_1",
        "plan_version_id": "plan_1",
        "attempt_id": "attempt_1",
        "step_number": 1,
        "actor_type": "tool",
        "actor_id": "tavily-web-search",
        "step_contract_hash": step_1["contract_hash"],
        "receipt_id": "receipt_tool_1",
        "implementation_id": "tavily-v1",
        "execution_mode": "real",
        "artifact": artifact_1,
        "content": artifact_1_content,
    }
    evidence_projection = project_verified_evidence_for_workbench(
        artifact=EvidenceManifestArtifactRefV3.model_validate(manifest_artifact),
        manifest=EvidenceManifestV3.model_validate(manifest),
        verified_artifacts=(VerifiedArtifactContentV3.model_validate(verified),),
    ).model_dump(mode="python")

    deliverable = deliverable_body()
    deliverable["evidence_manifest_artifact"] = manifest_artifact
    deliverable["capability_provenance"][0]["result_artifact"] = artifact_2
    deliverable_artifact = artifact_ref(
        "artifact_deliverable",
        "research_deliverable",
        "research-deliverable-v3",
        canonical_json_v3_sha256(deliverable),
    )
    review = review_body()
    review["deliverable_artifact"] = deliverable_artifact
    review_artifact = artifact_ref(
        "artifact_review",
        "report_review",
        "report-review-v3",
        canonical_json_v3_sha256(review),
    )
    report = report_body()
    report["deliverable_artifact"] = deliverable_artifact
    report["review_artifact"] = review_artifact
    report_artifact = artifact_ref(
        "artifact_report",
        "report_document",
        "report-document-v3",
        canonical_json_v3_sha256(report),
    )

    clarify_requirement = requirement_envelope()
    clarify_requirement["payload"]["scope"] = []
    clarify_requirement["payload"]["ambiguities"] = [
        {
            "id": "ambiguity_scope",
            "statement": "Comparison scope is unresolved.",
            "blocking": True,
        }
    ]
    clarify_requirement["payload"]["clarification_questions"] = [
        {
            "key": "scope",
            "question": "Which competitors are in scope?",
            "rationale": "Scope changes evidence collection.",
        }
    ]
    clarify_requirement["content_hash"] = canonical_json_v3_sha256(clarify_requirement["payload"])

    return {
        "idle": _aggregate("idle", 0, "none", "inactive"),
        "clarify": _aggregate(
            "clarify",
            1,
            "clarification",
            "pending",
            requirement=clarify_requirement,
        ),
        "candidates": _aggregate(
            "candidates",
            2,
            "candidate_selection",
            "pending",
            requirement=requirement,
            candidates=candidates,
        ),
        "plan": _aggregate(
            "plan",
            3,
            "plan_confirmation",
            "pending",
            requirement=requirement,
            candidates=candidates,
            selected_plan=plan,
        ),
        "approval": _aggregate(
            "approval",
            4,
            "role_approval",
            "pending",
            requirement=requirement,
            candidates=candidates,
            selected_plan=plan,
            approvals=pending_approvals,
        ),
        "dag_or_executing": _aggregate(
            "dag_or_executing",
            5,
            "none",
            "inactive",
            requirement=requirement,
            candidates=candidates,
            selected_plan=plan,
            approvals=approved,
            attempt=_attempt(step_1, step_2, result_1, result_2, "running", "running"),
        ),
        "paused": _aggregate(
            "paused",
            6,
            "recovery",
            "blocked",
            requirement=requirement,
            candidates=candidates,
            selected_plan=plan,
            approvals=approved,
            attempt=_attempt(step_1, step_2, result_1, result_2, "paused", "failed"),
            recovery={
                "failed_step_number": 2,
                "reason_code": "worker_loss",
                "allowed_actions": ["retry", "abort"],
                "decision_required": True,
            },
        ),
        "text_report": _aggregate(
            "text_report",
            7,
            "none",
            "inactive",
            requirement=requirement,
            candidates=candidates,
            selected_plan=plan,
            approvals=approved,
            attempt=_attempt(step_1, step_2, result_1, result_2, "completed", "succeeded"),
            evidence=evidence_projection,
            deliverable={"artifact": deliverable_artifact, "content": deliverable},
            review={"artifact": review_artifact, "content": review},
            report={"artifact": report_artifact, "content": report},
        ),
    }


def _result(step: dict, artifact: dict, receipt_id: str) -> dict:
    is_tool = step["actor_type"] == "tool"
    return {
        "run_id": "run_1",
        "plan_version_id": "plan_1",
        "attempt_id": "attempt_1",
        "step_number": step["step_number"],
        "actor_type": step["actor_type"],
        "actor_id": step["actor_id"],
        "step_contract_hash": step["contract_hash"],
        "result_artifact": artifact,
        "receipt_id": receipt_id,
        "implementation_id": "tavily-v1" if is_tool else "competitive-analysis-v1",
        "execution_mode": "real" if is_tool else "deterministic",
    }


def _attempt(
    step_1: dict,
    step_2: dict,
    result_1: dict,
    result_2: dict,
    status: str,
    second_status: str,
) -> dict:
    return {
        "attempt_id": "attempt_1",
        "run_id": "run_1",
        "plan_version_id": "plan_1",
        "status": status,
        "steps": [
            {
                "step_number": 1,
                "actor_type": step_1["actor_type"],
                "actor_id": step_1["actor_id"],
                "step_contract_hash": step_1["contract_hash"],
                "expected_outputs": step_1["expected_outputs"],
                "status": "succeeded",
                "result": result_1,
                "failure_code": None,
            },
            {
                "step_number": 2,
                "actor_type": step_2["actor_type"],
                "actor_id": step_2["actor_id"],
                "step_contract_hash": step_2["contract_hash"],
                "expected_outputs": step_2["expected_outputs"],
                "status": second_status,
                "result": result_2 if second_status == "succeeded" else None,
                "failure_code": "worker_loss" if second_status == "failed" else None,
            },
        ],
    }


def _aggregate(
    state: str,
    version: int,
    gate_kind: str,
    gate_status: str,
    **values: object,
) -> dict:
    body = {
        "schema_version": "research-workbench-aggregate-v1",
        "projection_kind": "research-v3-current",
        "orchestration_version": "research-v3",
        "run_id": "run_1",
        "workflow": {
            "state": state,
            "state_version": version,
            "gate": {
                "kind": gate_kind,
                "status": gate_status,
                "required_role": "owner" if gate_kind == "role_approval" else None,
            },
        },
        "requirement": None,
        "candidates": None,
        "selected_plan": None,
        "approvals": [],
        "attempt": None,
        "recovery": None,
        "evidence": None,
        "deliverable": None,
        "review": None,
        "report": None,
        "provenance": {
            "source_kind": "isolated_fixture",
            "projection_schema_version": "research-workbench-aggregate-v1",
            "projected_at": f"2026-08-21T00:{version:02d}:00Z",
            "source_state_version": version,
            "baseline_state_id": state,
        },
    }
    body.update(values)
    return body
