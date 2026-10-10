"""Admission for the complete SDK request, including tool schemas and prior outputs."""
from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal

from agents import ModelSettings
from agents.models.chatcmpl_converter import Converter
from agents.models.interface import Model
from pydantic import BaseModel, ConfigDict, Field

from agentmesh.agent_runtime.model_handoff import model_handoff_gate, run_model_meter

if TYPE_CHECKING:
    from agentmesh.agent_runtime.budget import RunModelBudgetMeter


class ModelAdmissionError(RuntimeError):
    """Static safe code; never include a rejected prompt or provider body."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ContextRequestError(ModelAdmissionError):
    pass


class ContextRequestBudgetV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    max_total_chars: int = Field(default=200000, ge=1000, le=1000000)
    max_tokens: int = Field(default=64000, ge=2000, le=256000)
    max_output_tokens: int = Field(default=8192, ge=1, le=32000)


class ContextRequestMeasurementV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    model_id: str
    estimation_method: Literal['utf8_conservative'] = 'utf8_conservative'
    total_chars: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    output_token_cap: int = Field(ge=1)
    decision: Literal['allowed', 'withheld']


def bounded_model_settings(settings: ModelSettings, budget: ContextRequestBudgetV1, *, metered: bool = False) -> ModelSettings:
    return replace(settings,
        max_tokens=min(settings.max_tokens or budget.max_output_tokens, budget.max_output_tokens),
        include_usage=True if metered else settings.include_usage,
        preserve_raw_usage=True if metered else settings.preserve_raw_usage)


def _has_unbudgeted_media(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get('type') in {'input_image', 'input_audio', 'input_file', 'image_url'} or any(
            _has_unbudgeted_media(item) for item in value.values()
        )
    return isinstance(value, list) and any(_has_unbudgeted_media(item) for item in value)


def model_request_payload(*, system_instructions: str | None, input: Any, tools: list,
                          handoffs: list, output_schema: Any, model_settings: ModelSettings) -> dict:
    # Use the pinned SDK's Chat Completions conversion, the only configured backend.
    # Function descriptions, strict parameters, handoffs and output schema all count.
    return {
        'instructions': system_instructions,
        'messages': Converter.items_to_messages(input),
        'tools': [Converter.tool_to_openai(tool) for tool in tools]
                 + [Converter.convert_handoff_tool(handoff) for handoff in handoffs],
        'output_schema': None if output_schema is None or output_schema.is_plain_text()
                         else output_schema.json_schema(),
        'model_settings': model_settings.to_json_dict(),
    }


def measure_model_request(*, system_instructions: str | None, input: Any, tools: list,
                          handoffs: list, output_schema: Any, model_settings: ModelSettings,
                          model_id: str, budget: ContextRequestBudgetV1) -> ContextRequestMeasurementV1:
    if _has_unbudgeted_media(input):
        raise ContextRequestError('context_request_media_unbudgeted')
    payload = model_request_payload(system_instructions=system_instructions, input=input, tools=tools,
                                   handoffs=handoffs, output_schema=output_schema, model_settings=model_settings)
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    # Enterprise aliases do not declare a verified tokenizer. Report a conservative
    # UTF-8 estimate instead of presenting chars/4 as measured/model-tokenizer usage.
    # A framing reserve includes model-added message/schema envelope overhead.
    estimated = len(rendered.encode('utf-8')) + 1024
    output_cap = min(model_settings.max_tokens or budget.max_output_tokens, budget.max_output_tokens)
    return ContextRequestMeasurementV1(
        model_id=model_id, total_chars=len(rendered), estimated_input_tokens=estimated,
        output_token_cap=output_cap,
        decision='allowed' if len(rendered) <= budget.max_total_chars
        and estimated + output_cap <= budget.max_tokens else 'withheld',
    )


def history_request_fits(history: list[dict], *, current_input: str, system_instructions: str | None,
                         tools: list, model_settings: ModelSettings, model_id: str,
                         budget: ContextRequestBudgetV1) -> bool:
    measured = measure_model_request(system_instructions=system_instructions,
        input=[*history, {'role': 'user', 'content': current_input}], tools=tools, handoffs=[], output_schema=None,
        model_settings=bounded_model_settings(model_settings, budget, metered=True), model_id=model_id, budget=budget)
    return measured.decision == 'allowed'


class RequestBudgetModel(Model):
    """Check every actual SDK model request after history/tools have been assembled."""

    def __init__(self, model: Model, *, model_id: str,
                 budget: ContextRequestBudgetV1 | None = None,
                 on_measure: Callable[[ContextRequestMeasurementV1], None] | None = None,
                 on_request: Callable[[dict], None] | None = None,
                 on_handoff: Callable[[], None] | None = None,
                 run_meter: RunModelBudgetMeter | None = None,
                 defer_delivery: bool = False):
        self._model = model
        self._model_id = model_id
        self._budget = budget or ContextRequestBudgetV1()
        self._on_measure = on_measure
        self._on_request = on_request
        self._on_handoff = on_handoff
        self._defer_delivery = defer_delivery
        self._run_meter = run_meter
        self._last_measurement: ContextRequestMeasurementV1 | None = None
        self.failure: BaseException | None = None

    def _admit(self, args: tuple, kwargs: dict, *, final: bool = False, deliver: bool = True) -> dict:
        bound = inspect.signature(Model.get_response).bind(None, *args, **kwargs)
        request = dict(bound.arguments)
        request.pop('self')
        if any(request.get(key) is not None for key in ('previous_response_id', 'conversation_id', 'prompt')):
            raise ContextRequestError('context_request_hidden_state')
        settings = request['model_settings']
        request['model_settings'] = bounded_model_settings(settings, self._budget, metered=self._run_meter is not None)
        measured = measure_model_request(
            **{key: request[key] for key in ('system_instructions', 'input', 'tools', 'handoffs',
                                            'output_schema', 'model_settings')},
            model_id=self._model_id, budget=self._budget,
        )
        if self._on_measure is not None and (not final or measured != self._last_measurement):
            self._on_measure(measured)
        self._last_measurement = measured
        if measured.decision != 'allowed':
            raise ContextRequestError('context_request_budget_exceeded')
        if deliver and (final or (not self._defer_delivery and self._run_meter is None)):
            self._deliver(request)
        return request

    def deliver_request(self, *args: Any, **kwargs: Any) -> dict:
        """Complete admitted delivery after a process-local capacity wait."""
        return self._admit(args, kwargs, final=True)

    def check_request(self, *args: Any, **kwargs: Any) -> dict:
        """Repeat complete request admission before reserving cumulative usage."""
        return self._admit(args, kwargs, final=True, deliver=False)

    def _deliver(self, request: dict) -> None:
        if self._on_request is not None:
            self._on_request(request)
        if self._on_handoff is not None:
            self._on_handoff()

    async def get_response(self, *args: Any, **kwargs: Any):  # noqa: ANN202
        self.failure = None
        token = None
        meter_token = None
        try:
            request = self._admit(args, kwargs)
            if self._defer_delivery:
                token = model_handoff_gate.set(self.deliver_request)
                meter_token = run_model_meter.set((self._run_meter, self.check_request) if self._run_meter else None)
            elif self._run_meter is not None:
                return await self._run_meter.get_response(self._model, before_send=self.deliver_request, **request)
            return await self._model.get_response(**request)
        except BaseException as error:
            self.failure = error
            raise
        finally:
            if token is not None:
                model_handoff_gate.reset(token)
            if meter_token is not None:
                run_model_meter.reset(meter_token)

    async def stream_response(self, *args: Any, **kwargs: Any):  # noqa: ANN202
        self.failure = None
        token = None
        meter_token = None
        try:
            request = self._admit(args, kwargs)
            if self._defer_delivery:
                token = model_handoff_gate.set(self.deliver_request)
                meter_token = run_model_meter.set((self._run_meter, self.check_request) if self._run_meter else None)
            stream = (self._run_meter.stream_response(self._model, before_send=self.deliver_request, **request)
                      if self._run_meter is not None and not self._defer_delivery
                      else self._model.stream_response(**request))
            async for event in stream:
                yield event
        except BaseException as error:
            self.failure = error
            raise
        finally:
            if token is not None:
                model_handoff_gate.reset(token)
            if meter_token is not None:
                run_model_meter.reset(meter_token)

    def get_retry_advice(self, request):  # noqa: ANN001, ANN201
        return self._model.get_retry_advice(request)

    async def _cleanup_on_run_end(self, owner: object) -> None:
        await self._model._cleanup_on_run_end(owner)

    async def close(self) -> None:
        await self._model.close()
