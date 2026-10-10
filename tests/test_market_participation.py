from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.agents import PersonalAgent
from agentmesh.app import app
from agentmesh.marketplace import publish_all_signals, scout_all
from agentmesh.models import (
    BlackboardPost,
    BlackboardPostType,
    MemoryLayer,
    Scope,
    UserMemoryItem,
)
from agentmesh.seed import PROJECT, TEAM_LEAD, USER, WORKSPACE, ensure_seed_data
from agentmesh.store import store


def _reset() -> None:
    store.reset()
    ensure_seed_data(store)


def _add_memory(user_id: str, title: str, summary: str) -> None:
    store.add_user_memory_item(
        UserMemoryItem(
            user_id=user_id, layer=MemoryLayer.MID_TERM, title=title, summary=summary,
            source_kind="promotion", memory_type="decision",
            workspace_id=WORKSPACE.id, project_id=PROJECT.id,
        )
    )


def _signal_for(owner_id: str, need: str) -> None:
    store.add_blackboard_post(
        BlackboardPost(
            id=f"bb_signal_{owner_id}", task_id=f"signal_{owner_id}",
            post_type=BlackboardPostType.MARKETPLACE_SIGNAL, actor=PersonalAgent.actor,
            title="信号", content=f"能力：大促降级预案\n可提供：答疑\n需要：{need}",
            scope=Scope.PROJECT, permission="project_visible",
            metadata={"workspace_id": WORKSPACE.id, "project_id": PROJECT.id},
        )
    )


def test_users_are_not_participants_by_default() -> None:
    _reset()
    assert store.is_market_participant(USER.id) is False


def test_setting_participation_toggles_it() -> None:
    _reset()
    store.set_market_participation(USER.id, True)
    assert store.is_market_participant(USER.id) is True
    store.set_market_participation(USER.id, False)
    assert store.is_market_participant(USER.id) is False


def test_publish_only_runs_for_participants() -> None:
    _reset()
    _add_memory(USER.id, "大促降级预案", "核心链路保底。")
    _add_memory(TEAM_LEAD.id, "前端会场改版", "首屏进行中。")
    store.set_market_participation(USER.id, True)  # only USER opts in

    published = publish_all_signals(store)

    signals = [p for p in store.blackboard_posts if p.post_type == BlackboardPostType.MARKETPLACE_SIGNAL]
    assert published == 1
    assert len(signals) == 1
    assert signals[0].task_id == f"signal_{USER.id}"


def test_scout_only_runs_for_participants() -> None:
    _reset()
    _add_memory(USER.id, "大促降级预案 v3", "核心链路保底。")  # USER can help
    _signal_for(TEAM_LEAD.id, "大促降级预案怎么做")  # TEAM_LEAD needs help
    # USER has NOT opted in → its scout must not act
    assert scout_all(store) == 0

    store.set_market_participation(USER.id, True)
    assert scout_all(store) >= 1


def test_participation_api_opt_in(monkeypatch) -> None:
    _reset()
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"})
    assert login.status_code == 200

    resp = client.put("/api/market/participation", json={"enabled": True})

    assert resp.status_code == 200
    assert store.is_market_participant(USER.id) is True


def test_publisher_scans_participants_in_bounded_pages_across_restart() -> None:
    from agentmesh.store import SQLiteStore

    _reset()
    for user in (USER, TEAM_LEAD):
        _add_memory(user.id, "大促降级预案", "核心链路保底。")
        store.set_market_participation(user.id, True)
    assert publish_all_signals(store, page_size=1) == 1
    assert len([post for post in store.blackboard_posts if post.post_type == "marketplace_signal"]) == 1
    reopened = SQLiteStore(store.db_path)
    assert publish_all_signals(reopened, page_size=1) == 1
    assert len([post for post in reopened.blackboard_posts if post.post_type == "marketplace_signal"]) == 2
