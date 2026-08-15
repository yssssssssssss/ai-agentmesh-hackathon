from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import NoReturn

from agentmesh.acquisition import (
    AcquisitionAgent,
    AcquisitionRequest,
    AcquisitionResult,
    MockAcquisitionAgent,
)
from agentmesh.brief_templates import BriefTemplate, select_brief_template
from agentmesh.chat_skills import ChatSkillInvocation, list_chat_skills, parse_chat_skill_invocation, spec_for_intent
from agentmesh.llm import LLMRequestError, market_llm_timeout_seconds
from agentmesh.model_registry import resolve_agent_model_id
from agentmesh.models import (
    ActivityLog,
    AnswerConfidence,
    AuditEvent,
    BlackboardPost,
    BlackboardPostType,
    ChatMessage,
    ChatResponse,
    ChatRole,
    ChatThread,
    ChatTurnTrace,
    ChatWorkflowTrace,
    CollaborationStage,
    ConsentGrant,
    ContributionPoint,
    DelegatedAnswer,
    DelegatedAnswerStatus,
    DocumentRecord,
    InboxItem,
    Intent,
    MemoryItem,
    MemoryKind,
    MemoryLayer,
    MemoryRelation,
    MemorySearchScope,
    MemorySearchTrace,
    RetrievalMetrics,
    RetrievedMemoryEvidence,
    Scope,
    SearchResult,
    Source,
    Task,
    TaskStatus,
    User,
    UserMemoryItem,
    new_id,
    now_utc,
)
from agentmesh.provider_status import provider_metadata
from agentmesh.risk import RiskDecision, assess_external_content, assess_tool_request
from agentmesh.seed import PROJECT, USER, WORKSPACE
from agentmesh.service_agents import MockDataAgent, RiskAgent
from agentmesh.store import SQLiteStore
from agentmesh.synthesis import (
    ChatLLM,
    SynthesisResult,
    assistant_sources,
    build_llm_prompt,
    chat_llm_client,
    evidence_answer,
    llm_model_provenance,
    source_titles,
    synthesize_with_llm_result,
)

logger = logging.getLogger(__name__)


@dataclass
class _ChatTurnState:
    request_post: BlackboardPost | None = None
    evidence_post: BlackboardPost | None = None
    synthesis_evidence_post: BlackboardPost | None = None
    risk_post: BlackboardPost | None = None
    activity_logs: list[ActivityLog] = field(default_factory=list)
    inbox_items: list[InboxItem] = field(default_factory=list)
    memory_items: list[MemoryItem] = field(default_factory=list)
    user_memory_items: list[UserMemoryItem] = field(default_factory=list)
    pending_tool_approval: bool = False
    retrieval_metrics: RetrievalMetrics | None = None
    memory_search: MemorySearchTrace | None = None
    requested_provider: str | None = None
    actual_provider: str | None = None
    provider_mode: str | None = None
    provider_latency_ms: float | None = None
    provider_fallback_reason: str | None = None


class RequestAlreadyFulfilledError(RuntimeError):
    """Raised when a blackboard request post has already produced evidence."""



class ChatThreadNotFoundError(LookupError):
    """Raised when a chat thread is missing or not visible to the current user."""


@dataclass
class ResearchFulfillment:
    task: Task
    request_post: BlackboardPost
    evidence_post: BlackboardPost
    assistant_message: ChatMessage | None
    activity_logs: list[ActivityLog] = field(default_factory=list)
    inbox_items: list[InboxItem] = field(default_factory=list)
    quarantined: bool = False
    llm_used: bool = False


