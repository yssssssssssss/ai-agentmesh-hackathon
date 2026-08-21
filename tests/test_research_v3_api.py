from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentmesh.research_orchestration.v3.api import (
    ResearchV3AggregateReadRequest,
    ResearchV3ConflictError,
    ResearchV3ExecuteRequest,
    ResearchV3MutationReceipt,
    ResearchV3NotFoundError,
    ResearchV3OwnerScope,
    create_research_v3_router,
    research_v3_request_hash,
)
from agentmesh.research_orchestration.v3.canonical import strict_json_v3_loads
from agentmesh.research_orchestration.v3.web_projection import ResearchV3WorkbenchAggregateV1

FIXTURE_PATH = Path("tests/fixtures/research_v3_workbench/idle.json")
OWNER = ResearchV3OwnerScope(user_id="user_owner", workspace_id="workspace_default", project_id="project_default")
RUN_ID = "run_1"


def _repository_aggregate() -> ResearchV3WorkbenchAggregateV1:
    body = strict_json_v3_loads(FIXTURE_PATH.read_bytes())
    body["provenance"] = {
        **body["provenance"],
        "source_kind": "repository_projection",
        "baseline_state_id": None,
    }
    return ResearchV3WorkbenchAggregateV1.model_validate(body)


class _AuthoritativeProjectorFake:
    def __init__(self, value: object | None = None) -> None:
        self.value = value if value is not None else _repository_aggregate()
        self.calls: list[ResearchV3AggregateReadRequest] = []

    def project_authoritative(self, request: ResearchV3AggregateReadRequest) -> object:
        self.calls.append(request)
        if request.run_id != RUN_ID or request.owner != OWNER:
            raise ResearchV3NotFoundError
        return self.value


class _IdempotentWorkflowFake:
    def __init__(self) -> None:
        self.state_versions = {RUN_ID: 0}
        self.receipts: dict[tuple[str, str], ResearchV3MutationReceipt] = {}
        self.apply_calls = 0
        self.scheduled_commands = 0

    def apply(self, run_id, command_type, request, *, owner, idempotency_key):  # noqa: ANN001, ANN201
        if run_id != RUN_ID or owner != OWNER:
            raise ResearchV3NotFoundError
        key = (run_id, idempotency_key)
        previous = self.receipts.get(key)
        if previous is not None:
            if previous.command_type != command_type or previous.request_hash != request.request_hash:
                raise ResearchV3ConflictError("idempotency key was used for a different command")
            return previous.model_copy(update={"replayed": True})
        if request.expected_state_version != self.state_versions[run_id]:
            raise ResearchV3ConflictError("research-v3 state version conflict")
        self.apply_calls += 1
        self.scheduled_commands += int(command_type == "execute")
        receipt = ResearchV3MutationReceipt(
            run_id=run_id,
            command_type=command_type,
            idempotency_key=idempotency_key,
            request_hash=request.request_hash,
            previous_state_version=request.expected_state_version,
            state_version=request.expected_state_version + 1,
            replayed=False,
            purged_artifact_count=0 if command_type == "purge" else None,
        )
        self.receipts[key] = receipt
        self.state_versions[run_id] = receipt.state_version
        return receipt


async def _owner_provider(request: Request) -> ResearchV3OwnerScope:
    return ResearchV3OwnerScope(
        user_id=request.headers.get("X-Test-User", "user_owner"),
        workspace_id="workspace_default",
        project_id="project_default",
    )


def _isolated_client(
    *,
    workflow: _IdempotentWorkflowFake | None = None,
    projector: _AuthoritativeProjectorFake | None = None,
) -> tuple[TestClient, _IdempotentWorkflowFake, _AuthoritativeProjectorFake]:
    workflow = workflow or _IdempotentWorkflowFake()
    projector = projector or _AuthoritativeProjectorFake()
    isolated_app = FastAPI()
    isolated_app.include_router(
        create_research_v3_router(
            workflow=workflow,
            projector=projector,
            owner_provider=_owner_provider,
        )
    )
    return TestClient(isolated_app), workflow, projector


def _execute_body(expected_state_version: int = 0) -> dict[str, object]:
    draft = ResearchV3ExecuteRequest(
        expected_state_version=expected_state_version,
        request_hash="0" * 64,
        plan_version_id="plan_1",
    )
    body = draft.model_copy(
        update={"request_hash": research_v3_request_hash("execute", RUN_ID, draft)}
    )
    return body.model_dump(mode="json")


def test_router_factory_is_not_mounted_by_the_production_application() -> None:
    from agentmesh.app import app as production_app

    assert not any(
        getattr(route, "name", "").startswith("research_v3_")
        for route in production_app.routes
    )


