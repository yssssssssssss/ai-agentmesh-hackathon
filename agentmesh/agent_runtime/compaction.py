from __future__ import annotations

import json

from agents import Agent, RunConfig, Runner
from agents.models.interface import Model

from agentmesh.agent_runtime.session import AgentMeshSession

_COMPACTION_INSTRUCTIONS = """Summarize the supplied earlier conversation for a future assistant.
Preserve goals, constraints, decisions, unresolved questions, referenced sources, active Skill names, and important tool outcomes.
Do not add facts. Return concise Markdown only.
"""


async def compact_session_if_needed(
    session: AgentMeshSession,
    model: Model,
    *,
    trigger_tokens: int = 60_000,
    keep_recent_items: int = 20,
) -> bool:
    items, version = await session.snapshot()
    if len(items) <= keep_recent_items:
        return False
    estimated_tokens = len(json.dumps(items, ensure_ascii=False, default=str)) // 4
    if estimated_tokens < trigger_tokens:
        return False
    older = items[:-keep_recent_items]
    recent = items[-keep_recent_items:]
    compactor = Agent(
        name="AgentMesh session compactor",
        instructions=_COMPACTION_INSTRUCTIONS,
        model=model,
    )
    result = await Runner.run(
        compactor,
        "Conversation items to summarize:\n" + json.dumps(older, ensure_ascii=False, default=str),
        max_turns=2,
        run_config=RunConfig(
            workflow_name="agentmesh_session_compaction",
            trace_include_sensitive_data=False,
        ),
    )
    summary_item = {
        "role": "assistant",
        "content": "Previous conversation summary:\n" + str(result.final_output),
    }
    return await session.replace_items([summary_item, *recent], expected_version=version)
