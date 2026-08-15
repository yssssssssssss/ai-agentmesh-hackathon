"""Auth routes."""

from __future__ import annotations

import hashlib
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from agentmesh.auth import (
    clear_session_cookie,
    create_password_hash,
    current_user_from_request,
    hash_session_token,
    issue_session,
    set_session_cookie,
    verify_password,
)
from agentmesh.models import Agent, LoginRequest, PasswordChangeRequest, StatusResponse, User, UserResponse, now_utc
from agentmesh.routes.deps import create_audit_event, current_user
from agentmesh.seed import PROJECT, WORKSPACE, ensure_demo_seed_data, ensure_user_default_membership
from agentmesh.store import store

router = APIRouter(prefix="/api/auth", tags=["auth"])
OAUTH_STATE_COOKIE = "agentmesh_oauth_state"


def revoke_user_sessions(user_id: str) -> int:
    revoked = 0
    now = now_utc()
    for session in store.auth_sessions:
        if session.user_id == user_id and session.revoked_at is None:
            session.revoked_at = now
            store.save_auth_session(session)
            revoked += 1
    return revoked


@router.post("/login", response_model=UserResponse)
def login(request: LoginRequest, response: Response) -> UserResponse:
    ensure_demo_seed_data(store)
    user = store.get_user(request.user_id)
    credential = store.get_auth_credential(request.user_id)
    if (
        user is None
        or user.status != "active"
        or credential is None
        or not verify_password(request.password, credential.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid user id or password")
    _, token = issue_session(store, user)
    set_session_cookie(response, token)
    return UserResponse(user=user)


@router.get("/oauth/status")
def oauth_status() -> dict[str, object]:
    config = oauth_config()
    configured = oauth_configured(config)
    return {
        "enabled": config["enabled"],
        "configured": configured,
        "provider": config["provider"],
        "authorize_url_configured": bool(config["authorize_url"]),
        "token_url_configured": bool(config["token_url"]),
        "userinfo_url_configured": bool(config["userinfo_url"]),
        "client_id_configured": bool(config["client_id"]),
        "redirect_uri": config["redirect_uri"],
    }


@router.get("/oauth/start")
def oauth_start() -> RedirectResponse:
    config = oauth_config()
    if not oauth_configured(config):
        raise HTTPException(status_code=503, detail="OAuth is not configured")
    state = secrets.token_urlsafe(24)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
            "scope": config["scope"],
            "state": state,
        }
    )
    response = RedirectResponse(f"{config['authorize_url']}?{query}", status_code=302)
    response.set_cookie(OAUTH_STATE_COOKIE, state, httponly=True, secure=os.getenv("AGENTMESH_COOKIE_SECURE") == "1", samesite="lax", max_age=600)
    return response


@router.get("/oauth/callback", response_model=UserResponse)
def oauth_callback(code: str, state: str, request: Request, response: Response) -> UserResponse:
    config = oauth_config()
    if not oauth_configured(config):
        raise HTTPException(status_code=503, detail="OAuth is not configured")
    if not state or request.cookies.get(OAUTH_STATE_COOKIE) != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    token_payload = exchange_oauth_code(config, code)
    access_token = token_payload.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="OAuth token response did not include access_token")
    profile = fetch_oauth_userinfo(config, str(access_token))
    user = upsert_oauth_user(profile, config)
    _, session_token = issue_session(store, user)
    set_session_cookie(response, session_token)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    store.add_audit_event(create_audit_event(user.id, "oauth_login", "user", user.id, {"provider": config["provider"]}))
    return UserResponse(user=user)


@router.post("/logout", response_model=StatusResponse)
def logout(request: Request, response: Response) -> StatusResponse:
    token = request.cookies.get("agentmesh_session")
    if token:
        session = store.get_auth_session_by_token_hash(hash_session_token(token))
        if session is not None and session.revoked_at is None:
            session.revoked_at = now_utc()
            store.save_auth_session(session)
    clear_session_cookie(response)
    return StatusResponse(status="ok")


