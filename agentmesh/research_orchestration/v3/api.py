"""Research-v3 HTTP contracts and isolated router factory.

Gate 2 reuses these contracts from the main stored-version research facade. The router
factory remains useful for isolated tests and explicit composition with an owner
provider, preview workflow, and authoritative repository projector. Read paths never
receive an execution dependency and therefore cannot schedule Provider work.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal, Protocol, TypeVar

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import Field, RootModel, ValidationError, field_validator, model_validator

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.common import Identifier, NonBlankString, Sha256Hex, StrictFrozenModel
from agentmesh.research_orchestration.v3.web_projection import ResearchV3WorkbenchAggregateV1

ResearchV3CommandType = Literal[
    "clarify",
    "select_candidate",
    "revise_plan",
    "confirm_plan",
    "approval",
    "execute",
    "retry",
    "skip",
    "abort",
    "cancel",
    "purge",
]
CandidateId = Literal["depth", "speed"]


class ResearchV3NotFoundError(LookupError):
    """The run is absent or outside the supplied owner scope."""


class ResearchV3ConflictError(RuntimeError):
    """The command conflicts with state, version, or idempotency history."""


class ResearchV3ProjectionIntegrityError(RuntimeError):
    """The authoritative repository projector returned a non-canonical aggregate."""


class ResearchV3OwnerScope(StrictFrozenModel):
    user_id: Identifier
    workspace_id: Identifier
    project_id: Identifier


class ResearchV3AggregateReadRequest(StrictFrozenModel):
    run_id: Identifier
    owner: ResearchV3OwnerScope


class ResearchV3PlanStreamRequest(StrictFrozenModel):
    run_id: Identifier
    owner: ResearchV3OwnerScope
    after_state_version: Annotated[int, Field(ge=0)] | None = None


class ResearchV3AggregateReadResponse(RootModel[ResearchV3WorkbenchAggregateV1]):
    """A direct, exact aggregate response restricted to repository projections."""

    @model_validator(mode="after")
    def require_authoritative_repository_projection(self) -> ResearchV3AggregateReadResponse:
        if self.root.provenance.source_kind != "repository_projection":
            raise ValueError("research-v3 API reads require an authoritative repository projection")
        return self


class ResearchV3PlanStreamResult(StrictFrozenModel):
    schema_version: Literal["research-v3-plan-stream-result-v1"] = "research-v3-plan-stream-result-v1"
    event_id: Identifier
    run_id: Identifier
    state_version: Annotated[int, Field(ge=0)]
    aggregate: ResearchV3WorkbenchAggregateV1

    @model_validator(mode="after")
    def validate_aggregate_identity(self) -> ResearchV3PlanStreamResult:
        if self.aggregate.run_id != self.run_id or self.aggregate.workflow.state_version != self.state_version:
            raise ValueError("plan stream result does not match its aggregate identity")
        if self.aggregate.provenance.source_kind != "repository_projection":
            raise ValueError("plan stream results require an authoritative repository projection")
        return self


class _ResearchV3MutationRequest(StrictFrozenModel):
    expected_state_version: Annotated[int, Field(ge=0)]
    request_hash: Sha256Hex


class ResearchV3ClarificationAnswer(StrictFrozenModel):
    question_key: Identifier
    answer: Annotated[NonBlankString, Field(max_length=4000)]

    @field_validator("answer")
    @classmethod
    def canonicalize_answer(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("clarification answers must not contain surrounding whitespace")
        return value


class ResearchV3ClarifyRequest(_ResearchV3MutationRequest):
    answers: tuple[ResearchV3ClarificationAnswer, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def require_unique_question_keys(self) -> ResearchV3ClarifyRequest:
        keys = tuple(item.question_key for item in self.answers)
        if len(keys) != len(set(keys)):
            raise ValueError("clarification question keys must be unique")
        return self


class ResearchV3CandidateSelectRequest(_ResearchV3MutationRequest):
    candidate_id: CandidateId


class ResearchV3AssumptionRevision(StrictFrozenModel):
    key: Identifier
    value: Annotated[NonBlankString, Field(max_length=2000)]


class ResearchV3ReviseRequest(_ResearchV3MutationRequest):
    plan_version_id: Identifier
    candidate_id: CandidateId | None = None
    revision_note: Annotated[NonBlankString, Field(max_length=4000)] | None = None
    assumptions: tuple[ResearchV3AssumptionRevision, ...] = Field(default=(), max_length=40)
    remove_optional_step_numbers: tuple[Annotated[int, Field(ge=1, le=8)], ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_revision(self) -> ResearchV3ReviseRequest:
        if self.revision_note is not None and self.revision_note != self.revision_note.strip():
            raise ValueError("revision notes must not contain surrounding whitespace")
        assumption_keys = tuple(item.key for item in self.assumptions)
        if len(assumption_keys) != len(set(assumption_keys)):
            raise ValueError("revised assumption keys must be unique")
        if len(self.remove_optional_step_numbers) != len(set(self.remove_optional_step_numbers)):
            raise ValueError("removed optional step numbers must be unique")
        if self.candidate_id is None and self.revision_note is None and not self.assumptions and not self.remove_optional_step_numbers:
            raise ValueError("at least one declarative plan revision is required")
        return self


class ResearchV3ConfirmRequest(_ResearchV3MutationRequest):
    plan_version_id: Identifier


class ResearchV3ApprovalRequest(_ResearchV3MutationRequest):
    gate_key: Identifier
    plan_version_id: Identifier
    role: Literal["owner", "legal", "security"]
    decision: Literal["approve", "reject"]


class ResearchV3ExecuteRequest(_ResearchV3MutationRequest):
    plan_version_id: Identifier


class _ResearchV3RecoveryRequest(_ResearchV3MutationRequest):
    attempt_id: Identifier
    failed_step_number: Annotated[int, Field(ge=1, le=8)]


class ResearchV3RetryRequest(_ResearchV3RecoveryRequest):
    pass


class ResearchV3SkipRequest(_ResearchV3RecoveryRequest):
    reason: Annotated[NonBlankString, Field(max_length=1000)]


class ResearchV3AbortRequest(_ResearchV3RecoveryRequest):
    reason: Annotated[NonBlankString, Field(max_length=1000)] | None = None


class ResearchV3CancelRequest(_ResearchV3MutationRequest):
    reason: Annotated[NonBlankString, Field(max_length=1000)] | None = None


class ResearchV3PurgeRequest(_ResearchV3MutationRequest):
    confirmation: Literal["PURGE"]


ResearchV3MutationRequest = (
    ResearchV3ClarifyRequest
    | ResearchV3CandidateSelectRequest
    | ResearchV3ReviseRequest
    | ResearchV3ConfirmRequest
    | ResearchV3ApprovalRequest
    | ResearchV3ExecuteRequest
    | ResearchV3RetryRequest
    | ResearchV3SkipRequest
    | ResearchV3AbortRequest
    | ResearchV3CancelRequest
    | ResearchV3PurgeRequest
)


class ResearchV3MutationReceipt(StrictFrozenModel):
    """Durable command receipt returned by the injected workflow.

    A command owns exactly one compare-and-swap transition. Execution scheduled after that
    transition advances state independently and is observed only through repository reads.
    """

    run_id: Identifier
    command_type: ResearchV3CommandType
    idempotency_key: Identifier
    request_hash: Sha256Hex
    previous_state_version: Annotated[int, Field(ge=0)]
    state_version: Annotated[int, Field(ge=1)]
    accepted: Literal[True] = True
    replayed: bool = False
    purged_artifact_count: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def validate_transition(self) -> ResearchV3MutationReceipt:
        if self.state_version != self.previous_state_version + 1:
            raise ValueError("a research-v3 command receipt must represent exactly one state transition")
        if (self.command_type == "purge") != (self.purged_artifact_count is not None):
            raise ValueError("only purge receipts contain a purged Artifact count")
        return self


class _ResearchV3MutationResponse(StrictFrozenModel):
    run_id: Identifier
    command_type: ResearchV3CommandType
    request_hash: Sha256Hex
    previous_state_version: Annotated[int, Field(ge=0)]
    state_version: Annotated[int, Field(ge=1)]
    accepted: Literal[True] = True
    replayed: bool

    @model_validator(mode="after")
    def validate_transition(self) -> _ResearchV3MutationResponse:
        if self.state_version != self.previous_state_version + 1:
            raise ValueError("a research-v3 mutation response must represent exactly one state transition")
        return self


class ResearchV3ClarifyResponse(_ResearchV3MutationResponse):
    command_type: Literal["clarify"] = "clarify"


class ResearchV3CandidateSelectResponse(_ResearchV3MutationResponse):
    command_type: Literal["select_candidate"] = "select_candidate"


class ResearchV3ReviseResponse(_ResearchV3MutationResponse):
    command_type: Literal["revise_plan"] = "revise_plan"


class ResearchV3ConfirmResponse(_ResearchV3MutationResponse):
    command_type: Literal["confirm_plan"] = "confirm_plan"


class ResearchV3ApprovalResponse(_ResearchV3MutationResponse):
    command_type: Literal["approval"] = "approval"


class ResearchV3ExecuteResponse(_ResearchV3MutationResponse):
    command_type: Literal["execute"] = "execute"


class ResearchV3RetryResponse(_ResearchV3MutationResponse):
    command_type: Literal["retry"] = "retry"


class ResearchV3SkipResponse(_ResearchV3MutationResponse):
    command_type: Literal["skip"] = "skip"


class ResearchV3AbortResponse(_ResearchV3MutationResponse):
    command_type: Literal["abort"] = "abort"


class ResearchV3CancelResponse(_ResearchV3MutationResponse):
    command_type: Literal["cancel"] = "cancel"


class ResearchV3PurgeResponse(_ResearchV3MutationResponse):
    command_type: Literal["purge"] = "purge"
    purged_artifact_count: Annotated[int, Field(ge=0)]


MutationResponse = (
    ResearchV3ClarifyResponse
    | ResearchV3CandidateSelectResponse
    | ResearchV3ReviseResponse
    | ResearchV3ConfirmResponse
    | ResearchV3ApprovalResponse
    | ResearchV3ExecuteResponse
    | ResearchV3RetryResponse
    | ResearchV3SkipResponse
    | ResearchV3AbortResponse
    | ResearchV3CancelResponse
    | ResearchV3PurgeResponse
)
_ResponseT = TypeVar("_ResponseT", bound=_ResearchV3MutationResponse)


class ResearchV3Workflow(Protocol):
    """Durable mutation boundary; it owns state CAS and idempotency receipts."""

    def apply(
        self,
        run_id: Identifier,
        command_type: ResearchV3CommandType,
        request: ResearchV3MutationRequest,
        *,
        owner: ResearchV3OwnerScope,
        idempotency_key: Identifier,
    ) -> ResearchV3MutationReceipt | Awaitable[ResearchV3MutationReceipt]: ...


class ResearchV3RepositoryProjector(Protocol):
    """Pure reader that reconstructs only authoritative persisted repository state."""

    def project_authoritative(
        self,
        request: ResearchV3AggregateReadRequest,
    ) -> ResearchV3WorkbenchAggregateV1 | Awaitable[ResearchV3WorkbenchAggregateV1]: ...


ResearchV3OwnerProvider = Callable[[Request], ResearchV3OwnerScope | Awaitable[ResearchV3OwnerScope]]
IdempotencyKeyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=120)]


def research_v3_request_hash(
    command_type: ResearchV3CommandType,
    run_id: str,
    request: ResearchV3MutationRequest,
) -> str:
    """Hash the command identity and body, excluding the self-referential hash field."""

    return canonical_json_v3_sha256(
        {
            "command_type": command_type,
            "run_id": run_id,
            "request": request.model_dump(mode="python", exclude={"request_hash"}),
        }
    )


async def _await_if_needed(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


def _mutation_response_values(receipt: ResearchV3MutationReceipt) -> dict[str, object]:
    return {
        "run_id": receipt.run_id,
        "command_type": receipt.command_type,
        "request_hash": receipt.request_hash,
        "previous_state_version": receipt.previous_state_version,
        "state_version": receipt.state_version,
        "accepted": receipt.accepted,
        "replayed": receipt.replayed,
    }


def create_research_v3_router(
    *,
    workflow: ResearchV3Workflow,
    projector: ResearchV3RepositoryProjector,
    owner_provider: ResearchV3OwnerProvider,
    prefix: str = "/api/agent/runs",
) -> APIRouter:
    """Compose an isolated router without consulting ``app.state`` or production globals."""

    router = APIRouter(prefix=prefix, tags=["research-v3-isolated"])

    async def owner_for(http_request: Request) -> ResearchV3OwnerScope:
        owner = await _await_if_needed(owner_provider(http_request))
        return ResearchV3OwnerScope.model_validate(owner)

    async def project(run_id: str, owner: ResearchV3OwnerScope) -> ResearchV3AggregateReadResponse:
        try:
            raw = await _await_if_needed(
                projector.project_authoritative(ResearchV3AggregateReadRequest(run_id=run_id, owner=owner))
            )
            aggregate = ResearchV3WorkbenchAggregateV1.model_validate(raw)
        except ValidationError as error:
            raise ResearchV3ProjectionIntegrityError("repository projection failed exact aggregate validation") from error
        if aggregate.provenance.source_kind != "repository_projection":
            raise ResearchV3ProjectionIntegrityError(
                "research-v3 API reads require an authoritative repository projection"
            )
        if aggregate.run_id != run_id:
            raise ResearchV3ProjectionIntegrityError("repository projection returned a different run")
        return ResearchV3AggregateReadResponse(root=aggregate)

    async def read_call(run_id: str, http_request: Request) -> ResearchV3AggregateReadResponse:
        try:
            return await project(run_id, await owner_for(http_request))
        except ResearchV3NotFoundError:
            raise HTTPException(status_code=404, detail="Research run not found") from None
        except (ResearchV3ConflictError, ResearchV3ProjectionIntegrityError) as error:
            raise HTTPException(status_code=409, detail=str(error) or "Research-v3 projection conflict") from None

    async def mutate(
        *,
        run_id: str,
        command_type: ResearchV3CommandType,
        body: ResearchV3MutationRequest,
        idempotency_key: str,
        http_request: Request,
        response_type: type[_ResponseT],
    ) -> _ResponseT:
        try:
            if idempotency_key != idempotency_key.strip():
                raise ResearchV3ConflictError("Idempotency-Key must be canonical")
            expected_hash = research_v3_request_hash(command_type, run_id, body)
            if body.request_hash != expected_hash:
                raise ResearchV3ConflictError("request_hash does not match the canonical research-v3 command")
            owner = await owner_for(http_request)
            raw = await _await_if_needed(
                workflow.apply(
                    run_id,
                    command_type,
                    body,
                    owner=owner,
                    idempotency_key=idempotency_key,
                )
            )
            receipt = ResearchV3MutationReceipt.model_validate(raw)
            expected_identity = (
                run_id,
                command_type,
                idempotency_key,
                body.request_hash,
                body.expected_state_version,
            )
            actual_identity = (
                receipt.run_id,
                receipt.command_type,
                receipt.idempotency_key,
                receipt.request_hash,
                receipt.previous_state_version,
            )
            if actual_identity != expected_identity:
                raise ResearchV3ConflictError("workflow receipt does not match the submitted command")
            values = _mutation_response_values(receipt)
            if response_type is ResearchV3PurgeResponse:
                values["purged_artifact_count"] = receipt.purged_artifact_count
            return response_type.model_validate(values)
        except ResearchV3NotFoundError:
            raise HTTPException(status_code=404, detail="Research run not found") from None
        except ResearchV3ConflictError as error:
            raise HTTPException(status_code=409, detail=str(error) or "Research-v3 workflow conflict") from None
        except ValidationError as error:
            raise HTTPException(status_code=409, detail="Research-v3 workflow returned an invalid receipt") from error

    @router.get("/{run_id}/research", response_model=ResearchV3AggregateReadResponse, name="research_v3_read")
    async def read_research_v3(run_id: str, request: Request) -> ResearchV3AggregateReadResponse:
        return await read_call(run_id, request)

    @router.get(
        "/{run_id}/research/refresh",
        response_model=ResearchV3AggregateReadResponse,
        name="research_v3_refresh",
    )
    async def refresh_research_v3(run_id: str, request: Request) -> ResearchV3AggregateReadResponse:
        return await read_call(run_id, request)

    @router.get("/{run_id}/research/plan/stream", name="research_v3_plan_stream")
    async def stream_research_v3_plan(
        run_id: str,
        request: Request,
        after_state_version: Annotated[int | None, Query(ge=0)] = None,
    ) -> StreamingResponse:
        try:
            owner = await owner_for(request)
            stream_request = ResearchV3PlanStreamRequest(
                run_id=run_id,
                owner=owner,
                after_state_version=after_state_version,
            )
            aggregate_response = await project(stream_request.run_id, stream_request.owner)
            aggregate = aggregate_response.root
            result = ResearchV3PlanStreamResult(
                event_id=f"state:{aggregate.workflow.state_version}",
                run_id=aggregate.run_id,
                state_version=aggregate.workflow.state_version,
                aggregate=aggregate,
            )
        except ResearchV3NotFoundError:
            raise HTTPException(status_code=404, detail="Research run not found") from None
        except (ResearchV3ConflictError, ResearchV3ProjectionIntegrityError) as error:
            raise HTTPException(status_code=409, detail=str(error) or "Research-v3 projection conflict") from None

        async def event_stream():  # noqa: ANN202
            yield f"id: {result.event_id}\nevent: projection\ndata: {result.model_dump_json()}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
        )

    @router.post(
        "/{run_id}/research/clarify",
        response_model=ResearchV3ClarifyResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_clarify",
    )
    async def clarify_research_v3(
        run_id: str,
        body: ResearchV3ClarifyRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3ClarifyResponse:
        return await mutate(
            run_id=run_id,
            command_type="clarify",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3ClarifyResponse,
        )

    @router.post(
        "/{run_id}/research/candidates/select",
        response_model=ResearchV3CandidateSelectResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_select_candidate",
    )
    async def select_research_v3_candidate(
        run_id: str,
        body: ResearchV3CandidateSelectRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3CandidateSelectResponse:
        return await mutate(
            run_id=run_id,
            command_type="select_candidate",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3CandidateSelectResponse,
        )

    @router.post(
        "/{run_id}/research/plans/revise",
        response_model=ResearchV3ReviseResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_revise_plan",
    )
    async def revise_research_v3_plan(
        run_id: str,
        body: ResearchV3ReviseRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3ReviseResponse:
        return await mutate(
            run_id=run_id,
            command_type="revise_plan",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3ReviseResponse,
        )

    @router.post(
        "/{run_id}/research/plans/confirm",
        response_model=ResearchV3ConfirmResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_confirm_plan",
    )
    async def confirm_research_v3_plan(
        run_id: str,
        body: ResearchV3ConfirmRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3ConfirmResponse:
        return await mutate(
            run_id=run_id,
            command_type="confirm_plan",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3ConfirmResponse,
        )

    @router.post(
        "/{run_id}/research/approvals",
        response_model=ResearchV3ApprovalResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_approval",
    )
    async def decide_research_v3_approval(
        run_id: str,
        body: ResearchV3ApprovalRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3ApprovalResponse:
        return await mutate(
            run_id=run_id,
            command_type="approval",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3ApprovalResponse,
        )

    @router.post(
        "/{run_id}/research/execute",
        response_model=ResearchV3ExecuteResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_execute",
    )
    async def execute_research_v3(
        run_id: str,
        body: ResearchV3ExecuteRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3ExecuteResponse:
        return await mutate(
            run_id=run_id,
            command_type="execute",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3ExecuteResponse,
        )

    @router.post(
        "/{run_id}/research/recovery/retry",
        response_model=ResearchV3RetryResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_retry",
    )
    async def retry_research_v3(
        run_id: str,
        body: ResearchV3RetryRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3RetryResponse:
        return await mutate(
            run_id=run_id,
            command_type="retry",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3RetryResponse,
        )

    @router.post(
        "/{run_id}/research/recovery/skip",
        response_model=ResearchV3SkipResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_skip",
    )
    async def skip_research_v3(
        run_id: str,
        body: ResearchV3SkipRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3SkipResponse:
        return await mutate(
            run_id=run_id,
            command_type="skip",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3SkipResponse,
        )

    @router.post(
        "/{run_id}/research/recovery/abort",
        response_model=ResearchV3AbortResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_abort",
    )
    async def abort_research_v3(
        run_id: str,
        body: ResearchV3AbortRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3AbortResponse:
        return await mutate(
            run_id=run_id,
            command_type="abort",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3AbortResponse,
        )

    @router.post(
        "/{run_id}/research/cancel",
        response_model=ResearchV3CancelResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_cancel",
    )
    async def cancel_research_v3(
        run_id: str,
        body: ResearchV3CancelRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3CancelResponse:
        return await mutate(
            run_id=run_id,
            command_type="cancel",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3CancelResponse,
        )

    @router.delete(
        "/{run_id}/research-data",
        response_model=ResearchV3PurgeResponse,
        status_code=status.HTTP_202_ACCEPTED,
        name="research_v3_purge",
    )
    async def purge_research_v3(
        run_id: str,
        body: ResearchV3PurgeRequest,
        request: Request,
        idempotency_key: IdempotencyKeyHeader,
    ) -> ResearchV3PurgeResponse:
        return await mutate(
            run_id=run_id,
            command_type="purge",
            body=body,
            idempotency_key=idempotency_key,
            http_request=request,
            response_type=ResearchV3PurgeResponse,
        )

    return router
