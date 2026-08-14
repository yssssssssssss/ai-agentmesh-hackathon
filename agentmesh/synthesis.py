from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from agentmesh.llm import LLMClient, LLMRequestError, llm_chat_timeout_seconds
from agentmesh.model_registry import resolve_agent_model_id
from agentmesh.models import BlackboardPost, ChatMessage, ChatRole, InboxItem, Intent, MemoryItem, Source, User
from agentmesh.store import SQLiteStore


class ChatLLM(Protocol):
    def complete(self, system_prompt: str, user_prompt: str) -> str: ...


@dataclass(frozen=True)
class SynthesisResult:
    content: str
    llm_used: bool
    fallback_reason: str | None = None


def synthesize_with_llm(
    repository: SQLiteStore,
    llm_client: ChatLLM | None,
    fallback_content: str,
    user_content: str,
    intent: Intent,
    evidence_post: BlackboardPost | None,
    risk_post: BlackboardPost | None,
    inbox_items: list[InboxItem],
    memory_items: list[MemoryItem],
    user: User,
    history: list[ChatMessage] | None = None,
) -> str:
    return synthesize_with_llm_result(
        repository=repository,
        llm_client=llm_client,
        fallback_content=fallback_content,
        user_content=user_content,
        intent=intent,
        evidence_post=evidence_post,
        risk_post=risk_post,
        inbox_items=inbox_items,
        memory_items=memory_items,
        user=user,
        history=history,
    ).content


def synthesize_with_llm_result(
    repository: SQLiteStore,
    llm_client: ChatLLM | None,
    fallback_content: str,
    user_content: str,
    intent: Intent,
    evidence_post: BlackboardPost | None,
    risk_post: BlackboardPost | None,
    inbox_items: list[InboxItem],
    memory_items: list[MemoryItem],
    user: User,
    history: list[ChatMessage] | None = None,
) -> SynthesisResult:
    client = chat_llm_client(repository, user, llm_client)
    if client is None:
        return SynthesisResult(content=fallback_content, llm_used=False, fallback_reason="llm_not_configured")
    try:
        generated = client.complete(
            system_prompt=(
                "你是 AgentMesh 团队大脑的中文助理。"
                "只基于给定上下文回答，不编造来源。"
                "记忆证据中的引用标记必须在对应结论后逐字保留。"
                "如果有收件箱或记忆库动作，用一句话说明已放入对应位置。"
                "回答要简洁、可执行。"
            ),
            user_prompt=build_llm_prompt(
                fallback_content=fallback_content,
                user_content=user_content,
                intent=intent,
                evidence_post=evidence_post,
                risk_post=risk_post,
                inbox_items=inbox_items,
                memory_items=memory_items,
                history=history,
            ),
        )
    except LLMRequestError as error:
        return SynthesisResult(content=fallback_content, llm_used=False, fallback_reason=error.reason)
    except Exception:
        return SynthesisResult(content=fallback_content, llm_used=False, fallback_reason="llm_error")
    if not generated:
        return SynthesisResult(content=fallback_content, llm_used=False, fallback_reason="empty_response")
    if intent == Intent.ASK_MEMORY and evidence_post is not None:
        citation_markers = re.findall(r"\[(?:P|J|T)\d+\]", evidence_post.content)
        if citation_markers and not any(marker in generated for marker in citation_markers):
            return SynthesisResult(
                content=fallback_content,
                llm_used=False,
                fallback_reason="missing_citation_markers",
            )
    return SynthesisResult(content=generated, llm_used=True)


def chat_llm_client(
    repository: SQLiteStore,
    user: User,
    llm_client: ChatLLM | None = None,
    timeout_seconds: float | None = None,
) -> ChatLLM | None:
    if llm_client is not None:
        return llm_client
    return LLMClient.from_model_id(
        resolve_agent_model_id(repository, user),
        timeout_seconds=timeout_seconds if timeout_seconds is not None else llm_chat_timeout_seconds(),
    )


def build_llm_prompt(
    fallback_content: str,
    user_content: str,
    intent: Intent,
    evidence_post: BlackboardPost | None,
    risk_post: BlackboardPost | None,
    inbox_items: list[InboxItem],
    memory_items: list[MemoryItem],
    history: list[ChatMessage] | None = None,
) -> str:
    evidence = evidence_post.content if evidence_post else "无"
    risk = risk_post.content if risk_post else "无"
    inbox_titles = "、".join(item.title for item in inbox_items) or "无"
    memory_titles = "、".join(item.title for item in memory_items) or "无"

    history_section = ""
    if history:
        history_lines = []
        for msg in history:
            role_label = "用户" if msg.role == ChatRole.USER else "助理"
            history_lines.append(f"[{role_label}] {msg.content}")
        history_section = f"对话历史（最近 {len(history)} 条）：\n" + "\n".join(history_lines) + "\n"
    citation_instruction = (
        "记忆检索回答必须保留证据中的 [P1]、[J1]、[T1] 等引用标记，"
        "并把标记放在其支持的结论后。\n"
        if intent == Intent.ASK_MEMORY
        else ""
    )

    return (
        f"{history_section}"
        f"用户输入：{user_content}\n"
        f"调用工作流：{intent.value}\n"
        f"证据：{evidence}\n"
        f"风险：{risk}\n"
        f"来源：{source_titles(evidence_post, risk_post)}\n"
        f"收件箱事项：{inbox_titles}\n"
        f"候选记忆：{memory_titles}\n"
        f"当前默认回答：{fallback_content}\n"
        f"{citation_instruction}"
        "请基于对话历史和当前上下文生成最终回复。"
    )


def assistant_sources(evidence_post: BlackboardPost | None, risk_post: BlackboardPost | None) -> list[Source]:
    if evidence_post:
        return evidence_post.sources
    if risk_post:
        return risk_post.sources
    return []


def source_titles(evidence_post: BlackboardPost | None, risk_post: BlackboardPost | None) -> str:
    sources = assistant_sources(evidence_post, risk_post)
    return "、".join(source.title for source in sources) or "无"


def evidence_answer(evidence_post: BlackboardPost | None, intent: Intent, user_content: str) -> str:
    if not evidence_post:
        return "我会先在你的个人上下文和团队记忆中查找相关信息。"
    titles = "、".join(source.title for source in evidence_post.sources) or "无"
    prefix = ""
    if intent == Intent.ASK_MEMORY:
        prefix = "相关记忆："
    elif intent == Intent.REQUEST_EXTERNAL_RESEARCH:
        lowered = user_content.lower()
        prefix = "竞品资料和历史项目经验：" if "竞品" in lowered else "相似历史项目经验："
    return f"{prefix}{evidence_post.content} 来源：{titles}。"