@router.get("/me", response_model=UserResponse)
def auth_me(request: Request) -> UserResponse:
    ensure_demo_seed_data(store)
    user = current_user_from_request(store, request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UserResponse(user=user)


@router.post("/password", response_model=StatusResponse)
def change_password(
    request: PasswordChangeRequest,
    response: Response,
    user: User = Depends(current_user),
) -> StatusResponse:
    credential = store.get_auth_credential(user.id)
    if credential is None or not verify_password(request.current_password, credential.password_hash):
        raise HTTPException(status_code=401, detail="Invalid current password")
    credential.password_hash = create_password_hash(request.new_password)
    credential.updated_at = now_utc()
    store.save_auth_credential(credential)
    revoked = revoke_user_sessions(user.id)
    clear_session_cookie(response)
    store.add_audit_event(
        create_audit_event(user.id, "change_password", "user", user.id, {"revoked_sessions": revoked})
    )
    return StatusResponse(status="ok")


def oauth_config() -> dict[str, str | bool]:
    return {
        "enabled": os.getenv("AGENTMESH_OAUTH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
        "provider": os.getenv("AGENTMESH_OAUTH_PROVIDER", "corporate_oauth"),
        "authorize_url": os.getenv("AGENTMESH_OAUTH_AUTHORIZE_URL", ""),
        "token_url": os.getenv("AGENTMESH_OAUTH_TOKEN_URL", ""),
        "userinfo_url": os.getenv("AGENTMESH_OAUTH_USERINFO_URL", ""),
        "client_id": os.getenv("AGENTMESH_OAUTH_CLIENT_ID", ""),
        "client_secret": os.getenv("AGENTMESH_OAUTH_CLIENT_SECRET", ""),
        "redirect_uri": os.getenv("AGENTMESH_OAUTH_REDIRECT_URI", "http://127.0.0.1:8010/api/auth/oauth/callback"),
        "scope": os.getenv("AGENTMESH_OAUTH_SCOPE", "openid profile email"),
        "default_role": os.getenv("AGENTMESH_OAUTH_DEFAULT_ROLE", "user"),
    }


def oauth_configured(config: dict[str, str | bool]) -> bool:
    return bool(
        config["enabled"]
        and config["authorize_url"]
        and config["token_url"]
        and config["userinfo_url"]
        and config["client_id"]
    )


def exchange_oauth_code(config: dict[str, str | bool], code: str) -> dict[str, object]:
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config["redirect_uri"],
        "client_id": config["client_id"],
    }
    if config["client_secret"]:
        payload["client_secret"] = config["client_secret"]
    with httpx.Client(timeout=20) as client:
        response = client.post(str(config["token_url"]), data=payload)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="OAuth token response was not an object")
    return data


def fetch_oauth_userinfo(config: dict[str, str | bool], access_token: str) -> dict[str, object]:
    with httpx.Client(timeout=20) as client:
        response = client.get(str(config["userinfo_url"]), headers={"Authorization": f"Bearer {access_token}"})
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="OAuth userinfo response was not an object")
    return data


def upsert_oauth_user(profile: dict[str, object], config: dict[str, str | bool]) -> User:
    ensure_demo_seed_data(store)
    external_id = str(profile.get("sub") or profile.get("id") or profile.get("erp") or "").strip()
    if not external_id:
        raise HTTPException(status_code=502, detail="OAuth userinfo missing stable identity")
    provider = str(config["provider"])
    email = str(profile.get("email") or "")
    name = str(profile.get("name") or profile.get("displayName") or profile.get("erp") or email or external_id)
    existing = next(
        (
            user
            for user in store.users
            if user.oauth_provider == provider and user.oauth_subject == external_id
        ),
        None,
    )
    role = oauth_default_role(config)
    if existing is not None:
        if existing.status != "active":
            raise HTTPException(status_code=403, detail="OAuth account is disabled")
        updated = existing.model_copy(deep=True)
        updated.name = name
        updated.updated_at = now_utc()
        ensure_user_default_membership(store, updated)
        return store.save_user(updated)

    user_id = oauth_user_id(provider, external_id)
    if store.get_user(user_id) is not None:
        raise HTTPException(status_code=409, detail="OAuth identity is already bound")
    user = User(
        id=user_id,
        workspace_id=WORKSPACE.id,
        default_project_id=PROJECT.id,
        name=name,
        role=role,
        personal_agent_id=f"agent_personal_{user_id.removeprefix('usr_')}",
        oauth_provider=provider,
        oauth_subject=external_id,
    )
    agent = Agent(
        id=user.personal_agent_id,
        workspace_id=WORKSPACE.id,
        name=f"{name}的个人 Agent",
        agent_type="personal",
        description="由 OAuth 登录自动创建的个人 Agent。",
        owner_user_id=user.id,
        capabilities=["chat", "private_memory", "task_routing"],
    )
    store.save_user(user)
    store.save_agent(agent)
    ensure_user_default_membership(store, user)
    return user


def oauth_user_id(provider: str, external_id: str) -> str:
    digest = hashlib.sha256(f"{provider}:{external_id}".encode()).hexdigest()[:20]
    return f"usr_oauth_{digest}"


def oauth_default_role(config: dict[str, str | bool]) -> str:
    role = str(config.get("default_role") or "user")
    return role if role in {"user", "team_lead", "admin"} else "user"


def safe_identity_id(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    return cleaned.strip("_")[:80] or secrets.token_hex(8)
