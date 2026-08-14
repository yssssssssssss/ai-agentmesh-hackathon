from __future__ import annotations

from agentmesh.agents import PersonalAgent
from agentmesh.chat_skills import parse_chat_skill_invocation, spec_for_intent
from agentmesh.models import (
    ChatMessage,
    ChatRole,
    ChatThread,
    Intent,
    MemoryItem,
    MemoryKind,
    MemoryLayer,
    MemorySearchScope,
    MemoryStatus,
    Project,
    Scope,
    Team,
    TeamMembership,
    UserMemoryItem,
)
from agentmesh.seed import PROJECT, TEAM, USER, WORKSPACE
from agentmesh.store import store


def _reset_context() -> None:
    store.reset()
    store.save_project(PROJECT)
    store.save_team(TEAM)
    store.save_team_membership(
        TeamMembership(id="membership_scoped_user", team_id=TEAM.id, user_id=USER.id)
    )


def _user_memory(item_id: str, user_id: str, title: str, project_id: str | None = None) -> UserMemoryItem:
    return UserMemoryItem(
        id=item_id,
        user_id=user_id,
        layer=MemoryLayer.SHORT_TERM,
        title=title,
        summary=f"{title}的详细内容",
        source_kind="note",
        workspace_id=WORKSPACE.id,
        project_id=project_id,
    )


def _shared_memory(
    item_id: str,
    title: str,
    scope: Scope,
    *,
    project_id: str | None = None,
    team_id: str | None = None,
) -> MemoryItem:
    return MemoryItem(
        id=item_id,
        title=title,
        summary=f"{title}的详细内容",
        memory_type="standard",
        scope=scope,
        status=MemoryStatus.ACCEPTED,
        workspace_id=WORKSPACE.id,
        project_id=project_id,
        team_id=team_id,
    )


class _UnexpectedLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return "来自旧对话历史的越界回答"


class _CapturingLLM:
    def __init__(self) -> None:
        self.user_prompts: list[str] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.user_prompts.append(user_prompt)
        return "仅基于个人检索结果回答 [P1]"


class TestScopedMemoryCommands:
    def test_commands_map_to_explicit_scopes_and_natural_intent_keeps_auto_default(self) -> None:
        expected = {
            "$memory.search": MemorySearchScope.AUTO,
            "$memory.personal": MemorySearchScope.PERSONAL,
            "$memory.project": MemorySearchScope.PROJECT,
            "$memory.team": MemorySearchScope.TEAM,
        }

        for command, scope in expected.items():
            invocation = parse_chat_skill_invocation(f"{command} 618 首屏")
            assert invocation is not None
            assert invocation.spec is not None
            assert invocation.spec.memory_search_scope == scope

        default_spec = spec_for_intent(Intent.ASK_MEMORY)
        assert default_spec is not None
        assert default_spec.command == "$memory.search"
        assert default_spec.memory_search_scope == MemorySearchScope.AUTO


