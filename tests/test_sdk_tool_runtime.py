from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agents import PersonalAgent
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    AgentToolGrant,
    ChatThread,
    MemoryLayer,
    Scope,
    SkillDefinition,
    SkillSourceScope,
    Source,
    ToolDefinition,
    UserMemoryItem,
)
from agentmesh.seed import USER, ensure_base_workspace_data
from agentmesh.skill_runtime.resources import (
    build_skill_resource_tool,
    resolve_skill_resource,
    skill_resource_manifest,
)
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.factory import AgentMeshToolFactory
from agentmesh.tools import ensure_tool_seed_data


def _repository(tmp_path) -> SQLiteStore:
    repository = SQLiteStore(tmp_path / "tools.sqlite3")
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    ensure_tool_seed_data(repository, granted_by="system")
    return repository


def _core_event_types(repository: SQLiteStore, run_id: str) -> list[str]:
    core = {"run_started", "approval_requested", "approval_resolved", "run_completed", "run_failed", "run_cancelled"}
    return [event.event_type for event in repository.list_agent_run_events(run_id) if event.event_type in core]


def test_late_ordinary_run_completion_cannot_overwrite_cancellation(tmp_path) -> None:
    repository = _repository(tmp_path)
    run = repository.save_agent_run(
        AgentRun(
            id="run_late_completion",
            thread_id="thread_late_completion",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="late",
            status=AgentRunStatus.RUNNING,
        )
    )
    runtime = AgentRuntimeService(repository, model=ScriptedModel([]), enabled=True)
    assert repository.cancel_agent_run_tree(run.id, user_id=USER.id) is not None
    result = SimpleNamespace(
        interruptions=[],
        final_output="too late",
        context_wrapper=SimpleNamespace(usage=SimpleNamespace(total_tokens=1)),
    )

    with pytest.raises(asyncio.CancelledError):
        runtime._finalize_result(
            run=run,
            result=result,
            selected=SimpleNamespace(requested_model="test", actual_model="test"),
            skill=None,
        )

    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.status == AgentRunStatus.CANCELLED
    assert persisted.output_text is None


