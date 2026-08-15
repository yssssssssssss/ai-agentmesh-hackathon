from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentmesh.models import (
    AuditEvent,
    BlackboardPost,
    BlackboardPostType,
    Scope,
)
from agentmesh.seed import USER
from agentmesh.store import store
from tests.test_chat_flow import authenticated_client, clear_store


def _seed_signal(user_id: str, need: str, created_at: datetime | None = None) -> None:
    store.add_blackboard_post(
        BlackboardPost(
            id=f"bb_signal_{user_id}",
            task_id=f"signal_{user_id}",
            post_type=BlackboardPostType.MARKETPLACE_SIGNAL,
            actor="agent_personal",
            title=f"{user_id} signal",
            content=f"能力：设计\n可提供：设计经验\n需要：{need}",
            scope=Scope.PROJECT,
            permission="project_visible",
            created_at=created_at or datetime.now(UTC),
        )
    )


def _seed_match(
    *,
    helper: str,
    needer: str,
    status: str,
    at: datetime | None = None,
    need: str = "指标口径",
) -> None:
    store._upsert(
        "audit_events",
        AuditEvent(
            id=f"audit_match_{helper}_{needer}_{status}",
            actor=helper,
            action="marketplace_match",
            target_type="user",
            target_id=needer,
            metadata={"helper": helper, "status": status, "need": need},
            created_at=at or datetime.now(UTC),
        ),
    )


def test_activity_empty_when_no_events() -> None:
    """Scenario: no signals, no matches → empty feed."""
    clear_store()
    client = authenticated_client()

    response = client.get("/api/market/activity")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []


def test_activity_merges_signals_and_matches() -> None:
    """Scenario: both kinds present → both appear with composed text."""
    clear_store()
    client = authenticated_client()
    _seed_signal("usr_team_lead", need="大促指标口径")
    _seed_match(helper="usr_team_lead", needer=USER.id, status="answered", need="大促指标")

    response = client.get("/api/market/activity")

    assert response.status_code == 200
    items = response.json()["items"]
    kinds = {item["kind"] for item in items}
    assert kinds == {"signal", "match"}
    for item in items:
        assert item["text"], "each item must carry composed text"


def test_activity_flags_items_involving_me() -> None:
    """Scenario: involves_me is true only for events touching the current user."""
    clear_store()
    client = authenticated_client()
    _seed_match(helper="usr_team_lead", needer=USER.id, status="answered", need="A")
    _seed_match(helper="usr_admin", needer="usr_team_lead", status="answered", need="B")

    response = client.get("/api/market/activity")

    assert response.status_code == 200
    items = response.json()["items"]
    mine = [item for item in items if item["involves_me"]]
    others = [item for item in items if not item["involves_me"]]
    assert len(mine) == 1
    assert len(others) == 1
    assert mine[0]["topic"] == "A"


def test_activity_composes_all_three_match_states() -> None:
    """Scenario: answered / awaiting_confirm / denied each get distinct wording."""
    clear_store()
    client = authenticated_client()
    _seed_match(helper="usr_team_lead", needer=USER.id, status="answered", need="A")
    _seed_match(helper="usr_admin", needer=USER.id, status="awaiting_confirm", need="B")
    _seed_match(helper="usr_team_lead", needer="usr_admin", status="denied", need="C")

    response = client.get("/api/market/activity")

    assert response.status_code == 200
    matches = [item for item in response.json()["items"] if item["kind"] == "match"]
    by_status = {item["status"]: item["text"] for item in matches}
    assert "解答了" in by_status["answered"]
    assert "等待确认" in by_status["awaiting_confirm"]
    assert "婉拒" in by_status["denied"]


def test_activity_sorted_newest_first() -> None:
    """Scenario: mixed timestamps → feed is newest-first."""
    clear_store()
    client = authenticated_client()
    now = datetime.now(UTC)
    _seed_match(
        helper="usr_team_lead", needer=USER.id, status="answered",
        at=now - timedelta(minutes=30), need="旧",
    )
    _seed_signal("usr_admin", need="新", created_at=now - timedelta(minutes=1))

    response = client.get("/api/market/activity")

    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["topic"] == "新"
    assert items[1]["topic"] == "旧"
