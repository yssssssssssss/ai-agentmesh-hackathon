from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from agents import Agent, ModelSettings, RunConfig, RunContextWrapper, Runner, set_tracing_disabled
from agents.exceptions import AgentsException
from pydantic import BaseModel

from agentmesh.agent_runtime.compaction import compact_session_if_needed
from agentmesh.agent_runtime.guardrails import agentmesh_input_guardrail, agentmesh_output_guardrail
from agentmesh.agent_runtime.model_factory import SelectedSDKModel, selected_model_from_env
from agentmesh.agent_runtime.node_contracts import StandardSkillNodeResultDraftV1
from agentmesh.memory_context.request_budget import (
    ContextRequestBudgetV1,
    ContextRequestError,
    ModelAdmissionError,
    RequestBudgetModel,
    history_request_fits,
)
from agentmesh.models import now_utc
from agentmesh.runner_contracts import (
    RunnerExecutionEnvelope,
    RunnerExecutionEnvelopeV2,
    RunnerExecutionEnvelopeV3,
    RunnerExecutionEventV1,
    RunnerSessionCommitV1,
    runner_envelope_hash,
)
from agentmesh.runner_handoff import RunnerHandoffError, RunnerHandoffModel, RunnerModelHandoff
from agentmesh.runner_session import RunnerSession
from agentmesh.runner_tools import LocalRunnerToolRegistry

set_tracing_disabled(True)


class RunnerExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunnerExecutionResult:
    output_text: str
    requested_model: str
    actual_model: str
    total_tokens: int
    result_payload: dict[str, Any] | None = None
    tool_events: tuple[RunnerExecutionEventV1, ...] = ()
    session_commit: RunnerSessionCommitV1 | None = None


def _verify_envelope(envelope: RunnerExecutionEnvelope) -> None:
    envelope_payload = envelope.model_dump(
        mode="python",
        exclude={"schema_version", "envelope_hash"},
    )
    if runner_envelope_hash(envelope_payload) != envelope.envelope_hash:
        raise RunnerExecutionError("Runner execution envelope hash mismatch")
    if isinstance(envelope, (RunnerExecutionEnvelopeV2, RunnerExecutionEnvelopeV3)) and envelope.session is not None and envelope.session.thread_id != envelope.thread_id:
        raise RunnerExecutionError('Runner Session thread mismatch')


def _model_input(envelope: RunnerExecutionEnvelope) -> str:
    if not envelope.history:
        return envelope.input_text
    history = "\n".join(f"{item.role}: {item.content}" for item in envelope.history)
    return f"<conversation_history>\n{history}\n</conversation_history>\n\nCurrent user request:\n{envelope.input_text}"


async def _run_agent(
    envelope: RunnerExecutionEnvelope,
    *,
    selected: SelectedSDKModel,
    input_value: str,
    output_type: type[BaseModel] | None = None,
    handoff: RunnerModelHandoff | None = None,
) -> tuple[object, int, tuple[RunnerExecutionEventV1, ...], RunnerSessionCommitV1 | None]:
    remaining = (envelope.deadline_at - now_utc()).total_seconds()
    if remaining <= 0:
        raise RunnerExecutionError("Runner execution deadline expired")
    registry = LocalRunnerToolRegistry(handoff=handoff)
    tools = registry.build(envelope.tools)
    if isinstance(envelope, RunnerExecutionEnvelopeV3) and handoff is None:
        raise RunnerHandoffError('runner_model_handoff_required')
    model = RunnerHandoffModel(selected.model, handoff, model_id=selected.actual_model) if handoff else selected.model
    agent = Agent(
        name=envelope.skill.title if envelope.skill is not None else "AgentMesh Personal Agent",
        instructions=envelope.instructions,
        model=RequestBudgetModel(model, model_id=selected.actual_model),
        model_settings=ModelSettings(timeout=remaining),
        tools=tools,
        input_guardrails=[agentmesh_input_guardrail],
        output_guardrails=[agentmesh_output_guardrail],
        output_type=output_type,
    )
    try:
        async with asyncio.timeout(remaining):
            session = None
            total_compaction_tokens = 0
            model_input: str | list[dict] = input_value
            if isinstance(envelope, (RunnerExecutionEnvelopeV2, RunnerExecutionEnvelopeV3)) and envelope.session is not None:
                session = RunnerSession(envelope.session, envelope.deadline_at)
                budget = ContextRequestBudgetV1()
                wrapper = RunContextWrapper(None)
                enabled_tools = await agent.get_all_tools(wrapper)
                instructions = await agent.get_system_prompt(wrapper)

                def request_fits(items: list[dict]) -> bool:
                    return history_request_fits(items, current_input=input_value,
                        system_instructions=instructions, tools=enabled_tools,
                        model_settings=agent.model_settings, model_id=selected.actual_model, budget=budget)

                if not request_fits([]):
                    raise ContextRequestError('context_request_budget_exceeded')

                def record_compaction_usage(tokens: int | None) -> None:
                    nonlocal total_compaction_tokens
                    total_compaction_tokens += tokens or 0

                compactor_model = RunnerHandoffModel(selected.model, handoff, model_id=selected.actual_model,
                                                     stage='compaction') if handoff else selected.model
                await compact_session_if_needed(session, compactor_model, request_fits=request_fits,
                                                on_usage=record_compaction_usage)
                history, _version = await session.snapshot()
                model_input = [*history, {'role': 'user', 'content': input_value}]
            result = await Runner.run(
                agent,
                model_input,
                max_turns=8,
                run_config=RunConfig(
                    workflow_name=(
                        f"runner-skill:{envelope.skill.name}" if envelope.skill is not None else "runner-general-chat"
                    ),
                    group_id=envelope.thread_id,
                    trace_include_sensitive_data=False,
                    trace_metadata={
                        "run_id": envelope.run_id,
                        "runner_lease_id": envelope.lease_id,
                        "operation_kind": envelope.operation_kind,
                    },
                ),
            )
    except TimeoutError as error:
        raise RunnerExecutionError("Runner execution timed out") from error
    except AgentsException as error:
        if isinstance(error.__cause__, ModelAdmissionError):
            raise error.__cause__ from None
        raise
    if result.interruptions:
        raise RunnerExecutionError("Tool approval is not supported by the current Runner slice")
    commit = session.commit(result.to_input_list()) if session is not None else None
    return (result.final_output, result.context_wrapper.usage.total_tokens + total_compaction_tokens,
            tuple(registry.events), commit)