class PersonalAgent:
    actor = "personal_agent"
    MAX_HISTORY_MESSAGES = 10
    MAX_HISTORY_CHARS = 4000
    SEARCH_STOP_TERMS = {"查询", "搜索", "经验", "项目", "相关", "有没有", "是否", "什么", "资料"}

    def __init__(
        self,
        repository: SQLiteStore,
        llm_client: ChatLLM | None = None,
        acquisition_agent: AcquisitionAgent | None = None,
        data_agent: MockDataAgent | None = None,
    ):
        self.repository = repository
        self.acquisition_agent = acquisition_agent or MockAcquisitionAgent()
        self.data_agent = data_agent or MockDataAgent(repository=repository)
        if self.data_agent.repository is None:
            self.data_agent.repository = repository
        self.risk_agent = RiskAgent(repository)
        self.llm_client = llm_client

    def handle_chat(self, content: str, thread_id: str | None = None, user: User = USER) -> ChatResponse:
        actual_thread_id = thread_id or new_id("thread")
        self._ensure_thread(actual_thread_id, content, user, allow_create=thread_id is None)

        # Ownership is checked before any conversation context is loaded.
        history = self._get_thread_history(actual_thread_id)

        llm_client = chat_llm_client(self.repository, user, self.llm_client)
        invocation = parse_chat_skill_invocation(content)
        if invocation is None:
            classified_intent, classified_arg, confidence = self._classify_intent(content, history, llm_client)
            classified_spec = spec_for_intent(classified_intent)
            if classified_spec is not None:
                invocation = ChatSkillInvocation(
                    command=classified_spec.command,
                    argument=classified_arg,
                    spec=classified_spec,
                )
                return self._run_skill_invocation(
                    invocation, content, actual_thread_id, user, history,
                    intent_source="llm", confidence=confidence,
                )
            started = time.perf_counter()
            chat_result = self._general_chat_answer(content, user, history, llm_client)
            latency_ms = (time.perf_counter() - started) * 1000 if llm_client is not None else None
            return self._persist_private_chat_turn(
                content=content,
                assistant_content=chat_result.content,
                thread_id=actual_thread_id,
                user=user,
                selected_workflow="chat",
                source="chat",
                llm_used=chat_result.llm_used,
                requested_provider="llm" if llm_client is not None else "agentmesh",
                actual_provider="llm" if chat_result.llm_used else "local_fallback",
                provider_mode="real" if chat_result.llm_used else "fallback",
                latency_ms=latency_ms,
                fallback_reason=None,
                requested_model=chat_result.requested_model,
                actual_model=chat_result.actual_model,
                model_fallback_reason=chat_result.fallback_reason,
            )

        if invocation.spec is None:
            return self._persist_private_chat_turn(
                content=content,
                assistant_content=self._unknown_skill_answer(invocation),
                thread_id=actual_thread_id,
                user=user,
                selected_workflow=invocation.command or "$",
                source="skill",
                llm_used=False,
            )

        if invocation.spec.requires_input and not invocation.argument:
            return self._persist_private_chat_turn(
                content=content,
                assistant_content=f"请补充要处理的内容。用法：{invocation.spec.usage}",
                thread_id=actual_thread_id,
                user=user,
                selected_workflow=invocation.spec.command,
                source="skill",
                llm_used=False,
            )

        return self._run_skill_invocation(
            invocation, content, actual_thread_id, user, history,
            intent_source="skill", confidence=1.0,
        )

    _INTENT_CLASSIFIER_SYSTEM_PROMPT = (
        "你是一个意图分类器。根据用户的输入判断最匹配的意图标签。\n"
        "可用标签：\n"
        "- ASK_MEMORY — 查询团队经验、历史记录、知识库\n"
        "- GENERATE_BRIEF — 生成文档、Brief、方案\n"
        "- RECORD_PRIVATE_NOTE — 保存个人笔记、备忘\n"
        "- REQUEST_EXTERNAL_RESEARCH — 搜索外部资料、竞品、网页\n"
        "- REQUEST_DATA_QUERY — 查询数据指标（点击率、转化率等）\n"
        "- REQUEST_RISK_REVIEW — 风险检查、授权审核\n"
        "- CREATE_MEMORY_CANDIDATE — 提炼经验为团队记忆候选\n"
        "- GENERAL_CHAT — 普通对话、闲聊、不确定\n\n"
        "规则：\n"
        "1. 只选一个标签。不确定时选 GENERAL_CHAT。\n"
        "2. 只输出一行：标签|参数（参数为用户真正想查/做的核心内容）。\n"
        "3. 如果选 GENERAL_CHAT，参数留空。\n"
        "示例输出：ASK_MEMORY|618 家电会场首屏经验"
    )

    _INTENT_LABEL_MAP: dict[str, Intent] = {
        "ASK_MEMORY": Intent.ASK_MEMORY,
        "GENERATE_BRIEF": Intent.GENERATE_BRIEF,
        "RECORD_PRIVATE_NOTE": Intent.RECORD_PRIVATE_NOTE,
        "REQUEST_EXTERNAL_RESEARCH": Intent.REQUEST_EXTERNAL_RESEARCH,
        "REQUEST_DATA_QUERY": Intent.REQUEST_DATA_QUERY,
        "REQUEST_RISK_REVIEW": Intent.REQUEST_RISK_REVIEW,
        "CREATE_MEMORY_CANDIDATE": Intent.CREATE_MEMORY_CANDIDATE,
        "GENERAL_CHAT": Intent.GENERAL_CHAT,
    }

    def _classify_intent(
        self,
        content: str,
        history: list[ChatMessage],
        llm_client,
    ) -> tuple[Intent, str, float]:
        if llm_client is None:
            return Intent.GENERAL_CHAT, content, 0.0
        try:
            response = llm_client.complete(self._INTENT_CLASSIFIER_SYSTEM_PROMPT, content)
        except LLMRequestError:
            return Intent.GENERAL_CHAT, content, 0.0
        except Exception:
            return Intent.GENERAL_CHAT, content, 0.0
        line = response.strip().split("\n")[0].strip()
        if "|" in line:
            label, _, argument = line.partition("|")
        else:
            label = line
            argument = ""
        label = label.strip().upper()
        intent = self._INTENT_LABEL_MAP.get(label)
        if intent is None or intent == Intent.GENERAL_CHAT:
            return Intent.GENERAL_CHAT, content, 0.0
        return intent, argument.strip() or content, 0.85

    def _run_skill_invocation(
        self,
        invocation: ChatSkillInvocation,
        content: str,
        thread_id: str,
        user: User,
        history: list[ChatMessage],
        *,
        intent_source: str,
        confidence: float,
    ) -> ChatResponse:
        skill_content = invocation.argument or content
        intent = invocation.spec.intent
        workflow_trace = self._command_workflow_trace(
            intent, invocation.spec.command, persisted=True, source=intent_source, confidence=confidence,
        )

        thread = self._ensure_thread(thread_id, content, user)

        user_message = self.repository.add_chat_message(
            ChatMessage(
                thread_id=thread_id,
                role=ChatRole.USER,
                content=content,
                scope=Scope.PRIVATE,
            )
        )

        task = self.repository.add_task(
            Task(
                thread_id=thread_id,
                intent=intent,
                status=TaskStatus.RUNNING,
                title=self._task_title(intent),
                steps=["received_user_message", "parsed_skill_command"],
            )
        )
        self._audit(
            "create_task",
            "task",
            task.id,
            {"intent": intent, "intent_source": intent_source, "command": invocation.spec.command, "confidence": confidence},
        )

        state = _ChatTurnState()

        try:
            if intent == Intent.ASK_MEMORY:
                self._handle_memory_search(
                    task,
                    skill_content,
                    user,
                    state,
                    search_scope=invocation.spec.memory_search_scope or MemorySearchScope.AUTO,
                    workspace_id=thread.workspace_id,
                    project_id=thread.project_id,
                )

            if intent == Intent.REQUEST_DATA_QUERY:
                self._handle_data_query(task, skill_content, user, state)

            if intent in {
                Intent.GENERATE_BRIEF,
                Intent.REQUEST_EXTERNAL_RESEARCH,
                Intent.CREATE_MEMORY_CANDIDATE,
            }:
                self._handle_acquisition_intent(task, skill_content, intent, user, state)

            if intent == Intent.REQUEST_RISK_REVIEW:
                self._handle_risk_review(task, skill_content, state, user)
        except Exception as error:
            self._mark_task_failed(task, error)
            raise

        assistant_content = self._assistant_content_for_turn(intent, skill_content, state, user)
        strict_memory_scope = bool(
            state.memory_search
            and state.memory_search.requested_scope != MemorySearchScope.AUTO
        )
        strict_memory_miss = bool(strict_memory_scope and not state.memory_search.results)
        synthesis_latency_ms: float | None = None

        if (
            not strict_memory_miss
            and not state.pending_tool_approval
            and intent not in {Intent.ASK_SYSTEM_INFO, Intent.GENERATE_BRIEF}
        ):
            synthesis_started = time.perf_counter()
            synthesis = self._synthesize_with_llm(
                fallback_content=assistant_content,
                user_content=skill_content,
                intent=intent,
                evidence_post=state.synthesis_evidence_post,
                risk_post=state.risk_post,
                inbox_items=state.inbox_items,
                memory_items=state.memory_items,
                user=user,
                history=None if strict_memory_scope else history,
            )
            synthesis_latency_ms = (time.perf_counter() - synthesis_started) * 1000
            assistant_content = synthesis.content
            workflow_trace.llm_used = synthesis.llm_used
            workflow_trace.requested_model = synthesis.requested_model
            workflow_trace.actual_model = synthesis.actual_model
            workflow_trace.model_fallback_reason = synthesis.fallback_reason
            workflow_trace.fallback_reason = state.provider_fallback_reason

        self._apply_trace_provenance(workflow_trace, state, user, synthesis_latency_ms)
        if state.retrieval_metrics is not None:
            state.retrieval_metrics.llm_used = workflow_trace.llm_used if workflow_trace else False
            citation_labels = {
                result.citation_label: result.result_id
                for result in state.memory_search.results
            } if state.memory_search else None
            state.retrieval_metrics.source_ids_cited = self._find_cited_source_ids(
                assistant_content,
                state.retrieval_metrics.source_ids_returned,
                citation_labels,
            )
            state.retrieval_metrics.results_cited = len(state.retrieval_metrics.source_ids_cited)

        state.activity_logs.append(
            self._activity(title="处理了一条用户请求", summary=f"通过 {invocation.spec.command} 调用 {intent.value}，默认保留在个人上下文。", category="personal", scope=Scope.PRIVATE, user_id=user.id)
        )

        if task.status != TaskStatus.WAITING_EXTERNAL_AGENT:
            task.status = TaskStatus.COMPLETED
            task.collaboration_stage = CollaborationStage.COMPLETED
        else:
            task.collaboration_stage = CollaborationStage.BLOCKED
        task.updated_at = now_utc()
        task.steps.append("returned_chat_response")
        self.repository.save_task(task)

        assistant_message = self.repository.add_chat_message(
            ChatMessage(
                thread_id=thread_id,
                role=ChatRole.ASSISTANT,
                content=assistant_content,
                scope=Scope.PRIVATE,
                sources=self._assistant_sources(state.evidence_post, state.risk_post),
                workflow_trace=workflow_trace,
            )
        )
        self._audit("return_chat_response", "chat_message", assistant_message.id, {"task_id": task.id})
        if state.retrieval_metrics is not None:
            state.retrieval_metrics.assistant_message_id = assistant_message.id
            self.repository.add_retrieval_metrics(state.retrieval_metrics)
        turn_trace = self._persist_turn_trace(
            workflow_trace,
            thread_id=thread_id,
            user_message=user_message,
            assistant_message=assistant_message,
            task=task,
            memory_search=state.memory_search,
        )
        memory_item = self._record_short_term_memory(task, intent, skill_content, assistant_content, state, user)
        if memory_item is not None:
            state.user_memory_items.append(memory_item)
            self._try_extract_skills(user)

        return ChatResponse(
            thread_id=thread_id,
            user_message=user_message,
            assistant_message=assistant_message,
            task=task,
            request_post=state.request_post,
            evidence_post=state.evidence_post,
            risk_post=state.risk_post,
            activity_logs=state.activity_logs,
            inbox_items=state.inbox_items,
            memory_items=state.memory_items,
            user_memory_items=state.user_memory_items,
            workflow_trace=workflow_trace,
            turn_trace=turn_trace,
        )

    def _persist_private_chat_turn(
        self,
        content: str,
        assistant_content: str,
        thread_id: str,
        user: User,
        selected_workflow: str,
        source: str,
        llm_used: bool,
        requested_provider: str | None = None,
        actual_provider: str | None = None,
        requested_model: str | None = None,
        actual_model: str | None = None,
        provider_mode: str | None = None,
        latency_ms: float | None = None,
        fallback_reason: str | None = None,
        model_fallback_reason: str | None = None,
    ) -> ChatResponse:
        self._ensure_thread(thread_id, content, user)
        trace = ChatWorkflowTrace(
            intent=Intent.GENERAL_CHAT,
            confidence=1.0,
            source=source,
            selected_workflow=selected_workflow,
            persisted=True,
            llm_used=llm_used,
            requested_provider=requested_provider or "agentmesh",
            actual_provider=actual_provider or requested_provider or "agentmesh",
            requested_model=requested_model,
            actual_model=actual_model,
            provider_mode=provider_mode or (
                "fallback" if fallback_reason or (model_fallback_reason and not llm_used) else "real"
            ),
            latency_ms=latency_ms,
            fallback_reason=fallback_reason,
            model_fallback_reason=model_fallback_reason,
        )
        user_message = self.repository.add_chat_message(
            ChatMessage(thread_id=thread_id, role=ChatRole.USER, content=content, scope=Scope.PRIVATE)
        )
        assistant_message = self.repository.add_chat_message(
            ChatMessage(
                thread_id=thread_id,
                role=ChatRole.ASSISTANT,
                content=assistant_content,
                scope=Scope.PRIVATE,
                workflow_trace=trace,
            )
        )
        turn_trace = self._persist_turn_trace(
            trace,
            thread_id=thread_id,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        return ChatResponse(
            thread_id=thread_id,
            user_message=user_message,
            assistant_message=assistant_message,
            task=None,
            activity_logs=[],
            inbox_items=[],
            memory_items=[],
            user_memory_items=[],
            workflow_trace=trace,
            turn_trace=turn_trace,
        )

    def _persist_turn_trace(
        self,
        workflow_trace: ChatWorkflowTrace,
        *,
        thread_id: str,
        user_message: ChatMessage,
        assistant_message: ChatMessage,
        task: Task | None = None,
        memory_search: MemorySearchTrace | None = None,
    ) -> ChatTurnTrace:
        sources: list[Source] = []
        seen_source_ids: set[str] = set()
        for source in assistant_message.sources:
            if source.id in seen_source_ids:
                continue
            seen_source_ids.add(source.id)
            sources.append(source)

        trace = self.repository.add_chat_turn_trace(
            ChatTurnTrace(
                thread_id=thread_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                task_id=task.id if task is not None else None,
                intent=workflow_trace.intent,
                source=workflow_trace.source,
                selected_workflow=workflow_trace.selected_workflow,
                persisted=workflow_trace.persisted,
                llm_used=workflow_trace.llm_used,
                confidence=workflow_trace.confidence,
                requested_provider=workflow_trace.requested_provider,
                actual_provider=workflow_trace.actual_provider,
                requested_model=workflow_trace.requested_model,
                actual_model=workflow_trace.actual_model,
                provider_mode=workflow_trace.provider_mode,
                latency_ms=workflow_trace.latency_ms,
                fallback_reason=workflow_trace.fallback_reason,
                model_fallback_reason=workflow_trace.model_fallback_reason,
                steps=list(task.steps) if task is not None else [],
                sources=sources,
                memory_search=memory_search,
            )
        )
        thread = self.repository.get_chat_thread(thread_id)
        if thread is not None:
            thread.updated_at = now_utc()
            self.repository.save_chat_thread(thread)
        return trace

    @staticmethod
    def _unknown_skill_answer(invocation: ChatSkillInvocation) -> str:
        skills = "、".join(item["command"] for item in list_chat_skills())
        command = invocation.command or "$"
        return f"没有找到 {command} 这个能力。当前可用能力：{skills}。"

    def _mark_task_failed(self, task: Task, error: Exception) -> None:
        step = f"failed:{type(error).__name__}"
        if step not in task.steps:
            task.steps.append(step)
        task.status = TaskStatus.FAILED
        task.collaboration_stage = CollaborationStage.BLOCKED
        task.updated_at = now_utc()
        self.repository.save_task(task)
        self._audit("fail_task", "task", task.id, {"error": type(error).__name__})

    def _handle_data_query(self, task: Task, content: str, user: User, state: _ChatTurnState) -> None:
        state.request_post = self._create_request_post(
            task,
            content,
            title="查询项目指标数据",
            read_by_agents=["data_agent"],
            current_owner_agent_id="data_agent",
            current_owner_label="data_agent",
            done_when="data_agent 返回可引用指标数据",
        )
        task.steps.append("created_blackboard_request")
        state.evidence_post = self.data_agent.query(task, state.request_post, content, user)
        self._capture_provider_metadata(state, state.evidence_post.metadata)
        state.synthesis_evidence_post = state.evidence_post
        self._persist_sources(state.evidence_post.sources)
        self.repository.add_blackboard_post(state.evidence_post)
        task.steps.append("received_data_agent_evidence")
        state.activity_logs.append(
            self._activity(title="请求 data_agent 查询指标", summary="data_agent 已返回本地指标数据并写入 BBS。", category="external_agent", scope=Scope.PROJECT, user_id=user.id)
        )

    def _handle_memory_search(
        self,
        task: Task,
        content: str,
        user: User,
        state: _ChatTurnState,
        *,
        search_scope: MemorySearchScope = MemorySearchScope.AUTO,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        resolved_workspace_id = workspace_id or user.workspace_id
        resolved_project_id = project_id or user.default_project_id
        t0 = time.perf_counter()
        results = self._search_team_brain(
            content,
            user,
            search_scope=search_scope,
            workspace_id=resolved_workspace_id,
            project_id=resolved_project_id,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        state.requested_provider = "memory_index"
        state.actual_provider = "memory_index"
        state.provider_mode = "real"
        state.provider_latency_ms = float(latency_ms)

        source_ids = [result.id for result in results]
        state.retrieval_metrics = RetrievalMetrics(
            query_text=content[:200],
            user_id=user.id,
            results_returned=len(results),
            source_ids_returned=source_ids,
            latency_ms=latency_ms,
            requested_scope=search_scope,
            task_id=task.id,
            thread_id=task.thread_id,
        )
        state.memory_search = self._build_memory_search_trace(search_scope, results)

        if results:
            state.evidence_post = self._create_memory_search_evidence(task, state.memory_search.results)
            state.synthesis_evidence_post = state.evidence_post
            task.steps.append("searched_memory")
            state.activity_logs.append(
                self._activity(title="检索个人与团队记忆", summary=f"命中 {len(results)} 条个人、项目或团队记忆，未发起新的 BBS 求助。", category="personal", scope=Scope.PRIVATE, user_id=user.id)
            )
            return
        if search_scope != MemorySearchScope.AUTO:
            task.steps.append("searched_memory")
            state.activity_logs.append(
                self._activity(
                    title="检索指定范围记忆",
                    summary="指定记忆范围未命中，未跨范围检索或发起 BBS 求助。",
                    category="personal",
                    scope=Scope.PRIVATE,
                    user_id=user.id,
                )
            )
            return

        state.request_post = self._create_request_post(
            task,
            content,
            title="请求补充团队经验",
            read_by_agents=["research_agent", "data_agent"],
            current_owner_agent_id="research_agent",
            current_owner_label="research_agent",
            done_when="团队成员或服务 Agent 补充可引用经验",
        )
        task.status = TaskStatus.WAITING_EXTERNAL_AGENT
        task.steps.extend(["searched_memory", "created_blackboard_request"])
        state.activity_logs.append(
            self._activity(title="记忆未命中，转入 BBS 求助", summary="个人、项目和团队记忆中没有足够结果，已在项目 BBS 发帖等待补充。", category="external_agent", scope=Scope.PROJECT, user_id=user.id)
        )

    def _search_team_brain(
        self,
        query: str,
        user: User,
        *,
        search_scope: MemorySearchScope = MemorySearchScope.AUTO,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> list[SearchResult]:
        """Search only memory visible in the requested thread context."""
        effective_workspace_id = workspace_id or user.workspace_id
        effective_project_id = project_id or user.default_project_id

        if search_scope == MemorySearchScope.PERSONAL:
            allowed_record_ids = {
                item.id
                for item in self.repository.user_memory_items
                if item.user_id == user.id and item.workspace_id == effective_workspace_id
            }
            results = self.repository.search(
                query,
                {Scope.PRIVATE},
                workspace_id=effective_workspace_id,
                user_id=user.id,
                max_results=10,
                result_types={"user_memory_item"},
                allowed_record_ids=allowed_record_ids,
            )
            return [result for result in results if result.result_type == "user_memory_item"][:5]

        if search_scope == MemorySearchScope.PROJECT:
            if not effective_project_id:
                return []
            project = self.repository.get_project(effective_project_id)
            can_access_project = bool(
                project
                and project.workspace_id == effective_workspace_id
                and self.repository.user_can_access_project(user.id, effective_project_id)
            )
            allowed_record_ids = {
                item.id
                for item in self.repository.memory_items
                if can_access_project
                and item.workspace_id == effective_workspace_id
                and item.project_id == effective_project_id
                and item.scope == Scope.PROJECT
            }
            results = self.repository.search(
                query,
                {Scope.PROJECT},
                workspace_id=effective_workspace_id,
                project_id=effective_project_id,
                user_id=None,  # allowed_record_ids already enforces project access
                max_results=10,
                result_types={"memory_item"},
                allowed_record_ids=allowed_record_ids,
            )
            return [
                result
                for result in results
                if result.result_type == "memory_item" and result.scope == Scope.PROJECT
            ][:5]

        if search_scope == MemorySearchScope.TEAM:
            accessible_team_ids = {
                membership.team_id
                for membership in self.repository.list_team_memberships(user_id=user.id)
            }
            can_access_all_teams = user.role in {"admin", "team_lead"}
            allowed_record_ids = {
                item.id
                for item in self.repository.memory_items
                if item.workspace_id == effective_workspace_id
                and item.scope == Scope.TEAM_ACCEPTED
                and (
                    item.team_id is None
                    or can_access_all_teams
                    or item.team_id in accessible_team_ids
                )
            }
            results = self.repository.search(
                query,
                {Scope.TEAM_ACCEPTED},
                workspace_id=effective_workspace_id,
                user_id=None,  # allowed_record_ids already enforces team access
                max_results=10,
                result_types={"memory_item"},
                allowed_record_ids=allowed_record_ids,
            )
            return [
                result
                for result in results
                if result.result_type == "memory_item" and result.scope == Scope.TEAM_ACCEPTED
            ][:5]

        tier1_results = self.repository.search(
            query,
            {Scope.TEAM_ACCEPTED},
            workspace_id=effective_workspace_id,
            project_id=effective_project_id,
            user_id=user.id,
            max_results=5,
        )
        tier1_results = self._filter_memory_types(tier1_results)
        if len(tier1_results) >= 3:
            return tier1_results[:5]

        tier2_results = self.repository.search(
            query,
            {Scope.PROJECT, Scope.TEAM_ACCEPTED, Scope.TEAM_CANDIDATE},
            workspace_id=effective_workspace_id,
            project_id=effective_project_id,
            user_id=user.id,
            max_results=10,
        )
        tier2_results = self._filter_memory_types(tier2_results)
        if len(tier2_results) >= 3:
            return tier2_results[:5]

        tier3_results = self.repository.search(
            query,
            {Scope.PRIVATE, Scope.PROJECT, Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED},
            workspace_id=effective_workspace_id,
            project_id=effective_project_id,
            user_id=user.id,
            max_results=10,
        )
        tier3_results = self._filter_memory_types(tier3_results)
        if tier3_results:
            return tier3_results[:5]

        terms = self._search_terms(query)
        scored_results: list[tuple[int, SearchResult]] = []
        for result in self._memory_search_pool(user, effective_workspace_id, effective_project_id):
            text = f"{result.title} {result.summary}".lower()
            score = sum(1 for term in terms if term in text)
            if score >= 2:
                scored_results.append((score, result))
        scored_results.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [result for _, result in scored_results[:5]]

    @staticmethod
    def _filter_memory_types(results: list[SearchResult]) -> list[SearchResult]:
        return [
            r for r in results
            if r.result_type in {"user_memory_item", "memory_item", "document", "blackboard_evidence"}
        ]

    @staticmethod
    def _count_cited_sources(
        llm_output: str,
        source_ids: list[str],
        citation_labels: dict[str, str] | None = None,
    ) -> int:
        """Count returned result IDs referenced directly or through stable labels."""
        if not llm_output or not source_ids:
            return 0
        return len(PersonalAgent._find_cited_source_ids(llm_output, source_ids, citation_labels))

    @staticmethod
    def _find_cited_source_ids(
        llm_output: str,
        source_ids: list[str],
        citation_labels: dict[str, str] | None = None,
    ) -> list[str]:
        """Map direct IDs and stable citation labels back to returned result IDs."""
        if not llm_output:
            return []
        cited_by_label = {
            result_id
            for label, result_id in (citation_labels or {}).items()
            if f"[{label}]" in llm_output
        }
        return [
            source_id
            for source_id in source_ids
            if source_id in llm_output or source_id in cited_by_label
        ]

    def _memory_search_pool(
        self,
        user: User,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> list[SearchResult]:
        effective_workspace_id = workspace_id or user.workspace_id
        effective_project_id = project_id or user.default_project_id
        results: list[SearchResult] = []
        for item in self.repository.user_memory_items:
            if item.user_id != user.id or item.workspace_id != effective_workspace_id:
                continue
            if item.project_id != effective_project_id:
                continue
            results.append(
                SearchResult(
                    id=item.id,
                    result_type="user_memory_item",
                    title=item.title,
                    summary=item.summary,
                    scope=item.scope,
                    sources=item.sources,
                    project_id=item.project_id,
                    created_at=item.created_at,
                )
            )

        team_ids = {
            membership.team_id
            for membership in self.repository.list_team_memberships(user_id=user.id)
        }
        can_access_all_teams = user.role in {"admin", "team_lead"}
        for item in self.repository.memory_items:
            if not self.repository.memory_item_visible_to_user(item, user.id):
                continue
            if item.workspace_id != effective_workspace_id or item.project_id != effective_project_id:
                continue
            if item.scope == Scope.PROJECT and item.project_id != effective_project_id:
                continue
            if item.scope in {Scope.TEAM_ACCEPTED, Scope.TEAM_CANDIDATE}:
                if item.project_id != effective_project_id:
                    continue
                if item.team_id and not can_access_all_teams and item.team_id not in team_ids:
                    continue
            results.append(
                SearchResult(
                    id=item.id,
                    result_type="memory_item",
                    title=item.title,
                    summary=item.summary,
                    scope=item.scope,
                    sources=item.sources,
                    project_id=item.project_id,
                    team_id=item.team_id,
                    created_at=item.created_at,
                )
            )

        for document in self.repository.documents:
            if document.uploaded_by != user.id:
                continue
            if document.workspace_id != effective_workspace_id or document.project_id != effective_project_id:
                continue
            results.append(
                SearchResult(
                    id=document.id,
                    result_type="document",
                    title=document.title,
                    summary=document.text[:500],
                    scope=Scope.PRIVATE,
                    sources=[document.source],
                    project_id=document.project_id,
                    created_at=document.created_at,
                )
            )

        tasks_by_id = {task.id: task for task in self.repository.tasks}
        threads_by_id = {thread.id: thread for thread in self.repository.chat_threads}
        for post in self.repository.blackboard_posts:
            if post.scope not in {Scope.PROJECT, Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED}:
                continue
            if post.post_type not in {
                BlackboardPostType.EVIDENCE,
                BlackboardPostType.DECISION,
                BlackboardPostType.MEMORY_CANDIDATE,
                BlackboardPostType.ARCHIVE,
            }:
                continue
            task = tasks_by_id.get(post.task_id)
            thread = threads_by_id.get(task.thread_id) if task else None
            if (
                thread is None
                or thread.workspace_id != effective_workspace_id
                or thread.project_id != effective_project_id
            ):
                continue
            results.append(
                SearchResult(
                    id=post.id,
                    result_type=f"blackboard_{post.post_type.value}",
                    title=post.title,
                    summary=post.content,
                    scope=post.scope,
                    sources=post.sources,
                    project_id=thread.project_id,
                    created_at=post.created_at,
                )
            )
        return results

    @staticmethod
    def _memory_kind(result: SearchResult) -> MemoryKind:
        if result.result_type == "user_memory_item" or result.scope == Scope.PRIVATE:
            return MemoryKind.PERSONAL
        if result.scope == Scope.PROJECT:
            return MemoryKind.PROJECT
        return MemoryKind.TEAM

    @classmethod
    def _build_memory_search_trace(
        cls,
        requested_scope: MemorySearchScope,
        results: list[SearchResult],
    ) -> MemorySearchTrace:
        prefixes = {
            MemoryKind.PERSONAL: "P",
            MemoryKind.PROJECT: "J",
            MemoryKind.TEAM: "T",
        }
        kind_ranks = {kind: 0 for kind in MemoryKind}
        evidence: list[RetrievedMemoryEvidence] = []
        for rank, result in enumerate(results, start=1):
            memory_kind = cls._memory_kind(result)
            kind_ranks[memory_kind] += 1
            evidence.append(
                RetrievedMemoryEvidence(
                    result_id=result.id,
                    result_type=result.result_type,
                    memory_kind=memory_kind,
                    citation_label=f"{prefixes[memory_kind]}{kind_ranks[memory_kind]}",
                    title=result.title,
                    summary=result.summary,
                    rank=rank,
                    scope=result.scope,
                    project_id=result.project_id,
                    team_id=result.team_id,
                    sources=result.sources,
                )
            )
        return MemorySearchTrace(
            requested_scope=requested_scope,
            personal_count=kind_ranks[MemoryKind.PERSONAL],
            project_count=kind_ranks[MemoryKind.PROJECT],
            team_count=kind_ranks[MemoryKind.TEAM],
            results=evidence,
        )

    @staticmethod
    def _create_memory_search_evidence(
        task: Task,
        results: list[RetrievedMemoryEvidence],
    ) -> BlackboardPost:
        kind_labels = {
            MemoryKind.PERSONAL: "个人记忆",
            MemoryKind.PROJECT: "项目记忆",
            MemoryKind.TEAM: "团队记忆",
        }
        sources = [source for result in results for source in result.sources]
        lines = [
            f"[{result.citation_label}][{kind_labels[result.memory_kind]}] {result.title}：{result.summary}"
            for result in results
        ]
        return BlackboardPost(
            task_id=task.id,
            post_type=BlackboardPostType.EVIDENCE,
            actor="memory_search",
            title="个人、项目与团队记忆检索结果",
            content="\n".join(lines),
            scope=Scope.PRIVATE,
            permission="private_visible",
            sources=sources,
            read_by_agents=[PersonalAgent.actor],
            collaboration_stage=CollaborationStage.REVIEW,
            done_when="个人 Agent 基于记忆结果回答用户",
        )

    @staticmethod
    def _search_terms(query: str) -> list[str]:
        text = query.strip().lower()
        terms = set(re.findall(r"[a-z0-9]+", text))
        for part in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            terms.add(part)
            for size in (2, 3):
                terms.update(part[index : index + size] for index in range(0, len(part) - size + 1))
        return sorted(term for term in terms if len(term) >= 2 and term not in PersonalAgent.SEARCH_STOP_TERMS)

    def _handle_acquisition_intent(
        self,
        task: Task,
        content: str,
        intent: Intent,
        user: User,
        state: _ChatTurnState,
    ) -> None:
        state.request_post = self._create_request_post(task, content)
        task.steps.append("created_blackboard_request")
        tool_risk = assess_tool_request(content)
        if tool_risk.decision == RiskDecision.NEEDS_REVIEW:
            state.pending_tool_approval = True
            task.status = TaskStatus.WAITING_EXTERNAL_AGENT
            task.steps.append("requested_tool_call_approval")
            state.inbox_items.append(
                self._inbox(
                    title="审批高风险工具调用",
                    summary="该请求涉及批量抓取、批量下载、内网访问或自动写入等高风险动作，需要审批后再执行。",
                    item_type="tool_call_approval",
                    scope=Scope.PROJECT,
                    user_id=user.id,
                )
            )
            return

        acquisition_request = AcquisitionRequest(
            query=content,
            intent=intent,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            user_id=user.id,
            task_id=task.id,
            request_post_id=state.request_post.id,
        )
        acquisition_result = self._document_acquisition_result(acquisition_request)
        if acquisition_result is None:
            acquisition_result = self.acquisition_agent.acquire(acquisition_request)
        self._capture_provider_metadata(state, acquisition_result.metadata)
        state.evidence_post = self._create_evidence_post(task, state.request_post, acquisition_result)
        content_risk = assess_external_content(acquisition_result.content)
        if content_risk.decision == RiskDecision.NEEDS_REVIEW:
            state.evidence_post.status = "needs_review"
            task.steps.append("quarantined_acquisition_evidence")
            state.inbox_items.append(
                self._inbox(
                    title="审核可疑外部资料",
                    summary="外部资料包含疑似提示词注入内容，已隔离，暂不用于回答合成。",
                    item_type="prompt_injection_review",
                    scope=Scope.PROJECT,
                    user_id=user.id,
                )
            )
        else:
            state.synthesis_evidence_post = state.evidence_post
            task.steps.append("received_acquisition_evidence")
        self._persist_sources(state.evidence_post.sources)
        self.repository.add_blackboard_post(state.evidence_post)
        state.activity_logs.append(
            self._activity(title="请求外接 Agent 补充资料", summary=f"{state.evidence_post.actor} 已返回资料证据和来源。", category="external_agent", scope=Scope.PROJECT, user_id=user.id)
        )

    def _document_acquisition_result(self, request: AcquisitionRequest) -> AcquisitionResult | None:
        document_results = self._document_search_results(request)
        if not document_results:
            return None
        selected = document_results[:3]
        content = "\n".join(f"{item.title}：{item.summary}" for item in selected)
        sources: list[Source] = []
        for item in selected:
            sources.extend(item.sources)
        return AcquisitionResult(
            actor="document_agent",
            title="已检索上传文档",
            content=content,
            sources=sources,
            metadata={
                **provider_metadata(
                    requested_provider="documents",
                    actual_provider="documents",
                    mode="real",
                    latency_ms=0.0,
                ),
                "request_post_id": request.request_post_id,
            },
        )

    def _document_search_results(self, request: AcquisitionRequest):
        matches = self.repository.search(
            request.query,
            {Scope.PRIVATE},
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            user_id=request.user_id,
        )
        document_results = [item for item in matches if item.result_type in {"document", "user_memory_item"}]
        if document_results:
            return document_results

        query_tokens = [token.lower() for token in request.query.replace("，", " ").replace("。", " ").split()]
        if not query_tokens:
            return []
        fallback_results = []
        for document in self.repository.documents:
            if document.uploaded_by != request.user_id:
                continue
            if document.workspace_id != request.workspace_id or document.project_id != request.project_id:
                continue
            haystack = f"{document.title} {document.file_name} {document.text}".lower()
            if any(token and token in haystack for token in query_tokens):
                fallback_results.append(
                    type(
                        "DocumentSearchHit",
                        (),
                        {
                            "result_type": "document",
                            "title": document.title,
                            "summary": document.text[:500],
                            "sources": [document.source],
                        },
                    )()
                )
        return fallback_results

    def _handle_risk_review(self, task: Task, content: str, state: _ChatTurnState, user: User) -> None:
        state.request_post = self._create_request_post(
            task,
            content,
            title="检查素材和来源风险",
            read_by_agents=["risk_agent"],
            current_owner_agent_id="risk_agent",
            current_owner_label="risk_agent",
            done_when="risk_agent 返回策略规则评审结论",
        )
        state.risk_post = self.risk_agent.review(task, state.request_post)
        self._persist_sources(state.risk_post.sources)
        self.repository.add_blackboard_post(state.risk_post)
        task.steps.extend(["created_blackboard_request", "received_policy_risk_review"])
        state.activity_logs.append(
            self._activity(title="请求 risk_agent 检查风险", summary="risk_agent 已返回策略规则评审结论，并放入收件箱。", category="external_agent", scope=Scope.PROJECT, user_id=user.id)
        )

    def fulfill_research_request(self, request_post: BlackboardPost, user: User) -> ResearchFulfillment:
        """消费一条 waiting_external_agent 的 BBS 求助帖，产出 evidence 回帖并推进任务。

        让 research_agent 真正认领 ``_handle_memory_search`` 留下的 open request，
        通过 acquisition 边界补充证据；命中提示词注入则隔离转人工审核，否则把任务推回完成
        并向原对话线程追加一条带来源的回答。重复处置同一请求会抛 RequestAlreadyFulfilledError。
        """
        if request_post.post_type != BlackboardPostType.REQUEST:
            raise ValueError("Only request posts can be fulfilled by a research agent")

        already = next(
            (
                post
                for post in self.repository.blackboard_posts
                if post.related_post_id == request_post.id and post.post_type == BlackboardPostType.EVIDENCE
            ),
            None,
        )
        if already is not None:
            raise RequestAlreadyFulfilledError(request_post.id)

        task = self.repository.get_task(request_post.task_id)
        if task is None:
            raise ValueError("Request post has no backing task")
        thread = self.repository.get_chat_thread(task.thread_id)
        if thread is None or thread.user_id != user.id:
            raise ChatThreadNotFoundError(task.thread_id)

        activity_logs: list[ActivityLog] = []
        inbox_items: list[InboxItem] = []

        result = self.acquisition_agent.acquire(
            AcquisitionRequest(
                query=request_post.content,
                intent=task.intent,
                workspace_id=thread.workspace_id,
                project_id=thread.project_id,
                user_id=user.id,
                task_id=task.id,
                request_post_id=request_post.id,
            )
        )
        evidence_post = self._create_evidence_post(task, request_post, result)
        self._persist_sources(evidence_post.sources)

        content_risk = assess_external_content(result.content)
        if content_risk.decision == RiskDecision.NEEDS_REVIEW:
            evidence_post.status = "needs_review"
            evidence_post.collaboration_stage = CollaborationStage.BLOCKED
            self.repository.add_blackboard_post(evidence_post)
            inbox_items.append(
                self._inbox(
                    title="审核可疑外部资料",
                    summary="BBS 求助返回的外部资料包含疑似提示词注入内容，已隔离，暂不用于回答合成。",
                    item_type="prompt_injection_review",
                    scope=Scope.PROJECT,
                    user_id=user.id,
                    metadata={"request_post_id": request_post.id, "evidence_post_id": evidence_post.id},
                )
            )
            task.steps.append("quarantined_research_evidence")
            task.collaboration_stage = CollaborationStage.BLOCKED
            task.updated_at = now_utc()
            self.repository.save_task(task)
            activity_logs.append(
                self._activity(title="BBS 求助资料被隔离", summary=f"{evidence_post.actor} 返回的资料疑似含提示词注入，已隔离并转人工审核。", category="external_agent", scope=Scope.PROJECT, user_id=user.id)
            )
            self._audit(
                "fulfill_blackboard_request",
                "blackboard_post",
                request_post.id,
                {"task_id": task.id, "evidence_post_id": evidence_post.id, "quarantined": True},
            )
            return ResearchFulfillment(
                task=task,
                request_post=request_post,
                evidence_post=evidence_post,
                assistant_message=None,
                activity_logs=activity_logs,
                inbox_items=inbox_items,
                quarantined=True,
            )

        self.repository.add_blackboard_post(evidence_post)
        task.steps.append("received_blackboard_evidence")
        activity_logs.append(
            self._activity(title="BBS 求助得到补充", summary=f"{evidence_post.actor} 在项目 BBS 回帖补充了可引用证据。", category="external_agent", scope=Scope.PROJECT, user_id=user.id)
        )
        assistant_message, llm_used = self._finalize_research_evidence(task, request_post, evidence_post, user)
        self._audit(
            "fulfill_blackboard_request",
            "blackboard_post",
            request_post.id,
            {"task_id": task.id, "evidence_post_id": evidence_post.id, "quarantined": False},
        )
        return ResearchFulfillment(
            task=task,
            request_post=request_post,
            evidence_post=evidence_post,
            assistant_message=assistant_message,
            activity_logs=activity_logs,
            inbox_items=inbox_items,
            quarantined=False,
            llm_used=llm_used,
        )

    def _finalize_research_evidence(
        self,
        task: Task,
        request_post: BlackboardPost,
        evidence_post: BlackboardPost,
        user: User,
    ) -> tuple[ChatMessage, bool]:
        """把一条已采纳的 evidence 推进为最终回答:回填证据状态、完成任务并向原线程追加带源回复。"""
        evidence_post.status = "published"
        evidence_post.collaboration_stage = CollaborationStage.REVIEW
        self.repository.add_blackboard_post(evidence_post)

        request_post.collaboration_stage = CollaborationStage.REVIEW
        if evidence_post.actor not in request_post.read_by_agents:
            request_post.read_by_agents.append(evidence_post.actor)
        self.repository.add_blackboard_post(request_post)

        task.status = TaskStatus.COMPLETED
        task.collaboration_stage = CollaborationStage.COMPLETED
        task.updated_at = now_utc()
        self.repository.save_task(task)

        fallback = self._evidence_answer(evidence_post, task.intent, request_post.content)
        synthesis = self._synthesize_with_llm(
            fallback_content=fallback,
            user_content=request_post.content,
            intent=task.intent,
            evidence_post=evidence_post,
            risk_post=None,
            inbox_items=[],
            memory_items=[],
            user=user,
            history=self._get_thread_history(task.thread_id),
        )
        assistant_message = self.repository.add_chat_message(
            ChatMessage(
                thread_id=task.thread_id,
                role=ChatRole.ASSISTANT,
                content=synthesis.content,
                scope=Scope.PRIVATE,
                sources=self._assistant_sources(evidence_post, None),
            )
        )
        return assistant_message, synthesis.llm_used

    def resolve_quarantined_research(
        self,
        request_post: BlackboardPost,
        evidence_post: BlackboardPost,
        user: User,
        action: str,
    ) -> ResearchFulfillment:
        """人工对隔离的 BBS 求助资料做终态决定:release 放行补全闭环,discard 丢弃并终止任务。

        关闭了隔离分支永远停在 waiting_external_agent 的漏洞:误报放行后任务正常完成,
        真注入则丢弃证据并把任务标记为 failed,不再悬空。
        """
        if action not in {"release", "discard"}:
            raise ValueError("action must be 'release' or 'discard'")
        task = self.repository.get_task(request_post.task_id)
        if task is None:
            raise ValueError("Request post has no backing task")
        if evidence_post.status != "needs_review":
            raise RequestAlreadyFulfilledError(request_post.id)

        if action == "release":
            task.steps.append("released_quarantined_research_evidence")
            activity_logs = [
                self._activity(title="人工放行隔离资料", summary="审核确认外部资料安全，已放行用于回答合成并完成 BBS 求助。", category="external_agent", scope=Scope.PROJECT, user_id=user.id)
            ]
            assistant_message, llm_used = self._finalize_research_evidence(task, request_post, evidence_post, user)
            self._audit(
                "resolve_quarantined_research",
                "blackboard_post",
                request_post.id,
                {"task_id": task.id, "evidence_post_id": evidence_post.id, "action": "release"},
            )
            return ResearchFulfillment(
                task=task,
                request_post=request_post,
                evidence_post=evidence_post,
                assistant_message=assistant_message,
                activity_logs=activity_logs,
                inbox_items=[],
                quarantined=False,
                llm_used=llm_used,
            )

        evidence_post.status = "discarded"
        evidence_post.collaboration_stage = CollaborationStage.BLOCKED
        self.repository.add_blackboard_post(evidence_post)
        task.status = TaskStatus.FAILED
        task.collaboration_stage = CollaborationStage.BLOCKED
        task.steps.append("discarded_quarantined_research_evidence")
        task.updated_at = now_utc()
        self.repository.save_task(task)
        activity_logs = [
            self._activity(title="人工丢弃隔离资料", summary="审核确认外部资料存在风险，已丢弃证据并终止该 BBS 求助任务。", category="external_agent", scope=Scope.PROJECT, user_id=user.id)
        ]
        self._audit(
            "resolve_quarantined_research",
            "blackboard_post",
            request_post.id,
            {"task_id": task.id, "evidence_post_id": evidence_post.id, "action": "discard"},
        )
        return ResearchFulfillment(
            task=task,
            request_post=request_post,
            evidence_post=evidence_post,
            assistant_message=None,
            activity_logs=activity_logs,
            inbox_items=[],
            quarantined=True,
        )

    # ==== ④ Delegated-answer gateway (answer-only cross-person collaboration) ====

    DELEGATED_CONFIRM_ITEM_TYPE = "delegated_answer_confirmation"

    def grant_consent(self, grantor: User, grantee: User) -> ConsentGrant:
        """A (grantor) grants B (grantee) standing consent to query A's twin."""
        existing = self.repository.get_active_consent_grant(grantor.id, grantee.id)
        if existing is not None:
            return existing
        grant = ConsentGrant(
            grantor_id=grantor.id,
            grantee_id=grantee.id,
            workspace_id=grantor.workspace_id,
        )
        self.repository.add_consent_grant(grant)
        self._audit("grant_consent", "consent_grant", grant.id, {"grantor": grantor.id, "grantee": grantee.id})
        return grant

    def revoke_consent(self, grantor: User, grantee: User) -> None:
        """Prospective revocation: future queries fall back to the confirmation gate."""
        grant = self.repository.get_active_consent_grant(grantor.id, grantee.id)
        if grant is None:
            return
        grant.revoked_at = now_utc()
        self.repository.save_consent_grant(grant)
        self._audit("revoke_consent", "consent_grant", grant.id, {"grantor": grantor.id, "grantee": grantee.id})

    def answer_for_peer(self, asker: User, target: User, question: str) -> DelegatedAnswer:
        """B's twin asks A's twin. A answers strictly from A's own personal memory.

        Runs automatically only under a standing grant and when no high-sensitivity
        memory is matched; otherwise it halts on the confirmation gate (Inbox).
        Only the abstracted answer and citation titles cross back to the asker.
        """
        matched = self._match_target_memory(target, question)
        high_sensitivity = any(item.sensitivity == "high" for item in matched)
        has_consent = self.repository.get_active_consent_grant(target.id, asker.id) is not None

        if has_consent and not high_sensitivity:
            return self._answer_and_audit(target, question, matched, asker_id=asker.id, auto=True)

        reason = "high_sensitivity" if high_sensitivity else "no_standing_consent"
        inbox_item = self._inbox(
            title="确认代答请求",
            summary=f"{asker.name} 的分身请求由你的分身代答：「{self._truncate(question, 60)}」。",
            item_type=self.DELEGATED_CONFIRM_ITEM_TYPE,
            scope=Scope.PRIVATE,
            user_id=target.id,
            metadata={"asker_id": asker.id, "target_id": target.id, "question": question, "reason": reason},
        )
        self._audit(
            "delegated_answer_pending", "inbox_item", inbox_item.id,
            {"asker": asker.id, "target": target.id, "reason": reason},
        )
        return DelegatedAnswer(status=DelegatedAnswerStatus.AWAITING_CONFIRM, inbox_item=inbox_item)

    def resolve_delegated_answer(self, inbox_item: InboxItem, action: str) -> DelegatedAnswer:
        """A resolves a pending delegated query: approve → answer, deny → nothing."""
        if action not in {"approve", "deny"}:
            raise ValueError("action must be 'approve' or 'deny'")
        meta = inbox_item.metadata
        target = self.repository.get_user(meta["target_id"])
        if target is None:
            raise ValueError("delegated-answer inbox item has no target user")
        inbox_item.status = "resolved"
        inbox_item.resolved_at = now_utc()
        self.repository.save_inbox_item(inbox_item)

        if action == "deny":
            self._audit("delegated_answer_denied", "inbox_item", inbox_item.id, {"target": target.id})
            return DelegatedAnswer(status=DelegatedAnswerStatus.DENIED)

        question = meta.get("question", "")
        matched = self._match_target_memory(target, question)
        return self._answer_and_audit(target, question, matched, asker_id=meta.get("asker_id"), auto=False)

    def _answer_and_audit(
        self, target: User, question: str, matched: list[UserMemoryItem], *, asker_id: str | None, auto: bool
    ) -> DelegatedAnswer:
        result = self._synthesize_delegated_answer(target, question, matched)
        self._audit(
            "delegated_answer", "user", target.id,
            {"asker": asker_id, "auto": auto, "confidence": result.confidence.value},
        )
        return result

    def adopt_delegated_answer(
        self, asker: User, target: User, answer: DelegatedAnswer
    ) -> tuple[ContributionPoint, MemoryRelation]:
        """B adopts A's answer: record-only shadow point for A + a derived_from edge."""
        if not answer.citations:
            raise ValueError("cannot adopt a delegated answer that has no citations")
        citation = answer.citations[0]
        adopted = self.repository.add_user_memory_item(
            UserMemoryItem(
                user_id=asker.id,
                layer=MemoryLayer.SHORT_TERM,
                title=f"采纳自 {target.name} 的代答",
                summary=self._truncate(answer.answer or "", 240),
                source_kind="delegated_answer",
                memory_type="note",
                workspace_id=asker.workspace_id,
                project_id=asker.default_project_id,
                sources=list(answer.citations),
            )
        )
        point = self.repository.add_contribution_point(
            ContributionPoint(
                awarded_to_id=target.id,
                awarded_by_id=asker.id,
                reason="delegated_answer_adopted",
                redeemable=False,
                workspace_id=target.workspace_id,
            )
        )
        relation = self.repository.add_memory_relation(
            MemoryRelation(
                from_memory_id=adopted.id,
                to_source_id=citation.id,
                relation_type="derived_from",
            )
        )
        self._audit(
            "adopt_delegated_answer", "contribution_point", point.id,
            {"awarded_to": target.id, "by": asker.id, "relation": relation.id},
        )
        return point, relation

    def read_peer_memory_directly(self, asker: User, target: User) -> NoReturn:
        """No direct-read path exists — the gateway is the only route. Refuse + audit."""
        self._audit("refuse_direct_peer_memory_read", "user", target.id, {"asker": asker.id})
        raise PermissionError(
            f"Direct read of {target.id} personal memory is not permitted; use answer_for_peer."
        )

    def _match_target_memory(self, target: User, question: str) -> list[UserMemoryItem]:
        """Retrieve strictly within the target's own personal memory (hard user scope)."""
        terms = self._search_terms(question)
        scored: list[tuple[int, UserMemoryItem]] = []
        for item in self.repository.list_user_memory_items(user_id=target.id):
            haystack = f"{item.title} {item.summary} {item.memory_type}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score >= 1:
                scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        return [item for _, item in scored]

    INSUFFICIENT_PREFIX = "信息不足"

    def _synthesize_delegated_answer(
        self, target: User, question: str, matched: list[UserMemoryItem]
    ) -> DelegatedAnswer:
        if not matched:
            return DelegatedAnswer(
                status=DelegatedAnswerStatus.ANSWERED,
                answer=f"{self.INSUFFICIENT_PREFIX}：{target.name} 的个人记忆中没有足够依据回答此问题。",
                citations=[],
                confidence=AnswerConfidence.NONE,
            )
        citations = self._delegated_citations(matched)
        count_confidence = AnswerConfidence.HIGH if len(matched) >= 2 else AnswerConfidence.LOW

        llm_answer = self._llm_delegated_answer(target, question, matched)
        if llm_answer is None:
            # No LLM configured or the call failed — fall back to a body-free template.
            return DelegatedAnswer(
                status=DelegatedAnswerStatus.ANSWERED,
                answer=self._delegated_template(target, matched),
                citations=citations,
                confidence=count_confidence,
            )
        if llm_answer.startswith(self.INSUFFICIENT_PREFIX):
            # Trust the model's own "insufficient" judgement over the hit count.
            return DelegatedAnswer(
                status=DelegatedAnswerStatus.ANSWERED,
                answer=llm_answer,
                citations=[],
                confidence=AnswerConfidence.NONE,
            )
        return DelegatedAnswer(
            status=DelegatedAnswerStatus.ANSWERED,
            answer=llm_answer,
            citations=citations,
            confidence=count_confidence,
        )

    def _llm_delegated_answer(self, target: User, question: str, matched: list[UserMemoryItem]) -> str | None:
        """Synthesize the target's answer with a real LLM. None when unavailable/failed.

        The target's own model config answers, over the target's matched memory only. The
        system prompt asks for conclusions (no verbatim copy, no fabrication, say
        "信息不足" when thin). Cross-user data flow is permitted here (ADR 0003), so this is
        a UX gateway, not a privacy control.
        """
        client = chat_llm_client(self.repository, target, self.llm_client, timeout_seconds=market_llm_timeout_seconds())
        if client is None:
            return None
        system_prompt = (
            f"你是员工「{target.name}」的数字分身。只能依据下面提供的 {target.name} 的个人记忆回答同事的问题。"
            "要求：给出可复用的结论性回答；不得逐字照抄原始记忆的句子；不得编造记忆中没有的信息；"
            f"若信息不足，请直接回答“{self.INSUFFICIENT_PREFIX}”。"
        )
        memory_block = "\n".join(f"{index}. {item.title}：{item.summary}" for index, item in enumerate(matched, 1))
        user_prompt = (
            f"同事的问题：{question}\n\n{target.name} 的相关个人记忆：\n{memory_block}\n\n请给出你的回答。"
        )
        try:
            answer = client.complete(system_prompt, user_prompt).strip()
        except Exception:
            return None
        return answer or None

    @staticmethod
    def _delegated_template(target: User, matched: list[UserMemoryItem]) -> str:
        return (
            f"根据「{target.name}」的 {len(matched)} 条相关个人记忆（详见引用来源），"
            "已归纳出可参考的答复；原始记忆内容未随本次回答一并传出。"
        )

    # ==== Autonomous market: agent-1 publishes a MARKETPLACE_SIGNAL ====

    def publish_marketplace_signal(self, user: User) -> BlackboardPost | None:
        """agent-1: summarize the user's work into a MARKETPLACE_SIGNAL post.

        The signal is an abstracted summary — capabilities / help-offered / help-needed —
        built from the user's tasks and personal memory. Skipped when there's no source
        material. Auto-published with a deterministic id so re-publishing refreshes the
        user's prior signal rather than duplicating it (the auto-post enqueue/drain pipeline
        mints a fresh id per drain, so it can't satisfy this refresh requirement — hence a
        direct upsert). Publishing is audited.
        """
        memory = self.repository.list_user_memory_items(user_id=user.id)
        tasks = self._user_tasks(user)
        if not memory and not tasks:
            return None
        post = BlackboardPost(
            id=f"bb_signal_{user.id}",  # deterministic → re-publish refreshes, not duplicates
            task_id=f"signal_{user.id}",  # synthetic, non-task
            post_type=BlackboardPostType.MARKETPLACE_SIGNAL,
            actor=self.actor,
            title=f"{user.name} 的协作信号",
            content=self._marketplace_signal_content(user, memory, tasks),
            scope=Scope.PROJECT,
            permission="project_visible",
            read_by_agents=[self.actor],
        )
        self.repository.add_blackboard_post(post)
        self._audit("publish_marketplace_signal", "blackboard_post", post.id, {"user": user.id})
        return post

    def _user_tasks(self, user: User) -> list[Task]:
        thread_ids = {thread.id for thread in self.repository.chat_threads if thread.user_id == user.id}
        return [task for task in self.repository.tasks if task.thread_id in thread_ids]

    def _marketplace_signal_content(self, user: User, memory: list[UserMemoryItem], tasks: list[Task]) -> str:
        llm_signal = self._llm_marketplace_signal(user, memory, tasks)
        if llm_signal is not None:
            return llm_signal
        source_titles = [item.title for item in memory] + [task.title for task in tasks]
        capabilities = "、".join(source_titles[:5])
        return f"能力：{capabilities}\n可提供：可就以上经验为同事提供帮助与解答。\n需要：（暂无）"

    def _llm_marketplace_signal(self, user: User, memory: list[UserMemoryItem], tasks: list[Task]) -> str | None:
        client = chat_llm_client(self.repository, user, self.llm_client, timeout_seconds=market_llm_timeout_seconds())
        if client is None:
            return None
        system_prompt = (
            f"你是员工「{user.name}」的数字分身。根据这个人的近期任务与个人工作记忆，提炼一条发布到协作看板的信号，"
            "分三段：能力（能做什么）、可提供（能帮别人解决什么）、需要（自己当前需要什么帮助）。"
            "每段一行，分别以“能力：”“可提供：”“需要：”开头；给出结论，不要逐字照抄原始记忆。"
        )
        memory_block = "；".join(f"{item.title}：{item.summary}" for item in memory[:8]) or "（无）"
        task_block = "、".join(task.title for task in tasks[:8]) or "（无）"
        user_prompt = f"{user.name} 的近期任务：{task_block}\n个人工作记忆：\n{memory_block}\n\n请输出三段信号。"
        try:
            text = client.complete(system_prompt, user_prompt).strip()
        except Exception:
            return None
        return text or None

    # ==== Autonomous market: agent-2 scouts, matches, triggers ④ answers ====

    def scout_and_match(
        self,
        user: User,
        seen: set[str] | None = None,
        max_matches: int | None = None,
    ) -> list[tuple[str, DelegatedAnswer]]:
        """agent-2: scan MARKETPLACE_SIGNAL posts for needs `user` can solve.

        For each solvable need on another person's signal, `user` (the helper) grants that
        needer standing consent — participating in the market means letting peers pull
        non-sensitive answers from your twin — and triggers `answer_for_peer(asker=needer,
        target=user, question=need)` so the helper's twin answers the need. Non-sensitive
        answers auto-resolve; high-sensitivity matches still hit the confirmation gate.

        Cost controls: pass ``seen`` (a caller-maintained fingerprint set) to skip needs
        already evaluated on prior passes — only re-evaluated when the need text changes;
        pass ``max_matches`` to cap the answers triggered per run. Returns (needer_id,
        answer) per triggered match.
        """
        capabilities = self._capability_text(user)
        if not capabilities:
            return []
        client = chat_llm_client(self.repository, user, self.llm_client, timeout_seconds=market_llm_timeout_seconds())
        results: list[tuple[str, DelegatedAnswer]] = []
        for post in self.repository.blackboard_posts:
            if post.post_type != BlackboardPostType.MARKETPLACE_SIGNAL:
                continue
            owner_id = post.task_id.removeprefix("signal_")
            if owner_id == user.id:  # never answer your own signal
                continue
            need = self._extract_need(post.content)
            if not need:
                continue
            fingerprint = f"{owner_id}:{need}"
            if seen is not None:
                if fingerprint in seen:  # unchanged need already evaluated — skip the LLM cost
                    continue
                seen.add(fingerprint)
            if not self._match_signal(need, capabilities, client):
                continue
            needer = self.repository.get_user(owner_id)
            if needer is None:
                continue
            self.grant_consent(user, needer)  # helper lets the needer pull non-sensitive answers
            answer = self.answer_for_peer(asker=needer, target=user, question=need)
            self._audit(
                "marketplace_match", "user", needer.id,
                {"helper": user.id, "status": answer.status.value},
            )
            logger.info(
                "market match: helper=%s needer=%s status=%s need=%r",
                user.id, needer.id, answer.status.value, need[:60],
            )
            self.repository.add_blackboard_post(
                BlackboardPost(
                    id=f"bb_match_{user.id}_{needer.id}",  # deterministic per pair → refresh, not spam
                    task_id="market_activity",  # synthetic, non-task → visible on the board to all
                    post_type=BlackboardPostType.MARKETPLACE_MATCH,
                    actor=self.actor,
                    title=f"协作代答：{user.name} 帮 {needer.name} 解决「{self._truncate(need, 24)}」",
                    content=self._truncate(answer.answer or "已发起代答，等待对方确认。", 200),
                    scope=Scope.PROJECT,
                    permission="project_visible",
                    read_by_agents=[self.actor],
                )
            )
            results.append((needer.id, answer))
            if max_matches is not None and len(results) >= max_matches:
                logger.info("market scout: hit per-run cap (%d) for helper=%s", max_matches, user.id)
                break
        return results

    def _match_signal(self, need: str, capabilities: str, client: ChatLLM | None) -> bool:
        """Two-stage match (validated by the Issue #6 spike): keyword pre-filter → LLM confirm.

        The pre-filter is permissive and cheap; the LLM is the real gate. With no LLM the
        match degrades to keyword-only.
        """
        if not self._keyword_overlap(need, capabilities):
            return False
        if client is None:
            return True
        system_prompt = (
            "你是一个协作匹配判断器。给定候选人的能力和一条求助需求，判断候选人能否切实解决该需求。"
            "只输出一行：YES 或 NO，后跟一句简短理由。"
        )
        user_prompt = f"候选人能力：{capabilities}\n求助需求：{need}\n能否切实解决？"
        try:
            reply = client.complete(system_prompt, user_prompt).strip()
        except Exception:
            return False
        return reply.upper().lstrip().startswith("YES")

    def _keyword_overlap(self, left: str, right: str) -> bool:
        return bool(set(self._search_terms(left)) & set(self._search_terms(right)))

    def _capability_text(self, user: User) -> str:
        memory = self.repository.list_user_memory_items(user_id=user.id)
        tasks = self._user_tasks(user)
        titles = [item.title for item in memory] + [task.title for task in tasks]
        return "、".join(titles)

    @staticmethod
    def _extract_need(content: str) -> str | None:
        for raw_line in content.splitlines():
            line = raw_line.strip()
            for prefix in ("需要：", "需要:"):
                if line.startswith(prefix):
                    need = line[len(prefix):].strip()
                    if need and need not in {"（暂无）", "(暂无)", "无"}:
                        return need
                    return None
        return None

    @staticmethod
    def _delegated_citations(matched: list[UserMemoryItem]) -> list[Source]:
        """Expose citation titles only — the memory's sources, or its title as a pointer.

        Never the memory summary (the raw body), which must not cross the boundary.
        """
        citations: list[Source] = []
        seen: set[str] = set()
        for item in matched:
            item_sources = item.sources or [
                Source(title=item.title, source_type="personal_memory", reference=f"user-memory://{item.id}")
            ]
            for source in item_sources:
                if source.id in seen:
                    continue
                seen.add(source.id)
                citations.append(source)
        return citations

    def _assistant_content_for_turn(self, intent: Intent, content: str, state: _ChatTurnState, user: User) -> str:
        if intent == Intent.ASK_SYSTEM_INFO:
            return self._system_info_answer(user)
        if intent == Intent.RECORD_PRIVATE_NOTE:
            return "已记录为你的私有工作上下文，暂不共享到项目或团队记忆。"
        if intent == Intent.GENERATE_BRIEF:
            brief_document = self._create_brief_document(content, state, user)
            state.inbox_items.append(
                self._inbox(
                    title="确认 Brief 中的设计原则",
                    summary="已生成 Brief 草稿。该原则会影响项目 Brief 和后续团队记忆，建议在收件箱打开确认。",
                    item_type="decision_review",
                    scope=Scope.PROJECT,
                    user_id=user.id,
                    metadata={"document_id": brief_document.id, "artifact_type": "brief_draft"},
                )
            )
            return (
                f"我已按「{brief_document.metadata.get('template_title', '匹配模板')}」生成 Brief 草稿"
                f"《{brief_document.title}》，并放入收件箱供你打开确认。"
                "草稿已结合当前用户需求、可引用证据和来源生成。"
            )
        if intent == Intent.REQUEST_RISK_REVIEW:
            state.inbox_items.append(
                self._inbox(
                    title="确认外部素材授权范围",
                    summary="正式稿使用前需要确认授权范围、使用期限和二次加工权限。",
                    item_type="risk_review",
                    scope=Scope.PROJECT,
                    user_id=user.id,
                )
            )
            return "risk_agent 已返回策略规则评审结论，我已放入收件箱等待你处理。"
        if intent == Intent.CREATE_MEMORY_CANDIDATE:
            state.memory_items.append(
                self._memory(
                    title="大促会场首屏结构偏好",
                    summary="转化目标优先时，首屏应优先保证核心入口密度。",
                    memory_type="method",
                    sources=state.synthesis_evidence_post.sources if state.synthesis_evidence_post else [],
                    owner_user_id=user.id,
                )
            )
            return "我已提取一条候选团队记忆，并放入记忆库审核，不会自动写入团队记忆。"
        if state.pending_tool_approval:
            return "这个请求涉及高风险工具调用，需要你先在收件箱审批，我不会在审批前执行。"
        if state.evidence_post and state.evidence_post.status == "needs_review":
            return "外部资料存在安全风险，已放入收件箱等待审核。"
        if (
            intent == Intent.ASK_MEMORY
            and state.memory_search
            and state.memory_search.requested_scope != MemorySearchScope.AUTO
            and not state.memory_search.results
        ):
            scope_labels = {
                MemorySearchScope.PERSONAL: "个人记忆",
                MemorySearchScope.PROJECT: "当前项目记忆",
                MemorySearchScope.TEAM: "可访问的已采纳团队记忆",
            }
            scope_label = scope_labels[state.memory_search.requested_scope]
            return f"没有在{scope_label}中找到相关结果；未跨范围检索或发起团队求助。"
        if intent == Intent.ASK_MEMORY and state.request_post and state.evidence_post is None:
            return "我没有在个人、项目或团队记忆中找到足够结果，已在项目 BBS 发帖等待团队或服务 Agent 补充。"
        return self._evidence_answer(state.synthesis_evidence_post, intent, content)

    def _system_info_answer(self, user: User) -> str:
        model_id = resolve_agent_model_id(self.repository, user)
        model = self.repository.get_model_definition(model_id)
        if model and model.configured:
            return f"当前个人 Agent 配置的模型是 {model.label}（{model.model_name}）。"
        return "当前没有配置外部大模型，正在使用本地兜底模式；可在 Agent 页面选择并保存模型。"

    def _general_chat_answer(
        self,
        content: str,
        user: User,
        history: list[ChatMessage],
        llm_client: ChatLLM | None,
    ) -> SynthesisResult:
        if llm_client is None:
            return SynthesisResult(
                content="我可以先帮你澄清问题；如果你需要查资料、查数据、生成 Brief 或沉淀记忆，我会再进入对应工作流。",
                llm_used=False,
                fallback_reason="llm_not_configured",
            )
        history_text = "\n".join(
            f"{'用户' if message.role == ChatRole.USER else '助理'}：{message.content}" for message in history[-6:]
        )
        prompt = f"历史上下文：\n{history_text or '无'}\n\n用户输入：{content}\n请直接自然回复，不要创建任务或编造数据。"
        requested_model, _, _ = llm_model_provenance(llm_client)
        try:
            generated = llm_client.complete(
                system_prompt=(
                    "你是 AgentMesh 作战室里的中文对话助手。"
                    "当前输入未形成明确的项目工作流意图，只做普通对话、解释或澄清。"
                    "不要声称已经调用 Agent，不要写入记忆，不要创建任务。"
                ),
                user_prompt=prompt,
            )
        except Exception as error:
            reason = error.reason if isinstance(error, LLMRequestError) else "llm_error"
            return SynthesisResult(
                content="我可以继续和你澄清需求；当问题明确需要查资料、查数据、生成 Brief 或沉淀记忆时，我会进入对应 Agent 工作流。",
                llm_used=False,
                fallback_reason=reason,
                requested_model=requested_model,
            )
        content_text = generated.strip()
        if not content_text:
            return SynthesisResult(
                content="我在，可以继续说。",
                llm_used=False,
                fallback_reason="empty_response",
                requested_model=requested_model,
            )
        requested_model, actual_model, model_fallback_reason = llm_model_provenance(llm_client)
        return SynthesisResult(
            content=content_text,
            llm_used=True,
            fallback_reason=model_fallback_reason,
            requested_model=requested_model,
            actual_model=actual_model,
        )

    def _create_request_post(
        self,
        task: Task,
        content: str,
        title: str = "补充团队历史经验",
        read_by_agents: list[str] | None = None,
        current_owner_agent_id: str = "mock_research_agent",
        current_owner_label: str = "research_agent",
        done_when: str = "服务 Agent 返回可引用证据或风险结论",
    ) -> BlackboardPost:
        post = BlackboardPost(
            task_id=task.id,
            post_type=BlackboardPostType.REQUEST,
            actor=self.actor,
            title=title,
            content=content,
            scope=Scope.PROJECT,
            permission="project_visible",
            read_by_agents=read_by_agents or ["mock_research_agent", "risk_agent"],
            collaboration_stage=CollaborationStage.DISCUSSION,
            current_owner_agent_id=current_owner_agent_id,
            current_owner_label=current_owner_label,
            done_when=done_when,
        )
        self.repository.add_blackboard_post(post)
        self._audit("create_blackboard_request", "blackboard_post", post.id, {"task_id": task.id})
        return post

    @staticmethod
    def _create_evidence_post(
        task: Task,
        request_post: BlackboardPost,
        result: AcquisitionResult,
    ) -> BlackboardPost:
        return BlackboardPost(
            task_id=task.id,
            post_type=BlackboardPostType.EVIDENCE,
            actor=result.actor,
            title=result.title,
            content=result.content,
            scope=Scope.PROJECT,
            permission=result.permission,
            sources=result.sources,
            metadata=result.metadata,
            read_by_agents=[request_post.actor],
            related_post_id=request_post.id,
            collaboration_stage=CollaborationStage.REVIEW,
            current_owner_agent_id=result.actor,
            current_owner_label=result.actor,
            done_when="个人 Agent 完成证据合成并返回用户",
        )

    def _ensure_thread(
        self,
        thread_id: str,
        content: str,
        user: User,
        *,
        allow_create: bool = False,
    ) -> ChatThread:
        existing_thread = self.repository.get_chat_thread(thread_id)
        if existing_thread is not None:
            if (
                existing_thread.user_id != user.id
                or existing_thread.workspace_id != user.workspace_id
                or existing_thread.project_id != user.default_project_id
            ):
                raise ChatThreadNotFoundError(thread_id)
            return existing_thread
        if not allow_create:
            raise ChatThreadNotFoundError(thread_id)
        title = content.strip()[:60] or "新的团队大脑对话"
        return self.repository.add_chat_thread(
            ChatThread(
                id=thread_id,
                workspace_id=user.workspace_id,
                project_id=user.default_project_id,
                user_id=user.id,
                title=title,
            )
        )

    def _get_thread_history(self, thread_id: str) -> list[ChatMessage]:
        """获取当前 thread 的最近 N 条消息作为对话上下文。

        控制 token budget：最多 MAX_HISTORY_MESSAGES 条，总字符数不超过 MAX_HISTORY_CHARS。
        """
        messages = self.repository.list_thread_messages(thread_id)
        # 取最近 N 条（不含当前正在处理的，因为还没存入）
        recent = messages[-self.MAX_HISTORY_MESSAGES:]
        # 按字符 budget 截断
        result = []
        total_chars = 0
        for msg in reversed(recent):
            msg_chars = len(msg.content)
            if total_chars + msg_chars > self.MAX_HISTORY_CHARS:
                break
            result.append(msg)
            total_chars += msg_chars
        result.reverse()
        return result

    def _activity(
        self,
        title: str,
        summary: str,
        category: str,
        scope: Scope,
        user_id: str,
    ) -> ActivityLog:
        owner = self.repository.get_user(user_id)
        log = ActivityLog(
            actor=self.actor,
            user_id=user_id,
            title=title,
            summary=summary,
            category=category,
            scope=scope,
            workspace_id=owner.workspace_id if owner is not None else WORKSPACE.id,
            project_id=owner.default_project_id if owner is not None else PROJECT.id,
        )
        self.repository.add_activity_log(log)
        return log

    def _create_brief_document(self, content: str, state: _ChatTurnState, user: User) -> DocumentRecord:
        template = select_brief_template(content)
        title = f"Brief 草稿：{template.title}"
        evidence = state.synthesis_evidence_post.content if state.synthesis_evidence_post else "暂无可引用证据。"
        source_titles = self._source_titles(state.synthesis_evidence_post, state.risk_post)
        document_source = Source(
            title=title,
            source_type="generated_brief",
            reference=f"generated://brief/{new_id('brief')}",
        )
        self.repository.add_source(document_source)
        fallback_draft = self._brief_template_fallback(content, template, evidence, source_titles)
        draft, generation_mode = self._generate_brief_draft_with_llm(content, template, evidence, source_titles, fallback_draft, user)
        return self.repository.add_document(
            DocumentRecord(
                title=title,
                file_name="generated-brief.md",
                content_type="text/markdown",
                text=draft,
                source=document_source,
                workspace_id=user.workspace_id,
                project_id=user.default_project_id,
                uploaded_by=user.id,
                metadata={
                    "generated_by": self.actor,
                    "artifact_type": "brief_draft",
                    "template_id": template.id,
                    "template_title": template.title,
                    "generation_mode": generation_mode,
                },
            )
        )

    def _generate_brief_draft_with_llm(
        self,
        content: str,
        template: BriefTemplate,
        evidence: str,
        source_titles: str,
        fallback_draft: str,
        user: User,
    ) -> tuple[str, str]:
        client = chat_llm_client(self.repository, user, self.llm_client)
        if client is None:
            return fallback_draft, "template_fallback"
        try:
            draft = client.complete(
                system_prompt=(
                    "你是 AgentMesh 的资深项目 Brief 写作助手。"
                    "必须基于用户需求、匹配到的 Brief 模板和可引用证据生成中文 Markdown。"
                    "不要编造来源；来源只能使用输入中的来源。"
                ),
                user_prompt=(
                    f"用户需求：{content}\n\n"
                    f"匹配模板：{template.title}\n"
                    f"模板说明：{template.description}\n"
                    f"模板写作要求：{template.guidance}\n"
                    f"建议章节：{'、'.join(template.sections)}\n\n"
                    f"可引用证据：{evidence}\n"
                    f"来源：{source_titles}\n\n"
                    "请生成一份可放入收件箱确认的 Brief 草稿。"
                ),
            ).strip()
        except Exception:
            return fallback_draft, "template_fallback"
        return (draft or fallback_draft), ("llm_regenerated" if draft else "template_fallback")

    @staticmethod
    def _brief_template_fallback(content: str, template: BriefTemplate, evidence: str, source_titles: str) -> str:
        sections = "\n".join(f"- {section}" for section in template.sections)
        return (
            f"# Brief 草稿：{template.title}\n\n"
            f"## 匹配模板\n{template.title}：{template.description}\n\n"
            f"## 用户请求\n{content}\n\n"
            f"## 模板章节\n{sections}\n\n"
            "## 核心结论\n"
            "基于当前需求和可引用证据，优先沿用模板中的关键章节，并围绕已验证的项目经验生成 Brief 草稿。\n\n"
            "## 可引用依据\n"
            f"{evidence}\n\n"
            "## 写作原则\n"
            f"{template.guidance}\n\n"
            "## 待确认\n"
            "- 是否将该 Brief 草稿作为项目正式 Brief 的基础版本。\n"
            "- 是否需要补充更多真实数据、竞品资料或用户研究。\n"
            "- 是否将确认后的结论沉淀为团队候选记忆。\n\n"
            f"## 来源\n{source_titles}\n"
        )

    def _inbox(
        self,
        title: str,
        summary: str,
        item_type: str,
        scope: Scope,
        user_id: str,
        metadata: dict[str, str] | None = None,
    ) -> InboxItem:
        owner = self.repository.get_user(user_id)
        item = InboxItem(
            title=title,
            summary=summary,
            item_type=item_type,
            scope=scope,
            user_id=user_id,
            workspace_id=owner.workspace_id if owner is not None else WORKSPACE.id,
            project_id=owner.default_project_id if owner is not None else PROJECT.id,
            metadata=metadata or {},
        )
        self.repository.add_inbox_item(item)
        return item

    def _memory(
        self,
        title: str,
        summary: str,
        memory_type: str,
        sources: list[Source],
        owner_user_id: str,
    ) -> MemoryItem:
        owner = self.repository.get_user(owner_user_id)
        item = MemoryItem(
            title=title,
            summary=summary,
            memory_type=memory_type,
            scope=Scope.TEAM_CANDIDATE,
            owner_user_id=owner_user_id,
            workspace_id=owner.workspace_id if owner is not None else WORKSPACE.id,
            project_id=owner.default_project_id if owner is not None else PROJECT.id,
            sources=sources,
        )
        self.repository.add_memory_item(item)
        return item

    def _record_short_term_memory(
        self,
        task: Task,
        intent: Intent,
        user_content: str,
        assistant_content: str,
        state: _ChatTurnState,
        user: User,
    ) -> UserMemoryItem | None:
        if intent == Intent.ASK_SYSTEM_INFO or state.pending_tool_approval:
            return None
        sources = self._assistant_sources(state.evidence_post, state.risk_post)
        item = UserMemoryItem(
            user_id=user.id,
            layer=MemoryLayer.SHORT_TERM,
            title=self._short_term_memory_title(intent),
            summary=(
                f"用户请求：{self._truncate(user_content, 120)}；"
                f"处理结果：{self._truncate(assistant_content, 240)}"
            ),
            source_kind=f"chat_workflow:{intent.value}",
            memory_type=self._short_term_memory_type(intent),
            memory_date=now_utc().date(),
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            source_thread_id=task.thread_id,
            source_task_id=task.id,
            sources=sources,
        )
        return self.repository.add_user_memory_item(item)

    def _audit(self, action: str, target_type: str, target_id: str, metadata: dict[str, object]) -> None:
        workspace_id, project_id = self._audit_scope(target_type, target_id, metadata)
        self.repository.add_audit_event(
            AuditEvent(
                actor=self.actor,
                action=action,
                target_type=target_type,
                target_id=target_id,
                workspace_id=workspace_id,
                project_id=project_id,
                metadata=metadata,
            )
        )

    def _audit_scope(
        self,
        target_type: str,
        target_id: str,
        metadata: dict[str, object],
    ) -> tuple[str | None, str | None]:
        target = None
        task = None
        if target_type == "task":
            task = self.repository.get_task(target_id)
        elif target_type == "blackboard_post":
            post = self.repository.get_blackboard_post(target_id)
            task = self.repository.get_task(post.task_id) if post is not None else None
        elif target_type == "chat_message":
            message = next((item for item in self.repository.chat_messages if item.id == target_id), None)
            target = self.repository.get_chat_thread(message.thread_id) if message is not None else None
        elif target_type == "inbox_item":
            target = self.repository.get_inbox_item(target_id)
        elif target_type == "document":
            target = self.repository.get_document(target_id)
        elif target_type == "memory_item":
            target = self.repository.get_memory_item(target_id)
        elif target_type == "user_memory_item":
            target = self.repository.get_user_memory_item(target_id)
        elif target_type == "user":
            target = self.repository.get_user(target_id)
        elif target_type == "consent_grant":
            target = next((item for item in self.repository.consent_grants if item.id == target_id), None)
        elif target_type == "contribution_point":
            target = next((item for item in self.repository.contribution_points if item.id == target_id), None)

        if task is None and isinstance(metadata.get("task_id"), str):
            task = self.repository.get_task(metadata["task_id"])
        if task is not None:
            target = self.repository.get_chat_thread(task.thread_id)

        workspace_id = getattr(target, "workspace_id", None)
        project_id = getattr(target, "project_id", None)
        if workspace_id is None and isinstance(metadata.get("workspace_id"), str):
            workspace_id = metadata["workspace_id"]
        if project_id is None and isinstance(metadata.get("project_id"), str):
            project_id = metadata["project_id"]

        candidate_user_ids = [
            getattr(target, "user_id", None),
            getattr(target, "owner_user_id", None),
            target_id if target_type == "user" else None,
            *(metadata.get(key) for key in ("user", "target", "grantor", "by", "awarded_to", "helper", "asker")),
        ]
        for candidate_user_id in candidate_user_ids:
            if not isinstance(candidate_user_id, str):
                continue
            user = self.repository.get_user(candidate_user_id)
            if user is None:
                continue
            workspace_id = workspace_id or user.workspace_id
            project_id = project_id or user.default_project_id
            break
        return workspace_id, project_id

    def _persist_sources(self, sources: list[Source]) -> None:
        for source in sources:
            self.repository.add_source(source)

    def _try_extract_skills(self, user: User) -> None:
        """Attempt to extract recurring workflow patterns into draft skills."""
        try:
            from agentmesh.skill_extractor import try_extract_skills

            new_skills = try_extract_skills(
                user_memory_items=self.repository.user_memory_items,
                existing_skills=self.repository.learned_skills,
                user_id=user.id,
                workspace_id=user.workspace_id,
                project_id=user.default_project_id,
            )
            for skill in new_skills:
                self.repository.add_learned_skill(skill)
        except Exception as exc:
            logger.warning("Skill extraction failed: %s", exc)

    def _synthesize_with_llm(
        self,
        fallback_content: str,
        user_content: str,
        intent: Intent,
        evidence_post: BlackboardPost | None,
        risk_post: BlackboardPost | None,
        inbox_items: list[InboxItem],
        memory_items: list[MemoryItem],
        user: User = USER,
        history: list[ChatMessage] | None = None,
    ):
        return synthesize_with_llm_result(
            repository=self.repository,
            llm_client=self.llm_client,
            fallback_content=fallback_content,
            user_content=user_content,
            intent=intent,
            evidence_post=evidence_post,
            risk_post=risk_post,
            inbox_items=inbox_items,
            memory_items=memory_items,
            user=user,
            history=history,
        )

    @staticmethod
    def _llm_prompt(
        fallback_content: str,
        user_content: str,
        intent: Intent,
        evidence_post: BlackboardPost | None,
        risk_post: BlackboardPost | None,
        inbox_items: list[InboxItem],
        memory_items: list[MemoryItem],
        history: list[ChatMessage] | None = None,
    ) -> str:
        return build_llm_prompt(
            fallback_content=fallback_content,
            user_content=user_content,
            intent=intent,
            evidence_post=evidence_post,
            risk_post=risk_post,
            inbox_items=inbox_items,
            memory_items=memory_items,
            history=history,
        )

    @staticmethod
    def _assistant_sources(evidence_post: BlackboardPost | None, risk_post: BlackboardPost | None) -> list[Source]:
        return assistant_sources(evidence_post, risk_post)

    @staticmethod
    def _source_titles(evidence_post: BlackboardPost | None, risk_post: BlackboardPost | None) -> str:
        return source_titles(evidence_post, risk_post)

    @staticmethod
    def _task_title(intent: Intent) -> str:
        labels = {
            Intent.GENERAL_CHAT: "普通对话",
            Intent.ASK_MEMORY: "查询团队经验",
            Intent.GENERATE_BRIEF: "生成项目 Brief",
            Intent.RECORD_PRIVATE_NOTE: "记录私有工作上下文",
            Intent.REQUEST_EXTERNAL_RESEARCH: "请求外接 Agent 补充资料",
            Intent.REQUEST_DATA_QUERY: "请求 data_agent 查询指标",
            Intent.REQUEST_RISK_REVIEW: "请求 risk_agent 检查风险",
            Intent.CREATE_MEMORY_CANDIDATE: "创建候选团队记忆",
            Intent.ASK_SYSTEM_INFO: "查询系统与模型配置",
        }
        return labels[intent]

    @staticmethod
    def _short_term_memory_title(intent: Intent) -> str:
        labels = {
            Intent.ASK_MEMORY: "短期记忆：查询团队经验",
            Intent.GENERATE_BRIEF: "短期记忆：生成项目 Brief",
            Intent.RECORD_PRIVATE_NOTE: "短期记忆：私有工作记录",
            Intent.REQUEST_EXTERNAL_RESEARCH: "短期记忆：资料检索结果",
            Intent.REQUEST_DATA_QUERY: "短期记忆：数据查询结果",
            Intent.REQUEST_RISK_REVIEW: "短期记忆：风险检查结果",
            Intent.CREATE_MEMORY_CANDIDATE: "短期记忆：候选记忆提取",
            Intent.ASK_SYSTEM_INFO: "短期记忆：系统信息查询",
            Intent.GENERAL_CHAT: "短期记忆：普通对话",
        }
        return labels[intent]

    @staticmethod
    def _short_term_memory_type(intent: Intent) -> str:
        labels = {
            Intent.ASK_MEMORY: "project_background",
            Intent.GENERATE_BRIEF: "project_background",
            Intent.RECORD_PRIVATE_NOTE: "note",
            Intent.REQUEST_EXTERNAL_RESEARCH: "competitor",
            Intent.REQUEST_DATA_QUERY: "data",
            Intent.REQUEST_RISK_REVIEW: "risk",
            Intent.CREATE_MEMORY_CANDIDATE: "decision",
            Intent.ASK_SYSTEM_INFO: "note",
            Intent.GENERAL_CHAT: "note",
        }
        return labels[intent]

    def _llm_provider_label(self, user: User, llm_client: ChatLLM | None) -> str:
        model_name = getattr(llm_client, "model", None)
        if isinstance(model_name, str) and model_name:
            return model_name
        model_id = resolve_agent_model_id(self.repository, user)
        model = self.repository.get_model_definition(model_id)
        return model.model_name if model is not None else model_id

    @staticmethod
    def _capture_provider_metadata(state: _ChatTurnState, metadata: dict[str, str]) -> None:
        state.requested_provider = metadata.get("requested_provider") or state.requested_provider
        state.actual_provider = metadata.get("actual_provider") or state.actual_provider
        mode = metadata.get("mode")
        if mode in {"real", "fallback"}:
            state.provider_mode = mode
        latency = metadata.get("latency_ms")
        if latency:
            try:
                state.provider_latency_ms = max(0.0, float(latency))
            except ValueError:
                state.provider_latency_ms = None
        state.provider_fallback_reason = metadata.get("fallback_reason") or state.provider_fallback_reason

    def _apply_trace_provenance(
        self,
        trace: ChatWorkflowTrace,
        state: _ChatTurnState,
        user: User,
        synthesis_latency_ms: float | None,
    ) -> None:
        if state.requested_provider is not None or state.actual_provider is not None:
            trace.requested_provider = state.requested_provider or state.actual_provider
            trace.actual_provider = state.actual_provider or state.requested_provider
            trace.provider_mode = state.provider_mode or "real"
            trace.latency_ms = state.provider_latency_ms
            trace.fallback_reason = trace.fallback_reason or state.provider_fallback_reason
            return
        if trace.llm_used:
            trace.requested_provider = "llm"
            trace.actual_provider = "llm"
            trace.provider_mode = "real"
            trace.latency_ms = synthesis_latency_ms
            return
        trace.requested_provider = "llm" if trace.model_fallback_reason else "agentmesh"
        trace.actual_provider = "local_fallback" if trace.model_fallback_reason else "agentmesh"
        trace.provider_mode = "fallback" if trace.model_fallback_reason else "real"
        trace.latency_ms = synthesis_latency_ms

    @staticmethod
    def _command_workflow_trace(
        intent: Intent, command: str, persisted: bool, source: str = "skill", confidence: float = 1.0,
    ) -> ChatWorkflowTrace:
        return ChatWorkflowTrace(
            intent=intent,
            confidence=confidence,
            source=source,
            selected_workflow=command,
            persisted=persisted,
            llm_used=False,
        )

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        text = " ".join(value.split())
        return text if len(text) <= limit else f"{text[: limit - 1]}…"

    @staticmethod
    def _evidence_answer(evidence_post: BlackboardPost | None, intent: Intent, user_content: str) -> str:
        return evidence_answer(evidence_post, intent, user_content)
