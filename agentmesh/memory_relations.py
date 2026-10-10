"""Bounded current-project relation projections; no independent memory authority."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import deque
from contextlib import closing
from datetime import datetime
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.chunker import chunk_text
from agentmesh.memory_context.origin import document_reference_identity
from agentmesh.memory_facts import document_evidence_hash, fact_evidence_available
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.memory_learning.contracts import DocumentSourceSpanV1
from agentmesh.memory_learning.service import source_span_hash
from agentmesh.memory_payloads import MemoryEvidenceRefV1
from agentmesh.models import (
    Artifact,
    AuditEvent,
    ChatThread,
    DocumentRecord,
    MemoryItem,
    MemoryRelation,
    PermissionPolicyRule,
    Project,
    Task,
    User,
    UserMemoryItem,
    UserRole,
    now_utc,
)
from agentmesh.permissions import ACTION_MANAGE_TEAM_MEMORY, has_permission
from agentmesh.store import SQLiteStore

RelationRecordType = Literal["task", "user_memory_item", "memory_item", "document", "artifact"]


class RelationLookupV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    record_type: RelationRecordType
    record_id: str = Field(min_length=1, max_length=120)

    @property
    def key(self) -> str:
        return f"{self.record_type}:{self.record_id}"


class MemoryRelationQueryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: str = Field(min_length=1, max_length=120)
    root: RelationLookupV1
    max_hops: int = Field(default=2, ge=1, le=2)
    max_nodes: int = Field(default=20, ge=1, le=40)
    max_edges: int = Field(default=40, ge=1, le=80)
    max_chars: int = Field(default=8000, ge=4096, le=12000)


class RelationNodeV1(RelationLookupV1):
    version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(max_length=120)
    status: str
    navigation_href: str
    depth: int = Field(ge=0, le=2)


class RelationVersionRefV1(RelationLookupV1):
    version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class MemoryRelationCreateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    project_id: str = Field(min_length=1, max_length=120)
    command_id: str = Field(min_length=1, max_length=120)
    source: RelationVersionRefV1
    target: RelationVersionRefV1
    evidence: RelationVersionRefV1
    relation_type: Literal["relates_to", "supports", "contradicts", "supersedes", "caused_by"]
    assertion: Literal["candidate", "confirmed"] = "candidate"

    @model_validator(mode="after")
    def validate_endpoints(self) -> MemoryRelationCreateV1:
        if self.source.record_type not in {"user_memory_item", "memory_item"}:
            raise ValueError("relation source must be a Memory")
        if self.evidence.record_type not in {"task", "document"}:
            raise ValueError("relation requires a current Task or document as evidence")
        if self.source.key == self.target.key:
            raise ValueError("self relations are not allowed")
        return self


class RelationEdgeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    from_key: str
    to_key: str
    relation_type: str
    assertion: Literal["native", "candidate", "confirmed"]
    evidence: RelationVersionRefV1 | None = None


class MemoryRelationGraphV1(BaseModel):
    schema_version: Literal["memory-relation-graph-v1"] = "memory-relation-graph-v1"
    data_mode: Literal["real"] = "real"
    project_id: str
    root_key: str
    snapshot_at: datetime
    nodes: list[RelationNodeV1] = Field(default_factory=list)
    edges: list[RelationEdgeV1] = Field(default_factory=list)
    truncated: bool = False
    diagnostics: list[str] = Field(default_factory=list)


class MemoryRelationError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code, self.status_code = code, status_code


class _RelationReader:
    def __init__(self, connection: sqlite3.Connection, user: User, project_id: str):
        self.connection, self.project_id = connection, project_id
        self.bytes_read = self.reads = self.candidates = 0
        self.diagnostics: set[str] = set()
        row = connection.execute(
            "SELECT payload FROM records WHERE collection='users' AND id=? AND length(CAST(payload AS BLOB))<=65536",
            (user.id,),
        ).fetchone()
        try:
            self.actor = User.model_validate_json(row["payload"]) if row else None
        except (ValueError, TypeError, RecursionError) as error:
            raise MemoryRelationError("relation_actor_not_authorized", 403) from error
        if (
            self.actor is None
            or self.actor.id != user.id
            or self.actor.status != "active"
            or self.actor.workspace_id != user.workspace_id
            or self.actor.role not in set(UserRole)
        ):
            raise MemoryRelationError("relation_actor_not_authorized", 403)
        self.spend(len(row["payload"].encode()))
        row = connection.execute(
            "SELECT payload FROM records WHERE collection='projects' AND id=? AND length(CAST(payload AS BLOB))<=262144",
            (project_id,),
        ).fetchone()
        try:
            project = Project.model_validate_json(row["payload"]) if row else None
        except (ValueError, TypeError, RecursionError) as error:
            raise MemoryRelationError("relation_project_not_found", 404) from error
        if (
            project is None
            or project.id != project_id
            or project.status != "active"
            or project.workspace_id != self.actor.workspace_id
            or (project.member_ids and self.actor.id not in project.member_ids)
        ):
            raise MemoryRelationError("relation_project_not_found", 404)
        self.objects: dict[str, object] = {}
        self.node_cache: dict[str, RelationNodeV1] = {}
        self.spend(len(row["payload"].encode()))
        self.review_cache: dict[tuple[type, str], bool] = {}

    def memory_scope(self, alias: str) -> tuple[str, list]:
        # All aliases are internal SQL constants. Values always use placeholders.
        clause = f"""json_extract({alias}.payload, '$.workspace_id') = ?
          AND (json_extract({alias}.payload, '$.project_id') IS NULL
               OR json_extract({alias}.payload, '$.project_id') = ?)
          AND json_extract({alias}.payload, '$.archived_at') IS NULL
          AND json_extract({alias}.payload, '$.evidence_withdrawn_at') IS NULL
          AND (({alias}.collection='user_memory_items'
                AND json_extract({alias}.payload, '$.user_id')=?
                AND json_extract({alias}.payload, '$.scope')='private'
                AND COALESCE(json_extract({alias}.payload, '$.status'),'active')='active')
            OR ({alias}.collection='memory_items'
                AND json_extract({alias}.payload, '$.status')='accepted'
                AND json_extract({alias}.payload, '$.scope') IN ('project','team_accepted')
                AND (json_extract({alias}.payload, '$.team_id') IS NULL OR ? IN ('admin','team_lead')
                     OR EXISTS (SELECT 1 FROM records AS member WHERE member.collection='team_memberships'
                         AND json_extract(member.payload, '$.user_id')=?
                         AND json_extract(member.payload, '$.team_id')=json_extract({alias}.payload, '$.team_id')))))"""
        return clause, [self.actor.workspace_id, self.project_id, self.actor.id, self.actor.role, self.actor.id]

    def spend(self, size: int, reads: int = 1) -> bool:
        if size > 4 * 1024 * 1024 - self.bytes_read or reads > 200 - self.reads:
            self.diagnostics.add("read_limit")
            return False
        self.bytes_read += size
        self.reads += reads
        return True

    def bounded_rows(self, sql: str, params: list | tuple) -> list[sqlite3.Row]:
        limit = min(128, 512 - self.candidates)
        if limit <= 0:
            self.diagnostics.add("candidate_limit")
            return []
        rows = self.connection.execute(sql + " LIMIT ?", [*params, limit + 1]).fetchall()
        if len(rows) > limit:
            self.diagnostics.add("candidate_limit")
        self.candidates += min(len(rows), limit)
        return rows[:limit]

    def node(self, ref: RelationLookupV1, depth: int) -> RelationNodeV1 | None:
        if ref.key in self.node_cache:
            return self.node_cache[ref.key].model_copy(update={"depth": depth})
        if ref.key in self.objects:
            item = self.objects[ref.key]
        else:
            item = self._load(ref)
            if item is None:
                return None
            self.objects[ref.key] = item
        if isinstance(item, Task):
            version, status, title = item.management.version, item.management.delivery_stage.value, item.title
            content_hash, href = (
                canonical_json_sha256(item.model_dump(mode="json")),
                f"/tasks?project={quote(self.project_id, safe='')}&task={quote(item.id, safe='')}",
            )
        elif isinstance(item, UserMemoryItem | MemoryItem):
            version, status, title = item.version, str(item.status), item.title
            content_hash = memory_content_hash(item)
            href = f"/knowledge?project={quote(self.project_id, safe='')}&memory={quote(item.id, safe='')}"
        elif isinstance(item, DocumentRecord):
            version, status, title = item.version, "current", item.title
            content_hash = document_evidence_hash(item)
            href = f"/knowledge?project={quote(self.project_id, safe='')}&document={quote(item.id, safe='')}"
        else:
            version, status, title = 1, "sealed", "已封存的交付依据"
            content_hash, href = item.content_hash, f"/api/artifacts/{quote(item.id, safe='')}"
        node = RelationNodeV1(
            record_type=ref.record_type,
            record_id=ref.record_id,
            version=version,
            content_hash=content_hash,
            title=title[:120],
            status=status,
            navigation_href=href,
            depth=depth,
        )
        self.node_cache[ref.key] = node
        return node

    def _load(self, ref: RelationLookupV1):
        params = [ref.record_id]
        if ref.record_type in {"user_memory_item", "memory_item"}:
            collection = "user_memory_items" if ref.record_type == "user_memory_item" else "memory_items"
            scope, scope_params = self.memory_scope("r")
            sql = f"SELECT r.payload FROM records r WHERE r.id=? AND r.collection=? AND {scope}"
            params += [collection, *scope_params]
            model, limit = (UserMemoryItem if ref.record_type == "user_memory_item" else MemoryItem), 65536
        elif ref.record_type == "task":
            sql = """SELECT r.payload FROM records r JOIN task_operations_projection t ON t.task_id=r.id
                WHERE r.id=? AND r.collection='tasks' AND t.workspace_id=? AND t.project_id=?
                  AND t.thread_kind='task' AND t.archived_at IS NULL"""
            params += [self.actor.workspace_id, self.project_id]
            model, limit = Task, 65536
        elif ref.record_type == "document":
            sql = """SELECT r.payload FROM records r WHERE r.id=? AND r.collection='documents'
                AND json_extract(r.payload,'$.uploaded_by')=? AND json_extract(r.payload,'$.workspace_id')=?
                AND json_extract(r.payload,'$.project_id')=? AND json_extract(r.payload,'$.withdrawn_at') IS NULL"""
            params += [self.actor.id, self.actor.workspace_id, self.project_id]
            model, limit = DocumentRecord, 1200000
        else:
            sql = """SELECT payload FROM artifacts WHERE id=? AND user_id=? AND workspace_id=? AND project_id=?
                AND verification_state='sealed' AND json_extract(payload,'$.purged_at') IS NULL"""
            params += [self.actor.id, self.actor.workspace_id, self.project_id]
            model, limit = Artifact, 262144
        # Gate byte size before reading/decoding payload; scope gates precede it.
        sizes = self.connection.execute(
            "SELECT length(CAST(payload AS BLOB)) AS size FROM (" + sql + ")", params
        ).fetchone()
        if sizes is None:
            return None
        if sizes["size"] > limit or not self.spend(sizes["size"]):
            self.diagnostics.add("read_limit")
            return None
        row = self.connection.execute(sql, params).fetchone()
        try:
            item = model.model_validate_json(row["payload"])
            if item.id != ref.record_id:
                return None
            if isinstance(item, UserMemoryItem | MemoryItem):
                if (
                    item.workspace_id != self.actor.workspace_id
                    or item.project_id not in {None, self.project_id}
                    or item.archived_at is not None
                ):
                    return None
                if isinstance(item, UserMemoryItem):
                    if item.user_id != self.actor.id or item.scope != "private" or item.status != "active":
                        return None
                elif (
                    item.scope not in {"project", "team_accepted"}
                    or item.status != "accepted"
                    or item.evidence_withdrawn_at is not None
                ):
                    return None
                elif item.team_id is not None and self.actor.role not in {"admin", "team_lead"}:
                    member = self.connection.execute(
                        """SELECT 1 FROM records WHERE collection='team_memberships'
                        AND json_extract(payload,'$.user_id')=? AND json_extract(payload,'$.team_id')=? LIMIT 1""",
                        (self.actor.id, item.team_id),
                    ).fetchone()
                    if member is None:
                        return None
            if isinstance(item, Task):
                if item.management is None or item.management.archived_at is not None:
                    return None
                size = self.connection.execute(
                    "SELECT length(CAST(payload AS BLOB)) AS size FROM records WHERE collection='chat_threads' AND id=?",
                    (item.thread_id,),
                ).fetchone()
                if size is None:
                    return None
                if size["size"] > 65536 or not self.spend(size["size"]):
                    self.diagnostics.add("read_limit")
                    return None
                thread_row = self.connection.execute(
                    "SELECT payload FROM records WHERE collection='chat_threads' AND id=?", (item.thread_id,)
                ).fetchone()
                thread = ChatThread.model_validate_json(thread_row["payload"])
                if (
                    thread.id != item.thread_id
                    or thread.workspace_id != self.actor.workspace_id
                    or thread.project_id != self.project_id
                    or thread.kind != "task"
                    or item.management is None
                ):
                    return None
            if isinstance(item, DocumentRecord) and (
                item.uploaded_by != self.actor.id
                or item.workspace_id != self.actor.workspace_id
                or item.project_id != self.project_id
                or item.withdrawn_at is not None
                or len(item.text.encode()) > 1024 * 1024
            ):
                return None
            if isinstance(item, Artifact) and (
                item.user_id != self.actor.id
                or item.workspace_id != self.actor.workspace_id
                or item.project_id != self.project_id
                or item.verification_state != "sealed"
                or item.purged_at is not None
                or hashlib.sha256(item.content.encode()).hexdigest() != item.content_hash
                or len(item.content.encode()) != item.size_bytes
            ):
                return None
            return item
        except (ValueError, TypeError, RecursionError):
            return None

    def reviewed(self, item: MemoryItem | UserMemoryItem) -> bool:
        key = (type(item), item.id)
        if key in self.review_cache:
            return self.review_cache[key]
        self.review_cache[key] = False
        p = item.provenance
        if p is None or p.source_kind != "task_artifact" or not p.artifact_ids:
            return False
        # The existing native verifier reads the Run and exact frozen Artifacts.
        # Charge and cap those reads before delegating; it never sends their body.
        for table, ids, limit in (
            ("task_reviews", [p.review_id], 65536),
            ("agent_runs", [p.run_id], 131072),
            ("artifacts", p.artifact_ids, 262144),
        ):
            for record_id in ids:
                row = self.connection.execute(
                    f"SELECT length(CAST(payload AS BLOB)) AS size FROM {table} WHERE id=?", (record_id,)
                ).fetchone()
                if row is None or row["size"] > limit or not self.spend(row["size"]):
                    if row is not None:
                        self.diagnostics.add("read_limit")
                    return False
        ref = MemoryEvidenceRefV1(
            record_type="artifact", record_id=p.artifact_ids[0], version=1, content_hash=p.artifact_hashes[0]
        )
        self.review_cache[key] = fact_evidence_available(self.connection, ref, item)
        return self.review_cache[key]

    @staticmethod
    def edge(
        source: RelationLookupV1,
        target: RelationLookupV1,
        relation_type: str,
        evidence: RelationVersionRefV1 | None = None,
    ) -> RelationEdgeV1:
        return RelationEdgeV1(
            id="relation_" + canonical_json_sha256([source.key, target.key, relation_type]),
            from_key=source.key,
            to_key=target.key,
            relation_type=relation_type,
            assertion="native",
            evidence=evidence,
        )

    def document_neighbors(self, item: UserMemoryItem | MemoryItem, node: RelationNodeV1):
        owner = item.user_id if isinstance(item, UserMemoryItem) else item.owner_user_id
        if owner != self.actor.id:  # Documents remain owner-only even behind a shared Memory.
            return
        evidence_depth = min(node.depth + 1, 2)  # Backlink qualification does not traverse another hop.
        # Legacy links have no frozen body hash. Only literal native chunks or
        # versioned Fact evidence can establish a current document citation.
        if (
            isinstance(item, UserMemoryItem)
            and item.source_kind == "document_import"
            and item.facts is None
            and item.procedure is None
        ):
            if len(item.sources) > 32:
                self.diagnostics.add("candidate_limit")
            for source in item.sources[:32]:
                identity = document_reference_identity(source.reference)
                if identity is None or len(identity[0]) > 120:
                    continue
                suffix = source.reference.rsplit("/chunk_", 1)[-1]
                if (
                    not suffix.isdecimal()
                    or suffix != str(int(suffix))
                    or source.reference != f"document://{identity[0]}#v{identity[1]}/chunk_{suffix}"
                ):
                    continue
                ref = RelationLookupV1(record_type="document", record_id=identity[0])
                document_node = self.node(ref, evidence_depth)
                if document_node is None or document_node.version != identity[1]:
                    continue
                document = self.objects[ref.key]
                if (
                    source.workspace_id != item.workspace_id
                    or source.project_id != item.project_id
                    or source.user_id != owner
                    or document.uploaded_by != owner
                    or document.workspace_id != item.workspace_id
                    or document.project_id != item.project_id
                ):
                    continue
                pieces = chunk_text(document.text)
                if int(suffix) < len(pieces) and pieces[int(suffix)] == item.summary:
                    yield (
                        ref,
                        self.edge(
                            node,
                            ref,
                            "cites",
                            RelationVersionRefV1(
                                **document_node.model_dump(
                                    include={"record_type", "record_id", "version", "content_hash"}
                                )
                            ),
                        ),
                    )
        count = 0
        for fact in item.facts or []:
            for evidence in fact.evidence_refs:
                count += 1
                if count > 128:
                    self.diagnostics.add("candidate_limit")
                    return
                span = None
                if evidence.record_type == "document":
                    ref = RelationLookupV1(record_type="document", record_id=evidence.record_id)
                elif evidence.record_type == "source_span":
                    row = self.connection.execute(
                        """SELECT payload FROM records WHERE collection='source_spans'
                        AND id=? AND json_extract(payload,'$.user_id')=? AND json_extract(payload,'$.workspace_id')=?
                        AND json_extract(payload,'$.project_id')=? AND length(CAST(payload AS BLOB))<=65536""",
                        (evidence.record_id, self.actor.id, self.actor.workspace_id, self.project_id),
                    ).fetchone()
                    if row is None or not self.spend(len(row["payload"].encode())):
                        continue
                    try:
                        span = DocumentSourceSpanV1.model_validate_json(row["payload"])
                    except (ValueError, TypeError, RecursionError):
                        continue
                    if (
                        span.id != evidence.record_id
                        or evidence.version != 1
                        or source_span_hash(span) != evidence.content_hash
                        or not 1 <= len(span.document_id) <= 120
                    ):
                        continue
                    ref = RelationLookupV1(record_type="document", record_id=span.document_id)
                else:
                    continue
                document_node = self.node(ref, evidence_depth)
                if document_node is None:
                    continue
                document = self.objects[ref.key]
                if (
                    document.uploaded_by != owner
                    or document.workspace_id != item.workspace_id
                    or document.project_id != item.project_id
                    or document.source.id not in {source.id for source in item.sources}
                ):
                    continue
                if span is None:
                    if (document_node.version, document_node.content_hash) != (evidence.version, evidence.content_hash):
                        continue
                elif (
                    span.user_id != owner
                    or span.workspace_id != item.workspace_id
                    or span.project_id != item.project_id
                    or span.source_id != document.source.id
                    or span.source_version != document.version
                    or span.source_hash != document_node.content_hash
                    or not 0 <= span.start < span.end <= len(document.text)
                    or document.text[span.start : span.end] != span.quote
                ):
                    continue
                yield (
                    ref,
                    self.edge(
                        node,
                        ref,
                        "cites",
                        RelationVersionRefV1(
                            **document_node.model_dump(include={"record_type", "record_id", "version", "content_hash"})
                        ),
                    ),
                )

    def neighbors(self, node: RelationNodeV1):
        yield from self.manual_neighbors(node)
        item = self.objects[node.key]
        if isinstance(item, Task):
            for task_id in [
                *item.management.dependency_task_ids,
                *([item.management.parent_task_id] if item.management.parent_task_id else []),
            ]:
                ref = RelationLookupV1(record_type="task", record_id=task_id)
                yield (
                    ref,
                    self.edge(
                        node, ref, "depends_on" if task_id in item.management.dependency_task_ids else "child_of"
                    ),
                )
            rows = self.bounded_rows(
                """SELECT task_id FROM task_operations_projection t
                WHERE t.workspace_id=? AND t.project_id=? AND t.thread_kind='task' AND t.archived_at IS NULL
                  AND length(t.task_id) BETWEEN 1 AND 120
                  AND (t.parent_task_id=? OR EXISTS (SELECT 1 FROM json_each(t.dependency_task_ids_json) WHERE value=?))
                ORDER BY t.updated_at DESC,t.task_id""",
                [self.actor.workspace_id, self.project_id, item.id, item.id],
            )
            for row in rows:
                ref = RelationLookupV1(record_type="task", record_id=row["task_id"])
                related = self.node(ref, node.depth + 1)
                if related is None:
                    continue
                management = self.objects[ref.key].management
                if management.parent_task_id == item.id:
                    yield ref, self.edge(ref, node, "child_of")
                elif item.id in management.dependency_task_ids:
                    yield ref, self.edge(ref, node, "depends_on")
            scope, params = self.memory_scope("m")
            rows = self.bounded_rows(
                "SELECT m.id,m.collection FROM records m WHERE "
                + scope
                + """
                AND length(m.id) BETWEEN 1 AND 120
                AND json_extract(m.payload,'$.provenance.task_id')=? ORDER BY m.created_order DESC""",
                [*params, item.id],
            )
            for row in rows:
                ref = RelationLookupV1(
                    record_type="user_memory_item" if row["collection"] == "user_memory_items" else "memory_item",
                    record_id=row["id"],
                )
                memory = self.node(ref, node.depth + 1)
                if memory is not None and self.reviewed(self.objects[ref.key]):
                    yield ref, self.edge(ref, node, "derived_from_task_review")
        elif isinstance(item, UserMemoryItem | MemoryItem):
            p = item.provenance
            if self.reviewed(item):
                ref = RelationLookupV1(record_type="task", record_id=p.task_id)
                yield ref, self.edge(node, ref, "derived_from_task_review")
                for artifact_id in p.artifact_ids:
                    ref = RelationLookupV1(record_type="artifact", record_id=artifact_id)
                    yield ref, self.edge(node, ref, "derived_from_artifact")
            yield from self.document_neighbors(item, node)
            if isinstance(item, MemoryItem) and item.metadata.get("source_memory_id"):
                try:
                    ref = RelationLookupV1(record_type="user_memory_item", record_id=item.metadata["source_memory_id"])
                    version = int(item.metadata.get("source_memory_version", ""))
                except ValueError:
                    pass
                else:
                    parent = self.node(ref, node.depth + 1)
                    if (
                        parent is not None
                        and parent.version == version
                        and parent.content_hash == item.metadata.get("source_memory_hash")
                        and self.objects[ref.key].user_id == item.owner_user_id
                        and self.objects[ref.key].project_id == item.project_id
                    ):
                        yield ref, self.edge(node, ref, "shared_from_personal")
            if p is not None and len(p.source_memory_ids) == len(p.source_memory_versions) == len(
                p.source_memory_hashes
            ):
                for parent_id, version, content_hash in zip(
                    p.source_memory_ids, p.source_memory_versions, p.source_memory_hashes, strict=True
                ):
                    ref = RelationLookupV1(record_type=node.record_type, record_id=parent_id)
                    parent = self.node(ref, node.depth + 1)
                    if (
                        parent is not None
                        and parent.version == version
                        and parent.content_hash == content_hash
                        and self.objects[ref.key].project_id == item.project_id
                    ):
                        yield ref, self.edge(node, ref, "derived_from_memory")
        elif isinstance(item, DocumentRecord):
            scope, params = self.memory_scope("m")
            prefix = f"document://{item.id}#v{item.version}/chunk_"
            rows = self.bounded_rows(
                """SELECT m.id,m.collection FROM records m WHERE """
                + scope
                + """
                AND length(m.id) BETWEEN 1 AND 120
                AND json_extract(m.payload,'$.project_id')=?
                AND COALESCE(json_extract(m.payload,'$.user_id'),json_extract(m.payload,'$.owner_user_id'))=?
                AND ((m.collection='user_memory_items' AND json_extract(m.payload,'$.source_kind')='document_import'
                    AND json_extract(m.payload,'$.facts') IS NULL AND json_extract(m.payload,'$.procedure') IS NULL
                    AND EXISTS (SELECT 1 FROM json_each(m.payload,'$.sources') source
                        WHERE substr(json_extract(source.value,'$.reference'),1,?)=?))
                  OR EXISTS (SELECT 1 FROM json_each(m.payload,'$.facts') fact,
                                          json_each(fact.value,'$.evidence_refs') evidence
                    WHERE (json_extract(evidence.value,'$.record_type')='document'
                        AND json_extract(evidence.value,'$.record_id')=?
                        AND json_extract(evidence.value,'$.version')=?
                        AND json_extract(evidence.value,'$.content_hash')=?)
                      OR (json_extract(evidence.value,'$.record_type')='source_span'
                        AND EXISTS (SELECT 1 FROM records span WHERE span.collection='source_spans'
                          AND span.id=json_extract(evidence.value,'$.record_id')
                          AND json_extract(span.payload,'$.document_id')=?
                          AND json_extract(span.payload,'$.source_version')=?
                          AND json_extract(span.payload,'$.source_hash')=?
                          AND json_extract(span.payload,'$.user_id')=?))))
                ORDER BY m.created_order DESC""",
                [
                    *params,
                    item.project_id,
                    self.actor.id,
                    len(prefix),
                    prefix,
                    item.id,
                    item.version,
                    node.content_hash,
                    item.id,
                    item.version,
                    node.content_hash,
                    self.actor.id,
                ],
            )
            for row in rows:
                ref = RelationLookupV1(
                    record_type="user_memory_item" if row["collection"] == "user_memory_items" else "memory_item",
                    record_id=row["id"],
                )
                memory_node = self.node(ref, node.depth + 1)
                if memory_node is not None:
                    for document_ref, edge in self.document_neighbors(self.objects[ref.key], memory_node):
                        if document_ref.key == node.key:
                            yield ref, edge

    def visible_reference_sql(self, kind_sql: str, id_sql: str) -> tuple[str, list]:
        scope, params = self.memory_scope("target")
        sql = f"""(
          EXISTS (SELECT 1 FROM records target WHERE target.id={id_sql} AND {scope}
            AND (({kind_sql}='user_memory_item' AND target.collection='user_memory_items')
              OR ({kind_sql}='memory_item' AND target.collection='memory_items')))
          OR ({kind_sql}='task' AND EXISTS (SELECT 1 FROM task_operations_projection target
            WHERE target.task_id={id_sql} AND target.workspace_id=? AND target.project_id=?
              AND target.thread_kind='task' AND target.archived_at IS NULL))
          OR ({kind_sql}='document' AND EXISTS (SELECT 1 FROM records target
            WHERE target.collection='documents' AND target.id={id_sql}
              AND json_extract(target.payload,'$.uploaded_by')=? AND json_extract(target.payload,'$.workspace_id')=?
              AND json_extract(target.payload,'$.project_id')=? AND json_extract(target.payload,'$.withdrawn_at') IS NULL))
          OR ({kind_sql}='artifact' AND EXISTS (SELECT 1 FROM artifacts target
            WHERE target.id={id_sql} AND target.user_id=? AND target.workspace_id=? AND target.project_id=?
              AND target.verification_state='sealed' AND json_extract(target.payload,'$.purged_at') IS NULL)))"""
        return sql, [
            *params,
            self.actor.workspace_id,
            self.project_id,
            self.actor.id,
            self.actor.workspace_id,
            self.project_id,
            self.actor.id,
            self.actor.workspace_id,
            self.project_id,
        ]

    def manual_neighbors(self, node: RelationNodeV1):
        source_scope, source_params = self.memory_scope("source")
        target_scope, target_params = self.visible_reference_sql(
            "json_extract(relation.payload,'$.target_record_type')",
            "json_extract(relation.payload,'$.to_source_id')",
        )
        evidence_scope, evidence_params = self.visible_reference_sql(
            "json_extract(relation.payload,'$.evidence_record_type')",
            "json_extract(relation.payload,'$.evidence_id')",
        )
        rows = self.bounded_rows(
            f"""SELECT relation.id,relation.payload FROM records relation
            JOIN records source ON source.id=json_extract(relation.payload,'$.from_memory_id')
              AND ((source.collection='user_memory_items' AND json_extract(relation.payload,'$.from_record_type')='user_memory_item')
                OR (source.collection='memory_items' AND json_extract(relation.payload,'$.from_record_type')='memory_item'))
            WHERE relation.collection='memory_relations'
              AND json_extract(relation.payload,'$.schema_version')='memory-relation-v1'
              AND json_extract(relation.payload,'$.workspace_id')=? AND json_extract(relation.payload,'$.project_id')=?
              AND length(CAST(relation.payload AS BLOB)) <= 16384
              AND {source_scope} AND {target_scope} AND {evidence_scope}
              AND json_extract(relation.payload,'$.source_version')=COALESCE(json_extract(source.payload,'$.version'),1)
              AND ((json_extract(relation.payload,'$.from_record_type')=? AND json_extract(relation.payload,'$.from_memory_id')=?)
                OR (json_extract(relation.payload,'$.target_record_type')=? AND json_extract(relation.payload,'$.to_source_id')=?))
            ORDER BY relation.created_order DESC""",
            [
                self.actor.workspace_id,
                self.project_id,
                *source_params,
                *target_params,
                *evidence_params,
                node.record_type,
                node.record_id,
                node.record_type,
                node.record_id,
            ],
        )
        for row in rows:
            if not self.spend(len(row["payload"].encode())):
                break
            try:
                relation = MemoryRelation.model_validate_json(row["payload"])
                if (
                    relation.id != row["id"]
                    or relation.schema_version != "memory-relation-v1"
                    or relation.workspace_id != self.actor.workspace_id
                    or relation.project_id != self.project_id
                ):
                    continue
                source_ref = RelationLookupV1(record_type=relation.from_record_type, record_id=relation.from_memory_id)
                target_ref = RelationLookupV1(record_type=relation.target_record_type, record_id=relation.to_source_id)
                evidence_ref = RelationVersionRefV1(
                    record_type=relation.evidence_record_type,
                    record_id=relation.evidence_id,
                    version=relation.evidence_version,
                    content_hash=relation.evidence_hash,
                )
                source = self.node(source_ref, node.depth + 1)
                target = self.node(target_ref, node.depth + 1)
                evidence = self.node(evidence_ref, min(node.depth + 1, 2))
                if (
                    source is None
                    or target is None
                    or evidence is None
                    or (source.version, source.content_hash) != (relation.source_version, relation.source_hash)
                    or (target.version, target.content_hash) != (relation.target_version, relation.target_hash)
                    or (evidence.version, evidence.content_hash) != (relation.evidence_version, relation.evidence_hash)
                ):
                    continue
                yield (
                    target_ref if source_ref.key == node.key else source_ref,
                    RelationEdgeV1(
                        id=relation.id,
                        from_key=source_ref.key,
                        to_key=target_ref.key,
                        relation_type=relation.relation_type,
                        assertion=relation.assertion,
                        evidence=evidence_ref,
                    ),
                )
            except (ValueError, TypeError, RecursionError):
                continue


class MemoryRelationService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    def create(self, request: MemoryRelationCreateV1, user: User) -> MemoryRelation:
        with closing(self.repository._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            reader = _RelationReader(connection, user, request.project_id)
            for ref in (request.source, request.target, request.evidence):
                node = reader.node(ref, 0)
                if node is None:
                    raise MemoryRelationError("relation_endpoint_not_found", 404)
                if (node.version, node.content_hash) != (ref.version, ref.content_hash):
                    raise MemoryRelationError("relation_endpoint_changed")
            source = reader.objects[request.source.key]
            if isinstance(source, MemoryItem) and source.owner_user_id != reader.actor.id:
                sizes = connection.execute("""SELECT length(CAST(payload AS BLOB)) AS size FROM records
                    WHERE collection='permission_policy_rules' ORDER BY created_order LIMIT 1025""").fetchall()
                if (
                    len(sizes) > 1024
                    or any(row["size"] > 65536 for row in sizes)
                    or not reader.spend(
                        sum(row["size"] for row in sizes),
                        len(sizes),
                    )
                ):
                    raise MemoryRelationError("relation_source_write_denied", 403)
                rows = connection.execute(
                    "SELECT payload FROM records WHERE collection='permission_policy_rules' ORDER BY created_order LIMIT 1024"
                ).fetchall()
                try:
                    rules = [PermissionPolicyRule.model_validate_json(row["payload"]) for row in rows]
                except (ValueError, TypeError, RecursionError) as error:
                    raise MemoryRelationError("relation_source_write_denied", 403) from error
                if not has_permission(reader.actor, ACTION_MANAGE_TEAM_MEMORY, rules):
                    raise MemoryRelationError("relation_source_write_denied", 403)
            command_hash = canonical_json_sha256(request.model_dump(mode="json"))
            relation_id = "memrel_" + canonical_json_sha256([reader.actor.id, request.command_id])
            relation = MemoryRelation(
                id=relation_id,
                schema_version="memory-relation-v1",
                workspace_id=reader.actor.workspace_id,
                project_id=request.project_id,
                created_by=reader.actor.id,
                from_memory_id=request.source.record_id,
                from_record_type=request.source.record_type,
                to_source_id=request.target.record_id,
                target_record_type=request.target.record_type,
                source_version=request.source.version,
                source_hash=request.source.content_hash,
                target_version=request.target.version,
                target_hash=request.target.content_hash,
                evidence_record_type=request.evidence.record_type,
                evidence_id=request.evidence.record_id,
                evidence_version=request.evidence.version,
                evidence_hash=request.evidence.content_hash,
                relation_type=request.relation_type,
                assertion=request.assertion,
                command_hash=command_hash,
            )
            row = connection.execute(
                """SELECT CASE WHEN length(CAST(payload AS BLOB))<=16384
                THEN payload END AS payload FROM records WHERE collection='memory_relations' AND id=?""",
                (relation_id,),
            ).fetchone()
            if row is not None:
                if row["payload"] is None or not reader.spend(len(row["payload"].encode())):
                    raise MemoryRelationError("relation_command_conflict")
                try:
                    existing = MemoryRelation.model_validate_json(row["payload"])
                except (ValueError, TypeError, RecursionError) as error:
                    raise MemoryRelationError("relation_command_conflict") from error
                if existing.model_dump(exclude={"created_at"}) != relation.model_dump(exclude={"created_at"}):
                    raise MemoryRelationError("relation_command_conflict")
                return existing
            audit = AuditEvent(
                actor=reader.actor.id,
                action="create_memory_relation",
                target_type="memory_relation",
                target_id=relation.id,
                workspace_id=reader.actor.workspace_id,
                project_id=request.project_id,
                metadata={"relation_type": request.relation_type, "assertion": request.assertion},
            )
            for collection, record in (("memory_relations", relation), ("audit_events", audit)):
                connection.execute(
                    "INSERT INTO records(collection,id,payload) VALUES (?,?,?)",
                    (collection, record.id, record.model_dump_json()),
                )
        return relation

    def query(self, request: MemoryRelationQueryV1, user: User) -> MemoryRelationGraphV1:
        graph = MemoryRelationGraphV1(project_id=request.project_id, root_key=request.root.key, snapshot_at=now_utc())
        with closing(self.repository._read_connect()) as connection, connection:
            connection.execute("BEGIN")
            reader = _RelationReader(connection, user, request.project_id)
            root = reader.node(request.root, 0)
            if root is None:
                raise MemoryRelationError("relation_root_not_found", 404)
            graph.nodes.append(root)
            visited, edges, queue = {root.key}, set(), deque([root])
            while queue:
                current = queue.popleft()
                if current.depth >= request.max_hops:
                    continue
                for ref, edge in reader.neighbors(current):
                    if edge.id in edges:
                        continue
                    target = reader.node(ref, current.depth + 1)
                    if target is None:
                        continue
                    is_new = target.key not in visited
                    if len(graph.edges) >= request.max_edges or (is_new and len(graph.nodes) >= request.max_nodes):
                        reader.diagnostics.add("edge_limit" if len(graph.edges) >= request.max_edges else "node_limit")
                        continue
                    trial = graph.model_copy(
                        update={
                            "nodes": [*graph.nodes, *([target] if is_new else [])],
                            "edges": [*graph.edges, edge],
                            "truncated": True,
                            "diagnostics": [
                                "candidate_limit",
                                "read_limit",
                                "node_limit",
                                "edge_limit",
                                "output_limit",
                            ],
                        }
                    )
                    if len(trial.model_dump_json()) > request.max_chars:
                        reader.diagnostics.add("output_limit")
                        continue
                    graph.edges.append(edge)
                    edges.add(edge.id)
                    if is_new:
                        graph.nodes.append(target)
                        visited.add(target.key)
                        queue.append(target)
            graph.diagnostics = sorted(reader.diagnostics)
            graph.truncated = bool(graph.diagnostics)
        return graph