def test_owner_scope_is_hidden_as_not_found_for_reads_and_mutations() -> None:
    client, _workflow, _projector = _isolated_client()

    read = client.get(
        f"/api/agent/runs/{RUN_ID}/research",
        headers={"X-Test-User": "user_other"},
    )
    mutate = client.post(
        f"/api/agent/runs/{RUN_ID}/research/execute",
        headers={"X-Test-User": "user_other", "Idempotency-Key": "execute.owner.hidden"},
        json=_execute_body(),
    )

    assert read.status_code == 404
    assert mutate.status_code == 404
    assert read.json() == {"detail": "Research run not found"}
    assert mutate.json() == {"detail": "Research run not found"}


def test_state_version_and_request_hash_conflicts_are_409() -> None:
    client, _workflow, _projector = _isolated_client()
    wrong_hash = _execute_body()
    wrong_hash["request_hash"] = "f" * 64

    hash_conflict = client.post(
        f"/api/agent/runs/{RUN_ID}/research/execute",
        headers={"Idempotency-Key": "execute.bad.hash"},
        json=wrong_hash,
    )
    version_conflict = client.post(
        f"/api/agent/runs/{RUN_ID}/research/execute",
        headers={"Idempotency-Key": "execute.bad.version"},
        json=_execute_body(expected_state_version=4),
    )

    assert hash_conflict.status_code == 409
    assert hash_conflict.json()["detail"] == "request_hash does not match the canonical research-v3 command"
    assert version_conflict.status_code == 409
    assert version_conflict.json()["detail"] == "research-v3 state version conflict"


def test_mutation_replays_idempotently_without_rescheduling() -> None:
    client, workflow, _projector = _isolated_client()
    headers = {"Idempotency-Key": "execute.idempotent.1"}
    body = _execute_body()

    first = client.post(f"/api/agent/runs/{RUN_ID}/research/execute", headers=headers, json=body)
    replay = client.post(f"/api/agent/runs/{RUN_ID}/research/execute", headers=headers, json=body)

    assert first.status_code == replay.status_code == 202
    assert first.json() == {
        "run_id": RUN_ID,
        "command_type": "execute",
        "request_hash": body["request_hash"],
        "previous_state_version": 0,
        "state_version": 1,
        "accepted": True,
        "replayed": False,
    }
    assert replay.json() == {**first.json(), "replayed": True}
    assert workflow.apply_calls == 1
    assert workflow.scheduled_commands == 1


def test_get_refresh_and_plan_sse_are_projection_only_reads() -> None:
    client, workflow, projector = _isolated_client()

    read = client.get(f"/api/agent/runs/{RUN_ID}/research")
    refresh = client.get(f"/api/agent/runs/{RUN_ID}/research/refresh")
    stream = client.get(f"/api/agent/runs/{RUN_ID}/research/plan/stream?after_state_version=0")

    expected = _repository_aggregate().model_dump(mode="json")
    assert read.status_code == refresh.status_code == stream.status_code == 200
    assert read.json() == refresh.json() == expected
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: projection" in stream.text
    assert '"schema_version":"research-v3-plan-stream-result-v1"' in stream.text
    assert workflow.apply_calls == 0
    assert workflow.scheduled_commands == 0
    assert len(projector.calls) == 3


def test_projection_boundary_requires_exact_authoritative_repository_aggregate() -> None:
    exact_client, _workflow, _projector = _isolated_client()
    exact = exact_client.get(f"/api/agent/runs/{RUN_ID}/research")
    assert exact.status_code == 200
    assert exact.json() == _repository_aggregate().model_dump(mode="json")

    with_extra = _repository_aggregate().model_dump(mode="python")
    with_extra["ambient_fixture_state"] = {"must": "not be consulted"}
    invalid_client, _workflow, _projector = _isolated_client(
        projector=_AuthoritativeProjectorFake(with_extra)
    )
    invalid = invalid_client.get(f"/api/agent/runs/{RUN_ID}/research")
    assert invalid.status_code == 409
    assert invalid.json()["detail"] == "repository projection failed exact aggregate validation"

    fixture_projection = deepcopy(strict_json_v3_loads(FIXTURE_PATH.read_bytes()))
    fixture_client, _workflow, _projector = _isolated_client(
        projector=_AuthoritativeProjectorFake(fixture_projection)
    )
    rejected_fixture = fixture_client.get(f"/api/agent/runs/{RUN_ID}/research")
    assert rejected_fixture.status_code == 409
    assert "authoritative repository projection" in rejected_fixture.json()["detail"]
