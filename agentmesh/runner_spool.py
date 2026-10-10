from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import httpx
from platformdirs import user_data_path

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.runner_client import RunnerControlPlaneClient
from agentmesh.runner_contracts import (
    RunnerArtifactUploadRequest,
    RunnerCancellationRequest,
    RunnerCompletionRequest,
    RunnerCompletionRequestV2,
    RunnerEventBatchRequest,
    RunnerExecutionEventV1,
    RunnerFailureRequest,
    RunnerModelDeliveryRequestV1,
    RunnerNodeCompletionRequest,
    RunnerNodeCompletionRequestV2,
)


class RunnerSpool:
    def __init__(self, path: str | Path | None = None):
        configured = path or os.getenv("AGENTMESH_RUNNER_SPOOL_PATH")
        self.path = Path(configured) if configured else user_data_path("agentmesh") / "runner-spool.sqlite3"
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    lease_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_order INTEGER PRIMARY KEY AUTOINCREMENT
                )
                """
            )
        self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _enqueue(self, *, item_id: str, kind: str, lease_id: str, payload: dict[str, object]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT kind, lease_id, payload FROM outbox WHERE id = ?",
                (item_id,),
            ).fetchone()
            if existing is not None:
                if existing["kind"] != kind or existing["lease_id"] != lease_id or existing["payload"] != serialized:
                    raise RuntimeError("runner_spool_idempotency_conflict")
                return
            connection.execute(
                "INSERT INTO outbox(id, kind, lease_id, payload) VALUES (?, ?, ?, ?)",
                (item_id, kind, lease_id, serialized),
            )

    def enqueue_events(self, lease_id: str, events: list[RunnerExecutionEventV1]) -> None:
        request = RunnerEventBatchRequest(events=events)
        item_id = (
            "events_"
            + canonical_json_sha256({"lease_id": lease_id, "event_ids": [event.client_event_id for event in events]})[
                :32
            ]
        )
        self._enqueue(
            item_id=item_id,
            kind="events",
            lease_id=lease_id,
            payload=request.model_dump(mode="json"),
        )

    def enqueue_completion(self, lease_id: str, request: RunnerCompletionRequest) -> None:
        self._enqueue(
            item_id=f"complete_{request.command_id}",
            kind="complete",
            lease_id=lease_id,
            payload=request.model_dump(mode="json"),
        )

    def enqueue_model_delivery(self, lease_id: str, request: RunnerModelDeliveryRequestV1, *, node: bool = False) -> None:
        self._enqueue(item_id='model_delivery_' + request.handoff_id,
                      kind='node_model_delivery' if node else 'model_delivery', lease_id=lease_id,
                      payload=request.model_dump(mode='json'))

    def acknowledge_model_delivery(self, handoff_id: str) -> None:
        with self._connect() as connection:
            connection.execute('DELETE FROM outbox WHERE id = ?', ('model_delivery_' + handoff_id,))

    def enqueue_artifact(self, lease_id: str, request: RunnerArtifactUploadRequest) -> None:
        self._enqueue(
            item_id=f"artifact_{request.artifact_id}",
            kind="artifact",
            lease_id=lease_id,
            payload=request.model_dump(mode="json"),
        )

    def enqueue_node_completion(self, lease_id: str, request: RunnerNodeCompletionRequest) -> None:
        self._enqueue(
            item_id=f"node_complete_{request.command_id}",
            kind="node_complete",
            lease_id=lease_id,
            payload=request.model_dump(mode="json"),
        )

    def enqueue_failure(
        self,
        lease_id: str,
        request: RunnerFailureRequest,
        *,
        node: bool = False,
    ) -> None:
        kind = "node_fail" if node else "fail"
        self._enqueue(
            item_id=f"{kind}_{request.command_id}",
            kind=kind,
            lease_id=lease_id,
            payload=request.model_dump(mode="json"),
        )

    def enqueue_cancellation(self, lease_id: str, request: RunnerCancellationRequest) -> None:
        self._enqueue(
            item_id=f"cancel_{request.command_id}",
            kind="cancelled",
            lease_id=lease_id,
            payload=request.model_dump(mode="json"),
        )

    @staticmethod
    def _discardable(error: httpx.HTTPStatusError) -> bool:
        if error.response.status_code == 404:
            return True
        try:
            payload = error.response.json()
        except ValueError:
            return False
        detail = payload.get("detail") if isinstance(payload, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        return code in {
            "runner_lease_inactive",
            "runner_lease_expired",
            "runner_dispatch_state_conflict",
        }

    def flush(self, client: RunnerControlPlaneClient) -> int:
        sent = 0
        while True:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT id, kind, lease_id, payload FROM outbox ORDER BY created_order LIMIT 1"
                ).fetchone()
            if row is None:
                return sent
            payload = json.loads(row["payload"])
            try:
                if row["kind"] == "events":
                    request = RunnerEventBatchRequest.model_validate(payload)
                    client.append_events(row["lease_id"], request.events)
                elif row["kind"] == "complete":
                    completion_type = (RunnerCompletionRequestV2 if payload.get('schema_version') == 'runner-completion-v2'
                                       else RunnerCompletionRequest)
                    client.complete(row["lease_id"], completion_type.model_validate(payload))
                elif row['kind'] in {'model_delivery', 'node_model_delivery'}:
                    result = client.confirm_model_handoff(row['lease_id'], RunnerModelDeliveryRequestV1.model_validate(payload))
                    code = result.get('budget_error_code')
                    if code in {'run_model_request_usage_exceeded', 'run_model_budget_exhausted'}:
                        failure = RunnerFailureRequest(command_id='budget_' + payload['handoff_id'], error_code=code)
                        fail = client.fail_node if row['kind'] == 'node_model_delivery' else client.fail
                        fail(row['lease_id'], failure)
                        with self._connect() as connection:
                            connection.execute("DELETE FROM outbox WHERE lease_id = ? AND kind IN ('complete', 'node_complete')",
                                               (row['lease_id'],))
                elif row["kind"] == "artifact":
                    client.upload_artifact(
                        row["lease_id"],
                        RunnerArtifactUploadRequest.model_validate(payload),
                    )
                elif row["kind"] == "node_complete":
                    completion_type = (RunnerNodeCompletionRequestV2 if payload.get('schema_version') == 'runner-node-completion-v2'
                                       else RunnerNodeCompletionRequest)
                    client.complete_node(
                        row["lease_id"],
                        completion_type.model_validate(payload),
                    )
                elif row["kind"] == "node_fail":
                    client.fail_node(
                        row["lease_id"],
                        RunnerFailureRequest.model_validate(payload),
                    )
                elif row["kind"] == "fail":
                    client.fail(row["lease_id"], RunnerFailureRequest.model_validate(payload))
                elif row["kind"] == "cancelled":
                    client.acknowledge_cancelled(
                        row["lease_id"],
                        RunnerCancellationRequest.model_validate(payload),
                    )
                else:
                    raise RuntimeError("runner_spool_kind_invalid")
            except httpx.HTTPStatusError as error:
                if not self._discardable(error):
                    raise
            with self._connect() as connection:
                connection.execute("DELETE FROM outbox WHERE id = ?", (row["id"],))
            sent += 1

    def pending_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) FROM outbox").fetchone()
        return int(row[0])
