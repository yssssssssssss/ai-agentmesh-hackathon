"""Current authority and identities for Agent memory binding configuration."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

from fastapi import HTTPException
from pydantic import BaseModel

from agentmesh.models import Agent, AgentMemoryBinding, PermissionPolicyRule, Project, User, UserRole, now_utc
from agentmesh.permissions import ACTION_MANAGE_PUBLIC_AGENT, ensure_can_manage_agent
from agentmesh.store import MemoryContextConflict

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore


def _record[Record: BaseModel](connection: sqlite3.Connection, collection: str, key: str,
                              model: type[Record]) -> Record | None:
    row = connection.execute('SELECT payload FROM records WHERE collection = ? AND id = ?',
                             (collection, key)).fetchone()
    if row is None:
        return None
    try:
        item = model.model_validate_json(row['payload'])
    except ValueError:
        raise HTTPException(409, 'memory_binding_integrity_failed') from None
    if item.id != key:
        raise HTTPException(409, 'memory_binding_integrity_failed')
    return item


class AgentMemoryBindingService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    @staticmethod
    def _authorize(connection: sqlite3.Connection, agent_id: str, user: User) -> Agent:
        actor = _record(connection, 'users', user.id, User)
        if (actor is None or actor.status != 'active' or actor.workspace_id != user.workspace_id
            or actor.role not in set(UserRole)):
            raise HTTPException(403, 'Not allowed to manage this agent')
        agent = _record(connection, 'agents', agent_id, Agent)
        if agent is None or agent.workspace_id != actor.workspace_id:
            raise HTTPException(404, 'Agent not found')
        rows = connection.execute("""SELECT payload FROM records WHERE collection = 'permission_policy_rules'
            AND json_extract(payload, '$.role') = ? AND json_extract(payload, '$.action') = ?
            ORDER BY created_order""", (actor.role, ACTION_MANAGE_PUBLIC_AGENT)).fetchall()
        try:
            rules = [PermissionPolicyRule.model_validate_json(row['payload']) for row in rows]
        except ValueError:
            raise HTTPException(409, 'memory_binding_integrity_failed') from None
        ensure_can_manage_agent(actor, agent, rules)
        return agent

    def _binding(self, connection: sqlite3.Connection, agent_id: str) -> AgentMemoryBinding | None:
        try:
            return self.repository._memory_binding_in_transaction(connection, agent_id)
        except MemoryContextConflict:
            raise HTTPException(409, 'memory_binding_integrity_failed') from None

    def get(self, agent_id: str, user: User) -> AgentMemoryBinding | None:
        with closing(self.repository._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            self._authorize(connection, agent_id, user)
            return self._binding(connection, agent_id)

    def set(self, agent_id: str, request: AgentMemoryBinding, user: User) -> AgentMemoryBinding:
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            agent = self._authorize(connection, agent_id, user)
            for project_id in request.allowed_project_ids:
                project = _record(connection, 'projects', project_id, Project)
                if (project is None or project.workspace_id != agent.workspace_id or project.status != 'active'
                    or (project.member_ids and user.id not in project.member_ids)
                    or (agent.agent_type == 'personal' and project.member_ids
                        and agent.owner_user_id not in project.member_ids)):
                    raise HTTPException(404, 'Project not found')
            existing = self._binding(connection, agent_id)
            fields = request.model_dump(include={
                'allowed_scopes', 'allowed_memory_types', 'allowed_project_ids', 'max_results_per_query',
            })
            fields['type_policy_version'] = 1
            if existing is None:
                binding = AgentMemoryBinding(agent_id=agent_id, **fields)
                connection.execute('INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)',
                                   ('agent_memory_bindings', binding.id, binding.model_dump_json()))
            else:
                binding = existing.model_copy(update={**fields, 'updated_at': now_utc()})
                connection.execute("UPDATE records SET payload = ? WHERE collection = 'agent_memory_bindings' AND id = ?",
                                   (binding.model_dump_json(), existing.id))
            return binding

    def delete(self, agent_id: str, user: User) -> bool:
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            self._authorize(connection, agent_id, user)
            existing = self._binding(connection, agent_id)
            if existing is None:
                return False
            connection.execute("DELETE FROM records WHERE collection = 'agent_memory_bindings' AND id = ?",
                               (existing.id,))
            return True