def test_sdk_runner_calls_granted_memory_tool(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.add_user_memory_item(
        UserMemoryItem(
            user_id=USER.id,
            layer=MemoryLayer.MID_TERM,
            title="Checkout study",
            summary="Checkout research found address editing was the largest usability issue.",
            source_kind="test",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            scope=Scope.PRIVATE,
        )
    )
    model = ScriptedModel(
        [
            [function_call("memory_search", {"query": "checkout address"}, call_id="memory_call")],
            [assistant_message("Address editing is the strongest known issue.")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    answer = runtime.run_sync(
        content="What did we learn about checkout?",
        user=USER,
        thread_id="thread_memory_tool",
        history=[],
    )

    assert answer.content == "Address editing is the strongest known issue."
    assert answer.waiting_approval is False
    assert len(model.calls) == 2
    assert any(event.action == "sdk_tool_completed" for event in repository.audit_events)
    assert _core_event_types(repository, answer.run_id or "") == ["run_started", "run_completed"]
    model.assert_complete()


def test_agentmesh_session_preserves_multiturn_history(tmp_path) -> None:
    repository = _repository(tmp_path)
    model = ScriptedModel(
        [
            [assistant_message("First answer")],
            [assistant_message("Second answer with context")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    first = runtime.run_sync(content="First question", user=USER, thread_id="thread_session", history=[])
    second = runtime.run_sync(content="Follow-up question", user=USER, thread_id="thread_session", history=[])

    assert first.content == "First answer"
    assert second.content == "Second answer with context"
    stored = repository.get_sdk_session("thread_session")
    assert stored is not None
    assert len(stored.items) == 4
    second_input = model.calls[1].input
    assert isinstance(second_input, list)
    assert any("First question" in str(item) for item in second_input)
    assert any("First answer" in str(item) for item in second_input)


def test_ungranted_tool_is_hidden_and_never_executes(tmp_path) -> None:
    repository = _repository(tmp_path)
    model = ScriptedModel(
        [
            [function_call("web_research", {"query": "should stay hidden"}, call_id="hidden_web")],
            [assistant_message("The requested tool is not available.")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    answer = runtime.run_sync(
        content="Use web research",
        user=USER,
        thread_id="thread_hidden_tool",
        history=[],
    )

    assert answer.content == "The requested tool is not available."
    assert not any(event.action == "sdk_tool_completed" for event in repository.audit_events)
    first_call = model.first_call
    assert first_call is not None
    assert "web_research" not in {tool.name for tool in first_call.tools}


def test_rejected_approval_resumes_without_executing_tool(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_rejected_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    model = ScriptedModel(
        [
            [function_call("web_research", {"query": "rejected research"}, call_id="rejected_web")],
            [assistant_message("The user rejected external research.")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    paused = runtime.run_sync(
        content="Research externally",
        user=USER,
        thread_id="thread_reject_tool",
        history=[],
    )

    resumed = runtime.resume_sync(
        paused.run_id or "",
        user=USER,
        decisions={paused.interruptions[0]["call_id"]: False},
    )

    assert resumed.content == "The user rejected external research."
    assert not any(event.action == "sdk_tool_completed" for event in repository.audit_events)
    assert _core_event_types(repository, paused.run_id or "")[-2] == "approval_resolved"


def test_mcp_cleanup_failure_after_resume_marks_run_failed(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_mcp_cleanup_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )

    class FailingExitServer:
        name = "failing-exit"

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            raise RuntimeError("mcp cleanup failed")

        async def list_tools(self, *args, **kwargs):
            return []

    class SequencedMCPFactory:
        def __init__(self):
            self.calls = 0

        def build(self, **_kwargs):
            self.calls += 1
            return [] if self.calls == 1 else [FailingExitServer()]

    model = ScriptedModel(
        [
            [function_call("web_research", {"query": "cleanup"}, call_id="web_cleanup")],
            [assistant_message("completed before cleanup")],
        ]
    )
    runtime = AgentRuntimeService(
        repository,
        model=model,
        enabled=True,
        mcp_factory=SequencedMCPFactory(),  # type: ignore[arg-type]
    )
    paused = runtime.run_sync(
        content="Research with cleanup",
        user=USER,
        thread_id="thread_mcp_cleanup",
        history=[],
    )

    with pytest.raises(RuntimeError, match="mcp cleanup failed"):
        runtime.resume_sync(
            paused.run_id or "",
            user=USER,
            decisions={"web_cleanup": True},
        )

    stored = repository.get_agent_run(paused.run_id or "")
    assert stored is not None
    assert stored.status == "failed"
    assert _core_event_types(repository, stored.id)[-1] == "run_failed"


def test_resumed_failure_marks_run_failed(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_failed_resume_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    model = ScriptedModel(
        [
            [function_call("web_research", {"query": "failure"}, call_id="web_failure")],
            ModelStep.raise_error(RuntimeError("provider failed")),
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    paused = runtime.run_sync(
        content="Research then fail",
        user=USER,
        thread_id="thread_resume_failure",
        history=[],
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        runtime.resume_sync(
            paused.run_id or "",
            user=USER,
            decisions={"web_failure": True},
        )

    stored = repository.get_agent_run(paused.run_id or "")
    assert stored is not None
    assert stored.status == "failed"
    assert _core_event_types(repository, stored.id)[-1] == "run_failed"


def test_each_pending_tool_call_requires_its_own_decision(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_batch_web",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    model = ScriptedModel(
        [
            [
                function_call("web_research", {"query": "first"}, call_id="web_first"),
                function_call("web_research", {"query": "second"}, call_id="web_second"),
            ],
            [assistant_message("Both individually approved calls completed.")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    paused = runtime.run_sync(
        content="Research two topics",
        user=USER,
        thread_id="thread_batch_approval",
        history=[],
    )
    assert {item["call_id"] for item in paused.interruptions} == {"web_first", "web_second"}

    partially_resumed = runtime.resume_sync(
        paused.run_id or "",
        user=USER,
        decisions={"web_first": True},
    )
    assert partially_resumed.waiting_approval is True
    assert [item["call_id"] for item in partially_resumed.interruptions] == ["web_second"]

    completed = runtime.resume_sync(
        paused.run_id or "",
        user=USER,
        decisions={"web_second": True},
    )
    assert completed.content == "Both individually approved calls completed."
    assert model.remaining_steps == 0


def test_personal_agent_surfaces_sdk_approval_in_inbox(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_personal_web_research",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    model = ScriptedModel(
        [
            [function_call("web_research", {"query": "campaign patterns"}, call_id="web_personal")],
            [assistant_message("Approved research answer")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)
    agent = PersonalAgent(repository, agent_runtime=runtime)

    response = agent.handle_chat("Research campaign patterns", user=USER)

    assert response.inbox_items
    item = response.inbox_items[0]
    assert item.item_type == "sdk_tool_approval"
    assert item.metadata["run_id"]
    interruptions = json.loads(item.metadata["interruptions"])
    resumed = runtime.resume_sync(
        item.metadata["run_id"],
        user=USER,
        decisions={interruptions[0]["call_id"]: True},
    )
    assert resumed.content == "Approved research answer"


def test_external_tool_pauses_and_resumes_from_serialized_run_state(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_test_web_research",
            agent_id=USER.personal_agent_id,
            tool_id="tool_web_research",
            granted_by="test",
        )
    )
    model = ScriptedModel(
        [
            [function_call("web_research", {"query": "2026 campaign patterns"}, call_id="web_call")],
            [assistant_message("Research completed after approval.")],
        ]
    )
    runtime = AgentRuntimeService(repository, model=model, enabled=True)

    paused = runtime.run_sync(
        content="Research current campaign patterns",
        user=USER,
        thread_id="thread_web_tool",
        history=[],
    )

    assert paused.waiting_approval is True
    assert paused.run_id is not None
    assert paused.interruptions[0]["name"] == "web_research"
    stored = repository.get_agent_run(paused.run_id)
    assert stored is not None
    assert stored.status == "waiting_approval"
    assert stored.paused_state is not None
    assert model.remaining_steps == 1

    resumed = runtime.resume_sync(
        paused.run_id,
        user=USER,
        decisions={paused.interruptions[0]["call_id"]: True},
    )

    assert resumed.waiting_approval is False
    assert resumed.content == "Research completed after approval."
    assert repository.get_agent_run(paused.run_id).status == "completed"  # type: ignore[union-attr]
    assert _core_event_types(repository, paused.run_id) == [
        "run_started",
        "approval_requested",
        "approval_resolved",
        "run_completed",
    ]
    assert any(event.action == "sdk_tool_completed" for event in repository.audit_events)
    model.assert_complete()


def test_skill_resource_tool_reads_only_approved_roots(tmp_path) -> None:
    repository = _repository(tmp_path)
    skill_dir = tmp_path / "resource-skill"
    references = skill_dir / "references"
    references.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: resource-skill\ndescription: Test\n---\n# Test\n")
    (references / "guide.md").write_text("trusted guide")
    outside = tmp_path / "outside.txt"
    outside.write_text("must not escape")
    skill = SkillDefinition(
        id="skill_resource_test",
        name="resource-skill",
        title="Resource Skill",
        description="Resource test",
        instructions="Read references/guide.md",
        source_path=str(skill_dir / "SKILL.md"),
        source_scope=SkillSourceScope.WORKSPACE,
        content_hash="resource-hash",
    )
    repository.add_chat_thread(
        ChatThread(
            id="thread_resource",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Resource test",
        )
    )
    repository.save_agent_run(
        AgentRun(
            id="run_resource",
            thread_id="thread_resource",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="read resource",
            status=AgentRunStatus.RUNNING,
        )
    )
    tool = build_skill_resource_tool(repository, skill)
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_resource",
        run_id="run_resource",
        approved_resource_hashes=skill_resource_manifest(skill),
    )
    wrapper = SimpleNamespace(context=context)

    output = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"path": "references/guide.md"})))

    payload = json.loads(output)
    assert payload["content"] == "trusted guide"
    assert payload["source"]["source_type"] == "skill_resource"
    assert payload["source"]["run_id"] == context.run_id
    assert context.source_ids == [payload["source"]["id"]]
    (references / "guide.md").write_text("changed after manifest", encoding="utf-8")
    with pytest.raises(PermissionError, match="changed after"):
        asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"path": "references/guide.md"})))
    with pytest.raises(FileNotFoundError):
        asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"path": "../outside.txt"})))


def test_function_and_resource_tools_recheck_project_membership_at_invocation(tmp_path) -> None:
    repository = _repository(tmp_path)
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_revoked_tool_access",
        run_id="run_revoked_tool_access",
    )
    repository.add_chat_thread(
        ChatThread(
            id=context.thread_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            user_id=context.user_id,
            title="Revoked tool access",
        )
    )
    repository.save_agent_run(
        AgentRun(
            id=context.run_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            input_text="invoke governed tools",
            status=AgentRunStatus.RUNNING,
        )
    )
    definition = repository.save_tool_definition(
        ToolDefinition(
            id="tool_revoked_access_probe",
            name="revoked_access_probe",
            description="Verify project membership immediately before execution",
            category="test",
            side_effect="read",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_revoked_access_probe",
            agent_id=USER.personal_agent_id,
            tool_id=definition.id,
            granted_by="test",
        )
    )
    calls: list[str] = []

    class Gateway:
        @staticmethod
        def handlers():
            return {"revoked_access_probe": lambda _context, _arguments: calls.append("function")}

    function_tool = AgentMeshToolFactory(repository, gateway=Gateway()).build(  # type: ignore[arg-type]
        USER,
        allowed_tool_names={definition.name},
    )[0]
    skill_dir = tmp_path / "revoked-resource-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: revoked-resource\ndescription: Test\n---\n")
    (skill_dir / "guide.md").write_text("must not be read after revocation", encoding="utf-8")
    resource_tool = build_skill_resource_tool(
        repository,
        SkillDefinition(
            id="skill_revoked_resource",
            name="revoked-resource",
            title="Revoked Resource",
            description="Revoked resource test",
            instructions="Read guide.md",
            source_path=str(skill_dir / "SKILL.md"),
            source_scope=SkillSourceScope.WORKSPACE,
            content_hash="revoked-resource-hash",
        ),
    )
    project = repository.get_project(context.project_id)
    assert project is not None
    repository.save_project(project.model_copy(update={"member_ids": ["another_user"]}))
    wrapper = SimpleNamespace(context=context)

    with pytest.raises(PermissionError, match="project access was revoked"):
        asyncio.run(function_tool.on_invoke_tool(wrapper, "{}"))
    with pytest.raises(PermissionError, match="project access was revoked"):
        asyncio.run(resource_tool.on_invoke_tool(wrapper, json.dumps({"path": "guide.md"})))

    assert calls == []
    assert context.source_ids == []


def test_function_tool_rechecks_grant_immediately_before_invocation(tmp_path) -> None:
    repository = _repository(tmp_path)
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_revoked_function_grant",
        run_id="run_revoked_function_grant",
    )
    repository.add_chat_thread(
        ChatThread(
            id=context.thread_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            user_id=context.user_id,
            title="Revoked function grant",
        )
    )
    repository.save_agent_run(
        AgentRun(
            id=context.run_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            input_text="invoke after grant revocation",
            status=AgentRunStatus.RUNNING,
        )
    )
    definition = repository.save_tool_definition(
        ToolDefinition(
            id="tool_revoked_function_grant",
            name="revoked_function_grant",
            description="Must stop when its grant is revoked",
            category="test",
            side_effect="read",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    grant = repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_revoked_function_grant",
            agent_id=USER.personal_agent_id,
            tool_id=definition.id,
            granted_by="test",
        )
    )
    calls: list[str] = []

    class Gateway:
        @staticmethod
        def handlers():
            return {definition.name: lambda _context, _arguments: calls.append("called")}

    tool = AgentMeshToolFactory(repository, gateway=Gateway()).build(  # type: ignore[arg-type]
        USER,
        allowed_tool_names={definition.name},
    )[0]
    repository.save_agent_tool_grant(grant.model_copy(update={"enabled": False}))

    with pytest.raises(PermissionError, match="tool grant was revoked"):
        asyncio.run(tool.on_invoke_tool(SimpleNamespace(context=context), "{}"))

    assert calls == []


def test_skill_resource_tool_cannot_cross_registered_wiki_subtree(tmp_path, monkeypatch) -> None:
    repository = _repository(tmp_path)
    skill_dir = tmp_path / "scoped-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: scoped-skill\ndescription: Test\n---\n")
    wiki = tmp_path / "wiki"
    allowed = wiki / "domain-a"
    denied = wiki / "domain-b"
    allowed.mkdir(parents=True)
    denied.mkdir(parents=True)
    (allowed / "guide.md").write_text("allowed", encoding="utf-8")
    (denied / "secret.md").write_text("denied", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = SkillDefinition(
        id="skill_scoped_resource",
        name="scoped-skill",
        title="Scoped Skill",
        description="Scoped resource test",
        instructions="Read the registered Wiki subtree",
        source_path=str(skill_dir / "SKILL.md"),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="scoped-resource-hash",
        metadata={"source": "2C-DesignWiki/domain-a/skills/scoped-skill/SKILL.md"},
    )
    repository.add_chat_thread(
        ChatThread(
            id="thread_scoped_resource",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Scoped resource test",
        )
    )
    repository.save_agent_run(
        AgentRun(
            id="run_scoped_resource",
            thread_id="thread_scoped_resource",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="read scoped resource",
            status=AgentRunStatus.RUNNING,
        )
    )
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_scoped_resource",
        run_id="run_scoped_resource",
    )
    tool = build_skill_resource_tool(repository, skill)
    wrapper = SimpleNamespace(context=context)

    allowed_payload = json.loads(
        asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"path": "guide.md"})))
    )
    assert allowed_payload["content"] == "allowed"
    with pytest.raises(FileNotFoundError):
        asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"path": "domain-b/secret.md"})))


