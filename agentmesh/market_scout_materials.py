"""Bounded private material for one current market signal project."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass

from pydantic import BaseModel

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.llm import normalize_model_id
from agentmesh.memory_context.origin import memory_origin_available
from agentmesh.memory_context.search_filter import MemorySearchFilter
from agentmesh.models import Agent, ChatThread, MemoryLayer, ModelDefinition, Project, Scope, Task, User, UserMemoryItem
from agentmesh.store import MemoryContextConflict, SQLiteStore
from agentmesh.tool_runtime.guardrails import unsafe_tool_output_reason


@dataclass(frozen=True)
class ScoutKnowledge:
    actor: User
    capabilities: str
    proof_hash: str


def _record[Record: BaseModel](connection: sqlite3.Connection, collection: str, key: str,
                              model: type[Record]) -> Record | None:
    item = SQLiteStore._get_in_transaction(connection, collection, key, model)
    if item is not None and item.id != key:
        raise ValueError('market_matching_record_invalid')
    return item


class MarketScoutMaterials:
    def __init__(self, repository: SQLiteStore):
        self.store = repository

    def prepare(self, user: User, project_id: str, *, query_terms: tuple[str, ...] = ()) -> ScoutKnowledge | None:
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            try:
                return self._prepare(connection, user, project_id, query_terms)
            except (ValueError, MemoryContextConflict):
                return None

    def _prepare(self, connection: sqlite3.Connection, user: User, project_id: str,
                 query_terms: tuple[str, ...]) -> ScoutKnowledge | None:
        actor = _record(connection, 'users', user.id, User)
        project = _record(connection, 'projects', project_id, Project)
        agent = _record(connection, 'agents', actor.personal_agent_id, Agent) if actor else None
        if (actor is None or actor.status != 'active' or actor.workspace_id != user.workspace_id
            or project is None or project.workspace_id != actor.workspace_id or project.status != 'active'
            or (project.member_ids and actor.id not in project.member_ids)
            or agent is None or agent.agent_type != 'personal' or agent.status != 'online'
            or agent.owner_user_id != actor.id or agent.workspace_id != actor.workspace_id):
            return None
        binding = self.store._memory_binding_in_transaction(connection, agent.id)
        model = _record(connection, 'model_definitions', normalize_model_id(agent.model_id), ModelDefinition)
        if (model is not None and not model.enabled) or (binding and (
            Scope.PRIVATE not in binding.allowed_scopes
            or binding.allowed_project_ids and project.id not in binding.allowed_project_ids
        )):
            return None
        maximum = min(8, binding.max_results_per_query) if binding else 8
        binding_types = binding.effective_memory_types if binding else None
        types = frozenset(binding_types) if binding_types is not None else None
        memory_filter = MemorySearchFilter(actor.id, actor.workspace_id, project.id, frozenset(MemoryLayer), types)
        terms = tuple(sorted({term for term in query_terms if 1 <= len(term) <= 120},
                             key=lambda term: (-len(term), term))[:8])
        if terms:
            keys = []
            with self.store._fts_lock:
                for term in terms:
                    candidates = self.store._fts_match(connection, term, ['private'], '?', {'user_memory_items'},
                        workspace_id=actor.workspace_id, user_id=actor.id, memory_filter=memory_filter)
                    if not candidates:
                        candidates = self.store._fts_like_fallback(connection, term, ['private'], '?',
                            {'user_memory_items'}, workspace_id=actor.workspace_id, user_id=actor.id, memory_filter=memory_filter)
                    for row in candidates:
                        if row['record_id'] not in keys:
                            keys.append(row['record_id'])
                        if len(keys) >= 32:
                            break
                    if len(keys) >= 32:
                        break
        else:
            # Used only for a direct material read without a matching question.
            type_filter = json.dumps(sorted(types)) if types is not None else None
            rows = connection.execute("""SELECT id FROM records WHERE collection = 'user_memory_items'
                AND json_extract(payload, '$.user_id') = ? AND json_extract(payload, '$.workspace_id') = ?
                AND (json_extract(payload, '$.project_id') IS NULL OR json_extract(payload, '$.project_id') = ?)
                AND json_extract(payload, '$.scope') = 'private' AND json_extract(payload, '$.status') = 'active'
                AND json_extract(payload, '$.archived_at') IS NULL
                AND (? IS NULL OR COALESCE(json_extract(payload, '$.memory_type'), 'note')
                     IN (SELECT value FROM json_each(?)))
                ORDER BY created_order DESC LIMIT 32""",
                (actor.id, actor.workspace_id, project.id, type_filter, type_filter)).fetchall()
            keys = [row['id'] for row in rows]
        memories, origins = [], {}
        for key in keys:
            row = connection.execute("""SELECT payload FROM records WHERE collection = 'user_memory_items'
                AND id = ? AND length(payload) <= 32000""", (key,)).fetchone()
            if row is None:
                continue
            item = UserMemoryItem.model_validate_json(row['payload'])
            if (item.id != key or item.user_id != actor.id or item.workspace_id != actor.workspace_id
                or item.project_id not in {None, project.id} or item.scope is not Scope.PRIVATE
                or item.status != 'active' or item.archived_at is not None or item.facts or item.procedure
                or item.sensitivity not in {'normal', 'high'} or len(item.sources) > 8
                or types is not None and item.memory_type not in types
                or unsafe_tool_output_reason(item.title) is not None):
                continue
            proof = {}
            if (not memory_origin_available(connection, item, require_document_version=True, proof=proof)
                or len(origins.keys() | proof.keys()) > 64):
                continue
            memories.append(item)
            origins.update(proof)
            if len(memories) >= maximum:
                break
        task_filter = ''
        if terms:
            task_filter = ' AND (' + ' OR '.join("instr(lower(json_extract(t.payload, '$.title')), ?) > 0" for _ in terms) + ')'
        rows = connection.execute("""SELECT t.id, t.payload FROM records t JOIN records c
            ON c.collection = 'chat_threads' AND c.id = json_extract(t.payload, '$.thread_id')
            WHERE t.collection = 'tasks' AND json_extract(c.payload, '$.user_id') = ?
                AND json_extract(c.payload, '$.id') = c.id AND json_extract(c.payload, '$.workspace_id') = ?
                AND json_extract(c.payload, '$.project_id') = ? AND json_extract(c.payload, '$.status') = 'active'
                AND json_extract(t.payload, '$.management.archived_at') IS NULL AND length(t.payload) <= 65536
                AND (json_extract(t.payload, '$.management.project_id') IS NULL
                     OR json_extract(t.payload, '$.management.project_id') = ?)
            """ + task_filter + ' ORDER BY t.created_order DESC LIMIT 32',
            (actor.id, actor.workspace_id, project.id, project.id, *terms)).fetchall()
        tasks, threads = [], {}
        for row in rows:
            item = Task.model_validate_json(row['payload'])
            if item.id != row['id'] or unsafe_tool_output_reason(item.title) is not None:
                continue
            thread = _record(connection, 'chat_threads', item.thread_id, ChatThread)
            if thread is None:
                continue
            tasks.append(item)
            threads[thread.id] = thread
            if len(tasks) >= 8:
                break
        if not memories and not tasks:
            return None
        records = [actor, project, agent, binding, model, *memories, *tasks, *threads.values()]
        digest = canonical_json_sha256({'records': [record.model_dump(mode='json') if record else None for record in records],
                                       'origins': origins})
        return ScoutKnowledge(actor, '、'.join(item.title[:120] for item in [*memories, *tasks]), digest)
