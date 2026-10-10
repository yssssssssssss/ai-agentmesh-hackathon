from __future__ import annotations

from typing import TYPE_CHECKING

from agentmesh.llm import DEFAULT_MODEL_ID, list_model_definitions_from_env, normalize_model_id
from agentmesh.models import Agent, ModelDefinition, User

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore


def ensure_model_seed_data(repository: SQLiteStore) -> None:
    for model in list_model_definitions_from_env():
        saved = repository.get_model_definition(model.id)
        if saved is None or saved.configured != model.configured or saved.model_name != model.model_name:
            repository.save_model_definition(model)


def list_enabled_models(repository: SQLiteStore) -> list[ModelDefinition]:
    models = [model for model in repository.model_definitions if model.enabled]
    if not models:
        ensure_model_seed_data(repository)
        models = [model for model in repository.model_definitions if model.enabled]
    return models


def resolve_agent_model_id(repository: SQLiteStore, user: User) -> str:
    agent = repository.get_agent(user.personal_agent_id)
    return normalize_model_id(agent.model_id if agent else None)


def set_agent_model(repository: SQLiteStore, agent: Agent, model_id: str | None) -> Agent:
    selected_model_id = normalize_model_id(model_id)
    if selected_model_id != DEFAULT_MODEL_ID:
        model = repository.get_model_definition(selected_model_id)
        if model is None or not model.enabled:
            raise ValueError("Unknown or disabled model")
    updated = agent.model_copy(deep=True)
    updated.model_id = selected_model_id
    return repository.save_agent(updated)
