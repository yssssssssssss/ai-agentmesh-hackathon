from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    WithJsonSchema,
)


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must contain non-whitespace characters")
    return value


def _reject_binary_float(value: Any) -> Any:
    if isinstance(value, float):
        raise TypeError("binary floating point values are not accepted by research-v3 contracts")
    return value


NonBlankString = Annotated[str, AfterValidator(_nonblank)]
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


class StrictFrozenModel(BaseModel):
    """Base for immutable research-v3 domain payloads.

    Tuples are used for collection fields because Pydantic's frozen setting alone does
    not make nested lists immutable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class SealedArtifactRefV3(StrictFrozenModel):
    artifact_id: Identifier
    kind: Identifier
    schema_version: Identifier
    content_hash: Sha256Hex


def require_unique(values: tuple[Any, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
