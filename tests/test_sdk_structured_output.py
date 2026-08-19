from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from agents import Agent, ModelBehaviorError, ModelSettings, RunConfig, Runner, function_tool
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict

from agentmesh.agent_runtime.model_factory import AgentMeshModelFactory
from agentmesh.agent_runtime.structured_output import (
    JSONObjectChatCompletionsModel,
    SDKStructuredOutputMode,
    sdk_structured_output_mode,
)
from agentmesh.store import SQLiteStore


class ProbeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


@function_tool(strict_mode=False)
def structured_probe(value: str) -> str:
    return f"tool:{value}"


def _chat_completion(content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-structured-output-test",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


async def _run_with_response(content: str, *, output_type=ProbeOutput):  # noqa: ANN001, ANN202
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert isinstance(payload, dict)
        requests.append(payload)
        return httpx.Response(200, json=_chat_completion(content))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    openai_client = AsyncOpenAI(
        api_key="test-only-key",
        base_url="https://provider.example/v1",
        http_client=http_client,
        max_retries=0,
    )
    model = JSONObjectChatCompletionsModel(model="test-model", openai_client=openai_client)
    agent = Agent(
        name="Structured output test",
        instructions="Return the requested value.",
        model=model,
        tools=[],
        output_type=output_type,
    )
    try:
        result = await Runner.run(
            agent,
            "Return ok.",
            max_turns=1,
            run_config=RunConfig(tracing_disabled=True),
        )
        return result, requests
    finally:
        await openai_client.close()


async def _run_streamed_response() -> tuple[object, list[dict[str, object]]]:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert isinstance(payload, dict)
        requests.append(payload)
        chunks = [
            {
                "id": "chatcmpl-stream-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": '{"value":"streamed"}'},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl-stream-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "test-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
            {
                "id": "chatcmpl-stream-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "test-model",
                "choices": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        ]
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    openai_client = AsyncOpenAI(
        api_key="test-only-key",
        base_url="https://provider.example/v1",
        http_client=http_client,
        max_retries=0,
    )
    model = JSONObjectChatCompletionsModel(model="test-model", openai_client=openai_client)
    agent = Agent(
        name="Structured streaming test",
        instructions="Return the requested value.",
        model=model,
        tools=[],
        output_type=ProbeOutput,
    )
    try:
        result = Runner.run_streamed(
            agent,
            "Return streamed.",
            max_turns=1,
            run_config=RunConfig(tracing_disabled=True),
        )
        async for _event in result.stream_events():
            pass
        return result, requests
    finally:
        await openai_client.close()


async def _run_streamed_tool_response() -> tuple[object, list[dict[str, object]], bool]:
    requests: list[dict[str, object]] = []

    def stream_body(chunks: list[dict[str, object]]) -> str:
        return "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"

    def chunk(choices: list[dict[str, object]], *, usage: dict[str, int] | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": "chatcmpl-tool-stream-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "test-model",
            "choices": choices,
        }
        if usage is not None:
            payload["usage"] = usage
        return payload

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert isinstance(payload, dict)
        requests.append(payload)
        if len(requests) == 1:
            chunks = [
                chunk(
                    [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_structured_probe",
                                        "type": "function",
                                        "function": {
                                            "name": "structured_probe",
                                            "arguments": '{"value":"probe"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ]
                ),
                chunk([{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]),
                chunk([], usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}),
            ]
        else:
            chunks = [
                chunk(
                    [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": '{"value":"complete"}'},
                            "finish_reason": None,
                        }
                    ]
                ),
                chunk([{"index": 0, "delta": {}, "finish_reason": "stop"}]),
                chunk([], usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}),
            ]
        return httpx.Response(
            200,
            content=stream_body(chunks),
            headers={"content-type": "text/event-stream"},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    openai_client = AsyncOpenAI(
        api_key="test-only-key",
        base_url="https://provider.example/v1",
        http_client=http_client,
        max_retries=0,
    )
    model = JSONObjectChatCompletionsModel(model="test-model", openai_client=openai_client)
    agent = Agent(
        name="Structured tool streaming test",
        instructions="Call structured_probe, then return the requested value.",
        model=model,
        model_settings=ModelSettings(tool_choice="required"),
        tools=[structured_probe],
        output_type=ProbeOutput,
    )
    tool_called = False
    try:
        result = Runner.run_streamed(
            agent,
            "Run the probe.",
            max_turns=3,
            run_config=RunConfig(tracing_disabled=True),
        )
        async for event in result.stream_events():
            if event.type == "run_item_stream_event" and getattr(event, "name", "") == "tool_called":
                tool_called = True
        return result, requests, tool_called
    finally:
        await openai_client.close()


def test_structured_output_mode_defaults_and_allows_model_override(monkeypatch) -> None:
    monkeypatch.delenv("AGENTMESH_SDK_STRUCTURED_OUTPUT_MODE", raising=False)
    monkeypatch.delenv("AGENTMESH_MODEL_GPT52_STRUCTURED_OUTPUT_MODE", raising=False)
    assert sdk_structured_output_mode("gpt52") == SDKStructuredOutputMode.JSON_SCHEMA

    monkeypatch.setenv("AGENTMESH_SDK_STRUCTURED_OUTPUT_MODE", "json_object")
    assert sdk_structured_output_mode("gpt52") == SDKStructuredOutputMode.JSON_OBJECT

    monkeypatch.setenv("AGENTMESH_MODEL_GPT52_STRUCTURED_OUTPUT_MODE", "json_schema")
    assert sdk_structured_output_mode("gpt52") == SDKStructuredOutputMode.JSON_SCHEMA


def test_structured_output_mode_rejects_invalid_configuration(monkeypatch) -> None:
    monkeypatch.setenv("AGENTMESH_SDK_STRUCTURED_OUTPUT_MODE", "automatic")

    with pytest.raises(ValueError, match="AGENTMESH_SDK_STRUCTURED_OUTPUT_MODE must be one of"):
        sdk_structured_output_mode("default")


def test_model_factory_selects_json_object_adapter(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENTMESH_MODEL_PRIMARY_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AGENTMESH_MODEL_PRIMARY_API_KEY", "test-only-key")
    monkeypatch.setenv("AGENTMESH_MODEL_PRIMARY_MODEL", "test-model")
    monkeypatch.setenv("AGENTMESH_SDK_STRUCTURED_OUTPUT_MODE", "json_object")

    selected = AgentMeshModelFactory(SQLiteStore(tmp_path / "factory.sqlite3")).for_model_id("primary")

    assert selected is not None
    assert isinstance(selected.model, JSONObjectChatCompletionsModel)
    assert selected.structured_output_mode == SDKStructuredOutputMode.JSON_OBJECT


def test_json_object_adapter_overrides_wire_format_and_keeps_local_validation() -> None:
    result, requests = asyncio.run(_run_with_response('{"value":"ok"}'))

    assert result.final_output == ProbeOutput(value="ok")
    assert len(requests) == 1
    request = requests[0]
    assert request["response_format"] == {"type": "json_object"}
    messages = request["messages"]
    assert isinstance(messages, list)
    system_message = messages[0]
    assert isinstance(system_message, dict)
    assert "JSON Schema:" in system_message["content"]
    assert '"additionalProperties":false' in system_message["content"]


def test_json_object_adapter_rejects_schema_invalid_provider_output() -> None:
    with pytest.raises(ModelBehaviorError):
        asyncio.run(_run_with_response('{"value":"ok","extra":"not allowed"}'))


def test_json_object_adapter_applies_to_streaming_output() -> None:
    result, requests = asyncio.run(_run_streamed_response())

    assert result.final_output == ProbeOutput(value="streamed")
    assert len(requests) == 1
    assert requests[0]["stream"] is True
    assert requests[0]["response_format"] == {"type": "json_object"}


def test_json_object_adapter_keeps_structured_streaming_tools_compatible() -> None:
    result, requests, tool_called = asyncio.run(_run_streamed_tool_response())

    assert result.final_output == ProbeOutput(value="complete")
    assert tool_called is True
    assert len(requests) == 2
    assert all("response_format" not in request for request in requests)
    assert requests[0]["tool_choice"] == "required"
    assert "tool_choice" not in requests[1]
    assert requests[0]["tools"]
    messages = requests[0]["messages"]
    assert isinstance(messages, list)
    assert "JSON Schema:" in messages[0]["content"]


def test_json_object_adapter_leaves_plain_text_requests_unchanged() -> None:
    result, requests = asyncio.run(_run_with_response("plain response", output_type=None))

    assert result.final_output == "plain response"
    assert len(requests) == 1
    request = requests[0]
    assert "response_format" not in request
    messages = request["messages"]
    assert isinstance(messages, list)
    system_message = messages[0]
    assert isinstance(system_message, dict)
    assert system_message["content"] == "Return the requested value."
