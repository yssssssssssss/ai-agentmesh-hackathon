"""Preview-only research-v3 command workflow.

The service persists planning artifacts and command receipts, but it has no Actor
execution dependency. Commands that could send Tool/model work fail closed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from agentmesh.research_orchestration.v3.api import (
    ResearchV3AbortRequest,
    ResearchV3AggregateReadRequest,
    ResearchV3ApprovalRequest,
    ResearchV3CancelRequest,
    ResearchV3CandidateSelectRequest,
    ResearchV3ClarifyRequest,
    ResearchV3CommandType,
    ResearchV3ConfirmRequest,
    ResearchV3ExecuteRequest,
    ResearchV3MutationReceipt,
    ResearchV3MutationRequest,
    ResearchV3OwnerScope,
    ResearchV3PurgeRequest,
    ResearchV3RetryRequest,
    ResearchV3ReviseRequest,
    ResearchV3SkipRequest,
    research_v3_request_hash,
)
from agentmesh.research_orchestration.v3.api import (
    ResearchV3ConflictError as ApiConflictError,
)
from agentmesh.research_orchestration.v3.api import (
    ResearchV3NotFoundError as ApiNotFoundError,
)
from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.sqlite_repository import (
    PreviewRecordAppendV3,
    ResearchCommandReceiptV3,
    ResearchV3ConflictError,
    ResearchV3NotFoundError,
    SQLiteResearchV3Repository,
)


@dataclass(frozen=True, slots=True)
class PreviewPlanningMutationV3:
    records: tuple[PreviewRecordAppendV3, ...]
    response_payload: Mapping[str, object]


class PreviewPlanningPortV3(Protocol):
    async def prepare(
        self,
        *,
        run_id: str,
        user_request: str,
        previous_requirement_id: str | None = None,
    ) -> PreviewPlanningMutationV3: ...

    def select_candidate(
        self,
        *,
        run_id: str,
        candidate_id: str,
        plan_version: int,
    ) -> PreviewPlanningMutationV3: ...

    async def revise(
        self,
        *,
        run_id: str,
        request: ResearchV3ReviseRequest,
        user_request: str,
        plan_version: int,
    ) -> PreviewPlanningMutationV3: ...


class ResearchV3PreviewWorkflow:
    """Owner-scoped planning workflow implementing the isolated HTTP mutation port."""

    _EXECUTION_COMMANDS = frozenset({"approval", "execute", "retry", "skip", "abort"})

    def __init__(
        self,
        *,
        repository: SQLiteResearchV3Repository,
        owner: ResearchV3OwnerScope,
        planner: PreviewPlanningPortV3,
        input_reader: Callable[[str], str | None],
    ) -> None:
        self._repository = repository
        self._owner = owner
        self._planner = planner
        self._input_reader = input_reader

    @staticmethod
    def _api_receipt(
        receipt: ResearchCommandReceiptV3,
        *,
        replayed: bool,
    ) -> ResearchV3MutationReceipt:
        purged_count = None
        if receipt.command_type == "purge":
            raw_count = receipt.response_payload.get("purged_artifact_count")
            if not isinstance(raw_count, int) or isinstance(raw_count, bool) or raw_count < 0:
                raise ApiConflictError("purge receipt lacks an exact Artifact count")
            purged_count = raw_count
        return ResearchV3MutationReceipt(
            run_id=receipt.run_id,
            command_type=receipt.command_type,
            idempotency_key=receipt.idempotency_key,
            request_hash=receipt.request_hash,
            previous_state_version=receipt.committed_state_version - 1,
            state_version=receipt.committed_state_version,
            replayed=replayed,
            purged_artifact_count=purged_count,
        )

    def _require_owner(self, owner: ResearchV3OwnerScope) -> None:
        if owner != self._owner:
            raise ApiNotFoundError

    def _existing_receipt(
        self,
        *,
        run_id: str,
        command_type: ResearchV3CommandType,
        idempotency_key: str,
        request_hash: str,
    ) -> ResearchV3MutationReceipt | None:
        try:
            existing = self._repository.get_command_receipt(run_id, idempotency_key)
        except (ResearchV3NotFoundError, ValueError):
            raise ApiNotFoundError from None
        if existing is None:
            return None
        if existing.command_type != command_type or existing.request_hash != request_hash:
            raise ApiConflictError("idempotency key was already used for a different command")
        return self._api_receipt(existing, replayed=True)

    async def initialize(self, *, run_id: str, user_request: str) -> None:
        mutation = await self._planner.prepare(
            run_id=run_id,
            user_request=user_request,
        )
        request_hash = canonical_json_v3_sha256(
            {
                "command_type": "initialize_preview",
                "run_id": run_id,
                "user_request": user_request,
            }
        )
        self._repository.commit_preview_command(
            run_id=run_id,
            idempotency_key="initialize_preview",
            command_type="initialize_preview",
            request_hash=request_hash,
            response_payload=mutation.response_payload,
            expected_state_version=0,
            records=mutation.records,
        )

    async def apply(
        self,
        run_id: str,
        command_type: ResearchV3CommandType,
        request: ResearchV3MutationRequest,
        *,
        owner: ResearchV3OwnerScope,
        idempotency_key: str,
    ) -> ResearchV3MutationReceipt:
        self._require_owner(owner)
        expected_hash = research_v3_request_hash(command_type, run_id, request)
        if request.request_hash != expected_hash:
            raise ApiConflictError("request_hash does not match the canonical research-v3 command")
        replay = self._existing_receipt(
            run_id=run_id,
            command_type=command_type,
            idempotency_key=idempotency_key,
            request_hash=request.request_hash,
        )
        if replay is not None:
            return replay
        if command_type in self._EXECUTION_COMMANDS:
            raise ApiConflictError("research-v3 preview cannot execute Provider-backed Actors")
        user_request = self._input_reader(run_id)
        if user_request is None:
            raise ApiNotFoundError
        try:
            snapshot = self._repository.projection_snapshot(run_id)
            if snapshot is None:
                raise ApiNotFoundError
            mutation = PreviewPlanningMutationV3(records=(), response_payload={"accepted": True})
            if command_type == "clarify":
                if not isinstance(request, ResearchV3ClarifyRequest) or snapshot.requirement is None:
                    raise ApiConflictError("clarification requires a persisted Requirement")
                answers = "\n".join(
                    f"{item.question_key}: {item.answer}" for item in request.answers
                )
                mutation = await self._planner.prepare(
                    run_id=run_id,
                    user_request=f"{user_request}\nClarification:\n{answers}",
                    previous_requirement_id=snapshot.requirement.id,
                )
            elif command_type == "select_candidate":
                if not isinstance(request, ResearchV3CandidateSelectRequest):
                    raise ApiConflictError("candidate selection request is invalid")
                next_version = 1 if snapshot.selected_plan is None else snapshot.selected_plan.version + 1
                mutation = self._planner.select_candidate(
                    run_id=run_id,
                    candidate_id=request.candidate_id,
                    plan_version=next_version,
                )
            elif command_type == "revise_plan":
                if not isinstance(request, ResearchV3ReviseRequest):
                    raise ApiConflictError("plan revision request is invalid")
                if snapshot.selected_plan is None or snapshot.selected_plan.id != request.plan_version_id:
                    raise ApiConflictError("plan revision does not match the selected Plan")
                mutation = await self._planner.revise(
                    run_id=run_id,
                    request=request,
                    user_request=user_request,
                    plan_version=snapshot.selected_plan.version + 1,
                )
            elif command_type == "confirm_plan":
                if not isinstance(request, ResearchV3ConfirmRequest):
                    raise ApiConflictError("plan confirmation request is invalid")
                if snapshot.selected_plan is None or snapshot.selected_plan.id != request.plan_version_id:
                    raise ApiConflictError("plan confirmation does not match the selected Plan")
                mutation = PreviewPlanningMutationV3(
                    records=(),
                    response_payload={
                        "accepted": True,
                        "preview_only": True,
                        "plan_version_id": request.plan_version_id,
                    },
                )
            elif command_type == "cancel":
                if not isinstance(request, ResearchV3CancelRequest):
                    raise ApiConflictError("cancel request is invalid")
                mutation = PreviewPlanningMutationV3(
                    records=(),
                    response_payload={"accepted": True, "cancelled": True},
                )
            elif command_type == "purge":
                if not isinstance(request, ResearchV3PurgeRequest):
                    raise ApiConflictError("purge request is invalid")
                receipt, replayed = self._repository.purge_run(
                    run_id=run_id,
                    idempotency_key=idempotency_key,
                    request_hash=request.request_hash,
                    expected_state_version=request.expected_state_version,
                )
                return self._api_receipt(receipt, replayed=replayed)
            else:
                request_types = (
                    ResearchV3ApprovalRequest,
                    ResearchV3ExecuteRequest,
                    ResearchV3RetryRequest,
                    ResearchV3SkipRequest,
                    ResearchV3AbortRequest,
                )
                if isinstance(request, request_types):
                    raise ApiConflictError(
                        "research-v3 preview cannot execute Provider-backed Actors"
                    )
                raise ApiConflictError("research-v3 preview command is unsupported")
            receipt, replayed = self._repository.commit_preview_command(
                run_id=run_id,
                idempotency_key=idempotency_key,
                command_type=command_type,
                request_hash=request.request_hash,
                response_payload=mutation.response_payload,
                expected_state_version=request.expected_state_version,
                records=mutation.records,
            )
            return self._api_receipt(receipt, replayed=replayed)
        except ApiNotFoundError:
            raise
        except ResearchV3NotFoundError:
            raise ApiNotFoundError from None
        except (ResearchV3ConflictError, ValueError) as error:
            raise ApiConflictError(str(error) or "research-v3 preview conflict") from None

    def project_request(self, request: ResearchV3AggregateReadRequest):  # noqa: ANN201
        self._require_owner(request.owner)
        return request
