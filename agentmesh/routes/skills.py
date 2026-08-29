"""Standards-compliant Skill catalog routes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from agentmesh.harness.skill_packages import SkillPackageError, SkillPackageService
from agentmesh.models import (
    ItemsResponse,
    SkillBinding,
    SkillBindingUpdateRequest,
    SkillCandidate,
    SkillCatalogItem,
    SkillCatalogItemResponse,
    SkillCatalogResponse,
    SkillMatchItem,
    SkillMatchRequest,
    SkillMatchResponse,
    SkillRecommendationCandidateView,
    SkillRecommendationRequest,
    SkillRecommendationResponse,
    User,
    now_utc,
)
from agentmesh.permissions import ensure_admin
from agentmesh.routes.deps import create_audit_event, current_user, require_default_project
from agentmesh.skill_runtime.planner import SkillIntentAnalyzer
from agentmesh.skill_runtime.profiles import skill_capability_card
from agentmesh.skill_runtime.recommendation import UniversalSkillSearchService, recommend_skill_directory
from agentmesh.skill_runtime.retrieval import SkillCandidateRetriever
from agentmesh.skill_runtime.service import catalog_service
from agentmesh.skill_runtime.trust import runtime_profile_trust_verifier
from agentmesh.store import store
from agentmesh.task_routing.contracts import TaskRoutingPreviewRequest, TaskRoutingPreviewResponse
from agentmesh.task_routing.router import TaskScenarioRouter

router = APIRouter(prefix="/api/skills", tags=["skills"])
_package_service = SkillPackageService(
    store,
    Path(os.getenv("AGENTMESH_SKILL_PACKAGE_DIR", Path(__file__).resolve().parents[2] / "data" / "skill_packages")),
)
_intent_analyzer = SkillIntentAnalyzer()
_task_router = TaskScenarioRouter()


def _public_candidate(candidate: SkillCandidate) -> SkillRecommendationCandidateView:
    skill = store.get_skill_definition(candidate.skill_id)
    if skill is None:
        raise RuntimeError("recommended_skill_missing")
    return SkillRecommendationCandidateView(
        skill_id=candidate.skill_id,
        skill_name=candidate.skill_name,
        title=candidate.title,
        description=candidate.description,
        capability_card=skill_capability_card(skill, candidate.profile),
        score=candidate.score,
        reason=candidate.reason,
        match_reason_codes=candidate.match_reason_codes,
        ready=candidate.ready,
        diagnostics=candidate.diagnostics,
        coverage_witness_scenario_id=candidate.coverage_witness_scenario_id,
        covered_requirement_ids=candidate.covered_requirement_ids,
    )


@router.get("", response_model=SkillCatalogResponse)
def list_skills(user: User = Depends(current_user)) -> SkillCatalogResponse:
    return _skill_catalog_response(user)


def _skill_catalog_response(user: User) -> SkillCatalogResponse:
    catalog = catalog_service()
    supported_tool_names = catalog.supported_tool_names()
    bindings = {
        binding.skill_id: binding.enabled
        for binding in store.list_agent_skill_bindings(user.personal_agent_id)
    }
    items = [
        catalog.to_chat_skill(
            skill,
            enabled=enabled,
            binding_enabled=bindings.get(skill.id, True),
            supported_tool_names=supported_tool_names,
        )
        for skill, enabled in catalog.list_for_agent(user.personal_agent_id)
    ]
    return SkillCatalogResponse(items=items)


@router.post("/matches", response_model=SkillMatchResponse)
async def match_skills(
    request: SkillMatchRequest,
    user: User = Depends(current_user),
) -> SkillMatchResponse:
    catalog = catalog_service()
    enabled_skills = [
        skill
        for skill, enabled in catalog.list_for_agent(user.personal_agent_id)
        if enabled
    ]
    from agentmesh.routes.chat import agent

    selected = None
    runtime = agent.agent_runtime
    if runtime is not None and runtime.enabled:
        try:
            selected = runtime.select_model(user)
        except ValueError:
            selected = None
    recommendation = await recommend_skill_directory(
        request.content,
        enabled_skills,
        repository=store,
        limit=request.limit,
        model=selected.model if selected is not None else None,
    )
    supported_tool_names = catalog.supported_tool_names()
    items: list[SkillMatchItem] = []
    for match in recommendation.matches:
        catalog_item = SkillCatalogItem.model_validate(
            catalog.to_chat_skill(match.skill, supported_tool_names=supported_tool_names)
        )
        items.append(
            SkillMatchItem(
                skill_id=match.skill.id,
                skill_name=match.skill.name,
                command=catalog_item.command,
                title=catalog_item.title,
                description=catalog_item.description,
                primary_stage=catalog_item.primary_stage,
                score=match.score,
                reason=match.reason,
                planner_eligible=catalog_item.planner_eligible,
                readiness=catalog_item.readiness,
                execution_readiness=catalog_item.execution_readiness,
                missing_tools=catalog_item.missing_tools,
            )
        )
    return SkillMatchResponse(
        items=items,
        mode=recommendation.mode,
        clarification=recommendation.clarification,
        diagnostics=recommendation.diagnostics,
    )


@router.post("/routing-preview", response_model=TaskRoutingPreviewResponse)
def preview_task_routing(
    request: TaskRoutingPreviewRequest,
    user: User = Depends(current_user),
) -> TaskRoutingPreviewResponse:
    project = require_default_project(user, store)
    thread_summary = ""
    if request.thread_id:
        thread = store.get_chat_thread(request.thread_id)
        if (
            thread is None
            or thread.user_id != user.id
            or thread.workspace_id != user.workspace_id
            or thread.project_id != user.default_project_id
        ):
            raise HTTPException(status_code=404, detail="Chat thread not found")
        thread_summary = "\n".join(message.content[:500] for message in store.list_thread_messages(thread.id)[-6:])
    routing_result, diagnostics = _task_router.route(
        request.content,
        project_summary=project.goal,
        thread_summary=thread_summary,
    )
    require_default_project(user, store)
    return TaskRoutingPreviewResponse(routing_result=routing_result, diagnostics=diagnostics)


@router.post("/recommendations", response_model=SkillRecommendationResponse)
async def recommend_skills(
    request: SkillRecommendationRequest,
    user: User = Depends(current_user),
) -> SkillRecommendationResponse:
    from agentmesh.routes.chat import agent

    project = require_default_project(user, store)
    thread_summary = ""
    if request.thread_id:
        thread = store.get_chat_thread(request.thread_id)
        if (
            thread is None
            or thread.user_id != user.id
            or thread.workspace_id != user.workspace_id
            or thread.project_id != user.default_project_id
        ):
            raise HTTPException(status_code=404, detail="Chat thread not found")
        thread_summary = "\n".join(message.content[:500] for message in store.list_thread_messages(thread.id)[-6:])
    selected = None
    runtime = agent.agent_runtime
    if runtime is not None and runtime.enabled:
        try:
            selected = runtime.select_model(user)
        except ValueError:
            selected = None
    intent, intent_diagnostics = await _intent_analyzer.analyze(
        request.content,
        model=selected.model if selected is not None else None,
        project_summary=project.goal,
        thread_summary=thread_summary,
    )
    require_default_project(user, store)
    verifier = runtime_profile_trust_verifier()
    if verifier.available:
        result = UniversalSkillSearchService(
            store,
            catalog_service(),
            profile_trust=verifier,
        ).search(user, intent)
        return SkillRecommendationResponse(
            intent=intent,
            candidates=[_public_candidate(candidate) for candidate in result.selectable_candidates],
            blocked_matches=[_public_candidate(candidate) for candidate in result.blocked_matches],
            retrieval_policy_version=result.retrieval_policy_version,
            outcome_code=result.outcome_code,
            searchable_count=result.searchable_count,
            selectable_count=len(result.selectable_candidates),
            blocked_match_count=len(result.blocked_matches),
            required_coverage_atoms=list(result.required_coverage_atoms),
            required_synthesis_output_ids=list(result.required_synthesis_output_ids),
            capability_gaps=list(result.capability_gaps),
            diagnostics=list(dict.fromkeys([*intent_diagnostics, *result.diagnostics])),
        )

    candidates, retrieval_diagnostics = SkillCandidateRetriever(store, catalog_service()).recommend(user, intent)
    return SkillRecommendationResponse(
        intent=intent,
        candidates=[_public_candidate(candidate) for candidate in candidates],
        outcome_code="legacy_trust_fallback",
        selectable_count=len(candidates),
        blocked_match_count=0,
        diagnostics=list(
            dict.fromkeys(
                [
                    *intent_diagnostics,
                    *retrieval_diagnostics,
                    "skill_profile_trust_unavailable",
                ]
            )
        ),
    )


@router.patch("/{skill_id}/binding")
def update_skill_binding(
    skill_id: str,
    request: SkillBindingUpdateRequest,
    user: User = Depends(current_user),
) -> SkillCatalogItemResponse:
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
    effective_enabled = catalog.is_runtime_enabled(skill, binding_enabled=saved.enabled)
    return SkillCatalogItemResponse(
        item=catalog.to_chat_skill(
            skill,
            enabled=effective_enabled,
            binding_enabled=saved.enabled,
            supported_tool_names=catalog.supported_tool_names(),
        )
    )


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


@router.post("/reload", response_model=SkillCatalogResponse)
def reload_skills(user: User = Depends(current_user)) -> SkillCatalogResponse:
    ensure_admin(user)
    catalog = catalog_service()
    catalog.reload()
    response = _skill_catalog_response(user)
    store.add_audit_event(
        create_audit_event(
            user.id,
            "reload_skill_catalog",
            "skill_catalog",
            "workspace",
            {"count": len(response.items), "diagnostics": len(catalog.diagnostics)},
        )
    )
    return response
