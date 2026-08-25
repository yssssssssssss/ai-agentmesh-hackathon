from __future__ import annotations

import sqlite3
import threading

import pytest

from agentmesh.models import (
    MemoryItem,
    Scope,
    SkillCapabilityProfile,
    SkillCapabilityType,
    SkillDefinition,
    SkillLifecycleStage,
    SkillSourceScope,
)
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore


def _skill(
    name: str,
    *,
    title: str = "Catalog title",
    description: str = "Catalog description",
    aliases: list[str] | None = None,
    metadata: dict[str, str] | None = None,
) -> SkillDefinition:
    return SkillDefinition(
        id=f"skilldef_{name}",
        name=name,
        title=title,
        description=description,
        instructions="qxzjkpwvbnm",
        source_path="/private/qazwsxedcrfv/SKILL.md",
        source_scope=SkillSourceScope.WORKSPACE,
        content_hash=f"hash-{name}",
        aliases=aliases or [],
        metadata=metadata or {},
    )


def test_skill_definition_index_contains_only_directory_safe_fields(tmp_path, monkeypatch) -> None:
    indexed_texts: list[str] = []

    def embed(text: str, **_kwargs) -> list[float]:
        indexed_texts.append(text)
        return [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    repository = SQLiteStore(tmp_path / "safe-skill-index.sqlite3")
    skill = _skill(
        "name-safe-beacon",
        title="Title safe beacon",
        description="Description safe beacon",
        aliases=["alias-safe-beacon"],
        metadata={
            "short-description": "Short safe beacon",
            "agentmesh-stage": "review",
            "owner_user_id": "plmoknijbuhv",
            "source": "metadata-source-qazwsxedcrfv",
            "arbitrary": "mnbvcxzlkjhg",
        },
    )

    repository.save_skill_definition(skill)

    with repository._connect() as connection:
        row = connection.execute(
            "SELECT title, body, scope, user_id FROM records_fts WHERE collection = ? AND record_id = ?",
            ("skill_definitions", skill.id),
        ).fetchone()
    assert row is not None
    assert row["title"] == "Title safe beacon"
    assert row["body"] == (
        "name-safe-beacon Description safe beacon alias-safe-beacon Short safe beacon review"
    )
    assert row["scope"] == Scope.PROJECT.value
    assert row["user_id"] == ""
    assert indexed_texts == [f'{row["title"]} {row["body"]}']
    indexed_projection = " ".join(indexed_texts)
    assert "qxzjkpwvbnm" not in indexed_projection
    assert "qazwsxedcrfv" not in indexed_projection
    assert "plmoknijbuhv" not in indexed_projection
    assert "mnbvcxzlkjhg" not in indexed_projection


def test_skill_definition_index_excludes_boundary_examples(tmp_path, monkeypatch) -> None:
    indexed_texts: list[str] = []

    def embed(text: str, **_kwargs) -> list[float]:
        indexed_texts.append(text)
        return [1.0, 0.0] if "qxzjkvbnm" in text else [0.0, 1.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    repository = SQLiteStore(tmp_path / "skill-boundary-index.sqlite3")
    skill = _skill(
        "positive-skill",
        description="Handles the primary workflow. Boundary: qxzjkvbnm belongs elsewhere.",
    )

    repository.save_skill_definition(skill)

    with repository._connect() as connection:
        row = connection.execute(
            "SELECT body FROM records_fts WHERE collection = ? AND record_id = ?",
            ("skill_definitions", skill.id),
        ).fetchone()
    assert row is not None
    assert "qxzjkvbnm" not in row["body"]
    assert "qxzjkvbnm" not in indexed_texts[0]

    fts_ids, vector_ids, _diagnostics = repository.rank_skill_definitions(
        "qxzjkvbnm",
        {skill.id},
    )
    assert fts_ids == []
    assert vector_ids == []


def test_catalog_reload_rebuilds_unchanged_legacy_skill_search_projection(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", False)
    skill_root = tmp_path / "workspace-skills"
    skill_dir = skill_root / "migration-skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: migration-skill\n"
        "description: Handles design cleanup. Boundary: staleboundarybeacon belongs elsewhere.\n"
        "---\n"
        "# Migration Skill\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTMESH_SKILL_PATHS", str(skill_root))
    repository = SQLiteStore(tmp_path / "legacy-skill-index.sqlite3")
    catalog = SkillCatalogService(repository)
    catalog.reload()
    skill = catalog.get_by_name("migration-skill")
    assert skill is not None
    with repository._connect() as connection:
        connection.execute(
            "UPDATE records_fts SET body = ? WHERE collection = ? AND record_id = ?",
            (
                "migration-skill Handles design cleanup Boundary staleboundarybeacon belongs elsewhere",
                "skill_definitions",
                skill.id,
            ),
        )

    legacy_ids, _vector_ids, _diagnostics = repository.rank_skill_definitions(
        "staleboundarybeacon",
        {skill.id},
    )
    assert legacy_ids == [skill.id]

    catalog.reload()

    current_ids, _vector_ids, _diagnostics = repository.rank_skill_definitions(
        "staleboundarybeacon",
        {skill.id},
    )
    assert current_ids == []


@pytest.mark.parametrize(
    "query",
    [
        "name-search-beacon",
        "title-search-beacon",
        "description-search-beacon",
        "alias-search-beacon",
        "short-search-beacon",
        "delivery",
    ],
)
def test_rank_skill_definitions_searches_only_allowlisted_catalog_fields(tmp_path, monkeypatch, query: str) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", False)
    repository = SQLiteStore(tmp_path / "skill-field-ranking.sqlite3")
    skill = _skill(
        "name-search-beacon",
        title="title-search-beacon",
        description="description-search-beacon",
        aliases=["alias-search-beacon"],
        metadata={
            "short-description": "short-search-beacon",
            "agentmesh-stage": "delivery",
            "owner_user_id": "owner-search-beacon",
        },
    )
    repository.save_skill_definition(skill)

    fts_ids, vector_ids, diagnostics = repository.rank_skill_definitions(query, {skill.id})

    assert fts_ids == [skill.id]
    assert vector_ids == []
    assert diagnostics == ["embedding_unavailable"]


@pytest.mark.parametrize(
    "query",
    [
        "qxzjkpwvbnm",
        "qazwsxedcrfv",
        "plmoknijbuhv",
        "mnbvcxzlkjhg",
    ],
)
def test_rank_skill_definitions_does_not_search_private_or_arbitrary_fields(tmp_path, monkeypatch, query: str) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", False)
    repository = SQLiteStore(tmp_path / "skill-private-fields.sqlite3")
    skill = _skill(
        "safe-name",
        metadata={
            "owner_user_id": "plmoknijbuhv",
            "arbitrary": "mnbvcxzlkjhg",
        },
    )
    repository.save_skill_definition(skill)

    fts_ids, vector_ids, _diagnostics = repository.rank_skill_definitions(query, {skill.id})

    assert fts_ids == []
    assert vector_ids == []


def test_rank_skill_definitions_limits_fts_and_vectors_to_allowed_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda _text, **_kwargs: [1.0, 0.0])
    repository = SQLiteStore(tmp_path / "allowed-skill-ranking.sqlite3")
    allowed = _skill("allowed-skill", description="shared lexical beacon")
    forbidden = _skill("forbidden-skill", description="shared lexical beacon")
    repository.save_skill_definition(allowed)
    repository.save_skill_definition(forbidden)

    fts_ids, vector_ids, diagnostics = repository.rank_skill_definitions(
        "shared lexical beacon",
        {allowed.id},
    )

    assert fts_ids == [allowed.id]
    assert vector_ids == [allowed.id]
    assert diagnostics == []


def test_rank_skill_definitions_ignores_vectors_without_ready_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda _text, **_kwargs: [1.0, 0.0])
    repository = SQLiteStore(tmp_path / "ready-skill-vectors.sqlite3")
    skill = _skill("vector-skill")
    repository.save_skill_definition(skill)
    with repository._connect() as connection:
        connection.execute(
            "UPDATE vector_states SET state = 'failed' WHERE collection = ? AND record_id = ?",
            ("skill_definitions", skill.id),
        )

    fts_ids, vector_ids, diagnostics = repository.rank_skill_definitions(
        "semantic-only-query",
        {skill.id},
    )

    assert fts_ids == []
    assert vector_ids == []
    assert diagnostics == []