async def execute_standard_direct(
    envelope: RunnerExecutionEnvelope,
    *, handoff: RunnerModelHandoff | None = None,
) -> RunnerExecutionResult:
    _verify_envelope(envelope)
    if envelope.operation_kind != "standard_direct":
        raise RunnerExecutionError("Runner envelope is not a direct execution")
    selected = selected_model_from_env(envelope.model_id)
    if selected is None:
        raise RunnerExecutionError(f"Local model profile is not configured: {envelope.model_id}")
    output, total_tokens, tool_events, session_commit = await _run_agent(
        envelope,
        selected=selected,
        input_value=_model_input(envelope),
        handoff=handoff,
    )
    text = str(output or "").strip()
    if not text:
        raise RunnerExecutionError("Runner model returned an empty result")
    return RunnerExecutionResult(
        output_text=text,
        requested_model=selected.requested_model,
        actual_model=selected.actual_model,
        total_tokens=total_tokens,
        tool_events=tool_events,
        session_commit=session_commit,
    )


async def execute_standard_skill_node(
    envelope: RunnerExecutionEnvelope,
    *, handoff: RunnerModelHandoff | None = None,
) -> RunnerExecutionResult:
    _verify_envelope(envelope)
    if (
        envelope.operation_kind != "standard_skill_node"
        or envelope.skill is None
        or envelope.plan_id is None
        or envelope.node_id is None
        or envelope.node_attempt is None
        or envelope.node_prompt is None
    ):
        raise RunnerExecutionError("Runner node envelope is incomplete")
    selected = selected_model_from_env(envelope.model_id)
    if selected is None:
        raise RunnerExecutionError(f"Local model profile is not configured: {envelope.model_id}")
    output, total_tokens, tool_events, _session_commit = await _run_agent(
        envelope,
        selected=selected,
        input_value=json.dumps(envelope.node_prompt, ensure_ascii=False),
        output_type=StandardSkillNodeResultDraftV1,
        handoff=handoff,
    )
    draft = StandardSkillNodeResultDraftV1.model_validate(output)
    return RunnerExecutionResult(
        output_text=draft.summary,
        requested_model=selected.requested_model,
        actual_model=selected.actual_model,
        total_tokens=total_tokens,
        result_payload=draft.model_dump(mode="json"),
        tool_events=tool_events,
    )


async def execute_runner_envelope(
    envelope: RunnerExecutionEnvelope,
    *, handoff: RunnerModelHandoff | None = None,
) -> RunnerExecutionResult:
    if envelope.operation_kind == "standard_direct":
        return await execute_standard_direct(envelope, handoff=handoff)
    if envelope.operation_kind == "standard_skill_node":
        return await execute_standard_skill_node(envelope, handoff=handoff)
    raise RunnerExecutionError(f"Unsupported Runner operation: {envelope.operation_kind}")
