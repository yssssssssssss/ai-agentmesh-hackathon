"""Read and advance the DeepSearch Requirement state machine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.routing import APIRoute
from starlette.types import Message

from agentmesh.deepsearch.contracts import DeepSearchClarifyRequestV1, DeepSearchStateResponse
from agentmesh.deepsearch.planning import RequirementRefinerUnavailable
from agentmesh.deepsearch.service import (
    DeepSearchExecutionUnavailable,
    DeepSearchPlanningService,
    DeepSearchRequirementIntegrityError,
    DeepSearchRequirementInvalid,
)
from agentmesh.models import AgentPlanningMode, AgentRun, User, new_id
from agentmesh.routes.deps import current_user
from agentmesh.runtime_capacity import (
    RuntimeCapacityError,
    current_runtime_capacity,
)
from agentmesh.store import DeepSearchRequirementConflict, ResearchStoreConflict, store

_CLARIFICATION_PATH = "/api/agent/runs/{run_id}/deepsearch/clarify"
_MAX_CLARIFICATION_BODY_BYTES = 16 * 1_024
_PAYLOAD_TOO_LARGE_CODE = "deepsearch_clarification_payload_too_large"


def _payload_too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail={"code": _PAYLOAD_TOO_LARGE_CODE},
    )


def _declared_body_exceeds_limit(request: Request) -> bool:
    values = request.headers.getlist("content-length")
    if len(values) != 1 or not values[0] or any(character not in "0123456789" for character in values[0]):
        return False
    return int(values[0]) > _MAX_CLARIFICATION_BODY_BYTES


class _ClarificationBodyLimitRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        route_handler = super().get_route_handler()
        if self.path != _CLARIFICATION_PATH or "POST" not in self.methods:
            return route_handler

        async def limited_route_handler(request: Request) -> Response:
            if _declared_body_exceeds_limit(request):
                raise _payload_too_large()

            receive = request.receive
            received_bytes = 0

            async def limited_receive() -> Message:
                nonlocal received_bytes
                message = await receive()
                if message["type"] == "http.request":
                    received_bytes += len(message.get("body", b""))
                    if received_bytes > _MAX_CLARIFICATION_BODY_BYTES:
                        raise _payload_too_large()
                return message

            return await route_handler(Request(request.scope, receive=limited_receive))

        return limited_route_handler


router = APIRouter(
    prefix="/api/agent/runs",
    tags=["deepsearch"],
    route_class=_ClarificationBodyLimitRoute,
)

def get_deepsearch_planning_service() -> DeepSearchPlanningService:
    from agentmesh.routes.chat import agent

    runtime = agent.agent_runtime
    service = getattr(runtime, "deepsearch_planning_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "deepsearch_planner_unavailable"},
        )
    return service


DeepSearchService = Annotated[DeepSearchPlanningService, Depends(get_deepsearch_planning_service)]
CurrentUser = Annotated[User, Depends(current_user)]


def _visible_deepsearch_run(run_id: str, user: User) -> AgentRun:
    run = store.get_agent_run(run_id)
    thread = store.get_chat_thread(run.thread_id) if run is not None else None
    if (
        run is None
        or run.user_id != user.id
        or run.workspace_id != user.workspace_id
        or thread is None
        or thread.status != "active"
        or thread.user_id != run.user_id
        or thread.workspace_id != run.workspace_id
        or thread.project_id != run.project_id
        or not store.user_can_execute_agent_run(user.id, run_id)
    ):
        raise HTTPException(status_code=404, detail="Agent run not found")
    if (
        run.orchestration_version != "v1"
        or run.planning_mode != AgentPlanningMode.DEEPSEARCH
    ):
        raise HTTPException(status_code=409, detail={"code": "deepsearch_mode_required"})
    return run


def _conflict(error: DeepSearchRequirementConflict) -> HTTPException:
    detail: dict[str, object] = {"code": error.code}
    if error.current_requirement_version is not None:
        detail["current_requirement_version"] = error.current_requirement_version
    return HTTPException(status_code=409, detail=detail)


def _with_scenario_assignment_options(
    state: DeepSearchStateResponse,
) -> DeepSearchStateResponse:
    from agentmesh.routes.agent_runs import (
        _blocked_matches_view,
        _scenario_assignment_options_view,
    )

    blocked_matches = _blocked_matches_view(state.run.id)
    if state.plan is None:
        return state.model_copy(update={"blocked_matches": blocked_matches})
    plan = store.get_skill_plan(state.plan.id)
    if plan is None:
        return state.model_copy(update={"blocked_matches": blocked_matches})

    return state.model_copy(
        update={
            "scenario_assignment_options": _scenario_assignment_options_view(plan),
            "blocked_matches": blocked_matches,
        }
    )


@router.get("/{run_id}/deepsearch", response_model=DeepSearchStateResponse)
def get_deepsearch_state(
    run_id: str,
    user: CurrentUser,
    service: DeepSearchService,
) -> DeepSearchStateResponse:
    run = _visible_deepsearch_run(run_id, user)
    try:
        return _with_scenario_assignment_options(service.get_state(run))
    except (DeepSearchRequirementIntegrityError, ResearchStoreConflict) as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "deepsearch_requirement_integrity_failed"},
        ) from error


@router.post(
    "/{run_id}/deepsearch/clarify",
    response_model=DeepSearchStateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def clarify_deepsearch_requirement(
    run_id: str,
    request: DeepSearchClarifyRequestV1,
    user: CurrentUser,
    service: DeepSearchService,
) -> DeepSearchStateResponse:
    run = _visible_deepsearch_run(run_id, user)
    capacity = current_runtime_capacity()
    capacity_key = new_id("deepsearch_clarification")
    accepted, capacity_created = capacity.claim_run(
        operation_key=capacity_key,
        user_id=user.id,
    )
    if not accepted:
        raise HTTPException(
            status_code=429,
            detail={"code": RuntimeCapacityError.code},
            headers={"Retry-After": "1"},
        )
    try:
        return _with_scenario_assignment_options(
            await service.clarify(run=run, request=request)
        )
    except DeepSearchRequirementConflict as error:
        raise _conflict(error) from error
    except DeepSearchRequirementInvalid as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "deepsearch_clarification_invalid", "message": str(error)},
        ) from error
    except RequirementRefinerUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "deepsearch_planner_unavailable"},
        ) from error
    except DeepSearchExecutionUnavailable as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "deepsearch_execution_unavailable"},
        ) from error
    except DeepSearchRequirementIntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "deepsearch_requirement_integrity_failed"},
        ) from error
    except ResearchStoreConflict as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "deepsearch_requirement_state_conflict"},
        ) from error
    finally:
        if capacity_created:
            capacity.release_run(capacity_key)
