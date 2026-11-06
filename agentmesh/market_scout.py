"""Durable matching receipts. Inbox/consent remain the delegated-answer authorities."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.market_scout_materials import MarketScoutMaterials, ScoutKnowledge
from agentmesh.model_registry import resolve_agent_model_id
from agentmesh.models import BlackboardPost, User, now_utc
from agentmesh.store import SQLiteStore
from agentmesh.synthesis import ChatLLM, FailoverChatLLM

_PROCESS_EPOCH = uuid4().hex
MATCHING_POLICY_VERSION = "market-matching-v3-scoped-qualified-material"


class MarketMatchingReadError(RuntimeError):
    """The model did not produce a matching decision; it did not say NO."""

    def __init__(self, code: str, *, retryable: bool = True):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class _GuardedMatchingClient:
    def __init__(self, client: ChatLLM, current: Callable[[], bool]):
        self.client, self.current = client, current

    def __getattr__(self, name):
        return getattr(self.client, name)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.current():
            raise MarketMatchingReadError('market_authorization_changed')
        return self.client.complete(system_prompt, user_prompt)


def guarded_matching_client(client: ChatLLM | None, current: Callable[[], bool]) -> ChatLLM | None:
    if client is None:
        return None
    if isinstance(client, FailoverChatLLM):
        return FailoverChatLLM(guarded_matching_client(client.primary, current),
                               guarded_matching_client(client.fallback, current))
    return _GuardedMatchingClient(client, current)


def _model_identity(client: ChatLLM | None) -> dict[str, object]:
    if isinstance(client, FailoverChatLLM):
        return {'adapter': type(client).__name__, 'primary': _model_identity(client.primary),
                'fallback': _model_identity(client.fallback)}
    return {'name': getattr(client, 'model', None), 'adapter': type(client).__name__,
            'endpoint': getattr(client, 'base_url', None), 'api_style': getattr(client, 'api_style', None)}


class MarketScoutReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["market-scout-receipt-v1"] = "market-scout-receipt-v1"
    id: str
    helper_id: str
    workspace_id: str | None = None
    project_id: str | None = None
    post_id: str
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["matching", "delivering", "processed", "retry_wait", "blocked", "indeterminate"]
    attempts: int = Field(default=1, ge=1)
    claim_id: str | None = None
    process_epoch: str | None = None
    lease_expires_at: AwareDatetime | None = None
    next_retry_at: AwareDatetime | None = None
    last_error_code: str | None = None
    outcome: str | None = None
    inbox_item_id: str | None = None
    updated_at: AwareDatetime


class MarketScoutRepository:
    def __init__(self, repository: SQLiteStore, *, process_epoch: str = _PROCESS_EPOCH):
        self.store = repository
        self.epoch = process_epoch

    def _page(self, cursor_id, query, parameters, model, limit):
        if not 1 <= limit <= 100:
            raise ValueError("market_page_invalid")
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "SELECT payload FROM records WHERE collection = 'market_scan_cursors' AND id = ?", (cursor_id,),
            ).fetchone()
            after = json.loads(cursor["payload"])["after_order"] if cursor else 0
            rows = connection.execute(query + " LIMIT ?", (*parameters, after, limit + 1)).fetchall()
            selected = rows[:limit]
            next_order = selected[-1]["created_order"] if len(rows) > limit else 0
            connection.execute(
                """INSERT INTO records(collection, id, payload) VALUES ('market_scan_cursors', ?, ?)
                    ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload""",
                (cursor_id, json.dumps({"id": cursor_id, "after_order": next_order})),
            )
        return [model.model_validate_json(row["payload"]) for row in selected]

    def participant_page(self, worker: Literal["publish", "scout"], *, limit: int = 50) -> list[User]:
        return self._page(
            "market_participants_" + worker,
            """SELECT user.payload, user.created_order FROM records user JOIN records participation
                ON participation.collection = 'market_participation' AND participation.id = user.id
                WHERE user.collection = 'users' AND json_extract(user.payload, '$.status') = 'active'
                    AND json_extract(participation.payload, '$.enabled') = 1
                    AND user.created_order > ? ORDER BY user.created_order""", (), User, limit,
        )

    def signal_page(self, user: User, *, limit: int = 20) -> list[BlackboardPost]:
        return self._page(
            "market_signals_" + user.id,
            """SELECT post.payload, post.created_order FROM records post JOIN records owner
                ON owner.collection = 'users' AND owner.id = substr(json_extract(post.payload, '$.task_id'), 8)
                JOIN records project ON project.collection = 'projects'
                    AND project.id = json_extract(post.payload, '$.metadata.project_id')
                WHERE post.collection = 'blackboard_posts' AND json_extract(post.payload, '$.post_type') = 'marketplace_signal'
                    AND substr(json_extract(post.payload, '$.task_id'), 1, 7) = 'signal_'
                    AND json_extract(post.payload, '$.scope') = 'project'
                    AND json_extract(post.payload, '$.permission') = 'project_visible'
                    AND json_extract(post.payload, '$.status') = 'published'
                    AND json_extract(owner.payload, '$.status') = 'active' AND owner.id != ?
                    AND json_extract(owner.payload, '$.workspace_id') = ?
                    AND json_extract(post.payload, '$.metadata.workspace_id') = json_extract(owner.payload, '$.workspace_id')
                    AND json_extract(project.payload, '$.workspace_id') = ?
                    AND json_extract(project.payload, '$.status') = 'active'
                    AND (json_array_length(project.payload, '$.member_ids') = 0 OR EXISTS (
                        SELECT 1 FROM json_each(project.payload, '$.member_ids') WHERE value = ?))
                    AND (json_array_length(project.payload, '$.member_ids') = 0 OR EXISTS (
                        SELECT 1 FROM json_each(project.payload, '$.member_ids') WHERE value = owner.id))
                    AND post.created_order > ? ORDER BY post.created_order""",
            (user.id, user.workspace_id, user.workspace_id, user.id), BlackboardPost, limit,
        )

    def knowledge_snapshot(self, user: User, project_id: str, *, query_terms: tuple[str, ...] = ()) -> ScoutKnowledge | None:
        return MarketScoutMaterials(self.store).prepare(user, project_id, query_terms=query_terms)

    def current(self, receipt: MarketScoutReceiptV1, user: User, post: BlackboardPost,
                query_terms: tuple[str, ...], client: ChatLLM | None) -> bool:
        with closing(self.store._read_connect()) as connection:
            row = connection.execute("SELECT payload FROM records WHERE collection = 'market_scout_receipts' AND id = ?",
                                     (receipt.id,)).fetchone()
        current = MarketScoutReceiptV1.model_validate_json(row['payload']) if row else None
        if (current is None or current.status != 'matching' or current.claim_id != receipt.claim_id
            or current.process_epoch != self.epoch or current.lease_expires_at is None
            or current.lease_expires_at <= now_utc()):
            return False
        knowledge = self.knowledge_snapshot(user, post.metadata['project_id'], query_terms=query_terms)
        latest_post = self.store.get_blackboard_post(post.id)
        return bool(knowledge is not None and latest_post is not None
                    and self.fingerprint(knowledge.actor, latest_post, knowledge.proof_hash, client) == receipt.fingerprint)

    def fingerprint(self, user: User, post: BlackboardPost, knowledge_hash: str, client) -> str | None:
        helper = self.store.get_user(user.id)
        needer_id = post.task_id.removeprefix("signal_")
        needer = self.store.get_user(needer_id)
        project = self.store.get_project(post.metadata.get("project_id", ""))
        if (
            helper is None or needer is None or project is None
            or post.post_type != 'marketplace_signal' or not post.task_id.startswith('signal_')
            or helper.id == needer.id or post.scope != 'project'
            or post.permission != 'project_visible' or post.status != 'published'
            or helper.status != "active" or needer.status != "active" or project.status != "active"
            or helper.workspace_id != needer.workspace_id or helper.workspace_id != project.workspace_id
            or (project.member_ids and (helper.id not in project.member_ids or needer.id not in project.member_ids))
            or post.metadata.get("workspace_id") != helper.workspace_id
        ):
            return None
        participations = [self.store.get_market_participation(identifier) for identifier in (helper.id, needer.id)]
        if any(record is not None and not record.enabled for record in participations):
            return None
        model_id = resolve_agent_model_id(self.store, helper)
        model = self.store.get_model_definition(model_id)
        with closing(self.store._connect()) as connection:
            rows = connection.execute(
                """SELECT payload FROM records WHERE collection = 'consent_grants'
                    AND (json_extract(payload, '$.grantor_id') = ? AND json_extract(payload, '$.grantee_id') = ?
                        OR json_extract(payload, '$.grantor_id') = ? AND json_extract(payload, '$.grantee_id') = ?)
                    ORDER BY created_order""", (helper.id, needer.id, needer.id, helper.id),
            ).fetchall()
            rules = connection.execute(
                "SELECT payload FROM records WHERE collection = 'permission_policy_rules' ORDER BY id",
            ).fetchall()
        return canonical_json_sha256({
            "source": {"id": post.id, "content": post.content, "scope": post.scope, "metadata": post.metadata},
            "knowledge_hash": knowledge_hash, "policy": MATCHING_POLICY_VERSION,
            "model": {"id": model_id, "definition": model.model_dump(mode="json") if model else None,
                      "client": _model_identity(client)},
            "authorization": {
                "helper": helper.model_dump(mode="json"), "needer": needer.model_dump(mode="json"),
                "project": project.model_dump(mode="json"),
                "participation": [record.model_dump(mode="json") if record else None for record in participations],
                "consents": [json.loads(row["payload"]) for row in rows],
                "rules": [json.loads(row["payload"]) for row in rules],
            },
        })

    def claim(self, user: User, post: BlackboardPost, fingerprint: str, *, at: datetime | None = None):
        at = at or now_utc()
        receipt_id = "market_scout_" + canonical_json_sha256([user.id, post.id])
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = 'market_scout_receipts' AND id = ?", (receipt_id,),
            ).fetchone()
            current = MarketScoutReceiptV1.model_validate_json(row["payload"]) if row else None
            if current:
                if current.status in {"matching", "delivering"}:
                    if current.process_epoch == self.epoch and current.lease_expires_at > at:
                        return None
                    if current.status == "delivering":
                        current.status, current.last_error_code = "indeterminate", "market_delivery_requires_reconciliation"
                        current.updated_at = at
                        self._save(connection, current)
                        return None
                if current.status == "indeterminate":
                    return None
                if current.fingerprint == fingerprint and (
                    current.status in {"processed", "blocked"} or current.next_retry_at is not None and current.next_retry_at > at
                ):
                    return None
            receipt = MarketScoutReceiptV1(
                id=receipt_id, helper_id=user.id, workspace_id=user.workspace_id,
                project_id=post.metadata.get('project_id'),
                post_id=post.id, fingerprint=fingerprint, status="matching",
                attempts=current.attempts + 1 if current and current.fingerprint == fingerprint else 1,
                claim_id=uuid4().hex, process_epoch=self.epoch, lease_expires_at=at + timedelta(minutes=10), updated_at=at,
            )
            self._save(connection, receipt)
        return receipt

    @staticmethod
    def _save(connection, receipt):
        connection.execute(
            """INSERT INTO records(collection, id, payload) VALUES ('market_scout_receipts', ?, ?)
                ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload""",
            (receipt.id, receipt.model_dump_json()),
        )

    def settle(self, receipt: MarketScoutReceiptV1, *, status: str, outcome=None, error_code=None, inbox_id=None) -> bool:
        at = now_utc()
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = 'market_scout_receipts' AND id = ?", (receipt.id,),
            ).fetchone()
            current = MarketScoutReceiptV1.model_validate_json(row["payload"]) if row else None
            if current is None or current.claim_id != receipt.claim_id:
                return False
            updated = current.model_copy(update={
                "status": status, "outcome": outcome, "last_error_code": error_code, "inbox_item_id": inbox_id,
                "updated_at": at,
            })
            if status != "delivering":
                updated.claim_id = updated.process_epoch = updated.lease_expires_at = None
            if status == "retry_wait":
                updated.next_retry_at = at + timedelta(seconds=5 if updated.attempts == 1 else 30 if updated.attempts == 2 else 300)
            self._save(connection, updated)
        return True

    def queue_health(self, *, workspace_id: str | None = None, project_id: str | None = None,
                     helper_id: str | None = None) -> dict[str, object]:
        query = """FROM records WHERE collection = 'market_scout_receipts'
            AND (? IS NULL OR json_extract(payload, '$.workspace_id') = ?)
            AND (? IS NULL OR json_extract(payload, '$.project_id') = ?)
            AND (? IS NULL OR json_extract(payload, '$.helper_id') = ?)"""
        parameters = (workspace_id, workspace_id, project_id, project_id, helper_id, helper_id)
        with closing(self.store._connect()) as connection, connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT json_extract(payload, '$.status') status, COUNT(*) count " + query + " GROUP BY status",
                parameters,
            ).fetchall()
            error = connection.execute(
                "SELECT json_extract(payload, '$.last_error_code') code " + query
                + " AND json_extract(payload, '$.last_error_code') IS NOT NULL"
                + " ORDER BY julianday(json_extract(payload, '$.updated_at')) DESC LIMIT 1",
                parameters,
            ).fetchone()
        return {"counts": {row["status"]: row["count"] for row in rows}, "last_error_code": error["code"] if error else None}
