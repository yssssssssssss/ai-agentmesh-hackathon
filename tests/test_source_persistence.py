from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest

from agentmesh.models import Source
from agentmesh.store import SQLiteStore


def test_concurrent_source_creation_preserves_one_identity(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'source-race.sqlite3')
    source = Source(id='src_racing_identity', title='Authorized evidence', source_type='web_page',
        reference='https://example.test/current', workspace_id='workspace', project_id='project',
        user_id='owner', run_id='run', skill_id='skill')
    competing = source.model_copy(update={'reference': 'https://example.test/replaced', 'user_id': 'other'})
    started = Barrier(2)
    read = Barrier(2)
    original_get = repository.get_source

    def synchronize_unprotected_read(source_id):
        value = original_get(source_id)
        if value is None:
            read.wait(timeout=5)
        return value

    # Reproduce both legacy callers observing absence before either write.
    # The fixed transaction does not depend on this out-of-transaction read.
    monkeypatch.setattr(repository, 'get_source', synchronize_unprotected_read)

    def create(value):
        started.wait(timeout=5)
        try:
            return repository.add_source(value)
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create, value) for value in (source, competing)]
        outcomes = [future.result(timeout=10) for future in futures]

    winners = [outcome for outcome in outcomes if isinstance(outcome, Source)]
    assert len(winners) == 1
    assert outcomes.count('source_identity_conflict') == 1
    assert original_get(source.id) == winners[0]
    repository.close()


def test_source_replay_preserves_first_record_after_reopen(tmp_path):
    path = tmp_path / 'source-replay.sqlite3'
    repository = SQLiteStore(path)
    source = repository.add_source(Source(id='src_replay', title='Evidence', source_type='web_page',
        reference='https://example.test/current'))
    replay = source.model_copy(update={'created_at': source.created_at + timedelta(minutes=1)})
    assert repository.add_source(replay) == source
    repository.close()

    reopened = SQLiteStore(path)
    assert reopened.add_source(replay) == source
    assert reopened.get_source(source.id) == source
    reopened.close()


def test_source_creation_rejects_mismatched_stored_record_identity(tmp_path):
    repository = SQLiteStore(tmp_path / 'source-mismatched-id.sqlite3')
    source = repository.add_source(Source(id='src_expected', title='Evidence', source_type='web_page',
        reference='https://example.test/current'))
    with repository._connect() as connection:
        connection.execute("UPDATE records SET payload = ? WHERE collection = 'sources' AND id = ?",
            (source.model_copy(update={'id': 'src_foreign'}).model_dump_json(), source.id))

    with pytest.raises(ValueError, match='source_identity_conflict'):
        repository.add_source(source)

    repository.close()
