from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from agents import (
    Agent,
    ModelRetryBackoffSettings,
    ModelRetrySettings,
    ModelSettings,
    Runner,
    function_tool,
    retry_policies,
)
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from openai.types.responses import ResponseTextDeltaEvent

from agentmesh.agent_runtime.model_retry import (
    AtomicModelStreamFailure,
    AtomicStreamModel,
    ModelStreamIncompleteError,
    ModelStreamRetryExhausted,
    ModelStreamTerminalError,
    retry_transient_atomic_stream,
)


class RemoteProtocolError(Exception):
    pass


class _ScriptedStreamModel:
    def __init__(self, attempts: list[list[object]]) -> None:
        self.attempts = attempts
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def get_response(self, *args: Any, **kwargs: Any) -> object:
        raise AssertionError("stream_response must be used")

    async def stream_response(self, *args: Any, **kwargs: Any):  # noqa: ANN202
        self.calls.append((args, kwargs))
        attempt = self.attempts[len(self.calls) - 1]
        for item in attempt:
            if isinstance(item, BaseException):
                raise item
            yield item

    async def _cleanup_on_run_end(self, _owner: object) -> None:
        return None

    async def close(self) -> None:
        return None

    def get_retry_advice(self, _request: object) -> None:
        return None


class _FaultyCloseStream:
    def __init__(self, items: list[object], close_error: Exception) -> None:
        self._items = iter(items)
        self._close_error = close_error

    def __aiter__(self):  # noqa: ANN204
        return self

    async def __anext__(self) -> object:
        try:
            item = next(self._items)
        except StopIteration as error:
            raise StopAsyncIteration from error
        if isinstance(item, BaseException):
            raise item
        return item

    async def aclose(self) -> None:
        raise self._close_error


class _FaultyCloseModel(_ScriptedStreamModel):
    def __init__(self, items: list[object], close_error: Exception) -> None:
        super().__init__([])
        self.stream = _FaultyCloseStream(items, close_error)

    def stream_response(self, *args: Any, **kwargs: Any) -> _FaultyCloseStream:
        self.calls.append((args, kwargs))
        return self.stream


async def _collect(model: AtomicStreamModel, *args: Any) -> list[object]:
    return [event async for event in model.stream_response(*args)]


def test_atomic_stream_discards_partial_attempt_and_preserves_same_tool_turn_for_retry() -> None:
    transport = _ScriptedStreamModel(
        [
            [SimpleNamespace(type="response.output_text.delta"), RemoteProtocolError("incomplete chunked read")],
            [
                SimpleNamespace(type="response.output_text.delta"),
                SimpleNamespace(type="response.completed"),
            ],
        ]
    )
    model = AtomicStreamModel(transport)  # type: ignore[arg-type]
    tool_turn = [{"type": "function_call_output", "call_id": "web-1", "output": "cached research"}]

    emitted: list[object] = []

    async def first_attempt() -> None:
        async for event in model.stream_response("system", tool_turn):
            emitted.append(event)

    with pytest.raises(AtomicModelStreamFailure, match="incomplete chunked read") as captured:
        asyncio.run(first_attempt())
    events = asyncio.run(_collect(model, "system", tool_turn))

    assert emitted == []
    assert isinstance(captured.value.error, RemoteProtocolError)
    assert [event.type for event in events] == ["response.output_text.delta", "response.completed"]
    assert len(transport.calls) == 2
    assert transport.calls[0][0][1] is tool_turn
    assert transport.calls[1][0][1] is tool_turn


def test_stream_retry_exhaustion_preserves_original_error_code() -> None:
    original = RemoteProtocolError("final disconnect")
    exhausted = ModelStreamRetryExhausted(original, attempts=3)

    assert exhausted.root_error_code == "RemoteProtocolError"
    assert exhausted.attempts == 3
    assert str(exhausted) == "final disconnect"


def test_atomic_stream_does_not_hide_non_transport_failures() -> None:
    transport = _ScriptedStreamModel([[ValueError("invalid structured output")]])
    model = AtomicStreamModel(transport)  # type: ignore[arg-type]

    with pytest.raises(AtomicModelStreamFailure, match="invalid structured output") as captured:
        asyncio.run(_collect(model, "system", "input"))

    assert isinstance(captured.value.error, ValueError)
    assert len(transport.calls) == 1


def test_atomic_stream_rejects_clean_eof_without_completion_event() -> None:
    transport = _ScriptedStreamModel([[SimpleNamespace(type="response.output_text.delta")]])
    model = AtomicStreamModel(transport)  # type: ignore[arg-type]

    with pytest.raises(AtomicModelStreamFailure, match="before response.completed") as captured:
        asyncio.run(_collect(model, "system", "input"))

    assert isinstance(captured.value.error, ModelStreamIncompleteError)


