"""Embedding client for vector search."""

from __future__ import annotations

import logging
import math
import os
import struct
from dataclasses import dataclass
from time import monotonic

import httpx

from agentmesh.provider_status import ProviderStatus, ProviderTelemetry, build_provider_status

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    enabled: bool
    api_url: str | None
    api_key: str | None
    model: str
    dimensions: int
    timeout_seconds: float

    @classmethod
    def from_env(cls) -> EmbeddingConfig:
        enabled = os.getenv("AGENTMESH_EMBEDDING_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        api_url = os.getenv("AGENTMESH_EMBEDDING_API_URL", "").strip() or None
        api_key = os.getenv("AGENTMESH_EMBEDDING_API_KEY", "").strip() or None
        if enabled and (api_url is None or api_key is None):
            raise ValueError("Embedding requires API URL and API key")
        return cls(
            enabled=enabled,
            api_url=api_url,
            api_key=api_key,
            model=os.getenv("AGENTMESH_EMBEDDING_MODEL", "Qwen3-Embedding-8B-joybuilder"),
            dimensions=4096,
            timeout_seconds=30.0,
        )


_config = EmbeddingConfig.from_env()
EMBEDDING_API_URL = _config.api_url
EMBEDDING_API_KEY = _config.api_key
EMBEDDING_MODEL = _config.model
EMBEDDING_DIMENSIONS = _config.dimensions
EMBEDDING_ENABLED = _config.enabled

_client: httpx.Client | None = None
_telemetry = ProviderTelemetry()


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=_config.timeout_seconds)
    return _client


def embed_text(text: str, *, timeout_seconds: float | None = None) -> list[float] | None:
    if not EMBEDDING_ENABLED or not EMBEDDING_API_URL or not EMBEDDING_API_KEY or not text.strip():
        return None
    started = monotonic()
    try:
        request_options = {"timeout": timeout_seconds} if timeout_seconds is not None else {}
        response = _get_client().post(
            EMBEDDING_API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {EMBEDDING_API_KEY}",
            },
            json={"model": EMBEDDING_MODEL, "input": text[:2000]},
            **request_options,
        )
        response.raise_for_status()
        data = response.json()
        embedding = validate_embedding(
            data["data"][0]["embedding"],
            expected_dimensions=EMBEDDING_DIMENSIONS,
        )
        _telemetry.success((monotonic() - started) * 1000)
        return embedding
    except Exception as error:
        _telemetry.failure(error, (monotonic() - started) * 1000)
        logger.warning("Embedding API call failed: %s", _telemetry.snapshot().last_error)
        return None


def embedding_provider_status() -> ProviderStatus:
    configured = bool(EMBEDDING_ENABLED and EMBEDDING_API_URL and EMBEDDING_API_KEY)
    observation = _telemetry.snapshot()
    return build_provider_status(
        name="embedding",
        configured=configured,
        ready=configured and observation.last_error is None,
        telemetry=_telemetry,
        error=None if configured else "not_configured",
    )


def embed_texts(
    texts: list[str],
    *,
    timeout_seconds: float | None = None,
) -> list[list[float] | None]:
    results: list[list[float] | None] = [None] * len(texts)
    if not EMBEDDING_ENABLED or not EMBEDDING_API_URL or not EMBEDDING_API_KEY:
        return results
    active = [(index, text[:2000]) for index, text in enumerate(texts) if text.strip()]
    if not active:
        return results
    started = monotonic()
    try:
        request_options = {"timeout": timeout_seconds} if timeout_seconds is not None else {}
        response = _get_client().post(
            EMBEDDING_API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {EMBEDDING_API_KEY}",
            },
            json={"model": EMBEDDING_MODEL, "input": [text for _index, text in active]},
            **request_options,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload["data"]
        if not isinstance(data, list) or len(data) != len(active):
            raise ValueError("invalid_embedding_batch_count")
        ordered: list[list[float] | None] = [None] * len(active)
        seen_indexes: set[int] = set()
        for position, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError("invalid_embedding_batch_item")
            response_index = item.get("index", position)
            if (
                isinstance(response_index, bool)
                or not isinstance(response_index, int)
                or response_index < 0
                or response_index >= len(active)
                or response_index in seen_indexes
            ):
                raise ValueError("invalid_embedding_batch_index")
            seen_indexes.add(response_index)
            ordered[response_index] = validate_embedding(
                item.get("embedding"),
                expected_dimensions=EMBEDDING_DIMENSIONS,
            )
        if any(value is None for value in ordered):
            raise ValueError("invalid_embedding_batch_count")
        for (original_index, _text), value in zip(active, ordered, strict=True):
            results[original_index] = value
        _telemetry.success((monotonic() - started) * 1000)
        return results
    except Exception as error:
        _telemetry.failure(error, (monotonic() - started) * 1000)
        logger.warning("Embedding API batch call failed: %s", _telemetry.snapshot().last_error)
        return [None] * len(texts)


def embedding_index_signature() -> str:
    """Identify the vector space used by persisted embeddings."""
    return f"{EMBEDDING_MODEL}:{EMBEDDING_DIMENSIONS}"


def validate_embedding(
    embedding: object,
    *,
    expected_dimensions: int | None = None,
) -> list[float]:
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("invalid_embedding")
    normalized: list[float] = []
    for value in embedding:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("invalid_embedding")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("invalid_embedding")
        normalized.append(numeric)
    if expected_dimensions is not None and len(normalized) != expected_dimensions:
        raise ValueError("invalid_embedding_dimensions")
    return normalized


def serialize_embedding(embedding: list[float]) -> bytes:
    normalized = validate_embedding(embedding)
    return struct.pack(f"{len(normalized)}f", *normalized)


def deserialize_embedding(data: bytes) -> list[float]:
    if not data or len(data) % 4:
        raise ValueError("invalid_embedding")
    count = len(data) // 4
    return validate_embedding(list(struct.unpack(f"{count}f", data)))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    left = validate_embedding(a)
    right = validate_embedding(b)
    if len(left) != len(right):
        return 0.0
    dot = sum(x * y for x, y in zip(left, right, strict=True))
    norm_a = sum(x * x for x in left) ** 0.5
    norm_b = sum(x * x for x in right) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
