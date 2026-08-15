from __future__ import annotations

import os
from time import monotonic
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from agentmesh.models import Source
from agentmesh.provider_status import (
    ProviderStatus,
    ProviderTelemetry,
    build_provider_status,
    provider_error_code,
    provider_metadata,
)

READ_ONLY_DATA_OPERATIONS = frozenset({"query", "search", "list", "find-tables", "schema", "describe", "get", "read", "lookup"})
_data_api_telemetry = ProviderTelemetry()


def is_read_only_data_operation(operation: str) -> bool:
    verb = operation.strip().lower().split(maxsplit=1)[0] if operation.strip() else ""
    return verb in READ_ONLY_DATA_OPERATIONS


class DataSourceRequestError(RuntimeError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class DataSourceQuery(BaseModel):
    connector_name: str = Field(min_length=1, max_length=120)
    operation: str = Field(min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str
    project_id: str
    requested_by: str


class DataSourceResult(BaseModel):
    connector_name: str
    title: str = Field(min_length=1, max_length=200)
    records: list[dict[str, Any]] = Field(default_factory=list)
    source: Source
    metadata: dict[str, str] = Field(default_factory=dict)


class DataSourceConnector(Protocol):
    def query(self, query: DataSourceQuery) -> DataSourceResult: ...


class ExternalDataSourceConnector:
    def query(self, query: DataSourceQuery) -> DataSourceResult:
        raise NotImplementedError("External data source integration is provided by another project.")


class LocalMetricsConnector:
    connector_name = "local_metrics"

    def query(self, query: DataSourceQuery) -> DataSourceResult:
        started = monotonic()
        metric = str(query.parameters.get("metric") or "conversion_rate")
        return DataSourceResult(
            connector_name=self.connector_name,
            title=f"{metric} 查询结果",
            records=[{"metric": metric, "value": 0.123, "source": "local_sample"}],
            source=Source(
                title="local_metrics",
                source_type="data_source",
                reference=f"datasource://local_metrics/{query.operation}",
            ),
            metadata=provider_metadata(
                requested_provider=query.connector_name,
                actual_provider=self.connector_name,
                mode="fallback",
                fallback_reason="explicit_local_metrics",
                latency_ms=(monotonic() - started) * 1000,
            ),
        )


class HTTPDataAPIConnector:
    connector_name = "http_data_api"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = (base_url or os.getenv("AGENTMESH_DATA_API_URL") or "").rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("AGENTMESH_DATA_API_KEY", "")
        self.timeout_seconds = timeout_seconds or int(os.getenv("AGENTMESH_DATA_API_TIMEOUT_SECONDS", "20"))
        self.http_client = http_client

    def query(self, query: DataSourceQuery) -> DataSourceResult:
        if not is_read_only_data_operation(query.operation):
            raise ValueError("Only allowlisted read-only data operations are supported")
        if not self.base_url:
            raise ValueError("AGENTMESH_DATA_API_URL is not configured")
        started = monotonic()
        try:
            endpoint = _safe_operation_path(query.operation)
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            response = self._client().post(
                f"{self.base_url}/{endpoint}",
                headers=headers,
                json={
                    "operation": query.operation,
                    "parameters": query.parameters,
                    "workspace_id": query.workspace_id,
                    "project_id": query.project_id,
                    "requested_by": query.requested_by,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError("Data API response must be an object or list")
            records = normalize_data_records(payload)
            title = str(_payload_value(payload, ("title", "name")) or f"{query.operation} 查询结果")
            source_title = str(_payload_value(payload, ("source_title", "source", "provider")) or self.connector_name)
            source_reference = str(
                _payload_value(payload, ("source_reference", "reference", "url"))
                or f"datasource://{self.connector_name}/{query.operation}"
            )
        except httpx.TimeoutException as error:
            _data_api_telemetry.failure(error, (monotonic() - started) * 1000)
            raise DataSourceRequestError("timeout", "Data API request timed out") from error
        except httpx.HTTPStatusError as error:
            reason = "auth_error" if error.response.status_code in {401, 403} else "http_status"
            _data_api_telemetry.failure(DataSourceRequestError(reason, reason), (monotonic() - started) * 1000)
            raise DataSourceRequestError(reason, f"Data API returned HTTP {error.response.status_code}") from error
        except httpx.RequestError as error:
            _data_api_telemetry.failure(error, (monotonic() - started) * 1000)
            raise DataSourceRequestError("request_error", "Data API request failed") from error
        except (KeyError, TypeError, ValueError) as error:
            _data_api_telemetry.failure(error, (monotonic() - started) * 1000)
            raise DataSourceRequestError("malformed_response", "Data API returned a malformed response") from error

        latency_ms = (monotonic() - started) * 1000
        _data_api_telemetry.success(latency_ms)
        return DataSourceResult(
            connector_name=self.connector_name,
            title=title,
            records=records,
            source=Source(title=source_title, source_type="data_source", reference=source_reference),
            metadata=provider_metadata(
                requested_provider=query.connector_name,
                actual_provider=self.connector_name,
                mode="real",
                latency_ms=latency_ms,
            ),
        )

    def _client(self) -> httpx.Client:
        if self.http_client is None:
            self.http_client = httpx.Client(timeout=self.timeout_seconds)
        return self.http_client


class DataSourceRegistry:
    def __init__(self):
        self._connectors: dict[str, DataSourceConnector] = {}

    def register(self, name: str, connector: DataSourceConnector) -> None:
        self._connectors[name] = connector

    def query(self, query: DataSourceQuery) -> DataSourceResult:
        connector = self._connectors.get(query.connector_name)
        if connector is None:
            raise KeyError(f"Unknown data source connector: {query.connector_name}")
        return connector.query(query)

    def query_first_available(
        self,
        connector_names: list[str],
        operation: str,
        parameters: dict[str, Any],
        workspace_id: str,
        project_id: str,
        requested_by: str,
    ) -> DataSourceResult:
        errors: list[str] = []
        requested_provider = connector_names[0] if connector_names else "data_api"
        for connector_name in connector_names:
            if connector_name not in self._connectors:
                continue
            try:
                result = self.query(
                    DataSourceQuery(
                        connector_name=connector_name,
                        operation=operation,
                        parameters=parameters,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        requested_by=requested_by,
                    )
                )
            except Exception as error:
                error_code = "auth_required" if str(error).strip() == "auth_required" else provider_error_code(error)
                errors.append(f"{connector_name}:{error_code}")
                continue
            if result.records:
                result.metadata["requested_provider"] = requested_provider
                if errors:
                    if not result.metadata.get("fallback_reason"):
                        result.metadata["fallback_reason"] = " | ".join(errors)[:500]
                    result.metadata["fallback_diagnostics"] = " | ".join(
                        entry.replace(":", ": ", 1) for entry in errors
                    )[:500]
                return result
            errors.append(f"{connector_name}:empty_result")
        raise RuntimeError("No data source connector returned records: " + " | ".join(errors))

    def list_connectors(self) -> list[str]:
        return sorted(self._connectors)


def default_data_source_registry() -> DataSourceRegistry:
    registry = DataSourceRegistry()
    maybe_register_http_data_api_connector(registry)
    registry.register(LocalMetricsConnector.connector_name, LocalMetricsConnector())
    return registry


def maybe_register_http_data_api_connector(registry: DataSourceRegistry) -> None:
    if os.getenv("AGENTMESH_DATA_API_URL", "").strip():
        registry.register(HTTPDataAPIConnector.connector_name, HTTPDataAPIConnector())


def data_api_provider_status() -> ProviderStatus:
    configured = bool(os.getenv("AGENTMESH_DATA_API_URL", "").strip())
    return build_provider_status(
        name="data_api",
        configured=configured,
        ready=configured,
        telemetry=_data_api_telemetry,
        error=None if configured else "not_configured",
    )


def normalize_data_records(payload: Any) -> list[dict[str, Any]]:
    items = _extract_record_items(payload)
    return [_flatten_record(item) for item in items]


def _extract_record_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return [{"value": payload}]
    for key in ("records", "items", "results", "data", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return [payload]


def _flatten_record(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"value": item}
    return {str(key): _stringify_record_value(value) for key, value in item.items()}


def _stringify_record_value(value: Any) -> Any:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _safe_operation_path(operation: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in operation.strip())
    return cleaned or "query"


def _payload_value(payload: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value:
            return value
    return None
