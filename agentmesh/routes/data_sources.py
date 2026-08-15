"""Data source routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.data_authorization import (
    DataQueryAuthorizationError,
    authorize_data_query,
)
from agentmesh.datasources import DataSourceQuery, DataSourceRequestError, default_data_source_registry
from agentmesh.models import BlackboardPost, DataSourceQueryRequest, Scope, User
from agentmesh.o2 import O2CommandError, maybe_register_o2_data_connector
from agentmesh.routes.deps import current_user
from agentmesh.store import SQLiteStore, store
from agentmesh.tools import ensure_tool_seed_data

router = APIRouter(prefix="/api", tags=["data_sources"])


data_source_registry = default_data_source_registry()
maybe_register_o2_data_connector(data_source_registry)


@router.get("/data-sources")
def data_sources(_: User = Depends(current_user)) -> dict[str, object]:
    return {"items": data_source_registry.list_connectors()}


def authorize_data_source_query(
    user: User,
    connector_name: str,
    operation: str,
    *,
    repository: SQLiteStore = store,
) -> None:
    try:
        authorize_data_query(repository, user, connector_name, operation)
    except DataQueryAuthorizationError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post("/data-agent/query")
def query_data_agent(request: DataSourceQueryRequest, user: User = Depends(current_user)) -> dict[str, object]:
    ensure_tool_seed_data(store, granted_by="system")
    authorize_data_source_query(user, request.connector_name, request.operation)
    project = store.get_project(user.default_project_id)
    if (
        project is None
        or project.workspace_id != user.workspace_id
        or not store.user_can_access_project(user.id, project.id)
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        result = data_source_registry.query(
            DataSourceQuery(
                connector_name=request.connector_name,
                operation=request.operation,
                parameters=request.parameters,
                workspace_id=user.workspace_id,
                project_id=project.id,
                requested_by=user.id,
            )
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (O2CommandError, DataSourceRequestError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    store.add_source(result.source)
    post = store.add_blackboard_post(
        BlackboardPost(
            task_id=f"data_{user.id}",
            post_type="evidence",
            actor="data_agent",
            title=result.title,
            content=str(result.records),
            scope=Scope.PROJECT,
            permission="project_visible",
            sources=[result.source],
            metadata=result.metadata,
            read_by_agents=["personal_agent"],
        )
    )
    return {"result": result, "post": post}
