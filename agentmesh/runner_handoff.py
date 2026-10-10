"""Live cloud admission before the local Provider; durable confirmation after a response."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import TYPE_CHECKING, Any

import httpx
from agents.models.interface import Model

from agentmesh.agent_runtime.budget import RunModelUsageV1
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_context.request_budget import (
    ContextRequestBudgetV1,
    ModelAdmissionError,
    measure_model_request,
    model_request_payload,
)
from agentmesh.models import new_id
from agentmesh.runner_contracts import (
    RunnerExecutionEnvelopeV3,
    RunnerModelDeliveryRequestV1,
    RunnerModelHandoffRequestV1,
    RunnerToolHandoffRequestV1,
    RunnerToolSnapshotV1,
    runner_envelope_hash,
)

if TYPE_CHECKING:
    from agentmesh.runner_client import RunnerControlPlaneClient
    from agentmesh.runner_spool import RunnerSpool


class RunnerHandoffError(ModelAdmissionError):
    pass


class RunnerModelHandoff:
    def __init__(self, client: RunnerControlPlaneClient, spool: RunnerSpool, envelope: RunnerExecutionEnvelopeV3):
        self.client = client
        self.spool = spool
        self.envelope = envelope

    @staticmethod
    def _denied(error: httpx.HTTPStatusError) -> RunnerHandoffError:
        try:
            code = error.response.json().get("detail", {}).get("code", "")
        except (ValueError, AttributeError):
            code = ""
        return RunnerHandoffError(
            code
            if isinstance(code, str) and re.fullmatch("[a-z][a-z0-9_]{0,159}", code)
            else "runner_model_handoff_denied"
        )

    async def authorize(self, request: dict, *, stage: str, model_id: str) -> tuple[str, str]:
        budget = (
            ContextRequestBudgetV1(max_tokens=128000, max_output_tokens=2000)
            if stage == "compaction"
            else ContextRequestBudgetV1()
        )
        fields = {
            key: request[key]
            for key in ("system_instructions", "input", "tools", "handoffs", "output_schema", "model_settings")
        }
        measured = measure_model_request(**fields, model_id=model_id, budget=budget)
        if measured.decision != "allowed":
            raise RunnerHandoffError("context_request_budget_exceeded")
        input_value = request["input"]
        inputs = (
            [input_value]
            if isinstance(input_value, str)
            else [item.get("content") for item in input_value if isinstance(item, dict) and item.get("role") == "user"]
        )
        input_hashes = []
        for content in inputs:
            if isinstance(content, list) and len(content) == 1:
                content = (
                    content[0].get("text")
                    if isinstance(content[0], dict) and content[0].get("type") == "input_text"
                    else None
                )
            if isinstance(content, str):
                input_hashes.append(canonical_json_sha256({"input": content}))
        request_hash = runner_envelope_hash(model_request_payload(**fields))
        payload = RunnerModelHandoffRequestV1(
            client_request_id=new_id("runner_request"),
            envelope_hash=self.envelope.envelope_hash,
            request_hash=request_hash,
            stage=stage,
            input_hashes=input_hashes,
            instructions_hash=canonical_json_sha256({"instructions": request["system_instructions"] or ""}),
            model_id=model_id,
            total_chars=measured.total_chars,
            estimated_input_tokens=measured.estimated_input_tokens,
            output_token_cap=measured.output_token_cap,
        )
        try:
            permit_id = await asyncio.to_thread(self.client.authorize_model_handoff, self.envelope.lease_id, payload)
        except httpx.HTTPStatusError as error:
            raise self._denied(error) from None
        return permit_id, request_hash

    async def authorize_tool(self, snapshot: RunnerToolSnapshotV1, raw_arguments: str, tool_call_id: str | None) -> None:
        payload = RunnerToolHandoffRequestV1(
            client_request_id=new_id("runner_tool_request"),
            envelope_hash=self.envelope.envelope_hash,
            tool_name=snapshot.name,
            tool_snapshot_hash=runner_envelope_hash(snapshot.model_dump()),
            arguments_hash=runner_envelope_hash(json.loads(raw_arguments)),
            tool_call_hash=canonical_json_sha256({"tool_call_id": tool_call_id}) if tool_call_id else None,
        )
        try:
            await asyncio.to_thread(self.client.authorize_tool_handoff, self.envelope.lease_id, payload)
        except httpx.HTTPStatusError as error:
            raise self._denied(error) from None

    async def confirm(self, permit_id: str, request_hash: str, reported: object) -> None:
        usage = RunModelUsageV1.from_reported(reported)
        total_tokens = getattr(reported, "total_tokens", None)
        if type(total_tokens) is not int or total_tokens <= 0:
            total_tokens = None
        payload = RunnerModelDeliveryRequestV1(
            handoff_id=permit_id,
            request_hash=request_hash,
            total_tokens=total_tokens,
            usage=usage,
        )
        self.spool.enqueue_model_delivery(self.envelope.lease_id, payload, node=self.envelope.node_id is not None)
        try:
            result = await asyncio.to_thread(self.client.confirm_model_handoff, self.envelope.lease_id, payload)
        except httpx.HTTPStatusError as error:
            if error.response.status_code >= 500:
                return
            raise self._denied(error) from None
        except httpx.TransportError:
            # Confirmation remains ahead of completion in the existing outbox.
            return
        self.spool.acknowledge_model_delivery(permit_id)
        if result.get("budget_error_code") in {"run_model_request_usage_exceeded", "run_model_budget_exhausted"}:
            raise RunnerHandoffError(result["budget_error_code"])


class RunnerHandoffModel(Model):
    def __init__(self, model: Model, handoff: RunnerModelHandoff, *, model_id: str, stage: str = "execution"):
        self._model = model
        self._handoff = handoff
        self._model_id = model_id
        self._stage = stage

    async def get_response(self, *args: Any, **kwargs: Any):
        bound = inspect.signature(Model.get_response).bind(None, *args, **kwargs)
        request = dict(bound.arguments)
        request.pop("self")
        permit, digest = await self._handoff.authorize(request, stage=self._stage, model_id=self._model_id)
        response = await self._model.get_response(*args, **kwargs)
        await self._handoff.confirm(permit, digest, response.usage)
        return response

    async def stream_response(self, *args: Any, **kwargs: Any):
        raise RunnerHandoffError("runner_streamed_handoff_not_supported")
        yield  # preserve the SDK async-iterator interface

    def get_retry_advice(self, request):
        return self._model.get_retry_advice(request)

    async def _cleanup_on_run_end(self, owner: object) -> None:
        await self._model._cleanup_on_run_end(owner)

    async def close(self) -> None:
        await self._model.close()
