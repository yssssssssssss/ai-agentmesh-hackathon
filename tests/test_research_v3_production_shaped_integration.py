from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agentmesh.research_orchestration.v3.api import (
    ResearchV3OwnerScope,
    create_research_v3_router,
)
from agentmesh.research_orchestration.v3.repository_projector import ResearchV3RepositoryProjector
from agentmesh.research_orchestration.v3.sqlite_repository import SQLiteResearchV3Repository

NOW = datetime(2026, 8, 21, 8, 45, tzinfo=UTC)
RUN_ID = "run_integration"
OWNER = ResearchV3OwnerScope(
    user_id="owner_integration",
    workspace_id="workspace_integration",
    project_id="project_integration",
)


class _NoMutationWorkflow:
    def __init__(self) -> None:
        self.calls = 0

    def apply(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("pure API reads must not invoke the mutation workflow")


async def _owner_provider(request: Request) -> ResearchV3OwnerScope:
    return ResearchV3OwnerScope(
        user_id=request.headers.get("X-Test-User", OWNER.user_id),
        workspace_id=OWNER.workspace_id,
        project_id=OWNER.project_id,
    )


def test_isolated_router_reads_authoritative_scoped_sqlite_projection(tmp_path) -> None:
    repository = SQLiteResearchV3Repository(
        tmp_path / "research-v3-integration.sqlite3",
        owner_id=OWNER.user_id,
        workspace_id=OWNER.workspace_id,
        project_id=OWNER.project_id,
        clock=lambda: NOW,
    )
    repository.initialize_schema()
    repository.create_run(RUN_ID)
    workflow = _NoMutationWorkflow()
    app = FastAPI()
    app.include_router(
        create_research_v3_router(
            workflow=workflow,
            projector=ResearchV3RepositoryProjector(repository, clock=lambda: NOW),
            owner_provider=_owner_provider,
        )
    )
    client = TestClient(app)

    try:
        visible = client.get(f"/api/agent/runs/{RUN_ID}/research")
        hidden = client.get(
            f"/api/agent/runs/{RUN_ID}/research",
            headers={"X-Test-User": "owner_foreign"},
        )
    finally:
        repository.close()

    assert visible.status_code == 200
    assert visible.json()["run_id"] == RUN_ID
    assert visible.json()["workflow"] == {
        "state": "idle",
        "state_version": 0,
        "gate": {"kind": "none", "status": "inactive", "required_role": None},
    }
    assert visible.json()["provenance"]["source_kind"] == "repository_projection"
    assert hidden.status_code == 404
    assert hidden.json() == {"detail": "Research run not found"}
    assert workflow.calls == 0
