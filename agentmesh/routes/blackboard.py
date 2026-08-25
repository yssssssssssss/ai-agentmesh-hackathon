"""Blackboard routes."""

from __future__ import annotations

import asyncio
import contextlib
import os

from fastapi import APIRouter, Depends, HTTPException, Query

from agentmesh.models import (
    Agent,
    AutoBlackboardPostCreateRequest,
    AutoBlackboardPostRequest,
    BlackboardHandoffRequest,
    BlackboardPost,
    BlackboardPostCreateRequest,
    BlackboardPostsResponse,
    BlackboardPostView,
    BlackboardTaskCard,
    BlackboardTaskCardsResponse,
    BlackboardTaskDetail,
    CollaborationStage,
    DrainAutoPostsResponse,
    ExecutionLock,
    ExecutionLockAcquireRequest,
    ExecutionLockReleaseRequest,
    ItemResponse,
    ItemsResponse,
    MemoryItem,
    Scope,
    Source,
    StructuredHandoffPacket,
    Task,
    User,
    UserRole,
    now_utc,
)
from agentmesh.permissions import (
    authorize_blackboard_action,
    can_control_blackboard_task,
    ensure_admin,
    ensure_can_manage_agent,
    ensure_can_release_execution_lock,
)
from agentmesh.routes.agents import agent_display_name
from agentmesh.routes.deps import create_audit_event, current_user
from agentmesh.seed import AGENTS
from agentmesh.store import store

router = APIRouter(prefix="/api/blackboard", tags=["blackboard"])


def positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


