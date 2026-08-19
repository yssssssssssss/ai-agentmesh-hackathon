from __future__ import annotations

import pytest
from agents.testing import ScriptedModel, assistant_message

from agentmesh.agent_runtime.model_factory import AgentMeshModelFactory, SelectedSDKModel
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agent_runtime.settings import strict_tools_enabled
from agentmesh.agent_runtime.trace_processor import AgentMeshTraceProcessor
from agentmesh.agents import PersonalAgent
from agentmesh.models import AgentRun, AgentRunStatus, SkillActivationPolicy, SkillDefinition, SkillSourceScope
from agentmesh.seed import USER
from agentmesh.skill_runtime.resources import build_skill_resource_tool
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore


def _skill() -> SkillDefinition:
    return SkillDefinition(
        id="skill_generate_research_plan",
        name="generate-research-plan",
        title="Generate Research Plan",
        description="Turn a research request into a decision-ready plan.",
        instructions="# Generate Research Plan\n\nAsk for missing goals before producing a plan.",
        source_path="/virtual/generate-research-plan/SKILL.md",
        source_scope=SkillSourceScope.BUILTIN,
        content_hash="abc123",
        activation_policy=SkillActivationPolicy.EXPLICIT_ONLY,
    )


def test_sdk_runtime_executes_general_chat_with_scripted_model(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "runtime.sqlite3")
    model = ScriptedModel([[assistant_message("SDK general answer")]])
    runtime = AgentRuntimeService(repository=repository, model=model, enabled=True)

    answer = runtime.run_sync(
        content="hello",
        user=USER,
        thread_id="thread_sdk_general",
        history=[],
    )

    assert answer.content == "SDK general answer"
    assert answer.llm_used is True
    assert answer.skill_name is None
    assert model.first_call is not None
    assert "ordinary conversation" in (model.first_call.system_instructions or "")
    model.assert_complete()


def test_sdk_runtime_injects_activated_skill_instructions(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "runtime.sqlite3")
    model = ScriptedModel([[assistant_message("SDK skill answer")]])
    runtime = AgentRuntimeService(repository=repository, model=model, enabled=True)
    skill = _skill()

    answer = runtime.run_sync(
        content="plan a checkout usability study",
        user=USER,
        thread_id="thread_sdk_skill",
        history=[],
        skill=skill,
    )

    assert answer.content == "SDK skill answer"
    assert answer.skill_name == "generate-research-plan"
    assert model.first_call is not None
    instructions = model.first_call.system_instructions or ""
    assert "Generate Research Plan" in instructions
    assert "Ask for missing goals" in instructions
    assert "cannot grant itself additional tools" in instructions
    assert "/virtual/generate-research-plan" not in instructions
    model.assert_complete()


