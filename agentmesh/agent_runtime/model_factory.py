from __future__ import annotations

import os
from dataclasses import dataclass

from agents import OpenAIChatCompletionsModel
from agents.models.interface import Model
from openai import AsyncOpenAI

from agentmesh.agent_runtime.structured_output import (
    JSONObjectChatCompletionsModel,
    SDKStructuredOutputMode,
    sdk_structured_output_mode,
)
from agentmesh.llm import llm_chat_timeout_seconds, model_config_from_env
from agentmesh.model_registry import resolve_agent_model_id
from agentmesh.models import User
from agentmesh.store import SQLiteStore


@dataclass(frozen=True, slots=True)
class SelectedSDKModel:
    model: Model
    requested_model: str
    actual_model: str
    structured_output_mode: SDKStructuredOutputMode = SDKStructuredOutputMode.JSON_SCHEMA


def _base_url(value: str) -> str:
    normalized = value.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


class AgentMeshModelFactory:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    def for_user(self, user: User) -> SelectedSDKModel | None:
        return self.for_model_id(resolve_agent_model_id(self.repository, user))

    def for_model_id(self, model_id: str) -> SelectedSDKModel | None:
        config = model_config_from_env(model_id)
        if config is None:
            return None
        if config["api_style"] != "chat_completions":
            raise ValueError(
                f"OpenAI Agents SDK runtime does not support API style '{config['api_style']}'"
            )
        structured_output_mode = sdk_structured_output_mode(config["id"])
        client = AsyncOpenAI(
            api_key=config["api_key"],
            base_url=_base_url(config["base_url"]),
            timeout=llm_chat_timeout_seconds(),
        )
        buffered = os.getenv("AGENTMESH_SDK_BUFFER_STREAMED_TOOL_CALLS", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        model_class = (
            JSONObjectChatCompletionsModel
            if structured_output_mode == SDKStructuredOutputMode.JSON_OBJECT
            else OpenAIChatCompletionsModel
        )
        model = model_class(
            model=config["model_name"],
            openai_client=client,
            buffer_streamed_tool_calls=buffered,
        )
        return SelectedSDKModel(
            model=model,
            requested_model=model_id,
            actual_model=config["model_name"],
            structured_output_mode=structured_output_mode,
        )
