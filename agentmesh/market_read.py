"""One current-project read snapshot for market projections.

Published scope is explicit. Legacy rows without project proof are never moved
with a participant's current default project. Private answers are read via Query.
"""
from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass

from agentmesh.memory_facts import MemoryFactsError, authorize_fact_project
from agentmesh.models import AuditEvent, BlackboardPost, Project, User
from agentmesh.store import SQLiteStore


@dataclass
class MarketReadSnapshot:
    actor: User
    project: Project
    users: dict[str, User]
    participants: set[str]
    signals: list[BlackboardPost]
    matches: list[AuditEvent]
    counts: dict[str, int]
    memory_count: int
    received_count: int
    given_count: int


def _member(alias: str) -> str:
    return f"(? = '[]' OR EXISTS (SELECT 1 FROM json_each(?) WHERE value = {alias}.id))"


def read_market(user: User, repository: SQLiteStore, *, project_id: str | None = None) -> MarketReadSnapshot:
    with closing(repository._read_connect()) as connection, connection:
        connection.execute('BEGIN')
        actor_row = connection.execute("SELECT payload FROM records WHERE collection = 'users' AND id = ?",
                                       (user.id,)).fetchone()
        if actor_row is None:
            raise MemoryFactsError('project_not_found', status_code=404)
        current = User.model_validate_json(actor_row['payload'])
        if current.id != user.id:
            raise MemoryFactsError('market_record_invalid')
        actor, project = authorize_fact_project(connection, user, project_id or current.default_project_id)
        members = json.dumps(project.member_ids)
        roster_query = f"""FROM records u WHERE u.collection = 'users'
            AND json_extract(u.payload, '$.workspace_id') = ?
            AND json_extract(u.payload, '$.status') = 'active' AND {_member('u')}"""
        roster_args = (actor.workspace_id, members, members)
        users = {}
        for row in connection.execute('SELECT u.id, u.payload ' + roster_query
                                      + ' ORDER BY CASE WHEN u.id = ? THEN 0 ELSE 1 END, u.created_order LIMIT 200',
                                      (*roster_args, actor.id)).fetchall():
            item = User.model_validate_json(row['payload'])
            if item.id != row['id']:
                raise MemoryFactsError('market_record_invalid')
            users[item.id] = item
        participant_query = roster_query + """
            AND EXISTS (SELECT 1 FROM records r WHERE r.collection = 'market_participation' AND r.id = u.id
                AND json_extract(r.payload, '$.user_id') = u.id AND json_extract(r.payload, '$.enabled') = 1)"""
        # Only roster members can appear in this bounded graph. Counts still cover the full project.
        participant_rows = connection.execute('SELECT u.id ' + participant_query
            + ' AND u.id IN (SELECT value FROM json_each(?))', (*roster_args, json.dumps(list(users)))).fetchall()
        participants = {row['id'] for row in participant_rows}
        signal_query = f"""FROM records s JOIN records u ON u.collection = 'users'
            AND u.id = substr(json_extract(s.payload, '$.task_id'), 8)
            WHERE s.collection = 'blackboard_posts' AND json_extract(s.payload, '$.post_type') = 'marketplace_signal'
              AND substr(json_extract(s.payload, '$.task_id'), 1, 7) = 'signal_'
              AND json_extract(s.payload, '$.metadata.workspace_id') = ?
              AND json_extract(s.payload, '$.metadata.project_id') = ?
              AND json_extract(s.payload, '$.scope') = 'project'
              AND json_extract(s.payload, '$.permission') = 'project_visible'
              AND json_extract(s.payload, '$.status') = 'published'
              AND json_extract(u.payload, '$.workspace_id') = ?
              AND json_extract(u.payload, '$.status') = 'active' AND {_member('u')}"""
        signal_args = (actor.workspace_id, project.id, actor.workspace_id, members, members)
        signal_rows = connection.execute('SELECT s.id, s.payload ' + signal_query
            + " ORDER BY julianday(json_extract(s.payload, '$.created_at')) DESC, s.created_order DESC LIMIT 200",
            signal_args).fetchall()
        signals = [BlackboardPost.model_validate_json(row['payload']) for row in signal_rows]
        match_query = f"""FROM records e
            JOIN records h ON h.collection = 'users' AND h.id = json_extract(e.payload, '$.metadata.helper')
            JOIN records n ON n.collection = 'users' AND n.id = json_extract(e.payload, '$.target_id')
            WHERE e.collection = 'audit_events' AND json_extract(e.payload, '$.action') = 'marketplace_match'
              AND json_extract(e.payload, '$.target_type') = 'user'
              AND json_extract(e.payload, '$.workspace_id') = ? AND json_extract(e.payload, '$.project_id') = ?
              AND json_extract(h.payload, '$.workspace_id') = ? AND json_extract(n.payload, '$.workspace_id') = ?
              AND json_extract(h.payload, '$.status') = 'active' AND json_extract(n.payload, '$.status') = 'active'
              AND h.id != n.id AND {_member('h')} AND {_member('n')}"""
        match_args = (actor.workspace_id, project.id, actor.workspace_id, actor.workspace_id,
                      members, members, members, members)
        match_rows = connection.execute('SELECT e.id, e.payload ' + match_query
            + " ORDER BY julianday(json_extract(e.payload, '$.created_at')) DESC, e.created_order DESC LIMIT 200",
            match_args).fetchall()
        matches = [AuditEvent.model_validate_json(row['payload']) for row in match_rows]
        if any(item.id != row['id'] for item, row in [*zip(signals, signal_rows, strict=True),
                                                     *zip(matches, match_rows, strict=True)]):
            raise MemoryFactsError('market_record_invalid')
        counts = {
            'signals': connection.execute('SELECT COUNT(*) ' + signal_query, signal_args).fetchone()[0],
            'matches': connection.execute('SELECT COUNT(*) ' + match_query, match_args).fetchone()[0],
            'participants': connection.execute('SELECT COUNT(*) ' + participant_query, roster_args).fetchone()[0],
            # Consent is owned configuration, not a project-wide disclosure.
            'consent_grants': connection.execute("""SELECT COUNT(*) FROM records c
                JOIN records u ON u.collection = 'users' AND u.id = json_extract(c.payload, '$.grantee_id')
                WHERE c.collection = 'consent_grants' AND json_extract(c.payload, '$.grantor_id') = ?
                  AND json_extract(c.payload, '$.workspace_id') = ? AND json_extract(c.payload, '$.project_id') = ?
                  AND json_extract(c.payload, '$.revoked_at') IS NULL
                  AND json_extract(u.payload, '$.workspace_id') = ? AND json_extract(u.payload, '$.status') = 'active'
                  AND """ + _member('u'), (actor.id, actor.workspace_id, project.id, actor.workspace_id,
                                          members, members)).fetchone()[0],
        }
        received = connection.execute('SELECT COUNT(*) ' + match_query + ' AND n.id = ?', (*match_args, actor.id)).fetchone()[0]
        given = connection.execute('SELECT COUNT(*) ' + match_query + ' AND h.id = ?', (*match_args, actor.id)).fetchone()[0]
        memory_count = connection.execute("""SELECT COUNT(*) FROM records WHERE collection = 'user_memory_items'
            AND json_extract(payload, '$.user_id') = ? AND json_extract(payload, '$.workspace_id') = ?
            AND (json_extract(payload, '$.project_id') IS NULL OR json_extract(payload, '$.project_id') = ?)
            AND json_extract(payload, '$.scope') = 'private' AND json_extract(payload, '$.status') = 'active'
            AND json_extract(payload, '$.archived_at') IS NULL""", (actor.id, actor.workspace_id, project.id)).fetchone()[0]
        return MarketReadSnapshot(actor, project, users, participants, signals, matches, counts, memory_count, received, given)
