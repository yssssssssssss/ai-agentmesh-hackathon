"""Risk policy routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.models import (
    RiskPoliciesResponse,
    RiskPolicyRule,
    RiskPolicyRuleCreateRequest,
    RiskPolicyRuleUpdateRequest,
    User,
    now_utc,
)
from agentmesh.permissions import ACTION_MANAGE_RISK_POLICIES
from agentmesh.routes.deps import create_audit_event, require_permission, validate_risk_decision
from agentmesh.store import store

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/policies", response_model=RiskPoliciesResponse)
def risk_policies(_: User = Depends(require_permission(ACTION_MANAGE_RISK_POLICIES))) -> RiskPoliciesResponse:
    return RiskPoliciesResponse(items=store.risk_policy_rules)


@router.post("/policies")
def create_risk_policy(
    request: RiskPolicyRuleCreateRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_RISK_POLICIES)),
) -> dict[str, object]:
    rule = RiskPolicyRule(
        rule_id=request.rule_id,
        category=request.category,
        signal=request.signal,
        message=request.message,
        decision=validate_risk_decision(request.decision),
        enabled=request.enabled,
    )
    saved = store.save_risk_policy_rule(rule)
    store.add_audit_event(create_audit_event(user.id, "create_risk_policy", "risk_policy_rule", saved.id, {}))
    return {"item": saved}


@router.patch("/policies/{rule_id}")
def update_risk_policy(
    rule_id: str,
    request: RiskPolicyRuleUpdateRequest,
    user: User = Depends(require_permission(ACTION_MANAGE_RISK_POLICIES)),
) -> dict[str, object]:
    rule = store.get_risk_policy_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Risk policy rule not found")
    updated = rule.model_copy(deep=True)
    if request.rule_id is not None:
        updated.rule_id = request.rule_id
    if request.category is not None:
        updated.category = request.category
    if request.signal is not None:
        updated.signal = request.signal
    if request.message is not None:
        updated.message = request.message
    if request.decision is not None:
        updated.decision = validate_risk_decision(request.decision)
    if request.enabled is not None:
        updated.enabled = request.enabled
    updated.updated_at = now_utc()
    saved = store.save_risk_policy_rule(updated)
    store.add_audit_event(
        create_audit_event(user.id, "update_risk_policy", "risk_policy_rule", saved.id, {"enabled": saved.enabled})
    )
    return {"item": saved}
