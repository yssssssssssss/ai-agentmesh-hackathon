#!/usr/bin/env python3
"""Secret-safe OpenAI Agents SDK compatibility smoke for the configured internal model."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agents import Agent, RunConfig, Runner, function_tool  # noqa: E402

from agentmesh.agent_runtime.model_factory import AgentMeshModelFactory  # noqa: E402
from agentmesh.agent_runtime.trace_processor import configure_agentmesh_tracing  # noqa: E402
from agentmesh.seed import USER  # noqa: E402
from agentmesh.store import store  # noqa: E402


@function_tool(strict_mode=False)
def agentmesh_sdk_probe(value: str) -> str:
    """Return a fixed marker used only by the Agent Runtime compatibility smoke."""
    del value
    return "agentmesh-tool-ok"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default="default")
    args = parser.parse_args()
    configure_agentmesh_tracing(store)
    selected = AgentMeshModelFactory(store).for_model_id(args.model_id)
    if selected is None:
        print(json.dumps({"configured": False, "reason": "model_not_configured"}))
        return 2

    agent = Agent(
        name="AgentMesh SDK smoke",
        instructions=(
            "Call agentmesh_sdk_probe exactly once with value 'probe', then reply with a short confirmation."
        ),
        model=selected.model,
        tools=[agentmesh_sdk_probe],
    )
    result = Runner.run_streamed(
        agent,
        "Run the compatibility probe.",
        max_turns=4,
        run_config=RunConfig(
            workflow_name="agentmesh_sdk_smoke",
            trace_include_sensitive_data=False,
            trace_metadata={"user_id": USER.id, "workspace_id": USER.workspace_id, "project_id": USER.default_project_id},
        ),
    )
    event_counts: dict[str, int] = {}
    tool_called = False
    async for event in result.stream_events():
        event_counts[event.type] = event_counts.get(event.type, 0) + 1
        if event.type == "run_item_stream_event" and getattr(event, "name", "") == "tool_called":
            tool_called = True
    payload = {
        "configured": True,
        "sdk": "openai-agents",
        "requested_model": selected.requested_model,
        "actual_model": selected.actual_model,
        "stream_complete": result.is_complete,
        "tool_called": tool_called,
        "final_output_present": bool(str(result.final_output).strip()),
        "requests": result.context_wrapper.usage.requests,
        "event_counts": event_counts,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if result.is_complete and tool_called and payload["final_output_present"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
