from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

import pytest

from agentmesh.models import Artifact, ArtifactVerificationState
from scripts import research_orchestration_smoke as smoke


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self.payload


class _FlowClient:
    def __init__(self) -> None:
        self.phase = "preview"
        self.calls: list[tuple[str, str]] = []
        self.research_reads = 0

    @staticmethod
    def _projection(phase: str) -> dict[str, Any]:
        gate = {
            "preview": "plan_confirmation",
            "confirmed": "none",
            "approval": "tool_approval",
            "terminal": "none",
        }[phase]
        workflow_phase = "terminal" if phase == "terminal" else "planning" if phase != "approval" else "execution"
        return {
            "workflow": {"phase": workflow_phase, "active_gate": gate, "state_version": 1},
            "plans": [{"plan_version_id": "plan_smoke"}],
            "attempt": {"attempt_id": "attempt_smoke", "status": "completed"} if phase == "terminal" else None,
            "tool_approval": (
                {"inbox_item_id": "inbox_smoke", "call_id": "call_smoke"}
                if phase == "approval"
                else None
            ),
        }

    def get(self, path: str, **_kwargs: Any) -> _Response:
        self.calls.append(("GET", path))
        if path.endswith("/research"):
            self.research_reads += 1
            if self.research_reads == 1:
                return _Response(
                    {
                        "workflow": {"phase": "requirement", "active_gate": "none", "state_version": 1},
                        "plans": [],
                    }
                )
            return _Response(self._projection(self.phase))
        return _Response({"item": {"id": "run_smoke", "status": "completed"}})

    def post(self, path: str, **_kwargs: Any) -> _Response:
        self.calls.append(("POST", path))
        if path == "/api/agent/runs":
            return _Response(
                {
                    "item": {
                        "id": "run_smoke",
                        "orchestration_version": "research-v2",
                        "orchestration_mode": "execute",
                    }
                },
                202,
            )
        if path.endswith("/confirm"):
            self.phase = "confirmed"
            return _Response({"accepted": True}, 202)
        if path.endswith("/execute"):
            self.phase = "approval"
            return _Response({"accepted": True}, 202)
        if "resolve-tool-approval" in path:
            self.phase = "terminal"
            return _Response({"scheduled": True})
        raise AssertionError(path)


class _OffClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get(self, path: str, **_kwargs: Any) -> _Response:
        self.calls.append(("GET", path))
        return _Response({"detail": "Research run not found"}, 404)

    def post(self, path: str, **_kwargs: Any) -> _Response:
        self.calls.append(("POST", path))
        if path == "/api/agent/runs":
            return _Response(
                {
                    "item": {
                        "id": "run_off_fallback",
                        "orchestration_version": "v1",
                        "orchestration_mode": "off",
                    }
                },
                202,
            )
        if path == "/api/agent/runs/run_off_fallback/cancel":
            return _Response({"item": {"id": "run_off_fallback", "status": "cancelled"}})
        raise AssertionError(path)


def test_http_smoke_keeps_plan_and_tool_approval_as_separate_gates() -> None:
    client = _FlowClient()

    run_id, projection = smoke._drive_new_run(client, timeout_seconds=1, poll_seconds=0.01)

    assert run_id == "run_smoke"
    assert projection["workflow"]["phase"] == "terminal"
    mutations = [path for method, path in client.calls if method == "POST"]
    assert mutations == [
        "/api/agent/runs",
        "/api/agent/runs/run_smoke/research/plans/plan_smoke/confirm",
        "/api/agent/runs/run_smoke/research/execute",
        "/api/inbox/inbox_smoke/resolve-tool-approval",
    ]


def test_artifact_validation_recomputes_hash_without_exposing_content() -> None:
    content = json.dumps({"private": "body"}, separators=(",", ":"))
    digest = hashlib.sha256(content.encode()).hexdigest()
    artifact = Artifact(
        id="artifact_smoke",
        run_id="run_smoke",
        workspace_id="workspace_smoke",
        project_id="project_smoke",
        user_id="user_smoke",
        artifact_type="report",
        content_type="application/json",
        content=content,
        verification_state=ArtifactVerificationState.SEALED,
        schema_version="report-document-v1",
        content_hash=digest,
        size_bytes=len(content.encode()),
        requirement_version_id="requirement_smoke",
        plan_version_id="plan_smoke",
        attempt_id="attempt_smoke",
        step_number=2,
    )
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE artifacts(
            id TEXT PRIMARY KEY, payload TEXT, verification_state TEXT,
            content_hash TEXT, size_bytes INTEGER
        )
        """
    )
    connection.execute(
        "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?)",
        (artifact.id, artifact.model_dump_json(), "sealed", digest, artifact.size_bytes),
    )

    verified = smoke._artifact(connection, artifact.id, run_id="run_smoke", attempt_id="attempt_smoke")
    assert verified.content_hash == digest
    connection.execute("UPDATE artifacts SET content_hash = ? WHERE id = ?", ("f" * 64, artifact.id))
    with pytest.raises(smoke.SmokeError) as caught:
        smoke._artifact(connection, artifact.id, run_id="run_smoke", attempt_id="attempt_smoke")
    assert caught.value.code == "artifact_integrity_failed"


def test_smoke_failure_output_never_includes_exception_text() -> None:
    output = smoke._safe_failure(RuntimeError("api-key-secret-must-not-appear"))

    assert output == {"passed": False, "error_code": "RuntimeError"}
    assert "secret" not in json.dumps(output)


def test_off_drill_requires_v1_without_a_research_workflow_and_cancels_it() -> None:
    client = _OffClient()

    result = smoke._verify_off_fallback(client)

    assert result == {
        "fallback_run_id": "run_off_fallback",
        "orchestration_version": "v1",
        "orchestration_mode": "off",
        "status": "cancelled",
    }
    assert client.calls == [
        ("POST", "/api/agent/runs"),
        ("POST", "/api/agent/runs/run_off_fallback/cancel"),
        ("GET", "/api/agent/runs/run_off_fallback/research"),
    ]
