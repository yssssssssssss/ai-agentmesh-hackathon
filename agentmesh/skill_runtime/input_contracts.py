from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agentmesh.canonical_json import canonical_json_bytes
from agentmesh.models import SkillDefinition

_USER_INPUT_CONTRACT_MAX_BYTES = 64 * 1024
_USER_INPUT_CONTRACT_MAX_DEPTH = 12
_USER_INPUT_CONTRACT_MAX_FIELDS = 64
_FIELD_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SUPPORTED_INPUT_MEDIA_TYPES = frozenset({"text/plain", "text/markdown", "text/csv"})


class UserInputContractError(ValueError):
    """Stable, safe failure raised while loading a Skill user-input contract."""


class _ContractProperty(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["string", "array"]
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    format: Literal["uri", "agentmesh-input-artifact"] | None = None
    content_media_type: str | None = Field(default=None, alias="contentMediaType", max_length=120)
    min_length: int | None = Field(default=None, alias="minLength", ge=0, le=100_000)
    max_length: int | None = Field(default=None, alias="maxLength", ge=1, le=100_000)
    min_items: int | None = Field(default=None, alias="minItems", ge=0, le=20)
    max_items: int | None = Field(default=None, alias="maxItems", ge=1, le=20)
    enum: list[str] | None = Field(default=None, min_length=1, max_length=50)
    items: _ContractProperty | None = None
    required_columns: list[str] = Field(
        default_factory=list,
        alias="x-agentmesh-required-columns",
        max_length=64,
    )

    @model_validator(mode="after")
    def validate_shape(self) -> _ContractProperty:
        if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
            raise ValueError("minLength cannot exceed maxLength")
        if self.min_items is not None and self.max_items is not None and self.min_items > self.max_items:
            raise ValueError("minItems cannot exceed maxItems")
        if self.type == "array":
            if (
                self.items is None
                or self.items.type != "string"
                or self.items.format != "agentmesh-input-artifact"
            ):
                raise ValueError("array fields require artifact string items")
            if self.format is not None or self.content_media_type is not None or self.enum is not None:
                raise ValueError("array validation belongs on items")
        elif self.items is not None or self.min_items is not None or self.max_items is not None:
            raise ValueError("string fields cannot declare array validation")
        if self.format == "agentmesh-input-artifact":
            if self.content_media_type not in SUPPORTED_INPUT_MEDIA_TYPES:
                raise ValueError("input media type is not supported")
        elif self.content_media_type is not None:
            raise ValueError("contentMediaType requires agentmesh-input-artifact")
        if self.required_columns and not (
            self.format == "agentmesh-input-artifact" and self.content_media_type == "text/csv"
        ):
            raise ValueError("required columns are only valid for CSV artifacts")
        return self

    @property
    def artifact_spec(self) -> _ContractProperty | None:
        if self.type == "array":
            return self.items if self.items and self.items.format == "agentmesh-input-artifact" else None
        return self if self.format == "agentmesh-input-artifact" else None


_ContractProperty.model_rebuild()


class SkillUserInputContractV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    json_schema: Literal["https://json-schema.org/draft/2020-12/schema"] = Field(alias="$schema")
    contract_id: str = Field(alias="$id", min_length=1, max_length=240)
    schema_version: Literal["skill-user-input-v1"]
    type: Literal["object"]
    required: list[str] = Field(default_factory=list, max_length=_USER_INPUT_CONTRACT_MAX_FIELDS)
    properties: dict[str, _ContractProperty] = Field(
        default_factory=dict,
        max_length=_USER_INPUT_CONTRACT_MAX_FIELDS,
    )
    additional_properties: Literal[False] = Field(alias="additionalProperties")

    @model_validator(mode="after")
    def validate_fields(self) -> SkillUserInputContractV1:
        if len(set(self.required)) != len(self.required):
            raise ValueError("required fields must be unique")
        unknown = set(self.required) - set(self.properties)
        if unknown:
            raise ValueError("required fields must exist in properties")
        if any(not _FIELD_ID_PATTERN.fullmatch(field_id) for field_id in self.properties):
            raise ValueError("field identifiers are invalid")
        return self


@dataclass(frozen=True, slots=True)
class LoadedUserInputContract:
    contract: SkillUserInputContractV1
    content_hash: str
    path: Path
    canonical_payload: dict[str, Any]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UserInputContractError("user_input_contract_invalid")
        result[key] = value
    return result


def _json_depth(value: Any, *, depth: int = 0) -> int:
    if depth > _USER_INPUT_CONTRACT_MAX_DEPTH:
        raise UserInputContractError("user_input_contract_too_deep")
    if isinstance(value, dict):
        for item in value.values():
            _json_depth(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _json_depth(item, depth=depth + 1)
    return depth


def load_user_input_contract(
    skill: SkillDefinition,
    schema_ref: str,
) -> LoadedUserInputContract:
    root = Path(skill.source_path).resolve().parent
    reference = Path(schema_ref)
    if reference.is_absolute():
        raise UserInputContractError("user_input_contract_path_invalid")
    try:
        path = (root / reference).resolve()
    except OSError as error:
        raise UserInputContractError("user_input_contract_path_invalid") from error
    if not path.is_relative_to(root):
        raise UserInputContractError("user_input_contract_path_invalid")
    if not path.is_file():
        raise UserInputContractError("user_input_contract_missing")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise UserInputContractError("user_input_contract_missing") from error
    if len(raw) > _USER_INPUT_CONTRACT_MAX_BYTES:
        raise UserInputContractError("user_input_contract_too_large")
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        _json_depth(payload)
        contract = SkillUserInputContractV1.model_validate(payload)
    except UserInputContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError) as error:
        raise UserInputContractError("user_input_contract_invalid") from error
    expected_id = f"agentmesh://skills/{skill.name}/user-input-v{skill.version}"
    if contract.contract_id != expected_id:
        raise UserInputContractError("user_input_contract_identity_mismatch")
    for field in contract.properties.values():
        artifact_spec = field.artifact_spec
        if artifact_spec is not None and artifact_spec.content_media_type not in SUPPORTED_INPUT_MEDIA_TYPES:
            raise UserInputContractError("input_media_type_unsupported")
        if field.format == "uri" or (field.items is not None and field.items.format == "uri"):
            raise UserInputContractError("input_adapter_unavailable")
    canonical_payload = contract.model_dump(mode="json", by_alias=True, exclude_none=True)
    return LoadedUserInputContract(
        contract=contract,
        content_hash=hashlib.sha256(canonical_json_bytes(canonical_payload)).hexdigest(),
        path=path,
        canonical_payload=canonical_payload,
    )


def field_kind(field: _ContractProperty) -> Literal["text", "artifact"]:
    return "artifact" if field.artifact_spec is not None else "text"


def field_media_types(field: _ContractProperty) -> list[str]:
    spec = field.artifact_spec
    return [spec.content_media_type] if spec is not None and spec.content_media_type else []
