from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.app import app


def test_agent_run_mutation_is_rejected_before_json_parsing_over_64_kib() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/agent/runs",
        content=b"x" * (64 * 1024 + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "request_body_too_large"}}


def test_task_mutation_is_rejected_before_json_parsing_over_64_kib() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/tasks",
        content=b"x" * (64 * 1024 + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "request_body_too_large"}}


def test_task_review_decision_is_rejected_before_json_parsing_over_64_kib() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/task-reviews/review-missing/decisions",
        content=b"x" * (64 * 1024 + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "request_body_too_large"}}


def test_deepsearch_clarification_has_a_16_kib_wire_limit() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/agent/runs/missing/deepsearch/clarify",
        content=b"x" * (16 * 1024 + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": {"code": "deepsearch_clarification_payload_too_large"}
    }
