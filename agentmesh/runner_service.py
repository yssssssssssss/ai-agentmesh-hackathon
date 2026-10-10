from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from agentmesh.memory_context.request_budget import ModelAdmissionError
from agentmesh.models import new_id, now_utc
from agentmesh.runner_client import RunnerControlPlaneClient
from agentmesh.runner_contracts import (
    RunnerCancellationRequest,
    RunnerCapabilitiesV1,
    RunnerCompletionRequest,
    RunnerCompletionRequestV2,
    RunnerExecutionEnvelope,
    RunnerExecutionEnvelopeV3,
    RunnerExecutionEventV1,
    RunnerFailureRequest,
    RunnerNodeCompletionRequest,
    RunnerNodeCompletionRequestV2,
)
from agentmesh.runner_executor import RunnerExecutionResult, execute_runner_envelope
from agentmesh.runner_handoff import RunnerModelHandoff
from agentmesh.runner_spool import RunnerSpool

RunnerExecutor = Callable[[RunnerExecutionEnvelope], Awaitable[RunnerExecutionResult]]


class RunnerCancelled(RuntimeError):
    pass


class LocalRunnerService:
    def __init__(
        self,
        client: RunnerControlPlaneClient,
        *,
        capabilities: RunnerCapabilitiesV1,
        executor: RunnerExecutor = execute_runner_envelope,
        renew_interval_seconds: float = 20.0,
        spool: RunnerSpool | None = None,
    ):
        self.client = client
        self.capabilities = capabilities
        self.executor = executor
        self.renew_interval_seconds = renew_interval_seconds
        self.spool = spool or RunnerSpool()

    @staticmethod
    def _event(event_type: str, payload: dict[str, object] | None = None) -> RunnerExecutionEventV1:
        return RunnerExecutionEventV1(
            client_event_id=new_id("runner_event"),
            event_type=event_type,
            payload=payload or {},
            occurred_at=now_utc(),
        )

    def _emit(self, lease_id: str, events: list[RunnerExecutionEventV1]) -> None:
        self.spool.enqueue_events(lease_id, events)
        self.spool.flush(self.client)

    async def _execute_with_renewal(
        self,
        envelope: RunnerExecutionEnvelope,
    ) -> RunnerExecutionResult:
        if isinstance(envelope, RunnerExecutionEnvelopeV3) and self.executor is execute_runner_envelope:
            execution = execute_runner_envelope(envelope, handoff=RunnerModelHandoff(self.client, self.spool, envelope))
        else:
            execution = self.executor(envelope)
        task = asyncio.create_task(execution)
        while True:
            done, _pending = await asyncio.wait(
                {task},
                timeout=self.renew_interval_seconds,
            )
            if task in done:
                return await task
            renewal = await asyncio.to_thread(self.client.renew, envelope.lease_id)
            if renewal.cancel_requested:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                raise RunnerCancelled("Runner execution was cancelled by the control plane")

    def run_once(self) -> bool:
        self.spool.flush(self.client)
        self.client.heartbeat(self.capabilities)
        envelope = self.client.claim(self.capabilities)
        if envelope is None:
            return False
        self._emit(
            envelope.lease_id,
            [self._event("execution_started")],
        )
        try:
            self._emit(
                envelope.lease_id,
                [self._event("model_started", {"model_id": envelope.model_id})],
            )
            result = asyncio.run(self._execute_with_renewal(envelope))
        except RunnerCancelled:
            cancellation = RunnerCancellationRequest(command_id=new_id("runner_command"))
            self.spool.enqueue_cancellation(envelope.lease_id, cancellation)
            self.spool.flush(self.client)
            return True
        except Exception as error:
            error_code = error.code if isinstance(error, ModelAdmissionError) else type(error).__name__[:160]
            try:
                self.spool.enqueue_events(
                    envelope.lease_id,
                    [self._event("execution_failed", {"error_code": error_code})],
                )
                self.spool.enqueue_failure(
                    envelope.lease_id,
                    RunnerFailureRequest(
                        command_id=new_id("runner_command"),
                        error_code=error_code,
                    ),
                    node=envelope.operation_kind == "standard_skill_node",
                )
                self.spool.flush(self.client)
            except Exception:
                pass
            return True
        model_completed = self._event(
            "model_completed",
            {
                "requested_model": result.requested_model,
                "actual_model": result.actual_model,
                "total_tokens": result.total_tokens,
            },
        )
        completion = RunnerCompletionRequest(
            command_id=new_id("runner_command"),
            output_text=result.output_text,
            requested_model=result.requested_model,
            actual_model=result.actual_model,
            total_tokens=result.total_tokens,
        )
        if result.session_commit is not None:
            completion = RunnerCompletionRequestV2(**completion.model_dump(), session_commit=result.session_commit)
        if result.tool_events:
            self.spool.enqueue_events(envelope.lease_id, list(result.tool_events))
        self.spool.enqueue_events(envelope.lease_id, [model_completed])
        if envelope.operation_kind == "standard_skill_node":
            if result.result_payload is None:
                raise RuntimeError("runner_node_result_missing")
            self.spool.enqueue_node_completion(
                envelope.lease_id,
                (RunnerNodeCompletionRequestV2 if isinstance(envelope, RunnerExecutionEnvelopeV3) else RunnerNodeCompletionRequest)(
                    command_id=new_id("runner_command"),
                    result_payload=result.result_payload,
                    requested_model=result.requested_model,
                    actual_model=result.actual_model,
                    total_tokens=result.total_tokens,
                ),
            )
        else:
            self.spool.enqueue_completion(envelope.lease_id, completion)
        self.spool.flush(self.client)
        return True
