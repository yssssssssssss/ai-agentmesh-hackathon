"""Bounded publication inputs and an atomic current-authority commit.

The model runs outside SQLite. Its output cannot replace a newer publication or
survive a change to the frozen owner, opt-in, project, binding or source records.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.llm import normalize_model_id
from agentmesh.market_publication_inputs import save_publication_inputs
from agentmesh.memory_context.origin import document_reference_identity, memory_origin_available
from agentmesh.models import (
    Agent,
    AuditEvent,
    BlackboardPost,
    ChatThread,
    DocumentRecord,
    MarketParticipation,
    ModelDefinition,
    Project,
    Scope,
    Task,
    User,
    UserMemoryItem,
)
from agentmesh.store import MemoryContextConflict, SQLiteStore
from agentmesh.tool_runtime.guardrails import unsafe_tool_output_reason


def _record[T: BaseModel](connection: sqlite3.Connection, collection: str, key: str, model: type[T]) -> T | None:
    item = SQLiteStore._get_in_transaction(connection, collection, key, model)
    if item is not None and item.id != key:
        raise ValueError('market_publication_record_invalid')
    return item


def valid_signal_content(content: str) -> bool:
    if len(content) > 2400 or unsafe_tool_output_reason(content) is not None:
        return False
    lines = content.splitlines()
    return len(lines) == 3 and all(
        line.startswith(label + '：') and 0 < len(line.removeprefix(label + '：').strip()) <= 800
        for line, label in zip(lines, ('能力', '可提供', '需要'), strict=True)
    )


@dataclass(frozen=True)
class MarketPublicationSnapshot:
    actor: User
    project: Project
    memory: list[UserMemoryItem]
    tasks: list[Task]
    proof_hash: str
    inputs: frozenset[tuple[str, str]]


class MarketPublishingService:
    def __init__(self, repository: SQLiteStore):
        self.store = repository

    def _capture(self, connection: sqlite3.Connection, user: User) -> MarketPublicationSnapshot | None:
        actor = _record(connection, 'users', user.id, User)
        project = _record(connection, 'projects', actor.default_project_id, Project) if actor else None
        agent = _record(connection, 'agents', actor.personal_agent_id, Agent) if actor else None
        participation = _record(connection, 'market_participation', user.id, MarketParticipation)
        if (actor is None or project is None or agent is None or participation is None
            or actor.status != 'active' or actor.workspace_id != user.workspace_id
            or project.status != 'active' or project.workspace_id != actor.workspace_id
            or (project.member_ids and actor.id not in project.member_ids)
            or agent.agent_type != 'personal' or agent.status != 'online'
            or agent.owner_user_id != actor.id or agent.workspace_id != actor.workspace_id
            or participation.user_id != actor.id or not participation.enabled):
            return None
        binding = self.store._memory_binding_in_transaction(connection, agent.id)
        model = _record(connection, 'model_definitions', normalize_model_id(agent.model_id), ModelDefinition)
        if model is not None and not model.enabled:
            return None
        previous = _record(connection, 'blackboard_posts', f'bb_signal_{actor.id}', BlackboardPost)
        if previous is not None and (previous.post_type != 'marketplace_signal' or previous.task_id != f'signal_{actor.id}'):
            return None

        memory: list[UserMemoryItem] = []
        source_inputs: dict[str, str] = {}
        size = 0
        maximum = min(8, max(0, binding.max_results_per_query)) if binding else 8
        types = binding.effective_memory_types if binding else None
        type_filter = json.dumps(sorted(types)) if types is not None else None
        if binding is None or (
            Scope.PRIVATE in (binding.allowed_scopes or [Scope.PRIVATE])
            and (not binding.allowed_project_ids or project.id in binding.allowed_project_ids)
        ):
            rows = connection.execute("""SELECT id, payload FROM records WHERE collection = 'user_memory_items'
                AND json_extract(payload, '$.user_id') = ? AND json_extract(payload, '$.workspace_id') = ?
                AND (json_extract(payload, '$.project_id') = ? OR json_extract(payload, '$.project_id') IS NULL)
                AND json_extract(payload, '$.scope') = 'private' AND json_extract(payload, '$.status') = 'active'
                AND json_extract(payload, '$.sensitivity') = 'normal' AND json_extract(payload, '$.archived_at') IS NULL
                AND json_extract(payload, '$.facts') IS NULL AND json_extract(payload, '$.procedure') IS NULL
                AND (? IS NULL OR COALESCE(json_extract(payload, '$.memory_type'), 'note')
                     IN (SELECT value FROM json_each(?)))
                AND length(payload) <= 32000
                ORDER BY created_order DESC LIMIT 32""",
                (actor.id, actor.workspace_id, project.id, type_filter, type_filter)).fetchall()
            for row in rows:
                item = UserMemoryItem.model_validate_json(row['payload'])
                origin_proof: dict[str, str] = {}
                if item.id != row['id']:
                    raise ValueError('market_publication_record_invalid')
                cost = len(item.title) + len(item.summary)
                if (len(memory) >= maximum or len(item.title) > 120 or len(item.summary) > 2000
                    or len(item.sources) > 8 or size + cost > 16000
                    # Private peer answers and personal rollups are not public signal material.
                    or item.source_kind in {'delegated_answer', 'daily_summary', 'short_term_rollup', 'project_archive'}
                    or any(source.source_type == 'delegated_answer' or source.reference.startswith('delegated-query://')
                           for source in item.sources)
                    or (binding and not binding.allows_memory_type(item.memory_type))
                    or not memory_origin_available(connection, item, require_document_version=True, proof=origin_proof)
                    or unsafe_tool_output_reason(item.model_dump_json()) is not None):
                    continue
                memory.append(item)
                source_inputs.update({key.removeprefix('sources/'): value for key, value in origin_proof.items()
                                      if key.startswith('sources/')})
                size += cost

        task_rows = connection.execute("""SELECT t.id, t.payload FROM records t JOIN records c
            ON c.collection = 'chat_threads' AND c.id = json_extract(t.payload, '$.thread_id')
            WHERE t.collection = 'tasks' AND json_extract(c.payload, '$.user_id') = ?
                AND json_extract(c.payload, '$.id') = c.id
                AND json_extract(c.payload, '$.workspace_id') = ? AND json_extract(c.payload, '$.project_id') = ?
                AND json_extract(c.payload, '$.status') = 'active'
                AND json_extract(t.payload, '$.management.archived_at') IS NULL AND length(t.payload) <= 65536
                AND (json_extract(t.payload, '$.management.project_id') IS NULL
                     OR json_extract(t.payload, '$.management.project_id') = ?)
            ORDER BY t.created_order DESC LIMIT 32""", (actor.id, actor.workspace_id, project.id, project.id)).fetchall()
        tasks = []
        for row in task_rows:
            item = Task.model_validate_json(row['payload'])
            if item.id != row['id']:
                raise ValueError('market_publication_record_invalid')
            if len(tasks) < 8 and len(item.title) <= 120 and unsafe_tool_output_reason(item.title) is None:
                tasks.append(item)
        if not memory and not tasks:
            return None
        threads: dict[str, ChatThread] = {}
        for item in tasks:
            if item.thread_id not in threads:
                thread = _record(connection, 'chat_threads', item.thread_id, ChatThread)
                if thread is None:
                    return None
                threads[thread.id] = thread
        documents: dict[str, str] = {}
        for item in memory:
            for source in item.sources:
                identity = document_reference_identity(source.reference)
                if identity is not None and identity[0] not in documents:
                    document = _record(connection, 'documents', identity[0], DocumentRecord)
                    if document is None:
                        return None
                    documents[document.id] = canonical_json_sha256(document.model_dump(mode='json'))
        records = [actor, project, agent, participation, binding, model, previous, *memory, *tasks,
                   *threads.values()]
        digest = canonical_json_sha256({'records': [item.model_dump(mode='json') if item else None for item in records],
                                        'documents': documents, 'sources': source_inputs})
        inputs = frozenset({('users', actor.id), ('projects', project.id), ('agents', agent.id),
                            ('market_participation', actor.id), ('agent_memory_bindings', agent.id),
                            ('model_definitions', normalize_model_id(agent.model_id)),
                            *(('user_memory_items', item.id) for item in memory),
                            *(('tasks', item.id) for item in tasks),
                            *(('chat_threads', key) for key in threads),
                            *(('documents', key) for key in documents)})
        inputs |= frozenset(('sources', key) for key in source_inputs)
        return MarketPublicationSnapshot(actor, project, memory, tasks, digest, inputs)

    def _read(self, connection: sqlite3.Connection, user: User) -> MarketPublicationSnapshot | None:
        try:
            return self._capture(connection, user)
        except (ValidationError, ValueError, MemoryContextConflict):
            return None

    def prepare(self, user: User) -> MarketPublicationSnapshot | None:
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            return self._read(connection, user)

    def current(self, snapshot: MarketPublicationSnapshot) -> bool:
        current = self.prepare(snapshot.actor)
        return current is not None and current.proof_hash == snapshot.proof_hash

    def commit(self, snapshot: MarketPublicationSnapshot, content: str, *, actor: str) -> BlackboardPost | None:
        if not valid_signal_content(content):
            return None
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self._read(connection, snapshot.actor)
            if current is None or current.proof_hash != snapshot.proof_hash:
                return None
            post = BlackboardPost(id=f'bb_signal_{current.actor.id}', task_id=f'signal_{current.actor.id}',
                post_type='marketplace_signal', actor=actor, title=f'{current.actor.name} 的协作信号', content=content,
                scope='project', permission='project_visible', read_by_agents=[actor],
                metadata={'workspace_id': current.actor.workspace_id, 'project_id': current.project.id,
                          'publication_hash': snapshot.proof_hash})
            self.store._upsert_plain_record(connection, 'blackboard_posts', post)
            self.store._sync_fts(connection, 'blackboard_posts', post)
            self.store.vector_index.prepare(connection, 'blackboard_posts', post.id, f'{post.title} {post.content}')
            save_publication_inputs(connection, post.id, current.inputs)
            self.store._upsert_plain_record(connection, 'audit_events', AuditEvent(actor=actor,
                action='publish_marketplace_signal', target_type='blackboard_post', target_id=post.id,
                workspace_id=current.actor.workspace_id, project_id=current.project.id,
                metadata={'user': current.actor.id}))
        return post
