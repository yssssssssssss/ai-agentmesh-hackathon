"""Standards-compliant Skill catalog routes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from agentmesh.harness.skill_packages import SkillPackageError, SkillPackageService
from agentmesh.models import ItemsResponse, SkillBinding, SkillBindingUpdateRequest, User, now_utc
from agentmesh.permissions import ensure_admin
from agentmesh.routes.deps import create_audit_event, current_user
from agentmesh.skill_runtime.service import catalog_service
from agentmesh.store import store

router = APIRouter(prefix="/api/skills", tags=["skills"])
_package_service = SkillPackageService(
    store,
    Path(os.getenv("AGENTMESH_SKILL_PACKAGE_DIR", Path(__file__).resolve().parents[2] / "data" / "skill_packages")),
)


@router.get("", response_model=ItemsResponse)
def list_skills(user: User = Depends(current_user)) -> ItemsResponse:
    catalog = catalog_service()
    items = [
        catalog.to_chat_skill(skill, enabled=enabled)
        for skill, enabled in catalog.list_for_agent(user.personal_agent_id)
    ]
    return ItemsResponse(items=items)


@router.patch("/{skill_id}/binding")
def update_skill_binding(
    skill_id: str,
    request: SkillBindingUpdateRequest,
    user: User = Depends(current_user),
) -> dict[str, object]:
    catalog = catalog_service()
    skill = next((item for item, _enabled in catalog.list_for_agent(user.personal_agent_id) if item.id == skill_id), None)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    existing = next(
        (binding for binding in store.list_agent_skill_bindings(user.personal_agent_id) if binding.skill_id == skill_id),
        None,
    )
    if existing is None:
        binding = SkillBinding(
            id=f"skill_binding_{user.personal_agent_id}_{skill_id}",
            agent_id=user.personal_agent_id,
            skill_id=skill_id,
            enabled=request.enabled,
            aliases=request.aliases or [],
            granted_by=user.id,
        )
    else:
        binding = existing.model_copy(deep=True)
        binding.enabled = request.enabled
        if request.aliases is not None:
            binding.aliases = request.aliases
        binding.granted_by = user.id
        binding.updated_at = now_utc()
    saved = store.save_skill_binding(binding)
    store.add_audit_event(
        create_audit_event(
            user.id,
            "update_skill_binding",
            "skill_binding",
            saved.id,
            {"skill_id": skill_id, "enabled": saved.enabled},
        )
    )
    return {"item": catalog.to_chat_skill(skill, enabled=saved.enabled)}


@router.get("/packages", response_model=ItemsResponse)
def list_skill_packages(user: User = Depends(current_user)) -> ItemsResponse:
    ensure_admin(user)
    return ItemsResponse(items=store.skill_packages)


@router.post("/packages/import")
async def import_skill_package(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
) -> dict[str, object]:
    ensure_admin(user)
    archive = await file.read(20 * 1024 * 1024 + 1)
    try:
        package = _package_service.import_zip(
            archive,
            file_name=file.filename or "skill-package.zip",
            created_by=user.id,
        )
    except SkillPackageError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    store.add_audit_event(
        create_audit_event(user.id, "import_skill_package", "skill_package", package.id, {"status": package.status})
    )
    return {"item": package}


@router.post("/packages/{package_id}/activate")
def activate_skill_package(package_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    ensure_admin(user)
    try:
        package = _package_service.activate(package_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    catalog_service().reload()
    store.add_audit_event(
        create_audit_event(user.id, "activate_skill_package", "skill_package", package.id, {"version": package.version})
    )
    return {"item": package}


@router.post("/packages/{package_id}/disable")
def disable_skill_package(package_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    ensure_admin(user)
    try:
        package = _package_service.disable(package_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    catalog_service().reload()
    store.add_audit_event(
        create_audit_event(user.id, "disable_skill_package", "skill_package", package.id, {})
    )
    return {"item": package}


@router.get("/diagnostics", response_model=ItemsResponse)
def skill_diagnostics(user: User = Depends(current_user)) -> ItemsResponse:
    ensure_admin(user)
    items = [
        {"level": item.level, "code": item.code, "message": item.message, "path": item.path}
        for item in catalog_service().diagnostics
    ]
    return ItemsResponse(items=items)


@router.post("/reload", response_model=ItemsResponse)
def reload_skills(user: User = Depends(current_user)) -> ItemsResponse:
    ensure_admin(user)
    catalog = catalog_service()
    skills = catalog.reload()
    store.add_audit_event(
        create_audit_event(
            user.id,
            "reload_skill_catalog",
            "skill_catalog",
            "workspace",
            {"count": len(skills), "diagnostics": len(catalog.diagnostics)},
        )
    )
    return ItemsResponse(items=[catalog.to_chat_skill(skill) for skill in skills])
