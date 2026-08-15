from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentmesh.models import (
    AuditEvent,
    BlackboardPost,
    BlackboardPostType,
    MemoryLayer,
    Scope,
    UserMemoryItem,
)
from agentmesh.seed import USER
from agentmesh.store import store
from tests.test_chat_flow import authenticated_client, clear_store


def _seed_memory(user_id: str, workspace_id: str, count: int) -> None:
    for i in range(count):
        store.add_user_memory_item(
            UserMemoryItem(
                id=f"umem_test_{user_id}_{i}",
                user_id=user_id,
                layer=MemoryLayer.SHORT_TERM,
                title=f"记忆 {i}",
                summary=f"summary {i}",
                source_kind="test",
                workspace_id=workspace_id,
                scope=Scope.PRIVATE,
            )
        )


def _seed_signal(user_id: str, need: str, created_at: datetime | None = None) -> BlackboardPost:
    post = BlackboardPost(
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
    store.add_blackboard_post(post)
    return post


def _seed_match(
    *,
    helper: str,
    needer: str,
    status: str,
    at: datetime | None = None,
    need: str = "指标口径",
) -> AuditEvent:
    event = AuditEvent(
        id=f"audit_match_{helper}_{needer}_{status}",
        actor=helper,
        action="marketplace_match",
        target_type="user",
        target_id=needer,
        metadata={"helper": helper, "status": status, "need": need},
        created_at=at or datetime.now(UTC),
    )
    store._upsert("audit_events", event)
    return event


def test_market_me_happy_path_has_all_sources() -> None:
    """Scenario: all three sources populated → view returns aggregated data."""
    clear_store()
    client = authenticated_client()

    store.set_market_participation(USER.id, True)
    store.set_market_participation("usr_team_lead", True)
    _seed_memory(USER.id, USER.workspace_id, 3)
    _seed_signal(USER.id, need="大促核心指标口径")
    _seed_match(helper="usr_team_lead", needer=USER.id, status="answered", need="大促指标")
    _seed_match(helper=USER.id, needer="usr_team_lead", status="answered", need="预算流程")

    response = client.get("/api/market/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == USER.id
    assert payload["presence"]["memory_count"] == 3
    assert payload["presence"]["signal_on"] is True
    assert payload["presence"]["received_count"] == 1
    assert payload["presence"]["given_count"] == 1
    assert isinstance(payload["graph"]["nodes"], list) and len(payload["graph"]["nodes"]) >= 1
    me_node = next(n for n in payload["graph"]["nodes"] if n["id"] == USER.id)
    assert me_node["tie_role"] == "me"
    directions = {edge["direction"] for edge in payload["graph"]["edges"]}
    assert directions == {"incoming", "outgoing"}
    categories = [item["category"] for item in payload["timeline"]]
    assert set(categories) == {"request", "incoming", "outgoing"}


def test_market_me_empty_user_has_zero_activity() -> None:
    """Scenario: no memory, no signal, no matches → presence counts are zero."""
    clear_store()
    client = authenticated_client()

    response = client.get("/api/market/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["presence"]["memory_count"] == 0
    assert payload["presence"]["signal_on"] is False
    assert payload["presence"]["received_count"] == 0
    assert payload["presence"]["given_count"] == 0
    assert payload["timeline"] == []


def test_market_me_denied_and_awaiting_are_kept_but_not_others() -> None:
    """Scenario: incoming events map status faithfully for the three UI states."""
    clear_store()
    client = authenticated_client()
    store.set_market_participation(USER.id, True)

    _seed_match(helper="usr_team_lead", needer=USER.id, status="answered", need="A")
    _seed_match(helper="usr_admin", needer=USER.id, status="awaiting_confirm", need="B")
    _seed_match(helper="usr_team_lead", needer=USER.id, status="denied", need="C")
    _seed_match(helper="usr_admin", needer=USER.id, status="unexpected_value", need="D")

    response = client.get("/api/market/me")

    assert response.status_code == 200
    payload = response.json()
    incoming = [item for item in payload["timeline"] if item["category"] == "incoming"]
    assert len(incoming) == 4
    statuses = {item["status"] for item in incoming}
    assert "answered" in statuses
    assert "awaiting_confirm" in statuses
    assert "denied" in statuses
    assert payload["presence"]["received_count"] == 4


def test_market_me_awaiting_counts_as_received() -> None:
    """Scenario: awaiting_confirm is a received match (not silently filtered)."""
    clear_store()
    client = authenticated_client()
    store.set_market_participation(USER.id, True)

    _seed_match(helper="usr_team_lead", needer=USER.id, status="awaiting_confirm")

    response = client.get("/api/market/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["presence"]["received_count"] == 1
    row = next(item for item in payload["timeline"] if item["category"] == "incoming")
    assert row["status"] == "awaiting_confirm"


def test_market_me_timeline_is_sorted_desc() -> None:
    """Scenario: multiple events with different timestamps → newest first."""
    clear_store()
    client = authenticated_client()
    store.set_market_participation(USER.id, True)
    now = datetime.now(UTC)

    _seed_match(
        helper="usr_team_lead", needer=USER.id, status="answered",
        at=now - timedelta(minutes=10), need="旧的",
    )
    _seed_match(
        helper=USER.id, needer="usr_admin", status="answered",
        at=now - timedelta(minutes=1), need="新的",
    )

    response = client.get("/api/market/me")

    assert response.status_code == 200
    payload = response.json()
    ordered = [item["topic"] for item in payload["timeline"] if item["category"] != "request"]
    assert ordered[0] == "新的"
    assert ordered[1] == "旧的"
