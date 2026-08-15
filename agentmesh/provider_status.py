from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, field_validator

ProviderMode = Literal["real", "fallback"]

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|token|password|secret|credential|cookie)\b"
    r"\s*[:=]\s*([^\s,;&]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[^\s,;&]+")
_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)


class ProviderStatus(BaseModel):
    """Serializable, secret-safe status shared by every real provider."""

    model_config = ConfigDict(extra="forbid")

    name: str
    configured: bool
    ready: bool
    mode: ProviderMode
    last_error: str | None = None
    latency_ms: float | None = None

    @field_validator("last_error")
    @classmethod
    def redact_error(cls, value: str | None) -> str | None:
        return redact_sensitive_text(value) if value else None


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    last_error: str | None
    latency_ms: float | None


class ProviderTelemetry:
    """Small thread-safe holder for the last adapter observation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._latency_ms: float | None = None

    def success(self, latency_ms: float) -> None:
        with self._lock:
            self._last_error = None
            self._latency_ms = round(max(0.0, latency_ms), 3)

    def failure(self, error: BaseException, latency_ms: float | None = None) -> None:
        with self._lock:
            self._last_error = provider_error_code(error)
            self._latency_ms = round(max(0.0, latency_ms), 3) if latency_ms is not None else None

    def snapshot(self) -> ProviderObservation:
        with self._lock:
            return ProviderObservation(last_error=self._last_error, latency_ms=self._latency_ms)


def build_provider_status(
    *,
    name: str,
    configured: bool,
    ready: bool,
    telemetry: ProviderTelemetry | None = None,
    error: str | None = None,
    mode: ProviderMode | None = None,
) -> ProviderStatus:
    observation = telemetry.snapshot() if telemetry is not None else ProviderObservation(None, None)
    last_error = error or observation.last_error
    current_ready = ready and last_error is None
    return ProviderStatus(
        name=name,
        configured=configured,
        ready=current_ready,
        mode=mode or ("real" if current_ready else "fallback"),
        last_error=last_error,
        latency_ms=observation.latency_ms,
    )


def provider_metadata(
    *,
    requested_provider: str,
    actual_provider: str,
    mode: ProviderMode,
    latency_ms: float,
    fallback_reason: str | None = None,
) -> dict[str, str]:
    return {
        "requested_provider": requested_provider,
        "actual_provider": actual_provider,
        "mode": mode,
        "fallback_reason": redact_sensitive_text(fallback_reason or ""),
        "latency_ms": f"{max(0.0, latency_ms):.3f}",
    }


def provider_error_code(error: BaseException) -> str:
    """Return a stable category without echoing provider response bodies or commands."""

    name = error.__class__.__name__.lower()
    reason = getattr(error, "reason", None)
    if isinstance(reason, str) and reason:
        return redact_sensitive_text(reason)[:80]
    if "timeout" in name:
        return "timeout"
    status_code = getattr(getattr(error, "response", None), "status_code", None)
    if status_code in {401, 403}:
        return "auth_error"
    if status_code is not None:
        return f"http_{status_code}"
    if isinstance(error, (KeyError, TypeError, ValueError)) or "json" in name or "decode" in name:
        return "malformed_response"
    message = str(error).lower()
    if any(marker in message for marker in ("unauthorized", "forbidden", "auth_required", "login required")):
        return "auth_error"
    if "not found" in message or "not configured" in message or "unavailable" in message:
        return "unavailable"
    return "provider_error"


def redact_url(value: str) -> str:
    """Remove URL userinfo and query/fragment values while retaining a useful endpoint identity."""

    try:
        parts = urlsplit(value)
    except ValueError:
        return "[REDACTED_URL]"
    if not parts.scheme or not parts.hostname:
        return "[REDACTED_URL]"
    host = parts.hostname
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def redact_sensitive_text(value: str) -> str:
    redacted = _BEARER_TOKEN.sub("Bearer [REDACTED]", value)
    redacted = _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return _URL.sub(lambda match: redact_url(match.group(0).rstrip(".,)")), redacted)
