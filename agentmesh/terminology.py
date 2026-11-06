"""Human-confirmed terminology subordinate to an existing authorized Project."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from pydantic import BaseModel, ConfigDict, Field

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_facts import MemoryFactsError, authorize_fact_project
from agentmesh.memory_payloads import Identity, ProjectTermAliasesV1, normalize_term_name
from agentmesh.models import AuditEvent, PermissionPolicyRule, Project, User, now_utc
from agentmesh.permissions import ACTION_MANAGE_TEAM_MEMORY, has_permission
from agentmesh.store import SQLiteStore


class TerminologyError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class TermAliasUpdateV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    command_id: Identity
    expected_version: int = Field(ge=0)
    aliases: dict[Identity, Identity] = Field(max_length=200)


def _normalized_aliases(aliases: dict[str, str], project_id: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, target in aliases.items():
        name, target = normalize_term_name(name), normalize_term_name(target)
        if len(f'{project_id}::{name}') > 120 or len(f'{project_id}::{target}') > 120:
            raise ValueError('term_name_invalid')
        if name == target or (name in result and result[name] != target):
            raise ValueError('term_alias_mapping_invalid')
        result[name] = target
    if any(target in result for target in result.values()):
        raise ValueError('term_alias_mapping_invalid')
    return dict(sorted(result.items()))


class ProjectTerminologyService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    @staticmethod
    def _project(connection: sqlite3.Connection, user: User, project_id: str) -> tuple[User, Project]:
        try:
            return authorize_fact_project(connection, user, project_id)
        except MemoryFactsError as error:
            raise TerminologyError(error.code, status_code=error.status_code) from error

    def get(self, project_id: str, user: User) -> ProjectTermAliasesV1:
        with closing(self.repository._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            _, project = self._project(connection, user, project_id)
            return project.term_aliases or ProjectTermAliasesV1(version=0)

    def update(self, project_id: str, request: TermAliasUpdateV1, user: User) -> ProjectTermAliasesV1:
        try:
            aliases = _normalized_aliases(request.aliases, project_id)
        except ValueError as error:
            raise TerminologyError('term_alias_mapping_invalid', status_code=422) from error
        request_hash = canonical_json_sha256({'project_id': project_id, 'aliases': aliases,
                                              'expected_version': request.expected_version})
        receipt_id = 'term_alias_command_' + canonical_json_sha256({'user_id': user.id, 'command': request.command_id})
        with closing(self.repository._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            actor, project = self._project(connection, user, project_id)
            rules = [PermissionPolicyRule.model_validate_json(row['payload']) for row in connection.execute(
                "SELECT payload FROM records WHERE collection = 'permission_policy_rules' ORDER BY created_order",
            ).fetchall()]
            if not has_permission(actor, ACTION_MANAGE_TEAM_MEMORY, rules):
                raise TerminologyError('terminology_manage_forbidden', status_code=403)
            row = connection.execute("SELECT payload FROM records WHERE collection = 'project_term_alias_commands' AND id = ?",
                                     (receipt_id,)).fetchone()
            if row:
                receipt = json.loads(row['payload'])
                if receipt['request_hash'] != request_hash:
                    raise TerminologyError('terminology_command_conflict')
                return ProjectTermAliasesV1.model_validate(receipt['result'])
            current = project.term_aliases or ProjectTermAliasesV1(version=0)
            if current.version != request.expected_version:
                raise TerminologyError('terminology_version_conflict')
            updated = ProjectTermAliasesV1(version=current.version + 1, aliases=aliases,
                                           confirmed_by=actor.id, confirmed_at=now_utc())
            project = project.model_copy(update={'term_aliases': updated, 'updated_at': updated.confirmed_at})
            self.repository._upsert_plain_record(connection, 'projects', project)
            connection.execute("INSERT INTO records(collection, id, payload) VALUES ('project_term_alias_commands', ?, ?)",
                               (receipt_id, json.dumps({'request_hash': request_hash, 'result': updated.model_dump(mode='json')},
                                                       ensure_ascii=False)))
            self.repository._upsert_plain_record(connection, 'audit_events', AuditEvent(
                actor=actor.id, action='project_term_aliases_confirmed', target_type='project', target_id=project.id,
                workspace_id=project.workspace_id, project_id=project.id,
                metadata={'version': updated.version, 'alias_count': len(updated.aliases), 'request_hash': request_hash},
            ))
            return updated
