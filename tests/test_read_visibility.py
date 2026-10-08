"""HTTP regressions for S0/T01 project and legacy memory read visibility.

Use real routers and an isolated SQLite store; authentication is overridden so
these tests exercise authorization without sessions, Providers, or workers.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentmesh.models import MemoryItem, MemoryStatus, Project, Scope, Team, TeamMembership, User, UserRole
from agentmesh.routes import memory as memory_routes
from agentmesh.routes import workspace as workspace_routes
from agentmesh.routes.deps import current_user
from agentmesh.store import SQLiteStore


@dataclass
class VisibilityCase:
    db: SQLiteStore
    db_path: Path
    client: TestClient
    users: dict[str, User]
    projects: dict[str, Project]
    memories: dict[str, MemoryItem]

    def sign_in(self, user_id: str) -> None:
        self.client.app.dependency_overrides[current_user] = lambda: self.users[user_id]


@pytest.fixture
def visibility_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[VisibilityCase]:
    db_path = tmp_path / "read-visibility.sqlite3"
    db = SQLiteStore(db_path=db_path)
    users = {
        user_id: User(
            id=user_id,
            name=user_id,
            role=role,
            workspace_id="ws_visibility",
            default_project_id="project_shared",
            personal_agent_id=f"agent_{user_id}",
        )
        for user_id, role in (
            ("alice", UserRole.USER),
            ("bob", UserRole.USER),
            ("lead", UserRole.TEAM_LEAD),
            ("admin", UserRole.ADMIN),
        )
    }
    for user in users.values():
        db._upsert("users", user)
    projects = {
        "shared": Project(
            id="project_shared", workspace_id="ws_visibility", name="Shared", goal="Shared work",
            member_ids=list(users),
        ),
        "restricted": Project(
            id="project_restricted", workspace_id="ws_visibility", name="Restricted", goal="Restricted work",
            member_ids=["bob"],
        ),
        "legacy": Project(
            id="project_legacy", workspace_id="ws_visibility", name="Legacy", goal="Legacy work", member_ids=[],
        ),
        "foreign": Project(
            id="project_foreign", workspace_id="ws_other", name="Foreign", goal="Other workspace",
            member_ids=["alice", "lead", "admin"],
        ),
    }
    for project in projects.values():
        db.save_project(project)
    for team_id, user_id in (("team_a", "alice"), ("team_b", "bob")):
        db._upsert("teams", Team(id=team_id, workspace_id="ws_visibility", name=team_id))
        db._upsert("team_memberships", TeamMembership(team_id=team_id, user_id=user_id))
    memories: dict[str, MemoryItem] = {}
    for name, scope, owner, team_id in (
        ("team_a", Scope.TEAM_ACCEPTED, "alice", "team_a"),
        ("team_b", Scope.TEAM_ACCEPTED, "bob", "team_b"),
        ("workspace", Scope.TEAM_ACCEPTED, "bob", None),
        ("private_a", Scope.PRIVATE, "alice", None),
        ("private_b", Scope.PRIVATE, "bob", None),
        ("candidate_a", Scope.TEAM_CANDIDATE, "alice", "team_a"),
        ("candidate_b", Scope.TEAM_CANDIDATE, "bob", "team_b"),
        ("project", Scope.PROJECT, "bob", None),
    ):
        item = MemoryItem(
            id=f"memory_{name}", title=name, summary=f"Content for {name}", memory_type="note",
            scope=scope, owner_user_id=owner, team_id=team_id,
            status=MemoryStatus.PROPOSED if scope == Scope.TEAM_CANDIDATE else MemoryStatus.ACCEPTED,
            workspace_id="ws_visibility", project_id="project_shared",
        )
        memories[name] = db.add_memory_item(item)
    app = FastAPI()
    app.include_router(workspace_routes.router)
    app.include_router(memory_routes.router)
    monkeypatch.setattr(workspace_routes, "store", db)
    monkeypatch.setattr(memory_routes, "store", db)
    with TestClient(app) as client:
        case = VisibilityCase(db, db_path, client, users, projects, memories)
        case.sign_in("alice")
        yield case
    app.dependency_overrides.clear()


def _memory_ids(case: VisibilityCase, endpoint: str) -> set[str]:
    response = case.client.get(endpoint, params={"project_id": "project_shared"})
    assert response.status_code == 200, response.text
    payload = response.json()
    items = payload["sections"]["team"] if endpoint.endswith("/overview") else payload["items"]
    if endpoint.endswith("/overview"):
        assert payload["counts"]["team"] == len(items)
    return {item["id"] for item in items}


@pytest.mark.parametrize("user_id", ["alice", "lead", "admin"])
@pytest.mark.parametrize("explicit_workspace", [False, True])
def test_projects_list_only_accessible_projects(
    visibility_case: VisibilityCase, user_id: str, explicit_workspace: bool,
) -> None:
    case = visibility_case
    case.sign_in(user_id)
    params = {"workspace_id": "ws_visibility"} if explicit_workspace else {}
    response = case.client.get("/api/projects", params=params)
    assert response.status_code == 200, response.text
    assert {item["id"] for item in response.json()["items"]} == {"project_shared", "project_legacy"}


@pytest.mark.parametrize("user_id", ["alice", "lead", "admin"])
@pytest.mark.parametrize("project_key", ["restricted", "foreign"])
def test_project_detail_uses_existing_read_model_gate(
    visibility_case: VisibilityCase, user_id: str, project_key: str,
) -> None:
    case = visibility_case
    case.sign_in(user_id)
    project_id = case.projects[project_key].id
    reference = case.client.get("/api/activity/today", params={"project_id": project_id})
    detail = case.client.get(f"/api/projects/{project_id}")
    assert reference.status_code == 404
    assert detail.status_code == reference.status_code
    assert detail.json() == reference.json()


@pytest.mark.parametrize("user_id", ["alice", "lead", "admin"])
@pytest.mark.parametrize("project_key", ["shared", "legacy"])
def test_members_and_legacy_projects_remain_readable(
    visibility_case: VisibilityCase, user_id: str, project_key: str,
) -> None:
    case = visibility_case
    case.sign_in(user_id)
    project = case.projects[project_key]
    response = case.client.get(f"/api/projects/{project.id}")
    assert response.status_code == 200, response.text
    assert response.json()["item"]["id"] == project.id


@pytest.mark.parametrize("workspace_id", ["ws_other", "ws_missing"])
def test_project_listing_rejects_other_workspace_filters(
    visibility_case: VisibilityCase, workspace_id: str,
) -> None:
    response = visibility_case.client.get("/api/projects", params={"workspace_id": workspace_id})
    assert response.status_code == 404
    assert response.json() == {"detail": "Workspace not found"}


def test_missing_project_is_hidden(visibility_case: VisibilityCase) -> None:
    response = visibility_case.client.get("/api/projects/project_missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


@pytest.mark.parametrize("endpoint", ["/api/memory", "/api/memory/overview"])
@pytest.mark.parametrize("user_id", ["alice", "bob", "lead", "admin"])
def test_legacy_memory_reads_match_canonical_visibility(
    visibility_case: VisibilityCase, endpoint: str, user_id: str,
) -> None:
    case = visibility_case
    case.sign_in(user_id)
    expected = {
        item.id for item in case.memories.values()
        if case.db.memory_item_visible_to_user(item, user_id)
        and (not endpoint.endswith("/overview") or item.scope in {Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED})
    }
    actual = _memory_ids(case, endpoint)
    assert actual == expected
    if user_id == "alice":
        assert case.memories["team_a"].id in actual
        assert case.memories["workspace"].id in actual
        assert case.memories["team_b"].id not in actual
        assert case.memories["candidate_b"].id not in actual
    if user_id in {"lead", "admin"}:
        assert {case.memories["team_a"].id, case.memories["team_b"].id} <= actual
        assert case.memories["private_a"].id not in actual
        assert case.memories["private_b"].id not in actual


@pytest.mark.parametrize("endpoint", ["/api/memory", "/api/memory/overview"])
def test_memory_reads_do_not_widen_project_or_workspace_scope(
    visibility_case: VisibilityCase, endpoint: str,
) -> None:
    case = visibility_case
    for name, updates in (
        ("foreign_workspace", {"workspace_id": "ws_other"}),
        ("other_project", {"project_id": "project_restricted"}),
    ):
        item = case.memories["workspace"].model_copy(update={"id": name, **updates})
        case.db.add_memory_item(item)
    assert not {"foreign_workspace", "other_project"} & _memory_ids(case, endpoint)


@pytest.mark.parametrize("endpoint", ["/api/memory", "/api/memory/overview"])
def test_team_membership_changes_apply_on_next_read(
    visibility_case: VisibilityCase, endpoint: str,
) -> None:
    case = visibility_case
    restricted_id = case.memories["team_b"].id
    assert restricted_id not in _memory_ids(case, endpoint)
    membership = TeamMembership(team_id="team_b", user_id="alice")
    case.db._upsert("team_memberships", membership)
    assert restricted_id in _memory_ids(case, endpoint)
    case.db._upsert("team_memberships", membership.model_copy(update={"user_id": "bob"}))
    assert restricted_id not in _memory_ids(case, endpoint)


def test_project_revocation_survives_store_reopen(
    visibility_case: VisibilityCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = visibility_case
    project = case.projects["shared"].model_copy(update={"member_ids": ["bob"]})
    case.db.save_project(project)
    reopened = SQLiteStore(db_path=case.db_path)
    monkeypatch.setattr(workspace_routes, "store", reopened)
    monkeypatch.setattr(memory_routes, "store", reopened)
    assert case.client.get("/api/projects/project_shared").status_code == 404
    for endpoint in ("/api/memory", "/api/memory/overview"):
        response = case.client.get(endpoint, params={"project_id": "project_shared"})
        assert response.status_code == 404
    listed = case.client.get("/api/projects")
    assert listed.status_code == 200
    assert "project_shared" not in {item["id"] for item in listed.json()["items"]}