class TestStrictMemoryScopeIsolation:
    def setup_method(self) -> None:
        _reset_context()

    def test_personal_scope_returns_only_current_users_private_memory(self) -> None:
        store.add_user_memory_item(_user_memory("umem_self", USER.id, "范围测试个人记忆"))
        store.add_user_memory_item(_user_memory("umem_other", "usr_other", "范围测试个人记忆"))
        store.add_memory_item(
            _shared_memory("mem_team", "范围测试个人记忆", Scope.TEAM_ACCEPTED, team_id=TEAM.id)
        )

        results = PersonalAgent(store)._search_team_brain(
            "范围测试个人记忆",
            USER,
            search_scope=MemorySearchScope.PERSONAL,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )

        assert [result.id for result in results] == ["umem_self"]

    def test_project_scope_returns_only_current_project_memory(self) -> None:
        other_project = Project(
            id="project_other",
            workspace_id=WORKSPACE.id,
            name="其他项目",
            goal="隔离测试",
            member_ids=[USER.id],
        )
        store.save_project(other_project)
        store.add_memory_item(
            _shared_memory("mem_project_current", "范围测试项目记忆", Scope.PROJECT, project_id=PROJECT.id)
        )
        store.add_memory_item(
            _shared_memory("mem_project_other", "范围测试项目记忆", Scope.PROJECT, project_id=other_project.id)
        )
        store.add_user_memory_item(_user_memory("umem_project", USER.id, "范围测试项目记忆", PROJECT.id))

        results = PersonalAgent(store)._search_team_brain(
            "范围测试项目记忆",
            USER,
            search_scope=MemorySearchScope.PROJECT,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )

        assert [result.id for result in results] == ["mem_project_current"]

    def test_team_scope_returns_only_accessible_accepted_team_memory(self) -> None:
        other_team = Team(id="team_other", workspace_id=WORKSPACE.id, name="其他团队")
        store.save_team(other_team)
        store.add_memory_item(
            _shared_memory("mem_team_visible", "范围测试团队记忆", Scope.TEAM_ACCEPTED, team_id=TEAM.id)
        )
        store.add_memory_item(
            _shared_memory("mem_team_candidate", "范围测试团队记忆", Scope.TEAM_CANDIDATE, team_id=TEAM.id)
        )
        store.add_memory_item(
            _shared_memory("mem_team_other", "范围测试团队记忆", Scope.TEAM_ACCEPTED, team_id=other_team.id)
        )
        store.add_memory_item(
            _shared_memory("mem_project", "范围测试团队记忆", Scope.PROJECT, project_id=PROJECT.id)
        )

        results = PersonalAgent(store)._search_team_brain(
            "范围测试团队记忆",
            USER,
            search_scope=MemorySearchScope.TEAM,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )

        assert [result.id for result in results] == ["mem_team_visible"]

    def test_strict_scope_does_not_fall_back_to_other_memory_kinds(self) -> None:
        store.add_memory_item(
            _shared_memory("mem_team_only", "严格范围无回退", Scope.TEAM_ACCEPTED, team_id=TEAM.id)
        )

        results = PersonalAgent(store)._search_team_brain(
            "严格范围无回退",
            USER,
            search_scope=MemorySearchScope.PERSONAL,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )

        assert results == []

    def test_strict_scope_miss_does_not_call_llm_with_cross_scope_history(self) -> None:
        llm = _UnexpectedLLM()
        agent = PersonalAgent(store, llm_client=llm)

        response = agent.handle_chat("$memory.personal 完全不存在的个人记忆", user=USER)

        assert llm.calls == 0
        assert response.assistant_message.content == "没有在个人记忆中找到相关结果；未跨范围检索或发起团队求助。"

    def test_strict_scope_hit_excludes_cross_scope_thread_history_from_llm_prompt(self) -> None:
        store.add_user_memory_item(_user_memory("umem_prompt", USER.id, "严格个人提示记忆"))
        thread = store.add_chat_thread(
            ChatThread(
                id="thread_strict_prompt",
                workspace_id=WORKSPACE.id,
                project_id=PROJECT.id,
                user_id=USER.id,
                title="严格提示隔离",
            )
        )
        store.add_chat_message(
            ChatMessage(
                thread_id=thread.id,
                role=ChatRole.ASSISTANT,
                content="不应进入严格检索提示的团队历史秘密",
            )
        )
        llm = _CapturingLLM()
        agent = PersonalAgent(store, llm_client=llm)

        response = agent.handle_chat(
            "$memory.personal 严格个人提示记忆",
            thread_id=thread.id,
            user=USER,
        )

        assert len(llm.user_prompts) == 1
        assert "不应进入严格检索提示的团队历史秘密" not in llm.user_prompts[0]
        assert response.assistant_message.content == "仅基于个人检索结果回答 [P1]"

    def test_strict_collection_filter_applies_before_backend_candidate_limit(self) -> None:
        for index in range(205):
            store.add_user_memory_item(
                _user_memory(
                    f"umem_other_{index:03d}",
                    "usr_other",
                    "候选截断范围记忆",
                )
            )
        store.add_user_memory_item(_user_memory("umem_after_limit", USER.id, "候选截断范围记忆"))

        results = PersonalAgent(store)._search_team_brain(
            "候选截断范围记忆",
            USER,
            search_scope=MemorySearchScope.PERSONAL,
            workspace_id=WORKSPACE.id,
            project_id=PROJECT.id,
        )

        assert [result.id for result in results] == ["umem_after_limit"]


class TestMemorySearchProvenance:
    def setup_method(self) -> None:
        _reset_context()

    def test_scoped_search_persists_memory_kind_counts_and_stable_citation(self) -> None:
        store.add_user_memory_item(_user_memory("umem_trace", USER.id, "范围追踪个人记忆"))
        agent = PersonalAgent(store)

        response = agent.handle_chat("$memory.personal 范围追踪个人记忆", user=USER)

        assert response.turn_trace is not None
        assert response.turn_trace.memory_search is not None
        memory_search = response.turn_trace.memory_search
        assert memory_search.requested_scope == MemorySearchScope.PERSONAL
        assert memory_search.personal_count == 1
        assert memory_search.project_count == 0
        assert memory_search.team_count == 0
        assert len(memory_search.results) == 1
        result = memory_search.results[0]
        assert result.result_id == "umem_trace"
        assert result.memory_kind == MemoryKind.PERSONAL
        assert result.citation_label == "P1"
        assert "[P1][个人记忆]" in response.assistant_message.content

        stored_trace = store.list_thread_turn_traces(response.thread_id)[0]
        assert stored_trace.memory_search == memory_search
        metrics = store.retrieval_metrics[0]
        assert metrics.requested_scope == MemorySearchScope.PERSONAL
        assert metrics.source_ids_cited == ["umem_trace"]
