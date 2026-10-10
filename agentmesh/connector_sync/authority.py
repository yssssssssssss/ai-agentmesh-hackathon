"""Current authority for canonical connector observations, independent of a reader call."""
from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.connector_sync.contracts import ConnectorSyncCursorV1, ConnectorSyncError

if TYPE_CHECKING:
    from agentmesh.models import Source

_CANONICAL_SOURCE = re.compile(r'^src_connector_[0-9a-f]{32}$')


def connector_id(owner_id: str, workspace_id: str, project_id: str, provider: str, namespace: str) -> str:
    return 'connector_' + canonical_json_sha256({'owner': owner_id, 'workspace': workspace_id,
        'project': project_id, 'provider': provider, 'namespace': namespace})[:32]


def operator_binding_current(cursor: ConnectorSyncCursorV1) -> bool:
    if not cursor.operator_bound:
        return True
    # The configuration factory uses this service's reader protocol. Import at the
    # authority boundary, after module initialization; it performs no HTTP calls.
    from agentmesh.connector_sync.configuration import configured_reader

    try:
        reader = configured_reader(cursor.project_id, cursor.provider)
        return reader.namespace == cursor.namespace and reader.configuration_hash() == cursor.configuration_hash
    except (ConnectorSyncError, OSError, ValueError):
        return False


def connector_source_available(connection: sqlite3.Connection, source: Source) -> bool:
    if not _CANONICAL_SOURCE.fullmatch(source.id):
        return True
    snapshot = source.snapshot
    if snapshot is None:
        return False
    rows = connection.execute("SELECT id, payload FROM records WHERE collection = 'connector_sync_cursors' "
        "AND json_extract(payload, '$.owner_user_id') = ? AND json_extract(payload, '$.workspace_id') = ? "
        "AND json_extract(payload, '$.project_id') = ? AND json_extract(payload, '$.provider') = ? "
        "AND substr(?, 1, length(json_extract(payload, '$.namespace')) + 1) "
        "= json_extract(payload, '$.namespace') || ':' LIMIT 101",
        (source.user_id, source.workspace_id, source.project_id, snapshot.provider, snapshot.external_id)).fetchall()
    if len(rows) > 100:
        return False
    matching = []
    for row in rows:
        try:
            cursor = ConnectorSyncCursorV1.model_validate_json(row['payload'])
        except ValueError:
            return False
        if (cursor.id != row['id'] or cursor.id != connector_id(source.user_id, source.workspace_id,
            source.project_id, cursor.provider, cursor.namespace)
            or (cursor.owner_user_id, cursor.workspace_id, cursor.project_id, cursor.provider) != (
                source.user_id, source.workspace_id, source.project_id, snapshot.provider)):
            return False
        external_id = snapshot.external_id[len(cursor.namespace) + 1:]
        expected = 'src_connector_' + canonical_json_sha256({'connector': cursor.id, 'external_id': external_id})[:32]
        if source.id == expected and source.source_type == cursor.provider:
            matching.append(cursor)
    return (len(matching) == 1 and matching[0].enabled and matching[0].status != 'disabled'
            and operator_binding_current(matching[0]))