def test_rank_skill_definitions_filters_low_similarity_vectors(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)

    def embed(text: str, **_kwargs) -> list[float]:
        return [0.0, 1.0] if text == "semantic-only-query" else [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    repository = SQLiteStore(tmp_path / "low-similarity-skill-vectors.sqlite3")
    skill = _skill("vector-skill")
    repository.save_skill_definition(skill)

    fts_ids, vector_ids, diagnostics = repository.rank_skill_definitions(
        "semantic-only-query",
        {skill.id},
    )

    assert fts_ids == []
    assert vector_ids == []
    assert diagnostics == []


def test_rank_skill_definitions_redacts_user_input_before_embedding(tmp_path, monkeypatch) -> None:
    embedded_texts: list[str] = []

    def embed(text: str, **_kwargs) -> list[float]:
        embedded_texts.append(text)
        return [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    repository = SQLiteStore(tmp_path / "redacted-skill-query.sqlite3")
    skill = _skill("redaction-skill")
    repository.save_skill_definition(skill)
    embedded_texts.clear()

    repository.rank_skill_definitions("联系 user@example.com 做用户研究", {skill.id})

    assert embedded_texts == ["联系 [REDACTED_EMAIL] 做用户研究"]


@pytest.mark.parametrize("invalid_embedding", [["not-a-number"], [float("nan")], [True]])
def test_invalid_skill_embedding_marks_the_index_failed_without_raising(
    tmp_path,
    monkeypatch,
    invalid_embedding,
) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda _text, **_kwargs: invalid_embedding)
    repository = SQLiteStore(tmp_path / "invalid-skill-vector.sqlite3")
    skill = _skill("invalid-vector-skill")

    repository.save_skill_definition(skill)

    status = repository.get_vector_state("skill_definitions", skill.id)
    assert status is not None
    assert status.state == "failed"


def test_rank_skill_definitions_degrades_on_incompatible_vector_dimensions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda _text, **_kwargs: [1.0, 0.0])
    repository = SQLiteStore(tmp_path / "incompatible-skill-vector.sqlite3")
    skill = _skill("dimension-safe-skill")
    repository.save_skill_definition(skill)
    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda _text, **_kwargs: [1.0, 0.0, 0.0])

    _fts_ids, vector_ids, diagnostics = repository.rank_skill_definitions("semantic-only-query", {skill.id})

    assert vector_ids == []
    assert "embedding_incompatible" in diagnostics


