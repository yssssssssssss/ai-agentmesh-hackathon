"""Administrative lifecycle controls for safe orchestration shutdown."""

from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agentmesh.models import User
from agentmesh.permissions import ensure_admin
from agentmesh.routes.deps import current_user
from agentmesh.skill_runtime.quiesce import OrchestrationQuiesceController

router = APIRouter(prefix="/api/admin/skill-orchestration", tags=["admin"])


def _require_loopback_peer(request: Request) -> None:
    host = request.client.host if request.client is not None else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "management_network_required"},
        ) from error
    if not address.is_loopback:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "management_network_required"},
        )


@router.post("/quiesce")
async def quiesce_skill_orchestration(
    request: Request,
    user: User = Depends(current_user),
) -> dict[str, object]:
    ensure_admin(user)
    _require_loopback_peer(request)
    controller = getattr(request.app.state, "orchestration_quiesce_controller", None)
    if not isinstance(controller, OrchestrationQuiesceController):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "orchestration_quiesce_unavailable"},
        )
    recovery = getattr(request.app.state, "deepsearch_recovery_coordinator", None)
    stop_recovery = getattr(recovery, "begin_quiesce", None)
    await controller.begin_quiesce(stop_recovery if callable(stop_recovery) else None)
    return {
        "state": "quiesced",
        "active_permits": controller.active_permits,
        "deepsearch_recovery_running": bool(
            recovery is not None and getattr(recovery, "running", False)
        ),
    }
