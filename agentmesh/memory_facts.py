"""Explicit source-backed facts and temporal reads of existing Memory records."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Callable
from contextlib import closing
from datetime import datetime

from pydantic import BaseModel

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.memory_payloads import (
    FactAssertionV1,
    FactConflictV1,
    FactHitV1,
    FactQueryResultV1,
    FactQueryV1,
    FactRememberV1,
    MemoryEvidenceRefV1,
    MemoryFactV1,
    ProcedureDraftV1,
    ProcedureMemoryV1,
    ProcedureRunEvidenceV1,
    TermResolutionV1,
)
from agentmesh.models import (
    AuditEvent,
    DocumentRecord,
    MemoryItem,
    MemoryLayer,
    MemoryProvenanceV1,
    MemorySourceKind,
    Project,
    Scope,
    Task,
    TaskReviewStatus,
    TaskReviewV1,
    User,
    UserMemoryItem,
    now_utc,
)
from agentmesh.store import SQLiteStore, TaskReviewConflict
from agentmesh.tool_runtime.guardrails import unsafe_tool_output_reason

MAX_FACT_MEMORIES = 512
MULTI_VALUE_PREDICATES = frozenset({"participant", "constraint", "tag"})


class MemoryFactsError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def document_evidence_hash(document: DocumentRecord) -> str:
    return canonical_json_sha256({
        "schema_version": "document-fact-evidence-v1", "id": document.id, "version": document.version,
        "title": document.title, "text": document.text, "source": document.source.model_dump(mode="json"),
        "workspace_id": document.workspace_id, "project_id": document.project_id,
        "uploaded_by": document.uploaded_by,
    })


def normalized_subject_id(
    fact: FactAssertionV1 | FactQueryV1, project_id: str, aliases: dict[str, str] | None = None,
) -> str:
    if fact.subject_type != "term":
        return fact.subject_id
    prefix = f"{project_id}::"
    name = fact.subject_id.removeprefix(prefix)
    name = " ".join(unicodedata.normalize("NFC", name).casefold().split())
    result = prefix + (aliases or {}).get(name, name)
    if len(result) > 120 or result == prefix:
        raise MemoryFactsError("fact_subject_invalid", status_code=422)
    return result


def _record[Record: BaseModel](
    connection: sqlite3.Connection, collection: str, record_id: str, model: type[Record],
) -> Record | None:
    row = connection.execute(
        "SELECT payload FROM records WHERE collection = ? AND id = ?", (collection, record_id),
    ).fetchone()
    if row is None:
        return None
    item = model.model_validate_json(row["payload"])
    if item.id != record_id:
        raise MemoryFactsError("fact_record_integrity_failed")
    return item


def authorize_fact_project(connection: sqlite3.Connection, user: User, project_id: str) -> tuple[User, Project]:
    actor = _record(connection, "users", user.id, User)
    project = _record(connection, "projects", project_id, Project)
    if (
        actor is None or actor.status != "active" or actor.workspace_id != user.workspace_id
        or project is None or project.status != "active" or project.workspace_id != actor.workspace_id
        or (project.member_ids and actor.id not in project.member_ids)
    ):
        raise MemoryFactsError("project_not_found", status_code=404)
    return actor, project


def validate_fact_subject(connection: sqlite3.Connection, fact: FactAssertionV1 | FactQueryV1, project: Project) -> None:
    if fact.subject_type == "term":
        normalized_subject_id(fact, project.id)
        return
    valid = fact.subject_id == project.id
    if fact.subject_type == "user":
        subject = _record(connection, "users", fact.subject_id, User)
        # Subject lifecycle is independent of the caller's current authorization.
        valid = bool(subject and subject.workspace_id == project.workspace_id
                     and (not project.member_ids or subject.id in project.member_ids))
    elif fact.subject_type == "task":
        task = _record(connection, "tasks", fact.subject_id, Task)
        row = connection.execute(
            "SELECT 1 FROM task_operations_projection WHERE task_id = ? AND workspace_id = ? "
            "AND project_id = ? AND thread_kind = 'task'",
            (fact.subject_id, project.workspace_id, project.id),
        ).fetchone()
        valid = task is not None and row is not None
    if not valid:
        raise MemoryFactsError("fact_subject_not_found", status_code=404)


def confirmed_facts(
    connection: sqlite3.Connection, assertions: list[FactAssertionV1], *, project: Project,
    evidence_refs: list[MemoryEvidenceRefV1], observed_at: datetime,
) -> list[MemoryFactV1]:
    facts = []
    for assertion in assertions:
        validate_fact_subject(connection, assertion, project)
        facts.append(MemoryFactV1(
            **{**assertion.model_dump(mode="python"), "subject_id": normalized_subject_id(
                assertion, project.id, project.term_aliases.aliases if project.term_aliases else None,
            )},
            observed_at=observed_at, evidence_refs=evidence_refs, source_classification="human_confirmed",
        ))
    if unsafe_tool_output_reason(json.dumps([item.model_dump(mode="json") for item in facts], ensure_ascii=False)):
        raise MemoryFactsError("fact_content_requires_review", status_code=422)
    return facts


def fact_evidence_available(
    connection: sqlite3.Connection, ref: MemoryEvidenceRefV1, item: MemoryItem | UserMemoryItem,
    *, snapshot_cache: dict[tuple, bool] | None = None,
) -> bool:
    cache = snapshot_cache if snapshot_cache is not None else {}
    from agentmesh.source_authority import document_source_available

    if ref.record_type == "document":
        key = ("document", ref.record_id, ref.version, ref.content_hash, item.workspace_id, item.project_id,
               item.user_id if isinstance(item, UserMemoryItem) else item.owner_user_id,
               tuple(sorted(source.id for source in item.sources)))
        if key in cache:
            return cache[key]
        document = _record(connection, "documents", ref.record_id, DocumentRecord)
        cache[key] = bool(
            document and document.withdrawn_at is None and document.version == ref.version
            and document_evidence_hash(document) == ref.content_hash
            and document.workspace_id == item.workspace_id and document.project_id == item.project_id
            and document.uploaded_by == (item.user_id if isinstance(item, UserMemoryItem) else item.owner_user_id)
            and document.source.id in {source.id for source in item.sources}
            and document_source_available(connection, document)
        )
        return cache[key]
    if ref.record_type == "artifact":
        provenance = item.provenance
        if provenance is None or ref.version != 1 or item.workspace_id is None or item.project_id is None:
            return False
        if (ref.record_id, ref.content_hash) not in set(zip(provenance.artifact_ids, provenance.artifact_hashes, strict=True)):
            return False
        key = ("reviewed_artifacts", item.workspace_id, item.project_id, provenance.review_id, provenance.task_id,
               provenance.run_id, tuple(provenance.artifact_ids), tuple(provenance.artifact_hashes))
        if key in cache:
            return cache[key]
        cache[key] = False
        row = connection.execute("SELECT * FROM task_reviews WHERE id = ?", (provenance.review_id,)).fetchone()
        if row is None:
            return False
        try:
            review = SQLiteStore._task_review_from_row(row)
            if (
                review.status is not TaskReviewStatus.ACCEPTED or review.run_id != provenance.run_id
                or review.task_id != provenance.task_id or review.artifact_ids != provenance.artifact_ids
                or review.artifact_hashes != provenance.artifact_hashes
                or (ref.record_id, ref.content_hash) not in set(zip(
                    review.artifact_ids, review.artifact_hashes, strict=True,
                ))
            ):
                return False
            run = SQLiteStore._validate_task_review_artifacts(
                connection, review=review, workspace_id=item.workspace_id, project_id=item.project_id,
            )
            cache[key] = run.user_id == review.requested_by
            return cache[key]
        except (TaskReviewConflict, ValueError, TypeError):
            return False
    if ref.record_type == "source_span":
        from agentmesh.memory_learning.contracts import DocumentSourceSpanV1
        from agentmesh.memory_learning.service import source_span_hash

        key = ("source_span", ref.record_id, ref.version, ref.content_hash, item.workspace_id, item.project_id,
               item.user_id if isinstance(item, UserMemoryItem) else item.owner_user_id,
               tuple(sorted(source.id for source in item.sources)))
        if key in cache:
            return cache[key]
        span = _record(connection, "source_spans", ref.record_id, DocumentSourceSpanV1)
        document = _record(connection, "documents", span.document_id, DocumentRecord) if span else None
        cache[key] = bool(
            span and ref.version == 1 and source_span_hash(span) == ref.content_hash
            and span.workspace_id == item.workspace_id and span.project_id == item.project_id
            and span.user_id == (item.user_id if isinstance(item, UserMemoryItem) else item.owner_user_id)
            and span.source_id in {source.id for source in item.sources}
            and document and document.withdrawn_at is None and document.version == span.source_version
            and document_evidence_hash(document) == span.source_hash
            and document.uploaded_by == span.user_id and document.workspace_id == span.workspace_id
            and document.project_id == span.project_id and document.source.id == span.source_id
            and 0 <= span.start < span.end <= len(document.text)
            and document.text[span.start:span.end] == span.quote
            and document_source_available(connection, document)
        )
        return cache[key]
    # A Source identity without persisted content is not evidence of an assertion.
    return False


def task_review_evidence_hash(review: TaskReviewV1) -> str:
    return canonical_json_sha256({"schema_version": "task-review-fact-evidence-v1", "review": review.model_dump(mode="json")})


def task_capture_payloads(
    connection: sqlite3.Connection, *, assertions: list[FactAssertionV1] | None, draft: ProcedureDraftV1 | None,
    project: Project, review: TaskReviewV1, confirmed_by: str, observed_at: datetime,
) -> dict:
    artifact_refs = [MemoryEvidenceRefV1(record_type="artifact", record_id=artifact_id, version=1, content_hash=hash_value)
                     for artifact_id, hash_value in zip(review.artifact_ids, review.artifact_hashes, strict=True)]
    facts = confirmed_facts(connection, assertions, project=project, evidence_refs=artifact_refs,
                            observed_at=observed_at) if assertions is not None else None
    procedure = ProcedureMemoryV1(
        **draft.model_dump(mode="python"), human_confirmed_by=confirmed_by, human_confirmed_at=observed_at,
        successful_runs=[ProcedureRunEvidenceV1(run_id=review.run_id, artifact_refs=artifact_refs,
                                              review_ref=MemoryEvidenceRefV1(record_type="task_review", record_id=review.id,
                                                                            version=review.version,
                                                                            content_hash=task_review_evidence_hash(review)))],
    ) if draft is not None else None
    if procedure is not None and unsafe_tool_output_reason(procedure.model_dump_json()):
        raise MemoryFactsError("procedure_content_requires_review", status_code=422)
    return {"facts": facts, "procedure": procedure}


def validate_memory_payload_evidence(
    connection: sqlite3.Connection, item: MemoryItem | UserMemoryItem, project: Project,
) -> None:
    if project.status != "active":
        raise MemoryFactsError("project_not_found", status_code=404)
    snapshot_cache = {}
    for fact in item.facts or []:
        validate_fact_subject(connection, fact, project)
        if not all(fact_evidence_available(connection, ref, item, snapshot_cache=snapshot_cache) for ref in fact.evidence_refs):
            raise MemoryFactsError("fact_evidence_unavailable")
    procedure = item.procedure
    if procedure is None:
        return
    if procedure.human_confirmed_by is None or not procedure.successful_runs:
        raise MemoryFactsError("procedure_requires_confirmation")
    for success in procedure.successful_runs:
        row = connection.execute("SELECT payload FROM task_reviews WHERE id = ?", (success.review_ref.record_id,)).fetchone()
        review = TaskReviewV1.model_validate_json(row["payload"]) if row else None
        if (
            review is None or review.status is not TaskReviewStatus.ACCEPTED or review.run_id != success.run_id
            or review.version != success.review_ref.version
            or task_review_evidence_hash(review) != success.review_ref.content_hash
            or {ref.record_id for ref in success.artifact_refs} != set(review.artifact_ids)
            or not all(fact_evidence_available(connection, ref, item, snapshot_cache=snapshot_cache) for ref in success.artifact_refs)
        ):
            raise MemoryFactsError("procedure_evidence_unavailable")


class MemoryFactsService:
    def __init__(self, repository: SQLiteStore, *, clock: Callable[[], datetime] = now_utc):
        self.repository = repository
        self.clock = clock

    def document_evidence(self, document_id: str, user: User) -> MemoryEvidenceRefV1:
        with closing(self.repository._read_connect()) as connection, connection:
            connection.execute("BEGIN")
            document = _record(connection, "documents", document_id, DocumentRecord)
            if (document is None or document.withdrawn_at is not None or document.uploaded_by != user.id
                    or document.workspace_id != user.workspace_id):
                raise MemoryFactsError("fact_source_not_found", status_code=404)
            authorize_fact_project(connection, user, document.project_id)
            from agentmesh.source_authority import document_source_available

            if not document_source_available(connection, document):
                raise MemoryFactsError('fact_source_not_found', status_code=404)
            return MemoryEvidenceRefV1(record_type="document", record_id=document.id, version=document.version,
                                       content_hash=document_evidence_hash(document))

    def remember(self, request: FactRememberV1, user: User) -> UserMemoryItem:
        request_hash = canonical_json_sha256(request.model_dump(mode="json"))
        command_id = "fact_command_" + canonical_json_sha256({"user_id": user.id, "command": request.command_id})
        with closing(self.repository._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            actor, project = authorize_fact_project(connection, user, request.project_id)
            existing = connection.execute(
                "SELECT payload FROM records WHERE collection = 'memory_fact_commands' AND id = ?", (command_id,),
            ).fetchone()
            if existing:
                receipt = json.loads(existing["payload"])
                if receipt["request_hash"] != request_hash:
                    raise MemoryFactsError("fact_command_conflict")
                item = _record(connection, "user_memory_items", receipt["memory_id"], UserMemoryItem)
                if (
                    item is None or item.status != "active" or item.archived_at is not None
                    or item.user_id != actor.id or item.workspace_id != actor.workspace_id or item.project_id != project.id
                ):
                    raise MemoryFactsError("fact_memory_no_longer_available")
                from agentmesh.memory_context.origin import memory_origin_available

                if not memory_origin_available(connection, item):
                    raise MemoryFactsError('fact_memory_no_longer_available')
                try:
                    validate_memory_payload_evidence(connection, item, project)
                except MemoryFactsError:
                    raise MemoryFactsError('fact_memory_no_longer_available') from None
                return item
            source_memory = None
            if request.supersedes_memory_id is not None:
                source_memory = _record(connection, "user_memory_items", request.supersedes_memory_id, UserMemoryItem)
                if (
                    source_memory is None or source_memory.user_id != actor.id
                    or source_memory.workspace_id != actor.workspace_id or source_memory.project_id != project.id
                    or source_memory.scope is not Scope.PRIVATE
                ):
                    raise MemoryFactsError("fact_memory_not_found", status_code=404)
                if source_memory.version != request.expected_memory_version:
                    raise MemoryFactsError("fact_memory_version_conflict")
                if source_memory.status != "active" or source_memory.archived_at is not None:
                    raise MemoryFactsError("fact_memory_no_longer_available")
                if source_memory.facts is None or source_memory.procedure is not None:
                    raise MemoryFactsError("fact_memory_kind_invalid")
            document = _record(connection, "documents", request.source_document_id, DocumentRecord)
            if (
                document is None or document.withdrawn_at is not None or document.uploaded_by != actor.id
                or document.workspace_id != actor.workspace_id
                or document.project_id != project.id
            ):
                raise MemoryFactsError("fact_source_not_found", status_code=404)
            if document.version != request.source_version or document_evidence_hash(document) != request.source_hash:
                raise MemoryFactsError("fact_source_changed")
            from agentmesh.source_authority import document_source_available

            if not document_source_available(connection, document):
                raise MemoryFactsError('fact_source_changed')
            observed_at = self.clock()
            facts = confirmed_facts(connection, request.facts, project=project, observed_at=observed_at, evidence_refs=[
                MemoryEvidenceRefV1(record_type="document", record_id=document.id, version=document.version,
                                    content_hash=request.source_hash),
            ])
            if unsafe_tool_output_reason(request.title + "\n" + request.summary):
                raise MemoryFactsError("fact_content_requires_review", status_code=422)
            provenance = MemoryProvenanceV1(
                source_kind=MemorySourceKind.IMPORTED_DOCUMENT, created_by=actor.id, created_at=observed_at,
            ) if source_memory is None else MemoryProvenanceV1(
                source_kind=MemorySourceKind.MEMORY_REVISION, created_by=actor.id, created_at=observed_at,
                source_memory_ids=[source_memory.id], source_memory_versions=[source_memory.version],
                source_memory_hashes=[memory_content_hash(source_memory)],
            )
            item = UserMemoryItem(
                user_id=actor.id, workspace_id=actor.workspace_id, project_id=project.id, layer=MemoryLayer.MID_TERM,
                title=request.title, summary=request.summary, source_kind="explicit_fact_confirmation",
                memory_type="fact", facts=facts, sources=[document.source],
                provenance=provenance, supersedes_memory_id=source_memory.id if source_memory is not None else None,
                created_at=observed_at, updated_at=observed_at,
            )
            if source_memory is not None:
                previous = source_memory.model_copy(update={"status": "deprecated", "version": source_memory.version + 1,
                                                           "updated_at": observed_at})
                self.repository._upsert_plain_record(connection, "user_memory_items", previous)
                self.repository._sync_fts(connection, "user_memory_items", previous)
                self.repository.vector_index.mark_stale(connection, "user_memory_items", previous.id)
            self.repository._upsert_plain_record(connection, "user_memory_items", item)
            self.repository._sync_fts(connection, "user_memory_items", item)
            self.repository.vector_index.prepare(connection, "user_memory_items", item.id,
                                                 f"{item.title} {item.summary}")
            connection.execute("INSERT INTO records(collection, id, payload) VALUES ('memory_fact_commands', ?, ?)", (
                command_id, json.dumps({"request_hash": request_hash, "memory_id": item.id}),
            ))
            self.repository._upsert_plain_record(connection, "audit_events", AuditEvent(
                actor=actor.id, action="confirm_memory_facts", target_type="memory", target_id=item.id,
                workspace_id=actor.workspace_id, project_id=project.id,
                metadata={"fact_count": len(facts), "source_id": document.id, "source_version": document.version,
                          **({"supersedes_memory_id": source_memory.id} if source_memory is not None else {})},
                created_at=observed_at,
            ))
        return item

    def query(self, request: FactQueryV1, user: User, *, allowed_scopes: set[Scope] | None = None,
              allowed_memory_types: set[str] | None = None,
              allowed_layers: set[MemoryLayer] | None = None) -> FactQueryResultV1:
        with closing(self.repository._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            return self.query_in_transaction(connection, request, user, snapshot_at=self.clock(),
                                             allowed_scopes=allowed_scopes, allowed_memory_types=allowed_memory_types,
                                             allowed_layers=allowed_layers)

    @staticmethod
    def query_in_transaction(connection: sqlite3.Connection, request: FactQueryV1, user: User, *,
                              snapshot_at: datetime, allowed_scopes: set[Scope] | None = None,
                              allowed_memory_types: set[str] | None = None,
                              allowed_layers: set[MemoryLayer] | None = None) -> FactQueryResultV1:
        subject_id = normalized_subject_id(request, request.project_id)
        subject_ids = {subject_id}
        term_resolution = None
        scopes = json.dumps(sorted(allowed_scopes)) if allowed_scopes is not None else None
        memory_types = json.dumps(sorted(allowed_memory_types)) if allowed_memory_types is not None else None
        layers = json.dumps(sorted(allowed_layers)) if allowed_layers is not None else None
        missing = set()
        hits = []
        actor, project = authorize_fact_project(connection, user, request.project_id)
        if request.subject_type == 'term' and project.term_aliases is not None and project.term_aliases.version > 0:
            aliases = project.term_aliases.aliases
            subject_id = normalized_subject_id(request, project.id, aliases)
            prefix = f'{project.id}::'
            canonical = subject_id.removeprefix(prefix)
            subject_ids = {subject_id, *(prefix + alias for alias, target in aliases.items() if target == canonical)}
            term_resolution = TermResolutionV1(
                canonical_subject_id=subject_id, matched_subject_ids=sorted(subject_ids),
                alias_version=project.term_aliases.version, confirmed_by=project.term_aliases.confirmed_by,
                confirmed_at=project.term_aliases.confirmed_at,
            )
        # Assertions validated real IDs when approved. Current entity membership
        # must not erase their past intervals; reads authorize the current Memory
        # and its source instead of re-reading the subject's current private data.
        rows = connection.execute(
            """SELECT memory.collection, memory.payload FROM records AS memory
            WHERE memory.collection IN ('memory_items','user_memory_items')
              AND json_extract(memory.payload, '$.workspace_id') = ?
              AND json_extract(memory.payload, '$.project_id') = ?
              AND json_extract(memory.payload, '$.archived_at') IS NULL
              AND (? IS NULL OR json_extract(memory.payload, '$.scope') IN (SELECT value FROM json_each(?)))
              AND (? IS NULL OR json_extract(memory.payload, '$.memory_type') IN (SELECT value FROM json_each(?)))
              AND (? IS NULL OR COALESCE(json_extract(memory.payload, '$.layer'),
                  CASE json_extract(memory.payload, '$.scope') WHEN 'project' THEN 'mid_term' ELSE 'long_term' END)
                  IN (SELECT value FROM json_each(?)))
              AND ((memory.collection = 'user_memory_items'
                    AND json_extract(memory.payload, '$.user_id') = ?
                    AND json_extract(memory.payload, '$.scope') = 'private'
                    AND json_extract(memory.payload, '$.status') = 'active'
                    AND NOT EXISTS (SELECT 1 FROM records AS successor
                        WHERE successor.collection = 'user_memory_items'
                          AND json_extract(successor.payload, '$.supersedes_memory_id') = memory.id
                          AND json_extract(successor.payload, '$.user_id') = ?
                          AND json_extract(successor.payload, '$.status') = 'active'
                          AND json_extract(successor.payload, '$.archived_at') IS NULL))
                   OR (memory.collection = 'memory_items'
                    AND json_extract(memory.payload, '$.scope') IN ('project','team_accepted')
                    AND json_extract(memory.payload, '$.status') IN ('accepted','disputed')
                    AND (json_extract(memory.payload, '$.team_id') IS NULL OR ? IN ('admin','team_lead')
                         OR EXISTS (SELECT 1 FROM records AS membership
                             WHERE membership.collection = 'team_memberships'
                               AND json_extract(membership.payload, '$.team_id') = json_extract(memory.payload, '$.team_id')
                               AND json_extract(membership.payload, '$.user_id') = ?))))
              AND EXISTS (SELECT 1 FROM json_each(memory.payload, '$.facts') AS fact
                  WHERE json_extract(fact.value, '$.subject_type') = ?
                    AND json_extract(fact.value, '$.subject_id') IN (SELECT value FROM json_each(?))
                    AND json_extract(fact.value, '$.predicate') = ?)
            ORDER BY memory.id LIMIT ?""",
            (actor.workspace_id, project.id, scopes, scopes, memory_types, memory_types, layers, layers,
             actor.id, actor.id, actor.role, actor.id, request.subject_type, json.dumps(sorted(subject_ids)),
             request.predicate, MAX_FACT_MEMORIES + 1),
        ).fetchall()
        if len(rows) > MAX_FACT_MEMORIES:
            missing.add("fact_memory_limit_exceeded")
        snapshot_cache = {}
        for row in rows[:MAX_FACT_MEMORIES]:
            item = (UserMemoryItem if row["collection"] == "user_memory_items" else MemoryItem).model_validate_json(
                row["payload"]
            )
            current_hash = memory_content_hash(item)
            for fact in item.facts or []:
                if (fact.subject_type != request.subject_type or fact.subject_id not in subject_ids
                    or fact.predicate != request.predicate
                    or (request.observed_before is not None and fact.observed_at > request.observed_before)):
                    continue
                if fact.time_precision == "unknown":
                    missing.add("fact_valid_time_unknown")
                    continue
                if not MemoryFactsService._matches_time(fact, request, snapshot_at):
                    continue
                if len(hits) >= 100:
                    missing.add("fact_result_limit_exceeded")
                    continue
                if not all(fact_evidence_available(connection, ref, item, snapshot_cache=snapshot_cache) for ref in fact.evidence_refs):
                    missing.add("fact_evidence_unavailable")
                    continue
                if unsafe_tool_output_reason(fact.model_dump_json()):
                    missing.add("fact_content_requires_review")
                    continue
                if fact.source_classification == "model_inference":
                    missing.add("fact_requires_confirmation")
                hits.append(FactHitV1(
                    memory_id=item.id, memory_record_type="user_memory_item" if isinstance(item, UserMemoryItem)
                    else "memory_item", memory_version=item.version, memory_hash=current_hash,
                    scope=item.scope, status=item.status, fact=fact,
                ))
        conflicting = set()
        values = [unicodedata.normalize("NFC", hit.fact.value) for hit in hits]
        if request.predicate not in MULTI_VALUE_PREDICATES:
            for index, hit in enumerate(hits):
                for other_index in range(index):
                    other = hits[other_index]
                    if values[index] != values[other_index] and MemoryFactsService._overlap_in_query(hit.fact, other.fact, request):
                        conflicting.update((index, other_index))
        conflicts = [FactConflictV1(
            group_id="fact_conflict_" + canonical_json_sha256({
                "project_id": request.project_id, "subject_type": request.subject_type,
                "subject_id": subject_id, "predicate": request.predicate,
            })[:24], fact_indexes=sorted(conflicting),
        )] if conflicting else []
        disputed = any(hit.status == "disputed" for hit in hits)
        outcome = "conflict" if conflicts or disputed else "insufficient_evidence" if missing else (
            "known" if hits else "unknown"
        )
        return FactQueryResultV1(project_id=project.id, snapshot_at=snapshot_at, outcome=outcome, facts=hits,
                                 conflicts=conflicts, missing_data=sorted(missing),
                                 automatic_context_eligible=outcome == "known", term_resolution=term_resolution)

    @staticmethod
    def _matches_time(fact: MemoryFactV1, request: FactQueryV1, now: datetime) -> bool:
        if request.interval_from is not None:
            return fact.valid_from < request.interval_to and (fact.valid_to is None or fact.valid_to > request.interval_from)
        point = request.as_of or now
        return fact.valid_from <= point and (fact.valid_to is None or point < fact.valid_to)

    @staticmethod
    def _overlap_in_query(first: MemoryFactV1, second: MemoryFactV1, request: FactQueryV1) -> bool:
        start = max(first.valid_from, second.valid_from)
        ends = [value for value in (first.valid_to, second.valid_to) if value is not None]
        if request.interval_from is not None:
            start = max(start, request.interval_from)
            ends.append(request.interval_to)
        return not ends or start < min(ends)