def test_embedding_model_change_rebuilds_ready_skill_vectors(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    def embed(text: str, **_kwargs) -> list[float]:
        calls.append(text)
        return [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_MODEL", "model-a")
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_DIMENSIONS", 2)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    database = tmp_path / "skill-vector-model-change.sqlite3"
    repository = SQLiteStore(database)
    skill = _skill("model-change-skill")
    repository.save_skill_definition(skill)
    original = repository.get_vector_state("skill_definitions", skill.id)
    assert original is not None
    calls.clear()

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_MODEL", "model-b")
    reopened = SQLiteStore(database)
    worker = reopened._skill_vector_thread
    assert worker is not None
    worker.join(timeout=10)

    rebuilt = reopened.get_vector_state("skill_definitions", skill.id)
    assert rebuilt is not None
    assert rebuilt.state == "ready"
    assert rebuilt.content_hash != original.content_hash
    assert calls


def test_embedding_model_change_does_not_rebuild_general_knowledge_vectors(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    def embed(text: str, **_kwargs) -> list[float]:
        calls.append(text)
        return [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_MODEL", "model-a")
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_DIMENSIONS", 2)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    database = tmp_path / "general-vector-model-change.sqlite3"
    repository = SQLiteStore(database)
    memory = MemoryItem(
        id="memory_model_change",
        title="Stable knowledge vector",
        summary="This vector is not part of the Skill recommendation index.",
        memory_type="note",
        scope=Scope.TEAM_ACCEPTED,
        workspace_id="ws_test",
    )
    repository.add_memory_item(memory)
    original = repository.get_vector_state("memory_items", memory.id)
    assert original is not None
    assert original.state == "ready"
    calls.clear()

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_MODEL", "model-b")
    reopened = SQLiteStore(database)

    current = reopened.get_vector_state("memory_items", memory.id)
    assert current is not None
    assert current.state == "ready"
    assert current.content_hash == original.content_hash
    assert reopened.count_ready_vectors("memory_items", memory.id) == 1
    assert calls == []

    same_text_after_model_change = memory.model_copy(update={"id": "memory_model_change_later"})
    reopened.add_memory_item(same_text_after_model_change)
    later = reopened.get_vector_state("memory_items", same_text_after_model_change.id)
    assert later is not None
    assert later.state == "ready"
    assert later.content_hash == original.content_hash


def test_profile_vector_ranking_keeps_the_existing_no_threshold_semantics(tmp_path, monkeypatch) -> None:
    def embed(text: str, **_kwargs) -> list[float]:
        return [0.0, 1.0] if text == "semantic-only-query" else [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    repository = SQLiteStore(tmp_path / "profile-vector-threshold.sqlite3")
    skill = _skill("planner-profile-skill")
    profile = SkillCapabilityProfile(
        id=skill.id,
        skill_id=skill.id,
        skill_name=skill.name,
        skill_version=skill.version,
        skill_content_hash=skill.content_hash,
        profile_version="1",
        profile_content_hash="profile-hash",
        primary_stage=SkillLifecycleStage.PRE_DESIGN,
        capability_type=SkillCapabilityType.RESEARCH,
    )
    repository.save_skill_capability_profile(profile)

    _fts_ids, vector_ids, diagnostics = repository.rank_skill_profiles("semantic-only-query", {skill.id})

    assert vector_ids == [skill.id]
    assert diagnostics == []


def test_background_skill_index_skips_one_bad_record_and_retries_it_on_the_next_run(
    tmp_path,
    monkeypatch,
) -> None:
    def embed(text: str, **_kwargs):  # noqa: ANN202
        return ["not-a-number"] if "first-skill" in text else [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    repository = SQLiteStore(tmp_path / "background-skill-retry.sqlite3")
    first = _skill("first-skill")
    second = _skill("second-skill")
    repository.save_skill_definition(first, defer_vector=True)
    repository.save_skill_definition(second, defer_vector=True)

    repository.start_skill_vector_indexing()
    worker = repository._skill_vector_thread
    assert worker is not None
    worker.join(timeout=10)

    first_status = repository.get_vector_state("skill_definitions", first.id)
    second_status = repository.get_vector_state("skill_definitions", second.id)
    assert first_status is not None and first_status.state == "failed"
    assert second_status is not None and second_status.state == "ready"

    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda _text, **_kwargs: [1.0, 0.0])
    repository.start_skill_vector_indexing()
    retry_worker = repository._skill_vector_thread
    assert retry_worker is not None
    retry_worker.join(timeout=10)

    assert repository.get_vector_state("skill_definitions", first.id).state == "ready"


def test_active_skill_vector_rescan_retries_a_failure_from_the_same_worker(
    tmp_path,
    monkeypatch,
) -> None:
    first_attempt_started = threading.Event()
    allow_first_attempt_to_finish = threading.Event()
    attempts = 0

    def embed(_text: str, **_kwargs):  # noqa: ANN202
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_attempt_started.set()
            assert allow_first_attempt_to_finish.wait(timeout=10)
            return ["not-a-number"]
        return [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    repository = SQLiteStore(tmp_path / "active-skill-rescan.sqlite3")
    skill = _skill("active-rescan-skill")
    repository.save_skill_definition(skill, defer_vector=True)

    repository.start_skill_vector_indexing()
    worker = repository._skill_vector_thread
    assert worker is not None
    assert first_attempt_started.wait(timeout=10)

    repository.start_skill_vector_indexing()
    allow_first_attempt_to_finish.set()
    worker.join(timeout=10)

    status = repository.get_vector_state("skill_definitions", skill.id)
    assert status is not None
    assert status.state == "ready"
    assert attempts == 2


def test_background_skill_index_does_not_lose_a_rescan_request_at_worker_exit(
    tmp_path,
    monkeypatch,
) -> None:
    first_scan_started = threading.Event()
    allow_first_scan_to_finish = threading.Event()
    scan_count = 0
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    repository = SQLiteStore(tmp_path / "background-skill-rescan.sqlite3")

    def next_work():  # noqa: ANN202
        nonlocal scan_count
        scan_count += 1
        if scan_count == 1:
            first_scan_started.set()
            assert allow_first_scan_to_finish.wait(timeout=10)
        return None

    monkeypatch.setattr(repository, "_next_skill_vector_work", next_work)
    repository.start_skill_vector_indexing()
    first_worker = repository._skill_vector_thread
    assert first_worker is not None
    assert first_scan_started.wait(timeout=10)

    repository.start_skill_vector_indexing()
    allow_first_scan_to_finish.set()
    first_worker.join(timeout=10)

    assert scan_count == 2


def test_late_vector_failure_cannot_overwrite_a_ready_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", lambda _text, **_kwargs: [1.0, 0.0])
    repository = SQLiteStore(tmp_path / "late-vector-failure.sqlite3")
    skill = _skill("late-failure-skill")
    repository.save_skill_definition(skill, defer_vector=True)
    work = repository._next_skill_vector_work()
    assert work is not None

    repository.vector_index.process(work)
    repository.vector_index._finish_failed(work, "late failure")

    status = repository.get_vector_state("skill_definitions", skill.id)
    assert status is not None
    assert status.state == "ready"


def test_catalog_reload_indexes_skill_vectors_off_the_startup_thread(tmp_path, monkeypatch) -> None:
    caller_thread = threading.get_ident()
    embedding_threads: list[int] = []

    def embed(_text: str, **_kwargs) -> list[float]:
        embedding_threads.append(threading.get_ident())
        return [1.0, 0.0]

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", embed)
    repository = SQLiteStore(tmp_path / "background-skill-index.sqlite3")

    SkillCatalogService(repository).reload()
    worker = repository._skill_vector_thread
    assert worker is not None
    worker.join(timeout=10)

    assert len(repository.skill_definitions) == 84
    assert embedding_threads
    assert caller_thread not in embedding_threads


def test_catalog_reload_indexes_all_84_skill_definitions_including_pilots(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", False)
    repository = SQLiteStore(tmp_path / "complete-skill-definition-index.sqlite3")

    SkillCatalogService(repository).reload()

    with repository._connect() as connection:
        indexed_ids = {
            str(row["record_id"])
            for row in connection.execute(
                "SELECT record_id FROM records_fts WHERE collection = 'skill_definitions'"
            ).fetchall()
        }
    assert len(indexed_ids) == 84
    for name in ("competitive-analysis", "generate-research-plan", "prd-feasibility"):
        skill = repository.get_skill_definition_by_name(name)
        assert skill is not None
        assert skill.id in indexed_ids


def test_rank_skill_definitions_short_circuits_before_embedding_without_allowed_ids(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "empty-skill-ranking.sqlite3")

    def unexpected_embedding(_text: str) -> list[float]:
        raise AssertionError("embedding must not run without an authorized candidate set")

    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", True)
    monkeypatch.setattr("agentmesh.embedding.embed_text", unexpected_embedding)

    assert repository.rank_skill_definitions("catalog query", set()) == ([], [], [])


def test_skill_definition_index_is_excluded_from_general_knowledge_search(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", False)
    repository = SQLiteStore(tmp_path / "isolated-skill-index.sqlite3")
    repository.save_skill_definition(_skill("knowledge-isolation-beacon"))

    assert repository.search("knowledge-isolation-beacon", {Scope.PROJECT}) == []


def test_existing_skill_definitions_are_safely_backfilled_on_reopen(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentmesh.embedding.EMBEDDING_ENABLED", False)
    database = tmp_path / "skill-index-backfill.sqlite3"
    SQLiteStore(database)
    skill = _skill(
        "backfill-safe-beacon",
        metadata={
            "short-description": "backfill short beacon",
            "owner_user_id": "backfill-owner-secret",
        },
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
            ("skill_definitions", skill.id, skill.model_dump_json()),
        )

    reopened = SQLiteStore(database)

    with reopened._connect() as connection:
        row = connection.execute(
            "SELECT title, body FROM records_fts WHERE collection = ? AND record_id = ?",
            ("skill_definitions", skill.id),
        ).fetchone()
    assert row is not None
    assert "backfill-safe-beacon" in row["body"]
    assert "backfill short beacon" in row["body"]
    assert "backfill-owner-secret" not in row["body"]
    assert reopened.get_vector_state("skill_definitions", skill.id).state == "pending"
