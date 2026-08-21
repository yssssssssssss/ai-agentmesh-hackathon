from __future__ import annotations

import unicodedata
from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    GetJsonSchemaHandler,
    WithJsonSchema,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema


def _reject_binary_float(value: Any) -> Any:
    if isinstance(value, float):
        raise TypeError("binary floating point values are not accepted by research-v3 contracts")
    return value


NonBlankString = Annotated[str, Field(pattern=r"\S")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$"),
]
JsonDecimal = Annotated[
    Decimal,
    BeforeValidator(_reject_binary_float),
    WithJsonSchema({"type": "number"}),
]
EvidenceClass = Literal[
    "public_source",
    "screenshot",
    "user_input",
    "knowledge",
    "dataset",
    "simulation",
    "derived",
]
ActorType = Literal["tool", "skill", "llm", "reviewer"]
ApprovalRole = Literal["owner", "legal", "security"]


type FrozenJsonValue = str | int | Decimal | bool | None | FrozenJsonObject | tuple[FrozenJsonValue, ...]


class FrozenJsonObject(tuple, Mapping[str, FrozenJsonValue]):
    """A recursively immutable JSON object with stable equality, hashing, and order."""

    __slots__ = ()

    def __new__(cls, value: Mapping[str, object]) -> FrozenJsonObject:
        normalized: dict[str, FrozenJsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("frozen JSON object keys must be strings")
            canonical_key = unicodedata.normalize("NFC", key)
            if canonical_key in normalized:
                raise ValueError("frozen JSON contains duplicate normalized keys")
            normalized[canonical_key] = freeze_json_value(item)
        items = tuple(sorted(normalized.items(), key=lambda item: item[0].encode("utf-8")))
        return tuple.__new__(cls, items)

    @property
    def _items(self) -> tuple[tuple[str, FrozenJsonValue], ...]:
        return tuple(tuple.__iter__(self))

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise TypeError("FrozenJsonObject state is immutable")

    def __delattr__(self, name: str) -> None:
        del name
        raise TypeError("FrozenJsonObject state is immutable")

    def __getitem__(self, key: str) -> FrozenJsonValue:
        for candidate, value in tuple.__iter__(self):
            if candidate == key:
                return value
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and any(candidate == key for candidate, _ in tuple.__iter__(self))

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in tuple.__iter__(self))

    def __len__(self) -> int:
        return tuple.__len__(self)

    __hash__ = tuple.__hash__

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenJsonObject):
            return tuple.__eq__(self, other)
        if isinstance(other, Mapping):
            try:
                return tuple.__eq__(self, FrozenJsonObject(other))
            except (TypeError, ValueError):
                return False
        return NotImplemented

    def __repr__(self) -> str:
        return f"FrozenJsonObject({thaw_json_value(self)!r})"

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: object,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        del source_type, handler
        return core_schema.no_info_plain_validator_function(
            freeze_json_object,
            serialization=core_schema.plain_serializer_function_ser_schema(
                thaw_json_value,
                return_schema=core_schema.dict_schema(),
                when_used="always",
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        del schema, handler
        return {"type": "object", "additionalProperties": True}


def freeze_json_value(value: object) -> FrozenJsonValue:
    """Defensively copy a JSON value into recursively immutable containers."""

    if isinstance(value, FrozenJsonObject):
        return FrozenJsonObject(value)
    if value is None or isinstance(value, (str, bool, int, Decimal)):
        return value
    if isinstance(value, float):
        raise TypeError("binary floating point values are not accepted by frozen JSON contracts")
    if isinstance(value, Mapping):
        return FrozenJsonObject(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json_value(item) for item in value)
    raise TypeError(f"unsupported frozen JSON value: {type(value).__name__}")


def freeze_json_object(value: object) -> FrozenJsonObject:
    frozen = freeze_json_value(value)
    if not isinstance(frozen, FrozenJsonObject):
        raise TypeError("value must be a JSON object")
    return frozen


def thaw_json_value(value: FrozenJsonValue) -> object:
    """Return a defensive plain-Python JSON copy for serialization boundaries."""

    if isinstance(value, FrozenJsonObject):
        return {key: thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json_value(item) for item in value]
    return value


class _FrozenJsonValueAnnotation:
    def __get_pydantic_core_schema__(self, source_type: object, handler: GetCoreSchemaHandler) -> CoreSchema:
        del source_type, handler
        return core_schema.no_info_plain_validator_function(
            freeze_json_value,
            serialization=core_schema.plain_serializer_function_ser_schema(
                thaw_json_value,
                return_schema=core_schema.any_schema(),
                when_used="always",
            ),
        )

    def __get_pydantic_json_schema__(
        self,
        schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        del schema, handler
        return {}


FrozenJson = Annotated[FrozenJsonValue, _FrozenJsonValueAnnotation()]


class StrictFrozenModel(BaseModel):
    """Base for immutable research-v3 domain payloads.

    Tuple fields and ``FrozenJsonObject`` values make nested collections immutable;
    validated copies are rebuilt when updates cross the model boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class SealedArtifactRefV3(StrictFrozenModel):
    artifact_id: Identifier
    kind: Identifier
    schema_version: Identifier
    content_hash: Sha256Hex


class EvidenceManifestArtifactRefV3(SealedArtifactRefV3):
    kind: Literal["evidence_manifest"]
    schema_version: Literal["evidence-manifest-v3"]


class ProblemGraphArtifactRefV3(SealedArtifactRefV3):
    kind: Literal["problem_graph"]
    schema_version: Literal["problem-graph-v1"]


def require_unique(values: tuple[Any, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