AUTO_POST_WORKER_ENABLED = os.getenv("AGENTMESH_AUTO_POST_WORKER_ENABLED", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
AUTO_POST_WORKER_INTERVAL_SECONDS = positive_int_env("AGENTMESH_AUTO_POST_WORKER_INTERVAL_SECONDS", 30)
auto_post_worker_task: asyncio.Task | None = None
auto_post_worker_state: dict[str, object] = {
    "enabled": AUTO_POST_WORKER_ENABLED,
    "interval_seconds": AUTO_POST_WORKER_INTERVAL_SECONDS,
    "running": False,
    "last_run_at": None,
    "last_posted": 0,
    "last_error": None,
}


def drain_queued_auto_blackboard_posts(actor: str) -> dict[str, object]:
    drained: list[AutoBlackboardPostRequest] = []
    for request in store.auto_blackboard_post_requests:
        if request.status != "reviewed":
            continue
        post = store.add_blackboard_post(
            BlackboardPost(
                task_id=request.task_id,
                post_type=request.post_type,
                actor=request.actor,
                title=request.title,
                content=request.content,
                scope=request.scope,
                permission=request.permission,
                related_post_id=request.related_post_id,
            )
        )
        updated = request.model_copy(
            update={"status": "published", "published_at": now_utc(), "blackboard_post_id": post.id}
        )
        store.save_auto_blackboard_post_request(updated)
        drained.append(updated)

    if drained:
        store.add_audit_event(
            create_audit_event(
                actor,
                "drain_auto_blackboard_posts",
                "blackboard_auto_post_queue",
                "auto_posts",
                {"posted": len(drained)},
            )
        )
    return DrainAutoPostsResponse(posted=len(drained), items=drained)


async def auto_post_worker_loop() -> None:
    while True:
        await asyncio.sleep(AUTO_POST_WORKER_INTERVAL_SECONDS)
        auto_post_worker_state["last_run_at"] = now_utc().isoformat()
        try:
            result = await asyncio.to_thread(drain_queued_auto_blackboard_posts, "auto_post_worker")
            auto_post_worker_state["last_posted"] = result["posted"]
            auto_post_worker_state["last_error"] = None
        except Exception as error:  # pragma: no cover - defensive worker boundary
            auto_post_worker_state["last_error"] = str(error)


async def start_auto_post_worker() -> None:
    global auto_post_worker_task
    if AUTO_POST_WORKER_ENABLED and (auto_post_worker_task is None or auto_post_worker_task.done()):
        auto_post_worker_task = asyncio.create_task(auto_post_worker_loop())
        auto_post_worker_state["running"] = True


async def stop_auto_post_worker() -> None:
    global auto_post_worker_task
    if auto_post_worker_task is not None:
        auto_post_worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await auto_post_worker_task
        auto_post_worker_task = None
    auto_post_worker_state["running"] = False


# --- Research Dispatch Worker ---

RESEARCH_DISPATCH_WORKER_ENABLED = os.getenv("AGENTMESH_RESEARCH_DISPATCH_WORKER_ENABLED", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
RESEARCH_DISPATCH_WORKER_INTERVAL_SECONDS = positive_int_env(
    "AGENTMESH_RESEARCH_DISPATCH_WORKER_INTERVAL_SECONDS", 30
)
research_dispatch_worker_task: asyncio.Task | None = None
research_dispatch_worker_state: dict[str, object] = {
    "enabled": RESEARCH_DISPATCH_WORKER_ENABLED,
    "interval_seconds": RESEARCH_DISPATCH_WORKER_INTERVAL_SECONDS,
    "running": False,
    "last_run_at": None,
    "last_dispatched": 0,
    "last_error": None,
}


def drain_dispatchable_research_requests(actor: str) -> dict[str, object]:
    from agentmesh.agents import RequestAlreadyFulfilledError
    from agentmesh.routes.chat import agent

    dispatched = 0
    for post in list(store.blackboard_posts):
        if post.post_type != "request":
            continue
        task = store.get_task(post.task_id)
        if task is None or task.status != "waiting_external_agent":
            continue
        if "requested_tool_call_approval" in task.steps:
            continue
        thread = store.get_chat_thread(task.thread_id)
        if thread is None:
            continue
        user = store.get_user(thread.user_id)
        if user is None:
            continue
        try:
            agent.fulfill_research_request(post, user)
            dispatched += 1
        except RequestAlreadyFulfilledError:
            continue
        except Exception:
            continue

    if dispatched:
        store.add_audit_event(
            create_audit_event(
                actor,
                "drain_research_dispatch",
                "blackboard_research_dispatch",
                "research_requests",
                {"dispatched": dispatched},
            )
        )
    return {"dispatched": dispatched}


async def research_dispatch_worker_loop() -> None:
    while True:
        await asyncio.sleep(RESEARCH_DISPATCH_WORKER_INTERVAL_SECONDS)
        research_dispatch_worker_state["last_run_at"] = now_utc().isoformat()
        try:
            result = await asyncio.to_thread(drain_dispatchable_research_requests, "research_dispatch_worker")
            research_dispatch_worker_state["last_dispatched"] = result["dispatched"]
            research_dispatch_worker_state["last_error"] = None
        except Exception as error:  # pragma: no cover
            research_dispatch_worker_state["last_error"] = str(error)


async def start_research_dispatch_worker() -> None:
    global research_dispatch_worker_task
    if RESEARCH_DISPATCH_WORKER_ENABLED and (
        research_dispatch_worker_task is None or research_dispatch_worker_task.done()
    ):
        research_dispatch_worker_task = asyncio.create_task(research_dispatch_worker_loop())
        research_dispatch_worker_state["running"] = True


async def stop_research_dispatch_worker() -> None:
    global research_dispatch_worker_task
    if research_dispatch_worker_task is not None:
        research_dispatch_worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await research_dispatch_worker_task
        research_dispatch_worker_task = None
    research_dispatch_worker_state["running"] = False


def handoff_summary(packet: StructuredHandoffPacket, next_owner_label: str) -> str:
    blockers = f" 阻塞点：{'；'.join(packet.blockers)}。" if packet.blockers else ""
    requires = f" 需要协作：{'、'.join(packet.requires_input_from)}。" if packet.requires_input_from else ""
    goal = packet.goal
    return (
        f"@{next_owner_label} 接棒：目标是\u201c{goal}\u201d。"
        f"当前结果：{packet.current_result}。"
        f"完成条件：{packet.done_when}。{blockers}{requires}"
    )


@router.get("", response_model=BlackboardPostsResponse)
def blackboard_posts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    task_id: str | None = Query(default=None, min_length=1, max_length=120),
    user: User = Depends(current_user),
) -> BlackboardPostsResponse:
    posts = list(reversed(store.blackboard_posts))
    if task_id is not None:
        posts = [post for post in posts if post.task_id == task_id]
    posts_by_task: dict[str, list[BlackboardPost]] = {}
    for post in store.blackboard_posts:
        posts_by_task.setdefault(post.task_id, []).append(post)
    posts = [post for post in posts if post_visible_to_user(post, posts_by_task.get(post.task_id, []), user)]
    start = (page - 1) * page_size
    end = start + page_size
    return BlackboardPostsResponse(
        items=[blackboard_post_view(post, user) for post in posts[start:end]],
        total=len(posts),
        page=page,
        page_size=page_size,
        has_next=end < len(posts),
    )


@router.get("/task-cards", response_model=BlackboardTaskCardsResponse)
def blackboard_task_cards(
    project_id: str = Query(min_length=1, max_length=120),
    user: User = Depends(current_user),
) -> BlackboardTaskCardsResponse:
    project = store.get_project(project_id)
    if (
        project is None
        or project.workspace_id != user.workspace_id
        or not store.user_can_access_project(user.id, project_id)
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    posts_by_task: dict[str, list[BlackboardPost]] = {}
    for post in store.blackboard_posts:
        posts_by_task.setdefault(post.task_id, []).append(post)
    cards = [
        card
        for task in reversed(store.tasks)
        if (thread := store.get_chat_thread(task.thread_id)) is not None
        and thread.project_id == project_id
        and thread.workspace_id == user.workspace_id
        and (card := build_task_card(task, posts_by_task.get(task.id, []), user)) is not None
    ]
    return BlackboardTaskCardsResponse(items=cards)


@router.get("/tasks/{task_id}", response_model=BlackboardTaskDetail)
def blackboard_task_detail(task_id: str, user: User = Depends(current_user)) -> BlackboardTaskDetail:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    posts = [post for post in store.blackboard_posts if post.task_id == task.id]
    card = build_task_card(task, posts, user)
    if card is None:
        raise HTTPException(status_code=404, detail="Task not found")
    visible_posts = task_posts_visible_to_user(task, posts, user)
    return BlackboardTaskDetail(
        task_card=card,
        posts=[blackboard_post_view(post, user) for post in visible_posts],
    )


def build_task_card(task, task_posts: list[BlackboardPost], user: User) -> BlackboardTaskCard | None:
    if not task_visible_to_user(task.thread_id, task_posts, user):
        return None
    visible_posts = task_posts_visible_to_user(task, task_posts, user)
    visible_post_ids = {post.id for post in visible_posts}
    latest_post = visible_posts[-1] if visible_posts else None
    locked_post = next(
        (post for post in reversed(task_posts) if post.execution_lock and post.execution_lock.active),
        None,
    )
    active_lock = locked_post.execution_lock if locked_post and locked_post.execution_lock else None
    state_post = locked_post or (task_posts[-1] if task_posts else None)
    state_post_visible = state_post is not None and state_post.id in visible_post_ids
    thread = store.get_chat_thread(task.thread_id)
    return BlackboardTaskCard(
        task=task,
        latest_post=blackboard_post_view(latest_post, user) if latest_post else None,
        stage=state_post.collaboration_stage if state_post_visible else task.collaboration_stage,
        owner=(
            state_post.current_owner_label
            if state_post_visible and state_post.current_owner_label
            else task.current_owner_label
        ),
        done_when=state_post.done_when if state_post_visible and state_post.done_when else task.done_when,
        active_lock=active_lock,
        post_count=len(visible_posts),
        initiator_user_id=thread.user_id if thread else None,
        initiated_by_current_user=thread is not None and thread.user_id == user.id,
        claimed_by_personal_agent=task_claimed_by_personal_agent(task, visible_posts, user),
        upstream_agents=task_upstream_agents(visible_posts),
        downstream_agents=task_downstream_agents(task, visible_posts, active_lock),
        target_post_id=state_post.id if state_post_visible else None,
        allowed_actions=blackboard_allowed_actions(state_post, user) if state_post_visible else [],
    )


def task_claimed_by_personal_agent(task, posts: list[BlackboardPost], user: User) -> bool:
    personal_agent = store.get_agent(user.personal_agent_id)
    personal_agent_ids = {user.personal_agent_id, "personal_agent"}
    if personal_agent is not None:
        personal_agent_ids.add(personal_agent.name)
    values = {task.current_owner_agent_id or "", task.current_owner_label or ""}
    if task.execution_lock:
        values.add(task.execution_lock.owner_agent_id)
        values.add(task.execution_lock.owner_label)
    for post in posts:
        values.update(
            {
                post.current_owner_agent_id or "",
                post.current_owner_label or "",
            }
        )
        if post.execution_lock:
            values.add(post.execution_lock.owner_agent_id)
            values.add(post.execution_lock.owner_label)
    return bool(values & personal_agent_ids)


def task_upstream_agents(posts: list[BlackboardPost]) -> list[str]:
    return unique_non_empty(post.actor for post in posts if post.actor)


def task_downstream_agents(
    task,
    posts: list[BlackboardPost],
    active_lock: ExecutionLock | None,
) -> list[str]:
    values = []
    if active_lock is not None:
        values.append(active_lock.owner_label or active_lock.owner_agent_id)
    values.extend(post.handoff.next_owner_agent_id for post in posts if post.handoff)
    values.extend(post.current_owner_label or post.current_owner_agent_id or "" for post in posts)
    values.append(task.current_owner_label or task.current_owner_agent_id or "")
    return unique_non_empty(values)


def unique_non_empty(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if not value or value in result:
            continue
        result.append(value)
    return result


def task_visible_to_user(thread_id: str, posts: list[BlackboardPost], user: User) -> bool:
    thread = store.get_chat_thread(thread_id)
    if thread is not None:
        if thread.workspace_id != user.workspace_id or not store.user_can_access_project(user.id, thread.project_id):
            return False
        if user.role in {UserRole.TEAM_LEAD, UserRole.ADMIN}:
            return True
        if thread.user_id == user.id:
            return True
        personal_agent_ids = {user.personal_agent_id}
    else:
        if user.role in {UserRole.TEAM_LEAD, UserRole.ADMIN}:
            return True
        personal_agent_ids = {"personal_agent", user.personal_agent_id}
    for post in posts:
        values = {
            post.actor,
            post.current_owner_agent_id or "",
            post.current_owner_label or "",
            *(post.read_by_agents or []),
        }
        if post.execution_lock:
            values.add(post.execution_lock.owner_agent_id)
            values.add(post.execution_lock.owner_label)
        if values & personal_agent_ids:
            return True
    return False


def task_posts_visible_to_user(task: Task, posts: list[BlackboardPost], user: User) -> list[BlackboardPost]:
    thread = store.get_chat_thread(task.thread_id)
    initiator_user_id = thread.user_id if thread is not None else None
    return [post for post in posts if task_post_visible_to_user(post, initiator_user_id, user)]


def task_post_visible_to_user(post: BlackboardPost, initiator_user_id: str | None, user: User) -> bool:
    if user.role in {UserRole.TEAM_LEAD, UserRole.ADMIN} or post.scope != Scope.PRIVATE:
        return True
    if post.actor in {user.id, user.personal_agent_id}:
        return True
    return post.actor == "personal_agent" and initiator_user_id == user.id


def post_visible_to_user(post: BlackboardPost, task_posts: list[BlackboardPost], user: User) -> bool:
    task = store.get_task(post.task_id)
    if task is not None:
        if not task_visible_to_user(task.thread_id, task_posts, user):
            return False
        thread = store.get_chat_thread(task.thread_id)
        initiator_user_id = thread.user_id if thread is not None else None
        return task_post_visible_to_user(post, initiator_user_id, user)
    if user.role in {UserRole.TEAM_LEAD, UserRole.ADMIN}:
        return True
    if post.scope == Scope.PRIVATE:
        return post.actor in {user.id, user.personal_agent_id} or (
            post.actor == "personal_agent" and post.task_id == f"manual_{user.id}"
        )
    if post.scope == Scope.PROJECT:
        return True
    return (
        post.task_id == f"manual_{user.id}"
        or post.actor in {user.id, user.personal_agent_id, "personal_agent"}
        or user.personal_agent_id in post.read_by_agents
        or "personal_agent" in post.read_by_agents
    )


def task_initiator_user_id(post: BlackboardPost) -> str | None:
    task = store.get_task(post.task_id)
    if task is not None:
        thread = store.get_chat_thread(task.thread_id)
        return thread.user_id if thread is not None else None
    if post.task_id.startswith("manual_"):
        return post.task_id.removeprefix("manual_")
    return None


def blackboard_post_context(post: BlackboardPost) -> tuple[str, str] | None:
    task = store.get_task(post.task_id)
    if task is not None:
        thread = store.get_chat_thread(task.thread_id)
        if thread is not None:
            return thread.workspace_id, thread.project_id
    initiator_id = task_initiator_user_id(post)
    initiator = store.get_user(initiator_id) if initiator_id is not None else None
    if initiator is None:
        return None
    return initiator.workspace_id, initiator.default_project_id


def resolve_handoff_recipient(post: BlackboardPost, agent_id: str) -> Agent:
    context = blackboard_post_context(post)
    if context is None:
        raise HTTPException(status_code=409, detail="Task context is unavailable")
    workspace_id, project_id = context
    agent = store.get_agent(agent_id) or next((item for item in AGENTS if item.id == agent_id), None)
    if agent is None or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Eligible handoff Agent not found")
    if agent.status != "online":
        raise HTTPException(status_code=409, detail="Handoff Agent is not eligible")

    owner = store.get_user(agent.owner_user_id) if agent.owner_user_id is not None else None
    if agent.agent_type == "personal" and owner is None:
        raise HTTPException(status_code=409, detail="Handoff Agent is not eligible")
    if owner is not None:
        project = store.get_project(project_id)
        in_project = owner.default_project_id == project_id or (
            project is not None and owner.id in project.member_ids
        )
        if owner.workspace_id != workspace_id or not in_project:
            raise HTTPException(status_code=404, detail="Eligible handoff Agent not found")
        if owner.status != "active":
            raise HTTPException(status_code=409, detail="Handoff Agent is not eligible")
    return agent


def authorize_post_action(post: BlackboardPost, user: User, action: str) -> None:
    task_posts = [item for item in store.blackboard_posts if item.task_id == post.task_id]
    authorize_blackboard_action(
        user,
        post,
        action,
        visible=post_visible_to_user(post, task_posts, user),
        task_initiator_user_id=task_initiator_user_id(post),
    )


def blackboard_allowed_actions(post: BlackboardPost, user: User) -> list[str]:
    task_posts = [item for item in store.blackboard_posts if item.task_id == post.task_id]
    if not post_visible_to_user(post, task_posts, user):
        return []

    actions = []
    if user.personal_agent_id not in post.read_by_agents:
        actions.append("read")
    controls_task = can_control_blackboard_task(user, post, task_initiator_user_id(post))
    if not controls_task:
        return actions

    actions.append("reply")
    lock = post.execution_lock
    can_release = (
        lock is None
        or not lock.active
        or user.role in {UserRole.TEAM_LEAD, UserRole.ADMIN}
        or lock.owner_agent_id == user.personal_agent_id
    )
    if lock is None or not lock.active or lock.owner_agent_id == user.personal_agent_id:
        actions.append("lock")
    if lock is not None and lock.active and can_release:
        actions.append("unlock")
    if can_release:
        actions.append("handoff")
    return actions


def blackboard_post_view(post: BlackboardPost, user: User) -> BlackboardPostView:
    return BlackboardPostView(
        **post.model_dump(),
        allowed_actions=blackboard_allowed_actions(post, user),
    )


@router.post("/posts/{post_id}/memory-candidate")
def create_memory_candidate_from_blackboard_post(
    post_id: str,
    user: User = Depends(current_user),
) -> dict[str, object]:
    post = store.get_blackboard_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Blackboard post not found")
    authorize_post_action(post, user, "create memory from")
    if post.post_type not in {"evidence", "decision", "digest", "archive", "memory_candidate"}:
        raise HTTPException(status_code=400, detail="Blackboard post cannot become a memory candidate")

    source = Source(
        title=post.title,
        source_type="blackboard_post",
        reference=f"blackboard://{post.id}",
    )
    store.add_source(source)
    item = store.add_memory_item(
        MemoryItem(
            title=f"候选团队记忆：{post.title}",
            summary=post.content,
            memory_type="bbs_evidence" if post.post_type == "evidence" else "bbs_decision",
            scope=Scope.TEAM_CANDIDATE,
            owner_user_id=user.id,
            workspace_id=user.workspace_id,
            project_id=user.default_project_id,
            sources=[source, *post.sources],
            metadata={"blackboard_post_id": post.id, "task_id": post.task_id, "post_type": post.post_type},
        )
    )
    store.add_audit_event(
        create_audit_event(
            user.id,
            "create_memory_candidate_from_blackboard",
            "blackboard_post",
            post.id,
            {"memory_id": item.id},
        )
    )
    return {"item": item, "post": post}


@router.post("/posts/{post_id}/dispatch")
def dispatch_blackboard_request(
    post_id: str,
    user: User = Depends(current_user),
) -> dict[str, object]:
    from agentmesh.agents import RequestAlreadyFulfilledError
    from agentmesh.routes.chat import agent

    post = store.get_blackboard_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Blackboard post not found")
    authorize_post_action(post, user, "dispatch")
    if post.post_type != "request":
        raise HTTPException(status_code=400, detail="Only request posts can be dispatched")

    task = store.get_task(post.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Request post has no backing task")
    if task.status != "waiting_external_agent":
        raise HTTPException(status_code=409, detail="Request is not awaiting an external agent")
    if "requested_tool_call_approval" in task.steps:
        raise HTTPException(status_code=409, detail="Request is gated behind a pending tool approval")

    try:
        fulfillment = agent.fulfill_research_request(post, user)
    except RequestAlreadyFulfilledError as error:
        raise HTTPException(status_code=409, detail="Request has already been fulfilled") from error

    store.add_audit_event(
        create_audit_event(
            user.id,
            "dispatch_blackboard_request",
            "blackboard_post",
            post.id,
            {
                "task_id": task.id,
                "evidence_post_id": fulfillment.evidence_post.id,
                "quarantined": fulfillment.quarantined,
            },
        )
    )
    return {
        "request_post": fulfillment.request_post,
        "evidence_post": fulfillment.evidence_post,
        "task": fulfillment.task,
        "assistant_message": fulfillment.assistant_message,
        "activity_logs": fulfillment.activity_logs,
        "inbox_items": fulfillment.inbox_items,
        "quarantined": fulfillment.quarantined,
    }


@router.get("/auto-posts", response_model=ItemsResponse)
def auto_blackboard_posts(user: User = Depends(current_user)) -> ItemsResponse:
    ensure_admin(user)
    return ItemsResponse(items=list(reversed(store.auto_blackboard_post_requests)))


@router.get("/auto-posts/worker")
def auto_blackboard_worker_status(_: User = Depends(current_user)) -> dict[str, object]:
    return auto_post_worker_state


@router.post("/auto-posts", response_model=ItemResponse)
def enqueue_auto_blackboard_post(
    request: AutoBlackboardPostCreateRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    task = store.get_task(request.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    thread = store.get_chat_thread(task.thread_id)
    if user.role not in {UserRole.TEAM_LEAD, UserRole.ADMIN} and (
        thread is None or thread.user_id != user.id
    ):
        raise HTTPException(status_code=403, detail="Not allowed to enqueue for this task")
    queued = AutoBlackboardPostRequest(
        **request.model_dump(),
        actor=user.personal_agent_id,
        submitted_by_user_id=user.id,
    )
    return ItemResponse(item=store.enqueue_auto_blackboard_post(queued))


@router.post("/auto-posts/drain", response_model=DrainAutoPostsResponse)
def drain_auto_blackboard_posts_endpoint(user: User = Depends(current_user)) -> DrainAutoPostsResponse:
    ensure_admin(user)
    return drain_queued_auto_blackboard_posts(user.id)


@router.get("/research-dispatch/worker")
def research_dispatch_worker_status(_: User = Depends(current_user)) -> dict[str, object]:
    return research_dispatch_worker_state


@router.post("/research-dispatch/drain")
def drain_research_dispatch_endpoint(user: User = Depends(current_user)) -> dict[str, object]:
    ensure_admin(user)
    return drain_dispatchable_research_requests(user.id)


@router.post("/auto-posts/{request_id}/review", response_model=ItemResponse)
def review_auto_blackboard_post(request_id: str, user: User = Depends(current_user)) -> ItemResponse:
    ensure_admin(user)
    request = next((item for item in store.auto_blackboard_post_requests if item.id == request_id), None)
    if request is None:
        raise HTTPException(status_code=404, detail="Auto blackboard post not found")
    if request.status != "queued":
        raise HTTPException(status_code=409, detail="Auto blackboard post is not queued")
    updated = request.model_copy(update={"status": "reviewed", "reviewed_at": now_utc(), "reviewed_by": user.id})
    store.save_auto_blackboard_post_request(updated)
    store.add_audit_event(
        create_audit_event(user.id, "review_auto_blackboard_post", "auto_blackboard_post", request.id, {})
    )
    return ItemResponse(item=updated)


@router.post("/posts", response_model=ItemResponse)
def create_blackboard_post(
    request: BlackboardPostCreateRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    post = store.add_blackboard_post(
        BlackboardPost(
            task_id=f"manual_{user.id}",
            post_type=request.post_type,
            actor=user.personal_agent_id,
            title=request.title,
            content=request.content,
            scope=request.scope,
            permission=request.permission,
        )
    )
    return ItemResponse(item=post)


@router.post("/posts/{post_id}/lock", response_model=ItemResponse)
def acquire_blackboard_execution_lock(
    post_id: str,
    request: ExecutionLockAcquireRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    post = store.get_blackboard_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Blackboard post not found")
    authorize_post_action(post, user, "lock")
    owner_agent = store.get_agent(request.owner_agent_id) or next(
        (item for item in AGENTS if item.id == request.owner_agent_id),
        None,
    )
    if owner_agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    ensure_can_manage_agent(user, owner_agent, store.permission_policy_rules)
    active_lock = post.execution_lock if post.execution_lock and post.execution_lock.active else None
    if active_lock and active_lock.owner_agent_id != request.owner_agent_id:
        raise HTTPException(status_code=409, detail=f"{active_lock.owner_label} already owns execution")

    owner_label = agent_display_name(request.owner_agent_id)
    lock = ExecutionLock(owner_agent_id=request.owner_agent_id, owner_label=owner_label)
    post.execution_lock = lock
    post.current_owner_agent_id = request.owner_agent_id
    post.current_owner_label = owner_label
    post.collaboration_stage = CollaborationStage.EXECUTION
    store.add_blackboard_post(post)

    task = store.get_task(post.task_id)
    if task is not None:
        task.execution_lock = lock
        task.current_owner_agent_id = request.owner_agent_id
        task.current_owner_label = owner_label
        task.collaboration_stage = CollaborationStage.EXECUTION
        task.updated_at = now_utc()
        store.save_task(task)

    store.add_audit_event(
        create_audit_event(user.id, "acquire_execution_lock", "blackboard_post", post.id, {"owner": owner_label})
    )
    return ItemResponse(item=post)


@router.post("/posts/{post_id}/unlock", response_model=ItemResponse)
def release_blackboard_execution_lock(
    post_id: str,
    request: ExecutionLockReleaseRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    post = store.get_blackboard_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Blackboard post not found")
    authorize_post_action(post, user, "unlock")
    ensure_can_release_execution_lock(user, post)
    if post.execution_lock and post.execution_lock.active:
        post.execution_lock.released_at = now_utc()
        post.execution_lock.released_reason = request.reason
    post.collaboration_stage = CollaborationStage.REVIEW
    store.add_blackboard_post(post)

    task = store.get_task(post.task_id)
    if task is not None:
        if task.execution_lock and task.execution_lock.active:
            task.execution_lock.released_at = now_utc()
            task.execution_lock.released_reason = request.reason
        task.collaboration_stage = CollaborationStage.REVIEW
        task.updated_at = now_utc()
        store.save_task(task)

    store.add_audit_event(
        create_audit_event(user.id, "release_execution_lock", "blackboard_post", post.id, {"reason": request.reason})
    )
    return ItemResponse(item=post)


@router.post("/posts/{post_id}/handoff", response_model=ItemResponse)
def create_blackboard_handoff(
    post_id: str,
    request: BlackboardHandoffRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    parent = store.get_blackboard_post(post_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Blackboard post not found")
    authorize_post_action(parent, user, "handoff")
    ensure_can_release_execution_lock(user, parent)
    next_owner = resolve_handoff_recipient(parent, request.next_owner_agent_id)
    packet = StructuredHandoffPacket(
        goal=request.goal,
        current_result=request.current_result,
        done_when=request.done_when,
        next_owner_agent_id=request.next_owner_agent_id,
        blockers=[item.strip() for item in request.blockers if item.strip()],
        requires_input_from=[item.strip() for item in request.requires_input_from if item.strip()],
    )
    next_owner_label = next_owner.name
    post = store.add_blackboard_post(
        BlackboardPost(
            task_id=parent.task_id,
            post_type="handoff",
            actor=parent.current_owner_label or parent.actor,
            title="任务交接",
            content=handoff_summary(packet, next_owner_label),
            scope=parent.scope,
            permission=parent.permission,
            related_post_id=parent.id,
            collaboration_stage=CollaborationStage.DISCUSSION,
            current_owner_agent_id=packet.next_owner_agent_id,
            current_owner_label=next_owner_label,
            done_when=packet.done_when,
            handoff=packet,
        )
    )
    if parent.execution_lock and parent.execution_lock.active:
        parent.execution_lock.released_at = now_utc()
        parent.execution_lock.released_reason = f"handoff:{packet.next_owner_agent_id}"
        parent.collaboration_stage = CollaborationStage.REVIEW
        store.add_blackboard_post(parent)

    task = store.get_task(parent.task_id)
    if task is not None:
        task.current_owner_agent_id = packet.next_owner_agent_id
        task.current_owner_label = next_owner_label
        task.done_when = packet.done_when
        task.collaboration_stage = CollaborationStage.DISCUSSION
        task.execution_lock = None
        task.steps.append("created_structured_handoff")
        task.updated_at = now_utc()
        store.save_task(task)

    store.add_audit_event(
        create_audit_event(user.id, "create_handoff", "blackboard_post", post.id, {"next_owner": next_owner_label})
    )
    return ItemResponse(item=post)


@router.patch("/posts/{post_id}/read", response_model=ItemResponse)
def mark_blackboard_post_read(post_id: str, user: User = Depends(current_user)) -> ItemResponse:
    post = next((item for item in store.blackboard_posts if item.id == post_id), None)
    if post is None:
        raise HTTPException(status_code=404, detail="Blackboard post not found")
    authorize_post_action(post, user, "read")
    reader_id = user.personal_agent_id
    if reader_id not in post.read_by_agents:
        post.read_by_agents.append(reader_id)
        store.add_blackboard_post(post)
    return ItemResponse(item=post)


@router.post("/posts/{post_id}/reply", response_model=ItemResponse)
def reply_blackboard_post(
    post_id: str,
    request: BlackboardPostCreateRequest,
    user: User = Depends(current_user),
) -> ItemResponse:
    parent = store.get_blackboard_post(post_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Blackboard post not found")
    authorize_post_action(parent, user, "reply to")
    post = store.add_blackboard_post(
        BlackboardPost(
            task_id=parent.task_id,
            post_type=request.post_type,
            actor=user.personal_agent_id,
            title=request.title,
            content=request.content,
            scope=parent.scope,
            permission=parent.permission,
            related_post_id=parent.id,
            collaboration_stage=parent.collaboration_stage,
            current_owner_agent_id=parent.current_owner_agent_id,
            current_owner_label=parent.current_owner_label,
            done_when=parent.done_when,
        )
    )
    return ItemResponse(item=post)
