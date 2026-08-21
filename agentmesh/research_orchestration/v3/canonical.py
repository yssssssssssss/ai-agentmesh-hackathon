from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

CANONICAL_JSON_V3_ALGORITHM = "agentmesh-canonical-json-v3"


def _normalized_string(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _decimal_token(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("canonical JSON forbids non-finite decimal values")
    if value.is_zero():
        return "0"
    token = format(value, "f")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token


def _canonical_token(value: Any) -> str:
    if isinstance(value, BaseModel):
        return _canonical_token(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return _canonical_token(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            canonical_key = _normalized_string(key)
            if canonical_key in normalized:
                raise ValueError("canonical JSON contains duplicate normalized keys")
            normalized[canonical_key] = item
        items = []
        for key in sorted(normalized, key=lambda item: item.encode("utf-8")):
            key_token = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            items.append(f"{key_token}:{_canonical_token(normalized[key])}")
        return "{" + ",".join(items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_token(item) for item in value) + "]"
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical datetime must include a timezone")
        normalized = value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return _canonical_token(normalized)
    if isinstance(value, Decimal):
        return _decimal_token(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON forbids NaN and infinities")
        raise TypeError("canonical JSON forbids binary floating point values")
    if isinstance(value, str):
        return json.dumps(_normalized_string(value), ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_v3_bytes(value: Any) -> bytes:
    return _canonical_token(value).encode("utf-8")


def canonical_json_v3_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_v3_bytes(value)).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _pairs_to_dict(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        normalized = _normalized_string(key)
        if normalized in result:
            raise ValueError("JSON object contains duplicate normalized keys")
        result[normalized] = value
    return result


def strict_json_v3_loads(value: str | bytes | bytearray) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="strict")
    return json.loads(
        value,
        object_pairs_hook=_pairs_to_dict,
        parse_float=Decimal,
        parse_int=int,
        parse_constant=_reject_constant,
    )
