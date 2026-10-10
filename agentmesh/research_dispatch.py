"""Bounded, durable delivery of the existing legacy research requests."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from math import isfinite
from uuid import uuid4

import httpx
from pydantic import ValidationError

from agentmesh.agents import PersonalAgent, RequestAlreadyFulfilledError, ResearchFulfillment
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AuditEvent,
    BlackboardPost,
    ChatThread,
    ChatThreadKind,
    Project,
    ResearchDispatchDrainV1,
    ResearchDispatchStateV1,
    Task,
    TaskStatus,
    User,
    now_utc,
)
from agentmesh.o2 import O2CommandError
from agentmesh.provider_status import ProviderQueryError
from agentmesh.store import SQLiteStore
from agentmesh.web_research import WebResearchError


class ResearchRequestBlockedError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def authorize_research_owner(
    repository: SQLiteStore, task: Task, user: User, request_post: BlackboardPost | None = None,
) -> None:
    """Recheck immediately around provider I/O; caller identities are never authority."""
    owner = repository.get_user(user.id)
    thread = repository.get_chat_thread(task.thread_id)
    project = repository.get_project(thread.project_id) if thread else None
    if not _owner_authorized(owner, thread, project) or thread.user_id != user.id:
        raise ResearchRequestBlockedError("research_owner_not_authorized", status_code=403)
    current = repository.get_task(task.id)
    if current is None or current.status != "waiting_external_agent" or current.thread_id != task.thread_id:
        raise ResearchRequestBlockedError("research_task_not_dispatchable")
    if current.management is not None or thread.kind != ChatThreadKind.CONVERSATION:
        raise ResearchRequestBlockedError("research_project_task_requires_runtime")
    if "requested_tool_call_approval" in current.steps:
        raise ResearchRequestBlockedError("research_tool_approval_required")
    if request_post is not None:
        current_post = repository.get_blackboard_post(request_post.id)
        if current_post is None or _request_hash(current_post) != _request_hash(request_post):
            raise ResearchRequestBlockedError("research_request_changed")
        claim = request_post.research_dispatch
        if claim and not _context_matches(claim, owner, thread):
            raise ResearchRequestBlockedError("research_context_changed")
        if claim and (
            current_post.research_dispatch is None
            or current_post.research_dispatch.status != "running"
            or current_post.research_dispatch.claim_id != claim.claim_id
        ):
            raise ResearchRequestBlockedError("research_claim_superseded")


def _owner_authorized(owner: User | None, thread: ChatThread | None, project: Project | None) -> bool:
    return bool(
        owner and thread and project
        and owner.status == "active" and thread.status == "active" and project.status == "active"
        and owner.id == thread.user_id and owner.workspace_id == thread.workspace_id == project.workspace_id
        and (not project.member_ids or owner.id in project.member_ids)
    )


def _request_hash(post: BlackboardPost) -> str:
    return canonical_json_sha256({
        "task_id": post.task_id, "content": post.content, "post_type": post.post_type,
        "scope": post.scope, "permission": post.permission,
    })


def _context_matches(state: ResearchDispatchStateV1, owner: User, thread: ChatThread) -> bool:
    return (state.owner_user_id, state.workspace_id, state.project_id, state.thread_id) == (
        owner.id, thread.workspace_id, thread.project_id, thread.id,
    )


def _failure(error: Exception, at: datetime) -> tuple[str, bool, float]:
    """Only recognized transient *reads* retry. No exception text is persisted."""
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "research_read_timeout", True, 0
    if isinstance(error, (ConnectionError, httpx.NetworkError)):
        return "research_read_unavailable", True, 0
    if isinstance(error, sqlite3.OperationalError) and getattr(error, "sqlite_errorcode", None) in {
        sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
    }:
        return "research_store_busy", True, 0
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status in {429, 502, 503, 504}:
            header = error.response.headers.get("Retry-After", "0")
            try:
                retry_after = max(0, float(header))
            except ValueError:
                try:
                    retry_after = max(0, (parsedate_to_datetime(header) - at).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    retry_after = 0
            try:
                if not isfinite(retry_after):
                    raise OverflowError
                at + timedelta(seconds=retry_after)
            except OverflowError:
                return "research_provider_response_invalid", False, 0
            return "research_read_rate_limited" if status == 429 else "research_read_unavailable", True, retry_after
        return "research_provider_unauthorized" if status in {401, 403} else "research_provider_rejected", False, 0
    if isinstance(error, ResearchRequestBlockedError):
        return error.code, False, 0
    if isinstance(error, ProviderQueryError):
        # Provider reasons are not arbitrary upstream exception messages.
        allowed = {
            "no_real_provider_configured", "demo_provider_disabled", "unverified_provider_result",
            "insufficient_evidence", "no_data_source_result",
        }
        return error.reason if error.reason in allowed else "research_provider_failed", False, 0
    if isinstance(error, WebResearchError):
        if error.reason in {"timeout", "rate_limit", "provider_unavailable"}:
            return "research_read_" + error.reason, True, 0
        return "research_provider_unauthorized" if error.reason == "auth_error" else "research_provider_failed", False, 0
    if isinstance(error, O2CommandError):
        return ("research_read_timeout", True, 0) if error.reason == "timeout" else ("research_provider_failed", False, 0)
    if isinstance(error, (ValueError, ValidationError)):
        return "research_input_invalid", False, 0
    return "research_dispatch_failed", False, 0


class ResearchDispatchRepository:
    def __init__(self, repository: SQLiteStore):
        self.store = repository

    @staticmethod
    def _get(connection, collection, record_id, model):
        row = connection.execute(
            "SELECT payload FROM records WHERE collection = ? AND id = ?", (collection, record_id),
        ).fetchone()
        return model.model_validate_json(row["payload"]) if row else None

    def candidates(self, at: datetime, epoch: str, *, limit: int, workspace_id: str | None) -> list[str]:
        with closing(self.store._connect()) as connection:
            rows = connection.execute(
                """SELECT post.id FROM records post
                LEFT JOIN records task ON task.collection = 'tasks' AND task.id = json_extract(post.payload, '$.task_id')
                LEFT JOIN records thread ON thread.collection = 'chat_threads'
                    AND thread.id = json_extract(task.payload, '$.thread_id')
                WHERE post.collection = 'blackboard_posts' AND json_extract(post.payload, '$.post_type') = 'request'
                    AND (? IS NULL OR COALESCE(json_extract(post.payload, '$.research_dispatch.workspace_id'),
                        json_extract(thread.payload, '$.workspace_id')) = ?)
                    AND (json_extract(post.payload, '$.research_dispatch.status') IS NULL
                        AND json_extract(task.payload, '$.status') = 'waiting_external_agent'
                        OR json_extract(post.payload, '$.research_dispatch.status') = 'retry_wait'
                            AND julianday(json_extract(post.payload, '$.research_dispatch.next_retry_at')) <= julianday(?)
                        OR json_extract(post.payload, '$.research_dispatch.status') = 'running'
                            AND (json_extract(post.payload, '$.research_dispatch.process_epoch') != ?
                                OR julianday(json_extract(post.payload, '$.research_dispatch.lease_expires_at')) <= julianday(?)))
                    AND NOT EXISTS (SELECT 1 FROM json_each(task.payload, '$.steps')
                        WHERE value = 'requested_tool_call_approval')
                ORDER BY post.created_order LIMIT ?""",
                (workspace_id, workspace_id, at.isoformat(), epoch, at.isoformat(), limit),
            ).fetchall()
        return [row["id"] for row in rows]

    def queue_health(self, *, workspace_id: str | None) -> dict[str, object]:
        query = """FROM records post
            WHERE post.collection = 'blackboard_posts' AND json_extract(post.payload, '$.post_type') = 'request'
                AND json_extract(post.payload, '$.research_dispatch.status') IS NOT NULL
                AND (? IS NULL OR json_extract(post.payload, '$.research_dispatch.workspace_id') = ?)"""
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT json_extract(post.payload, '$.research_dispatch.status') status, COUNT(*) count "
                + query + " GROUP BY status", (workspace_id, workspace_id),
            ).fetchall()
            error = connection.execute(
                "SELECT json_extract(post.payload, '$.research_dispatch.last_error_code') code " + query
                + " AND json_extract(post.payload, '$.research_dispatch.last_error_code') IS NOT NULL"
                + " ORDER BY julianday(json_extract(post.payload, '$.research_dispatch.updated_at')) DESC LIMIT 1",
                (workspace_id, workspace_id),
            ).fetchone()
        return {"counts": {row["status"]: row["count"] for row in rows}, "last_error_code": error["code"] if error else None}

    def _save_state(self, connection, post, state, actor):
        post.research_dispatch = state
        connection.execute(
            "UPDATE records SET payload = ? WHERE collection = 'blackboard_posts' AND id = ?",
            (post.model_dump_json(), post.id),
        )
        event = AuditEvent(
            actor=actor, action="research_dispatch_" + state.status, target_type="blackboard_post", target_id=post.id,
            workspace_id=state.workspace_id, project_id=state.project_id,
            metadata={"attempts": state.attempts, "error_code": state.last_error_code},
        )
        connection.execute(
            "INSERT INTO records(collection, id, payload) VALUES ('audit_events', ?, ?)",
            (event.id, event.model_dump_json()),
        )

    def claim(self, post_id, at, epoch, actor, *, owner_id: str | None = None):
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            post = self._get(connection, "blackboard_posts", post_id, BlackboardPost)
            if post is None or post.post_type != "request":
                return None, None, None
            state = post.research_dispatch
            if state and state.status not in {"running", "retry_wait"}:
                return None, None, None
            if state and state.status == "running" and state.process_epoch == epoch and state.lease_expires_at > at:
                return None, None, None
            if state and state.status == "retry_wait" and state.next_retry_at > at:
                return None, None, None
            task = self._get(connection, "tasks", post.task_id, Task)
            thread = self._get(connection, "chat_threads", task.thread_id, ChatThread) if task else None
            owner = self._get(connection, "users", thread.user_id, User) if thread else None
            project = self._get(connection, "projects", thread.project_id, Project) if thread else None
            if owner_id is not None and (owner is None or owner.id != owner_id):
                raise ResearchRequestBlockedError("research_owner_not_authorized", status_code=403)
            if task and "requested_tool_call_approval" in task.steps:
                return None, None, None
            state = state or ResearchDispatchStateV1(
                status="running", request_hash=_request_hash(post), updated_at=at,
                owner_user_id=owner.id if owner else None, workspace_id=thread.workspace_id if thread else None,
                project_id=thread.project_id if thread else None, thread_id=thread.id if thread else None,
            )
            code, outcome = None, None
            if not _owner_authorized(owner, thread, project):
                code, outcome = "research_owner_not_authorized", "blocked"
            elif not _context_matches(state, owner, thread):
                code, outcome = "research_context_changed", "blocked"
            elif state.request_hash != _request_hash(post):
                code, outcome = "research_request_changed", "blocked"
            elif task.management is not None or thread.kind != ChatThreadKind.CONVERSATION:
                code, outcome = "research_project_task_requires_runtime", "blocked"
            else:
                evidence_row = connection.execute(
                    """SELECT payload FROM records WHERE collection = 'blackboard_posts'
                    AND json_extract(payload, '$.related_post_id') = ? AND json_extract(payload, '$.post_type') = 'evidence'
                    ORDER BY created_order LIMIT 1""", (post.id,),
                ).fetchone()
                evidence = BlackboardPost.model_validate_json(evidence_row["payload"]) if evidence_row else None
                if evidence:
                    state.evidence_post_id = evidence.id
                    if evidence.status == "needs_review":
                        outcome = "quarantined"
                    else:
                        # A legacy multi-write fulfillment can be interrupted. Do not silently replay it.
                        code, outcome = "research_result_requires_reconciliation", "indeterminate"
                elif task.status != "waiting_external_agent":
                    code, outcome = "research_task_not_dispatchable", "blocked"
                elif state.attempts >= 3:
                    code, outcome = "research_attempts_exhausted", "failed"
            if outcome:
                state = state.model_copy(update={
                    "status": outcome, "last_error_code": code, "next_retry_at": None,
                    "claim_id": None, "process_epoch": None, "lease_expires_at": None, "updated_at": at,
                })
                self._save_state(connection, post, state, actor)
                return None, None, state
            state = state.model_copy(update={
                "status": "running", "attempts": state.attempts + 1, "claim_id": uuid4().hex,
                "process_epoch": epoch, "lease_expires_at": at + timedelta(minutes=10),
                "next_retry_at": None, "updated_at": at,
            })
            self._save_state(connection, post, state, actor)
            return post, owner, None

    def finish(self, post_id, claim_id, state, actor):
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            post = self._get(connection, "blackboard_posts", post_id, BlackboardPost)
            if not post or not post.research_dispatch or post.research_dispatch.claim_id != claim_id:
                return False
            self._save_state(connection, post, state, actor)
            if state.status == "failed":
                task = self._get(connection, "tasks", post.task_id, Task)
                if task and task.status == "waiting_external_agent":
                    task.status = TaskStatus.FAILED
                    task.updated_at = state.updated_at
                    connection.execute(
                        "UPDATE records SET payload = ? WHERE collection = 'tasks' AND id = ?",
                        (task.model_dump_json(), task.id),
                    )
        return True


class ResearchDispatchService:
    def __init__(
        self, repository: SQLiteStore, agent: PersonalAgent, *, process_epoch: str, clock: Callable[[], datetime] = now_utc,
    ):
        self.store = repository
        self.repository = ResearchDispatchRepository(repository)
        self.agent = agent
        self.epoch = process_epoch
        self.clock = clock

    def queue_health(self, *, workspace_id: str | None = None) -> dict[str, object]:
        return self.repository.queue_health(workspace_id=workspace_id)

    def dispatch(self, post_id: str, user: User) -> ResearchFulfillment:
        post, owner, settled = self.repository.claim(
            post_id, self.clock(), self.epoch, user.id, owner_id=user.id,
        )
        if post is None:
            raise ResearchRequestBlockedError(
                settled.last_error_code if settled and settled.last_error_code else "research_request_already_claimed",
            )
        _, fulfillment = self._execute(post, owner, user.id, raise_errors=True)
        assert fulfillment is not None
        return fulfillment

    def drain(self, actor: str, *, limit: int = 50) -> ResearchDispatchDrainV1:
        if not 1 <= limit <= 100:
            raise ValueError("research_page_invalid")
        at = self.clock()
        if at.utcoffset() is None:
            raise ValueError("research_time_invalid")
        actor_user = self.store.get_user(actor)
        candidates = self.repository.candidates(
            at, self.epoch, limit=limit + 1, workspace_id=actor_user.workspace_id if actor_user else None,
        )
        result = ResearchDispatchDrainV1(has_more=len(candidates) > limit)
        for post_id in candidates[:limit]:
            post, owner, settled = self.repository.claim(post_id, self.clock(), self.epoch, actor)
            if settled:
                self._count(result, settled, recovered=True)
            if post is None:
                continue
            state, _ = self._execute(post, owner, actor)
            if state is not None:
                self._count(result, state)
        return result

    def _execute(self, post, owner, actor, *, raise_errors=False):
        claim = post.research_dispatch
        state = claim.model_copy(update={
            "claim_id": None, "process_epoch": None, "lease_expires_at": None, "last_error_code": None,
        })
        fulfillment, caught_error = None, None
        try:
            fulfillment = self.agent.fulfill_research_request(post, owner)
            state.status = "quarantined" if fulfillment.quarantined else "completed"
            state.evidence_post_id = fulfillment.evidence_post.id
        except RequestAlreadyFulfilledError as error:
            caught_error = error
            state.status = "indeterminate"
            state.last_error_code = "research_result_requires_reconciliation"
        except Exception as error:
            caught_error = error
            code, retryable, retry_after = _failure(error, self.clock())
            # Any persisted evidence makes a retry ambiguous, even if the exception looked transient.
            with closing(self.store._connect()) as connection:
                has_evidence = connection.execute(
                    """SELECT 1 FROM records WHERE collection = 'blackboard_posts'
                    AND json_extract(payload, '$.related_post_id') = ?
                    AND json_extract(payload, '$.post_type') = 'evidence' LIMIT 1""", (post.id,),
                ).fetchone()
            if has_evidence:
                state.status, code = "indeterminate", "research_result_requires_reconciliation"
            elif isinstance(error, ResearchRequestBlockedError):
                state.status = "blocked"
            elif retryable and state.attempts < 3:
                state.status = "retry_wait"
                state.next_retry_at = self.clock() + timedelta(seconds=max((5, 30)[state.attempts - 1], retry_after))
            else:
                state.status = "failed"
            state.last_error_code = code
        state.updated_at = self.clock()
        if not self.repository.finish(post.id, claim.claim_id, state, actor):
            if raise_errors:
                raise ResearchRequestBlockedError("research_claim_superseded")
            return None, None
        if caught_error is not None and raise_errors:
            if isinstance(caught_error, (ProviderQueryError, ResearchRequestBlockedError)):
                raise caught_error
            raise ResearchRequestBlockedError(
                state.last_error_code, status_code=503 if state.status in {"retry_wait", "failed"} else 409,
            ) from caught_error
        if fulfillment is not None:
            fulfillment.request_post.research_dispatch = state
        return state, fulfillment

    @staticmethod
    def _count(result, state, *, recovered=False):
        if recovered:
            result.recovered += 1
        elif state.status in {"completed", "quarantined"}:
            result.dispatched += 1
        if state.status == "retry_wait":
            result.retrying += 1
        elif state.status in {"failed", "blocked", "indeterminate"}:
            setattr(result, state.status, getattr(result, state.status) + 1)
        if state.last_error_code:
            result.last_error_code = state.last_error_code
