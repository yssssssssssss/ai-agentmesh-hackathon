from __future__ import annotations

from typing import Any

from agents import ModelRetryAdviceRequest, RetryPolicyContext
from agents.models.interface import Model

_TRANSIENT_STREAM_ERROR_NAMES = frozenset(
    {
        "APIConnectionError",
        "ConnectError",
        "InternalServerError",
        "NetworkError",
        "ReadError",
        "RemoteProtocolError",
        "RateLimitError",
        "ServiceUnavailableError",
        "TemporaryProviderError",
    }
)


def is_transient_stream_error(error: Exception) -> bool:
    return isinstance(error, ConnectionError) or type(error).__name__ in _TRANSIENT_STREAM_ERROR_NAMES


class ModelStreamRetryExhausted(RuntimeError):
    """A stable wrapper that preserves the provider error after request-level retries."""

    def __init__(self, error: Exception, *, attempts: int) -> None:
        super().__init__(str(error) or type(error).__name__)
        self.root_error_code = type(error).__name__
        self.attempts = attempts


class ModelStreamIncompleteError(ConnectionError):
    """The provider closed a stream without its terminal completion event."""


class ModelStreamTerminalError(RuntimeError):
    """The provider explicitly terminated a streamed response as failed."""


class AtomicModelStreamFailure(RuntimeError):
    """Marks an exception as originating inside the wrapped model stream."""

    def __init__(self, error: Exception, *, attempts: int) -> None:
        super().__init__(str(error) or type(error).__name__)
        self.error = error
        self.attempts = attempts


def retry_transient_atomic_stream(context: RetryPolicyContext) -> bool:
    return isinstance(context.error, AtomicModelStreamFailure) and is_transient_stream_error(
        context.error.error,
    )


class AtomicStreamModel(Model):
    """Make one streamed provider response atomic to the Agent runner.

    Events are held until the provider finishes the response. If the stream breaks,
    no partial event reaches the Agent runner, so its request-level retry can safely
    replay the exact request, including tool outputs from earlier completed turns.
    This is intentionally used only for Standard nodes; DeepSearch owns its durable
    attempt and budget accounting.
    """

    def __init__(self, model: Model) -> None:
        self._model = model

    def _failure(self, error: Exception) -> AtomicModelStreamFailure:
        return AtomicModelStreamFailure(error, attempts=1)

    async def get_response(self, *args: Any, **kwargs: Any):  # noqa: ANN202
        return await self._model.get_response(*args, **kwargs)

    def stream_response(self, *args: Any, **kwargs: Any):  # noqa: ANN202
        return self._stream_response(args, kwargs)

    async def _stream_response(self, args: tuple[Any, ...], kwargs: dict[str, Any]):  # noqa: ANN202
        buffered: list[Any] = []
        completed = False
        terminal_failure: str | None = None
        stream = self._model.stream_response(*args, **kwargs)
        try:
            async for event in stream:
                buffered.append(event)
                event_type = getattr(event, "type", None)
                completed = completed or event_type == "response.completed"
                if event_type in {"response.failed", "response.incomplete", "error", "response.error"}:
                    terminal_failure = str(event_type)
        except BaseException as error:
            close = getattr(stream, "aclose", None)
            if callable(close):
                try:
                    await close()
                except Exception as close_error:
                    error.add_note(f"model stream close failed: {close_error}")
            if isinstance(error, Exception):
                raise self._failure(error) from error
            raise
        close = getattr(stream, "aclose", None)
        if callable(close):
            try:
                await close()
            except Exception as error:
                raise self._failure(error) from error
        if terminal_failure is not None:
            error = ModelStreamTerminalError(f"model stream ended with {terminal_failure}")
            raise self._failure(error) from error
        if not completed:
            error = ModelStreamIncompleteError("model stream ended before response.completed")
            raise self._failure(error) from error
        for event in buffered:
            yield event

    async def _cleanup_on_run_end(self, owner: object) -> None:
        await self._model._cleanup_on_run_end(owner)

    async def close(self) -> None:
        await self._model.close()

    def get_retry_advice(self, request: ModelRetryAdviceRequest):  # noqa: ANN201
        if isinstance(request.error, AtomicModelStreamFailure):
            request.error.attempts = request.attempt
        return self._model.get_retry_advice(request)
