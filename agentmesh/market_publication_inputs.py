"""Private dependencies of the one generated signal per user.

These rows are a publication projection, not a new memory or event system.
SQLite invalidates the projection even when a source writer uses raw SQL.
"""
from __future__ import annotations

import sqlite3


def _input_key(alias: str) -> str:
    # Bindings are optional and their record IDs are generated. Track the agent
    # key so creating the first binding also invalidates an earlier publication.
    return (f"CASE WHEN {alias}.collection = 'agent_memory_bindings' "
            f"THEN json_extract({alias}.payload, '$.agent_id') ELSE {alias}.id END")


def ensure_publication_input_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS market_publication_inputs (
        post_id TEXT NOT NULL, collection TEXT NOT NULL, record_id TEXT NOT NULL,
        PRIMARY KEY (post_id, collection, record_id))""")
    connection.execute("""CREATE INDEX IF NOT EXISTS idx_market_publication_input
        ON market_publication_inputs(collection, record_id, post_id)""")
    for event, aliases in (('INSERT', ('NEW',)), ('UPDATE', ('OLD', 'NEW')), ('DELETE', ('OLD',))):
        match = ' OR '.join(f"(collection = {alias}.collection AND record_id = {_input_key(alias)})"
                            for alias in aliases)
        affected = f'SELECT post_id FROM market_publication_inputs WHERE {match}'
        changed = 'OLD.payload != NEW.payload AND ' if event == 'UPDATE' else ''
        connection.execute(f"""CREATE TRIGGER IF NOT EXISTS market_publication_input_{event.lower()}
            AFTER {event} ON records WHEN {changed}EXISTS ({affected})
            BEGIN
                DELETE FROM records_fts WHERE collection = 'blackboard_posts' AND record_id IN ({affected});
                DELETE FROM records_vec WHERE collection = 'blackboard_posts' AND record_id IN ({affected});
                DELETE FROM vector_states WHERE collection = 'blackboard_posts' AND record_id IN ({affected});
                UPDATE records SET payload = json_set(payload, '$.status', 'withdrawn',
                    '$.title', '协作信号已撤回', '$.content', '')
                    WHERE collection = 'blackboard_posts' AND id IN ({affected})
                        AND json_extract(payload, '$.post_type') = 'marketplace_signal'
                        AND id = 'bb_signal_' || substr(json_extract(payload, '$.task_id'), 8);
                DELETE FROM market_publication_inputs WHERE post_id IN ({affected});
            END""")

    for event in ('UPDATE', 'DELETE'):
        fields = "'$.content', '$.title', '$.status', '$.task_id', '$.post_type', '$.scope', '$.permission', '$.metadata'"
        changed = (f'AND json_extract(OLD.payload, {fields}) IS NOT json_extract(NEW.payload, {fields})'
                   if event == 'UPDATE' else '')
        connection.execute(f"""CREATE TRIGGER IF NOT EXISTS market_publication_post_{event.lower()}
            AFTER {event} ON records WHEN OLD.collection = 'blackboard_posts' {changed}
            BEGIN DELETE FROM market_publication_inputs WHERE post_id = OLD.id; END""")

    # Never invent dependencies for previously generated aggregates. Startup
    # removes their public body; a later publication can select fresh material.
    legacy = """SELECT id FROM records WHERE collection = 'blackboard_posts'
        AND json_extract(payload, '$.post_type') = 'marketplace_signal'
        AND substr(json_extract(payload, '$.task_id'), 1, 7) = 'signal_'
        AND id = 'bb_signal_' || substr(json_extract(payload, '$.task_id'), 8)
        AND (json_extract(payload, '$.status') != 'published'
             OR NOT EXISTS (SELECT 1 FROM market_publication_inputs WHERE post_id = records.id)
             OR EXISTS (SELECT 1 FROM market_publication_inputs memory_input
                 JOIN records memory ON memory.collection = 'user_memory_items' AND memory.id = memory_input.record_id
                 JOIN json_each(memory.payload, '$.sources') citation
                 JOIN records source ON source.collection = 'sources'
                                    AND source.id = json_extract(citation.value, '$.id')
                 WHERE memory_input.post_id = records.id AND memory_input.collection = 'user_memory_items'
                   AND NOT EXISTS (SELECT 1 FROM market_publication_inputs source_input
                       WHERE source_input.post_id = records.id AND source_input.collection = 'sources'
                         AND source_input.record_id = source.id))
             OR EXISTS (SELECT 1 FROM market_publication_inputs document_input
                 JOIN records document ON document.collection = 'documents' AND document.id = document_input.record_id
                 JOIN records source ON source.collection = 'sources'
                                    AND source.id = json_extract(document.payload, '$.source.id')
                 WHERE document_input.post_id = records.id AND document_input.collection = 'documents'
                   AND NOT EXISTS (SELECT 1 FROM market_publication_inputs source_input
                       WHERE source_input.post_id = records.id AND source_input.collection = 'sources'
                         AND source_input.record_id = source.id))
             OR (EXISTS (SELECT 1 FROM market_publication_inputs memory_input
                         WHERE memory_input.post_id = records.id AND memory_input.collection = 'user_memory_items')
                 AND EXISTS (SELECT 1 FROM market_publication_inputs binding_input JOIN records binding
                    ON binding.collection = 'agent_memory_bindings'
                       AND json_extract(binding.payload, '$.agent_id') = binding_input.record_id
                    WHERE binding_input.post_id = records.id AND binding_input.collection = 'agent_memory_bindings'
                      AND COALESCE(json_array_length(binding.payload, '$.allowed_memory_types'), 0) > 0
                      AND json_extract(binding.payload, '$.type_policy_version') IS NOT 1)))"""
    for table in ('records_fts', 'records_vec', 'vector_states'):
        connection.execute(f"DELETE FROM {table} WHERE collection = 'blackboard_posts' AND record_id IN ({legacy})")
    connection.execute(f"""UPDATE records SET payload = json_set(payload, '$.status', 'withdrawn',
        '$.title', '协作信号已撤回', '$.content', '') WHERE collection = 'blackboard_posts' AND id IN ({legacy})""")


def save_publication_inputs(connection: sqlite3.Connection, post_id: str,
                            inputs: frozenset[tuple[str, str]]) -> None:
    connection.execute('DELETE FROM market_publication_inputs WHERE post_id = ?', (post_id,))
    connection.executemany('INSERT INTO market_publication_inputs(post_id, collection, record_id) VALUES (?, ?, ?)',
                           [(post_id, collection, record_id) for collection, record_id in sorted(inputs)])
