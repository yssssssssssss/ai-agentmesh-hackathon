"""Authenticated market observability and current-user participation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from agentmesh.marketplace import MARKET_ENABLED, publish_worker_state, scout_worker_state
from agentmesh.models import (
    BlackboardPostType,
    DelegatedAnswerStatus,
    MarketActivityFeed,
    MarketActivityItem,
    MarketMeGraph,
    MarketMeGraphEdge,
    MarketMeGraphNode,
    MarketMePresence,
    MarketMeTimelineItem,
    MarketMeUser,
    MarketMeView,
    MarketMeWorkerState,
    MarketParticipation,
    MarketParticipationRequest,
    User,
)
from agentmesh.routes.deps import current_user
from agentmesh.seed import list_users
from agentmesh.store import SQLiteStore, store

router = APIRouter(prefix="/api/market", tags=["market"])


def _counts() -> dict[str, int]:
    signals = [post for post in store.blackboard_posts if post.post_type == BlackboardPostType.MARKETPLACE_SIGNAL]
    return {
        "signals": len(signals),
        "matches": len([event for event in store.audit_events if event.action == "marketplace_match"]),
        "consent_grants": len([grant for grant in store.consent_grants if grant.active]),
        "participants": len([record for record in store.market_participations if record.enabled]),
    }


@router.get("/status")
def market_status(_: User = Depends(current_user)) -> dict[str, object]:
    return {
        "enabled": MARKET_ENABLED,
        "publish_worker": publish_worker_state,
        "scout_worker": scout_worker_state,
        "counts": _counts(),
    }


def _parse_signal(content: str) -> dict[str, str]:
    fields = {"capability": "", "offer": "", "need": ""}
    labels = {"能力": "capability", "可提供": "offer", "需要": "need"}
    for raw in content.splitlines():
        line = raw.strip()
        for label, key in labels.items():
            for sep in (f"{label}：", f"{label}:"):
                if line.startswith(sep):
                    fields[key] = line[len(sep):].strip()
    return fields


@router.get("/board")
def market_board(_: User = Depends(current_user)) -> dict[str, object]:
    """Everything the dashboard needs in one fetch: workers, counts, signal cards, matches."""
    users_by_id = {user.id: user for user in list_users(store)}
    signals = []
    for post in store.blackboard_posts:
        if post.post_type != BlackboardPostType.MARKETPLACE_SIGNAL:
            continue
        owner_id = post.task_id.removeprefix("signal_")
        owner = users_by_id.get(owner_id)
        signals.append(
            {
                "owner_id": owner_id,
                "owner_name": owner.name if owner else owner_id,
                "participating": store.is_market_participant(owner_id),
                **_parse_signal(post.content),
                "created_at": post.created_at.isoformat(),
            }
        )
    signals.sort(key=lambda item: item["created_at"], reverse=True)

    def _name(user_id: str | None) -> str | None:
        user = users_by_id.get(user_id) if user_id else None
        return user.name if user else user_id

    matches = [
        {
            "helper_id": event.metadata.get("helper"),
            "helper_name": _name(event.metadata.get("helper")),
            "needer_id": event.target_id,
            "needer_name": _name(event.target_id),
            "status": event.metadata.get("status"),
            "at": event.created_at.isoformat(),
        }
        for event in store.audit_events
        if event.action == "marketplace_match"
    ]
    matches = matches[-30:][::-1]

    return {
        "enabled": MARKET_ENABLED,
        "publish_worker": publish_worker_state,
        "scout_worker": scout_worker_state,
        "counts": _counts(),
        "signals": signals,
        "matches": matches,
    }


@router.put("/participation", response_model=MarketParticipation)
def set_participation(
    request: MarketParticipationRequest,
    user: User = Depends(current_user),
) -> MarketParticipation:
    """The current user opts their twins into (or out of) the autonomous market."""
    return store.set_market_participation(user.id, request.enabled)


@router.get("/participation", response_model=MarketParticipation)
def get_participation(user: User = Depends(current_user)) -> MarketParticipation:
    record = store.get_market_participation(user.id)
    return record or MarketParticipation(id=user.id, user_id=user.id, enabled=False)


@router.get("/me", response_model=MarketMeView)
def market_me(user: User = Depends(current_user)) -> MarketMeView:
    """Personal view over the autonomous market: presence tiles, graph, timeline."""
    return build_me_view(user, store)


@router.get("/activity", response_model=MarketActivityFeed)
def market_activity(user: User = Depends(current_user)) -> MarketActivityFeed:
    """Global activity feed: every agent's signals and matches, newest first.

    Where /me is the current user's personal view, this is the whole trading
    floor — so the demo can show many agents helping each other in real time.
    Each item's ``text`` is fully composed server-side; the frontend renders it.
    """
    return build_activity_feed(user, store)


@router.post("/delegated-answers/{inbox_item_id}/resolve")
def resolve_delegated_answer_route(
    inbox_item_id: str,
    action: str,
    user: User = Depends(current_user),
) -> dict[str, object]:
    """The confirmation gate: the target approves or denies a pending delegated answer."""
    from agentmesh.agents import PersonalAgent

    if action not in {"approve", "deny"}:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'deny'")
    item = store.get_inbox_item(inbox_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inbox item not found")
    if item.item_type != PersonalAgent.DELEGATED_CONFIRM_ITEM_TYPE:
        raise HTTPException(status_code=400, detail="Inbox item is not a delegated-answer confirmation")
    if item.metadata.get("target_id") != user.id:
        raise HTTPException(status_code=403, detail="Only the answering user can resolve this request")
    if item.status == "resolved":
        raise HTTPException(status_code=409, detail="This request has already been resolved")

    result = PersonalAgent(store).resolve_delegated_answer(item, action)
    return {
        "status": result.status.value,
        "answer": result.answer,
        "citations": [source.title for source in result.citations],
    }


@router.post("/delegated-answers/adopt")
def adopt_delegated_answer_route(
    helper_id: str,
    question: str,
    user: User = Depends(current_user),
) -> dict[str, object]:
    """The asker adopts a helper's answer: records a contribution point + lineage edge.

    Builds the adopted answer from the match post already on the board (the answer the
    helper's twin produced), rather than re-synthesizing — so adoption doesn't depend on
    a live LLM or standing consent at demo time.
    """
    from agentmesh.agents import PersonalAgent
    from agentmesh.models import AnswerConfidence, DelegatedAnswer, Source

    helper = store.get_user(helper_id)
    if helper is None:
        raise HTTPException(status_code=404, detail="Helper user not found")
    if helper.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot adopt your own answer")

    post = store.get_blackboard_post(f"bb_match_{helper_id}_{user.id}")
    if post is None or not post.content.strip():
        raise HTTPException(status_code=404, detail="No answer from this helper to adopt")

    citation = Source(
        title=f"{helper.name} 的代答：{question}"[:80],
        source_type="delegated_answer",
        reference=f"market://match/{helper_id}",
    )
    store.add_source(citation)
    answer = DelegatedAnswer(
        status=DelegatedAnswerStatus.ANSWERED,
        answer=post.content,
        citations=[citation],
        confidence=AnswerConfidence.HIGH,
    )
    point, relation = PersonalAgent(store).adopt_delegated_answer(asker=user, target=helper, answer=answer)
    return {
        "point_id": point.id,
        "awarded_to": point.awarded_to_id,
        "relation_id": relation.id,
    }


# --- Personal view --------------------------------------------------------


def _worker_view(state: dict[str, Any]) -> MarketMeWorkerState:
    last = state.get("last_run_at")
    return MarketMeWorkerState(
        running=bool(state.get("running")),
        interval_seconds=int(state.get("interval_seconds") or 0),
        last_run_at=last if isinstance(last, str) else None,
    )


def _user_group(user: User, repository: SQLiteStore) -> str:
    workspace = repository.get_workspace(user.workspace_id) if user.workspace_id else None
    return workspace.name if workspace else ""


def _parse_signal_fields(content: str) -> dict[str, str]:
    fields = {"capability": "", "offer": "", "need": ""}
    labels = {"能力": "capability", "可提供": "offer", "需要": "need"}
    for raw in content.splitlines():
        line = raw.strip()
        for label, key in labels.items():
            for sep in (f"{label}：", f"{label}:"):
                if line.startswith(sep):
                    fields[key] = line[len(sep):].strip()
    return fields


def _signals_by_owner(repository: SQLiteStore) -> dict[str, tuple[Any, dict[str, str]]]:
    result: dict[str, tuple[Any, dict[str, str]]] = {}
    for post in repository.blackboard_posts:
        if post.post_type != BlackboardPostType.MARKETPLACE_SIGNAL:
            continue
        owner_id = post.task_id.removeprefix("signal_")
        result[owner_id] = (post, _parse_signal_fields(post.content))
    return result


def _matches_for_user(repository: SQLiteStore, user_id: str) -> tuple[list[Any], list[Any]]:
    """Return (incoming, outgoing) audit events.

    incoming = someone helped me (target_id == user_id)
    outgoing = I helped someone (metadata.helper == user_id)
    """
    incoming, outgoing = [], []
    for event in repository.audit_events:
        if event.action != "marketplace_match":
            continue
        helper = event.metadata.get("helper")
        if event.target_id == user_id and helper != user_id:
            incoming.append(event)
        elif helper == user_id and event.target_id != user_id:
            outgoing.append(event)
    return incoming, outgoing


def _tie_count(user_id: str, incoming: list[Any], outgoing: list[Any]) -> int:
    peers = {event.metadata.get("helper") for event in incoming}
    peers.update(event.target_id for event in outgoing)
    peers.discard(user_id)
    peers.discard(None)
    return len(peers)


def _build_graph(
    me: User,
    repository: SQLiteStore,
    signals: dict[str, tuple[Any, dict[str, str]]],
    my_incoming: list[Any],
    my_outgoing: list[Any],
) -> MarketMeGraph:
    """Nodes: me + every other market participant with source material.

    tie_role classifies each peer relative to me:
      * ``incoming`` — this peer answered one of my needs (helper on my events)
      * ``outgoing`` — I answered this peer's need (target of my outgoing events)
      * ``peer`` — participating but no direct tie yet
    """
    incoming_peers = {event.metadata.get("helper") for event in my_incoming if event.metadata.get("helper")}
    outgoing_peers = {event.target_id for event in my_outgoing if event.target_id}

    nodes: list[MarketMeGraphNode] = []
    edges: list[MarketMeGraphEdge] = []
    included: set[str] = set()

    for user in list_users(repository):
        if user.id != me.id and not repository.is_market_participant(user.id):
            continue
        signal_fields = signals.get(user.id, (None, {}))[1]
        peer_incoming, peer_outgoing = _matches_for_user(repository, user.id)
        ties = _tie_count(user.id, peer_incoming, peer_outgoing)
        role: str
        if user.id == me.id:
            role = "me"
        elif user.id in incoming_peers:
            role = "incoming"
        elif user.id in outgoing_peers:
            role = "outgoing"
        else:
            role = "peer"
        nodes.append(
            MarketMeGraphNode(
                id=user.id,
                name=user.name,
                group=_user_group(user, repository),
                size=26 if user.id == me.id else 18 + min(ties, 6),
                tie_role=role,  # type: ignore[arg-type]
                offer=signal_fields.get("offer", ""),
                need=signal_fields.get("need", ""),
                ties=ties,
            )
        )
        included.add(user.id)

    seen_edges: set[tuple[str, str, str]] = set()
    for event in repository.audit_events:
        if event.action != "marketplace_match":
            continue
        helper = event.metadata.get("helper")
        needer = event.target_id
        if not helper or not needer or helper == needer:
            continue
        if helper not in included or needer not in included:
            continue
        touches_me = helper == me.id or needer == me.id
        direction = ("incoming" if needer == me.id else "outgoing") if touches_me else "peer"
        key = (helper, needer, direction)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append(MarketMeGraphEdge(**{"from": helper, "to": needer, "direction": direction}))  # type: ignore[arg-type]

    return MarketMeGraph(nodes=nodes, edges=edges)


def _timeline_status(raw: str | None) -> str:
    valid = {"answered", "awaiting_confirm", "denied"}
    if raw in valid:
        return raw  # type: ignore[return-value]
    return "answered"


def _match_detail(repository: SQLiteStore, helper_id: str, needer_id: str) -> str:
    """The abstracted answer body for a match, read from its MARKETPLACE_MATCH post."""
    post = repository.get_blackboard_post(f"bb_match_{helper_id}_{needer_id}")
    return post.content if post else ""


def _open_confirm_ref(repository: SQLiteStore, target_id: str) -> str:
    """The open delegated-answer confirmation inbox item id for this target, if any."""
    for item in repository.inbox_items:
        if (
            item.item_type == "delegated_answer_confirmation"
            and item.status == "open"
            and item.metadata.get("target_id") == target_id
        ):
            return item.id
    return ""


def _build_timeline(
    me: User,
    repository: SQLiteStore,
    signal_owned: Any | None,
    my_incoming: list[Any],
    my_outgoing: list[Any],
) -> list[MarketMeTimelineItem]:
    items: list[MarketMeTimelineItem] = []
    users_by_id = {u.id: u for u in list_users(repository)}

    if signal_owned is not None:
        fields = _parse_signal_fields(signal_owned.content)
        need_topic = fields.get("need") or fields.get("offer") or signal_owned.title
        items.append(
            MarketMeTimelineItem(
                id=signal_owned.id,
                at=signal_owned.created_at,
                category="request",
                title=f"我的分身发布了求助：{need_topic}",
                counterpart=None,
                topic=need_topic,
                status="open",
                sensitivity="low",
                meta="agent-1 · publisher · marketplace_signal",
                detail=signal_owned.content,
            )
        )

    for event in my_incoming:
        helper_id = event.metadata.get("helper", "")
        helper = users_by_id.get(helper_id)
        helper_name = helper.name if helper else helper_id
        status = _timeline_status(event.metadata.get("status"))
        topic = event.metadata.get("need") or event.metadata.get("topic") or "我的求助"
        items.append(
            MarketMeTimelineItem(
                id=event.id,
                at=event.created_at,
                category="incoming",
                title=f"{helper_name} 的分身回答了《{topic}》",
                counterpart={"id": helper_id, "name": helper_name} if helper_id else None,
                topic=topic,
                status=status,  # type: ignore[arg-type]
                sensitivity=event.metadata.get("sensitivity", "low"),  # type: ignore[arg-type]
                meta="agent-2 · scout · marketplace_match",
                detail=_match_detail(repository, helper_id, me.id),
            )
        )

    for event in my_outgoing:
        needer_id = event.target_id
        needer = users_by_id.get(needer_id)
        needer_name = needer.name if needer else needer_id
        status = _timeline_status(event.metadata.get("status"))
        topic = event.metadata.get("need") or event.metadata.get("topic") or "对方的求助"
        items.append(
            MarketMeTimelineItem(
                id=event.id,
                at=event.created_at,
                category="outgoing",
                title=f"我的分身帮 {needer_name} 解答了《{topic}》",
                counterpart={"id": needer_id, "name": needer_name} if needer_id else None,
                topic=topic,
                status=status,  # type: ignore[arg-type]
                sensitivity=event.metadata.get("sensitivity", "low"),  # type: ignore[arg-type]
                meta="agent-2 · scout · marketplace_match",
                detail=_match_detail(repository, me.id, needer_id),
                action_ref=_open_confirm_ref(repository, me.id) if status == "awaiting_confirm" else "",
            )
        )

    items.sort(key=lambda item: item.at, reverse=True)
    return items


def build_me_view(user: User, repository: SQLiteStore) -> MarketMeView:
    """Aggregate the current user's personal view over the autonomous market."""
    signals = _signals_by_owner(repository)
    my_signal_entry = signals.get(user.id)
    my_signal_post = my_signal_entry[0] if my_signal_entry else None

    my_incoming, my_outgoing = _matches_for_user(repository, user.id)
    memory_count = len(repository.list_user_memory_items(user_id=user.id))

    presence = MarketMePresence(
        memory_count=memory_count,
        signal_on=repository.is_market_participant(user.id) and my_signal_post is not None,
        signal_refreshed_at=my_signal_post.created_at if my_signal_post else None,
        received_count=len(my_incoming),
        given_count=len(my_outgoing),
    )

    graph = _build_graph(user, repository, signals, my_incoming, my_outgoing)
    timeline = _build_timeline(user, repository, my_signal_post, my_incoming, my_outgoing)

    return MarketMeView(
        user=MarketMeUser(id=user.id, name=user.name, group=_user_group(user, repository)),
        presence=presence,
        workers={
            "publish": _worker_view(publish_worker_state),
            "scout": _worker_view(scout_worker_state),
        },
        graph=graph,
        timeline=timeline,
        enabled=MARKET_ENABLED,
    )


# --- Global activity feed -------------------------------------------------


def build_activity_feed(me: User, repository: SQLiteStore) -> MarketActivityFeed:
    """Merge every participant's signals and matches into one newest-first feed."""
    users_by_id = {u.id: u for u in list_users(repository)}

    def _name(user_id: str | None) -> str:
        user = users_by_id.get(user_id) if user_id else None
        return user.name if user else (user_id or "某位同事")

    items: list[MarketActivityItem] = []

    for post in repository.blackboard_posts:
        if post.post_type != BlackboardPostType.MARKETPLACE_SIGNAL:
            continue
        owner_id = post.task_id.removeprefix("signal_")
        fields = _parse_signal_fields(post.content)
        topic = fields.get("need") or fields.get("offer") or post.title
        actor = _name(owner_id)
        items.append(
            MarketActivityItem(
                id=f"act_signal_{owner_id}",
                at=post.created_at,
                kind="signal",
                status="open",
                actor_name=actor,
                topic=topic,
                text=f"{actor} 的分身发出协作信号，想找人聊聊《{topic}》",
                involves_me=owner_id == me.id,
            )
        )

    for event in repository.audit_events:
        if event.action != "marketplace_match":
            continue
        helper_id = event.metadata.get("helper")
        needer_id = event.target_id
        status = _timeline_status(event.metadata.get("status"))
        topic = event.metadata.get("need") or event.metadata.get("topic") or "一个问题"
        helper = _name(helper_id)
        needer = _name(needer_id)
        verb = {
            "answered": f"{helper} 的分身解答了 {needer} 的《{topic}》",
            "awaiting_confirm": f"{helper} 的分身准备代答 {needer} 的《{topic}》，等待确认放行",
            "denied": f"{helper} 的分身判断《{topic}》过于敏感，婉拒了 {needer}",
        }.get(status, f"{helper} 的分身回应了 {needer} 的《{topic}》")
        items.append(
            MarketActivityItem(
                id=f"act_match_{helper_id}_{needer_id}",
                at=event.created_at,
                kind="match",
                status=status,  # type: ignore[arg-type]
                actor_name=helper,
                counterpart_name=needer,
                topic=topic,
                text=verb,
                involves_me=me.id in (helper_id, needer_id),
            )
        )

    items.sort(key=lambda item: item.at, reverse=True)
    return MarketActivityFeed(items=items[:40], enabled=MARKET_ENABLED)


