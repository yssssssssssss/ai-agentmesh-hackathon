from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from enum import StrEnum

from agents import (
    AgentOutputSchemaBase,
    Handoff,
    ModelResponse,
    ModelSettings,
    ModelTracing,
    OpenAIChatCompletionsModel,
    Tool,
    TResponseInputItem,
)
from agents.items import TResponseStreamEvent
from openai.types.responses.response_prompt_param import ResponsePromptParam

STRUCTURED_OUTPUT_MODE_ENV = "AGENTMESH_SDK_STRUCTURED_OUTPUT_MODE"


class SDKStructuredOutputMode(StrEnum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"


def sdk_structured_output_mode(model_id: str) -> SDKStructuredOutputMode:
    normalized_id = model_id.strip() or "default"
    model_env_key = "".join(char if char.isalnum() else "_" for char in normalized_id).upper()
    model_value = (
        os.getenv(f"AGENTMESH_MODEL_{model_env_key}_STRUCTURED_OUTPUT_MODE")
        if normalized_id != "default"
        else None
    )
    global_value = os.getenv(STRUCTURED_OUTPUT_MODE_ENV, "").strip()
    raw = (model_value or "").strip() or global_value or SDKStructuredOutputMode.JSON_SCHEMA.value
    raw = raw.lower()
    try:
        return SDKStructuredOutputMode(raw)
    except ValueError as error:
        allowed = ", ".join(mode.value for mode in SDKStructuredOutputMode)
        raise ValueError(f"{STRUCTURED_OUTPUT_MODE_ENV} must be one of: {allowed}") from error


def configure_structured_output(
    *,
    instructions: str | None,
    output_schema: AgentOutputSchemaBase,
    model_settings: ModelSettings,
    use_json_mode: bool = True,
) -> tuple[str, ModelSettings]:
    """Adapt SDK structured output without weakening local schema validation."""

    if output_schema.is_plain_text():
        raise ValueError("json_object structured output requires a non-text output type")

    schema_json = json.dumps(
        output_schema.json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    json_instructions = (
        f"{(instructions or '').rstrip()}\n\n"
        "When you provide the final answer, return exactly one valid JSON object matching the JSON Schema below. "
        "You may call available tools before the final answer. "
        "Do not wrap the final JSON in Markdown or add fields outside the schema.\n"
        f"JSON Schema:\n{schema_json}"
    )
    if not use_json_mode:
        return json_instructions, model_settings

    response_format = {"type": SDKStructuredOutputMode.JSON_OBJECT.value}
    extra_body = dict(model_settings.extra_body or {})
    configured_response_format = extra_body.get("response_format")
    if configured_response_format not in (None, response_format):
        raise ValueError("model settings already define a conflicting response_format")
    extra_body["response_format"] = response_format
    return json_instructions, replace(model_settings, extra_body=extra_body)


class JSONObjectChatCompletionsModel(OpenAIChatCompletionsModel):
    """Chat Completions adapter for gateways that support JSON mode but not JSON Schema mode."""

    @staticmethod
    def _adapt_request(
        system_instructions: str | None,
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
    ) -> tuple[str | None, ModelSettings, AgentOutputSchemaBase | None]:
        if output_schema is None or output_schema.is_plain_text():
            return system_instructions, model_settings, output_schema

        use_json_mode = not tools and not handoffs
        system_instructions, model_settings = configure_structured_output(
            instructions=system_instructions,
            output_schema=output_schema,
            model_settings=model_settings,
            use_json_mode=use_json_mode,
        )
        # JSON mode suppresses tool selection on the target gateway. Keep the schema in the
        # instructions for tool-enabled turns; Runner still validates the final output locally.
        provider_output_schema = output_schema if use_json_mode else None
        return system_instructions, model_settings, provider_output_schema

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: ResponsePromptParam | None = None,
    ) -> ModelResponse:
        system_instructions, model_settings, provider_output_schema = self._adapt_request(
            system_instructions,
            model_settings,
            tools,
            output_schema,
            handoffs,
        )
        return await super().get_response(
            system_instructions,
            input,
            model_settings,
            tools,
            provider_output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )

    def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: ResponsePromptParam | None = None,
    ) -> AsyncIterator[TResponseStreamEvent]:
        system_instructions, model_settings, provider_output_schema = self._adapt_request(
            system_instructions,
            model_settings,
            tools,
            output_schema,
            handoffs,
        )
        return super().stream_response(
            system_instructions,
            input,
            model_settings,
            tools,
            provider_output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )
