"""Authenticated market observability and current-user participation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from agentmesh.delegated_queries import (
    DelegatedQueryCreate,
    DelegatedQueryError,
    DelegatedQueryList,
    DelegatedQueryService,
    DelegatedQueryView,
    QueryAdoptionV1,
    QueryAdoptRequest,
    QueryConsentList,
    QueryConsentRequest,
    QueryConsentView,
    QueryResolveRequest,
)
from agentmesh.market_read import MarketReadSnapshot, read_market
from agentmesh.market_scout import MarketScoutRepository
from agentmesh.marketplace import MARKET_ENABLED, publish_worker_state, scout_worker_state
from agentmesh.memory_facts import MemoryFactsError
from agentmesh.models import (
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
from agentmesh.store import SQLiteStore, store

router = APIRouter(prefix="/api/market", tags=["market"])


@router.post('/queries', response_model=DelegatedQueryView)
def create_query(request: DelegatedQueryCreate, user: User = Depends(current_user)):
    try:
        return DelegatedQueryService(store).create(user, request)
    except DelegatedQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None


@router.get('/queries', response_model=DelegatedQueryList)
def list_queries(project_id: str, user: User = Depends(current_user)):
    try:
        return DelegatedQueryService(store).list(user, project_id)
    except DelegatedQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None


@router.get('/queries/{query_id}', response_model=DelegatedQueryView)
def get_query(query_id: str, user: User = Depends(current_user)):
    try:
        return DelegatedQueryService(store).get(user, query_id)
    except DelegatedQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None


@router.post('/queries/{query_id}/resolve', response_model=DelegatedQueryView)
def resolve_query(query_id: str, request: QueryResolveRequest, user: User = Depends(current_user)):
    try:
        return DelegatedQueryService(store).resolve(user, query_id, action=request.action,
                                                    expected_version=request.expected_version)
    except DelegatedQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None


@router.post('/queries/{query_id}/resume', response_model=DelegatedQueryView)
def resume_query(query_id: str, user: User = Depends(current_user)):
    try:
        return DelegatedQueryService(store).resume(user, query_id)
    except DelegatedQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None


@router.post('/queries/{query_id}/adopt', response_model=QueryAdoptionV1)
def adopt_query(query_id: str, request: QueryAdoptRequest, user: User = Depends(current_user)):
    try:
        return DelegatedQueryService(store).adopt(user, query_id, request)
    except DelegatedQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None


@router.get('/query-consents', response_model=QueryConsentList)
def list_query_consents(project_id: str, user: User = Depends(current_user)):
    try:
        return DelegatedQueryService(store).consents(user, project_id)
    except DelegatedQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None


@router.put('/query-consents', response_model=QueryConsentView)
def set_query_consent(request: QueryConsentRequest, user: User = Depends(current_user)):
    try:
        return DelegatedQueryService(store).set_consent(user, request)
    except DelegatedQueryError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None


def _snapshot(user: User, repository: SQLiteStore, project_id: str | None = None) -> MarketReadSnapshot:
    try:
        return read_market(user, repository, project_id=project_id)
    except MemoryFactsError as error:
        raise HTTPException(status_code=error.status_code, detail=error.code) from None


def _scout_state(user: User, project_id: str) -> dict[str, object]:
    health = MarketScoutRepository(store).queue_health(workspace_id=user.workspace_id,
        project_id=project_id, helper_id=user.id)
    return {**_public_worker(scout_worker_state), "queue": health, "last_error": health["last_error_code"]}


def _public_worker(state: dict[str, object]) -> dict[str, object]:
    return {key: state.get(key) for key in ('enabled', 'running', 'interval_seconds', 'last_run_at')}


@router.get("/status")
def market_status(user: User = Depends(current_user),
                  project_id: str | None = Query(default=None, min_length=1, max_length=120)) -> dict[str, object]:
    data = _snapshot(user, store, project_id)
    return {
        "enabled": MARKET_ENABLED,
        "publish_worker": _public_worker(publish_worker_state),
        "scout_worker": _scout_state(data.actor, data.project.id),
        "counts": data.counts,
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
def market_board(user: User = Depends(current_user),
                 project_id: str | None = Query(default=None, min_length=1, max_length=120)) -> dict[str, object]:
    """Everything the dashboard needs in one fetch: workers, counts, signal cards, matches."""
    data = _snapshot(user, store, project_id)
    users_by_id = data.users
    signals = []
    for post in data.signals:
        owner_id = post.task_id.removeprefix("signal_")
        owner = users_by_id.get(owner_id)
        signals.append(
            {
                "owner_id": owner_id,
                "owner_name": owner.name if owner else owner_id,
                "participating": owner_id in data.participants,
                **_parse_signal(post.content),
                "created_at": post.created_at.isoformat(),
            }
        )

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
        for event in data.matches
    ]
    matches = matches[:30]

    return {
        "enabled": MARKET_ENABLED,
        "publish_worker": _public_worker(publish_worker_state),
        "scout_worker": _scout_state(data.actor, data.project.id),
        "counts": data.counts,
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
def market_me(user: User = Depends(current_user),
              project_id: str | None = Query(default=None, min_length=1, max_length=120)) -> MarketMeView:
    """Personal view over the autonomous market: presence tiles, graph, timeline."""
    return build_me_view(user, store, project_id=project_id)


@router.get("/activity", response_model=MarketActivityFeed)
def market_activity(user: User = Depends(current_user),
                    project_id: str | None = Query(default=None, min_length=1, max_length=120)) -> MarketActivityFeed:
    """Current-project activity, newest first, with no private answer bodies."""
    return build_activity_feed(user, store, project_id=project_id)


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

    if item.metadata.get('query_id'):
        service = DelegatedQueryService(store)
        try:
            query = service.get(user, item.metadata['query_id'])
            result = service.resolve(user, query.id, action=action, expected_version=query.version)
        except DelegatedQueryError as error:
            raise HTTPException(status_code=error.status_code, detail=error.code) from None
        return {'status': result.status, 'answer': result.answer, 'citations': [source.title for source in result.citations]}

    raise HTTPException(status_code=409, detail='verified_delegated_query_required')


@router.post("/delegated-answers/adopt")
def adopt_delegated_answer_route(
    helper_id: str,
    question: str,
    user: User = Depends(current_user),
) -> dict[str, object]:
    """Legacy match posts contain status metadata, not verifiable answer artifacts."""
    raise HTTPException(status_code=409, detail="verified_delegated_query_required")


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


def _signals_by_owner(data: MarketReadSnapshot) -> dict[str, tuple[Any, dict[str, str]]]:
    result: dict[str, tuple[Any, dict[str, str]]] = {}
    for post in data.signals:
        owner_id = post.task_id.removeprefix("signal_")
        result.setdefault(owner_id, (post, _parse_signal(post.content)))
    return result


def _matches_for_user(data: MarketReadSnapshot, user_id: str) -> tuple[list[Any], list[Any]]:
    """Return (incoming, outgoing) audit events.

    incoming = someone helped me (target_id == user_id)
    outgoing = I helped someone (metadata.helper == user_id)
    """
    incoming, outgoing = [], []
    for event in data.matches:
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
    group: str,
    signals: dict[str, tuple[Any, dict[str, str]]],
    data: MarketReadSnapshot,
    my_incoming: list[Any],
    my_outgoing: list[Any],
) -> MarketMeGraph:
    """Bounded roster and ties from the latest 200 current-project matches.

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

    for user in data.users.values():
        if user.id != me.id and user.id not in data.participants:
            continue
        signal_fields = signals.get(user.id, (None, {}))[1]
        peer_incoming, peer_outgoing = _matches_for_user(data, user.id)
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
                group=group,
                size=26 if user.id == me.id else 18 + min(ties, 6),
                tie_role=role,  # type: ignore[arg-type]
                offer=signal_fields.get("offer", ""),
                need=signal_fields.get("need", ""),
                ties=ties,
            )
        )
        included.add(user.id)

    seen_edges: set[tuple[str, str, str]] = set()
    for event in data.matches:
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
    valid = {"answered", "awaiting_confirm", "denied", "blocked", "insufficient_evidence"}
    if raw in valid:
        return raw  # type: ignore[return-value]
    return "open"


def _match_detail(status: str) -> str:
    return {
        'answered': '历史记录显示已答复；可在本人有权访问的提问记录中查看答复。',
        'awaiting_confirm': '提问等待回答方本人确认。',
        'denied': '回答方已拒绝此提问。',
        'blocked': '代答暂不可用，未交付答复。',
        'insufficient_evidence': '资料不足，未生成答复。',
    }.get(status, '该协作记录尚未核验。')


def _build_timeline(
    me: User,
    signal_owned: Any | None,
    data: MarketReadSnapshot,
    my_incoming: list[Any],
    my_outgoing: list[Any],
) -> list[MarketMeTimelineItem]:
    items: list[MarketMeTimelineItem] = []
    users_by_id = data.users

    if signal_owned is not None:
        fields = _parse_signal(signal_owned.content)
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
                title=f"{helper_name} 的分身回应了《{topic}》",
                counterpart={"id": helper_id, "name": helper_name} if helper_id else None,
                topic=topic,
                status=status,  # type: ignore[arg-type]
                sensitivity=event.metadata.get("sensitivity", "low"),  # type: ignore[arg-type]
                meta="agent-2 · scout · marketplace_match",
                detail=_match_detail(status),
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
                title=f"我的分身处理了 {needer_name} 的《{topic}》",
                counterpart={"id": needer_id, "name": needer_name} if needer_id else None,
                topic=topic,
                status=status,  # type: ignore[arg-type]
                sensitivity=event.metadata.get("sensitivity", "low"),  # type: ignore[arg-type]
                meta="agent-2 · scout · marketplace_match",
                detail=_match_detail(status),
            )
        )

    items.sort(key=lambda item: item.at, reverse=True)
    return items[:200]


