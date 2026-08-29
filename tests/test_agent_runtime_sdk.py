from __future__ import annotations

import asyncio

import httpx
import pytest
from agents import ModelRetryAdvice
from agents.testing import ModelStep, ScriptedModel, assistant_message
from openai.types.responses import ResponseTextDeltaEvent

from agentmesh.agent_runtime.model_factory import AgentMeshModelFactory, SelectedSDKModel
from agentmesh.agent_runtime.model_retry import AtomicStreamModel, ModelStreamRetryExhausted
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.agent_runtime.settings import strict_tools_enabled
from agentmesh.agent_runtime.trace_processor import AgentMeshTraceProcessor
from agentmesh.agents import PersonalAgent
from agentmesh.models import (
    AgentRun,
    AgentRunStatus,
    ChatThread,
    SkillActivationPolicy,
    SkillDefinition,
    SkillSourceScope,
)
from agentmesh.seed import USER, ensure_base_workspace_data
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
    ensure_base_workspace_data(repository)
    repository.save_user(USER)
    repository.add_chat_thread(
        ChatThread(
            id="thread_orchestration_projection",
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            user_id=USER.id,
            title="Projection",
        )
    )
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
        output_text="synthesized result",
        project_chat=True,
    )
    repository.save_agent_run(run)

    runtime.project_orchestration_output(
        run,
        "synthesized result",
        selected=SelectedSDKModel(
            model=model,
            requested_model="gpt-primary",
            actual_model="gpt-5.2",
        ),
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

    messages = repository.list_thread_messages(run.thread_id)
    assert len(messages) == 1
    trace = messages[-1].workflow_trace
    assert trace is not None
    assert trace.source == "orchestration"
    assert trace.selected_workflow == "skill_orchestration"
    assert trace.llm_used is True
    assert trace.requested_provider == "openai_agents_sdk"
    assert trace.actual_provider == "openai_agents_sdk"
    assert trace.requested_model == "gpt-primary"
    assert trace.actual_model == "gpt-5.2"
    assert trace.provider_mode == "real"
    receipt = repository.get_run_output_projection(run.id)
    assert receipt is not None
    assert receipt.assistant_message_id == messages[0].id
    assert receipt.disposition == "message"


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
    monkeypatch.setenv("AGENTMESH_CHAT_LLM_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("AGENTMESH_RESEARCH_SKILL_TIMEOUT_SECONDS", "2")

    selected = AgentMeshModelFactory(repository).for_user(USER)

    assert selected is not None
    assert selected.actual_model == "internal-tool-model"
    assert str(selected.model._client.base_url) == "https://gateway.example/v1/"  # type: ignore[attr-defined]
    assert selected.model._client.timeout == 300  # type: ignore[attr-defined]


def test_model_factory_rejects_unsupported_api_style(monkeypatch, tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "models-unsupported.sqlite3")
    monkeypatch.setenv("AI_API_URL", "https://gateway.example/v1/responses")
    monkeypatch.setenv("AI_API_KEY", "secret-not-logged")
    monkeypatch.setenv("AI_MODEL", "responses-only-model")
    monkeypatch.setenv("AI_API_STYLE", "responses")

    with pytest.raises(ValueError, match="does not support API style 'responses'"):
        AgentMeshModelFactory(repository).for_user(USER)


def test_standard_atomic_stream_model_enables_request_level_network_retries(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "model-stream-retry-settings.sqlite3")
    scripted = ScriptedModel([])
    runtime = AgentRuntimeService(repository=repository, model=scripted, enabled=True)
    selected = SelectedSDKModel(
        model=scripted,
        requested_model="test-model",
        actual_model="test-model",
    )

    agent = runtime._build_agent(
        selected=selected,
        user=USER,
        skill=None,
        model=AtomicStreamModel(scripted),
        allow_skill_activation=False,
    )

    assert agent.model_settings.retry is not None
    assert agent.model_settings.retry.max_retries == 2
    assert agent.model_settings.retry.backoff is not None
    assert agent.model_settings.retry.backoff.initial_delay == 0.5


def test_standard_stream_retry_exhaustion_records_the_provider_root_cause(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "model-stream-retry-exhausted.sqlite3")

    async def interrupted(_call):  # noqa: ANN001, ANN202
        yield ResponseTextDeltaEvent(
            type="response.output_text.delta",
            content_index=0,
            delta="PARTIAL",
            item_id="msg_partial",
            logprobs=[],
            output_index=0,
            sequence_number=0,
        )
        raise httpx.RemoteProtocolError("peer closed incomplete body")

    scripted = ScriptedModel([ModelStep.stream(interrupted) for _ in range(3)])
    runtime = AgentRuntimeService(repository=repository, model=scripted, enabled=True)
    selected = SelectedSDKModel(
        model=scripted,
        requested_model="test-model",
        actual_model="test-model",
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_model_stream_retry_exhausted",
            thread_id="thread_model_stream_retry_exhausted",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="research",
            status=AgentRunStatus.RUNNING,
        )
    )
    agent = runtime._build_agent(
        selected=selected,
        user=USER,
        skill=None,
        model=AtomicStreamModel(scripted),
        allow_skill_activation=False,
    )

    with pytest.raises(ModelStreamRetryExhausted) as captured:
        asyncio.run(runtime._run_streamed(agent, "research", run=run))

    assert captured.value.root_error_code == "RemoteProtocolError"
    assert captured.value.attempts == 3
    assert len(scripted.calls) == 3
    event = repository.list_agent_run_events(run.id)[-1]
    assert event.event_type == "model_stream_retry_exhausted"
    assert event.payload == {"error_code": "RemoteProtocolError", "attempts": 3}


def test_standard_stream_retry_retries_provider_transient_errors_before_exhaustion(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "model-provider-retry-exhausted.sqlite3")

    class RateLimitError(Exception):
        pass

    async def rate_limited(_call):  # noqa: ANN001, ANN202
        raise RateLimitError("gateway is temporarily rate limited")
        yield  # pragma: no cover

    scripted = ScriptedModel([ModelStep.stream(rate_limited) for _ in range(3)])
    runtime = AgentRuntimeService(repository=repository, model=scripted, enabled=True)
    selected = SelectedSDKModel(
        model=scripted,
        requested_model="test-model",
        actual_model="test-model",
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_model_provider_retry_exhausted",
            thread_id="thread_model_provider_retry_exhausted",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="research",
            status=AgentRunStatus.RUNNING,
        )
    )
    agent = runtime._build_agent(
        selected=selected,
        user=USER,
        skill=None,
        model=AtomicStreamModel(scripted),
        allow_skill_activation=False,
    )

    with pytest.raises(ModelStreamRetryExhausted) as captured:
        asyncio.run(runtime._run_streamed(agent, "research", run=run))

    assert captured.value.root_error_code == "RateLimitError"
    assert captured.value.attempts == 3
    assert len(scripted.calls) == 3


