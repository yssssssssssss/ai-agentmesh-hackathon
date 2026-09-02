"""Pre-parse request body limits for orchestration mutation endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

_HTTP_MUTATIONS = frozenset({"POST", "PUT", "PATCH"})
_UNIVERSAL_BODY_LIMIT = 64 * 1024
_DEEPSEARCH_CLARIFY_BODY_LIMIT = 16 * 1024


def _body_limit(scope: dict[str, Any]) -> tuple[int, str] | None:
    if scope.get("type") != "http" or scope.get("method") not in _HTTP_MUTATIONS:
        return None
    path = str(scope.get("path", ""))
    if path.endswith("/deepsearch/clarify"):
        return (
            _DEEPSEARCH_CLARIFY_BODY_LIMIT,
            "deepsearch_clarification_payload_too_large",
        )
    if path == "/api/chat/messages" or path == "/api/skills/routing-preview":
        return _UNIVERSAL_BODY_LIMIT, "request_body_too_large"
    if path == "/api/agent/runs" or path.startswith("/api/agent/runs/"):
        return _UNIVERSAL_BODY_LIMIT, "request_body_too_large"
    if path == "/api/tasks" or path.startswith("/api/tasks/"):
        return _UNIVERSAL_BODY_LIMIT, "request_body_too_large"
    if path.startswith("/api/task-reviews/") or path.startswith("/api/memory-reviews/"):
        return _UNIVERSAL_BODY_LIMIT, "request_body_too_large"
    return None


class RequestBodyLimitMiddleware:
    """Reject oversized mutation bodies before framework JSON parsing."""

    def __init__(self, app):  # noqa: ANN001
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        configured = _body_limit(scope)
        if configured is None:
            await self.app(scope, receive, send)
            return
        limit, error_code = configured
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                content_length = int(value)
            except ValueError:
                content_length = limit + 1
            if content_length > limit:
                await self._reject(send, error_code=error_code)
                return
            break

        messages: list[dict[str, Any]] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            body = message.get("body", b"")
            total += len(body)
            if total > limit:
                await self._reject(send, error_code=error_code)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        index = 0

        async def replay() -> dict[str, Any]:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(
        send: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        error_code: str,
    ) -> None:
        payload = (f'{{"detail":{{"code":"{error_code}"}}}}').encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})
