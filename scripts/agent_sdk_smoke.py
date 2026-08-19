#!/usr/bin/env python3
"""Secret-safe OpenAI Agents SDK compatibility smoke for configured models."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agents import Agent, ModelSettings, RunConfig, Runner, function_tool  # noqa: E402

from agentmesh.agent_runtime.model_factory import AgentMeshModelFactory, SelectedSDKModel  # noqa: E402
from agentmesh.agent_runtime.trace_processor import configure_agentmesh_tracing  # noqa: E402
from agentmesh.llm import model_config_from_env, normalize_model_id  # noqa: E402
from agentmesh.seed import USER  # noqa: E402
from agentmesh.store import store  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_CONFIGURED = 2
REQUESTED_PROVIDER = "openai_agents_sdk"
SDK_API_STYLE = "chat_completions"
SDK_PROVIDER_TYPES = {"OpenAIChatCompletionsModel", "JSONObjectChatCompletionsModel"}


class ProbeIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str
    deliverables: list[str]


class ProbePlanNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    skill_name: str
    depends_on: list[str]


class ProbePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[ProbePlanNode]


class ProbeNodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    summary: str


class ProbeSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    node_ids: list[str]


@function_tool(strict_mode=False)
def agentmesh_sdk_probe(value: str) -> str:
    """Return a fixed marker used only by the Agent Runtime compatibility smoke."""
    del value
    return "agentmesh-tool-ok"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--model-id", help="probe one configured model (default: default)")
    selection.add_argument(
        "--all-configured",
        action="store_true",
        help="probe every configured SDK-compatible model listed in AGENTMESH_MODELS",
    )
    return parser


def configured_sdk_model_ids() -> tuple[list[str], list[dict[str, str]]]:
    listed = [normalize_model_id(item) for item in os.getenv("AGENTMESH_MODELS", "").split(",") if item.strip()]
    model_ids = list(dict.fromkeys(listed))
    compatible: list[str] = []
    skipped: list[dict[str, str]] = []
    for model_id in model_ids:
        config = model_config_from_env(model_id)
        if config is None:
            skipped.append({"model_id": model_id, "reason": "not_configured"})
        elif config["api_style"] != SDK_API_STYLE:
            skipped.append({"model_id": model_id, "reason": "sdk_incompatible"})
        else:
            compatible.append(model_id)
    return compatible, skipped


def _run_config(phase: str) -> RunConfig:
    return RunConfig(
        workflow_name=f"agentmesh_sdk_smoke_{phase}",
        trace_include_sensitive_data=False,
        trace_metadata={
            "user_id": USER.id,
            "workspace_id": USER.workspace_id,
            "project_id": USER.default_project_id,
        },
    )


def _usage(result: Any) -> tuple[int, int]:
    usage = result.context_wrapper.usage
    return int(usage.requests), int(usage.total_tokens)


def _valid_text(value: str) -> bool:
    return bool(value.strip())


async def _run_intent(selected: SelectedSDKModel) -> tuple[bool, Any]:
    agent = Agent(
        name="AgentMesh SDK smoke Intent",
        instructions="Return a structured intent for the supplied synthetic design request. Do not call tools.",
        model=selected.model,
        tools=[],
        output_type=ProbeIntent,
    )
    result = await Runner.run(
        agent,
        "The user wants a checkout usability study. Return its goal and at least one deliverable.",
        max_turns=2,
        run_config=_run_config("intent"),
    )
    output = result.final_output
    passed = isinstance(output, ProbeIntent) and _valid_text(output.goal) and bool(output.deliverables)
    return passed, result


async def _run_plan(selected: SelectedSDKModel) -> tuple[bool, Any]:
    agent = Agent(
        name="AgentMesh SDK smoke Plan",
        instructions=(
            "Return a structured two-node plan. Use node IDs 'research' and 'synthesis'. "
            "The synthesis node must depend on research. Do not call tools."
        ),
        model=selected.model,
        tools=[],
        output_type=ProbePlan,
    )
    result = await Runner.run(
        agent,
        "Plan a synthetic checkout usability study with a research node followed by synthesis.",
        max_turns=2,
        run_config=_run_config("plan"),
    )
    output = result.final_output
    node_ids: set[str] = set()
    synthesis: ProbePlanNode | None = None
    if isinstance(output, ProbePlan):
        node_ids = {node.node_id for node in output.nodes}
        synthesis = next((node for node in output.nodes if node.node_id == "synthesis"), None)
    passed = node_ids == {"research", "synthesis"} and synthesis is not None and "research" in synthesis.depends_on
    return passed, result


async def _run_node(selected: SelectedSDKModel, node_id: str) -> tuple[bool, Any]:
    agent = Agent(
        name=f"AgentMesh SDK smoke Node {node_id}",
        instructions=f"Return a structured node result whose node_id is exactly '{node_id}'. Do not call tools.",
        model=selected.model,
        tools=[],
        output_type=ProbeNodeResult,
    )
    result = await Runner.run(
        agent,
        f"Complete the synthetic {node_id} node with a short summary.",
        max_turns=2,
        run_config=_run_config(f"node_{node_id}"),
    )
    output = result.final_output
    passed = isinstance(output, ProbeNodeResult) and output.node_id == node_id and _valid_text(output.summary)
    return passed, result


async def _run_synthesis(selected: SelectedSDKModel) -> tuple[dict[str, bool], Any, dict[str, int]]:
    agent = Agent(
        name="AgentMesh SDK smoke Synthesis",
        instructions=(
            "Call agentmesh_sdk_probe exactly once with value 'probe'. Then return a structured synthesis "
            "with a non-empty summary and node_ids containing 'research' and 'evidence'."
        ),
        model=selected.model,
        model_settings=ModelSettings(tool_choice="required"),
        tools=[agentmesh_sdk_probe],
        output_type=ProbeSynthesis,
    )
    result = Runner.run_streamed(
        agent,
        "Synthesize the two synthetic node results.",
        max_turns=4,
        run_config=_run_config("synthesis"),
    )
    event_counts: dict[str, int] = {}
    tool_called = False
    async for event in result.stream_events():
        event_counts[event.type] = event_counts.get(event.type, 0) + 1
        if event.type == "run_item_stream_event" and getattr(event, "name", "") == "tool_called":
            tool_called = True
    output = result.final_output
    synthesis_ok = (
        isinstance(output, ProbeSynthesis)
        and _valid_text(output.summary)
        and {"research", "evidence"}.issubset(output.node_ids)
    )
    return {
        "structured_synthesis": synthesis_ok,
        "streaming": bool(result.is_complete and event_counts),
        "tool_call": tool_called,
    }, result, event_counts


async def _run_cancellation(selected: SelectedSDKModel) -> bool:
    agent = Agent(
        name="AgentMesh SDK smoke Cancellation",
        instructions="Return a short acknowledgement.",
        model=selected.model,
        tools=[],
    )
    result = Runner.run_streamed(
        agent,
        "This synthetic run will be cancelled immediately.",
        max_turns=2,
        run_config=_run_config("cancellation"),
    )
    result.cancel()
    async for _event in result.stream_events():
        pass
    return bool(result.is_complete)


async def run_model_smoke(selected: SelectedSDKModel) -> dict[str, object]:
    intent_ok, intent_result = await _run_intent(selected)
    plan_ok, plan_result = await _run_plan(selected)
    node_runs = await asyncio.gather(
        _run_node(selected, "research"),
        _run_node(selected, "evidence"),
    )
    synthesis_checks, synthesis_result, event_counts = await _run_synthesis(selected)
    cancellation_ok = await _run_cancellation(selected)

    measured_results = [intent_result, plan_result, *(result for _passed, result in node_runs), synthesis_result]
    usage = [_usage(result) for result in measured_results]
    requests = sum(item[0] for item in usage)
    total_tokens = sum(item[1] for item in usage)
    actual_provider = type(selected.model).__name__
    checks = {
        "structured_intent": intent_ok,
        "structured_plan": plan_ok,
        "parallel_node_results": all(passed for passed, _result in node_runs),
        **synthesis_checks,
        "usage": requests > 0,
        "cancellation": cancellation_ok,
        "provider_provenance": actual_provider in SDK_PROVIDER_TYPES,
    }
    passed = all(checks.values())
    return {
        "configured": True,
        "sdk": "openai-agents",
        "requested_provider": REQUESTED_PROVIDER,
        "actual_provider": actual_provider,
        "requested_model": selected.requested_model,
        "actual_model": selected.actual_model,
        "structured_output_mode": selected.structured_output_mode.value,
        "stream_complete": synthesis_checks["streaming"],
        "tool_called": synthesis_checks["tool_call"],
        "final_output_present": synthesis_checks["structured_synthesis"],
        "requests": requests,
        "total_tokens": total_tokens,
        "event_counts": event_counts,
        "checks": checks,
        "passed": passed,
    }


def _safe_failure(model_id: str, error: BaseException, selected: SelectedSDKModel | None = None) -> dict[str, object]:
    return {
        "configured": True,
        "sdk": "openai-agents",
        "requested_provider": REQUESTED_PROVIDER,
        "actual_provider": type(selected.model).__name__ if selected is not None else "unknown",
        "requested_model": selected.requested_model if selected is not None else model_id,
        "actual_model": selected.actual_model if selected is not None else "unknown",
        "structured_output_mode": selected.structured_output_mode.value if selected is not None else "unknown",
        "error_code": type(error).__name__,
        "checks": {},
        "passed": False,
    }


async def _probe_model(factory: AgentMeshModelFactory, model_id: str) -> dict[str, object] | None:
    selected: SelectedSDKModel | None = None
    try:
        selected = factory.for_model_id(model_id)
        if selected is None:
            return None
        return await run_model_smoke(selected)
    except Exception as error:
        return _safe_failure(model_id, error, selected)


async def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    factory = AgentMeshModelFactory(store)

    if not args.all_configured:
        model_id = args.model_id or "default"
        configure_agentmesh_tracing(store)
        result = await _probe_model(factory, model_id)
        if result is None:
            print(json.dumps({"configured": False, "reason": "model_not_configured"}, sort_keys=True))
            return EXIT_NOT_CONFIGURED
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return EXIT_OK if result["passed"] else EXIT_FAILED

    model_ids, skipped = configured_sdk_model_ids()
    if not model_ids:
        print(
            json.dumps(
                {
                    "configured": False,
                    "mode": "all_configured",
                    "reason": "no_sdk_compatible_models_configured",
                    "models": [],
                    "skipped": skipped,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return EXIT_NOT_CONFIGURED

    configure_agentmesh_tracing(store)
    results = [await _probe_model(factory, model_id) for model_id in model_ids]
    model_results = [
        result if result is not None else _safe_failure(model_id, RuntimeError())
        for model_id, result in zip(model_ids, results, strict=True)
    ]
    passed = all(bool(result["passed"]) for result in model_results)
    print(
        json.dumps(
            {
                "configured": True,
                "mode": "all_configured",
                "models": model_results,
                "skipped": skipped,
                "passed": passed,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return EXIT_OK if passed else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
