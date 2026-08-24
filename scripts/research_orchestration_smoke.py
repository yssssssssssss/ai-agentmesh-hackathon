#!/usr/bin/env python3
"""Run or re-read one redacted research-v2 flow against a live AgentMesh server.

The default mode creates a competitive research Run and drives every HTTP gate.
After restarting the server, pass ``--verify-run-id`` with the emitted Run ID to
prove that the same verified result is still readable from durable state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agentmesh.models import Artifact, ArtifactVerificationState  # noqa: E402
from agentmesh.research_orchestration.artifacts import ArtifactRef  # noqa: E402
from agentmesh.research_orchestration.contracts import (  # noqa: E402
    InvocationState,
    ModelCallReceipt,
    ToolInvocation,
)
from agentmesh.research_orchestration.delivery import (  # noqa: E402
    ClaimLedger,
    ClaimType,
    DeliverableDocument,
    DeterministicReview,
    ReportDocument,
)
from agentmesh.research_orchestration.evidence import (  # noqa: E402
    EvidenceManifest,
    EvidenceSource,
    resolve_json_pointer,
)

EXIT_OK = 0
EXIT_FAILED = 1
DEFAULT_QUERY = (
    "对比三款面向企业产品团队的 AI 研究助手，重点分析证据可追溯、任务恢复和协作能力，"
    "给出适用场景与局限。"
)
ARTIFACT_MODELS = {
    "evidence_manifest": EvidenceManifest,
    "claim_ledger": ClaimLedger,
    "deliverable": DeliverableDocument,
    "review": DeterministicReview,
    "report": ReportDocument,
}


class SmokeError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ResponseLike(Protocol):
    status_code: int

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def get(self, path: str, **kwargs: Any) -> ResponseLike: ...

    def post(self, path: str, **kwargs: Any) -> ResponseLike: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--database", type=Path, default=None)
    verification = parser.add_mutually_exclusive_group()
    verification.add_argument("--verify-run-id", help="only re-read and verify an existing terminal Run")
    verification.add_argument(
        "--verify-off-run-id",
        help="verify an existing Run, then prove off mode creates only a v1 fallback without a research projection",
    )
    parser.add_argument("--timeout-seconds", type=float, default=420.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    return parser


def _response_json(response: ResponseLike, *, expected: set[int], operation: str) -> dict[str, Any]:
    if response.status_code not in expected:
        raise SmokeError(f"{operation}_http_{response.status_code}")
    try:
        payload = response.json()
    except (TypeError, ValueError):
        raise SmokeError(f"{operation}_response_invalid") from None
    if not isinstance(payload, dict):
        raise SmokeError(f"{operation}_response_invalid")
    return payload


def _login(client: HttpClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"user_id": "usr_current_designer", "password": "designer123"},
    )
    _response_json(response, expected={200}, operation="login")


def _get_run(client: HttpClient, run_id: str) -> dict[str, Any]:
    payload = _response_json(
        client.get(f"/api/agent/runs/{run_id}"),
        expected={200},
        operation="get_run",
    )
    item = payload.get("item")
    if not isinstance(item, dict):
        raise SmokeError("run_projection_invalid")
    return item


def _get_projection(client: HttpClient, run_id: str) -> dict[str, Any]:
    return _response_json(
        client.get(f"/api/agent/runs/{run_id}/research"),
        expected={200},
        operation="get_research",
    )


def _post_command(
    client: HttpClient,
    path: str,
    *,
    body: Mapping[str, Any],
    idempotency_key: str,
    operation: str,
) -> dict[str, Any]:
    return _response_json(
        client.post(path, json=dict(body), headers={"Idempotency-Key": idempotency_key}),
        expected={202},
        operation=operation,
    )


def _drive_new_run(client: HttpClient, *, timeout_seconds: float, poll_seconds: float) -> tuple[str, dict[str, Any]]:
    created = _response_json(
        client.post(
            "/api/agent/runs",
            json={
                "content": DEFAULT_QUERY,
                "client_turn_id": f"research-smoke-{uuid4().hex}",
                "explicit_skill_name": "competitive-analysis",
                "orchestration_mode": "single",
            },
        ),
        expected={202},
        operation="create_run",
    )
    run = created.get("item")
    if not isinstance(run, dict) or not isinstance(run.get("id"), str):
        raise SmokeError("create_run_response_invalid")
    if run.get("orchestration_version") != "research-v2" or run.get("orchestration_mode") != "execute":
        raise SmokeError("research_execute_mode_not_active")
    run_id = str(run["id"])
    planning_deadline = time.monotonic() + max(1.0, timeout_seconds)
    while True:
        projection = _get_projection(client, run_id)
        workflow = projection.get("workflow")
        plans = projection.get("plans")
        if not isinstance(workflow, dict) or not isinstance(plans, list):
            raise SmokeError("research_plan_projection_invalid")
        if len(plans) == 1 and workflow.get("active_gate") == "plan_confirmation":
            break
        if workflow.get("active_gate") == "clarification":
            raise SmokeError("unexpected_clarification_gate")
        if workflow.get("phase") == "terminal":
            raise SmokeError("research_planning_failed")
        if time.monotonic() >= planning_deadline:
            raise SmokeError("research_planning_timeout")
        time.sleep(max(0.05, poll_seconds))
    plan = plans[0]
    if not isinstance(plan, dict) or not isinstance(plan.get("plan_version_id"), str):
        raise SmokeError("research_plan_invalid")
    state_version = workflow.get("state_version")
    if not isinstance(state_version, int):
        raise SmokeError("research_state_version_missing")
    _post_command(
        client,
        f"/api/agent/runs/{run_id}/research/plans/{plan['plan_version_id']}/confirm",
        body={"expected_state_version": state_version},
        idempotency_key=f"research-smoke-confirm-{run_id}",
        operation="confirm_plan",
    )
    projection = _get_projection(client, run_id)
    workflow = projection.get("workflow")
    if not isinstance(workflow, dict) or workflow.get("phase") != "planning" or workflow.get("active_gate") != "none":
        raise SmokeError("plan_confirmation_did_not_converge")
    state_version = workflow.get("state_version")
    if not isinstance(state_version, int):
        raise SmokeError("research_state_version_missing")
    _post_command(
        client,
        f"/api/agent/runs/{run_id}/research/execute",
        body={"expected_state_version": state_version},
        idempotency_key=f"research-smoke-execute-{run_id}",
        operation="execute_research",
    )

    approved = False
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    while time.monotonic() < deadline:
        projection = _get_projection(client, run_id)
        workflow = projection.get("workflow")
        if not isinstance(workflow, dict):
            raise SmokeError("research_workflow_projection_invalid")
        gate = workflow.get("active_gate")
        if gate == "tool_approval" and not approved:
            approval = projection.get("tool_approval")
            if not isinstance(approval, dict):
                raise SmokeError("tool_approval_projection_missing")
            item_id = approval.get("inbox_item_id")
            call_id = approval.get("call_id")
            if not isinstance(item_id, str) or not isinstance(call_id, str):
                raise SmokeError("tool_approval_projection_invalid")
            _response_json(
                client.post(
                    f"/api/inbox/{item_id}/resolve-tool-approval",
                    params={"action": "approve", "call_id": call_id},
                ),
                expected={200},
                operation="approve_tool",
            )
            approved = True
            continue
        if gate == "recovery_decision":
            raise SmokeError("tool_result_unknown")
        if workflow.get("phase") == "terminal":
            run = _get_run(client, run_id)
            attempt = projection.get("attempt")
            if run.get("status") not in {"completed", "partial"} or not isinstance(attempt, dict) or attempt.get("status") != "completed":
                raise SmokeError("research_run_not_successful")
            return run_id, projection
        time.sleep(max(0.05, poll_seconds))
    raise SmokeError("research_run_timeout")


def _verify_off_fallback(client: HttpClient) -> dict[str, str]:
    created = _response_json(
        client.post(
            "/api/agent/runs",
            json={
                "content": DEFAULT_QUERY,
                "client_turn_id": f"research-off-drill-{uuid4().hex}",
                "orchestration_mode": "single",
            },
        ),
        expected={202},
        operation="create_off_fallback",
    )
    run = created.get("item")
    if (
        not isinstance(run, dict)
        or not isinstance(run.get("id"), str)
        or run.get("orchestration_version") != "v1"
        or run.get("orchestration_mode") != "off"
    ):
        raise SmokeError("off_mode_created_research_v2")
    run_id = str(run["id"])
    cancelled = _response_json(
        client.post(f"/api/agent/runs/{run_id}/cancel"),
        expected={200},
        operation="cancel_off_fallback",
    )
    cancelled_run = cancelled.get("item")
    if not isinstance(cancelled_run, dict) or cancelled_run.get("status") not in {
        "cancelled",
        "completed",
        "failed",
    }:
        raise SmokeError("off_fallback_not_cancelled")
    research_response = client.get(f"/api/agent/runs/{run_id}/research")
    if research_response.status_code not in {404, 409}:
        raise SmokeError("off_mode_exposed_research_projection")
    return {
        "fallback_run_id": run_id,
        "orchestration_version": "v1",
        "orchestration_mode": "off",
        "status": str(cancelled_run["status"]),
    }


def _database_path(value: Path | None) -> Path:
    path = value if value is not None else Path(os.getenv("AGENTMESH_DB_PATH", "data/agentmesh.sqlite3"))
    return path if path.is_absolute() else PROJECT_ROOT / path


def _connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SmokeError("research_database_missing")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _artifact(connection: sqlite3.Connection, artifact_id: str, *, run_id: str, attempt_id: str) -> Artifact:
    row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    if row is None:
        raise SmokeError("artifact_missing")
    try:
        artifact = Artifact.model_validate_json(row["payload"])
    except (TypeError, ValueError):
        raise SmokeError("artifact_payload_invalid") from None
    encoded = artifact.content.encode("utf-8")
    if (
        artifact.run_id != run_id
        or artifact.attempt_id != attempt_id
        or artifact.verification_state != ArtifactVerificationState.SEALED
        or row["verification_state"] != ArtifactVerificationState.SEALED.value
        or row["content_hash"] != artifact.content_hash
        or row["size_bytes"] != artifact.size_bytes
        or hashlib.sha256(encoded).hexdigest() != artifact.content_hash
        or len(encoded) != artifact.size_bytes
    ):
        raise SmokeError("artifact_integrity_failed")
    return artifact


def _artifact_ref_matches(reference: ArtifactRef, artifact: Artifact) -> bool:
    return reference.artifact_id == artifact.id and reference.content_hash == artifact.content_hash


def _validate_durable_result(
    database: Path,
    *,
    run_id: str,
    projection: Mapping[str, Any],
    mode: str,
) -> dict[str, Any]:
    requirement = projection.get("requirement")
    plans = projection.get("plans")
    attempt = projection.get("attempt")
    artifacts_projection = projection.get("artifacts")
    provenance = projection.get("provenance")
    if (
        not isinstance(requirement, dict)
        or not isinstance(plans, list)
        or len(plans) != 1
        or not isinstance(plans[0], dict)
        or not isinstance(attempt, dict)
        or not isinstance(artifacts_projection, dict)
        or not isinstance(provenance, dict)
        or projection.get("integrity_errors") not in ([], None)
    ):
        raise SmokeError("terminal_projection_invalid")
    attempt_id = attempt.get("attempt_id")
    if not isinstance(attempt_id, str):
        raise SmokeError("terminal_attempt_missing")

    artifact_ids: dict[str, str] = {}
    for kind in ARTIFACT_MODELS:
        value = artifacts_projection.get(f"{kind}_id")
        if not isinstance(value, str):
            raise SmokeError(f"{kind}_missing")
        artifact_ids[kind] = value

    with _connect_read_only(database) as connection:
        parsed_artifacts: dict[str, Artifact] = {}
        parsed_models: dict[str, Any] = {}
        for kind, artifact_id in artifact_ids.items():
            artifact = _artifact(connection, artifact_id, run_id=run_id, attempt_id=attempt_id)
            if artifact.artifact_type != kind:
                raise SmokeError("artifact_kind_mismatch")
            try:
                parsed = ARTIFACT_MODELS[kind].model_validate_json(artifact.content)
            except (TypeError, ValueError):
                raise SmokeError(f"{kind}_payload_invalid") from None
            parsed_artifacts[kind] = artifact
            parsed_models[kind] = parsed

        invocation_rows = connection.execute(
            "SELECT payload FROM research_tool_invocations WHERE run_id = ? AND active_attempt_id = ?",
            (run_id, attempt_id),
        ).fetchall()
        if len(invocation_rows) != 1:
            raise SmokeError("tool_invocation_count_invalid")
        try:
            invocation = ToolInvocation.model_validate_json(invocation_rows[0]["payload"])
        except (TypeError, ValueError):
            raise SmokeError("tool_invocation_invalid") from None

        receipt_rows = connection.execute(
            """
            SELECT payload FROM research_model_call_receipts
            WHERE run_id = ? AND owner_kind = 'attempt' AND owner_id = ?
              AND stage = 'competitive-analysis'
            """,
            (run_id, attempt_id),
        ).fetchall()
        if len(receipt_rows) != 1:
            raise SmokeError("model_receipt_count_invalid")
        try:
            model_receipt = ModelCallReceipt.model_validate_json(receipt_rows[0]["payload"])
        except (TypeError, ValueError):
            raise SmokeError("model_receipt_invalid") from None

        manifest: EvidenceManifest = parsed_models["evidence_manifest"]
        ledger: ClaimLedger = parsed_models["claim_ledger"]
        deliverable: DeliverableDocument = parsed_models["deliverable"]
        review: DeterministicReview = parsed_models["review"]
        report: ReportDocument = parsed_models["report"]
        evidence_ids = {entry.evidence_id for entry in manifest.entries}
        if not evidence_ids:
            raise SmokeError("evidence_missing")
        for entry in manifest.entries:
            source_artifact = _artifact(connection, entry.artifact_id, run_id=run_id, attempt_id=attempt_id)
            if source_artifact.content_hash != entry.content_hash or source_artifact.artifact_type != "evidence_source":
                raise SmokeError("evidence_artifact_mismatch")
            try:
                source = EvidenceSource.model_validate_json(source_artifact.content)
            except (TypeError, ValueError):
                raise SmokeError("evidence_source_invalid") from None
            if source.evidence_id != entry.evidence_id or resolve_json_pointer(source.model_dump(), entry.evidence_pointer) != source.quote:
                raise SmokeError("evidence_pointer_invalid")
            origin = _artifact(connection, source.origin_artifact.artifact_id, run_id=run_id, attempt_id=attempt_id)
            if not _artifact_ref_matches(source.origin_artifact, origin) or origin.artifact_type != "tool_result":
                raise SmokeError("evidence_origin_invalid")

    factual_claims = [claim for claim in ledger.claims if claim.claim_type == ClaimType.FACT]
    if not factual_claims or any(not claim.evidence_ids or not set(claim.evidence_ids).issubset(evidence_ids) for claim in factual_claims):
        raise SmokeError("factual_claim_coverage_failed")
    if ledger.model_call_receipt_id != model_receipt.id or any(
        claim.model_call_receipt_id != model_receipt.id for claim in ledger.claims
    ):
        raise SmokeError("claim_model_receipt_mismatch")
    if (
        not _artifact_ref_matches(deliverable.evidence_manifest_artifact, parsed_artifacts["evidence_manifest"])
        or not _artifact_ref_matches(deliverable.claim_ledger_artifact, parsed_artifacts["claim_ledger"])
        or not _artifact_ref_matches(review.deliverable_artifact, parsed_artifacts["deliverable"])
        or not _artifact_ref_matches(report.deliverable_artifact, parsed_artifacts["deliverable"])
        or not _artifact_ref_matches(report.review_artifact, parsed_artifacts["review"])
    ):
        raise SmokeError("result_lineage_invalid")
    if review.status != "pass" or not all(check.passed for check in review.checks):
        raise SmokeError("deterministic_review_failed")
    if (
        invocation.state != InvocationState.ACKNOWLEDGED
        or invocation.send_count != 1
        or invocation.receipt is None
        or invocation.receipt.mode != "real"
        or invocation.receipt.result_count < 1
    ):
        raise SmokeError("tool_receipt_invalid")
    if (
        provenance.get("tool_execution_mode") != "real"
        or provenance.get("tool_implementation_id") != invocation.receipt.implementation_id
        or not isinstance(provenance.get("requested_model"), str)
        or provenance.get("actual_model") != model_receipt.actual_model
        or sum(model_receipt.usage.values()) <= 0
    ):
        raise SmokeError("provider_provenance_invalid")

    return {
        "passed": True,
        "mode": mode,
        "run_id": run_id,
        "requirement_id": requirement.get("requirement_version_id"),
        "plan_id": plans[0].get("plan_version_id"),
        "attempt_id": attempt_id,
        "invocation_id": invocation.id,
        "model_call_id": model_receipt.id,
        "requested_model": provenance.get("requested_model"),
        "actual_model": model_receipt.actual_model,
        "tool": {
            "implementation_id": invocation.receipt.implementation_id,
            "provider": invocation.receipt.provider,
            "mode": invocation.receipt.mode,
            "state": invocation.state.value,
            "send_count": invocation.send_count,
        },
        "artifacts": {
            kind: {"id": artifact.id, "sha256": artifact.content_hash}
            for kind, artifact in parsed_artifacts.items()
        },
        "evidence": {
            "count": len(manifest.entries),
            "ids": sorted(evidence_ids),
            "pointers": sorted({entry.evidence_pointer for entry in manifest.entries}),
        },
        "claims": {
            "count": len(ledger.claims),
            "factual_count": len(factual_claims),
            "factual_coverage_percent": 100,
        },
        "review": {"status": review.status, "passed_checks": len(review.checks)},
        "report_bound_to_reviewed_deliverable": True,
    }


def run_smoke(
    client: HttpClient,
    *,
    database: Path,
    verify_run_id: str | None,
    timeout_seconds: float,
    poll_seconds: float,
    verify_off_run_id: str | None = None,
) -> dict[str, Any]:
    _login(client)
    existing_run_id = verify_run_id or verify_off_run_id
    if existing_run_id is None:
        run_id, projection = _drive_new_run(
            client,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        mode = "full"
    else:
        run_id = existing_run_id
        run = _get_run(client, run_id)
        projection = _get_projection(client, run_id)
        workflow = projection.get("workflow")
        if run.get("status") not in {"completed", "partial"} or not isinstance(workflow, dict) or workflow.get("phase") != "terminal":
            raise SmokeError("historical_run_not_readable")
        mode = "off_rollback" if verify_off_run_id is not None else "verify_existing"
    result = _validate_durable_result(database, run_id=run_id, projection=projection, mode=mode)
    if verify_off_run_id is not None:
        result["off_fallback"] = _verify_off_fallback(client)
    return result


def _safe_failure(error: BaseException) -> dict[str, Any]:
    return {
        "passed": False,
        "error_code": error.code if isinstance(error, SmokeError) else type(error).__name__,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = _database_path(args.database)
    try:
        with httpx.Client(
            base_url=args.base_url.rstrip("/"),
            timeout=max(1.0, min(args.timeout_seconds, 120.0)),
            follow_redirects=False,
        ) as client:
            result = run_smoke(
                client,
                database=database,
                verify_run_id=args.verify_run_id,
                verify_off_run_id=args.verify_off_run_id,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
    except BaseException as error:
        print(json.dumps(_safe_failure(error), ensure_ascii=False, sort_keys=True))
        return EXIT_FAILED
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