def test_atomic_stream_does_not_retry_an_explicit_terminal_failure_as_network() -> None:
    transport = _ScriptedStreamModel([[SimpleNamespace(type="response.failed")]])
    model = AtomicStreamModel(transport)  # type: ignore[arg-type]

    with pytest.raises(AtomicModelStreamFailure, match="response.failed") as captured:
        asyncio.run(_collect(model, "system", "input"))

    assert isinstance(captured.value.error, ModelStreamTerminalError)


def test_atomic_stream_treats_close_failure_as_an_atomic_stream_failure() -> None:
    close_error = httpx.RemoteProtocolError("peer failed while closing stream")
    transport = _FaultyCloseModel(
        [
            SimpleNamespace(type="response.output_text.delta"),
            SimpleNamespace(type="response.completed"),
        ],
        close_error,
    )
    model = AtomicStreamModel(transport)  # type: ignore[arg-type]
    emitted: list[object] = []

    async def execute() -> None:
        async for event in model.stream_response("system", "input"):
            emitted.append(event)

    with pytest.raises(AtomicModelStreamFailure, match="peer failed while closing stream") as captured:
        asyncio.run(execute())

    assert emitted == []
    assert captured.value.error is close_error


def test_atomic_stream_preserves_read_failure_when_close_also_fails() -> None:
    read_error = httpx.RemoteProtocolError("peer closed incomplete body")
    close_error = httpx.ReadError("close failed")
    transport = _FaultyCloseModel([read_error], close_error)
    model = AtomicStreamModel(transport)  # type: ignore[arg-type]

    with pytest.raises(AtomicModelStreamFailure, match="peer closed incomplete body") as captured:
        asyncio.run(_collect(model, "system", "input"))

    assert captured.value.error is read_error
    assert getattr(read_error, "__notes__", []) == ["model stream close failed: close failed"]


def test_agent_retry_reuses_completed_tool_turn_instead_of_calling_tool_again() -> None:
    tool_calls: list[str] = []

    @function_tool
    def lookup(query: str) -> str:
        tool_calls.append(query)
        return "cached research evidence"

    async def interrupted_report(_call):  # noqa: ANN001, ANN202
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

    scripted = ScriptedModel(
        [
            [function_call("lookup", {"query": "market"}, call_id="lookup_once")],
            ModelStep.stream(interrupted_report),
            [assistant_message("COMPLETE")],
        ]
    )
    agent = Agent(
        name="retry probe",
        model=AtomicStreamModel(scripted),
        tools=[lookup],
        model_settings=ModelSettings(
            retry=ModelRetrySettings(
                max_retries=2,
                backoff=ModelRetryBackoffSettings(
                    initial_delay=0,
                    max_delay=0,
                    multiplier=1,
                    jitter=False,
                ),
                policy=retry_policies.network_error(),
            )
        ),
    )

    async def execute() -> tuple[str, list[object]]:
        result = Runner.run_streamed(agent, "research", max_turns=4)
        events = [event async for event in result.stream_events()]
        return str(result.final_output), events

    output, events = asyncio.run(execute())
    assert output == "COMPLETE"
    assert all(getattr(getattr(event, "data", None), "delta", None) != "PARTIAL" for event in events)
    assert tool_calls == ["market"]
    assert len(scripted.calls) == 3


def test_agent_retry_recovers_from_clean_eof_without_completion_event() -> None:
    async def incomplete_response(_call):  # noqa: ANN001, ANN202
        yield ResponseTextDeltaEvent(
            type="response.output_text.delta",
            content_index=0,
            delta="PARTIAL",
            item_id="msg_partial",
            logprobs=[],
            output_index=0,
            sequence_number=0,
        )

    scripted = ScriptedModel(
        [
            ModelStep.stream(incomplete_response),
            [assistant_message("COMPLETE")],
        ]
    )
    agent = Agent(
        name="incomplete stream probe",
        model=AtomicStreamModel(scripted),
        model_settings=ModelSettings(
            retry=ModelRetrySettings(
                max_retries=1,
                backoff=ModelRetryBackoffSettings(initial_delay=0, max_delay=0, jitter=False),
                policy=retry_policies.any(
                    retry_policies.network_error(),
                    retry_transient_atomic_stream,
                ),
            )
        ),
    )

    async def execute() -> str:
        result = Runner.run_streamed(agent, "research", max_turns=2)
        async for _event in result.stream_events():
            pass
        return str(result.final_output)

    assert asyncio.run(execute()) == "COMPLETE"
    assert len(scripted.calls) == 2