def test_standard_stream_retry_respects_an_explicit_provider_veto(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "model-provider-retry-veto.sqlite3")

    class RateLimitError(Exception):
        pass

    async def rate_limited(_call):  # noqa: ANN001, ANN202
        raise RateLimitError("provider says not to retry")
        yield  # pragma: no cover

    class ProviderVetoModel(ScriptedModel):
        def get_retry_advice(self, _request):  # noqa: ANN001, ANN201
            return ModelRetryAdvice(suggested=False, reason="provider veto")

    scripted = ProviderVetoModel([ModelStep.stream(rate_limited)])
    runtime = AgentRuntimeService(repository=repository, model=scripted, enabled=True)
    selected = SelectedSDKModel(
        model=scripted,
        requested_model="test-model",
        actual_model="test-model",
    )
    run = repository.save_agent_run(
        AgentRun(
            id="run_model_provider_retry_veto",
            thread_id="thread_model_provider_retry_veto",
            user_id=USER.id,
            workspace_id=USER.workspace_id,
            project_id=USER.default_project_id,
            input_text="research",
            status=AgentRunStatus.RUNNING,
        )
    )
    agent = runtime._build_agent(
        selected=selected,
        user=USER,
        skill=None,
        model=AtomicStreamModel(scripted),
        allow_skill_activation=False,
    )

    with pytest.raises(ModelStreamRetryExhausted) as captured:
        asyncio.run(runtime._run_streamed(agent, "research", run=run))

    assert captured.value.attempts == 1
    assert len(scripted.calls) == 1
    event = repository.list_agent_run_events(run.id)[-1]
    assert event.payload == {"error_code": "RateLimitError", "attempts": 1}


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
