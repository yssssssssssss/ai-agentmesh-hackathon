"""Optional versioned observations on the existing Source identity."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class SourceSnapshotV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    schema_version: Literal['source_snapshot_v1'] = 'source_snapshot_v1'
    provider: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    external_id: str = Field(min_length=1, max_length=512)
    version: str = Field(min_length=1, max_length=256)
    body_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    revision: int = Field(ge=1, le=2147483647)
    observed_at: AwareDatetime
    lifecycle: Literal['active', 'archived', 'deleted', 'unavailable'] = 'active'

    @field_validator('observed_at', mode='before')
    @classmethod
    def decode_observed_at(cls, value: object) -> object:
        # Runtime snapshots also hydrate JSON dictionaries through model_validate.
        return datetime.fromisoformat(value) if isinstance(value, str) else value


class SourceOriginV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    schema_version: Literal['source_origin_v1'] = 'source_origin_v1'
    source_id: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=1, le=2147483647)
    source_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    body_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
