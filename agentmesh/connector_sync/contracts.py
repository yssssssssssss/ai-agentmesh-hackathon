from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ConnectorObservationV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    external_id: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=300)
    reference: str = Field(min_length=1, max_length=2000)
    version: str = Field(min_length=1, max_length=256)
    text: str = Field(max_length=1024 * 1024)


class ConnectorPageV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    observations: list[ConnectorObservationV1] = Field(default_factory=list, max_length=20)
    next_position: str | None = Field(default=None, max_length=512)


class ConnectorSyncCursorV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal['connector_sync_cursor_v1'] = 'connector_sync_cursor_v1'
    id: str = Field(min_length=1, max_length=120)
    owner_user_id: str = Field(min_length=1, max_length=120)
    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=120)
    provider: Literal['repo_docs', 'github_issues']
    namespace: str = Field(min_length=1, max_length=200)
    configuration_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    version: int = Field(ge=1, le=2147483647, strict=True)
    next_position: str | None = Field(default=None, max_length=512)
    last_successful_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    observed_count: int = Field(ge=0)
    status: Literal['idle', 'syncing', 'reading', 'failed', 'disabled', 'cancelled'] = 'idle'
    read_claim_id: str | None = Field(default=None, min_length=1, max_length=64)
    read_lease_until: AwareDatetime | None = None
    enabled: bool = True
    operator_bound: bool = True
    auto_sync_enabled: bool = False
    interval_seconds: int = Field(default=900, ge=300, le=86400, strict=True)
    next_sync_at: AwareDatetime | None = None
    next_allowed_at: AwareDatetime | None = None
    scan_mode: Literal['full', 'incremental'] = 'full'
    scan_started_at: AwareDatetime | None = None
    scan_since: AwareDatetime | None = None
    watermark_at: AwareDatetime | None = None
    last_full_sync_at: AwareDatetime | None = None
    seen_source_ids: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=1000)
    last_failed_at: AwareDatetime | None = None
    last_error_code: str | None = Field(default=None, pattern=r'^[a-z_]{1,80}$')
    consecutive_failures: int = Field(default=0, ge=0, le=2147483647)


class ConnectorSyncError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409, retryable: bool = False, retry_after: float = 0):
        super().__init__(code)
        self.code, self.status_code = code, status_code
        self.retryable, self.retry_after = retryable, retry_after


class ConnectorSyncRequestV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    expected_version: int = Field(ge=0, le=2147483647, strict=True)
    mode: Literal['incremental', 'full'] = 'incremental'


class ConnectorStatusV1(BaseModel):
    provider: Literal['repo_docs', 'github_issues']
    namespace: str
    cursor: ConnectorSyncCursorV1 | None
    configured: bool = True
    configuration_changed: bool = False


class ConnectorControlRequestV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    expected_version: int = Field(ge=1, le=2147483647, strict=True)
    action: Literal['disable', 'reset', 'cancel', 'enable_auto', 'pause_auto']
    interval_seconds: int = Field(default=900, ge=300, le=86400, strict=True)


class ConnectorStatusListV1(BaseModel):
    items: list[ConnectorStatusV1]
    auto_sync_available: bool = False