def test_sdk_runtime_announces_registered_wiki_to_the_activated_skill(
    tmp_path,
    configure_pilot_wiki,
) -> None:
    configure_pilot_wiki(tmp_path / "wiki")
    repository = SQLiteStore(tmp_path / "wiki-instructions.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("generate-research-plan", USER.personal_agent_id)
    assert skill is not None

    instructions = AgentRuntimeService._instructions(skill)

    assert "Registered Wiki subtree: available" in instructions
    assert "call read_skill_resource directly" in instructions
    assert str(tmp_path) not in instructions


def test_skill_resource_tool_batches_reads_against_the_shared_tool_budget(tmp_path) -> None:
    tool = build_skill_resource_tool(SQLiteStore(tmp_path / "batch-resource.sqlite3"), _skill())

    paths = tool.params_json_schema["properties"]["paths"]
    assert tool.params_json_schema["required"] == ["paths"]
    assert paths["type"] == "array"
    assert paths["minItems"] == 1
    assert paths["maxItems"] == 12
    assert "shared 24-call budget" in tool.description


def test_orchestration_projection_preserves_real_model_provenance(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "orchestration-projection.sqlite3")
    model = ScriptedModel([])
    runtime = AgentRuntimeService(repository=repository, model=model, enabled=True)
    run = AgentRun(
        id="run_orchestration_projection",
        thread_id="thread_orchestration_projection",
        user_id=USER.id,
        workspace_id=USER.workspace_id,
        project_id=USER.default_project_id,
        input_text="create a research plan and synthesize it",
        status=AgentRunStatus.COMPLETED,
        project_chat=True,
    )

    runtime.project_orchestration_output(
        run,
        "synthesized result",
        selected=SelectedSDKModel(
            model=model,
            requested_model="gpt-primary",
            actual_model="gpt-5.2",
        ),
    )

    trace = repository.list_thread_messages(run.thread_id)[-1].workflow_trace
    assert trace is not None
    assert trace.source == "orchestration"
    assert trace.selected_workflow == "skill_orchestration"
    assert trace.llm_used is True
    assert trace.requested_provider == "openai_agents_sdk"
    assert trace.actual_provider == "openai_agents_sdk"
    assert trace.requested_model == "gpt-primary"
    assert trace.actual_model == "gpt-5.2"
    assert trace.provider_mode == "real"


def test_personal_agent_routes_general_and_catalog_skill_through_sdk(tmp_path, configure_pilot_wiki) -> None:
    configure_pilot_wiki(tmp_path)
    repository = SQLiteStore(tmp_path / "agent.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    model = ScriptedModel(
        [
            [assistant_message("private sdk chat")],
            [assistant_message("prioritized by sdk")],
        ]
    )
    runtime = AgentRuntimeService(repository=repository, model=model, enabled=True)
    agent = PersonalAgent(repository, agent_runtime=runtime, skill_catalog=catalog)

    general = agent.handle_chat("hello from runtime v2", user=USER)
    prioritized = agent.handle_chat("$issue-prioritization first issue, second issue", user=USER)

    assert general.assistant_message.content == "private sdk chat"
    assert general.task is None
    assert general.workflow_trace is not None
    assert general.workflow_trace.source == "chat"
    assert general.workflow_trace.requested_provider == "openai_agents_sdk"
    assert prioritized.assistant_message.content == "prioritized by sdk"
    assert prioritized.workflow_trace is not None
    assert prioritized.workflow_trace.source == "skill"
    assert prioritized.workflow_trace.selected_workflow == "$issue-prioritization"
    assert len(model.calls) == 2
    model.assert_complete()


def test_model_factory_uses_existing_openai_compatible_configuration(monkeypatch, tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "models.sqlite3")
    monkeypatch.setenv("AI_API_URL", "https://gateway.example/v1/chat/completions")
    monkeypatch.setenv("AI_API_KEY", "secret-not-logged")
    monkeypatch.setenv("AI_MODEL", "internal-tool-model")

    selected = AgentMeshModelFactory(repository).for_user(USER)

    assert selected is not None
    assert selected.actual_model == "internal-tool-model"
    assert str(selected.model._client.base_url) == "https://gateway.example/v1/"  # type: ignore[attr-defined]


def test_model_factory_rejects_unsupported_api_style(monkeypatch, tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "models-unsupported.sqlite3")
    monkeypatch.setenv("AI_API_URL", "https://gateway.example/v1/responses")
    monkeypatch.setenv("AI_API_KEY", "secret-not-logged")
    monkeypatch.setenv("AI_MODEL", "responses-only-model")
    monkeypatch.setenv("AI_API_STYLE", "responses")

    with pytest.raises(ValueError, match="does not support API style 'responses'"):
        AgentMeshModelFactory(repository).for_user(USER)


def test_trace_processor_persists_only_whitelisted_metadata(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "trace.sqlite3")
    processor = AgentMeshTraceProcessor(repository)

    class TraceStub:
        trace_id = "trace_local"
        name = "skill:test"

        @staticmethod
        def export():
            return {
                "metadata": {
                    "run_id": "run_1",
                    "user_id": USER.id,
                    "workspace_id": USER.workspace_id,
                    "project_id": USER.default_project_id,
                    "secret": "must-not-persist",
                }
            }

    processor.on_trace_end(TraceStub())

    event = repository.audit_events[-1]
    assert event.action == "sdk_trace_completed"
    assert event.target_id == "run_1"
    assert "secret" not in event.metadata
    assert "must-not-persist" not in event.model_dump_json()


def test_sdk_strict_tool_compatibility_flag(monkeypatch) -> None:
    monkeypatch.delenv("AGENTMESH_SDK_STRICT_TOOLS", raising=False)
    assert strict_tools_enabled() is True
    monkeypatch.setenv("AGENTMESH_SDK_STRICT_TOOLS", "false")
    assert strict_tools_enabled() is False


def test_runtime_flag_is_disabled_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AGENTMESH_AGENT_RUNTIME", raising=False)
    runtime = AgentRuntimeService(repository=SQLiteStore(tmp_path / "runtime.sqlite3"))

    assert runtime.enabled is False