def build_me_view(user: User, repository: SQLiteStore, *, project_id: str | None = None) -> MarketMeView:
    """Aggregate the current user's personal view over the autonomous market."""
    data = _snapshot(user, repository, project_id)
    user = data.actor
    signals = _signals_by_owner(data)
    my_signal_entry = signals.get(user.id)
    my_signal_post = my_signal_entry[0] if my_signal_entry else None

    my_incoming, my_outgoing = _matches_for_user(data, user.id)
    memory_count = data.memory_count

    presence = MarketMePresence(
        memory_count=memory_count,
        signal_on=user.id in data.participants and my_signal_post is not None,
        signal_refreshed_at=my_signal_post.created_at if my_signal_post else None,
        received_count=data.received_count,
        given_count=data.given_count,
    )

    group = _user_group(user, repository)
    graph = _build_graph(user, group, signals, data, my_incoming, my_outgoing)
    timeline = _build_timeline(user, my_signal_post, data, my_incoming, my_outgoing)

    return MarketMeView(
        user=MarketMeUser(id=user.id, name=user.name, group=group),
        presence=presence,
        workers={
            "publish": _worker_view(publish_worker_state),
            "scout": _worker_view(scout_worker_state),
        },
        graph=graph,
        timeline=timeline,
        enabled=MARKET_ENABLED,
    )


# --- Current-project activity feed ---------------------------------------


def build_activity_feed(me: User, repository: SQLiteStore, *, project_id: str | None = None) -> MarketActivityFeed:
    """Merge bounded, authorized current-project signals and matches."""
    data = _snapshot(me, repository, project_id)
    me = data.actor
    users_by_id = data.users

    def _name(user_id: str | None) -> str:
        user = users_by_id.get(user_id) if user_id else None
        return user.name if user else (user_id or "某位同事")

    items: list[MarketActivityItem] = []

    for post in data.signals:
        owner_id = post.task_id.removeprefix("signal_")
        fields = _parse_signal(post.content)
        topic = fields.get("need") or fields.get("offer") or post.title
        actor = _name(owner_id)
        items.append(
            MarketActivityItem(
                id=f"act_signal_{post.id}",
                at=post.created_at,
                kind="signal",
                status="open",
                actor_name=actor,
                topic=topic,
                text=f"{actor} 的分身发出协作信号，想找人聊聊《{topic}》",
                involves_me=owner_id == me.id,
            )
        )

    for event in data.matches:
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
            'blocked': f'{helper} 的分身暂不可代答 {needer} 的《{topic}》',
            'insufficient_evidence': f'{helper} 的分身没有足够资料回答 {needer} 的《{topic}》',
        }.get(status, f"{helper} 的分身回应了 {needer} 的《{topic}》")
        items.append(
            MarketActivityItem(
                id=f"act_match_{event.id}",
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
