"""Data source routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agentmesh.connector_sync.configuration import configured_reader, configured_readers
from agentmesh.connector_sync.contracts import (
    ConnectorControlRequestV1,
    ConnectorStatusListV1,
    ConnectorStatusV1,
    ConnectorSyncCursorV1,
    ConnectorSyncError,
    ConnectorSyncRequestV1,
)
from agentmesh.connector_sync.service import ConnectorSyncService
from agentmesh.data_authorization import (
    DataQueryAuthorizationError,
    authorize_data_query,
)
from agentmesh.datasources import DataSourceQuery, DataSourceRequestError, default_data_source_registry
from agentmesh.models import BlackboardPost, DataSourceQueryRequest, Scope, User
from agentmesh.o2 import O2CommandError, maybe_register_o2_data_connector
from agentmesh.provider_status import ProviderQueryError
from agentmesh.routes.deps import current_user
from agentmesh.source_authority import SourceAuthorityError
from agentmesh.store import SQLiteStore, store
from agentmesh.tools import ensure_tool_seed_data

router = APIRouter(prefix="/api", tags=["data_sources"])


data_source_registry = default_data_source_registry()
maybe_register_o2_data_connector(data_source_registry)


@router.get("/data-sources")
def data_sources(_: User = Depends(current_user)) -> dict[str, object]:
    return {"items": data_source_registry.list_connectors()}


@router.get('/projects/{project_id}/connectors', response_model=ConnectorStatusListV1)
def project_connectors(project_id: str, request: Request, user: User = Depends(current_user)) -> ConnectorStatusListV1:
    try:
        ConnectorSyncService.authorize_project(store, user, project_id)
        ConnectorSyncService.reconcile_bindings(store, user, project_id=project_id)
        cursors = ConnectorSyncService.stored_cursors(store, user, project_id=project_id)
        try:
            readers = configured_readers(project_id)
        except ConnectorSyncError as error:
            if error.code != 'connector_not_found':
                raise
            readers = []
        configured = {(reader.provider, reader.namespace): reader.configuration_hash() for reader in readers}
        items = [ConnectorStatusV1(provider=cursor.provider, namespace=cursor.namespace, cursor=cursor,
            configured=(cursor.provider, cursor.namespace) in configured,
            configuration_changed=(cursor.provider, cursor.namespace) in configured
                and configured[cursor.provider, cursor.namespace] != cursor.configuration_hash) for cursor in cursors]
        stored = {(cursor.provider, cursor.namespace) for cursor in cursors}
        items.extend(ConnectorStatusV1(provider=reader.provider, namespace=reader.namespace, cursor=None)
                     for reader in readers if (reader.provider, reader.namespace) not in stored)
        coordinator = getattr(request.app.state, 'connector_sync_coordinator', None)
        return ConnectorStatusListV1(items=items, auto_sync_available=bool(coordinator and coordinator.available))
    except ConnectorSyncError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post('/projects/{project_id}/connectors/{provider}/sync', response_model=ConnectorSyncCursorV1)
def sync_project_connector(project_id: str, provider: str, request: ConnectorSyncRequestV1,
                           user: User = Depends(current_user)) -> ConnectorSyncCursorV1:
    try:
        ConnectorSyncService.authorize_project(store, user, project_id)
        reader = configured_reader(project_id, provider)
        service = ConnectorSyncService(store, reader, current_configuration_hash=lambda:
            configured_reader(project_id, provider).configuration_hash())
        return service.sync_page(user, project_id=project_id, expected_version=request.expected_version, mode=request.mode)
    except (ConnectorSyncError, SourceAuthorityError) as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


@router.post('/projects/{project_id}/connectors/{cursor_id}/control', response_model=ConnectorSyncCursorV1)
def control_project_connector(project_id: str, cursor_id: str, request: ConnectorControlRequestV1,
                              user: User = Depends(current_user)) -> ConnectorSyncCursorV1:
    try:
        reader = None
        current_configuration_hash = None
        if request.action in {'reset', 'enable_auto'}:
            cursor = next((item for item in ConnectorSyncService.stored_cursors(store, user, project_id=project_id)
                           if item.id == cursor_id), None)
            if cursor is None:
                raise ConnectorSyncError('connector_not_found', status_code=404)
            reader = configured_reader(project_id, cursor.provider)

            def current_configuration_hash() -> str:
                return configured_reader(project_id, cursor.provider).configuration_hash()
        return ConnectorSyncService.control(store, user, project_id=project_id, cursor_id=cursor_id,
            expected_version=request.expected_version, action=request.action, reader=reader,
            current_configuration_hash=current_configuration_hash, interval_seconds=request.interval_seconds)
    except (ConnectorSyncError, SourceAuthorityError) as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from error


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
    except ProviderQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.public_detail()) from error
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
