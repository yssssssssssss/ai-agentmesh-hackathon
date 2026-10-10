from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderMode = Literal["real", "fallback"]
ProviderDataMode = Literal["real", "demo", "derived"]
ProviderOutcome = Literal["success", "no_change", "insufficient_evidence", "blocked", "failed", "indeterminate"]


def demo_mode_enabled() -> bool:
    return os.getenv("AGENTMESH_DEMO_MODE", "").strip() == "1"


class ProviderQueryError(RuntimeError):
    """An unavailable query, with a stable public reason and no provider payload."""

    def __init__(
        self,
        reason: str,
        *,
        requested_provider: str,
        actual_provider: str | None = None,
        outcome: ProviderOutcome = "blocked",
    ) -> None:
        messages = {
            "demo_provider_disabled": "该数据源只提供演示样本，当前未启用演示模式。请配置真实数据源。",
            "no_real_provider_configured": "尚未配置可用的真实数据源，未返回演示样本。",
            "unverified_provider_result": "数据源未提供可验证的结果来源，本次查询未完成。",
            "insufficient_evidence": "数据源没有返回足够的资料，暂时无法完成本次查询。",
            "no_data_source_result": "数据源查询未返回可用结果，请检查数据源状态后重试。",
        }
        super().__init__(messages.get(reason, "数据源查询失败，请检查数据源状态后重试。"))
        self.reason = reason
        self.requested_provider = requested_provider
        self.actual_provider = actual_provider
        self.outcome = outcome

    @property
    def status_code(self) -> int:
        return 503 if self.outcome == "blocked" else 502

    def public_detail(self) -> dict[str, str | None]:
        return {
            "code": self.reason,
            "message": str(self),
            "outcome": self.outcome,
            "requested_provider": self.requested_provider,
            "actual_provider": self.actual_provider,
        }


def require_demo_provider(requested_provider: str, actual_provider: str) -> None:
    if not demo_mode_enabled():
        raise ProviderQueryError(
            "demo_provider_disabled",
            requested_provider=requested_provider,
            actual_provider=actual_provider,
        )


def validate_query_result(
    metadata: dict[str, str],
    *,
    requested_provider: str,
    has_evidence: bool,
) -> dict[str, str]:
    """Accept evidence before it is persisted or used to complete a query."""
    actual_provider = metadata.get("actual_provider")
    data_mode = metadata.get("data_mode")
    if actual_provider in {"mock", "local_metrics"}:
        data_mode = "demo"
    elif data_mode is None:
        # Compatibility for existing real adapters; unlabelled demo fixtures stay demo.
        if metadata.get("mode") == "real" and actual_provider:
            data_mode = "real"
        elif demo_mode_enabled():
            data_mode = "demo"
    if data_mode not in {"real", "demo", "derived"} or (not actual_provider and data_mode != "demo"):
        raise ProviderQueryError(
            "unverified_provider_result",
            requested_provider=requested_provider,
            actual_provider=actual_provider,
        )
    if data_mode == "demo":
        require_demo_provider(requested_provider, actual_provider or requested_provider)
    if not has_evidence or metadata.get("outcome", "success") != "success":
        raise ProviderQueryError(
            "insufficient_evidence",
            requested_provider=requested_provider,
            actual_provider=actual_provider,
            outcome="insufficient_evidence",
        )
    return {**metadata, "data_mode": data_mode, "outcome": "success"}


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
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
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
        checked_at=datetime.now(UTC),
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
    data_mode: ProviderDataMode = "real",
    outcome: ProviderOutcome = "success",
) -> dict[str, str]:
    return {
        "requested_provider": requested_provider,
        "actual_provider": actual_provider,
        "mode": mode,
        "data_mode": data_mode,
        "outcome": outcome,
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
