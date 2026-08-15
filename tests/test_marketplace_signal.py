from __future__ import annotations

from agentmesh.agents import PersonalAgent
from agentmesh.models import (
    BlackboardPostType,
    ChatThread,
    Intent,
    MemoryLayer,
    Scope,
    Task,
    TaskStatus,
    UserMemoryItem,
)
from agentmesh.seed import PROJECT, USER, WORKSPACE, ensure_seed_data
from agentmesh.store import store


def _reset() -> PersonalAgent:
    store.reset()
    ensure_seed_data(store)
    return PersonalAgent(store, llm_client=None)


def _add_memory(title: str, summary: str, user_id: str = USER.id) -> None:
    store.add_user_memory_item(
        UserMemoryItem(
            user_id=user_id,
            layer=MemoryLayer.MID_TERM,
            title=title,
            summary=summary,
            source_kind="promotion",
            memory_type="decision",
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )
    )


def _signal_posts() -> list:
    return [p for p in store.blackboard_posts if p.post_type == BlackboardPostType.MARKETPLACE_SIGNAL]


class _StubLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.reply


def test_publishes_marketplace_signal_from_user_memory() -> None:
    agent = _reset()
    _add_memory("大促降级预案", "核心链路保底、按 QPS 阶梯降级。")

    post = agent.publish_marketplace_signal(USER)

    assert post is not None
    assert post.post_type == BlackboardPostType.MARKETPLACE_SIGNAL
    assert post.scope == Scope.PROJECT
    assert post.actor == PersonalAgent.actor
    # signal is non-task (synthetic id) and persisted
    assert post.task_id == f"signal_{USER.id}"
    assert any(p.id == post.id for p in _signal_posts())


def test_no_source_material_is_skipped() -> None:
    agent = _reset()  # user has no memory

    post = agent.publish_marketplace_signal(USER)

    assert post is None
    assert _signal_posts() == []


def test_republish_refreshes_instead_of_duplicating() -> None:
    agent = _reset()
    _add_memory("大促降级预案", "核心链路保底。")

    agent.publish_marketplace_signal(USER)
    agent.publish_marketplace_signal(USER)

    mine = [p for p in _signal_posts() if p.task_id == f"signal_{USER.id}"]
    assert len(mine) == 1


def test_publish_is_audited() -> None:
    agent = _reset()
    _add_memory("大促降级预案", "核心链路保底。")

    agent.publish_marketplace_signal(USER)

    assert any(e.action == "publish_marketplace_signal" for e in store.audit_events)


def test_llm_generated_signal_content_is_used() -> None:
    store.reset()
    ensure_seed_data(store)
    agent = PersonalAgent(store, llm_client=_StubLLM("能力：稳定性\n可提供：降级预案答疑\n需要：前端埋点支持"))
    _add_memory("大促降级预案", "核心链路保底。")

    post = agent.publish_marketplace_signal(USER)

    assert post is not None
    assert "前端埋点支持" in post.content


def test_offline_fallback_still_produces_a_signal() -> None:
    agent = _reset()  # llm_client=None
    _add_memory("大促降级预案", "核心链路保底、按 QPS 阶梯降级。")

    post = agent.publish_marketplace_signal(USER)

    assert post is not None
    assert post.content  # body-free-of-LLM template, non-empty


def test_signal_can_be_built_from_tasks_alone() -> None:
    agent = _reset()  # no memory
    thread = store.add_chat_thread(
        ChatThread(workspace_id=WORKSPACE.id, project_id=PROJECT.id, user_id=USER.id, title="降级预案讨论")
    )
    store.add_task(
        Task(thread_id=thread.id, intent=Intent.ASK_MEMORY, title="查询大促降级经验", status=TaskStatus.COMPLETED)
    )

    post = agent.publish_marketplace_signal(USER)

    assert post is not None  # tasks alone are enough source material


def test_publish_all_signals_step_counts_users_with_material() -> None:
    from agentmesh.marketplace import publish_all_signals

    store.reset()
    ensure_seed_data(store)
    _add_memory("大促降级预案", "核心链路保底。", user_id=USER.id)  # only USER has material
    store.set_market_participation(USER.id, True)  # and opts into the market

    published = publish_all_signals(store)

    assert published == 1
    assert len(_signal_posts()) == 1


def test_market_llm_timeout_is_long_by_default() -> None:
    from agentmesh.llm import llm_chat_timeout_seconds, market_llm_timeout_seconds

    # interactive chat is now generous too (real answers, no fast-fail to fallback)
    assert llm_chat_timeout_seconds() >= 15
    # market background calls stay strictly longer than the interactive-chat budget
    assert market_llm_timeout_seconds() >= 15
    assert market_llm_timeout_seconds() > llm_chat_timeout_seconds()


def test_publish_resolves_llm_with_the_market_timeout(monkeypatch) -> None:
    import agentmesh.agents as agents_mod
    from agentmesh.llm import market_llm_timeout_seconds

    agent = _reset()
    _add_memory("大促降级预案", "核心链路保底。", user_id=USER.id)

    captured: dict[str, float | None] = {}

    class _Client:
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            return "能力：X\n可提供：Y\n需要：Z"

    def fake_chat_llm_client(repository, user, llm_client=None, timeout_seconds=None):
        captured["timeout"] = timeout_seconds
        return _Client()

    monkeypatch.setattr(agents_mod, "chat_llm_client", fake_chat_llm_client)
    agent.publish_marketplace_signal(USER)

    assert captured["timeout"] == market_llm_timeout_seconds()


