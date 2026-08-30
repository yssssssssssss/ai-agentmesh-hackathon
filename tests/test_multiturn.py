"""Tests for multi-turn conversation context."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentmesh.app import app
from agentmesh.models import ChatMessage, ChatRole
from agentmesh.seed import USER
from agentmesh.store import store


def clear_store() -> None:
    store.reset()


def authenticated_client() -> TestClient:
    client = TestClient(app)
    client.post("/api/auth/login", json={"user_id": USER.id, "password": "designer123"})
    return client


class TestMultiTurnContext:
    def test_second_message_has_history_available(self):
        """第二条消息时，系统能访问第一条消息作为历史。"""
        clear_store()
        client = authenticated_client()

        # 第一条消息 -> 创建 thread
        r1 = client.post("/api/chat/messages", json={"content": "我们去年做了618家电首页改版"})
        assert r1.status_code == 200
        thread_id = r1.json()["thread_id"]

        # 第二条消息 -> 复用 thread
        r2 = client.post("/api/chat/messages", json={"content": "那个项目的转化率怎么样？", "thread_id": thread_id})
        assert r2.status_code == 200
        assert r2.json()["thread_id"] == thread_id

        # 验证 thread 中有 4 条消息（2 user + 2 assistant）
        messages = store.list_thread_messages(thread_id)
        assert len(messages) == 4
        assert messages[0].role == ChatRole.USER
        assert messages[1].role == ChatRole.ASSISTANT
        assert messages[2].role == ChatRole.USER
        assert messages[3].role == ChatRole.ASSISTANT

    def test_history_respects_max_messages(self):
        """历史消息不超过 MAX_HISTORY_MESSAGES 条。"""
        clear_store()
        from agentmesh.agents import PersonalAgent

        thread_id = "thread_history_limit"
        for i in range(13):
            store.add_chat_message(ChatMessage(thread_id=thread_id, role=ChatRole.USER, content=f"第{i + 1}条用户消息"))
            store.add_chat_message(
                ChatMessage(thread_id=thread_id, role=ChatRole.ASSISTANT, content=f"第{i + 1}条助理消息")
            )

        history = PersonalAgent(store)._get_thread_history(thread_id)

        assert len(store.list_thread_messages(thread_id)) == 26
        assert len(history) == PersonalAgent.MAX_HISTORY_MESSAGES

    def test_recent_history_uses_sql_limit_and_complete_utf8_message_boundaries(self):
        clear_store()
        thread_id = "thread_recent_history_limit"
        for index in range(8):
            store.add_chat_message(
                ChatMessage(
                    thread_id=thread_id,
                    role=ChatRole.USER,
                    content=f"message-{index}-" + ("界" * 20),
                )
            )

        recent = store.list_recent_thread_messages(
            thread_id,
            limit=6,
            max_content_bytes=200,
        )

        assert [message.content.split("-")[1] for message in recent] == ["6", "7"]
        assert sum(len(message.content.encode("utf-8")) for message in recent) <= 200

    def test_history_included_in_llm_prompt(self):
        """验证 _llm_prompt 正确包含历史。"""
        from agentmesh.agents import PersonalAgent
        from agentmesh.models import Intent

        history = [
            ChatMessage(thread_id="t1", role=ChatRole.USER, content="去年618数据怎么样？"),
            ChatMessage(thread_id="t1", role=ChatRole.ASSISTANT, content="去年618转化率提升了15%。"),
        ]

        prompt = PersonalAgent._llm_prompt(
            fallback_content="默认回答",
            user_content="那今年的目标呢？",
            intent=Intent.ASK_MEMORY,
            evidence_post=None,
            risk_post=None,
            inbox_items=[],
            memory_items=[],
            history=history,
        )

        assert "对话历史" in prompt
        assert "去年618数据怎么样？" in prompt
        assert "去年618转化率提升了15%" in prompt
        assert "那今年的目标呢？" in prompt

    def test_empty_history_produces_no_history_section(self):
        """无历史时 prompt 中不包含对话历史段落。"""
        from agentmesh.agents import PersonalAgent
        from agentmesh.models import Intent

        prompt = PersonalAgent._llm_prompt(
            fallback_content="默认回答",
            user_content="你好",
            intent=Intent.ASK_MEMORY,
            evidence_post=None,
            risk_post=None,
            inbox_items=[],
            memory_items=[],
            history=[],
        )

        assert "对话历史（最近" not in prompt
