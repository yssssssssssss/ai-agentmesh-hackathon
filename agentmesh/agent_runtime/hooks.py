from __future__ import annotations

from agents.lifecycle import RunHooksBase

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.models import AgentPlanningMode
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController
from agentmesh.store import SQLiteStore


class AgentMeshRunHooks(RunHooksBase[AgentMeshRunContext, object]):
    """Metadata-only lifecycle projection; model and tool payloads are intentionally omitted."""

    def __init__(
        self,
        repository: SQLiteStore,
        admission: OrchestrationQuiesceController | None = None,
    ):
        self.repository = repository
        self.admission = admission or OrchestrationQuiesceController()

    @staticmethod
    def _run_id(context) -> str | None:  # noqa: ANN001
        value = getattr(context, "context", None)
        return value.run_id if isinstance(value, AgentMeshRunContext) else None

    def _event(self, context, event_type: str, payload: dict[str, object]) -> None:  # noqa: ANN001
        run_id = self._run_id(context)
        if run_id:
            self.repository.append_agent_run_event(run_id, event_type, payload)

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:  # noqa: ANN001
        del system_prompt, input_items
        self._event(context, "sdk_llm_started", {"agent_name": str(agent.name)})

    async def on_llm_end(self, context, agent, response) -> None:  # noqa: ANN001
        del response
        self._event(context, "sdk_llm_completed", {"agent_name": str(agent.name)})

    async def on_agent_start(self, context, agent) -> None:  # noqa: ANN001
        self._event(context, "sdk_agent_started", {"agent_name": str(getattr(agent, "name", "agent"))})

    async def on_agent_end(self, context, agent, output) -> None:  # noqa: ANN001
        del output
        self._event(context, "sdk_agent_completed", {"agent_name": str(getattr(agent, "name", "agent"))})

    async def on_handoff(self, context, from_agent, to_agent) -> None:  # noqa: ANN001
        self._event(
            context,
            "sdk_handoff",
            {"from_agent": str(getattr(from_agent, "name", "")), "to_agent": str(getattr(to_agent, "name", ""))},
        )

    async def on_tool_start(self, context, agent, tool) -> None:  # noqa: ANN001
        del agent
        run_context = getattr(context, "context", None)
        if isinstance(run_context, AgentMeshRunContext):
            run = self.repository.get_agent_run(run_context.run_id)
            if run is None or run.planning_mode is not AgentPlanningMode.DEEPSEARCH:
                with self.admission.permit():
                    count = self.repository.consume_agent_run_tool_call(run_context.run_id)
                if count is None:
                    raise RuntimeError("Agent run exceeded the 24 tool-call limit")
                run_context.tool_call_count = count
        self._event(context, "sdk_tool_hook_started", {"tool_name": str(getattr(tool, "name", ""))})

    async def on_tool_end(self, context, agent, tool, result) -> None:  # noqa: ANN001
        del agent, result
        self._event(context, "sdk_tool_hook_completed", {"tool_name": str(getattr(tool, "name", ""))})
