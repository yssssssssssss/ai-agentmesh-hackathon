from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Protocol

from agents import Agent, ModelSettings, RunConfig, Runner
from agents.models.interface import Model
from agents.retry import ModelRetrySettings

from agentmesh.agent_runtime.budget import RunModelBudgetMeter
from agentmesh.memory_context.request_budget import ContextRequestBudgetV1, RequestBudgetModel
from agentmesh.tool_runtime.guardrails import unsafe_tool_output_reason

_COMPACTION_INSTRUCTIONS = """Summarize the supplied earlier conversation for a future assistant.
Preserve goals, constraints, decisions, unresolved questions, referenced sources, active Skill names, and important tool outcomes.
Do not add facts. Return concise Markdown only.
"""


class CompactionSession(Protocol):
    async def snapshot(self) -> tuple[list[dict], int]: ...
    def validate_handoff(self, expected_version: int) -> None: ...
    def remaining_seconds(self, maximum: float) -> float: ...
    async def replace_items(self, items: list[dict], *, expected_version: int) -> bool: ...


def _tool_spans(items: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    calls: dict[str, int] = {}
    outputs: dict[str, int] = {}
    for index, item in enumerate(items):
        if item.get('type') == 'function_call':
            calls.setdefault(item['call_id'], index)
        for call in item.get('tool_calls') or []:
            calls.setdefault(call['id'], index)
        if item.get('type') == 'function_call_output':
            outputs[item['call_id']] = index
        elif item.get('role') == 'tool':
            outputs[item['tool_call_id']] = index
    return calls, outputs


def _recent_boundary(items: list[dict], keep_recent_items: int) -> int:
    boundary = max(0, len(items) - keep_recent_items)
    calls, outputs = _tool_spans(items)
    # Move the cut back across parallel/interleaved call-result units. Unfinished
    # calls stay recent; summarizing them would erase a still-pending operation.
    while True:
        earlier = min((index for call_id, index in calls.items()
                       if index < boundary and outputs.get(call_id, len(items)) >= boundary), default=boundary)
        if earlier == boundary:
            return boundary
        boundary = earlier


def _request_boundary(items: list[dict], request_fits: Callable[[list[dict]], bool]) -> int:
    calls, outputs = _tool_spans(items)
    # Reserve the existing 8 KiB summary limit with worst-case ordinary JSON
    # escaping. The actual summary is checked again before a durable replacement.
    reserve = {'role': 'assistant', 'content': 'Previous conversation summary:\n' + '"' * 8000}
    for index, item in enumerate(items):
        if index == 0 or item.get('role') != 'user':
            continue
        if any(start < index <= outputs.get(call_id, len(items)) for call_id, start in calls.items()):
            continue
        if request_fits([reserve, *items[index:]]):
            return index
    return 0


async def compact_session_if_needed(
    session: CompactionSession,
    model: Model,
    *,
    trigger_tokens: int = 60_000,
    keep_recent_items: int = 20,
    on_usage: Callable[[int | None], None] | None = None,
    run_meter: RunModelBudgetMeter | None = None,
    defer_delivery: bool = False,
    timeout_seconds: float = 90,
    request_fits: Callable[[list[dict]], bool] | None = None,
) -> bool:
    if trigger_tokens < 1 or keep_recent_items < 1 or not 0 < timeout_seconds <= 90:
        raise ValueError('compaction limits must be positive')
    items, version = await session.snapshot()
    if request_fits is not None:
        if request_fits(items):
            return False
        boundary = _request_boundary(items, request_fits)
    else:
        if len(items) <= keep_recent_items:
            return False
        estimated_tokens = len(json.dumps(items, ensure_ascii=False, default=str).encode('utf-8')) + 1024
        if estimated_tokens < trigger_tokens:
            return False
        boundary = _recent_boundary(items, keep_recent_items)
    if boundary == 0:
        return False
    older = items[:boundary]
    recent = items[boundary:]
    guarded = RequestBudgetModel(model, model_id='session-compactor', budget=ContextRequestBudgetV1(
        max_tokens=128000, max_output_tokens=2000,
    ), on_request=lambda _request: session.validate_handoff(version), defer_delivery=defer_delivery, run_meter=run_meter)
    compactor = Agent(
        name="AgentMesh session compactor",
        instructions=_COMPACTION_INSTRUCTIONS,
        model=guarded,
        model_settings=ModelSettings(max_tokens=2000, retry=ModelRetrySettings(max_retries=0)),
    )
    async with asyncio.timeout(session.remaining_seconds(timeout_seconds)):
        result = await Runner.run(
            compactor,
            "Conversation items to summarize:\n" + json.dumps(older, ensure_ascii=False, default=str),
            max_turns=1,
            run_config=RunConfig(
                workflow_name="agentmesh_session_compaction",
                trace_include_sensitive_data=False,
                tracing_disabled=True,
            ),
        )
    if on_usage is not None:
        on_usage(result.context_wrapper.usage.total_tokens or None)
    summary = str(result.final_output)
    if len(summary.encode('utf-8')) > 8000 or unsafe_tool_output_reason(summary):
        return False
    summary_item = {
        "role": "assistant",
        "content": "Previous conversation summary:\n" + summary,
    }
    replacement = [summary_item, *recent]
    if request_fits is not None and not request_fits(replacement):
        return False
    return await session.replace_items(replacement, expected_version=version)