def test_skill_resource_rejects_unrelated_wiki_subtree_with_same_suffix(tmp_path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    wrong_subtree = wiki / "shared-tail"
    wrong_subtree.mkdir(parents=True)
    (wrong_subtree / "secret.md").write_text("wrong subtree", encoding="utf-8")
    package = tmp_path / "suffix-collision-skill"
    package.mkdir()
    (package / "SKILL.md").write_text("---\nname: suffix-collision\ndescription: Test\n---\n", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    skill = SkillDefinition(
        id="skill_suffix_collision",
        name="suffix-collision",
        title="Suffix Collision",
        description="Reject a same-suffix Wiki subtree",
        instructions="Read only the registered Wiki subtree",
        source_path=str(package / "SKILL.md"),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="suffix-collision-hash",
        metadata={"source": "2C-DesignWiki/domain-a/shared-tail/skills/suffix-collision/SKILL.md"},
    )

    assert not (wiki / "domain-a" / "shared-tail").exists()
    assert resolve_skill_resource(skill, "secret.md") is None


def test_builtin_skill_resources_follow_each_registered_wiki_subtree(tmp_path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    boundaries = {
        "generate-research-plan": "jd-design-system-md-v16/horizontal/user-research",
        "query-experiment-conclusions": (
            "jd-design-system-md-v16/product-architecture/plus-and-new-channel"
        ),
        "prd-feasibility": (
            "jd-design-system-md-v16/product-architecture/comprehensive-business/content-ecosystem"
        ),
    }
    for boundary in boundaries.values():
        directory = wiki / boundary
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "boundary-proof.md").write_text(boundary, encoding="utf-8")
    sibling = wiki / "jd-design-system-md-v16/product-architecture/comprehensive-business/other-domain"
    sibling.mkdir(parents=True)
    (sibling / "secret.md").write_text("outside approved subtree", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))
    repository = _repository(tmp_path)
    catalog = SkillCatalogService(repository)
    catalog.reload()

    for skill_name, boundary in boundaries.items():
        skill = catalog.get_by_name(skill_name, USER.personal_agent_id)
        assert skill is not None
        assert resolve_skill_resource(skill, "boundary-proof.md") == (
            wiki / boundary / "boundary-proof.md"
        ).resolve()

    prd = catalog.get_by_name("prd-feasibility", USER.personal_agent_id)
    assert prd is not None
    assert resolve_skill_resource(
        prd,
        "jd-design-system-md-v16/product-architecture/comprehensive-business/other-domain/secret.md",
    ) is None


def test_untrusted_skill_metadata_cannot_expand_the_configured_wiki_root(tmp_path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    escaped = tmp_path / "escaped"
    escaped.mkdir()
    (escaped / "secret.md").write_text("must remain outside", encoding="utf-8")
    forged_workspace_root = wiki / "escaped"
    forged_workspace_root.mkdir()
    (forged_workspace_root / "secret.md").write_text("workspace metadata is untrusted", encoding="utf-8")
    package = tmp_path / "package"
    package.mkdir()
    (package / "SKILL.md").write_text("---\nname: unsafe\ndescription: Unsafe\n---\n", encoding="utf-8")
    monkeypatch.setenv("AGENTMESH_WIKI_ROOT", str(wiki))

    traversal = SkillDefinition(
        id="skill_wiki_traversal",
        name="wiki-traversal",
        title="Wiki Traversal",
        description="Traversal attempt",
        instructions="Read a forged Wiki boundary",
        source_path=str(package / "SKILL.md"),
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="wiki-traversal-hash",
        metadata={"source": "2C-DesignWiki/../escaped/skills/wiki-traversal/SKILL.md"},
    )
    workspace_skill = traversal.model_copy(
        update={
            "id": "skill_workspace_wiki",
            "name": "workspace-wiki",
            "source_scope": SkillSourceScope.WORKSPACE,
            "metadata": {"source": "2C-DesignWiki/escaped/skills/workspace-wiki/SKILL.md"},
        }
    )

    assert resolve_skill_resource(traversal, "secret.md") is None
    assert resolve_skill_resource(workspace_skill, "secret.md") is None


def test_unsafe_oversized_tool_output_is_not_persisted_as_artifact(tmp_path) -> None:
    repository = _repository(tmp_path)
    definition = repository.save_tool_definition(
        ToolDefinition(
            id="tool_unsafe_large",
            name="unsafe_large",
            description="Unsafe large output",
            category="test",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_unsafe_large",
            agent_id=USER.personal_agent_id,
            tool_id=definition.id,
            granted_by="test",
        )
    )

    class Gateway:
        @staticmethod
        def handlers():
            return {"unsafe_large": lambda _context, _arguments: "x" * 60_000 + "\nAuthorization: Bearer tail-secret"}

    factory = AgentMeshToolFactory(repository, gateway=Gateway())  # type: ignore[arg-type]
    tool = next(item for item in factory.build(USER) if item.name == "unsafe_large")
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_unsafe_large",
        run_id="run_unsafe_large",
    )
    repository.save_agent_run(
        AgentRun(
            id=context.run_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            input_text="unsafe output test",
            status=AgentRunStatus.RUNNING,
        )
    )

    output = asyncio.run(tool.on_invoke_tool(SimpleNamespace(context=context), "{}"))

    assert output == "Tool output was withheld by AgentMesh policy."
    with repository._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifacts WHERE run_id = ?", (context.run_id,)).fetchone()[0] == 0


def test_source_shaped_tool_records_do_not_grant_unpersisted_or_foreign_sources(tmp_path) -> None:
    repository = _repository(tmp_path)
    context = AgentMeshRunContext(
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        thread_id="thread_source_shape",
        run_id="run_source_shape",
    )
    repository.add_chat_thread(
        ChatThread(
            id=context.thread_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            user_id=context.user_id,
            title="Source-shaped records",
        )
    )
    repository.save_agent_run(
        AgentRun(
            id=context.run_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            input_text="return ordinary records",
            status=AgentRunStatus.RUNNING,
        )
    )
    foreign = repository.add_source(
        Source(
            id="src_foreign_shape",
            title="Foreign source",
            source_type="web_page",
            reference="https://example.test/foreign",
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            user_id="another_user",
            run_id=context.run_id,
        )
    )
    definition = repository.save_tool_definition(
        ToolDefinition(
            id="tool_source_shape",
            name="source_shape",
            description="Return records that happen to look like Source objects",
            category="test",
            side_effect="read",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id="grant_source_shape",
            agent_id=USER.personal_agent_id,
            tool_id=definition.id,
            granted_by="test",
        )
    )

    class Gateway:
        @staticmethod
        def handlers():
            return {
                "source_shape": lambda _context, _arguments: {
                    "records": [
                        {
                            "id": "src_not_persisted",
                            "title": "Ordinary row",
                            "source_type": "web_page",
                            "reference": "row://not-a-citation",
                        },
                        foreign.model_dump(mode="json"),
                    ]
                }
            }

    tool = AgentMeshToolFactory(repository, gateway=Gateway()).build(  # type: ignore[arg-type]
        USER,
        allowed_tool_names={definition.name},
    )[0]

    asyncio.run(tool.on_invoke_tool(SimpleNamespace(context=context), "{}"))

    assert context.source_ids == []


def test_source_identity_cannot_be_reassigned_to_another_run_or_project(tmp_path) -> None:
    repository = _repository(tmp_path)
    original = repository.add_source(
        Source(
            id="src_immutable_identity",
            title="Original source",
            source_type="web_page",
            reference="https://example.test/original",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            run_id="run_original",
            skill_id="skill_original",
        )
    )

    with pytest.raises(ValueError, match="source_identity_conflict"):
        repository.add_source(
            original.model_copy(
                update={
                    "project_id": "project_other",
                    "run_id": "run_other",
                    "skill_id": "skill_other",
                }
            )
        )

    assert repository.get_source(original.id) == original
