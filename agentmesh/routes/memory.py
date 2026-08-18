"""Memory routes."""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import date as dt_date

from fastapi import APIRouter, Depends, HTTPException, Query

from agentmesh.llm import LLMClient
from agentmesh.model_registry import resolve_agent_model_id
from agentmesh.models import (
    DailyMemorySummaryRequest,
    GroupMemorySummaryRequest,
    ItemResponse,
    ItemsResponse,
    MemoryCreateRequest,
    MemoryItem,
    MemoryItemsResponse,
    MemoryItemView,
    MemoryLayer,
    MemoryOverviewResponse,
    MemoryRelation,
    MemoryStatus,
    MemoryUpdateRequest,
    ProjectArchiveRequest,
    ProjectMemorySummaryRequest,
    Scope,
    SkillStatus,
    User,
    UserMemoryCreateRequest,
    UserMemoryItem,
    UserRole,
    now_utc,
)
from agentmesh.permissions import ACTION_ACCEPT_TEAM_MEMORY, ensure_can_update_memory, has_permission
from agentmesh.routes.deps import current_user
from agentmesh.skill_runtime.materialize import materialize_learned_skill
from agentmesh.skill_runtime.service import catalog_service
from agentmesh.store import store

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


DAILY_SUMMARY_WORKER_ENABLED = os.getenv("AGENTMESH_DAILY_MEMORY_WORKER_ENABLED", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DAILY_SUMMARY_WORKER_INTERVAL_SECONDS = _positive_int_env("AGENTMESH_DAILY_MEMORY_WORKER_INTERVAL_SECONDS", 3600)
daily_summary_worker_task: asyncio.Task | None = None
daily_summary_worker_state: dict[str, object] = {
    "enabled": DAILY_SUMMARY_WORKER_ENABLED,
    "interval_seconds": DAILY_SUMMARY_WORKER_INTERVAL_SECONDS,
    "running": False,
    "last_run_at": None,
    "last_created": 0,
    "last_skipped_existing": 0,
    "last_skipped_empty": 0,
    "last_error": None,
}


@router.get("", response_model=MemoryItemsResponse)
def memory_items(
    project_id: str | None = Query(default=None, min_length=1, max_length=120),
    user: User = Depends(current_user),
) -> MemoryItemsResponse:
    resolved_project_id = _resolve_user_project_id(user, project_id)
    items = [memory_item_view(item, user) for item in _visible_memory_items(user, resolved_project_id)]
    return MemoryItemsResponse(items=items)


@router.post("", response_model=ItemResponse)
def create_memory_item(request: MemoryCreateRequest, user: User = Depends(current_user)) -> ItemResponse:
    if request.scope == Scope.TEAM_ACCEPTED:
        raise HTTPException(status_code=403, detail="Team memory must be reviewed before acceptance")
    scope = Scope.TEAM_CANDIDATE if request.scope == Scope.PROJECT else request.scope
    item = store.add_memory_item(
        MemoryItem(
            title=request.title,
            summary=request.summary,
            memory_type=request.memory_type,
            scope=scope,
            status=MemoryStatus.PROPOSED,
            owner_user_id=user.id,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
        )
    )
    return ItemResponse(item=item)


@router.get("/user", response_model=ItemsResponse)
def user_memory_items(
    layer: MemoryLayer | None = Query(default=None),
    project_id: str | None = Query(default=None, min_length=1, max_length=120),
    memory_date: dt_date | None = Query(default=None),
    memory_type: str | None = Query(default=None, min_length=1, max_length=80),
    user: User = Depends(current_user),
) -> ItemsResponse:
    return ItemsResponse(items=store.list_user_memory_items(user.id, layer, project_id, memory_date, memory_type))


@router.get("/overview", response_model=MemoryOverviewResponse)
def memory_overview(
    project_id: str | None = Query(default=None, min_length=1, max_length=120),
    memory_date: dt_date | None = Query(default=None),
    memory_type: str | None = Query(default=None, min_length=1, max_length=80),
    user: User = Depends(current_user),
) -> MemoryOverviewResponse:
    resolved_project_id = _resolve_user_project_id(user, project_id)
    sections = {
        "short": store.list_user_memory_items(
            user.id,
            MemoryLayer.SHORT_TERM,
            resolved_project_id,
            memory_date,
            memory_type,
        ),
        "project": store.list_user_memory_items(
            user.id,
            MemoryLayer.MID_TERM,
            resolved_project_id,
            None,
            memory_type,
        ),
        "archive": store.list_user_memory_items(
            user.id,
            MemoryLayer.LONG_TERM,
            resolved_project_id,
            None,
            memory_type,
        ),
        "team": [
            memory_item_view(item, user)
            for item in _visible_team_memory_items(user, resolved_project_id, memory_type)
        ],
    }
    return MemoryOverviewResponse(
        project_id=resolved_project_id,
        sections=sections,
        counts={key: len(items) for key, items in sections.items()},
        daily_summary_worker=daily_summary_worker_state,
    )


@router.post("/user", response_model=ItemResponse)
def create_user_memory_item(request: UserMemoryCreateRequest, user: User = Depends(current_user)) -> ItemResponse:
    project_id = _resolve_user_project_id(user, request.project_id)
    item = UserMemoryItem(
        user_id=user.id,
        layer=request.layer,
        title=request.title,
        summary=request.summary,
        source_kind=request.source_kind,
        memory_type=request.memory_type,
        memory_date=request.memory_date or now_utc().date(),
        workspace_id=user.workspace_id,
        project_id=project_id,
    )
    return ItemResponse(item=store.add_user_memory_item(item))


@router.post("/user/daily-summary", response_model=ItemResponse)
def create_daily_memory_summary(
    request: DailyMemorySummaryRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    project_id = _resolve_user_project_id(user, request.project_id)
    target_date = request.date or now_utc().date()
    if _daily_summary_exists(user.id, project_id, target_date):
        raise HTTPException(status_code=409, detail="Daily summary already exists for the requested date")
    item = create_daily_summary_for_user(user, project_id, target_date)
    return ItemResponse(item=item)


@router.post("/user/group-summary", response_model=ItemResponse)
def create_group_memory_summary(
    request: GroupMemorySummaryRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    project_id = _resolve_user_project_id(user, request.project_id)
    memory_date = request.memory_date or now_utc().date()
    item = UserMemoryItem(
        user_id=user.id,
        layer=MemoryLayer.SHORT_TERM,
        title=request.title or f"{memory_date.isoformat()} 群聊总结",
        summary=request.summary,
        source_kind="group_chat_summary",
        memory_type=request.memory_type,
        memory_date=memory_date,
        workspace_id=user.workspace_id,
        project_id=project_id,
        source_thread_id=request.source_thread_id,
    )
    return ItemResponse(item=store.add_user_memory_item(item))


@router.post("/user/project-summary", response_model=ItemResponse)
def create_project_memory_summary(
    request: ProjectMemorySummaryRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    project_id = _resolve_user_project_id(user, request.project_id)
    source_items = [
        item
        for item in store.list_user_memory_items(user.id, MemoryLayer.SHORT_TERM, project_id)
        if item.source_kind != "short_term_rollup"
    ]
    _ensure_source_items(source_items, "No short-term project memory found")

    item = UserMemoryItem(
        user_id=user.id,
        layer=MemoryLayer.MID_TERM,
        title=f"{_project_name(project_id)} 项目中期记忆摘要",
        summary=_summarize_project_memory(user, project_id, source_items),
        source_kind="short_term_rollup",
        memory_type="project_summary",
        workspace_id=user.workspace_id,
        project_id=project_id,
    )
    return ItemResponse(item=store.add_user_memory_item(item))


@router.post("/user/archive-project", response_model=ItemResponse)
def archive_project_memory(
    request: ProjectArchiveRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    project_id = _resolve_user_project_id(user, request.project_id)
    source_items = [
        item
        for item in store.list_user_memory_items(user.id, MemoryLayer.MID_TERM, project_id)
        if item.source_kind != "project_archive"
    ]
    _ensure_source_items(source_items, "No mid-term project memory found")

    item = UserMemoryItem(
        user_id=user.id,
        layer=MemoryLayer.LONG_TERM,
        title=f"{_project_name(project_id)} 项目长期归档",
        summary=_summarize_archive_memory(user, project_id, source_items),
        source_kind="project_archive",
        memory_type="project_archive",
        workspace_id=user.workspace_id,
        project_id=project_id,
    )
    return ItemResponse(item=store.add_user_memory_item(item))


@router.post("/user/{item_id}/share-to-project", response_model=ItemResponse)
def share_user_memory_to_project(item_id: str, user: User = Depends(current_user)) -> ItemResponse:
    """Share a personal memory to project scope so all project members can see it."""
    source_item = store.get_user_memory_item(item_id)
    if source_item is None or source_item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Memory not found")

    if source_item.project_id is None:
        raise HTTPException(status_code=400, detail="Memory has no associated project")

    project = store.get_project(source_item.project_id)
    if (
        project is None
        or project.workspace_id != user.workspace_id
        or not store.user_can_access_project(user.id, source_item.project_id)
    ):
        raise HTTPException(status_code=404, detail="Project not found")

    shared = MemoryItem(
        title=source_item.title,
        summary=source_item.summary,
        memory_type=source_item.memory_type,
        scope=Scope.TEAM_CANDIDATE,
        status=MemoryStatus.PROPOSED,
        owner_user_id=user.id,
        workspace_id=user.workspace_id,
        project_id=source_item.project_id,
        sources=source_item.sources,
    )
    store.add_memory_item(shared)

    store.add_memory_relation(
        MemoryRelation(
            from_memory_id=shared.id,
            to_source_id=source_item.id,
            relation_type="shared_from_personal",
        )
    )
    return ItemResponse(item=shared)


@router.patch("/{item_id}", response_model=ItemResponse)
def update_memory_item(
    item_id: str,
    request: MemoryUpdateRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    item = store.get_memory_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Memory item not found")
    ensure_can_update_memory(user, item, request.status, request.scope, store.permission_policy_rules)
    if request.status == MemoryStatus.ACCEPTED or request.scope == Scope.TEAM_ACCEPTED:
        item.status = MemoryStatus.ACCEPTED
        item.scope = Scope.TEAM_ACCEPTED
    elif request.status is not None:
        item.status = request.status
    store.save_memory_item(item)
    return ItemResponse(item=item)


def _resolve_user_project_id(user: User, requested_project_id: str | None) -> str:
    project_id = requested_project_id or user.default_project_id
    project = store.get_project(project_id)
    if (
        project is None
        or project.workspace_id != user.workspace_id
        or not store.user_can_access_project(user.id, project_id)
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    return project_id


def create_daily_summary_for_user(user: User, project_id: str, target_date: dt_date) -> UserMemoryItem:
    source_items = _daily_summary_source_items(user.id, project_id, target_date)
    _ensure_source_items(source_items, "No short-term memory found for the requested date")
    item = UserMemoryItem(
        user_id=user.id,
        layer=MemoryLayer.SHORT_TERM,
        title=f"{target_date.isoformat()} 每日短期记忆摘要",
        summary=_summarize_memory_items("当天关键记忆", source_items),
        source_kind="daily_summary",
        memory_type="daily_summary",
        memory_date=target_date,
        workspace_id=user.workspace_id,
        project_id=project_id,
    )
    return store.add_user_memory_item(item)


def generate_daily_memory_summaries(target_date: dt_date | None = None) -> dict[str, object]:
    date_value = target_date or now_utc().date()
    created: list[UserMemoryItem] = []
    skipped_existing = 0
    skipped_empty = 0
    for user in store.users:
        if user.status != "active":
            continue
        project_id = user.default_project_id
        if store.get_project(project_id) is None:
            skipped_empty += 1
            continue
        if _daily_summary_exists(user.id, project_id, date_value):
            skipped_existing += 1
            continue
        if not _daily_summary_source_items(user.id, project_id, date_value):
            skipped_empty += 1
            continue
        created.append(create_daily_summary_for_user(user, project_id, date_value))
    return {
        "date": date_value.isoformat(),
        "created": len(created),
        "skipped_existing": skipped_existing,
        "skipped_empty": skipped_empty,
        "items": created,
    }


async def daily_memory_worker_loop() -> None:
    while True:
        await asyncio.sleep(DAILY_SUMMARY_WORKER_INTERVAL_SECONDS)
        daily_summary_worker_state["last_run_at"] = now_utc().isoformat()
        try:
            result = await asyncio.to_thread(generate_daily_memory_summaries)
            daily_summary_worker_state["last_created"] = result["created"]
            daily_summary_worker_state["last_skipped_existing"] = result["skipped_existing"]
            daily_summary_worker_state["last_skipped_empty"] = result["skipped_empty"]
            daily_summary_worker_state["last_error"] = None
        except Exception as error:  # pragma: no cover - defensive worker boundary
            daily_summary_worker_state["last_error"] = str(error)


async def start_daily_memory_worker() -> None:
    global daily_summary_worker_task
    if DAILY_SUMMARY_WORKER_ENABLED and (
        daily_summary_worker_task is None or daily_summary_worker_task.done()
    ):
        daily_summary_worker_task = asyncio.create_task(daily_memory_worker_loop())
        daily_summary_worker_state["running"] = True


async def stop_daily_memory_worker() -> None:
    global daily_summary_worker_task
    if daily_summary_worker_task is not None:
        daily_summary_worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await daily_summary_worker_task
        daily_summary_worker_task = None
    daily_summary_worker_state["running"] = False


@router.get("/user/daily-summary/worker")
def daily_memory_worker_status(_: User = Depends(current_user)) -> dict[str, object]:
    return daily_summary_worker_state


@router.post("/user/daily-summary/run")
def run_daily_memory_summary(_: User = Depends(current_user)) -> dict[str, object]:
    result = generate_daily_memory_summaries()
    daily_summary_worker_state["last_run_at"] = now_utc().isoformat()
    daily_summary_worker_state["last_created"] = result["created"]
    daily_summary_worker_state["last_skipped_existing"] = result["skipped_existing"]
    daily_summary_worker_state["last_skipped_empty"] = result["skipped_empty"]
    daily_summary_worker_state["last_error"] = None
    return result


def _daily_summary_source_items(user_id: str, project_id: str, target_date: dt_date) -> list[UserMemoryItem]:
    return [
        item
        for item in store.list_user_memory_items(user_id, MemoryLayer.SHORT_TERM, project_id, target_date)
        if item.source_kind != "daily_summary"
    ]


def _daily_summary_exists(user_id: str, project_id: str, target_date: dt_date) -> bool:
    return any(
        item.source_kind == "daily_summary"
        for item in store.list_user_memory_items(
            user_id,
            MemoryLayer.SHORT_TERM,
            project_id,
            target_date,
            "daily_summary",
        )
    )


def _project_name(project_id: str) -> str:
    project = store.get_project(project_id)
    return project.name if project is not None else project_id


def memory_item_view(item: MemoryItem, user: User) -> MemoryItemView:
    actions = []
    if (
        item.status == MemoryStatus.PROPOSED
        and item.scope == Scope.TEAM_CANDIDATE
        and has_permission(user, ACTION_ACCEPT_TEAM_MEMORY, store.permission_policy_rules)
    ):
        actions.append("accept")
    return MemoryItemView(**item.model_dump(), allowed_actions=actions)


def _visible_memory_items(user: User, project_id: str) -> list[MemoryItem]:
    items: list[MemoryItem] = []
    for item in store.memory_items:
        if item.project_id != project_id:
            continue
        if item.scope == Scope.PRIVATE and item.owner_user_id != user.id:
            continue
        if item.scope == Scope.TEAM_CANDIDATE and user.role not in {UserRole.TEAM_LEAD, UserRole.ADMIN}:
            continue
        if item.workspace_id is not None and item.workspace_id != user.workspace_id and user.role != UserRole.ADMIN:
            continue
        items.append(item)
    return items


def _visible_team_memory_items(user: User, project_id: str, memory_type: str | None = None) -> list[MemoryItem]:
    items = [
        item
        for item in _visible_memory_items(user, project_id)
        if item.scope in {Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED}
    ]
    if memory_type is not None:
        items = [item for item in items if item.memory_type == memory_type]
    return sorted(items, key=lambda item: item.created_at, reverse=True)


def _ensure_source_items(items: list[UserMemoryItem], detail: str) -> None:
    if not items:
        raise HTTPException(status_code=400, detail=detail)


def _summarize_memory_items(heading: str, items: list[UserMemoryItem]) -> str:
    ordered = sorted(items, key=lambda item: item.created_at)
    lines = [f"{heading}：共 {len(ordered)} 条。"]
    for item in ordered[:8]:
        lines.append(f"- {item.title}：{item.summary}")
    if len(ordered) > 8:
        lines.append(f"- 另有 {len(ordered) - 8} 条记忆未展开。")
    return "\n".join(lines)[:2000]


def _summarize_project_memory(user: User, project_id: str, items: list[UserMemoryItem]) -> str:
    fallback = _summarize_memory_items("项目阶段沉淀", items)
    client = LLMClient.from_model_id(resolve_agent_model_id(store, user))
    if client is None:
        return fallback
    try:
        summary = client.complete(
            system_prompt=(
                "你是 AgentMesh 的项目记忆整理助手。"
                "只基于给定短期记忆提炼项目中期记忆，不编造事实。"
                "输出中文，结构包括：项目背景、关键数据/证据、竞品/外部信息、风险、决策与待跟进。"
                "保持简洁，适合作为后续项目 Brief 和知识召回依据。"
            ),
            user_prompt=_project_memory_prompt(project_id, items),
        ).strip()
    except Exception:
        return fallback
    return summary[:2000] if summary else fallback


def _summarize_archive_memory(user: User, project_id: str, items: list[UserMemoryItem]) -> str:
    fallback = _archive_fallback_summary(project_id, items)
    client = LLMClient.from_model_id(resolve_agent_model_id(store, user))
    if client is None:
        return fallback
    try:
        summary = client.complete(
            system_prompt=(
                "你是 AgentMesh 的项目归档助手。"
                "只基于给定项目中期记忆生成长期归档，不编造事实。"
                "输出中文，必须包含两段：项目总结、召回索引。"
                "召回索引用关键词短语表示，方便未来搜索相似项目、风险、数据口径和设计决策。"
            ),
            user_prompt=_archive_memory_prompt(project_id, items),
        ).strip()
    except Exception:
        return fallback
    return _ensure_archive_index(summary, project_id, items)[:2000] if summary else fallback


def _archive_fallback_summary(project_id: str, items: list[UserMemoryItem]) -> str:
    summary = _summarize_memory_items("项目归档摘要", items)
    return _ensure_archive_index(summary, project_id, items)


def _ensure_archive_index(summary: str, project_id: str, items: list[UserMemoryItem]) -> str:
    if "召回索引" in summary:
        return summary
    keywords = _archive_keywords(project_id, items)
    return f"{summary}\n召回索引：{keywords}"


def _archive_keywords(project_id: str, items: list[UserMemoryItem]) -> str:
    tokens = [_project_name(project_id)]
    for item in sorted(items, key=lambda value: value.created_at):
        tokens.extend([item.title, item.memory_type])
        for word in item.summary.replace("，", " ").replace("。", " ").replace("；", " ").split():
            if 2 <= len(word) <= 24:
                tokens.append(word)
    seen: set[str] = set()
    unique = []
    for token in tokens:
        value = token.strip(" ：:、,.-")
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
        if len(unique) >= 16:
            break
    return "、".join(unique)


def _archive_memory_prompt(project_id: str, items: list[UserMemoryItem]) -> str:
    ordered = sorted(items, key=lambda item: item.created_at)
    lines = [f"项目：{_project_name(project_id)}", "项目中期记忆："]
    for item in ordered[:20]:
        lines.append(f"- 标题：{item.title}；类型：{item.memory_type}；内容：{item.summary}")
    if len(ordered) > 20:
        lines.append(f"- 另有 {len(ordered) - 20} 条中期记忆未展开。")
    return "\n".join(lines)[:6000]


def _project_memory_prompt(project_id: str, items: list[UserMemoryItem]) -> str:
    ordered = sorted(items, key=lambda item: item.created_at)
    lines = [f"项目：{_project_name(project_id)}", "短期记忆来源："]
    for item in ordered[:20]:
        lines.append(
            f"- 日期：{item.memory_date.isoformat()}；类型：{item.memory_type}；标题：{item.title}；内容：{item.summary}"
        )
    if len(ordered) > 20:
        lines.append(f"- 另有 {len(ordered) - 20} 条短期记忆未展开。")
    return "\n".join(lines)[:6000]


@router.get("/retrieval-metrics")
def retrieval_metrics_list(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Return recent retrieval metrics for recall quality analysis."""
    all_metrics = sorted(store.retrieval_metrics, key=lambda m: m.created_at, reverse=True)
    items = all_metrics[:limit]
    if not items:
        return {"items": [], "summary": {"total": 0, "avg_citation_rate": 0.0, "avg_latency_ms": 0}}
    total = len(items)
    total_returned = sum(m.results_returned for m in items)
    total_cited = sum(m.results_cited for m in items)
    avg_citation_rate = total_cited / total_returned if total_returned > 0 else 0.0
    avg_latency_ms = sum(m.latency_ms for m in items) / total
    return {
        "items": [m.model_dump() for m in items],
        "summary": {
            "total": total,
            "avg_citation_rate": round(avg_citation_rate, 3),
            "avg_latency_ms": round(avg_latency_ms, 1),
            "total_returned": total_returned,
            "total_cited": total_cited,
        },
    }


@router.get("/skills")
def list_learned_skills(user: User = Depends(current_user)) -> dict[str, object]:
    """List learned skills for the current user."""
    skills = [
        s for s in store.learned_skills
        if s.user_id == user.id or s.scope in (Scope.PROJECT, Scope.TEAM_ACCEPTED)
    ]
    return {"items": [s.model_dump() for s in sorted(skills, key=lambda s: s.created_at, reverse=True)]}


@router.post("/skills/{skill_id}/activate")
def activate_skill(skill_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    """Activate a draft skill (user confirms it's useful)."""
    skill = store.get_learned_skill(skill_id)
    if skill is None or skill.user_id != user.id:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.status != SkillStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft skills can be activated")
    skill.status = SkillStatus.ACTIVE
    skill.updated_at = now_utc()
    store.save_learned_skill(skill)
    definition = materialize_learned_skill(store, skill)
    catalog_service().reload()
    return {"item": skill.model_dump(), "skill_definition": definition.model_dump()}


@router.post("/skills/{skill_id}/share")
def share_skill_to_project(skill_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    """Share a personal skill to project scope."""
    skill = store.get_learned_skill(skill_id)
    if skill is None or skill.user_id != user.id:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.status != SkillStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Only active skills can be shared")
    skill.scope = Scope.PROJECT
    skill.updated_at = now_utc()
    store.save_learned_skill(skill)
    return {"item": skill.model_dump()}


@router.post("/skills/{skill_id}/deprecate")
def deprecate_skill(skill_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    """Mark a skill as deprecated."""
    skill = store.get_learned_skill(skill_id)
    if skill is None or skill.user_id != user.id:
        raise HTTPException(status_code=404, detail="Skill not found")
    skill.status = SkillStatus.DEPRECATED
    skill.updated_at = now_utc()
    store.save_learned_skill(skill)
    return {"item": skill.model_dump()}
