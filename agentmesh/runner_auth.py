from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from agentmesh.models import User
from agentmesh.runner_contracts import RunnerCredentialV1, RunnerDeviceStatus, RunnerDeviceV1
from agentmesh.store import SQLiteStore, store

_RUNNER_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True, slots=True)
class AuthenticatedRunner:
    device: RunnerDeviceV1
    credential: RunnerCredentialV1
    user: User


def hash_runner_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_runner_token() -> str:
    return secrets.token_urlsafe(32)


def generate_runner_user_code() -> str:
    value = "".join(secrets.choice(_RUNNER_USER_CODE_ALPHABET) for _ in range(8))
    return f"{value[:4]}-{value[4:]}"


def runner_from_request(repository: SQLiteStore, request: Request) -> AuthenticatedRunner | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    credential = repository.get_runner_credential_by_token_hash(hash_runner_token(token))
    if credential is None or credential.revoked_at is not None:
        return None
    device = repository.get_runner_device(credential.runner_id)
    if device is None or device.status is not RunnerDeviceStatus.ACTIVE:
        return None
    user = repository.get_user(device.owner_user_id)
    if user is None or user.status != "active" or user.workspace_id != device.workspace_id:
        return None
    return AuthenticatedRunner(device=device, credential=credential, user=user)


def require_current_runner(request: Request) -> AuthenticatedRunner:
    authenticated = runner_from_request(store, request)
    if authenticated is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Runner authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authenticated
