from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import threading
import unicodedata
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as dt_date
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from agentmesh.agent_run_identity import (
    agent_run_create_request_hash_for_run,
    agent_run_create_request_matches,
)
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256, strict_json_loads
from agentmesh.deepsearch.budget import (
    DeepSearchBudgetMutationResult,
    DeepSearchBudgetScope,
)
from agentmesh.models import (
    ActivityLog,
    Agent,
    AgentMemoryBinding,
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    AgentRunEvent,
    AgentRunStatus,
    AgentToolGrant,
    Artifact,
    ArtifactVerificationState,
    AuditEvent,
    AuthCredential,
    AuthSession,
    AutoBlackboardPostRequest,
    BlackboardPost,
    BlackboardPostType,
    ChatMessage,
    ChatResponse,
    ChatThread,
    ChatTurnReceipt,
    ChatTurnReceiptStatus,
    ChatTurnTrace,
    ConsentGrant,
    ContributionPoint,
    DeepSearchBudgetReservationV1,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    DeepSearchEvidenceCoverageV1,
    DeepSearchFinalizationStage,
    DeepSearchReviewOutcomeV1,
    DeepSearchSynthesisV1,
    DeepSearchToolInvocationV1,
    DocumentParseJob,
    DocumentRecord,
    InboxItem,
    LearnedSkill,
    MarketParticipation,
    MemoryItem,
    MemoryLayer,
    MemoryRelation,
    ModelDefinition,
    OrchestrationQuiesceInventoryV1,
    PermissionPolicyRule,
    Project,
    RetrievalMetrics,
    RiskPolicyRule,
    RuntimeToolCallClaimV1,
    RuntimeToolCallOutcomeV1,
    ScheduledAgentTaskDefinition,
    Scope,
    SDKSessionRecord,
    SearchResult,
    SkillBinding,
    SkillCapabilityProfile,
    SkillDefinition,
    SkillNodeResult,
    SkillOrchestrationRequestMode,
    SkillPackage,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSideEffect,
    SkillStatus,
    Source,
    Task,
    Team,
    TeamMembership,
    ToolDefinition,
    User,
    UserMemoryItem,
    UserRole,
    Workspace,
    now_utc,
)
from agentmesh.research_orchestration.contracts import (
    ExecutionAttempt,
    ExecutionPlanVersion,
    InvocationState,
    RequirementVersion,
    ResearchGate,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    ToolInvocation,
    ToolReceipt,
    canonical_sha256,
)
from agentmesh.skill_runtime.universal_policy import universal_retrieval_policy
from agentmesh.vector_index import VectorIndex, VectorState, VectorStatus, VectorWork

if TYPE_CHECKING:
    from agentmesh.deepsearch.contracts import ProblemGraphV1, RequirementVersionV1
    from agentmesh.research_orchestration.api import ResearchOwnerScope
    from agentmesh.research_orchestration.v2_history import WorkflowContext

ModelT = TypeVar("ModelT", bound=BaseModel)

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "data" / "agentmesh.sqlite3"
_SQLITE_BUSY_TIMEOUT_SECONDS = 5.0
_SQLITE_BUSY_TIMEOUT_MS = int(_SQLITE_BUSY_TIMEOUT_SECONDS * 1000)


class BriefConfirmationError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ResearchStoreConflict(RuntimeError):
    """A durable research invariant or compare-and-swap precondition failed."""


class RuntimeToolCallConflict(RuntimeError):
    """A durable Runtime Tool-call identity or state invariant failed."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class DeepSearchRequirementConflict(ResearchStoreConflict):
    """A stable DeepSearch Requirement idempotency or CAS conflict."""

    def __init__(self, code: str, *, current_requirement_version: int | None = None):
        super().__init__(code)
        self.code = code
        self.current_requirement_version = current_requirement_version


class DeepSearchBudgetConflict(ResearchStoreConflict):
    """A stable DeepSearch budget identity, state, capacity, or CAS conflict."""

    def __init__(self, code: str, *, current_budget_version: int | None = None):
        super().__init__(code)
        self.code = code
        self.current_budget_version = current_budget_version


class DeepSearchEvidenceConflict(ResearchStoreConflict):
    """A stable DeepSearch Evidence identity, lineage, or state conflict."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class BriefConfirmationResult:
    inbox_item: InboxItem
    document: DocumentRecord
    memory_item: MemoryItem


@dataclass(frozen=True, slots=True)
class DeepSearchRequirementAppendResult:
    requirement: dict[str, object]
    run: AgentRun
    replayed: bool


@dataclass(frozen=True, slots=True)
class DeepSearchRequirementPrepareResult:
    requirement: dict[str, object] | None
    run: AgentRun
    replayed: bool


@dataclass(frozen=True, slots=True)
class DeepSearchStateSnapshot:
    run: AgentRun
    requirement: dict[str, object] | None
    plan: SkillPlan | None


@dataclass(frozen=True, slots=True)
class DeepSearchEvidenceBatchSaveResult:
    sources: tuple[Source, ...]
    artifacts: tuple[Artifact, ...]
    replayed: bool

# --- FTS5 infrastructure ---

_FTS_COLLECTIONS = frozenset(
    {
        "chat_messages",
        "activity_logs",
        "blackboard_posts",
        "memory_items",
        "user_memory_items",
        "documents",
        "skill_definitions",
        "skill_capability_profiles",
    }
)

_SKILL_FTS_COLLECTIONS = frozenset({"skill_definitions", "skill_capability_profiles"})
_SKILL_DIRECTORY_VECTOR_SIMILARITY_THRESHOLD = 0.4
_UNIVERSAL_RETRIEVAL_POLICY = universal_retrieval_policy()
SKILL_PROFILE_VECTOR_SIMILARITY_THRESHOLD = _UNIVERSAL_RETRIEVAL_POLICY.vector_similarity_millis / 1000
_SKILL_QUERY_EMBEDDING_TIMEOUT_SECONDS = _UNIVERSAL_RETRIEVAL_POLICY.embedding_batch_deadline_ms / 1000

_KNOWLEDGE_FTS_COLLECTIONS = frozenset(_FTS_COLLECTIONS - _SKILL_FTS_COLLECTIONS)

_RESULT_TYPE_COLLECTIONS = {
    "chat_message": "chat_messages",
    "activity_log": "activity_logs",
    "blackboard_evidence": "blackboard_posts",
    "memory_item": "memory_items",
    "user_memory_item": "user_memory_items",
    "document": "documents",
}


def _skill_embedding_index_signature(collection: str) -> str | None:
    if collection not in _SKILL_FTS_COLLECTIONS:
        return None
    from agentmesh.embedding import embedding_index_signature

    return embedding_index_signature()


@dataclass(slots=True)
class _FTSDoc:
    collection: str
    record_id: str
    title: str
    body: str
    scope: str
    workspace_id: str
    project_id: str
    user_id: str
    created_at: str


def _extract_fts_doc(collection: str, item: BaseModel) -> _FTSDoc | None:
    """Extract searchable fields from an item for FTS indexing."""
    if collection not in _FTS_COLLECTIONS:
        return None

    scope = ""
    workspace_id = ""
    project_id = ""
    user_id = ""
    title = ""
    body = ""
    created_at = ""

    if collection == "chat_messages":
        title = "对话记录"
        body = getattr(item, "content", "")
        scope = getattr(item, "scope", "")
        created_at = _dt_str(getattr(item, "created_at", None))
    elif collection == "activity_logs":
        title = getattr(item, "title", "")
        body = getattr(item, "summary", "")
        scope = getattr(item, "scope", "")
        workspace_id = getattr(item, "workspace_id", "") or ""
        project_id = getattr(item, "project_id", "") or ""
        user_id = getattr(item, "user_id", "") or ""
        created_at = _dt_str(getattr(item, "created_at", None))
    elif collection == "blackboard_posts":
        title = getattr(item, "title", "")
        body = getattr(item, "content", "")
        scope = getattr(item, "scope", "")
        created_at = _dt_str(getattr(item, "created_at", None))
    elif collection == "memory_items":
        title = getattr(item, "title", "")
        body = getattr(item, "summary", "")
        scope = getattr(item, "scope", "")
        workspace_id = getattr(item, "workspace_id", "") or ""
        project_id = getattr(item, "project_id", "") or ""
        user_id = getattr(item, "owner_user_id", "") or ""
        created_at = _dt_str(getattr(item, "created_at", None))
    elif collection == "user_memory_items":
        if (
            getattr(item, "source_kind", "") in {"document_import", "document_upload"}
            and getattr(item, "status", "active") != "active"
        ):
            return None
        title = getattr(item, "title", "")
        summary = getattr(item, "summary", "")
        memory_type = getattr(item, "memory_type", "")
        body = f"{summary} {memory_type}"
        scope = getattr(item, "scope", "")
        workspace_id = getattr(item, "workspace_id", "") or ""
        project_id = getattr(item, "project_id", "") or ""
        user_id = getattr(item, "user_id", "") or ""
        created_at = _dt_str(getattr(item, "created_at", None))
    elif collection == "documents":
        title = getattr(item, "title", "")
        file_name = getattr(item, "file_name", "")
        text = getattr(item, "text", "")
        body = f"{file_name} {text[:2000]}"
        scope = str(Scope.PRIVATE)
        workspace_id = getattr(item, "workspace_id", "") or ""
        project_id = getattr(item, "project_id", "") or ""
        user_id = getattr(item, "uploaded_by", "") or ""
        created_at = _dt_str(getattr(item, "created_at", None))
    elif collection == "skill_capability_profiles":
        title = ""
        body = item.search_text()
        scope = Scope.PROJECT.value
        created_at = _dt_str(getattr(item, "updated_at", None))
    elif collection == "skill_definitions":
        from agentmesh.skill_runtime.matching import positive_skill_description

        metadata = getattr(item, "metadata", {})
        body = " ".join(
            part
            for part in (
                getattr(item, "name", ""),
                positive_skill_description(getattr(item, "description", "")),
                *getattr(item, "aliases", []),
                metadata.get("short-description", ""),
                metadata.get("agentmesh-stage", ""),
            )
            if part
        )
        title = getattr(item, "title", "")
        scope = Scope.PROJECT.value
        created_at = _dt_str(getattr(item, "updated_at", None))

    if isinstance(scope, Scope):
        scope = scope.value

    return _FTSDoc(
        collection=collection,
        record_id=getattr(item, "id", ""),
        title=title,
        body=body,
        scope=str(scope),
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        created_at=created_at,
    )


def _dt_str(val: datetime | None) -> str:
    if val is None:
        return ""
    return val.isoformat()


def _build_fts_query(needle: str) -> str:
    """Build a FTS5 MATCH query from user input, escaping special characters."""
    tokens = [f'"{t.replace(chr(34), chr(34) * 2)}"' for t in needle.split() if t]
    if not tokens:
        return f'"{needle}"'
    return " ".join(tokens)


def _can_use_fts_match(needle: str) -> bool:
    """FTS5 trigram silently ignores tokens shorter than 3 chars, causing false positives.
    Only use MATCH when all whitespace-separated tokens are >= 3 chars."""
    tokens = needle.split()
    return bool(tokens) and all(len(t) >= 3 for t in tokens)


_FTS_COLLECTION_MODELS: dict[str, type[BaseModel]] = {
    "chat_messages": ChatMessage,
    "activity_logs": ActivityLog,
    "blackboard_posts": BlackboardPost,
    "memory_items": MemoryItem,
    "user_memory_items": UserMemoryItem,
    "documents": DocumentRecord,
    "skill_definitions": SkillDefinition,
    "skill_capability_profiles": SkillCapabilityProfile,
}


class SQLiteStore:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        enforce_writer_lock: bool = False,
        initialize_schema: bool = True,
    ):
        configured_path = db_path or os.getenv("AGENTMESH_DB_PATH") or DEFAULT_DB_PATH
        self.db_path = Path(configured_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._writer_lock_descriptor: int | None = None
        self._writer_lock_pid: int | None = None
        if enforce_writer_lock:
            self._acquire_writer_lock()
        self.vector_index = VectorIndex(self.db_path)
        self._skill_vector_lock = threading.Lock()
        self._skill_vector_thread: threading.Thread | None = None
        self._skill_vector_rescan_requested = False
        try:
            if initialize_schema:
                self._init_schema()
                self._backfill_artifact_projections()
                self._backfill_fts()
                self._backfill_vec()
        except BaseException:
            self.close()
            raise

    def _acquire_writer_lock(self) -> None:
        lock_path = self.db_path.with_suffix(self.db_path.suffix + ".writer.lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(descriptor)
            raise RuntimeError("sqlite_writer_lock_unavailable") from error
        metadata = json.dumps(
            {
                "database": str(self.db_path.resolve()),
                "pid": os.getpid(),
                "release_id": os.getenv("AGENTMESH_RELEASE_ID", "development"),
            },
            sort_keys=True,
        ).encode("utf-8")
        os.ftruncate(descriptor, 0)
        os.write(descriptor, metadata)
        os.fsync(descriptor)
        self._writer_lock_descriptor = descriptor
        self._writer_lock_pid = os.getpid()

    def _verify_writer_process(self) -> None:
        if self._writer_lock_descriptor is not None and self._writer_lock_pid != os.getpid():
            raise RuntimeError("sqlite_writer_lock_process_mismatch")

    def writer_lock_diagnostics(self) -> dict[str, object]:
        return {
            "enforced": self._writer_lock_descriptor is not None,
            "pid": self._writer_lock_pid,
            "database": str(self.db_path.resolve()),
            "release_id": os.getenv("AGENTMESH_RELEASE_ID", "development"),
        }

    def close(self) -> None:
        descriptor = self._writer_lock_descriptor
        if descriptor is None or self._writer_lock_pid != os.getpid():
            return
        self._writer_lock_descriptor = None
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    def _connect(self) -> sqlite3.Connection:
        self._verify_writer_process()
        connection = sqlite3.connect(self.db_path, timeout=_SQLITE_BUSY_TIMEOUT_SECONDS)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _read_connect(self) -> sqlite3.Connection:
        self._verify_writer_process()
        connection = sqlite3.connect(
            f"{self.db_path.resolve().as_uri()}?mode=ro",
            timeout=_SQLITE_BUSY_TIMEOUT_SECONDS,
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA query_only = ON")
        return connection

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path, timeout=_SQLITE_BUSY_TIMEOUT_SECONDS) as connection:
            connection.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
            journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
            if journal_mode.lower() != "wal":
                raise RuntimeError("SQLite WAL mode is required")
            connection.execute("PRAGMA synchronous = NORMAL")
            self._ensure_schema(connection)

    def _backfill_artifact_projections(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                UPDATE artifacts SET
                    workspace_id = COALESCE(workspace_id, json_extract(payload, '$.workspace_id')),
                    project_id = COALESCE(project_id, json_extract(payload, '$.project_id')),
                    user_id = COALESCE(user_id, json_extract(payload, '$.user_id')),
                    artifact_type = COALESCE(artifact_type, json_extract(payload, '$.artifact_type')),
                    content_type = COALESCE(content_type, json_extract(payload, '$.content_type')),
                    truncated = COALESCE(truncated, json_extract(payload, '$.truncated')),
                    verification_state = COALESCE(verification_state, json_extract(payload, '$.verification_state')),
                    schema_version = COALESCE(schema_version, json_extract(payload, '$.schema_version')),
                    content_hash = COALESCE(content_hash, json_extract(payload, '$.content_hash')),
                    size_bytes = COALESCE(size_bytes, json_extract(payload, '$.size_bytes')),
                    requirement_version_id = COALESCE(
                        requirement_version_id,
                        json_extract(payload, '$.requirement_version_id')
                    ),
                    plan_version_id = COALESCE(plan_version_id, json_extract(payload, '$.plan_version_id')),
                    attempt_id = COALESCE(attempt_id, json_extract(payload, '$.attempt_id')),
                    step_number = COALESCE(step_number, json_extract(payload, '$.step_number')),
                    purged_at = COALESCE(purged_at, json_extract(payload, '$.purged_at')),
                    purged_by = COALESCE(purged_by, json_extract(payload, '$.purged_by')),
                    updated_at = COALESCE(updated_at, json_extract(payload, '$.updated_at'))
                WHERE json_valid(payload)
                  AND (
                      workspace_id IS NULL OR project_id IS NULL OR user_id IS NULL
                      OR artifact_type IS NULL OR content_type IS NULL OR truncated IS NULL
                  )
                """
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        declaration: str,
    ) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            try:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            except sqlite3.OperationalError as error:
                refreshed = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                if column not in refreshed:
                    raise error

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
              collection TEXT NOT NULL,
              id TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_order INTEGER PRIMARY KEY AUTOINCREMENT,
              UNIQUE(collection, id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_records_collection ON records(collection, created_order)"
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_recent
            ON records(
                json_extract(payload, '$.thread_id'),
                json_extract(payload, '$.created_at') DESC,
                id DESC
            )
            WHERE collection = 'chat_messages'
            """
        )
        connection.execute(
            """
            WITH ranked_daily_summaries AS (
                SELECT created_order,
                       ROW_NUMBER() OVER (
                           PARTITION BY
                               json_extract(payload, '$.user_id'),
                               json_extract(payload, '$.project_id'),
                               json_extract(payload, '$.memory_date')
                           ORDER BY created_order DESC
                       ) AS duplicate_rank
                FROM records
                WHERE collection = 'user_memory_items'
                  AND json_extract(payload, '$.memory_type') = 'daily_summary'
                  AND json_extract(payload, '$.status') = 'active'
                  AND json_valid(payload)
            )
            UPDATE records
            SET payload = json_set(payload, '$.status', 'archived')
            WHERE created_order IN (
                SELECT created_order FROM ranked_daily_summaries WHERE duplicate_rank > 1
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_user_daily_summary_unique
            ON records(
                json_extract(payload, '$.user_id'),
                json_extract(payload, '$.project_id'),
                json_extract(payload, '$.memory_date')
            )
            WHERE collection = 'user_memory_items'
              AND json_extract(payload, '$.memory_type') = 'daily_summary'
              AND json_extract(payload, '$.status') = 'active'
            """
        )
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
                collection UNINDEXED,
                record_id UNINDEXED,
                title,
                body,
                scope UNINDEXED,
                workspace_id UNINDEXED,
                project_id UNINDEXED,
                user_id UNINDEXED,
                created_at UNINDEXED,
                tokenize='trigram'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS records_vec (
                collection TEXT NOT NULL,
                record_id TEXT NOT NULL,
                embedding BLOB NOT NULL,
                UNIQUE(collection, record_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_records_vec_collection ON records_vec(collection)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                orchestration_version TEXT NOT NULL DEFAULT 'v1'
            )
            """
        )
        SQLiteStore._ensure_column(
            connection,
            "agent_runs",
            "orchestration_version",
            "TEXT NOT NULL DEFAULT 'v1'",
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_run_receipts (
                user_id TEXT NOT NULL,
                client_turn_id TEXT NOT NULL,
                run_id TEXT NOT NULL UNIQUE,
                PRIMARY KEY(user_id, client_turn_id)
            )
            """
        )
        for trigger_name in (
            "agent_runs_research_writer_guard",
            "research_writer_generation_fence",
            "research_writer_admission_fence_v2",
        ):
            connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS retired_research_run_admission_fence
            BEFORE INSERT ON agent_runs
            WHEN NEW.orchestration_version IN ('research-v2', 'research-v3')
              AND NOT EXISTS (
                  SELECT 1 FROM agent_runs WHERE id = NEW.id
              )
            BEGIN
                SELECT RAISE(ABORT, 'retired research writer is disabled');
            END
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_run_events (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(run_id, sequence)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_run_events_created ON agent_run_events(run_id, created_at)"
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_run_events_tool_call
            ON agent_run_events(json_extract(payload, '$.payload.call_id'), run_id, sequence)
            WHERE json_extract(payload, '$.event_type') IN (
                'tool_call_claimed', 'tool_call_settled',
                'tool_call_abandoned', 'tool_call_outcome_unknown'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS deepsearch_requirement_versions (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                request_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                derived_from_requirement_version_id TEXT,
                schema_version TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, version),
                UNIQUE(run_id, request_key),
                FOREIGN KEY(run_id) REFERENCES agent_runs(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                workspace_id TEXT,
                project_id TEXT,
                user_id TEXT,
                artifact_type TEXT,
                content_type TEXT,
                truncated INTEGER,
                verification_state TEXT,
                schema_version TEXT,
                content_hash TEXT,
                size_bytes INTEGER,
                requirement_version_id TEXT,
                plan_version_id TEXT,
                attempt_id TEXT,
                step_number INTEGER,
                purged_at TEXT,
                purged_by TEXT,
                updated_at TEXT
            )
            """
        )
        for column, declaration in (
            ("workspace_id", "TEXT"),
            ("project_id", "TEXT"),
            ("user_id", "TEXT"),
            ("artifact_type", "TEXT"),
            ("content_type", "TEXT"),
            ("truncated", "INTEGER"),
            ("verification_state", "TEXT"),
            ("schema_version", "TEXT"),
            ("content_hash", "TEXT"),
            ("size_bytes", "INTEGER"),
            ("requirement_version_id", "TEXT"),
            ("plan_version_id", "TEXT"),
            ("attempt_id", "TEXT"),
            ("step_number", "INTEGER"),
            ("purged_at", "TEXT"),
            ("purged_by", "TEXT"),
            ("updated_at", "TEXT"),
        ):
            SQLiteStore._ensure_column(connection, "artifacts", column, declaration)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id, created_at)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_run_kind_state "
            "ON artifacts(run_id, artifact_type, verification_state, created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_verification ON artifacts(verification_state, created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_attempt_step ON artifacts(attempt_id, step_number)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_plan_kind ON artifacts(plan_version_id, artifact_type, created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_run_provenance "
            "ON artifacts(run_id, requirement_version_id, plan_version_id, attempt_id, step_number, created_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_plans (
                id TEXT PRIMARY KEY,
                run_id TEXT UNIQUE NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_skill_plans_status ON skill_plans(status, updated_at)")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_plan_nodes (
                plan_id TEXT NOT NULL,
                id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(plan_id, id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_plan_nodes_status ON skill_plan_nodes(plan_id, status, updated_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_node_results (
                plan_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(plan_id, node_id, attempt)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_node_results_plan ON skill_node_results(plan_id, created_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_workflows (
                run_id TEXT PRIMARY KEY,
                phase TEXT NOT NULL,
                active_gate TEXT NOT NULL,
                active_requirement_version_id TEXT,
                active_plan_version_id TEXT,
                active_attempt_id TEXT,
                state_version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_workflows_state ON research_workflows(phase, active_gate, updated_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_requirement_versions (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, version)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_requirements_run ON research_requirement_versions(run_id, version)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_plan_versions (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                requirement_version_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                plan_hash TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, version),
                UNIQUE(run_id, plan_hash)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_plans_run ON research_plan_versions(run_id, version)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_commands (
                run_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                command_type TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_status INTEGER NOT NULL,
                response_payload TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(run_id, idempotency_key)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_attempts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                plan_version_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                status TEXT NOT NULL,
                lease_owner TEXT,
                lease_token TEXT,
                fencing_epoch INTEGER NOT NULL,
                lease_expires_at TEXT,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(run_id, attempt_number)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_attempts_lease ON research_attempts(status, lease_expires_at)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_research_attempts_one_active "
            "ON research_attempts(run_id) WHERE status IN ('pending', 'running', 'recovery_required')"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_steps (
                attempt_id TEXT NOT NULL,
                step_number INTEGER NOT NULL,
                status TEXT NOT NULL,
                claim_epoch INTEGER NOT NULL,
                result_artifact_id TEXT,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(attempt_id, step_number)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_steps_status ON research_steps(attempt_id, status, step_number)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_tool_invocations (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                plan_version_id TEXT NOT NULL,
                step_number INTEGER NOT NULL,
                operation_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                resolved_input_hash TEXT NOT NULL,
                request_artifact_id TEXT NOT NULL,
                active_attempt_id TEXT NOT NULL,
                state TEXT NOT NULL,
                send_count INTEGER NOT NULL,
                active_send_sequence INTEGER NOT NULL,
                sent_fencing_epoch INTEGER,
                receipt_payload TEXT,
                artifact_id TEXT,
                provider_operation_id TEXT,
                last_sent_at TEXT,
                acknowledged_at TEXT,
                unknown_at TEXT,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(run_id, operation_key)
            )
            """
        )
        for column, declaration in (
            ("resolved_input_hash", "TEXT"),
            ("request_artifact_id", "TEXT"),
            ("active_attempt_id", "TEXT"),
            ("active_send_sequence", "INTEGER NOT NULL DEFAULT 0"),
            ("sent_fencing_epoch", "INTEGER"),
            ("provider_operation_id", "TEXT"),
            ("last_sent_at", "TEXT"),
            ("acknowledged_at", "TEXT"),
            ("unknown_at", "TEXT"),
        ):
            SQLiteStore._ensure_column(connection, "research_tool_invocations", column, declaration)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_invocations_state ON research_tool_invocations(state, updated_at)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_research_invocations_plan_step "
            "ON research_tool_invocations(run_id, plan_version_id, step_number)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_model_call_receipts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                owner_kind TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                call_key TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(owner_kind, owner_id, stage, call_key)
            )
            """
        )
        VectorIndex.ensure_schema(connection)

    def reset(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM records")
            connection.execute("DELETE FROM records_fts")
            connection.execute("DELETE FROM records_vec")
            connection.execute("DELETE FROM vector_states")
            connection.execute("DELETE FROM agent_run_events")
            connection.execute("DELETE FROM agent_run_receipts")
            connection.execute("DELETE FROM deepsearch_requirement_versions")
            connection.execute("DELETE FROM research_model_call_receipts")
            connection.execute("DELETE FROM research_tool_invocations")
            connection.execute("DELETE FROM research_steps")
            connection.execute("DELETE FROM research_attempts")
            connection.execute("DELETE FROM research_commands")
            connection.execute("DELETE FROM research_plan_versions")
            connection.execute("DELETE FROM research_requirement_versions")
            connection.execute("DELETE FROM research_workflows")
            connection.execute("DELETE FROM agent_runs")
            connection.execute("DELETE FROM artifacts")
            connection.execute("DELETE FROM skill_node_results")
            connection.execute("DELETE FROM skill_plan_nodes")
            connection.execute("DELETE FROM skill_plans")

    def _upsert(
        self,
        collection: str,
        item: BaseModel,
        *,
        process_vector: bool = True,
        index_vector: bool = True,
    ) -> None:
        work: VectorWork | None = None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO records(collection, id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(collection, id)
                DO UPDATE SET payload = excluded.payload
                """,
                (collection, item.id, item.model_dump_json()),
            )
            self._sync_fts(connection, collection, item)
            doc = _extract_fts_doc(collection, item)
            if doc is not None:
                if index_vector:
                    work = self.vector_index.prepare(
                        connection,
                        collection,
                        item.id,
                        f"{doc.title} {doc.body}".strip(),
                        index_signature=_skill_embedding_index_signature(collection),
                    )
                else:
                    connection.execute(
                        "DELETE FROM records_vec WHERE collection = ? AND record_id = ?",
                        (collection, item.id),
                    )
                    connection.execute(
                        "DELETE FROM vector_states WHERE collection = ? AND record_id = ?",
                        (collection, item.id),
                    )
            elif collection in _FTS_COLLECTIONS:
                self.vector_index.mark_stale(connection, collection, item.id)

        if work is not None and process_vector:
            from agentmesh.embedding import EMBEDDING_ENABLED

            if EMBEDDING_ENABLED:
                self.vector_index.process(work)

    def _sync_fts(self, connection: sqlite3.Connection, collection: str, item: BaseModel) -> None:
        connection.execute(
            "DELETE FROM records_fts WHERE collection = ? AND record_id = ?",
            (collection, item.id),
        )
        doc = _extract_fts_doc(collection, item)
        if doc is None:
            return
        if collection == "chat_messages":
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("chat_threads", getattr(item, "thread_id", "")),
            ).fetchone()
            if row is not None:
                thread = ChatThread.model_validate_json(row["payload"])
                doc.workspace_id = thread.workspace_id
                doc.project_id = thread.project_id
                doc.user_id = thread.user_id
        elif collection == "blackboard_posts":
            task_row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("tasks", getattr(item, "task_id", "")),
            ).fetchone()
            if task_row is not None:
                task = Task.model_validate_json(task_row["payload"])
                thread_row = connection.execute(
                    "SELECT payload FROM records WHERE collection = ? AND id = ?",
                    ("chat_threads", task.thread_id),
                ).fetchone()
                if thread_row is not None:
                    thread = ChatThread.model_validate_json(thread_row["payload"])
                    doc.workspace_id = thread.workspace_id
                    doc.project_id = thread.project_id
                    doc.user_id = thread.user_id
        connection.execute(
            "INSERT INTO records_fts(collection, record_id, title, body, scope, workspace_id, project_id, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc.collection, doc.record_id, doc.title, doc.body, doc.scope, doc.workspace_id, doc.project_id, doc.user_id, doc.created_at),
        )

    def _backfill_fts(self) -> None:
        """Rebuild FTS index from records if out of sync."""
        with self._connect() as connection:
            placeholders = ",".join(f"'{c}'" for c in _FTS_COLLECTIONS)
            records_count = connection.execute(
                f"SELECT COUNT(*) FROM records WHERE collection IN ({placeholders})"
            ).fetchone()[0]
            fts_count = connection.execute("SELECT COUNT(*) FROM records_fts").fetchone()[0]
            missing_tenant_count = connection.execute(
                """
                SELECT COUNT(*) FROM records_fts
                WHERE collection = 'chat_messages' AND workspace_id = ''
                """
            ).fetchone()[0]
            if fts_count >= records_count and missing_tenant_count == 0:
                return
            connection.execute("DELETE FROM records_fts")
            rows = connection.execute(
                f"SELECT collection, payload FROM records WHERE collection IN ({placeholders}) ORDER BY created_order"
            ).fetchall()
            for row in rows:
                collection = row["collection"]
                payload = row["payload"]
                model_cls = _FTS_COLLECTION_MODELS.get(collection)
                if model_cls is None:
                    continue
                item = model_cls.model_validate_json(payload)
                self._sync_fts(connection, collection, item)

    def _backfill_vec(self) -> None:
        """Register existing vectors and prepare missing work without provider calls in a transaction."""
        from agentmesh.embedding import EMBEDDING_ENABLED

        pending: list[VectorWork] = []
        with self._connect() as connection:
            placeholders = ",".join(f"'{c}'" for c in _FTS_COLLECTIONS)
            rows = connection.execute(
                f"""
                SELECT r.collection, r.id, r.payload,
                       CASE WHEN rv.record_id IS NULL THEN 0 ELSE 1 END AS has_vector,
                       CASE WHEN vs.record_id IS NULL THEN 0 ELSE 1 END AS has_state
                FROM records r
                LEFT JOIN records_vec rv
                  ON rv.collection = r.collection AND rv.record_id = r.id
                LEFT JOIN vector_states vs
                  ON vs.collection = r.collection AND vs.record_id = r.id
                WHERE r.collection IN ({placeholders})
                ORDER BY r.created_order
                """
            ).fetchall()
            for row in rows:
                collection = row["collection"]
                model_cls = _FTS_COLLECTION_MODELS.get(collection)
                if model_cls is None:
                    continue
                item = model_cls.model_validate_json(row["payload"])
                if (
                    collection == "skill_capability_profiles"
                    and isinstance(item, SkillCapabilityProfile)
                    and not item.planner_eligible
                ):
                    connection.execute(
                        "DELETE FROM records_vec WHERE collection = ? AND record_id = ?",
                        (collection, row["id"]),
                    )
                    connection.execute(
                        "DELETE FROM vector_states WHERE collection = ? AND record_id = ?",
                        (collection, row["id"]),
                    )
                    continue
                doc = _extract_fts_doc(collection, item)
                if doc is None:
                    continue
                text = f"{doc.title} {doc.body}".strip()
                if collection not in _SKILL_FTS_COLLECTIONS:
                    if row["has_state"]:
                        continue
                    if row["has_vector"]:
                        self.vector_index.adopt_ready(connection, collection, row["id"], text)
                        continue
                work = self.vector_index.prepare(
                    connection,
                    collection,
                    row["id"],
                    text,
                    index_signature=_skill_embedding_index_signature(collection),
                )
                if work is not None:
                    pending.append(work)

        if EMBEDDING_ENABLED:
            synchronous = [item for item in pending if item.collection not in _SKILL_FTS_COLLECTIONS]
            for work in synchronous[:100]:
                self.vector_index.process(work)
            if any(item.collection in _SKILL_FTS_COLLECTIONS for item in pending):
                self.start_skill_vector_indexing()

    def start_skill_vector_indexing(self) -> None:
        """Process the small Skill vector backlog without blocking application startup."""
        from agentmesh.embedding import EMBEDDING_ENABLED

        if not EMBEDDING_ENABLED:
            return
        with self._skill_vector_lock:
            if self._skill_vector_thread is not None and self._skill_vector_thread.is_alive():
                self._skill_vector_rescan_requested = True
                return
            self._skill_vector_rescan_requested = False
            self._reset_failed_skill_vectors()
            self._skill_vector_thread = threading.Thread(
                target=self._process_skill_vector_backlog,
                name="agentmesh-skill-vector-index",
                daemon=True,
            )
            self._skill_vector_thread.start()

    def _process_skill_vector_backlog(self) -> None:
        while True:
            while work := self._next_skill_vector_work():
                self.vector_index.process(work)
            with self._skill_vector_lock:
                if self._skill_vector_rescan_requested:
                    self._skill_vector_rescan_requested = False
                    self._reset_failed_skill_vectors()
                    continue
                self._skill_vector_thread = None
                return

    def _reset_failed_skill_vectors(self) -> None:
        placeholders = ",".join("?" for _ in _SKILL_FTS_COLLECTIONS)
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE vector_states SET state = ?, error = NULL
                WHERE collection IN ({placeholders}) AND state = ?
                """,
                [VectorState.PENDING.value, *_SKILL_FTS_COLLECTIONS, VectorState.FAILED.value],
            )

    def _next_skill_vector_work(self) -> VectorWork | None:
        placeholders = ",".join("?" for _ in _SKILL_FTS_COLLECTIONS)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT record.collection, record.id, record.payload
                FROM records AS record
                LEFT JOIN vector_states AS state
                  ON state.collection = record.collection AND state.record_id = record.id
                LEFT JOIN records_vec AS vector
                  ON vector.collection = record.collection AND vector.record_id = record.id
                WHERE record.collection IN ({placeholders})
                  AND NOT (
                    record.collection = 'skill_capability_profiles'
                    AND COALESCE(json_extract(record.payload, '$.planner_eligible'), 0) = 0
                  )
                  AND (
                    state.record_id IS NULL
                    OR state.state IN (?, ?)
                    OR (state.state = ? AND vector.record_id IS NULL)
                  )
                ORDER BY record.created_order
                LIMIT 1
                """,
                [
                    *_SKILL_FTS_COLLECTIONS,
                    VectorState.PENDING.value,
                    VectorState.STALE.value,
                    VectorState.READY.value,
                ],
            ).fetchone()
            if row is None:
                return None
            model_cls = _FTS_COLLECTION_MODELS[row["collection"]]
            item = model_cls.model_validate_json(row["payload"])
            doc = _extract_fts_doc(row["collection"], item)
            if doc is None:
                self.vector_index.mark_stale(connection, row["collection"], row["id"])
                return None
            return self.vector_index.prepare(
                connection,
                row["collection"],
                row["id"],
                f"{doc.title} {doc.body}".strip(),
                index_signature=_skill_embedding_index_signature(row["collection"]),
            )

    def _get(self, collection: str, item_id: str, model: type[ModelT]) -> ModelT | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                (collection, item_id),
            ).fetchone()
        if row is None:
            return None
        return model.model_validate_json(row["payload"])

    def _list(self, collection: str, model: type[ModelT]) -> list[ModelT]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM records WHERE collection = ? ORDER BY created_order",
                (collection,),
            ).fetchall()
        return [model.model_validate_json(row["payload"]) for row in rows]

    @property
    def chat_messages(self) -> list[ChatMessage]:
        return self._list("chat_messages", ChatMessage)

    @property
    def workspaces(self) -> list[Workspace]:
        return self._list("workspaces", Workspace)

    @property
    def projects(self) -> list[Project]:
        return self._list("projects", Project)

    @property
    def chat_threads(self) -> list[ChatThread]:
        return self._list("chat_threads", ChatThread)

    @property
    def chat_turn_traces(self) -> list[ChatTurnTrace]:
        return self._list("chat_turn_traces", ChatTurnTrace)


    @property
    def tasks(self) -> list[Task]:
        return self._list("tasks", Task)

    @property
    def blackboard_posts(self) -> list[BlackboardPost]:
        return self._list("blackboard_posts", BlackboardPost)

    @property
    def auto_blackboard_post_requests(self) -> list[AutoBlackboardPostRequest]:
        return self._list("auto_blackboard_post_requests", AutoBlackboardPostRequest)

    @property
    def activity_logs(self) -> list[ActivityLog]:
        return self._list("activity_logs", ActivityLog)

    @property
    def inbox_items(self) -> list[InboxItem]:
        return self._list("inbox_items", InboxItem)

    @property
    def memory_items(self) -> list[MemoryItem]:
        return self._list("memory_items", MemoryItem)

    @property
    def user_memory_items(self) -> list[UserMemoryItem]:
        return self._list("user_memory_items", UserMemoryItem)

    @property
    def sources(self) -> list[Source]:
        return self._list("sources", Source)

    @property
    def documents(self) -> list[DocumentRecord]:
        return self._list("documents", DocumentRecord)

    @property
    def document_parse_jobs(self) -> list[DocumentParseJob]:
        return self._list("document_parse_jobs", DocumentParseJob)

    @property
    def audit_events(self) -> list[AuditEvent]:
        return self._list("audit_events", AuditEvent)

    @property
    def agents(self) -> list[Agent]:
        return self._list("agents", Agent)

    @property
    def tool_definitions(self) -> list[ToolDefinition]:
        return self._list("tool_definitions", ToolDefinition)

    @property
    def skill_definitions(self) -> list[SkillDefinition]:
        return self._list("skill_definitions", SkillDefinition)

    @property
    def skill_capability_profiles(self) -> list[SkillCapabilityProfile]:
        return self._list("skill_capability_profiles", SkillCapabilityProfile)

    @property
    def skill_bindings(self) -> list[SkillBinding]:
        return self._list("skill_bindings", SkillBinding)

    @property
    def skill_packages(self) -> list[SkillPackage]:
        return self._list("skill_packages", SkillPackage)

    @property
    def model_definitions(self) -> list[ModelDefinition]:
        return self._list("model_definitions", ModelDefinition)

    @property
    def risk_policy_rules(self) -> list[RiskPolicyRule]:
        return self._list("risk_policy_rules", RiskPolicyRule)

    @property
    def permission_policy_rules(self) -> list[PermissionPolicyRule]:
        return self._list("permission_policy_rules", PermissionPolicyRule)

    @property
    def scheduled_agent_task_definitions(self) -> list[ScheduledAgentTaskDefinition]:
        return self._list("scheduled_agent_task_definitions", ScheduledAgentTaskDefinition)

    @property
    def agent_tool_grants(self) -> list[AgentToolGrant]:
        return self._list("agent_tool_grants", AgentToolGrant)

    @property
    def users(self) -> list[User]:
        return self._list("users", User)

    @property
    def auth_credentials(self) -> list[AuthCredential]:
        return self._list("auth_credentials", AuthCredential)

    @property
    def auth_sessions(self) -> list[AuthSession]:
        return self._list("auth_sessions", AuthSession)

    @property
    def teams(self) -> list[Team]:
        return self._list("teams", Team)

    @property
    def team_memberships(self) -> list[TeamMembership]:
        return self._list("team_memberships", TeamMembership)

    @property
    def consent_grants(self) -> list[ConsentGrant]:
        return self._list("consent_grants", ConsentGrant)

    @property
    def contribution_points(self) -> list[ContributionPoint]:
        return self._list("contribution_points", ContributionPoint)

    @property
    def memory_relations(self) -> list[MemoryRelation]:
        return self._list("memory_relations", MemoryRelation)

    @property
    def retrieval_metrics(self) -> list[RetrievalMetrics]:
        return self._list("retrieval_metrics", RetrievalMetrics)

    def add_retrieval_metrics(self, metrics: RetrievalMetrics) -> RetrievalMetrics:
        self._upsert("retrieval_metrics", metrics)
        return metrics

    @property
    def learned_skills(self) -> list[LearnedSkill]:
        return self._list("learned_skills", LearnedSkill)

    def add_learned_skill(self, skill: LearnedSkill) -> LearnedSkill:
        self._upsert("learned_skills", skill)
        return skill

    def save_learned_skill(self, skill: LearnedSkill) -> LearnedSkill:
        self._upsert("learned_skills", skill)
        return skill

    def get_learned_skill(self, skill_id: str) -> LearnedSkill | None:
        return self._get("learned_skills", skill_id, LearnedSkill)

    @property
    def agent_memory_bindings(self) -> list[AgentMemoryBinding]:
        return self._list("agent_memory_bindings", AgentMemoryBinding)

    def add_agent_memory_binding(self, binding: AgentMemoryBinding) -> AgentMemoryBinding:
        self._upsert("agent_memory_bindings", binding)
        return binding

    def save_agent_memory_binding(self, binding: AgentMemoryBinding) -> AgentMemoryBinding:
        self._upsert("agent_memory_bindings", binding)
        return binding

    def get_agent_memory_binding(self, binding_id: str) -> AgentMemoryBinding | None:
        return self._get("agent_memory_bindings", binding_id, AgentMemoryBinding)

    def get_binding_for_agent(self, agent_id: str) -> AgentMemoryBinding | None:
        for binding in self.agent_memory_bindings:
            if binding.agent_id == agent_id:
                return binding
        return None

    def search_for_agent(
        self,
        query: str,
        agent_id: str,
        workspace_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> list[SearchResult]:
        """Search with constraints from agent's memory binding."""
        binding = self.get_binding_for_agent(agent_id)
        if binding is None:
            return self.search(
                query,
                {Scope.PRIVATE, Scope.PROJECT, Scope.TEAM_CANDIDATE, Scope.TEAM_ACCEPTED},
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
            )
        allowed_scopes = set(binding.allowed_scopes) if binding.allowed_scopes else {Scope.PRIVATE}
        effective_project = binding.allowed_project_ids[0] if binding.allowed_project_ids else project_id
        results = self.search(
            query,
            allowed_scopes,
            workspace_id=workspace_id,
            project_id=effective_project,
            user_id=user_id,
            max_results=binding.max_results_per_query,
        )
        if binding.allowed_memory_types:
            results = [r for r in results if r.result_type in set(binding.allowed_memory_types)]
        return results

    @property
    def market_participations(self) -> list[MarketParticipation]:
        return self._list("market_participation", MarketParticipation)

    def get_market_participation(self, user_id: str) -> MarketParticipation | None:
        return self._get("market_participation", user_id, MarketParticipation)

    def is_market_participant(self, user_id: str) -> bool:
        record = self.get_market_participation(user_id)
        return bool(record and record.enabled)

    def set_market_participation(self, user_id: str, enabled: bool) -> MarketParticipation:
        record = MarketParticipation(id=user_id, user_id=user_id, enabled=enabled)
        self._upsert("market_participation", record)
        return record

    @staticmethod
    def chat_turn_receipt_id(user_id: str, client_turn_id: str) -> str:
        digest = hashlib.sha256(f"{user_id}\0{client_turn_id}".encode()).hexdigest()
        return f"chat_turn_{digest}"

    def get_chat_turn_receipt(self, user_id: str, client_turn_id: str) -> ChatTurnReceipt | None:
        receipt_id = self.chat_turn_receipt_id(user_id, client_turn_id)
        return self._get("chat_turn_receipts", receipt_id, ChatTurnReceipt)

    def claim_chat_turn_receipt(self, receipt: ChatTurnReceipt) -> tuple[ChatTurnReceipt, bool]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("chat_turn_receipts", receipt.id),
            ).fetchone()
            if row is not None:
                return ChatTurnReceipt.model_validate_json(row["payload"]), False
            connection.execute(
                "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
                ("chat_turn_receipts", receipt.id, receipt.model_dump_json()),
            )
        return receipt, True

    def finish_chat_turn_receipt(
        self,
        receipt: ChatTurnReceipt,
        *,
        status: ChatTurnReceiptStatus,
        response: ChatResponse | None = None,
        error_code: str | None = None,
    ) -> ChatTurnReceipt:
        if status == ChatTurnReceiptStatus.PROCESSING:
            raise ValueError("A chat turn receipt cannot finish in processing state")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("chat_turn_receipts", receipt.id),
            ).fetchone()
            if row is None:
                raise ValueError("Chat turn receipt not found")
            current = ChatTurnReceipt.model_validate_json(row["payload"])
            if current.status != ChatTurnReceiptStatus.PROCESSING:
                return current
            current.status = status
            current.response = response
            current.error_code = error_code
            current.updated_at = now_utc()
            connection.execute(
                "UPDATE records SET payload = ? WHERE collection = ? AND id = ?",
                (current.model_dump_json(), "chat_turn_receipts", current.id),
            )
        return current

    def add_chat_message(self, message: ChatMessage) -> ChatMessage:
        self._upsert("chat_messages", message)
        thread = self.get_chat_thread(message.thread_id)
        if thread is not None:
            thread.updated_at = now_utc()
            self._upsert("chat_threads", thread)
        return message

    def save_workspace(self, workspace: Workspace) -> Workspace:
        self._upsert("workspaces", workspace)
        return workspace

    def save_project(self, project: Project) -> Project:
        self._upsert("projects", project)
        return project

    def add_chat_thread(self, thread: ChatThread) -> ChatThread:
        self._upsert("chat_threads", thread)
        return thread

    def add_chat_turn_trace(self, trace: ChatTurnTrace) -> ChatTurnTrace:
        self._upsert("chat_turn_traces", trace)
        return trace


    def save_chat_thread(self, thread: ChatThread) -> ChatThread:
        self._upsert("chat_threads", thread)
        return thread

    def add_task(self, task: Task) -> Task:
        self._upsert("tasks", task)
        return task

    def save_task(self, task: Task) -> Task:
        self._upsert("tasks", task)
        return task

    def add_blackboard_post(self, post: BlackboardPost) -> BlackboardPost:
        self._upsert("blackboard_posts", post)
        return post

    def enqueue_auto_blackboard_post(self, request: AutoBlackboardPostRequest) -> AutoBlackboardPostRequest:
        self._upsert("auto_blackboard_post_requests", request)
        return request

    def save_auto_blackboard_post_request(
        self,
        request: AutoBlackboardPostRequest,
    ) -> AutoBlackboardPostRequest:
        self._upsert("auto_blackboard_post_requests", request)
        return request

    def add_activity_log(self, log: ActivityLog) -> ActivityLog:
        self._upsert("activity_logs", log)
        return log

    def save_agent(self, agent: Agent) -> Agent:
        self._upsert("agents", agent)
        return agent

    def save_tool_definition(self, tool: ToolDefinition) -> ToolDefinition:
        self._upsert("tool_definitions", tool)
        return tool

    def save_skill_definition(
        self,
        skill: SkillDefinition,
        *,
        defer_vector: bool = False,
    ) -> SkillDefinition:
        self._upsert("skill_definitions", skill, process_vector=not defer_vector)
        return skill

    def save_skill_capability_profile(
        self,
        profile: SkillCapabilityProfile,
        *,
        defer_vector: bool = False,
        index_vector: bool = True,
    ) -> SkillCapabilityProfile:
        self._upsert(
            "skill_capability_profiles",
            profile,
            process_vector=not defer_vector,
            index_vector=index_vector and profile.planner_eligible,
        )
        return profile

    def get_skill_capability_profile(self, skill_id: str) -> SkillCapabilityProfile | None:
        return self._get("skill_capability_profiles", skill_id, SkillCapabilityProfile)

    def delete_skill_capability_profile(self, skill_id: str) -> None:
        collection = "skill_capability_profiles"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM records WHERE collection = ? AND id = ?",
                (collection, skill_id),
            )
            connection.execute(
                "DELETE FROM records_fts WHERE collection = ? AND record_id = ?",
                (collection, skill_id),
            )
            connection.execute(
                "DELETE FROM records_vec WHERE collection = ? AND record_id = ?",
                (collection, skill_id),
            )
            connection.execute(
                "DELETE FROM vector_states WHERE collection = ? AND record_id = ?",
                (collection, skill_id),
            )

    def skill_profile_index_counts(self) -> dict[str, int]:
        """Return aggregate FTS coverage without exposing profile identifiers."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM records
                     WHERE collection = 'skill_capability_profiles') AS records,
                    (SELECT COUNT(*) FROM records_fts
                     WHERE collection = 'skill_capability_profiles') AS indexed,
                    (SELECT COUNT(*) FROM records AS profile
                     WHERE profile.collection = 'skill_capability_profiles'
                       AND NOT EXISTS (
                           SELECT 1 FROM records_fts
                           WHERE collection = 'skill_capability_profiles'
                             AND record_id = profile.id
                       )) AS missing
                """
            ).fetchone()
        return {key: int(row[key]) for key in ("records", "indexed", "missing")}

    def skill_search_index_counts(self) -> dict[str, int]:
        """Return FTS coverage for every collection used by Skill recommendation."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM records
                     WHERE collection IN ('skill_definitions', 'skill_capability_profiles')) AS records,
                    (SELECT COUNT(*) FROM records_fts
                     WHERE collection IN ('skill_definitions', 'skill_capability_profiles')) AS indexed,
                    (SELECT COUNT(*) FROM records AS skill_record
                     WHERE skill_record.collection IN ('skill_definitions', 'skill_capability_profiles')
                       AND NOT EXISTS (
                           SELECT 1 FROM records_fts
                           WHERE collection = skill_record.collection
                             AND record_id = skill_record.id
                       )) AS missing
                """
            ).fetchone()
        return {key: int(row[key]) for key in ("records", "indexed", "missing")}

    def rank_skill_profiles_batch(
        self,
        queries: list[str],
        allowed_skill_ids: set[str],
    ) -> list[tuple[list[str], list[str], list[str]]]:
        """Rank multiple Profile queries with one all-or-nothing embedding request."""
        if not queries:
            return []
        if not allowed_skill_ids:
            return [([], [], []) for _query in queries]
        allowed = sorted(allowed_skill_ids)
        placeholders = ",".join("?" for _ in allowed)
        fts_rankings: list[list[str]] = []
        vector_rankings: list[list[str]] = [[] for _query in queries]
        diagnostics: list[str] = []

        from agentmesh.embedding import EMBEDDING_ENABLED, cosine_similarity, deserialize_embedding, embed_texts
        from agentmesh.tool_runtime.guardrails import redact_sensitive_text

        embedding_future = None
        executor = None
        started = monotonic()
        if EMBEDDING_ENABLED:
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="skill-query-embedding")
            embedding_future = executor.submit(
                embed_texts,
                [redact_sensitive_text(query)[:2000] for query in queries],
                timeout_seconds=_SKILL_QUERY_EMBEDDING_TIMEOUT_SECONDS,
            )
        else:
            diagnostics.append("embedding_unavailable")

        with self._connect() as connection:
            for query in queries:
                chunks: list[str] = []
                for token in re.findall(r"[\w\u3400-\u9fff]+", query.lower()):
                    if 3 <= len(token) <= 8:
                        chunks.append(token)
                    chunks.extend(token[index : index + 3] for index in range(max(0, len(token) - 2)))
                chunks = list(dict.fromkeys(chunks))[:80]
                if not chunks:
                    fts_rankings.append([])
                    continue
                match_query = " OR ".join(f'"{chunk.replace(chr(34), chr(34) * 2)}"' for chunk in chunks)
                rows = connection.execute(
                    f"""
                    SELECT record_id
                    FROM records_fts
                    WHERE records_fts MATCH ?
                      AND collection = 'skill_capability_profiles'
                      AND record_id IN ({placeholders})
                    ORDER BY bm25(records_fts), record_id
                    LIMIT 50
                    """,
                    [match_query, *allowed],
                ).fetchall()
                fts_rankings.append([str(row["record_id"]) for row in rows])

            query_embeddings: list[list[float] | None] | None = None
            if embedding_future is not None:
                remaining = max(0.0, _SKILL_QUERY_EMBEDDING_TIMEOUT_SECONDS - (monotonic() - started))
                try:
                    query_embeddings = embedding_future.result(timeout=remaining)
                except FutureTimeoutError:
                    diagnostics.append("embedding_timeout")
                finally:
                    assert executor is not None
                    executor.shutdown(wait=False, cancel_futures=True)
            if query_embeddings is None or any(value is None for value in query_embeddings):
                if EMBEDDING_ENABLED:
                    diagnostics.append("embedding_unavailable")
            else:
                rows = connection.execute(
                    f"""
                    SELECT rv.record_id, rv.embedding
                    FROM records_vec AS rv
                    JOIN vector_states AS vs
                      ON vs.collection = rv.collection AND vs.record_id = rv.record_id
                    WHERE rv.collection = 'skill_capability_profiles'
                      AND vs.state = ?
                      AND rv.record_id IN ({placeholders})
                    """,
                    [VectorState.READY.value, *allowed],
                ).fetchall()
                indexed: list[tuple[str, list[float]]] = []
                for row in rows:
                    try:
                        indexed.append((str(row["record_id"]), deserialize_embedding(row["embedding"])))
                    except (TypeError, ValueError):
                        diagnostics.append("embedding_index_invalid")
                for query_index, query_embedding in enumerate(query_embeddings):
                    assert query_embedding is not None
                    scores: list[tuple[float, str]] = []
                    for skill_id, indexed_embedding in indexed:
                        if len(indexed_embedding) != len(query_embedding):
                            diagnostics.append("embedding_incompatible")
                            continue
                        score = cosine_similarity(query_embedding, indexed_embedding)
                        if score >= SKILL_PROFILE_VECTOR_SIMILARITY_THRESHOLD:
                            scores.append((score, skill_id))
                    scores.sort(key=lambda item: (-item[0], item[1]))
                    vector_rankings[query_index] = [skill_id for _score, skill_id in scores]

        normalized_diagnostics = list(dict.fromkeys(diagnostics))
        return [
            (fts_rankings[index], vector_rankings[index], normalized_diagnostics)
            for index in range(len(queries))
        ]

    def rank_skill_profiles(
        self,
        query: str,
        allowed_skill_ids: set[str],
    ) -> tuple[list[str], list[str], list[str]]:
        """Return isolated lexical/vector rankings for already-authorized profiles."""
        return self._rank_skill_index(
            query,
            allowed_skill_ids,
            "skill_capability_profiles",
            minimum_vector_similarity=SKILL_PROFILE_VECTOR_SIMILARITY_THRESHOLD,
        )

    def rank_skill_definitions(
        self,
        query: str,
        allowed_skill_ids: set[str],
    ) -> tuple[list[str], list[str], list[str]]:
        """Return safe directory rankings restricted to already-authorized Skills."""
        return self._rank_skill_index(
            query,
            allowed_skill_ids,
            "skill_definitions",
            minimum_vector_similarity=_SKILL_DIRECTORY_VECTOR_SIMILARITY_THRESHOLD,
        )

    def _rank_skill_index(
        self,
        query: str,
        allowed_skill_ids: set[str],
        collection: str,
        *,
        minimum_vector_similarity: float | None,
    ) -> tuple[list[str], list[str], list[str]]:
        if collection not in _SKILL_FTS_COLLECTIONS:
            raise ValueError(f"Unsupported Skill search collection: {collection}")
        if not query.strip() or not allowed_skill_ids:
            return [], [], []
        allowed = sorted(allowed_skill_ids)
        placeholders = ",".join("?" for _ in allowed)
        chunks: list[str] = []
        for token in re.findall(r"[\w\u3400-\u9fff]+", query.lower()):
            if len(token) <= 8 and len(token) >= 3:
                chunks.append(token)
            chunks.extend(token[index : index + 3] for index in range(max(0, len(token) - 2)))
        chunks = list(dict.fromkeys(chunks))[:80]
        fts_ids: list[str] = []
        diagnostics: list[str] = []
        query_embedding = None
        from agentmesh.embedding import EMBEDDING_ENABLED, deserialize_embedding, embed_text, validate_embedding
        from agentmesh.tool_runtime.guardrails import redact_sensitive_text

        if EMBEDDING_ENABLED:
            try:
                raw_embedding = embed_text(
                    redact_sensitive_text(query),
                    timeout_seconds=_SKILL_QUERY_EMBEDDING_TIMEOUT_SECONDS,
                )
                query_embedding = validate_embedding(raw_embedding) if raw_embedding is not None else None
            except (TypeError, ValueError):
                query_embedding = None
            if query_embedding is None:
                diagnostics.append("embedding_unavailable")
        else:
            diagnostics.append("embedding_unavailable")
        with self._connect() as connection:
            if chunks:
                match_query = " OR ".join(f'"{chunk.replace(chr(34), chr(34) * 2)}"' for chunk in chunks)
                rows = connection.execute(
                    f"""
                    SELECT record_id
                    FROM records_fts
                    WHERE records_fts MATCH ?
                      AND collection = ?
                      AND record_id IN ({placeholders})
                    ORDER BY bm25(records_fts), record_id
                    LIMIT 50
                    """,
                    [match_query, collection, *allowed],
                ).fetchall()
                fts_ids = [str(row["record_id"]) for row in rows]
            vector_ids: list[str] = []
            if query_embedding is not None:
                from agentmesh.embedding import cosine_similarity

                rows = connection.execute(
                    f"""
                    SELECT rv.record_id, rv.embedding
                    FROM records_vec AS rv
                    JOIN vector_states AS vs
                      ON vs.collection = rv.collection AND vs.record_id = rv.record_id
                    WHERE rv.collection = ?
                      AND vs.state = ?
                      AND rv.record_id IN ({placeholders})
                    """,
                    [collection, VectorState.READY.value, *allowed],
                ).fetchall()
                scores = []
                for row in rows:
                    try:
                        indexed_embedding = deserialize_embedding(row["embedding"])
                    except (TypeError, ValueError):
                        diagnostics.append("embedding_index_invalid")
                        continue
                    if len(indexed_embedding) != len(query_embedding):
                        diagnostics.append("embedding_incompatible")
                        continue
                    score = cosine_similarity(query_embedding, indexed_embedding)
                    if minimum_vector_similarity is None or score >= minimum_vector_similarity:
                        scores.append((score, str(row["record_id"])))
                scores.sort(reverse=True)
                vector_ids = [skill_id for _score, skill_id in scores]
        return fts_ids, vector_ids, list(dict.fromkeys(diagnostics))

    def get_skill_definition(self, skill_id: str) -> SkillDefinition | None:
        return self._get("skill_definitions", skill_id, SkillDefinition)

    def get_skill_definition_by_name(self, name: str) -> SkillDefinition | None:
        for skill in self.skill_definitions:
            if skill.name == name:
                return skill
        return None

    def save_skill_binding(self, binding: SkillBinding) -> SkillBinding:
        self._upsert("skill_bindings", binding)
        return binding

    def save_skill_package(self, package: SkillPackage) -> SkillPackage:
        self._upsert("skill_packages", package)
        return package

    def get_skill_package(self, package_id: str) -> SkillPackage | None:
        return self._get("skill_packages", package_id, SkillPackage)

    def list_agent_skill_bindings(self, agent_id: str) -> list[SkillBinding]:
        return [binding for binding in self.skill_bindings if binding.agent_id == agent_id]

    def save_sdk_session(self, session: SDKSessionRecord) -> SDKSessionRecord:
        self._upsert("sdk_sessions", session)
        return session

    def get_sdk_session(self, session_id: str) -> SDKSessionRecord | None:
        return self._get("sdk_sessions", session_id, SDKSessionRecord)

    def append_sdk_session_items(
        self,
        session_id: str,
        items: list[dict[str, object]],
        message_ids: list[str] | None = None,
    ) -> SDKSessionRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("sdk_sessions", session_id),
            ).fetchone()
            record = SDKSessionRecord.model_validate_json(row["payload"]) if row is not None else SDKSessionRecord(id=session_id)
            record.items.extend(items)
            if message_ids:
                record.synced_chat_message_ids = list(
                    dict.fromkeys([*record.synced_chat_message_ids, *message_ids])
                )
            record.version += 1
            record.updated_at = now_utc()
            connection.execute(
                """
                INSERT INTO records(collection, id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload
                """,
                ("sdk_sessions", session_id, record.model_dump_json()),
            )
        return record

    def mark_sdk_session_chat_messages(self, session_id: str, message_ids: list[str]) -> SDKSessionRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("sdk_sessions", session_id),
            ).fetchone()
            record = SDKSessionRecord.model_validate_json(row["payload"]) if row is not None else SDKSessionRecord(id=session_id)
            record.synced_chat_message_ids = list(dict.fromkeys([*record.synced_chat_message_ids, *message_ids]))
            record.version += 1
            record.updated_at = now_utc()
            connection.execute(
                """
                INSERT INTO records(collection, id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload
                """,
                ("sdk_sessions", session_id, record.model_dump_json()),
            )
        return record

    def reconcile_sdk_session_messages(
        self,
        session_id: str,
        messages: list[tuple[str, dict[str, object]]],
    ) -> SDKSessionRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("sdk_sessions", session_id),
            ).fetchone()
            record = SDKSessionRecord.model_validate_json(row["payload"]) if row is not None else SDKSessionRecord(id=session_id)
            synced = set(record.synced_chat_message_ids)
            missing = [(message_id, item) for message_id, item in messages if message_id not in synced]
            if missing:
                record.items.extend(item for _message_id, item in missing)
                record.synced_chat_message_ids.extend(message_id for message_id, _item in missing)
                record.synced_chat_message_ids = list(dict.fromkeys(record.synced_chat_message_ids))
                record.version += 1
                record.updated_at = now_utc()
                connection.execute(
                    """
                    INSERT INTO records(collection, id, payload)
                    VALUES (?, ?, ?)
                    ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload
                    """,
                    ("sdk_sessions", session_id, record.model_dump_json()),
                )
        return record

    def replace_sdk_session_items(
        self,
        session_id: str,
        items: list[dict[str, object]],
        *,
        expected_version: int,
    ) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("sdk_sessions", session_id),
            ).fetchone()
            record = SDKSessionRecord.model_validate_json(row["payload"]) if row is not None else SDKSessionRecord(id=session_id)
            if record.version != expected_version:
                return False
            record.items = items
            record.version += 1
            record.updated_at = now_utc()
            connection.execute(
                """
                INSERT INTO records(collection, id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload
                """,
                ("sdk_sessions", session_id, record.model_dump_json()),
            )
        return True

    def pop_sdk_session_item(self, session_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("sdk_sessions", session_id),
            ).fetchone()
            if row is None:
                return None
            record = SDKSessionRecord.model_validate_json(row["payload"])
            if not record.items:
                return None
            item = record.items.pop()
            record.version += 1
            record.updated_at = now_utc()
            connection.execute(
                "UPDATE records SET payload = ? WHERE collection = ? AND id = ?",
                (record.model_dump_json(), "sdk_sessions", session_id),
            )
        return item

    def clear_sdk_session(self, session_id: str) -> SDKSessionRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("sdk_sessions", session_id),
            ).fetchone()
            record = SDKSessionRecord.model_validate_json(row["payload"]) if row is not None else SDKSessionRecord(id=session_id)
            record.items = []
            record.version += 1
            record.updated_at = now_utc()
            connection.execute(
                """
                INSERT INTO records(collection, id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload
                """,
                ("sdk_sessions", session_id, record.model_dump_json()),
            )
        return record

    @staticmethod
    def _is_retired_research_run(run: AgentRun, stored_version: str | None = None) -> bool:
        retired_versions = {"research-v2", "research-v3"}
        return run.orchestration_version in retired_versions or stored_version in retired_versions

    @staticmethod
    def _agent_run_creation_identity_matches(current: AgentRun, updated: AgentRun) -> bool:
        fields = (
            "id",
            "thread_id",
            "user_id",
            "workspace_id",
            "project_id",
            "input_text",
            "client_turn_id",
            "skill_id",
            "skill_name",
            "retry_of_run_id",
            "planning_mode",
            "planning_contract_version",
            "create_request_hash",
            "orchestration_version",
            "orchestration_mode",
            "requested_orchestration_mode",
        )
        return all(getattr(current, field) == getattr(updated, field) for field in fields)

    @classmethod
    def _require_agent_run_creation_identity(cls, current: AgentRun, updated: AgentRun) -> None:
        if not cls._agent_run_creation_identity_matches(current, updated):
            raise ResearchStoreConflict("Agent run creation identity is immutable")

    @staticmethod
    def _decode_agent_run_row(row: sqlite3.Row) -> AgentRun:
        run = AgentRun.model_validate_json(row["payload"])
        stored_version = row["orchestration_version"]
        if stored_version in {"research-v2", "research-v3"} and stored_version != run.orchestration_version:
            return run.model_copy(update={"orchestration_version": stored_version})
        return run

    @staticmethod
    def _decode_deepsearch_requirement_row(row: sqlite3.Row) -> dict[str, object]:
        try:
            requirement = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError) as error:
            raise ResearchStoreConflict("DeepSearch Requirement failed integrity verification") from error
        if not isinstance(requirement, dict):
            raise ResearchStoreConflict("DeepSearch Requirement failed integrity verification")
        from agentmesh.deepsearch.contracts import RequirementVersionV1

        try:
            requirement = RequirementVersionV1.model_validate(requirement).model_dump(mode="json")
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch Requirement failed integrity verification") from error
        projections = {
            "id": row["id"],
            "run_id": row["run_id"],
            "version": row["version"],
            "request_key": row["request_key"],
            "request_hash": row["request_hash"],
            "content_hash": row["content_hash"],
            "derived_from_requirement_version_id": row["derived_from_requirement_version_id"],
            "schema_version": row["schema_version"],
            "created_at": row["created_at"],
        }
        if any(requirement.get(key) != value for key, value in projections.items()):
            raise ResearchStoreConflict("DeepSearch Requirement failed integrity verification")
        return requirement

    @staticmethod
    def _validate_deepsearch_requirement_events(
        events: list[tuple[str, dict[str, object]]],
        *,
        requirement: dict[str, object],
        previous_requirement: dict[str, object] | None,
        next_run_status: AgentRunStatus,
        error_code: str | None,
    ) -> list[tuple[str, dict[str, object]]]:
        requirement_payload = requirement["payload"]
        if not isinstance(requirement_payload, dict):
            raise ResearchStoreConflict("DeepSearch Requirement event payload is invalid")
        questions = requirement_payload["clarification_questions"]
        history = requirement_payload["clarification_history"]
        if not isinstance(questions, list) or not isinstance(history, list):
            raise ResearchStoreConflict("DeepSearch Requirement event payload is invalid")

        common_values = {
            "requirement_version_id": requirement["id"],
            "requirement_version": requirement["version"],
            "content_hash": requirement["content_hash"],
        }
        expected: list[tuple[str, dict[str, object]]] = []
        if previous_requirement is None:
            expected.append(("deepsearch_requirement_created", common_values))
        else:
            previous_payload = previous_requirement["payload"]
            if not isinstance(previous_payload, dict) or not history:
                raise ResearchStoreConflict("DeepSearch Requirement event payload is invalid")
            latest_history = history[-1]
            if not isinstance(latest_history, dict) or not isinstance(latest_history.get("answers"), dict):
                raise ResearchStoreConflict("DeepSearch Requirement event payload is invalid")
            expected.append(
                (
                    "deepsearch_clarification_answered",
                    {
                        **common_values,
                        "clarification_round": previous_payload["clarification_round"],
                        "answer_count": len(latest_history["answers"]),
                    },
                )
            )
        if questions:
            expected.append(
                (
                    "deepsearch_clarification_requested",
                    {
                        **common_values,
                        "clarification_round": requirement_payload["clarification_round"],
                        "question_count": len(questions),
                    },
                )
            )
        if next_run_status is AgentRunStatus.FAILED:
            expected.append(("run_failed", {"error_code": error_code}))

        if events:
            events_match = len(events) == len(expected) and all(
                actual_type == expected_type
                and actual_payload.keys() == expected_payload.keys()
                and all(
                    type(actual_payload[key]) is type(expected_value)
                    and actual_payload[key] == expected_value
                    for key, expected_value in expected_payload.items()
                )
                for (actual_type, actual_payload), (expected_type, expected_payload) in zip(
                    events,
                    expected,
                    strict=True,
                )
            )
            if not events_match:
                raise ResearchStoreConflict("DeepSearch Requirement event payload is invalid")
        return expected

    @staticmethod
    def _validate_deepsearch_requirement_history(
        *,
        run_id: str,
        requirement: object,
        previous_requirement: dict[str, object] | None,
    ) -> None:
        if previous_requirement is None:
            return

        from agentmesh.deepsearch.contracts import (
            RequirementVersionV1,
            clarification_request_hash,
            normalize_clarification_answers,
        )

        try:
            current = RequirementVersionV1.model_validate(requirement)
            previous = RequirementVersionV1.model_validate(previous_requirement)
            history = current.payload.clarification_history
            if len(history) != len(previous.payload.clarification_history) + 1:
                raise ValueError("clarification history did not append exactly one round")
            if history[:-1] != previous.payload.clarification_history:
                raise ValueError("clarification history prefix changed")
            latest = history[-1]
            if (
                latest.round != previous.payload.clarification_round
                or latest.questions != previous.payload.clarification_questions
            ):
                raise ValueError("clarification history does not answer the previous questions")
            normalized_answers = normalize_clarification_answers(
                questions=previous.payload.clarification_questions,
                answers=latest.answers,
            )
            expected_request_hash = clarification_request_hash(
                run_id=run_id,
                expected_requirement_version=previous.version,
                normalized_answers=normalized_answers,
            )
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch Requirement history is invalid") from error
        if current.request_hash != expected_request_hash:
            raise ResearchStoreConflict("DeepSearch Requirement request identity is invalid")

    @classmethod
    def _deepsearch_requirement_parent(
        cls,
        connection: sqlite3.Connection,
        *,
        run: AgentRun,
        latest_row: sqlite3.Row | None,
        requirement: dict[str, object],
    ) -> str | None:
        if latest_row is not None:
            return str(latest_row["id"])
        if run.retry_of_run_id is None:
            return None

        source_run_row = connection.execute(
            "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
            (run.retry_of_run_id,),
        ).fetchone()
        source_requirement_row = connection.execute(
            """SELECT * FROM deepsearch_requirement_versions
            WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
            (run.retry_of_run_id,),
        ).fetchone()
        if source_run_row is None or source_requirement_row is None:
            raise ResearchStoreConflict("DeepSearch retry Requirement source is invalid")
        source_run = AgentRun.model_validate_json(source_run_row["payload"])
        if (
            source_run_row["orchestration_version"] != "v1"
            or source_run.orchestration_version != "v1"
            or source_run.planning_mode != AgentPlanningMode.DEEPSEARCH
            or source_run.id != run.retry_of_run_id
            or source_run.user_id != run.user_id
            or source_run.workspace_id != run.workspace_id
            or source_run.project_id != run.project_id
        ):
            raise ResearchStoreConflict("DeepSearch retry Requirement source is invalid")
        source_requirement = cls._decode_deepsearch_requirement_row(source_requirement_row)
        if (
            requirement.get("derived_from_requirement_version_id") != source_requirement["id"]
            or requirement.get("schema_version") != source_requirement["schema_version"]
            or requirement.get("content_hash") != source_requirement["content_hash"]
            or requirement.get("payload") != source_requirement["payload"]
        ):
            raise ResearchStoreConflict("DeepSearch retry Requirement clone is invalid")
        return str(source_requirement["id"])

    @staticmethod
    def _write_skill_plan(connection: sqlite3.Connection, plan: SkillPlan) -> None:
        connection.execute(
            """
            INSERT INTO skill_plans(id, run_id, version, status, payload, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                run_id = excluded.run_id,
                version = excluded.version,
                status = excluded.status,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                plan.id,
                plan.run_id,
                plan.version,
                plan.status.value,
                plan.model_dump_json(),
                plan.updated_at.isoformat(),
            ),
        )
        node_ids = [node.id for node in plan.nodes]
        if node_ids:
            placeholders = ",".join("?" for _ in node_ids)
            connection.execute(
                f"DELETE FROM skill_plan_nodes WHERE plan_id = ? AND id NOT IN ({placeholders})",
                [plan.id, *node_ids],
            )
        else:
            connection.execute("DELETE FROM skill_plan_nodes WHERE plan_id = ?", (plan.id,))
        for node in plan.nodes:
            connection.execute(
                """
                INSERT INTO skill_plan_nodes(plan_id, id, status, payload, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(plan_id, id) DO UPDATE SET
                    status = excluded.status,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (plan.id, node.id, node.status.value, node.model_dump_json(), plan.updated_at.isoformat()),
            )

    @staticmethod
    def _append_agent_run_events(
        connection: sqlite3.Connection,
        run_id: str,
        events: list[tuple[str, dict[str, object]]],
    ) -> None:
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM agent_run_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        for event_type, payload in events:
            sequence += 1
            event = AgentRunEvent(run_id=run_id, sequence=sequence, event_type=event_type, payload=payload)
            connection.execute(
                "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
            )

    @staticmethod
    def _resolve_open_run_inboxes(
        connection: sqlite3.Connection,
        run_id: str,
        *,
        reason: str,
        resolved_at: datetime,
    ) -> None:
        rows = connection.execute(
            """
            SELECT payload FROM records
            WHERE collection = 'inbox_items'
              AND json_extract(payload, '$.metadata.run_id') = ?
              AND json_extract(payload, '$.status') = 'open'
            """,
            (run_id,),
        ).fetchall()
        for row in rows:
            item = InboxItem.model_validate_json(row["payload"])
            item.status = "resolved"
            item.acknowledged_at = item.acknowledged_at or resolved_at
            item.resolved_at = resolved_at
            item.updated_at = resolved_at
            item.metadata["approval_failure"] = reason
            connection.execute(
                "UPDATE records SET payload = ? WHERE collection = 'inbox_items' AND id = ?",
                (item.model_dump_json(), item.id),
            )

    @staticmethod
    def _waiting_approval_expired(
        connection: sqlite3.Connection,
        run: AgentRun,
        *,
        checked_at: datetime,
    ) -> bool:
        if run.status != AgentRunStatus.WAITING_APPROVAL:
            return False
        expiries: list[datetime] = []
        if run.deadline_at is not None:
            expiries.append(run.deadline_at)
        raw_expiry = (run.paused_state or {}).get("expires_at")
        if isinstance(raw_expiry, str):
            with suppress(ValueError):
                parsed = datetime.fromisoformat(raw_expiry)
                expiries.append(parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC))
        rows = connection.execute(
            """
            SELECT payload FROM records
            WHERE collection = 'inbox_items'
              AND json_extract(payload, '$.metadata.run_id') = ?
              AND json_extract(payload, '$.status') = 'open'
            """,
            (run.id,),
        ).fetchall()
        expiries.extend(InboxItem.model_validate_json(row["payload"]).created_at + timedelta(hours=24) for row in rows)
        return bool(expiries) and checked_at >= min(expiries)

    @staticmethod
    def _deepsearch_expiration_code(run: AgentRun, *, checked_at: datetime) -> str | None:
        stable_expiration_codes = {
            "deepsearch_run_expired",
            "deepsearch_interaction_expired",
        }
        if run.status is AgentRunStatus.CANCELLED and run.error_code in stable_expiration_codes:
            return run.error_code
        if run.status in {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.PARTIAL,
            AgentRunStatus.FAILED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.CANCELLED,
        }:
            return None
        if run.absolute_expires_at is not None and checked_at >= run.absolute_expires_at:
            return "deepsearch_run_expired"
        if (
            run.status
            in {
                AgentRunStatus.WAITING_CLARIFICATION,
                AgentRunStatus.WAITING_PLAN_APPROVAL,
                AgentRunStatus.WAITING_APPROVAL,
            }
            and run.interaction_expires_at is not None
            and checked_at >= run.interaction_expires_at
        ):
            return "deepsearch_interaction_expired"
        return None


    def _cancel_agent_run_tree_in_transaction(
        self,
        connection: sqlite3.Connection,
        run: AgentRun,
        *,
        stored_version: str,
        reason: str,
        error_code: str | None = None,
        cancelled_at: datetime | None = None,
    ) -> AgentRun:
        if self._is_retired_research_run(run, stored_version):
            return run
        cancelled_at = cancelled_at or now_utc()
        events: list[tuple[str, dict[str, object]]] = []
        tool_claims, tool_outcomes = self._runtime_tool_call_history_in_transaction(
            connection,
            run.id,
        )
        terminal_by_call = {outcome.call_id: outcome for outcome in tool_outcomes}
        unknown_node_ids = {
            claim.node_id
            for claim in tool_claims
            if claim.node_id is not None
            and claim.side_effect != "read"
            and (
                claim.call_id not in terminal_by_call
                or terminal_by_call[claim.call_id].outcome != "settled"
            )
        }
        unknown_write = bool(unknown_node_ids) or any(
            claim.node_id is None
            and claim.side_effect != "read"
            and (
                claim.call_id not in terminal_by_call
                or terminal_by_call[claim.call_id].outcome != "settled"
            )
            for claim in tool_claims
        )
        partial = False
        plan_row = connection.execute(
            "SELECT payload FROM skill_plans WHERE run_id = ?",
            (run.id,),
        ).fetchone()
        if plan_row is not None:
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            deepsearch_plan = run.planning_mode is AgentPlanningMode.DEEPSEARCH
            if deepsearch_plan and (
                stored_version != "v1"
                or run.orchestration_version != "v1"
                or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
                or run.plan_id != plan.id
                or plan.run_id != run.id
                or plan.finalization_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED
                or DeepSearchFinalizationStage.TERMINAL_COMMITTED in plan.finalization_input_hashes
                or plan.report_artifact_id is not None
                or plan.report_content_hash is not None
                or run.output_text is not None
            ):
                raise ResearchStoreConflict("DeepSearch cancellation state is invalid")
            terminal_nodes = {
                SkillPlanNodeStatus.COMPLETED,
                SkillPlanNodeStatus.FAILED,
                SkillPlanNodeStatus.SKIPPED,
                SkillPlanNodeStatus.CANCELLED,
            }
            for node in plan.nodes:
                if node.status in terminal_nodes:
                    continue
                if node.id in unknown_node_ids:
                    node.status = SkillPlanNodeStatus.FAILED
                    node.error_code = "external_outcome_unknown"
                    event_type = "node_failed"
                else:
                    node.status = SkillPlanNodeStatus.CANCELLED
                    event_type = "node_cancelled"
                node.completed_at = cancelled_at
                events.append(
                    (
                        event_type,
                        {
                            "plan_id": plan.id,
                            "node_id": node.id,
                            "error_code": node.error_code,
                        },
                    )
                )
            if unknown_write and plan.candidate_snapshot is not None:
                from agentmesh.skill_runtime.universal_plan import has_valid_partial_delivery

                result_rows = connection.execute(
                    """
                    SELECT payload FROM skill_node_results
                    WHERE plan_id = ? ORDER BY created_at, node_id, attempt
                    """,
                    (plan.id,),
                ).fetchall()
                partial = has_valid_partial_delivery(
                    plan=plan,
                    results=[
                        SkillNodeResult.model_validate_json(result_row["payload"])
                        for result_row in result_rows
                    ],
                )
            plan.status = (
                SkillPlanStatus.PARTIAL
                if partial
                else SkillPlanStatus.FAILED
                if unknown_write
                else SkillPlanStatus.CANCELLED
            )
            if deepsearch_plan:
                from agentmesh.artifacts import ArtifactAccessError, V1VerifiedArtifactStore

                staging_rows = connection.execute(
                    """SELECT payload FROM artifacts
                    WHERE run_id = ?
                      AND plan_version_id = ?
                      AND artifact_type = 'deepsearch_report'
                      AND verification_state = ?""",
                    (
                        run.id,
                        f"{plan.id}:v{plan.version}",
                        ArtifactVerificationState.STAGING.value,
                    ),
                ).fetchall()
                try:
                    artifact_store = V1VerifiedArtifactStore(self)
                    for row in staging_rows:
                        staging_report = Artifact.model_validate_json(row["payload"])
                        artifact_store.fail_report(
                            staging_report.model_copy(
                                update={
                                    "verification_state": ArtifactVerificationState.FAILED,
                                    "updated_at": cancelled_at,
                                }
                            ),
                            connection=connection,
                        )
                except (ArtifactAccessError, TypeError, ValueError) as error:
                    raise ResearchStoreConflict(
                        "DeepSearch cancellation report state is invalid"
                    ) from error
                previous_stage = plan.finalization_stage
                terminal_input_hash = canonical_json_sha256(
                    {
                        "kind": "deepsearch-cancel-without-report-v1",
                        "run_id": run.id,
                        "plan_id": plan.id,
                        "plan_version": plan.version,
                        "finalization_stage": previous_stage.value,
                        "finalization_version": plan.finalization_version,
                        "reason": reason,
                        "error_code": error_code,
                    }
                )
                plan.finalization_stage = DeepSearchFinalizationStage.TERMINAL_COMMITTED
                plan.finalization_version += 1
                plan.finalization_input_hashes = {
                    **plan.finalization_input_hashes,
                    DeepSearchFinalizationStage.TERMINAL_COMMITTED: terminal_input_hash,
                }
                events.append(
                    (
                        "deepsearch_finalization_stage_changed",
                        {
                            "plan_id": plan.id,
                            "from_stage": previous_stage.value,
                            "to_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED.value,
                            "finalization_version": plan.finalization_version,
                            "input_hash": terminal_input_hash,
                        },
                    )
                )
            plan.updated_at = cancelled_at
            plan = SkillPlan.model_validate(plan.model_dump(mode="python"))
            self._write_skill_plan(connection, plan)
        if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
            run.deepsearch_budget = self._close_deepsearch_budget_for_terminal(run)
        run.status = (
            AgentRunStatus.PARTIAL
            if partial
            else AgentRunStatus.FAILED
            if unknown_write
            else AgentRunStatus.CANCELLED
        )
        run.paused_state = None
        run.interaction_expires_at = None
        if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
            run.output_text = None
        run.error_code = (
            "external_outcome_unknown" if unknown_write else error_code
        )
        run.updated_at = cancelled_at
        connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (run.model_dump_json(), cancelled_at.isoformat(), run.id),
        )
        self._resolve_open_run_inboxes(
            connection,
            run.id,
            reason=reason,
            resolved_at=cancelled_at,
        )
        events.append(
            (
                "run_partially_completed"
                if run.status is AgentRunStatus.PARTIAL
                else "run_failed"
                if run.status is AgentRunStatus.FAILED
                else "run_cancelled",
                (
                    {"reason": reason, "error_code": run.error_code}
                    if run.status is not AgentRunStatus.CANCELLED
                    else {"reason": reason}
                ),
            )
        )
        self._append_agent_run_events(connection, run.id, events)
        return run

    def create_standard_planning_skeleton(
        self,
        *,
        run_id: str,
        plan: SkillPlan,
    ) -> tuple[SkillPlan, AgentRun] | None:
        if (
            plan.run_id != run_id
            or plan.status is not SkillPlanStatus.PLANNING
            or plan.nodes
            or plan.candidate_snapshot is None
            or plan.planning_mode is not AgentPlanningMode.STANDARD
        ):
            raise RuntimeError("standard_planning_skeleton_invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            existing_plan = connection.execute(
                "SELECT id FROM skill_plans WHERE id = ? OR run_id = ?",
                (plan.id, run_id),
            ).fetchone()
            if row is None or existing_plan is not None:
                return None
            run = self._decode_agent_run_row(row)
            if (
                run.status is not AgentRunStatus.PLANNING
                or run.plan_id is not None
                or run.planning_mode is not AgentPlanningMode.STANDARD
                or run.planning_contract_version
                is not AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
                or run.execution_contract_version != plan.execution_contract_version
            ):
                return None
            self._write_skill_plan(connection, plan)
            run.plan_id = plan.id
            run.updated_at = now_utc()
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), run.updated_at.isoformat(), run.id),
            )
            self._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "candidate_snapshot_created",
                        {
                            "plan_id": plan.id,
                            "plan_version": plan.version,
                            "candidate_snapshot_hash": plan.candidate_snapshot.content_hash,
                            "candidate_count": len(plan.candidate_snapshot.candidates),
                        },
                    )
                ],
            )
            return plan, run

    def complete_standard_planning_skeleton(
        self,
        *,
        plan: SkillPlan,
        expected_version: int,
        next_run_status: AgentRunStatus,
        events: list[tuple[str, dict[str, object]]],
    ) -> tuple[SkillPlan, AgentRun] | None:
        if (
            plan.status not in {SkillPlanStatus.WAITING_APPROVAL, SkillPlanStatus.APPROVED}
            or plan.candidate_snapshot is None
            or not plan.nodes
            or next_run_status not in {
                AgentRunStatus.WAITING_PLAN_APPROVAL,
                AgentRunStatus.RUNNING,
            }
        ):
            raise RuntimeError("standard_planning_completion_invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute(
                "SELECT payload FROM skill_plans WHERE id = ?",
                (plan.id,),
            ).fetchone()
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (plan.run_id,),
            ).fetchone()
            if plan_row is None or run_row is None:
                return None
            current = SkillPlan.model_validate_json(plan_row["payload"])
            run = self._decode_agent_run_row(run_row)
            if (
                current.status is not SkillPlanStatus.PLANNING
                or current.version != expected_version
                or current.candidate_snapshot != plan.candidate_snapshot
                or run.status is not AgentRunStatus.PLANNING
                or run.plan_id != plan.id
                or run.planning_contract_version
                is not AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
                or current.execution_contract_version != run.execution_contract_version
                or plan.execution_contract_version != current.execution_contract_version
            ):
                return None
            plan.version = expected_version + 1
            plan.updated_at = now_utc()
            self._write_skill_plan(connection, plan)
            run.status = next_run_status
            run.updated_at = plan.updated_at
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), run.updated_at.isoformat(), run.id),
            )
            self._append_agent_run_events(connection, run.id, events)
            return plan, run

    def fail_standard_planning_skeleton(
        self,
        *,
        run_id: str,
        plan_id: str,
        error_code: str,
    ) -> tuple[SkillPlan, AgentRun] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute(
                "SELECT payload FROM skill_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if plan_row is None or run_row is None:
                return None
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            run = self._decode_agent_run_row(run_row)
            if (
                plan.run_id != run.id
                or plan.status is not SkillPlanStatus.PLANNING
                or run.status is not AgentRunStatus.PLANNING
                or run.plan_id != plan.id
            ):
                return None
            now = now_utc()
            plan.status = SkillPlanStatus.FAILED
            plan.degradation = error_code
            plan.updated_at = now
            run.status = AgentRunStatus.FAILED
            run.error_code = error_code
            run.updated_at = now
            self._write_skill_plan(connection, plan)
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), now.isoformat(), run.id),
            )
            self._append_agent_run_events(
                connection,
                run.id,
                [("plan_planning_failed", {"plan_id": plan.id, "error_code": error_code})],
            )
            return plan, run

    def save_skill_plan(self, plan: SkillPlan) -> SkillPlan:
        if plan.planning_mode is AgentPlanningMode.DEEPSEARCH:
            raise ResearchStoreConflict("DeepSearch Plans require dedicated persistence methods")
        with self._connect() as connection:
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (plan.run_id,),
            ).fetchone()
            if run_row is not None:
                run = AgentRun.model_validate_json(run_row["payload"])
                if self._is_retired_research_run(run, run_row["orchestration_version"]):
                    raise ResearchStoreConflict("research-v2 runs are historical and read-only")
                if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
                    raise ResearchStoreConflict("DeepSearch Plans require dedicated persistence methods")
                if (
                    run.planning_contract_version
                    is AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
                ) != (plan.candidate_snapshot is not None):
                    raise ResearchStoreConflict("Standard Plan contract and Candidate Snapshot disagree")
                if run.execution_contract_version != plan.execution_contract_version:
                    raise ResearchStoreConflict("Standard execution contract marker disagrees")
            plan.updated_at = now_utc()
            self._write_skill_plan(connection, plan)
        return plan

    def compare_and_swap_skill_plan(
        self,
        plan: SkillPlan,
        *,
        expected_version: int,
        events: list[tuple[str, dict[str, object]]] | None = None,
    ) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan.id,)).fetchone()
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (plan.run_id,),
            ).fetchone()
            if row is None or run_row is None:
                return False
            current = SkillPlan.model_validate_json(row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
            if (
                current.planning_mode is AgentPlanningMode.DEEPSEARCH
                or plan.planning_mode is AgentPlanningMode.DEEPSEARCH
                or run.planning_mode is AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("DeepSearch Plans require dedicated persistence methods")
            if (
                self._is_retired_research_run(run, run_row["orchestration_version"])
                or current.run_id != run.id
                or current.version != expected_version
                or current.status != SkillPlanStatus.WAITING_APPROVAL
                or plan.status != SkillPlanStatus.WAITING_APPROVAL
                or run.status != AgentRunStatus.WAITING_PLAN_APPROVAL
                or current.execution_contract_version != plan.execution_contract_version
                or run.execution_contract_version != plan.execution_contract_version
            ):
                return False
            plan.version = expected_version + 1
            plan.updated_at = now_utc()
            self._write_skill_plan(connection, plan)
            self._append_agent_run_events(connection, plan.run_id, events or [])
        return True

    def transition_skill_plan_and_run(
        self,
        *,
        plan_id: str,
        run_id: str,
        expected_version: int,
        expected_plan_status: SkillPlanStatus,
        expected_run_status: AgentRunStatus,
        next_plan_status: SkillPlanStatus,
        next_run_status: AgentRunStatus,
        events: list[tuple[str, dict[str, object]]],
        output_text: str | None = None,
    ) -> tuple[SkillPlan, AgentRun] | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan_id,)).fetchone()
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if plan_row is None or run_row is None:
                return None
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
            deepsearch = (
                plan.planning_mode is AgentPlanningMode.DEEPSEARCH
                or run.planning_mode is AgentPlanningMode.DEEPSEARCH
            )
            if deepsearch and (
                run_row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
                or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
                or run.plan_id != plan.id
                or expected_plan_status is not SkillPlanStatus.WAITING_APPROVAL
                or expected_run_status is not AgentRunStatus.WAITING_PLAN_APPROVAL
                or next_plan_status is not SkillPlanStatus.REJECTED
                or next_run_status is not AgentRunStatus.REJECTED
                or [event_type for event_type, _payload in events]
                != ["plan_rejected", "run_rejected"]
            ):
                raise ResearchStoreConflict("DeepSearch Plans require dedicated transitions")
            if (
                self._is_retired_research_run(run, run_row["orchestration_version"])
                or plan.run_id != run.id
                or plan.version != expected_version
                or plan.status != expected_plan_status
                or run.status != expected_run_status
            ):
                return None
            now = now_utc()
            if deepsearch:
                run.deepsearch_budget = self._close_deepsearch_budget_for_terminal(run)
            plan.version += 1
            plan.status = next_plan_status
            plan.updated_at = now
            run.status = next_run_status
            run.output_text = output_text
            run.updated_at = now
            self._write_skill_plan(connection, plan)
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), now.isoformat(), run.id),
            )
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM agent_run_events WHERE run_id = ?",
                (run.id,),
            ).fetchone()[0]
            for event_type, payload in events:
                sequence += 1
                event = AgentRunEvent(run_id=run.id, sequence=sequence, event_type=event_type, payload=payload)
                connection.execute(
                    "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (run.id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
                )
        return plan, run

    def get_skill_plan(self, plan_id: str) -> SkillPlan | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan_id,)).fetchone()
        return SkillPlan.model_validate_json(row["payload"]) if row is not None else None

    def get_skill_plan_for_run(self, run_id: str) -> SkillPlan | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM skill_plans WHERE run_id = ?", (run_id,)).fetchone()
        return SkillPlan.model_validate_json(row["payload"]) if row is not None else None

    @staticmethod
    def _sum_deepsearch_budget_usage(
        usages: list[DeepSearchBudgetUsageV1],
    ) -> DeepSearchBudgetUsageV1:
        return DeepSearchBudgetUsageV1(
            **{
                field: sum(getattr(usage, field) for usage in usages)
                for field in DeepSearchBudgetUsageV1.model_fields
            }
        )

    @classmethod
    def _billed_deepsearch_budget_usage(
        cls,
        reservations: list[DeepSearchBudgetReservationV1],
    ) -> DeepSearchBudgetUsageV1:
        return cls._sum_deepsearch_budget_usage(
            [
                reservation.actual_usage
                if reservation.status == "settled" and reservation.actual_usage is not None
                else reservation.resource_maxima
                for reservation in reservations
            ]
        )

    @staticmethod
    def _deepsearch_budget_usage_matches(
        left: DeepSearchBudgetUsageV1,
        right: DeepSearchBudgetUsageV1,
    ) -> bool:
        return all(
            abs(getattr(left, field) - getattr(right, field)) <= 1e-9
            if field == "active_seconds"
            else getattr(left, field) == getattr(right, field)
            for field in DeepSearchBudgetUsageV1.model_fields
        )

    @classmethod
    def _validate_deepsearch_budget_ledger(cls, budget: DeepSearchBudgetV1) -> None:
        invocation_keys = [reservation.invocation_key for reservation in budget.reservations]
        attempt_keys = [
            (reservation.logical_operation_key, reservation.physical_attempt)
            for reservation in budget.reservations
        ]
        if (
            len(invocation_keys) != len(set(invocation_keys))
            or len(attempt_keys) != len(set(attempt_keys))
            or not cls._deepsearch_budget_usage_matches(
                budget.consumed,
                cls._billed_deepsearch_budget_usage(budget.reservations),
            )
        ):
            raise DeepSearchBudgetConflict("deepsearch_budget_integrity_failed")

        standard_reservations = [
            reservation for reservation in budget.reservations if reservation.scope == "standard"
        ]
        finalization_reservations = [
            reservation for reservation in budget.reservations if reservation.scope == "finalization"
        ]
        standard_usage = cls._billed_deepsearch_budget_usage(standard_reservations)
        finalization_usage = cls._billed_deepsearch_budget_usage(finalization_reservations)
        for field in DeepSearchBudgetUsageV1.model_fields:
            standard_limit = getattr(budget.limits, field)
            finalization_limit = 0
            if field == "active_seconds":
                finalization_limit = budget.finalization_reserve.active_seconds
                standard_limit -= finalization_limit
            elif field == "artifact_bytes":
                finalization_limit = budget.finalization_reserve.artifact_bytes
                standard_limit -= finalization_limit
            standard_value = getattr(standard_usage, field)
            finalization_value = getattr(finalization_usage, field)
            tolerance = 1e-9 if field == "active_seconds" else 0
            if standard_value - standard_limit > tolerance:
                raise DeepSearchBudgetConflict("deepsearch_budget_exhausted")
            if finalization_value - finalization_limit > tolerance:
                code = (
                    "deepsearch_budget_scope_invalid"
                    if finalization_limit == 0 and finalization_value > 0
                    else "deepsearch_budget_exhausted"
                )
                raise DeepSearchBudgetConflict(code)

    @classmethod
    def _load_deepsearch_budget_run_in_transaction(
        cls,
        connection: sqlite3.Connection,
        *,
        run_id: str,
    ) -> AgentRun:
        row = connection.execute(
            "SELECT id, payload, orchestration_version FROM agent_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise DeepSearchBudgetConflict("deepsearch_budget_run_not_found")
        try:
            run = AgentRun.model_validate_json(row["payload"])
        except (TypeError, ValueError) as error:
            raise DeepSearchBudgetConflict("deepsearch_budget_integrity_failed") from error
        if (
            row["id"] != run.id
            or row["orchestration_version"] != "v1"
            or run.orchestration_version != "v1"
            or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            or run.deepsearch_budget is None
        ):
            raise DeepSearchBudgetConflict("deepsearch_budget_run_invalid")
        cls._validate_deepsearch_budget_ledger(run.deepsearch_budget)
        return run

    @staticmethod
    def _deepsearch_budget_status_allowed(
        run: AgentRun,
        *,
        scope: DeepSearchBudgetScope,
        checked_at: datetime,
    ) -> bool:
        if run.absolute_expires_at is not None and checked_at >= run.absolute_expires_at:
            return False
        if scope == "finalization":
            return run.status is AgentRunStatus.RUNNING
        return run.status in {
            AgentRunStatus.PLANNING,
            AgentRunStatus.WAITING_CLARIFICATION,
            AgentRunStatus.RUNNING,
        }

    @staticmethod
    def _write_deepsearch_budget_run(
        connection: sqlite3.Connection,
        *,
        run: AgentRun,
        budget: DeepSearchBudgetV1,
        updated_at: datetime,
    ) -> AgentRun:
        updated_run = AgentRun.model_validate(
            {
                **run.model_dump(mode="python"),
                "deepsearch_budget": budget,
                "updated_at": updated_at,
            }
        )
        connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (updated_run.model_dump_json(), updated_at.isoformat(), updated_run.id),
        )
        return updated_run

    @classmethod
    def _settle_deepsearch_finalization_budget_for_transition(
        cls,
        *,
        run: AgentRun,
        invocation_key: str,
        actual_usage: DeepSearchBudgetUsageV1,
        additional_active_seconds: float = 0,
    ) -> DeepSearchBudgetV1:
        """Settle one finalization reservation inside its durable stage transaction."""

        if (
            not isinstance(invocation_key, str)
            or not invocation_key
            or isinstance(additional_active_seconds, bool)
            or not isinstance(additional_active_seconds, (int, float))
            or not isfinite(additional_active_seconds)
            or additional_active_seconds < 0
        ):
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")
        try:
            actual = DeepSearchBudgetUsageV1.model_validate(
                {
                    **actual_usage.model_dump(mode="python"),
                    "active_seconds": (
                        actual_usage.active_seconds + additional_active_seconds
                    ),
                }
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid") from error
        budget = run.deepsearch_budget
        if budget is None:
            raise DeepSearchBudgetConflict("deepsearch_budget_run_invalid")
        cls._validate_deepsearch_budget_ledger(budget)
        matches = [
            item for item in budget.reservations if item.invocation_key == invocation_key
        ]
        if len(matches) != 1:
            raise DeepSearchBudgetConflict("deepsearch_budget_reservation_not_found")
        current = matches[0]
        if current.scope != "finalization":
            raise DeepSearchBudgetConflict("deepsearch_budget_scope_invalid")
        if any(
            getattr(actual, field) > getattr(current.resource_maxima, field)
            for field in DeepSearchBudgetUsageV1.model_fields
        ):
            raise DeepSearchBudgetConflict("deepsearch_budget_exhausted")
        if current.status == "settled":
            if current.actual_usage != actual:
                raise DeepSearchBudgetConflict("deepsearch_budget_settlement_conflict")
            return budget
        if run.status is not AgentRunStatus.RUNNING:
            raise DeepSearchBudgetConflict("deepsearch_budget_state_conflict")
        try:
            settled_reservation = DeepSearchBudgetReservationV1(
                **current.model_dump(mode="python", exclude={"status", "actual_usage"}),
                status="settled",
                actual_usage=actual,
            )
        except (TypeError, ValueError) as error:
            raise DeepSearchBudgetConflict("deepsearch_budget_settlement_invalid") from error
        reservations = [
            settled_reservation if item.invocation_key == invocation_key else item
            for item in budget.reservations
        ]
        try:
            updated_budget = DeepSearchBudgetV1.model_validate(
                {
                    **budget.model_dump(mode="python"),
                    "version": budget.version + 1,
                    "consumed": cls._billed_deepsearch_budget_usage(reservations),
                    "reservations": reservations,
                }
            )
            cls._validate_deepsearch_budget_ledger(updated_budget)
        except (TypeError, ValueError) as error:
            raise DeepSearchBudgetConflict("deepsearch_budget_settlement_invalid") from error
        return updated_budget

    @classmethod
    def _close_deepsearch_budget_for_terminal(
        cls,
        run: AgentRun,
        *,
        settlement_invocation_key: str | None = None,
        settlement_actual_usage: DeepSearchBudgetUsageV1 | None = None,
        settlement_additional_active_seconds: float = 0,
    ) -> DeepSearchBudgetV1 | None:
        """Settle every outstanding reservation in one terminal budget version."""

        if (
            (settlement_invocation_key is None) != (settlement_actual_usage is None)
            or isinstance(settlement_additional_active_seconds, bool)
            or not isinstance(settlement_additional_active_seconds, (int, float))
            or not isfinite(settlement_additional_active_seconds)
            or settlement_additional_active_seconds < 0
            or (
                settlement_invocation_key is None
                and settlement_additional_active_seconds != 0
            )
        ):
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")
        budget = run.deepsearch_budget
        if budget is None:
            return None
        cls._validate_deepsearch_budget_ledger(budget)

        settlement_actual: DeepSearchBudgetUsageV1 | None = None
        if settlement_actual_usage is not None:
            if not isinstance(settlement_invocation_key, str) or not settlement_invocation_key:
                raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")
            try:
                settlement_actual = DeepSearchBudgetUsageV1.model_validate(
                    {
                        **settlement_actual_usage.model_dump(mode="python"),
                        "active_seconds": (
                            settlement_actual_usage.active_seconds
                            + settlement_additional_active_seconds
                        ),
                    }
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid") from error
            matches = [
                reservation
                for reservation in budget.reservations
                if reservation.invocation_key == settlement_invocation_key
            ]
            if len(matches) != 1:
                raise DeepSearchBudgetConflict("deepsearch_budget_reservation_not_found")
            settlement_reservation = matches[0]
            if settlement_reservation.scope != "finalization":
                raise DeepSearchBudgetConflict("deepsearch_budget_scope_invalid")
            if any(
                getattr(settlement_actual, field)
                > getattr(settlement_reservation.resource_maxima, field)
                for field in DeepSearchBudgetUsageV1.model_fields
            ):
                raise DeepSearchBudgetConflict("deepsearch_budget_exhausted")
            if (
                settlement_reservation.status == "settled"
                and settlement_reservation.actual_usage != settlement_actual
            ):
                raise DeepSearchBudgetConflict("deepsearch_budget_settlement_conflict")

        changed = False
        reservations: list[DeepSearchBudgetReservationV1] = []
        for reservation in budget.reservations:
            if reservation.status == "settled":
                reservations.append(reservation)
                continue
            actual_usage = (
                settlement_actual
                if reservation.invocation_key == settlement_invocation_key
                else reservation.resource_maxima
            )
            assert actual_usage is not None
            try:
                reservations.append(
                    DeepSearchBudgetReservationV1(
                        **reservation.model_dump(
                            mode="python",
                            exclude={"status", "actual_usage"},
                        ),
                        status="settled",
                        actual_usage=actual_usage,
                    )
                )
            except (TypeError, ValueError) as error:
                raise DeepSearchBudgetConflict(
                    "deepsearch_budget_settlement_invalid"
                ) from error
            changed = True

        if not changed:
            return budget
        try:
            updated_budget = DeepSearchBudgetV1.model_validate(
                {
                    **budget.model_dump(mode="python"),
                    "version": budget.version + 1,
                    "consumed": cls._billed_deepsearch_budget_usage(reservations),
                    "reservations": reservations,
                }
            )
            cls._validate_deepsearch_budget_ledger(updated_budget)
        except (TypeError, ValueError) as error:
            raise DeepSearchBudgetConflict("deepsearch_budget_settlement_invalid") from error
        return updated_budget

    def reserve_deepsearch_budget(
        self,
        *,
        run_id: str,
        expected_budget_version: int,
        logical_operation_key: str,
        invocation_key: str,
        physical_attempt: int,
        resource_maxima: DeepSearchBudgetUsageV1,
        scope: DeepSearchBudgetScope = "standard",
        tool_invocation: DeepSearchToolInvocationV1 | None = None,
    ) -> DeepSearchBudgetMutationResult:
        """Atomically charge maxima before any external DeepSearch operation starts."""

        if type(expected_budget_version) is not int or expected_budget_version < 1 or scope not in {
            "standard",
            "finalization",
        }:
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")
        try:
            reservation = DeepSearchBudgetReservationV1(
                logical_operation_key=logical_operation_key,
                invocation_key=invocation_key,
                physical_attempt=physical_attempt,
                scope=scope,
                resource_maxima=DeepSearchBudgetUsageV1.model_validate(
                    resource_maxima.model_dump(mode="python")
                ),
                status="reserved",
                tool_invocation=(
                    DeepSearchToolInvocationV1.model_validate(
                        tool_invocation.model_dump(mode="python")
                    )
                    if tool_invocation is not None
                    else None
                ),
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid") from error

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._load_deepsearch_budget_run_in_transaction(
                connection,
                run_id=run_id,
            )
            budget = run.deepsearch_budget
            assert budget is not None
            existing = next(
                (
                    item
                    for item in budget.reservations
                    if item.invocation_key == reservation.invocation_key
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.logical_operation_key != reservation.logical_operation_key
                    or existing.physical_attempt != reservation.physical_attempt
                    or existing.scope != reservation.scope
                    or existing.resource_maxima != reservation.resource_maxima
                    or existing.tool_invocation != reservation.tool_invocation
                ):
                    raise DeepSearchBudgetConflict("deepsearch_budget_invocation_conflict")
                return DeepSearchBudgetMutationResult(
                    budget=budget,
                    reservation=existing,
                    replayed=True,
                )
            now = now_utc()
            if not self._deepsearch_budget_status_allowed(run, scope=scope, checked_at=now):
                raise DeepSearchBudgetConflict("deepsearch_budget_state_conflict")
            if budget.version != expected_budget_version:
                raise DeepSearchBudgetConflict(
                    "deepsearch_budget_version_conflict",
                    current_budget_version=budget.version,
                )
            if reservation.tool_invocation is not None:
                if reservation.tool_invocation.run_id != run_id:
                    raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")
                try:
                    (
                        _lineage_run,
                        _lineage_plan,
                        _lineage_node,
                        tool,
                        _step_number,
                        writable,
                    ) = self._load_deepsearch_evidence_context_in_transaction(
                        connection,
                        invocation=reservation.tool_invocation,
                        require_reservation=False,
                    )
                except DeepSearchEvidenceConflict as error:
                    raise DeepSearchBudgetConflict(error.code) from error
                if not writable:
                    raise DeepSearchBudgetConflict("deepsearch_evidence_state_conflict")
                if (
                    abs(reservation.resource_maxima.active_seconds - tool.timeout_seconds)
                    > 1e-9
                ):
                    raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")

            logical_attempts = [
                item
                for item in budget.reservations
                if item.logical_operation_key == reservation.logical_operation_key
            ]
            if any(item.status == "reserved" for item in logical_attempts):
                raise DeepSearchBudgetConflict("deepsearch_budget_previous_attempt_unsettled")
            expected_attempt = max(
                (item.physical_attempt for item in logical_attempts),
                default=0,
            ) + 1
            if reservation.physical_attempt != expected_attempt:
                raise DeepSearchBudgetConflict("deepsearch_budget_attempt_conflict")

            reservations = [*budget.reservations, reservation]
            candidate_budget = budget.model_copy(
                update={
                    "version": budget.version + 1,
                    "consumed": self._billed_deepsearch_budget_usage(reservations),
                    "reservations": reservations,
                }
            )
            self._validate_deepsearch_budget_ledger(candidate_budget)
            updated_budget = DeepSearchBudgetV1.model_validate(
                candidate_budget.model_dump(mode="python")
            )
            self._write_deepsearch_budget_run(
                connection,
                run=run,
                budget=updated_budget,
                updated_at=now,
            )
        return DeepSearchBudgetMutationResult(
            budget=updated_budget,
            reservation=reservation,
            replayed=False,
        )

    def settle_deepsearch_budget(
        self,
        *,
        run_id: str,
        expected_budget_version: int,
        invocation_key: str,
        actual_usage: DeepSearchBudgetUsageV1,
    ) -> DeepSearchBudgetMutationResult:
        """Atomically replace one reserved maximum with trusted actual usage."""

        if type(expected_budget_version) is not int or expected_budget_version < 1:
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")
        try:
            actual = DeepSearchBudgetUsageV1.model_validate(
                actual_usage.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid") from error

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._load_deepsearch_budget_run_in_transaction(
                connection,
                run_id=run_id,
            )
            budget = run.deepsearch_budget
            assert budget is not None
            matches = [
                item for item in budget.reservations if item.invocation_key == invocation_key
            ]
            if len(matches) != 1:
                raise DeepSearchBudgetConflict("deepsearch_budget_reservation_not_found")
            current = matches[0]
            if current.status == "settled":
                if current.actual_usage != actual:
                    raise DeepSearchBudgetConflict("deepsearch_budget_settlement_conflict")
                return DeepSearchBudgetMutationResult(
                    budget=budget,
                    reservation=current,
                    replayed=True,
                )
            now = now_utc()
            if not self._deepsearch_budget_status_allowed(
                run,
                scope=current.scope,
                checked_at=now,
            ):
                raise DeepSearchBudgetConflict("deepsearch_budget_state_conflict")
            if budget.version != expected_budget_version:
                raise DeepSearchBudgetConflict(
                    "deepsearch_budget_version_conflict",
                    current_budget_version=budget.version,
                )
            try:
                settled_reservation = DeepSearchBudgetReservationV1(
                    **current.model_dump(mode="python", exclude={"status", "actual_usage"}),
                    status="settled",
                    actual_usage=actual,
                )
            except (TypeError, ValueError) as error:
                raise DeepSearchBudgetConflict("deepsearch_budget_settlement_invalid") from error
            reservations = [
                settled_reservation if item.invocation_key == invocation_key else item
                for item in budget.reservations
            ]
            updated_budget = DeepSearchBudgetV1.model_validate(
                {
                    **budget.model_dump(mode="python"),
                    "version": budget.version + 1,
                    "consumed": self._billed_deepsearch_budget_usage(reservations),
                    "reservations": reservations,
                }
            )
            self._validate_deepsearch_budget_ledger(updated_budget)
            self._write_deepsearch_budget_run(
                connection,
                run=run,
                budget=updated_budget,
                updated_at=now,
            )
        return DeepSearchBudgetMutationResult(
            budget=updated_budget,
            reservation=settled_reservation,
            replayed=False,
        )

    def _load_deepsearch_evidence_context_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        invocation: DeepSearchToolInvocationV1,
        require_reservation: bool = True,
    ) -> tuple[AgentRun, SkillPlan, SkillPlanNode, ToolDefinition, int, bool]:
        """Validate the durable lineage required by one Tool Evidence batch."""

        run_row = connection.execute(
            "SELECT id, payload, orchestration_version FROM agent_runs WHERE id = ?",
            (invocation.run_id,),
        ).fetchone()
        plan_row = connection.execute(
            "SELECT id, run_id, version, status, payload FROM skill_plans WHERE id = ?",
            (invocation.plan_id,),
        ).fetchone()
        node_row = connection.execute(
            "SELECT id, status, payload FROM skill_plan_nodes WHERE plan_id = ? AND id = ?",
            (invocation.plan_id, invocation.node_id),
        ).fetchone()
        requirement_row = connection.execute(
            """SELECT * FROM deepsearch_requirement_versions
            WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
            (invocation.run_id,),
        ).fetchone()
        tool_row = connection.execute(
            "SELECT id, payload FROM records WHERE collection = ? AND id = ?",
            ("tool_definitions", invocation.tool_definition_id),
        ).fetchone()
        if any(row is None for row in (run_row, plan_row, node_row, requirement_row, tool_row)):
            raise DeepSearchEvidenceConflict("deepsearch_evidence_lineage_invalid")

        try:
            run = AgentRun.model_validate_json(run_row["payload"])
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            node = SkillPlanNode.model_validate_json(node_row["payload"])
            tool = ToolDefinition.model_validate_json(tool_row["payload"])
            requirement = self._decode_deepsearch_requirement_row(requirement_row)
            if run.deepsearch_budget is None:
                raise ValueError("DeepSearch budget is missing")
            self._validate_deepsearch_budget_ledger(run.deepsearch_budget)
        except (DeepSearchBudgetConflict, ResearchStoreConflict, TypeError, ValueError) as error:
            raise DeepSearchEvidenceConflict("deepsearch_evidence_lineage_invalid") from error

        plan_nodes = {item.id: item for item in plan.nodes}
        expected_node = plan_nodes.get(invocation.node_id)
        tool_references = {tool.id, tool.name}
        if tool.external_name:
            tool_references.add(tool.external_name)
        expected_operation_key = canonical_json_sha256(
            {
                "run_id": invocation.run_id,
                "plan_id": invocation.plan_id,
                "plan_version": invocation.plan_version,
                "node_id": invocation.node_id,
                "node_attempt": invocation.node_attempt,
                "tool_call_id": invocation.tool_call_id,
            }
        )
        if (
            run_row["id"] != run.id
            or run_row["orchestration_version"] != "v1"
            or run.orchestration_version != "v1"
            or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            or run.plan_id != plan.id
            or plan_row["id"] != plan.id
            or plan_row["run_id"] != plan.run_id
            or plan_row["version"] != plan.version
            or plan_row["status"] != plan.status.value
            or plan.run_id != run.id
            or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
            or plan.version != invocation.plan_version
            or plan.requirement_version_id != invocation.requirement_version_id
            or requirement.get("id") != invocation.requirement_version_id
            or len(plan_nodes) != len(plan.nodes)
            or expected_node is None
            or expected_node != node
            or node_row["id"] != node.id
            or node_row["status"] != node.status.value
            or node.attempt != invocation.node_attempt
            or tool_row["id"] != tool.id
            or tool.id != invocation.tool_definition_id
            or not tool.enabled
            or tool.side_effect != "read"
            or tool.implementation_id != invocation.implementation_id
            or tool.implementation_version != invocation.implementation_version
            or not tool_references.intersection(node.required_tool_names)
            or invocation.operation_key != expected_operation_key
            or run.deepsearch_budget is None
        ):
            raise DeepSearchEvidenceConflict("deepsearch_evidence_lineage_invalid")

        if require_reservation:
            reservations = [
                item
                for item in run.deepsearch_budget.reservations
                if item.invocation_key == invocation.operation_key
            ]
            if (
                len(reservations) != 1
                or reservations[0].scope != "standard"
                or reservations[0].resource_maxima.tool_calls != 1
                or reservations[0].tool_invocation != invocation
            ):
                raise DeepSearchEvidenceConflict("deepsearch_evidence_reservation_missing")

        if plan.plan_content_hash is None:
            raise DeepSearchEvidenceConflict("deepsearch_evidence_lineage_invalid")
        try:
            self._load_deepsearch_plan_snapshot_in_transaction(
                connection,
                run=run,
                requirement=requirement,
                plan=plan,
                expected_plan_hash=plan.plan_content_hash,
            )
        except (ResearchStoreConflict, TypeError, ValueError) as error:
            raise DeepSearchEvidenceConflict("deepsearch_evidence_lineage_invalid") from error

        step_number = next(
            index
            for index, item in enumerate(plan.nodes, start=1)
            if item.id == invocation.node_id
        )
        checked_at = now_utc()
        writable = (
            run.status is AgentRunStatus.RUNNING
            and plan.status is SkillPlanStatus.RUNNING
            and node.status is SkillPlanNodeStatus.RUNNING
            and (run.absolute_expires_at is None or checked_at < run.absolute_expires_at)
        )
        return run, plan, node, tool, step_number, writable

    @staticmethod
    def _validate_deepsearch_evidence_batch(
        *,
        invocation: DeepSearchToolInvocationV1,
        run: AgentRun,
        node: SkillPlanNode,
        tool: ToolDefinition,
        step_number: int,
        sources: tuple[Source, ...],
        artifacts: tuple[Artifact, ...],
    ) -> tuple[tuple[Source, Artifact], ...]:
        from agentmesh.artifacts import (
            ArtifactAccessError,
            DeepSearchArtifactSchemaRegistry,
            TrustedEvidenceEnvelopeV1,
        )

        if not sources or len(sources) != len(artifacts) or len(sources) > 60:
            raise DeepSearchEvidenceConflict("deepsearch_evidence_batch_invalid")
        source_by_id = {source.id: source for source in sources}
        if len(source_by_id) != len(sources) or len({artifact.id for artifact in artifacts}) != len(artifacts):
            raise DeepSearchEvidenceConflict("deepsearch_evidence_batch_invalid")

        artifact_by_source_id: dict[str, tuple[Artifact, TrustedEvidenceEnvelopeV1]] = {}
        for artifact in artifacts:
            try:
                parsed = DeepSearchArtifactSchemaRegistry.parse(
                    artifact.artifact_type,
                    artifact.schema_version or "",
                    artifact.content,
                )
            except ArtifactAccessError as error:
                raise DeepSearchEvidenceConflict("deepsearch_evidence_integrity_failed") from error
            if not isinstance(parsed, TrustedEvidenceEnvelopeV1) or parsed.source_id is None:
                raise DeepSearchEvidenceConflict("deepsearch_evidence_integrity_failed")
            if parsed.source_id in artifact_by_source_id:
                raise DeepSearchEvidenceConflict("deepsearch_evidence_batch_invalid")
            artifact_by_source_id[parsed.source_id] = (artifact, parsed)

        if set(source_by_id) != set(artifact_by_source_id):
            raise DeepSearchEvidenceConflict("deepsearch_evidence_batch_invalid")

        unordered = [
            (source_by_id[source_id], artifact, envelope)
            for source_id, (artifact, envelope) in artifact_by_source_id.items()
        ]
        ordered = sorted(
            unordered,
            key=lambda item: (
                item[2].normalized_reference,
                item[2].content_hash,
                unicodedata.normalize("NFC", item[0].title.strip()),
            ),
        )
        order_keys = [
            (
                envelope.normalized_reference,
                envelope.content_hash,
                unicodedata.normalize("NFC", source.title.strip()),
            )
            for source, _artifact, envelope in ordered
        ]
        if len(order_keys) != len(set(order_keys)):
            raise DeepSearchEvidenceConflict("deepsearch_evidence_batch_invalid")

        reference_ordinals: dict[str, int] = {}
        validated: list[tuple[Source, Artifact]] = []
        for source, artifact, envelope in ordered:
            normalized_reference = envelope.normalized_reference
            normalized_title = unicodedata.normalize("NFC", source.title.strip())
            source_ordinal = reference_ordinals.get(normalized_reference, 0)
            reference_ordinals[normalized_reference] = source_ordinal + 1
            expected_source_id = "src_deepsearch_" + canonical_json_sha256(
                {
                    "run_id": invocation.run_id,
                    "plan_id": invocation.plan_id,
                    "plan_version": invocation.plan_version,
                    "node_id": invocation.node_id,
                    "node_attempt": invocation.node_attempt,
                    "operation_key": invocation.operation_key,
                    "normalized_reference": normalized_reference,
                    "source_ordinal": source_ordinal,
                }
            )
            expected_artifact_id = "artifact_deepsearch_evidence_" + canonical_json_sha256(
                {"source_id": expected_source_id}
            )
            if (
                not normalized_title
                or not source.source_type.strip()
                or source.id != expected_source_id
                or source.reference != normalized_reference
                or unicodedata.normalize("NFC", source.reference.strip()) != source.reference
                or source.workspace_id != run.workspace_id
                or source.project_id != run.project_id
                or source.user_id != run.user_id
                or source.run_id != run.id
                or source.skill_id != node.skill_id
                or source.created_at != envelope.retrieved_at
                or envelope.schema_version != "deepsearch-tool-evidence-v1"
                or envelope.origin_type != "tool"
                or envelope.run_id != invocation.run_id
                or envelope.requirement_version_id != invocation.requirement_version_id
                or envelope.plan_id != invocation.plan_id
                or envelope.plan_version != invocation.plan_version
                or envelope.node_id != invocation.node_id
                or envelope.attempt != invocation.node_attempt
                or envelope.tool_name != tool.name
                or envelope.tool_implementation_id != invocation.implementation_id
                or envelope.tool_implementation_version != invocation.implementation_version
                or envelope.execution_mode != "real"
                or envelope.tool_call_id != invocation.tool_call_id
                or envelope.operation_key != invocation.operation_key
                or envelope.request_hash != invocation.canonical_arguments_hash
                or envelope.source_id != expected_source_id
                or envelope.source_ordinal != source_ordinal
                or artifact.id != expected_artifact_id
                or artifact.run_id != run.id
                or artifact.workspace_id != run.workspace_id
                or artifact.project_id != run.project_id
                or artifact.user_id != run.user_id
                or artifact.artifact_type != "deepsearch_tool_evidence"
                or artifact.content_type != "application/json"
                or artifact.truncated
                or artifact.verification_state is not ArtifactVerificationState.SEALED
                or artifact.schema_version != "deepsearch-tool-evidence-v1"
                or artifact.requirement_version_id != invocation.requirement_version_id
                or artifact.plan_version_id != f"{invocation.plan_id}:v{invocation.plan_version}"
                or artifact.attempt_id != f"{invocation.node_id}:attempt:{invocation.node_attempt}"
                or artifact.step_number != step_number
                or artifact.created_at != envelope.retrieved_at
                or artifact.updated_at != envelope.retrieved_at
            ):
                raise DeepSearchEvidenceConflict("deepsearch_evidence_integrity_failed")
            validated.append((source, artifact))
        return tuple(validated)

    def save_deepsearch_evidence_batch(
        self,
        *,
        invocation: DeepSearchToolInvocationV1,
        sources: Sequence[Source],
        artifacts: Sequence[Artifact],
    ) -> DeepSearchEvidenceBatchSaveResult:
        """Atomically insert one Tool call's Sources and sealed Evidence Artifacts."""

        from agentmesh.artifacts import (
            ArtifactAccessError,
            DeepSearchArtifactSchemaRegistry,
            TrustedEvidenceEnvelopeV1,
            V1VerifiedArtifactStore,
        )

        try:
            invocation = DeepSearchToolInvocationV1.model_validate(
                invocation.model_dump(mode="python")
            )
            checked_sources = tuple(
                Source.model_validate(source.model_dump(mode="python"))
                for source in sources
            )
            checked_artifacts = tuple(
                Artifact.model_validate(artifact.model_dump(mode="python"))
                for artifact in artifacts
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise DeepSearchEvidenceConflict("deepsearch_evidence_batch_invalid") from error

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run, _plan, node, tool, step_number, writable = (
                self._load_deepsearch_evidence_context_in_transaction(
                    connection,
                    invocation=invocation,
                )
            )
            pairs = self._validate_deepsearch_evidence_batch(
                invocation=invocation,
                run=run,
                node=node,
                tool=tool,
                step_number=step_number,
                sources=checked_sources,
                artifacts=checked_artifacts,
            )
            budget = run.deepsearch_budget
            assert budget is not None
            try:
                envelopes = tuple(
                    DeepSearchArtifactSchemaRegistry.parse(
                        artifact.artifact_type,
                        artifact.schema_version or "",
                        artifact.content,
                    )
                    for _source, artifact in pairs
                )
            except ArtifactAccessError as error:
                raise DeepSearchEvidenceConflict(
                    "deepsearch_evidence_integrity_failed"
                ) from error
            if not all(
                isinstance(envelope, TrustedEvidenceEnvelopeV1)
                for envelope in envelopes
            ):
                raise DeepSearchEvidenceConflict("deepsearch_evidence_integrity_failed")
            evidence_usage = DeepSearchBudgetUsageV1(
                evidence_items=len(pairs),
                evidence_bytes=sum(envelope.size_bytes for envelope in envelopes),
                artifact_bytes=sum(
                    len(artifact.content.encode("utf-8"))
                    for _source, artifact in pairs
                ),
            )
            evidence_reservation = DeepSearchBudgetReservationV1(
                logical_operation_key=f"evidence:{invocation.operation_key}",
                invocation_key=canonical_json_sha256(
                    {
                        "operation_key": invocation.operation_key,
                        "resource": "evidence_batch",
                    }
                ),
                physical_attempt=1,
                resource_maxima=evidence_usage,
                status="settled",
                actual_usage=evidence_usage,
            )
            matching_evidence_reservations = [
                item
                for item in budget.reservations
                if item.invocation_key == evidence_reservation.invocation_key
            ]
            if len(matching_evidence_reservations) > 1 or (
                matching_evidence_reservations
                and matching_evidence_reservations[0] != evidence_reservation
            ):
                raise DeepSearchEvidenceConflict("deepsearch_evidence_identity_conflict")
            existing_source_rows = [
                connection.execute(
                    "SELECT id, payload FROM records WHERE collection = ? AND id = ?",
                    ("sources", source.id),
                ).fetchone()
                for source, _artifact in pairs
            ]
            existing_artifact_rows = [
                connection.execute(
                    "SELECT id FROM artifacts WHERE id = ?",
                    (artifact.id,),
                ).fetchone()
                for _source, artifact in pairs
            ]
            presence = [
                source_row is not None and artifact_row is not None
                for source_row, artifact_row in zip(
                    existing_source_rows,
                    existing_artifact_rows,
                    strict=True,
                )
            ]
            if any(
                (source_row is None) != (artifact_row is None)
                for source_row, artifact_row in zip(
                    existing_source_rows,
                    existing_artifact_rows,
                    strict=True,
                )
            ) or (any(presence) and not all(presence)):
                raise DeepSearchEvidenceConflict("deepsearch_evidence_identity_conflict")

            artifact_store = V1VerifiedArtifactStore(self)
            if all(presence):
                if len(matching_evidence_reservations) != 1:
                    raise DeepSearchEvidenceConflict("deepsearch_evidence_identity_conflict")
                persisted_sources: list[Source] = []
                persisted_artifacts: list[Artifact] = []
                for (source, artifact), source_row in zip(
                    pairs,
                    existing_source_rows,
                    strict=True,
                ):
                    try:
                        existing_source = Source.model_validate_json(source_row["payload"])
                        existing_artifact = artifact_store.insert_sealed(
                            artifact,
                            connection=connection,
                        )
                    except (ArtifactAccessError, TypeError, ValueError) as error:
                        raise DeepSearchEvidenceConflict(
                            "deepsearch_evidence_identity_conflict"
                        ) from error
                    if source_row["id"] != source.id or existing_source != source:
                        raise DeepSearchEvidenceConflict("deepsearch_evidence_identity_conflict")
                    persisted_sources.append(existing_source)
                    persisted_artifacts.append(existing_artifact)
                return DeepSearchEvidenceBatchSaveResult(
                    sources=tuple(persisted_sources),
                    artifacts=tuple(persisted_artifacts),
                    replayed=True,
                )

            if not writable:
                raise DeepSearchEvidenceConflict("deepsearch_evidence_state_conflict")
            if matching_evidence_reservations:
                raise DeepSearchEvidenceConflict("deepsearch_evidence_identity_conflict")
            reservations = [*budget.reservations, evidence_reservation]
            candidate_budget = budget.model_copy(
                update={
                    "version": budget.version + 1,
                    "consumed": self._billed_deepsearch_budget_usage(reservations),
                    "reservations": reservations,
                }
            )
            try:
                self._validate_deepsearch_budget_ledger(candidate_budget)
                updated_budget = DeepSearchBudgetV1.model_validate(
                    candidate_budget.model_dump(mode="python")
                )
            except (DeepSearchBudgetConflict, TypeError, ValueError) as error:
                code = getattr(error, "code", "deepsearch_budget_integrity_failed")
                raise DeepSearchEvidenceConflict(code) from error
            try:
                for source, _artifact in pairs:
                    connection.execute(
                        "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
                        ("sources", source.id, source.model_dump_json()),
                    )
                persisted_artifacts = tuple(
                    artifact_store.insert_sealed(artifact, connection=connection)
                    for _source, artifact in pairs
                )
            except (ArtifactAccessError, sqlite3.IntegrityError) as error:
                raise DeepSearchEvidenceConflict("deepsearch_evidence_identity_conflict") from error
            self._write_deepsearch_budget_run(
                connection,
                run=run,
                budget=updated_budget,
                updated_at=now_utc(),
            )

        return DeepSearchEvidenceBatchSaveResult(
            sources=tuple(source for source, _artifact in pairs),
            artifacts=persisted_artifacts,
            replayed=False,
        )

    def _load_deepsearch_finalization_context_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        plan_id: str,
    ) -> tuple[SkillPlan, AgentRun, RequirementVersionV1, ProblemGraphV1] | None:
        """Load and verify the immutable lineage for one DeepSearch finalization CAS."""

        from agentmesh.deepsearch.contracts import (
            ProblemGraphV1,
            RequirementVersionV1,
            validate_problem_graph_against_requirement,
        )
        from agentmesh.deepsearch.planning import plan_content_hash

        plan_row = connection.execute(
            "SELECT id, run_id, version, status, payload FROM skill_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        run_row = connection.execute(
            "SELECT id, payload, orchestration_version FROM agent_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if plan_row is None or run_row is None:
            return None
        try:
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch finalization state is invalid") from error
        if (
            run_row["id"] != run.id
            or plan_row["id"] != plan.id
            or plan_row["run_id"] != plan.run_id
            or plan_row["version"] != plan.version
            or plan_row["status"] != plan.status.value
            or run.id != run_id
            or plan.id != plan_id
            or plan.run_id != run.id
            or run.plan_id != plan.id
            or run_row["orchestration_version"] != "v1"
            or run.orchestration_version != "v1"
            or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
            or run.deepsearch_budget is None
        ):
            raise ResearchStoreConflict("DeepSearch finalization identity is invalid")

        requirement_row = connection.execute(
            """SELECT * FROM deepsearch_requirement_versions
            WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
            (run.id,),
        ).fetchone()
        if requirement_row is None:
            raise ResearchStoreConflict("DeepSearch finalization Requirement is missing")
        requirement_data = self._decode_deepsearch_requirement_row(requirement_row)
        try:
            requirement = RequirementVersionV1.model_validate(requirement_data)
            graph = ProblemGraphV1.model_validate(plan.problem_graph)
            validate_problem_graph_against_requirement(graph=graph, requirement=requirement)
            expected_plan_hash = plan_content_hash(plan)
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch finalization lineage is invalid") from error
        if (
            requirement.run_id != run.id
            or plan.requirement_version_id != requirement.id
            or plan.requirement_content_hash != requirement.content_hash
            or plan.problem_graph_hash != graph.content_hash
            or plan.plan_content_hash != expected_plan_hash
        ):
            raise ResearchStoreConflict("DeepSearch finalization lineage is invalid")
        self._load_deepsearch_plan_snapshot_in_transaction(
            connection,
            run=run,
            requirement=requirement,
            plan=plan,
            expected_plan_hash=expected_plan_hash,
        )
        return plan, run, requirement, graph

    @staticmethod
    def _validate_deepsearch_finalization_cas_input(
        *,
        expected_plan_version: int,
        expected_finalization_version: int,
        expected_stage: DeepSearchFinalizationStage,
        target_stage: DeepSearchFinalizationStage,
        input_hash: str,
    ) -> tuple[DeepSearchFinalizationStage, DeepSearchFinalizationStage]:
        try:
            current = DeepSearchFinalizationStage(expected_stage)
            target = DeepSearchFinalizationStage(target_stage)
        except ValueError as error:
            raise ResearchStoreConflict("DeepSearch finalization stage is invalid") from error
        if (
            type(expected_plan_version) is not int
            or expected_plan_version < 1
            or type(expected_finalization_version) is not int
            or expected_finalization_version < 0
            or not isinstance(input_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", input_hash) is None
        ):
            raise ResearchStoreConflict("DeepSearch finalization CAS input is invalid")
        return current, target

    def compare_and_swap_deepsearch_finalization(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
        expected_finalization_version: int,
        expected_stage: DeepSearchFinalizationStage,
        target_stage: DeepSearchFinalizationStage,
        input_hash: str,
        evidence_manifest_artifact: Artifact | None = None,
        synthesis: DeepSearchSynthesisV1 | None = None,
        coverage: DeepSearchEvidenceCoverageV1 | None = None,
        review_outcome: DeepSearchReviewOutcomeV1 | None = None,
        budget_invocation_key: str | None = None,
        budget_actual_usage: DeepSearchBudgetUsageV1 | None = None,
    ) -> tuple[SkillPlan, AgentRun] | None:
        """Atomically persist one typed finalization result and advance its checkpoint."""

        current_stage, next_stage = self._validate_deepsearch_finalization_cas_input(
            expected_plan_version=expected_plan_version,
            expected_finalization_version=expected_finalization_version,
            expected_stage=expected_stage,
            target_stage=target_stage,
            input_hash=input_hash,
        )
        allowed_targets = {
            DeepSearchFinalizationStage.NONE: DeepSearchFinalizationStage.NODES_TERMINAL,
            DeepSearchFinalizationStage.NODES_TERMINAL: DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED,
            DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED: DeepSearchFinalizationStage.SYNTHESIS_V0_SAVED,
            DeepSearchFinalizationStage.SYNTHESIS_V0_SAVED: DeepSearchFinalizationStage.COVERAGE_V0_CHECKED,
            DeepSearchFinalizationStage.COVERAGE_V0_CHECKED: DeepSearchFinalizationStage.REVIEW_V0_CHECKED,
            DeepSearchFinalizationStage.REVIEW_V0_CHECKED: DeepSearchFinalizationStage.SYNTHESIS_V1_SAVED,
            DeepSearchFinalizationStage.SYNTHESIS_V1_SAVED: DeepSearchFinalizationStage.COVERAGE_V1_CHECKED,
            DeepSearchFinalizationStage.COVERAGE_V1_CHECKED: DeepSearchFinalizationStage.REVIEW_V1_CHECKED,
        }
        if allowed_targets.get(current_stage) is not next_stage:
            raise ResearchStoreConflict("DeepSearch finalization stage transition is invalid")

        payloads = {
            "evidence_manifest_artifact": evidence_manifest_artifact,
            "synthesis": synthesis,
            "coverage": coverage,
            "review_outcome": review_outcome,
        }
        expected_payload = {
            DeepSearchFinalizationStage.EVIDENCE_MANIFEST_SEALED: "evidence_manifest_artifact",
            DeepSearchFinalizationStage.SYNTHESIS_V0_SAVED: "synthesis",
            DeepSearchFinalizationStage.COVERAGE_V0_CHECKED: "coverage",
            DeepSearchFinalizationStage.REVIEW_V0_CHECKED: "review_outcome",
            DeepSearchFinalizationStage.SYNTHESIS_V1_SAVED: "synthesis",
            DeepSearchFinalizationStage.COVERAGE_V1_CHECKED: "coverage",
            DeepSearchFinalizationStage.REVIEW_V1_CHECKED: "review_outcome",
        }.get(next_stage)
        supplied_payloads = {name for name, value in payloads.items() if value is not None}
        required_payloads = {expected_payload} if expected_payload is not None else set()
        if supplied_payloads != required_payloads:
            raise ResearchStoreConflict("DeepSearch finalization payload does not match its stage")
        if (budget_invocation_key is None) != (budget_actual_usage is None):
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")
        try:
            checked_manifest_artifact = (
                Artifact.model_validate(evidence_manifest_artifact.model_dump(mode="python"))
                if evidence_manifest_artifact is not None
                else None
            )
            checked_synthesis = (
                DeepSearchSynthesisV1.model_validate(synthesis.model_dump(mode="python"))
                if synthesis is not None
                else None
            )
            checked_coverage = (
                DeepSearchEvidenceCoverageV1.model_validate(coverage.model_dump(mode="python"))
                if coverage is not None
                else None
            )
            checked_review_outcome = (
                DeepSearchReviewOutcomeV1.model_validate(review_outcome.model_dump(mode="python"))
                if review_outcome is not None
                else None
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch finalization payload is invalid") from error
        requires_finalization_budget = (
            checked_manifest_artifact is not None
            or checked_coverage is not None
            or (
                checked_synthesis is not None
                and checked_synthesis.synthesis_mode == "deterministic_evidence_digest"
            )
        )
        if requires_finalization_budget and budget_invocation_key is None:
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")

        persistence_started_at = monotonic()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._load_deepsearch_finalization_context_in_transaction(
                connection,
                run_id=run_id,
                plan_id=plan_id,
            )
            if context is None:
                return None
            plan, run, requirement, graph = context
            if (
                plan.version == expected_plan_version
                and plan.finalization_version == expected_finalization_version + 1
                and plan.finalization_stage is next_stage
                and plan.finalization_input_hashes.get(next_stage) == input_hash
                and plan.status is SkillPlanStatus.RUNNING
                and run.status is AgentRunStatus.RUNNING
            ):
                replay_matches = False
                if checked_manifest_artifact is not None:
                    from agentmesh.artifacts import ArtifactAccessError, V1VerifiedArtifactStore

                    artifact_row = connection.execute(
                        "SELECT 1 FROM artifacts WHERE id = ?",
                        (checked_manifest_artifact.id,),
                    ).fetchone()
                    replay_matches = (
                        artifact_row is not None
                        and plan.evidence_manifest_artifact_id == checked_manifest_artifact.id
                        and plan.evidence_manifest_hash == checked_manifest_artifact.content_hash
                    )
                    if replay_matches:
                        try:
                            V1VerifiedArtifactStore(self).insert_sealed(
                                checked_manifest_artifact,
                                connection=connection,
                            )
                        except ArtifactAccessError as error:
                            raise ResearchStoreConflict(
                                "DeepSearch finalization replay payload conflicts"
                            ) from error
                elif checked_synthesis is not None:
                    revision = checked_synthesis.revision_count
                    replay_matches = (
                        revision < len(plan.deepsearch_syntheses)
                        and plan.deepsearch_syntheses[revision] == checked_synthesis
                    )
                elif checked_coverage is not None:
                    replay_matches = plan.evidence_coverage == checked_coverage
                elif checked_review_outcome is not None:
                    revision = checked_review_outcome.revision_count
                    replay_matches = (
                        revision < len(plan.review_outcomes)
                        and plan.review_outcomes[revision] == checked_review_outcome
                    )
                else:
                    return None
                if not replay_matches:
                    raise ResearchStoreConflict(
                        "DeepSearch finalization replay payload conflicts"
                    )
                return plan, run
            if (
                plan.version != expected_plan_version
                or plan.finalization_version != expected_finalization_version
                or plan.finalization_stage is not current_stage
                or plan.status is not SkillPlanStatus.RUNNING
                or run.status is not AgentRunStatus.RUNNING
            ):
                return None
            terminal_node_statuses = {
                SkillPlanNodeStatus.COMPLETED,
                SkillPlanNodeStatus.FAILED,
                SkillPlanNodeStatus.SKIPPED,
                SkillPlanNodeStatus.CANCELLED,
            }
            if next_stage is DeepSearchFinalizationStage.NODES_TERMINAL and any(
                node.status not in terminal_node_statuses for node in plan.nodes
            ):
                raise ResearchStoreConflict("DeepSearch finalization requires all nodes to be terminal")
            if next_stage in plan.finalization_input_hashes:
                raise ResearchStoreConflict("DeepSearch finalization input hash already exists")

            updates: dict[str, object] = {}
            if checked_manifest_artifact is not None:
                from agentmesh.artifacts import (
                    ArtifactAccessError,
                    DeepSearchArtifactSchemaRegistry,
                    DeepSearchEvidenceManifestV1,
                    V1VerifiedArtifactStore,
                )

                try:
                    manifest = DeepSearchArtifactSchemaRegistry.parse(
                        checked_manifest_artifact.artifact_type,
                        checked_manifest_artifact.schema_version or "",
                        checked_manifest_artifact.content,
                    )
                except (ArtifactAccessError, TypeError, ValueError) as error:
                    raise ResearchStoreConflict(
                        "DeepSearch evidence manifest is invalid"
                    ) from error
                if (
                    not isinstance(manifest, DeepSearchEvidenceManifestV1)
                    or checked_manifest_artifact.artifact_type
                    != "deepsearch_evidence_manifest"
                    or checked_manifest_artifact.verification_state
                    is not ArtifactVerificationState.SEALED
                    or manifest.run_id != run.id
                    or manifest.requirement_version_id != requirement.id
                    or manifest.plan_id != plan.id
                    or manifest.plan_version != plan.version
                    or manifest.plan_content_hash != plan.plan_content_hash
                    or plan.evidence_manifest_artifact_id is not None
                    or plan.evidence_manifest_hash is not None
                ):
                    raise ResearchStoreConflict("DeepSearch evidence manifest is invalid")
                try:
                    V1VerifiedArtifactStore(self).insert_sealed(
                        checked_manifest_artifact,
                        connection=connection,
                    )
                except ArtifactAccessError as error:
                    raise ResearchStoreConflict(
                        "DeepSearch evidence manifest is invalid"
                    ) from error
                updates = {
                    "evidence_manifest_artifact_id": checked_manifest_artifact.id,
                    "evidence_manifest_hash": checked_manifest_artifact.content_hash,
                }
            elif checked_synthesis is not None:
                revision = (
                    0
                    if next_stage is DeepSearchFinalizationStage.SYNTHESIS_V0_SAVED
                    else 1
                )
                if (
                    checked_synthesis.revision_count != revision
                    or len(plan.deepsearch_syntheses) != revision
                    or len(plan.synthesis_content_hashes) != revision
                    or plan.evidence_manifest_artifact_id is None
                    or plan.evidence_manifest_hash is None
                    or (
                        revision == 1
                        and (
                            len(plan.review_outcomes) != 1
                            or plan.review_outcomes[0].outcome != "revise"
                            or plan.deepsearch_syntheses[0].synthesis_mode != "model"
                        )
                    )
                ):
                    raise ResearchStoreConflict("DeepSearch synthesis revision is invalid")
                for ordinal, claim in enumerate(checked_synthesis.claims, start=1):
                    expected_claim_id = "claim_" + canonical_json_sha256(
                        {
                            "run_id": run.id,
                            "plan_id": plan.id,
                            "plan_version": plan.version,
                            "revision_count": revision,
                            "ordinal": ordinal,
                            "claim": claim.model_dump(mode="python", exclude={"id"}),
                        }
                    )
                    if claim.id != expected_claim_id:
                        raise ResearchStoreConflict("DeepSearch synthesis claim identity is invalid")
                synthesis_hash = canonical_json_sha256(
                    checked_synthesis.model_dump(mode="python")
                )
                updates = {
                    "deepsearch_syntheses": [
                        *plan.deepsearch_syntheses,
                        checked_synthesis,
                    ],
                    "synthesis_content_hashes": [
                        *plan.synthesis_content_hashes,
                        synthesis_hash,
                    ],
                    "report_revision_count": revision,
                }
            elif checked_coverage is not None:
                revision = (
                    0
                    if next_stage is DeepSearchFinalizationStage.COVERAGE_V0_CHECKED
                    else 1
                )
                synthesis_hash = (
                    plan.synthesis_content_hashes[revision]
                    if revision < len(plan.synthesis_content_hashes)
                    else None
                )
                required_question_ids = [
                    question.id for question in graph.questions if question.required
                ]
                required_criterion_ids = [
                    criterion.id for criterion in requirement.payload.success_criteria
                ]
                synthesis_claim_ids = (
                    {claim.id for claim in plan.deepsearch_syntheses[revision].claims}
                    if revision < len(plan.deepsearch_syntheses)
                    else set()
                )
                checkpoint_claim_ids = set(checked_coverage.validated_claim_ids) | set(
                    checked_coverage.invalid_claim_ids
                )
                if (
                    checked_coverage.revision_count != revision
                    or checked_coverage.synthesis_content_hash != synthesis_hash
                    or checked_coverage.required_question_ids != required_question_ids
                    or checked_coverage.required_success_criterion_ids
                    != required_criterion_ids
                    or checkpoint_claim_ids != synthesis_claim_ids
                    or checked_coverage.passed != (not checked_coverage.gap_codes)
                    or (
                        revision == 0 and plan.evidence_coverage is not None
                    )
                    or (
                        revision == 1
                        and (
                            plan.evidence_coverage is None
                            or plan.evidence_coverage.revision_count != 0
                        )
                    )
                ):
                    raise ResearchStoreConflict("DeepSearch evidence coverage is invalid")
                updates = {"evidence_coverage": checked_coverage}
            elif checked_review_outcome is not None:
                revision = (
                    0
                    if next_stage is DeepSearchFinalizationStage.REVIEW_V0_CHECKED
                    else 1
                )
                synthesis_hash = (
                    plan.synthesis_content_hashes[revision]
                    if revision < len(plan.synthesis_content_hashes)
                    else None
                )
                review = checked_review_outcome.review
                known_claim_ids = (
                    {claim.id for claim in plan.deepsearch_syntheses[revision].claims}
                    if revision < len(plan.deepsearch_syntheses)
                    else set()
                )
                if (
                    checked_review_outcome.revision_count != revision
                    or checked_review_outcome.synthesis_content_hash != synthesis_hash
                    or len(plan.review_outcomes) != revision
                    or plan.evidence_coverage is None
                    or plan.evidence_coverage.revision_count != revision
                    or (
                        review is not None
                        and (
                            review.requirement_version_id != requirement.id
                            or review.requirement_content_hash != requirement.content_hash
                            or review.problem_graph_hash != graph.content_hash
                            or review.plan_id != plan.id
                            or review.plan_version != plan.version
                            or review.plan_content_hash != plan.plan_content_hash
                            or not set(review.unsupported_claim_ids).issubset(
                                known_claim_ids
                            )
                            or not set(review.contradictory_claim_ids).issubset(
                                known_claim_ids
                            )
                            or set(review.unsupported_claim_ids)
                            & set(review.contradictory_claim_ids)
                            or not set(review.missing_section_ids).issubset(
                                {question.id for question in graph.questions}
                            )
                        )
                    )
                ):
                    raise ResearchStoreConflict("DeepSearch review outcome is invalid")
                updates = {
                    "review_outcomes": [
                        *plan.review_outcomes,
                        checked_review_outcome,
                    ]
                }

            now = now_utc()
            if budget_invocation_key is not None and budget_actual_usage is not None:
                updated_budget = self._settle_deepsearch_finalization_budget_for_transition(
                    run=run,
                    invocation_key=budget_invocation_key,
                    actual_usage=budget_actual_usage,
                    additional_active_seconds=max(
                        monotonic() - persistence_started_at,
                        0,
                    ),
                )
                run = self._write_deepsearch_budget_run(
                    connection,
                    run=run,
                    budget=updated_budget,
                    updated_at=now,
                )
            input_hashes = dict(plan.finalization_input_hashes)
            input_hashes[next_stage] = input_hash
            updated_plan = SkillPlan.model_validate(
                {
                    **plan.model_dump(mode="python"),
                    **updates,
                    "finalization_stage": next_stage,
                    "finalization_version": expected_finalization_version + 1,
                    "finalization_input_hashes": input_hashes,
                    "updated_at": now,
                }
            )
            self._write_skill_plan(connection, updated_plan)
            self._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "deepsearch_finalization_stage_changed",
                        {
                            "plan_id": plan.id,
                            "from_stage": current_stage.value,
                            "to_stage": next_stage.value,
                            "finalization_version": updated_plan.finalization_version,
                            "input_hash": input_hash,
                        },
                    )
                ],
            )
        return updated_plan, run

    def commit_deepsearch_terminal_without_report(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
        expected_finalization_version: int,
        expected_stage: DeepSearchFinalizationStage,
        expected_plan_status: SkillPlanStatus,
        expected_run_status: AgentRunStatus,
        terminal_status: AgentRunStatus,
        error_code: str | None,
        input_hash: str,
        events: list[tuple[str, dict[str, object]]],
    ) -> tuple[SkillPlan, AgentRun] | None:
        """Fail or cancel DeepSearch without publishing a report or accepting stale state."""

        current_stage, _terminal_stage = self._validate_deepsearch_finalization_cas_input(
            expected_plan_version=expected_plan_version,
            expected_finalization_version=expected_finalization_version,
            expected_stage=expected_stage,
            target_stage=DeepSearchFinalizationStage.TERMINAL_COMMITTED,
            input_hash=input_hash,
        )
        try:
            final_run_status = AgentRunStatus(terminal_status)
            current_plan_status = SkillPlanStatus(expected_plan_status)
            current_run_status = AgentRunStatus(expected_run_status)
        except ValueError as error:
            raise ResearchStoreConflict("DeepSearch terminal status is invalid") from error
        plan_statuses = {
            AgentRunStatus.FAILED: SkillPlanStatus.FAILED,
            AgentRunStatus.CANCELLED: SkillPlanStatus.CANCELLED,
        }
        final_plan_status = plan_statuses.get(final_run_status)
        if final_plan_status is None:
            raise ResearchStoreConflict("DeepSearch terminal status is invalid")
        allowed_current_states = {
            (SkillPlanStatus.APPROVED, AgentRunStatus.RUNNING),
            (SkillPlanStatus.RUNNING, AgentRunStatus.RUNNING),
            (SkillPlanStatus.RUNNING, AgentRunStatus.WAITING_APPROVAL),
        }
        if (current_plan_status, current_run_status) not in allowed_current_states:
            raise ResearchStoreConflict("DeepSearch terminal expected state is invalid")
        if (
            (error_code is not None and (not isinstance(error_code, str) or not error_code or len(error_code) > 120))
            or (final_run_status is AgentRunStatus.FAILED and error_code is None)
            or not events
            or len(events) > 16
            or any(
                not isinstance(event_type, str)
                or not event_type
                or len(event_type) > 120
                or not isinstance(payload, dict)
                for event_type, payload in events
            )
        ):
            raise ResearchStoreConflict("DeepSearch terminal patch is invalid")
        expected_terminal_event = {
            AgentRunStatus.FAILED: "run_failed",
            AgentRunStatus.CANCELLED: "run_cancelled",
        }[final_run_status]
        if (
            events[-1][0] != expected_terminal_event
            or events[-1][1].get("error_code") != error_code
        ):
            raise ResearchStoreConflict("DeepSearch terminal events are invalid")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._load_deepsearch_finalization_context_in_transaction(
                connection,
                run_id=run_id,
                plan_id=plan_id,
            )
            if context is None:
                return None
            plan, run, _requirement, _graph = context
            if (
                plan.version != expected_plan_version
                or plan.finalization_version != expected_finalization_version
                or plan.finalization_stage is not current_stage
                or plan.status is not current_plan_status
                or run.status is not current_run_status
            ):
                return None
            if current_stage is DeepSearchFinalizationStage.TERMINAL_COMMITTED:
                return None
            if (
                plan.report_artifact_id is not None
                or plan.report_content_hash is not None
                or run.output_text is not None
                or DeepSearchFinalizationStage.TERMINAL_COMMITTED in plan.finalization_input_hashes
            ):
                raise ResearchStoreConflict("DeepSearch terminal-without-report state is invalid")
            staging_report = connection.execute(
                """SELECT 1 FROM artifacts
                WHERE run_id = ?
                  AND artifact_type = 'deepsearch_report'
                  AND verification_state = ?
                LIMIT 1""",
                (run.id, ArtifactVerificationState.STAGING.value),
            ).fetchone()
            if staging_report is not None:
                raise ResearchStoreConflict(
                    "DeepSearch staging report requires a typed failure transition"
                )

            now = now_utc()
            closed_budget = self._close_deepsearch_budget_for_terminal(run)
            input_hashes = dict(plan.finalization_input_hashes)
            input_hashes[DeepSearchFinalizationStage.TERMINAL_COMMITTED] = input_hash
            terminal_node_statuses = {
                SkillPlanNodeStatus.COMPLETED,
                SkillPlanNodeStatus.FAILED,
                SkillPlanNodeStatus.SKIPPED,
                SkillPlanNodeStatus.CANCELLED,
            }
            node_events: list[tuple[str, dict[str, object]]] = []
            updated_nodes: list[SkillPlanNode] = []
            for node in plan.nodes:
                if node.status in terminal_node_statuses:
                    updated_nodes.append(node)
                    continue
                updated_nodes.append(
                    node.model_copy(
                        update={
                            "status": SkillPlanNodeStatus.CANCELLED,
                            "completed_at": now,
                        }
                    )
                )
                node_events.append(
                    (
                        "node_cancelled",
                        {
                            "plan_id": plan.id,
                            "node_id": node.id,
                            "reason": error_code or final_run_status.value,
                        },
                    )
                )
            updated_plan = SkillPlan.model_validate(
                {
                    **plan.model_dump(mode="python"),
                    "status": final_plan_status,
                    "nodes": updated_nodes,
                    "finalization_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED,
                    "finalization_version": expected_finalization_version + 1,
                    "finalization_input_hashes": input_hashes,
                    "updated_at": now,
                }
            )
            updated_run = AgentRun.model_validate(
                {
                    **run.model_dump(mode="python"),
                    "deepsearch_budget": closed_budget,
                    "status": final_run_status,
                    "paused_state": None,
                    "interaction_expires_at": None,
                    "output_text": None,
                    "error_code": error_code,
                    "updated_at": now,
                }
            )
            self._write_skill_plan(connection, updated_plan)
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (updated_run.model_dump_json(), now.isoformat(), updated_run.id),
            )
            self._resolve_open_run_inboxes(
                connection,
                run.id,
                reason=error_code or final_run_status.value,
                resolved_at=now,
            )
            self._append_agent_run_events(
                connection,
                run.id,
                [
                    *node_events,
                    (
                        "deepsearch_finalization_stage_changed",
                        {
                            "plan_id": plan.id,
                            "from_stage": current_stage.value,
                            "to_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED.value,
                            "finalization_version": updated_plan.finalization_version,
                            "input_hash": input_hash,
                        },
                    ),
                    *events,
                ],
            )
        return updated_plan, updated_run

    def commit_deepsearch_terminal_with_report(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
        expected_finalization_version: int,
        expected_stage: DeepSearchFinalizationStage,
        expected_plan_status: SkillPlanStatus,
        expected_run_status: AgentRunStatus,
        staging_artifact_id: str,
        sealed_report: Artifact,
        terminal_status: AgentRunStatus,
        error_code: str | None,
        input_hash: str,
        events: list[tuple[str, dict[str, object]]],
        budget_invocation_key: str | None = None,
        budget_actual_usage: DeepSearchBudgetUsageV1 | None = None,
    ) -> tuple[SkillPlan, AgentRun] | None:
        """Seal and publish exactly one report with its Plan/Run terminal state."""

        from agentmesh.artifacts import (
            ArtifactAccessError,
            DeepSearchArtifactSchemaRegistry,
            DeepSearchReportV1,
            V1VerifiedArtifactStore,
        )

        current_stage, _terminal_stage = self._validate_deepsearch_finalization_cas_input(
            expected_plan_version=expected_plan_version,
            expected_finalization_version=expected_finalization_version,
            expected_stage=expected_stage,
            target_stage=DeepSearchFinalizationStage.TERMINAL_COMMITTED,
            input_hash=input_hash,
        )
        try:
            final_run_status = AgentRunStatus(terminal_status)
            current_plan_status = SkillPlanStatus(expected_plan_status)
            current_run_status = AgentRunStatus(expected_run_status)
            report_artifact = Artifact.model_validate(
                sealed_report.model_dump(mode="python")
            )
            parsed_report = DeepSearchArtifactSchemaRegistry.parse(
                report_artifact.artifact_type,
                report_artifact.schema_version or "",
                report_artifact.content,
            )
        except (AttributeError, ArtifactAccessError, TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch terminal report is invalid") from error
        final_plan_status = {
            AgentRunStatus.COMPLETED: SkillPlanStatus.COMPLETED,
            AgentRunStatus.PARTIAL: SkillPlanStatus.PARTIAL,
        }.get(final_run_status)
        expected_report_status = {
            AgentRunStatus.COMPLETED: "complete",
            AgentRunStatus.PARTIAL: "partial",
        }.get(final_run_status)
        expected_terminal_event = {
            AgentRunStatus.COMPLETED: "run_completed",
            AgentRunStatus.PARTIAL: "run_partial",
        }.get(final_run_status)
        if (
            final_plan_status is None
            or expected_report_status is None
            or expected_terminal_event is None
            or current_plan_status is not SkillPlanStatus.RUNNING
            or current_run_status is not AgentRunStatus.RUNNING
            or not isinstance(parsed_report, DeepSearchReportV1)
            or not isinstance(staging_artifact_id, str)
            or not staging_artifact_id
            or staging_artifact_id != report_artifact.id
            or report_artifact.verification_state is not ArtifactVerificationState.SEALED
            or report_artifact.artifact_type != "deepsearch_report"
            or report_artifact.schema_version != "deepsearch-report-v1"
            or parsed_report.report_status != expected_report_status
            or (final_run_status is AgentRunStatus.COMPLETED and error_code is not None)
            or (
                final_run_status is AgentRunStatus.PARTIAL
                and (
                    not isinstance(error_code, str)
                    or not error_code
                    or len(error_code) > 120
                )
            )
            or not events
            or len(events) > 16
            or events[-1][0] != expected_terminal_event
            or events[-1][1].get("error_code") != error_code
            or any(
                not isinstance(event_type, str)
                or not event_type
                or len(event_type) > 120
                or not isinstance(payload, dict)
                for event_type, payload in events
            )
        ):
            raise ResearchStoreConflict("DeepSearch terminal report is invalid")
        if (
            (budget_invocation_key is None) != (budget_actual_usage is None)
            or budget_invocation_key is None
        ):
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")

        persistence_started_at = monotonic()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._load_deepsearch_finalization_context_in_transaction(
                connection,
                run_id=run_id,
                plan_id=plan_id,
            )
            if context is None:
                return None
            plan, run, requirement, graph = context
            report_revision = plan.report_revision_count
            expected_review_stage = (
                DeepSearchFinalizationStage.REVIEW_V0_CHECKED
                if report_revision == 0
                else DeepSearchFinalizationStage.REVIEW_V1_CHECKED
            )
            is_exact_replay = (
                plan.version == expected_plan_version
                and plan.finalization_version == expected_finalization_version + 1
                and plan.finalization_stage
                is DeepSearchFinalizationStage.TERMINAL_COMMITTED
                and plan.finalization_input_hashes.get(
                    DeepSearchFinalizationStage.TERMINAL_COMMITTED
                )
                == input_hash
                and plan.status is final_plan_status
                and run.status is final_run_status
            )
            if is_exact_replay:
                if (
                    plan.report_artifact_id != report_artifact.id
                    or plan.report_content_hash != report_artifact.content_hash
                    or run.output_text != parsed_report.rendered_text
                    or run.error_code != error_code
                ):
                    raise ResearchStoreConflict(
                        "DeepSearch terminal report replay conflicts"
                    )
                try:
                    V1VerifiedArtifactStore(self).seal_report(
                        report_artifact,
                        connection=connection,
                    )
                except ArtifactAccessError as error:
                    raise ResearchStoreConflict(
                        "DeepSearch terminal report replay conflicts"
                    ) from error
                return plan, run
            if (
                plan.version != expected_plan_version
                or plan.finalization_version != expected_finalization_version
                or plan.finalization_stage is not current_stage
                or plan.status is not current_plan_status
                or run.status is not current_run_status
            ):
                return None
            if current_stage is not expected_review_stage:
                raise ResearchStoreConflict("DeepSearch terminal report stage is invalid")
            if (
                plan.report_artifact_id is not None
                or plan.report_content_hash is not None
                or run.output_text is not None
                or DeepSearchFinalizationStage.TERMINAL_COMMITTED
                in plan.finalization_input_hashes
                or len(plan.deepsearch_syntheses) != report_revision + 1
                or len(plan.synthesis_content_hashes) != report_revision + 1
                or len(plan.review_outcomes) != report_revision + 1
                or plan.evidence_coverage is None
                or plan.evidence_coverage.revision_count != report_revision
            ):
                raise ResearchStoreConflict("DeepSearch terminal report state is invalid")

            synthesis = plan.deepsearch_syntheses[report_revision]
            synthesis_hash = plan.synthesis_content_hashes[report_revision]
            coverage = plan.evidence_coverage
            review_outcome = plan.review_outcomes[report_revision]
            review = review_outcome.review
            excluded_claim_ids = (
                set(review.unsupported_claim_ids)
                | set(review.contradictory_claim_ids)
                if review is not None
                else set()
            )
            safe_claim_ids = set(coverage.validated_claim_ids) - excluded_claim_ids
            if review is not None and review.verdict == "block" and not excluded_claim_ids:
                safe_claim_ids.clear()
            expected_claims = [
                claim
                for claim in synthesis.claims
                if claim.id in safe_claim_ids
                and set(claim.question_ids).issubset(
                    {question.id for question in graph.questions}
                )
            ]
            if (
                parsed_report.run_id != run.id
                or parsed_report.requirement_version_id != requirement.id
                or parsed_report.plan_id != plan.id
                or parsed_report.plan_version != plan.version
                or parsed_report.requirement_content_hash != requirement.content_hash
                or parsed_report.problem_graph_hash != graph.content_hash
                or parsed_report.plan_content_hash != plan.plan_content_hash
                or parsed_report.evidence_manifest_hash
                != plan.evidence_manifest_hash
                or parsed_report.synthesis_content_hash != synthesis_hash
                or parsed_report.review_outcome != review_outcome.outcome
                or parsed_report.review_reason_code != review_outcome.reason_code
                or [claim.model_dump(mode="python") for claim in parsed_report.claims]
                != [claim.model_dump(mode="python") for claim in expected_claims]
                or (
                    final_run_status is AgentRunStatus.COMPLETED
                    and (
                        not coverage.passed
                        or review_outcome.outcome != "pass"
                        or synthesis.synthesis_mode != "model"
                        or any(
                            node.status is not SkillPlanNodeStatus.COMPLETED
                            for node in plan.nodes
                        )
                    )
                )
            ):
                raise ResearchStoreConflict("DeepSearch terminal report lineage is invalid")

            try:
                V1VerifiedArtifactStore(self).seal_report(
                    report_artifact,
                    connection=connection,
                )
            except ArtifactAccessError as error:
                raise ResearchStoreConflict("DeepSearch terminal report is invalid") from error
            now = now_utc()
            closed_budget = self._close_deepsearch_budget_for_terminal(
                run,
                settlement_invocation_key=budget_invocation_key,
                settlement_actual_usage=budget_actual_usage,
                settlement_additional_active_seconds=max(
                    monotonic() - persistence_started_at,
                    0,
                ),
            )
            input_hashes = dict(plan.finalization_input_hashes)
            input_hashes[DeepSearchFinalizationStage.TERMINAL_COMMITTED] = input_hash
            updated_plan = SkillPlan.model_validate(
                {
                    **plan.model_dump(mode="python"),
                    "status": final_plan_status,
                    "report_artifact_id": report_artifact.id,
                    "report_content_hash": report_artifact.content_hash,
                    "finalization_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED,
                    "finalization_version": expected_finalization_version + 1,
                    "finalization_input_hashes": input_hashes,
                    "updated_at": now,
                }
            )
            updated_run = AgentRun.model_validate(
                {
                    **run.model_dump(mode="python"),
                    "deepsearch_budget": closed_budget,
                    "status": final_run_status,
                    "paused_state": None,
                    "interaction_expires_at": None,
                    "output_text": parsed_report.rendered_text,
                    "error_code": error_code,
                    "updated_at": now,
                }
            )
            self._write_skill_plan(connection, updated_plan)
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (updated_run.model_dump_json(), now.isoformat(), updated_run.id),
            )
            self._resolve_open_run_inboxes(
                connection,
                run.id,
                reason=error_code or final_run_status.value,
                resolved_at=now,
            )
            self._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "deepsearch_finalization_stage_changed",
                        {
                            "plan_id": plan.id,
                            "from_stage": current_stage.value,
                            "to_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED.value,
                            "finalization_version": updated_plan.finalization_version,
                            "input_hash": input_hash,
                        },
                    ),
                    *events,
                ],
            )
        return updated_plan, updated_run

    def fail_deepsearch_staging_report_and_commit_terminal(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
        expected_finalization_version: int,
        expected_stage: DeepSearchFinalizationStage,
        expected_plan_status: SkillPlanStatus,
        expected_run_status: AgentRunStatus,
        staging_artifact_id: str,
        failed_report: Artifact,
        error_code: str,
        input_hash: str,
        events: list[tuple[str, dict[str, object]]],
    ) -> tuple[SkillPlan, AgentRun] | None:
        """Fail a STAGING report and the owning Plan/Run in one transaction."""

        from agentmesh.artifacts import ArtifactAccessError, V1VerifiedArtifactStore

        current_stage, _terminal_stage = self._validate_deepsearch_finalization_cas_input(
            expected_plan_version=expected_plan_version,
            expected_finalization_version=expected_finalization_version,
            expected_stage=expected_stage,
            target_stage=DeepSearchFinalizationStage.TERMINAL_COMMITTED,
            input_hash=input_hash,
        )
        try:
            current_plan_status = SkillPlanStatus(expected_plan_status)
            current_run_status = AgentRunStatus(expected_run_status)
            report_artifact = Artifact.model_validate(
                failed_report.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch failed report is invalid") from error
        if (
            not isinstance(staging_artifact_id, str)
            or not staging_artifact_id
            or current_plan_status is not SkillPlanStatus.RUNNING
            or current_run_status is not AgentRunStatus.RUNNING
            or staging_artifact_id != report_artifact.id
            or report_artifact.artifact_type != "deepsearch_report"
            or report_artifact.schema_version != "deepsearch-report-v1"
            or report_artifact.verification_state is not ArtifactVerificationState.FAILED
            or report_artifact.content
            or report_artifact.content_hash is not None
            or report_artifact.size_bytes is not None
            or not isinstance(error_code, str)
            or not error_code
            or len(error_code) > 120
            or not events
            or len(events) > 16
            or events[-1][0] != "run_failed"
            or events[-1][1].get("error_code") != error_code
            or any(
                not isinstance(event_type, str)
                or not event_type
                or len(event_type) > 120
                or not isinstance(payload, dict)
                for event_type, payload in events
            )
        ):
            raise ResearchStoreConflict("DeepSearch failed report is invalid")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._load_deepsearch_finalization_context_in_transaction(
                connection,
                run_id=run_id,
                plan_id=plan_id,
            )
            if context is None:
                return None
            plan, run, _requirement, _graph = context
            expected_review_stage = (
                DeepSearchFinalizationStage.REVIEW_V0_CHECKED
                if plan.report_revision_count == 0
                else DeepSearchFinalizationStage.REVIEW_V1_CHECKED
            )
            is_exact_replay = (
                plan.version == expected_plan_version
                and plan.finalization_version == expected_finalization_version + 1
                and plan.finalization_stage
                is DeepSearchFinalizationStage.TERMINAL_COMMITTED
                and plan.finalization_input_hashes.get(
                    DeepSearchFinalizationStage.TERMINAL_COMMITTED
                )
                == input_hash
                and plan.status is SkillPlanStatus.FAILED
                and run.status is AgentRunStatus.FAILED
                and run.error_code == error_code
                and run.output_text is None
                and plan.report_artifact_id is None
                and plan.report_content_hash is None
            )
            if is_exact_replay:
                try:
                    V1VerifiedArtifactStore(self).fail_report(
                        report_artifact,
                        connection=connection,
                    )
                except ArtifactAccessError as error:
                    raise ResearchStoreConflict(
                        "DeepSearch failed report replay conflicts"
                    ) from error
                return plan, run
            if (
                plan.version != expected_plan_version
                or plan.finalization_version != expected_finalization_version
                or plan.finalization_stage is not current_stage
                or plan.status is not current_plan_status
                or run.status is not current_run_status
            ):
                return None
            if current_stage is not expected_review_stage:
                raise ResearchStoreConflict("DeepSearch failed report stage is invalid")
            if (
                plan.report_artifact_id is not None
                or plan.report_content_hash is not None
                or run.output_text is not None
                or DeepSearchFinalizationStage.TERMINAL_COMMITTED
                in plan.finalization_input_hashes
            ):
                raise ResearchStoreConflict("DeepSearch failed report state is invalid")
            try:
                V1VerifiedArtifactStore(self).fail_report(
                    report_artifact,
                    connection=connection,
                )
            except ArtifactAccessError as error:
                raise ResearchStoreConflict("DeepSearch failed report is invalid") from error

            now = now_utc()
            closed_budget = self._close_deepsearch_budget_for_terminal(run)
            input_hashes = dict(plan.finalization_input_hashes)
            input_hashes[DeepSearchFinalizationStage.TERMINAL_COMMITTED] = input_hash
            updated_plan = SkillPlan.model_validate(
                {
                    **plan.model_dump(mode="python"),
                    "status": SkillPlanStatus.FAILED,
                    "finalization_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED,
                    "finalization_version": expected_finalization_version + 1,
                    "finalization_input_hashes": input_hashes,
                    "updated_at": now,
                }
            )
            updated_run = AgentRun.model_validate(
                {
                    **run.model_dump(mode="python"),
                    "deepsearch_budget": closed_budget,
                    "status": AgentRunStatus.FAILED,
                    "paused_state": None,
                    "interaction_expires_at": None,
                    "output_text": None,
                    "error_code": error_code,
                    "updated_at": now,
                }
            )
            self._write_skill_plan(connection, updated_plan)
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (updated_run.model_dump_json(), now.isoformat(), updated_run.id),
            )
            self._resolve_open_run_inboxes(
                connection,
                run.id,
                reason=error_code,
                resolved_at=now,
            )
            self._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "deepsearch_finalization_stage_changed",
                        {
                            "plan_id": plan.id,
                            "from_stage": current_stage.value,
                            "to_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED.value,
                            "finalization_version": updated_plan.finalization_version,
                            "input_hash": input_hash,
                        },
                    ),
                    *events,
                ],
            )
        return updated_plan, updated_run

    @staticmethod
    def _validate_deepsearch_execution_authorization_in_transaction(
        connection: sqlite3.Connection,
        *,
        run: AgentRun,
        plan: SkillPlan,
    ) -> User:
        """Recheck mutable owner, project, thread, and Skill grants before execution."""

        user_row = connection.execute(
            "SELECT id, payload FROM records WHERE collection = ? AND id = ?",
            ("users", run.user_id),
        ).fetchone()
        project_row = connection.execute(
            "SELECT id, payload FROM records WHERE collection = ? AND id = ?",
            ("projects", run.project_id),
        ).fetchone()
        thread_row = connection.execute(
            "SELECT id, payload FROM records WHERE collection = ? AND id = ?",
            ("chat_threads", run.thread_id),
        ).fetchone()
        if user_row is None or project_row is None or thread_row is None:
            raise ResearchStoreConflict("DeepSearch execution authorization is invalid")
        try:
            user = User.model_validate_json(user_row["payload"])
            project = Project.model_validate_json(project_row["payload"])
            thread = ChatThread.model_validate_json(thread_row["payload"])
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch execution authorization is invalid") from error
        if (
            user.id != user_row["id"]
            or user.id != run.user_id
            or user.status != "active"
            or user.workspace_id != run.workspace_id
            or project.id != project_row["id"]
            or project.id != run.project_id
            or project.status != "active"
            or project.workspace_id != run.workspace_id
            or (project.member_ids and user.id not in project.member_ids)
            or thread.id != thread_row["id"]
            or thread.id != run.thread_id
            or thread.status != "active"
            or thread.user_id != user.id
            or thread.workspace_id != run.workspace_id
            or thread.project_id != run.project_id
        ):
            raise ResearchStoreConflict("DeepSearch execution authorization is invalid")

        selected_skill_ids = {node.skill_id for node in plan.nodes}
        if not selected_skill_ids:
            return user
        binding_rows = connection.execute(
            "SELECT id, payload FROM records WHERE collection = ? ORDER BY created_order",
            ("skill_bindings",),
        ).fetchall()
        try:
            bindings = [
                SkillBinding.model_validate_json(row["payload"])
                for row in binding_rows
            ]
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch execution authorization is invalid") from error
        if any(
            binding.id != row["id"]
            for binding, row in zip(bindings, binding_rows, strict=True)
        ) or any(
            binding.agent_id == user.personal_agent_id
            and binding.skill_id in selected_skill_ids
            and not binding.enabled
            for binding in bindings
        ):
            raise ResearchStoreConflict("DeepSearch execution authorization is invalid")
        return user

    def claim_skill_plan_for_execution(self, plan_id: str, run_id: str) -> SkillPlan | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan_id,)).fetchone()
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if plan_row is None or run_row is None:
                return None
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
            if (
                self._is_retired_research_run(run, run_row["orchestration_version"])
                or plan.run_id != run.id
                or plan.status != SkillPlanStatus.APPROVED
                or run.status != AgentRunStatus.RUNNING
            ):
                return None
            if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
                if (
                    run_row["orchestration_version"] != "v1"
                    or run.orchestration_version != "v1"
                    or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
                    or run.plan_id != plan.id
                ):
                    raise ResearchStoreConflict("DeepSearch execution Plan identity is invalid")
                requirement_row = connection.execute(
                    """SELECT * FROM deepsearch_requirement_versions
                    WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
                    (run.id,),
                ).fetchone()
                if requirement_row is None:
                    raise ResearchStoreConflict("DeepSearch execution Requirement is missing")
                requirement = self._decode_deepsearch_requirement_row(requirement_row)
                plan, expected_plan_hash = self._validate_deepsearch_plan_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=plan,
                )
                self._load_deepsearch_plan_snapshot_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=plan,
                    expected_plan_hash=expected_plan_hash,
                )
            elif plan.planning_mode is AgentPlanningMode.DEEPSEARCH:
                raise ResearchStoreConflict("DeepSearch execution Plan identity is invalid")
            elif (
                run.planning_contract_version
                is AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
                and (
                    run.execution_contract_version is None
                    or run.execution_contract_version != plan.execution_contract_version
                    or plan.candidate_snapshot is None
                )
            ):
                raise ResearchStoreConflict("Universal execution contract is unavailable")
            plan.status = SkillPlanStatus.RUNNING
            plan.updated_at = now_utc()
            self._write_skill_plan(connection, plan)
        return plan

    def claim_skill_plan_node(self, plan_id: str, node_id: str) -> SkillPlanNode | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan_id,)).fetchone()
            node_row = connection.execute(
                "SELECT payload FROM skill_plan_nodes WHERE plan_id = ? AND id = ?",
                (plan_id, node_id),
            ).fetchone()
            if plan_row is None or node_row is None:
                return None
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (plan.run_id,),
            ).fetchone()
            if run_row is None:
                return None
            run = AgentRun.model_validate_json(run_row["payload"])
            node = SkillPlanNode.model_validate_json(node_row["payload"])
            if (
                self._is_retired_research_run(run, run_row["orchestration_version"])
                or plan.status != SkillPlanStatus.RUNNING
                or run.status != AgentRunStatus.RUNNING
                or node.status != SkillPlanNodeStatus.READY
                or node.attempt >= 2
                or (
                    run.planning_contract_version
                    is AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1
                    and (
                        run.execution_contract_version is None
                        or run.execution_contract_version != plan.execution_contract_version
                        or plan.candidate_snapshot is None
                    )
                )
            ):
                return None
            node.status = SkillPlanNodeStatus.RUNNING
            node.attempt += 1
            node.started_at = now_utc()
            plan.nodes = [node if item.id == node.id else item for item in plan.nodes]
            plan.updated_at = now_utc()
            self._write_skill_plan(connection, plan)
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_run_events WHERE run_id = ?",
                (run.id,),
            ).fetchone()[0]
            event = AgentRunEvent(
                run_id=run.id,
                sequence=sequence,
                event_type="node_started",
                payload={"plan_id": plan.id, "node_id": node.id, "attempt": node.attempt},
            )
            connection.execute(
                "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (run.id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
            )
        return node

    def transition_skill_plan_node(
        self,
        *,
        plan_id: str,
        run_id: str,
        node: SkillPlanNode,
        expected_statuses: set[SkillPlanNodeStatus],
        event_type: str,
        event_payload: dict[str, object],
        result: SkillNodeResult | None = None,
        clear_run_paused_state: bool = False,
        expected_attempt: int | None = None,
    ) -> SkillPlanNode | None:
        """CAS one node transition, optional immutable result, and event in one transaction."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan_id,)).fetchone()
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            node_row = connection.execute(
                "SELECT payload FROM skill_plan_nodes WHERE plan_id = ? AND id = ?",
                (plan_id, node.id),
            ).fetchone()
            if plan_row is None or run_row is None or node_row is None:
                return None
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
            current = SkillPlanNode.model_validate_json(node_row["payload"])
            required_attempt = node.attempt if expected_attempt is None else expected_attempt
            if (
                self._is_retired_research_run(run, run_row["orchestration_version"])
                or plan.run_id != run.id
                or run.id != run_id
                or plan.status != SkillPlanStatus.RUNNING
                or run.status != AgentRunStatus.RUNNING
                or current.status not in expected_statuses
                or current.attempt != required_attempt
            ):
                return None
            if result is not None:
                if (
                    result.node_id != current.id
                    or result.skill_id != current.skill_id
                    or result.attempt != current.attempt
                ):
                    return None
                exists = connection.execute(
                    "SELECT 1 FROM skill_node_results WHERE plan_id = ? AND node_id = ? AND attempt = ?",
                    (plan.id, result.node_id, result.attempt),
                ).fetchone()
                if exists is not None:
                    return None
                connection.execute(
                    """
                    INSERT INTO skill_node_results(plan_id, node_id, attempt, payload, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (plan.id, result.node_id, result.attempt, result.model_dump_json(), result.created_at.isoformat()),
                )
            plan.nodes = [node if item.id == node.id else item for item in plan.nodes]
            plan.updated_at = now_utc()
            self._write_skill_plan(connection, plan)
            if clear_run_paused_state:
                run.paused_state = None
                if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
                    run.interaction_expires_at = None
                run.updated_at = now_utc()
                connection.execute(
                    "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                    (run.model_dump_json(), run.updated_at.isoformat(), run.id),
                )
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_run_events WHERE run_id = ?",
                (run.id,),
            ).fetchone()[0]
            event = AgentRunEvent(
                run_id=run.id,
                sequence=sequence,
                event_type=event_type,
                payload=event_payload,
            )
            connection.execute(
                "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (run.id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
            )
        return node

    def pause_skill_plan_node_and_run(
        self,
        *,
        plan_id: str,
        run_id: str,
        node_id: str,
        attempt: int,
        paused_state: dict[str, object],
        inbox_item: InboxItem,
        call_ids: list[str],
    ) -> tuple[SkillPlan, AgentRun, SkillPlanNode] | None:
        """Atomically pause one running node, its parent Run, events, and approval inbox."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan_id,)).fetchone()
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            node_row = connection.execute(
                "SELECT payload FROM skill_plan_nodes WHERE plan_id = ? AND id = ?",
                (plan_id, node_id),
            ).fetchone()
            if plan_row is None or run_row is None or node_row is None:
                return None
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
            node = SkillPlanNode.model_validate_json(node_row["payload"])
            if (
                self._is_retired_research_run(run, run_row["orchestration_version"])
                or plan.run_id != run.id
                or run.id != run_id
                or plan.status != SkillPlanStatus.RUNNING
                or run.status != AgentRunStatus.RUNNING
                or node.status != SkillPlanNodeStatus.RUNNING
                or node.attempt != attempt
            ):
                return None
            now = now_utc()
            node.status = SkillPlanNodeStatus.WAITING_TOOL_APPROVAL
            plan.nodes = [node if item.id == node.id else item for item in plan.nodes]
            plan.updated_at = now
            run.status = AgentRunStatus.WAITING_APPROVAL
            run.paused_state = paused_state
            if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
                interaction_expires_at = now + timedelta(hours=24)
                if run.absolute_expires_at is not None:
                    interaction_expires_at = min(interaction_expires_at, run.absolute_expires_at)
                run.interaction_expires_at = interaction_expires_at
            run.updated_at = now
            self._write_skill_plan(connection, plan)
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), now.isoformat(), run.id),
            )
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM agent_run_events WHERE run_id = ?",
                (run.id,),
            ).fetchone()[0]
            for event_type, payload in (
                ("node_waiting_tool_approval", {"plan_id": plan.id, "node_id": node.id}),
                ("approval_requested", {"plan_id": plan.id, "node_id": node.id, "call_ids": call_ids}),
            ):
                sequence += 1
                event = AgentRunEvent(run_id=run.id, sequence=sequence, event_type=event_type, payload=payload)
                connection.execute(
                    "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (run.id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
                )
            connection.execute(
                """
                INSERT INTO records(collection, id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload
                """,
                ("inbox_items", inbox_item.id, inbox_item.model_dump_json()),
            )
        return plan, run, node

    def update_skill_plan_node(self, plan_id: str, node: SkillPlanNode) -> SkillPlan | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan_id,)).fetchone()
            if row is None:
                return None
            plan = SkillPlan.model_validate_json(row["payload"])
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (plan.run_id,),
            ).fetchone()
            if run_row is not None:
                run = AgentRun.model_validate_json(run_row["payload"])
                if self._is_retired_research_run(run, run_row["orchestration_version"]):
                    return None
            if not any(item.id == node.id for item in plan.nodes):
                return None
            plan.nodes = [node if item.id == node.id else item for item in plan.nodes]
            plan.updated_at = now_utc()
            self._write_skill_plan(connection, plan)
        return plan

    def save_skill_node_result(self, plan_id: str, result: SkillNodeResult) -> SkillNodeResult:
        with self._connect() as connection:
            run_row = connection.execute(
                """SELECT agent_runs.payload, agent_runs.orchestration_version
                FROM skill_plans
                JOIN agent_runs ON agent_runs.id = skill_plans.run_id
                WHERE skill_plans.id = ?""",
                (plan_id,),
            ).fetchone()
            if run_row is not None:
                run = AgentRun.model_validate_json(run_row["payload"])
                if self._is_retired_research_run(run, run_row["orchestration_version"]):
                    raise ResearchStoreConflict("research-v2 runs are historical and read-only")
            connection.execute(
                """
                INSERT INTO skill_node_results(plan_id, node_id, attempt, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (plan_id, result.node_id, result.attempt, result.model_dump_json(), result.created_at.isoformat()),
            )
        return result

    def list_skill_node_results(self, plan_id: str) -> list[SkillNodeResult]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM skill_node_results WHERE plan_id = ? ORDER BY created_at, node_id, attempt",
                (plan_id,),
            ).fetchall()
        return [SkillNodeResult.model_validate_json(row["payload"]) for row in rows]

    def get_deepsearch_requirement(
        self,
        run_id: str,
        *,
        version: int,
    ) -> dict[str, object] | None:
        with self._read_connect() as connection:
            row = connection.execute(
                "SELECT * FROM deepsearch_requirement_versions WHERE run_id = ? AND version = ?",
                (run_id, version),
            ).fetchone()
        return self._decode_deepsearch_requirement_row(row) if row is not None else None

    def get_active_deepsearch_requirement(self, run_id: str) -> dict[str, object] | None:
        """Return the latest append-only Requirement version for a DeepSearch Run."""
        with self._read_connect() as connection:
            row = connection.execute(
                """SELECT * FROM deepsearch_requirement_versions
                WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
                (run_id,),
            ).fetchone()
        return self._decode_deepsearch_requirement_row(row) if row is not None else None

    def get_latest_deepsearch_requirement(self, run_id: str) -> dict[str, object] | None:
        return self.get_active_deepsearch_requirement(run_id)

    def get_deepsearch_requirement_by_request_key(
        self,
        run_id: str,
        request_key: str,
    ) -> dict[str, object] | None:
        with self._read_connect() as connection:
            row = connection.execute(
                "SELECT * FROM deepsearch_requirement_versions WHERE run_id = ? AND request_key = ?",
                (run_id, request_key),
            ).fetchone()
        return self._decode_deepsearch_requirement_row(row) if row is not None else None

    def get_deepsearch_state_snapshot(self, run_id: str) -> DeepSearchStateSnapshot | None:
        """Read Run, active Requirement, and Plan from one SQLite snapshot."""
        with self._read_connect() as connection:
            connection.execute("BEGIN")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            requirement_row = connection.execute(
                """SELECT * FROM deepsearch_requirement_versions
                WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
                (run_id,),
            ).fetchone()
            plan_row = connection.execute(
                "SELECT id, run_id, payload FROM skill_plans WHERE run_id = ?",
                (run_id,),
            ).fetchone()

        run = self._decode_agent_run_row(run_row)
        if (
            run_row["orchestration_version"] != "v1"
            or run.orchestration_version != "v1"
            or run.planning_mode != AgentPlanningMode.DEEPSEARCH
        ):
            raise ResearchStoreConflict("Run is not a v1 DeepSearch Run")
        requirement = (
            self._decode_deepsearch_requirement_row(requirement_row)
            if requirement_row is not None
            else None
        )
        try:
            plan = SkillPlan.model_validate_json(plan_row["payload"]) if plan_row is not None else None
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch Plan failed integrity verification") from error
        if (run.plan_id is None) != (plan is None) or (
            plan is not None
            and (
                plan.id != run.plan_id
                or plan.run_id != run.id
                or plan_row["id"] != plan.id
                or plan_row["run_id"] != plan.run_id
            )
        ):
            raise ResearchStoreConflict("DeepSearch Plan failed integrity verification")
        return DeepSearchStateSnapshot(run=run, requirement=requirement, plan=plan)

    def prepare_deepsearch_requirement_append(
        self,
        *,
        run_id: str,
        user_id: str,
        request_key: str,
        request_hash: str,
        expected_requirement_version: int | None,
        expected_run_status: AgentRunStatus,
        checked_at: datetime | None = None,
    ) -> DeepSearchRequirementPrepareResult | None:
        """Freeze the input to an out-of-transaction Refiner call.

        The durable request receipt is checked before the active Requirement version so
        a client retry is distinguishable from a stale, different clarification.
        """
        now = checked_at or now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        expired_conflict: DeepSearchRequirementConflict | None = None
        prepared: DeepSearchRequirementPrepareResult | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            run = AgentRun.model_validate_json(run_row["payload"])
            if run.user_id != user_id:
                return None
            if (
                run_row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or run.planning_mode != AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("Run is not a v1 DeepSearch Run")
            if (
                not isinstance(request_key, str)
                or not request_key
                or len(request_key) > 120
                or not isinstance(request_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", request_hash)
            ):
                raise ResearchStoreConflict("DeepSearch Requirement request identity is invalid")

            replay_row = connection.execute(
                "SELECT * FROM deepsearch_requirement_versions WHERE run_id = ? AND request_key = ?",
                (run_id, request_key),
            ).fetchone()
            if replay_row is not None:
                replay = self._decode_deepsearch_requirement_row(replay_row)
                if replay_row["request_hash"] != request_hash:
                    current_version = connection.execute(
                        "SELECT MAX(version) FROM deepsearch_requirement_versions WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()[0]
                    raise DeepSearchRequirementConflict(
                        "deepsearch_requirement_idempotency_conflict",
                        current_requirement_version=current_version,
                    )
                return DeepSearchRequirementPrepareResult(requirement=replay, run=run, replayed=True)

            latest_row = connection.execute(
                """SELECT * FROM deepsearch_requirement_versions
                WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
                (run_id,),
            ).fetchone()
            current_version = latest_row["version"] if latest_row is not None else None
            expiration_code = self._deepsearch_expiration_code(run, checked_at=now)
            if expiration_code is not None:
                if run.status is not AgentRunStatus.CANCELLED:
                    self._cancel_agent_run_tree_in_transaction(
                        connection,
                        run,
                        stored_version=run_row["orchestration_version"],
                        reason=expiration_code,
                        error_code=expiration_code,
                        cancelled_at=now,
                    )
                expired_conflict = DeepSearchRequirementConflict(
                    expiration_code,
                    current_requirement_version=current_version,
                )
            elif current_version is None and (
                request_key != run.client_turn_id or request_hash != run.create_request_hash
            ):
                raise ResearchStoreConflict(
                    "Initial DeepSearch Requirement request identity does not match its Run claim"
                )
            elif current_version != expected_requirement_version:
                raise DeepSearchRequirementConflict(
                    "deepsearch_requirement_version_conflict",
                    current_requirement_version=current_version,
                )
            elif (
                expected_run_status
                != (
                    AgentRunStatus.PLANNING
                    if current_version is None
                    else AgentRunStatus.WAITING_CLARIFICATION
                )
                or run.status != expected_run_status
            ):
                raise DeepSearchRequirementConflict(
                    "deepsearch_requirement_state_conflict",
                    current_requirement_version=current_version,
                )
            else:
                current = self._decode_deepsearch_requirement_row(latest_row) if latest_row is not None else None
                prepared = DeepSearchRequirementPrepareResult(requirement=current, run=run, replayed=False)
        if expired_conflict is not None:
            raise expired_conflict
        return prepared

    def append_deepsearch_requirement_and_transition(
        self,
        *,
        run_id: str,
        user_id: str,
        requirement: dict[str, object],
        expected_requirement_version: int | None,
        expected_run_status: AgentRunStatus,
        next_run_status: AgentRunStatus,
        events: list[tuple[str, dict[str, object]]],
        interaction_expires_at: datetime | None = None,
        error_code: str | None = None,
        checked_at: datetime | None = None,
    ) -> DeepSearchRequirementAppendResult | None:
        """Append one Requirement and atomically transition its owning DeepSearch Run."""
        request_key = requirement.get("request_key")
        request_hash = requirement.get("request_hash")
        now = checked_at or now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        expired_conflict: DeepSearchRequirementConflict | None = None
        result: DeepSearchRequirementAppendResult | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            run = AgentRun.model_validate_json(run_row["payload"])
            if run.user_id != user_id:
                return None
            if (
                run_row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or run.planning_mode != AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("Run is not a v1 DeepSearch Run")
            if (
                not isinstance(request_key, str)
                or not request_key
                or len(request_key) > 120
                or not isinstance(request_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", request_hash)
            ):
                raise ResearchStoreConflict("DeepSearch Requirement request identity is invalid")

            replay_row = connection.execute(
                "SELECT * FROM deepsearch_requirement_versions WHERE run_id = ? AND request_key = ?",
                (run_id, request_key),
            ).fetchone()
            if replay_row is not None:
                replay = self._decode_deepsearch_requirement_row(replay_row)
                if replay_row["request_hash"] != request_hash:
                    current_version = connection.execute(
                        "SELECT MAX(version) FROM deepsearch_requirement_versions WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()[0]
                    raise DeepSearchRequirementConflict(
                        "deepsearch_requirement_idempotency_conflict",
                        current_requirement_version=current_version,
                    )
                return DeepSearchRequirementAppendResult(requirement=replay, run=run, replayed=True)

            latest_row = connection.execute(
                """SELECT * FROM deepsearch_requirement_versions
                WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
                (run_id,),
            ).fetchone()
            current_version = latest_row["version"] if latest_row is not None else None
            expiration_code = self._deepsearch_expiration_code(run, checked_at=now)
            if expiration_code is not None:
                if run.status is not AgentRunStatus.CANCELLED:
                    self._cancel_agent_run_tree_in_transaction(
                        connection,
                        run,
                        stored_version=run_row["orchestration_version"],
                        reason=expiration_code,
                        error_code=expiration_code,
                        cancelled_at=now,
                    )
                expired_conflict = DeepSearchRequirementConflict(
                    expiration_code,
                    current_requirement_version=current_version,
                )
            elif current_version is None and (
                request_key != run.client_turn_id or request_hash != run.create_request_hash
            ):
                raise ResearchStoreConflict(
                    "Initial DeepSearch Requirement request identity does not match its Run claim"
                )
            elif current_version != expected_requirement_version:
                raise DeepSearchRequirementConflict(
                    "deepsearch_requirement_version_conflict",
                    current_requirement_version=current_version,
                )
            elif (
                expected_run_status
                != (
                    AgentRunStatus.PLANNING
                    if current_version is None
                    else AgentRunStatus.WAITING_CLARIFICATION
                )
                or run.status != expected_run_status
            ):
                raise DeepSearchRequirementConflict(
                    "deepsearch_requirement_state_conflict",
                    current_requirement_version=current_version,
                )
            else:
                from agentmesh.deepsearch.contracts import RequirementVersionV1

                try:
                    validated_requirement = RequirementVersionV1.model_validate(requirement)
                except (TypeError, ValueError) as error:
                    raise ResearchStoreConflict(
                        "DeepSearch Requirement schema or content hash is invalid"
                    ) from error
                requirement = validated_requirement.model_dump(mode="json")
                payload = validated_requirement.payload
                blocking = any(ambiguity.blocking for ambiguity in payload.ambiguities)
                if payload.clarification_questions:
                    derived_status = AgentRunStatus.WAITING_CLARIFICATION
                    derived_error_code = None
                elif blocking:
                    derived_status = AgentRunStatus.FAILED
                    derived_error_code = "deepsearch_clarification_unresolved"
                else:
                    derived_status = AgentRunStatus.PLANNING
                    derived_error_code = None
                if next_run_status != derived_status or error_code != derived_error_code:
                    raise ResearchStoreConflict("DeepSearch Requirement transition is invalid")
                previous_requirement = (
                    self._decode_deepsearch_requirement_row(latest_row)
                    if latest_row is not None
                    else None
                )
                self._validate_deepsearch_requirement_history(
                    run_id=run_id,
                    requirement=validated_requirement,
                    previous_requirement=previous_requirement,
                )
                events = self._validate_deepsearch_requirement_events(
                    events,
                    requirement=requirement,
                    previous_requirement=previous_requirement,
                    next_run_status=derived_status,
                    error_code=derived_error_code,
                )
                waiting_statuses = {
                    AgentRunStatus.WAITING_CLARIFICATION,
                    AgentRunStatus.WAITING_PLAN_APPROVAL,
                    AgentRunStatus.WAITING_APPROVAL,
                }
                next_interaction_expires_at: datetime | None = None
                if next_run_status in waiting_statuses:
                    next_interaction_expires_at = interaction_expires_at or now + timedelta(hours=24)
                next_version = 1 if current_version is None else current_version + 1
                derived_from = self._deepsearch_requirement_parent(
                    connection,
                    run=run,
                    latest_row=latest_row,
                    requirement=requirement,
                )
                expected_projections = {
                    "run_id": run_id,
                    "version": next_version,
                    "request_key": request_key,
                    "request_hash": request_hash,
                    "derived_from_requirement_version_id": derived_from,
                }
                if any(requirement.get(key) != value for key, value in expected_projections.items()):
                    raise ResearchStoreConflict("DeepSearch Requirement projection is invalid")
                for key in ("id", "schema_version", "content_hash", "created_at"):
                    if not isinstance(requirement.get(key), str) or not requirement[key]:
                        raise ResearchStoreConflict("DeepSearch Requirement projection is invalid")
                if not isinstance(requirement.get("payload"), dict):
                    raise ResearchStoreConflict("DeepSearch Requirement payload is invalid")

                connection.execute(
                    """INSERT INTO deepsearch_requirement_versions(
                        id, run_id, version, request_key, request_hash, content_hash,
                        derived_from_requirement_version_id, schema_version, payload, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        requirement["id"],
                        run_id,
                        next_version,
                        request_key,
                        request_hash,
                        requirement["content_hash"],
                        derived_from,
                        requirement["schema_version"],
                        json.dumps(requirement, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                        requirement["created_at"],
                    ),
                )
                if derived_status is AgentRunStatus.FAILED:
                    run.deepsearch_budget = self._close_deepsearch_budget_for_terminal(run)
                run.status = next_run_status
                run.error_code = error_code
                run.updated_at = now
                if next_run_status in waiting_statuses:
                    run.interaction_expires_at = next_interaction_expires_at
                    run.deadline_at = None
                else:
                    run.interaction_expires_at = None
                connection.execute(
                    "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                    (run.model_dump_json(), now.isoformat(), run.id),
                )
                self._append_agent_run_events(connection, run.id, events)
                result = DeepSearchRequirementAppendResult(requirement=requirement, run=run, replayed=False)
        if expired_conflict is not None:
            raise expired_conflict
        return result

    def _validate_deepsearch_plan_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        run: AgentRun,
        requirement: object,
        plan: SkillPlan,
    ) -> tuple[SkillPlan, str]:
        from agentmesh.deepsearch.contracts import (
            ProblemGraphV1,
            RequirementVersionV1,
            validate_plan_question_coverage,
            validate_problem_graph_against_requirement,
        )
        from agentmesh.deepsearch.planning import plan_content_hash
        from agentmesh.deepsearch.tool_policy import DEEPSEARCH_V1_TOOL_NAMES
        from agentmesh.models import (
            SkillCandidate,
            SkillCandidateScore,
            SkillPlanDraft,
            SkillSideEffect,
        )
        from agentmesh.skill_runtime.plan_validation import validate_draft
        from agentmesh.skill_runtime.profiles import profile_matches_skill
        from agentmesh.skill_runtime.resources import (
            build_skill_resource_manifest_snapshot,
            skill_wiki_corpus_ready,
        )
        from agentmesh.skill_runtime.retrieval import (
            is_supported_wiki_capability,
            tool_name_for_capability,
            tool_names_for_profile,
        )

        try:
            requirement = RequirementVersionV1.model_validate(requirement)
            plan = SkillPlan.model_validate(plan.model_dump(mode="python"))
            graph = ProblemGraphV1.model_validate(plan.problem_graph)
            validate_problem_graph_against_requirement(graph=graph, requirement=requirement)
            validate_plan_question_coverage(graph=graph, nodes=plan.nodes)
            expected_plan_hash = plan_content_hash(plan)
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch Plan integrity is invalid") from error
        if (
            plan.run_id != run.id
            or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
            or plan.requirement_version_id != requirement.id
            or plan.requirement_content_hash != requirement.content_hash
            or plan.problem_graph_hash != graph.content_hash
            or plan.plan_content_hash != expected_plan_hash
            or len(plan.candidate_skill_ids) != len(set(plan.candidate_skill_ids))
            or any(node.side_effect not in {SkillSideEffect.READ, SkillSideEffect.DRAFT} for node in plan.nodes)
            or any(
                node.status is not SkillPlanNodeStatus.PENDING
                or node.attempt != 0
                or node.error_code is not None
                or node.started_at is not None
                or node.completed_at is not None
                for node in plan.nodes
            )
        ):
            raise ResearchStoreConflict("DeepSearch Plan integrity is invalid")

        user = self._validate_deepsearch_execution_authorization_in_transaction(
            connection,
            run=run,
            plan=plan,
        )

        required_tool_references = {
            reference for node in plan.nodes for reference in node.required_tool_names
        }
        tool_definitions: list[ToolDefinition] = []
        granted_tool_ids: set[str] = set()
        if required_tool_references:
            tool_rows = connection.execute(
                "SELECT id, payload FROM records WHERE collection = ?",
                ("tool_definitions",),
            ).fetchall()
            grant_rows = connection.execute(
                "SELECT payload FROM records WHERE collection = ?",
                ("agent_tool_grants",),
            ).fetchall()
            try:
                tool_definitions = [
                    ToolDefinition.model_validate_json(row["payload"])
                    for row in tool_rows
                ]
                if any(tool.id != row["id"] for tool, row in zip(tool_definitions, tool_rows, strict=True)):
                    raise ValueError("DeepSearch Tool projection is invalid")
                grants = [
                    AgentToolGrant.model_validate_json(row["payload"])
                    for row in grant_rows
                ]
            except (TypeError, ValueError) as error:
                raise ResearchStoreConflict("DeepSearch Plan integrity is invalid") from error
            granted_tool_ids = {
                grant.tool_id
                for grant in grants
                if grant.agent_id == user.personal_agent_id and grant.enabled
            }

        current_candidates: list[SkillCandidate] = []
        for node in plan.nodes:
            skill_row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("skill_definitions", node.skill_id),
            ).fetchone()
            profile_row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("skill_capability_profiles", node.skill_id),
            ).fetchone()
            if skill_row is None or profile_row is None:
                raise ResearchStoreConflict("DeepSearch Plan integrity is invalid")
            try:
                skill = SkillDefinition.model_validate_json(skill_row["payload"])
                profile = SkillCapabilityProfile.model_validate_json(profile_row["payload"])
                resource_manifest = build_skill_resource_manifest_snapshot(skill, profile)
            except (TypeError, ValueError) as error:
                raise ResearchStoreConflict("DeepSearch Plan integrity is invalid") from error
            for capability in profile.required_capabilities:
                if capability.startswith("wiki."):
                    capability_ready = (
                        is_supported_wiki_capability(capability)
                        and skill_wiki_corpus_ready(skill, capability)
                    )
                else:
                    capability_ready = tool_name_for_capability(capability) is not None
                if not capability_ready:
                    raise ResearchStoreConflict("DeepSearch Plan integrity is invalid")
            expected_tool_names = tool_names_for_profile(profile)
            if (
                skill.id != node.skill_id
                or profile.id != node.skill_id
                or node.skill_id not in plan.candidate_skill_ids
                or not skill.enabled
                or node.skill_version != skill.version
                or node.skill_content_hash != skill.content_hash
                or not profile.planner_eligible
                or not profile_matches_skill(profile, skill)
                or node.resource_manifest != resource_manifest
                or node.side_effect is not profile.side_effect
                or len(node.required_tool_names) != len(set(node.required_tool_names))
                or set(node.required_tool_names) != expected_tool_names
                or not expected_tool_names.issubset(DEEPSEARCH_V1_TOOL_NAMES)
            ):
                raise ResearchStoreConflict("DeepSearch Plan integrity is invalid")
            current_candidates.append(
                SkillCandidate(
                    skill_id=skill.id,
                    skill_name=skill.name,
                    title=skill.title,
                    description=skill.description,
                    profile=profile,
                    score=SkillCandidateScore(),
                    reason=node.reason,
                )
            )
            for reference in node.required_tool_names:
                matching_tools = [
                    tool
                    for tool in tool_definitions
                    if reference in {tool.id, tool.name, tool.external_name}
                ]
                if (
                    len(matching_tools) != 1
                    or matching_tools[0].name not in DEEPSEARCH_V1_TOOL_NAMES
                    or not matching_tools[0].enabled
                    or matching_tools[0].side_effect != "read"
                    or matching_tools[0].id not in granted_tool_ids
                ):
                    raise ResearchStoreConflict("DeepSearch Plan integrity is invalid")

        try:
            validate_draft(
                SkillPlanDraft(
                    output_contract=plan.output_contract,
                    synthesis_output_contract=plan.synthesis_output_contract,
                    capability_gaps=plan.capability_gaps,
                    nodes=plan.nodes,
                ),
                current_candidates,
                intent=plan.intent,
            )
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch Plan integrity is invalid") from error
        return plan, expected_plan_hash

    @staticmethod
    def _validate_deepsearch_plan_snapshot(
        *,
        run: AgentRun,
        requirement: object,
        plan: SkillPlan,
        plan_snapshot: Artifact,
        expected_plan_hash: str,
    ) -> Artifact:
        from agentmesh.deepsearch.contracts import RequirementVersionV1
        from agentmesh.deepsearch.planning import build_deepsearch_plan_snapshot

        try:
            requirement = RequirementVersionV1.model_validate(requirement)
            plan_snapshot = Artifact.model_validate(plan_snapshot.model_dump(mode="python"))
            expected_snapshot = build_deepsearch_plan_snapshot(
                run=run,
                plan=plan,
                created_at=plan_snapshot.created_at,
            )
        except (TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch Plan snapshot is invalid") from error
        if (
            plan.requirement_version_id != requirement.id
            or plan.requirement_content_hash != requirement.content_hash
            or plan.plan_content_hash != expected_plan_hash
            or plan_snapshot != expected_snapshot
        ):
            raise ResearchStoreConflict("DeepSearch Plan snapshot is invalid")
        return plan_snapshot

    def _insert_deepsearch_plan_snapshot_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        run: AgentRun,
        requirement: object,
        plan: SkillPlan,
        plan_snapshot: Artifact,
        expected_plan_hash: str,
    ) -> Artifact:
        from agentmesh.artifacts import ArtifactAccessError, V1VerifiedArtifactStore

        plan_snapshot = self._validate_deepsearch_plan_snapshot(
            run=run,
            requirement=requirement,
            plan=plan,
            plan_snapshot=plan_snapshot,
            expected_plan_hash=expected_plan_hash,
        )
        try:
            return V1VerifiedArtifactStore(self).insert_sealed(
                plan_snapshot,
                connection=connection,
            )
        except ArtifactAccessError as error:
            raise ResearchStoreConflict("DeepSearch Plan snapshot is invalid") from error

    def _charge_deepsearch_plan_snapshot_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        run: AgentRun,
        plan_snapshot: Artifact,
        charged_at: datetime,
    ) -> AgentRun:
        """Account for a sealed Plan snapshot in the transaction that inserts it."""

        budget = run.deepsearch_budget
        if budget is None:
            raise DeepSearchBudgetConflict("deepsearch_budget_run_invalid")
        content_bytes = plan_snapshot.content.encode("utf-8")
        if (
            plan_snapshot.artifact_type != "deepsearch_plan_snapshot"
            or plan_snapshot.verification_state is not ArtifactVerificationState.SEALED
            or plan_snapshot.size_bytes != len(content_bytes)
            or len(content_bytes) > 1_048_576
        ):
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")

        artifact_identity = {
            "artifact_id": plan_snapshot.id,
            "artifact_type": plan_snapshot.artifact_type,
            "run_id": plan_snapshot.run_id,
        }
        logical_operation_key = f"artifact:{canonical_json_sha256(artifact_identity)}"
        invocation_key = f"{logical_operation_key}:attempt:1"
        usage = DeepSearchBudgetUsageV1(artifact_bytes=len(content_bytes))
        reservation = DeepSearchBudgetReservationV1(
            logical_operation_key=logical_operation_key,
            invocation_key=invocation_key,
            physical_attempt=1,
            resource_maxima=usage,
            status="settled",
            actual_usage=usage,
        )
        matching = [
            item for item in budget.reservations if item.invocation_key == invocation_key
        ]
        artifact_exists = connection.execute(
            "SELECT 1 FROM artifacts WHERE id = ?",
            (plan_snapshot.id,),
        ).fetchone() is not None
        if matching:
            if len(matching) != 1 or matching[0] != reservation or not artifact_exists:
                raise DeepSearchBudgetConflict("deepsearch_budget_invocation_conflict")
            return run
        if artifact_exists:
            raise DeepSearchBudgetConflict("deepsearch_budget_invocation_conflict")
        if run.status not in {
            AgentRunStatus.PLANNING,
            AgentRunStatus.WAITING_PLAN_APPROVAL,
        }:
            raise DeepSearchBudgetConflict("deepsearch_budget_state_conflict")

        reservations = [*budget.reservations, reservation]
        candidate_budget = budget.model_copy(
            update={
                "version": budget.version + 1,
                "consumed": self._billed_deepsearch_budget_usage(reservations),
                "reservations": reservations,
            }
        )
        self._validate_deepsearch_budget_ledger(candidate_budget)
        try:
            updated_budget = DeepSearchBudgetV1.model_validate(
                candidate_budget.model_dump(mode="python")
            )
        except (TypeError, ValueError) as error:
            raise DeepSearchBudgetConflict("deepsearch_budget_settlement_invalid") from error
        return self._write_deepsearch_budget_run(
            connection,
            run=run,
            budget=updated_budget,
            updated_at=charged_at,
        )

    def _load_deepsearch_plan_snapshot_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        run: AgentRun,
        requirement: object,
        plan: SkillPlan,
        expected_plan_hash: str,
    ) -> Artifact:
        from agentmesh.artifacts import ArtifactAccessError, _verified_artifact_from_row

        if plan.approved_plan_artifact_id is None:
            raise ResearchStoreConflict("DeepSearch approved Plan snapshot is missing")
        row = connection.execute(
            "SELECT * FROM artifacts WHERE id = ?",
            (plan.approved_plan_artifact_id,),
        ).fetchone()
        if row is None:
            raise ResearchStoreConflict("DeepSearch approved Plan snapshot is missing")
        try:
            plan_snapshot = _verified_artifact_from_row(row, run)
        except (ArtifactAccessError, TypeError, ValueError) as error:
            raise ResearchStoreConflict("DeepSearch Plan snapshot is invalid") from error
        return self._validate_deepsearch_plan_snapshot(
            run=run,
            requirement=requirement,
            plan=plan,
            plan_snapshot=plan_snapshot,
            expected_plan_hash=expected_plan_hash,
        )

    def save_deepsearch_plan_and_transition(
        self,
        *,
        run_id: str,
        user_id: str,
        expected_requirement_version: int,
        plan: SkillPlan,
        plan_snapshot: Artifact,
        checked_at: datetime | None = None,
    ) -> tuple[SkillPlan, AgentRun, Artifact] | None:
        """Atomically publish the first DeepSearch Plan and its sealed snapshot."""

        from agentmesh.deepsearch.contracts import RequirementVersionV1

        now = checked_at or now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        expired_conflict: DeepSearchRequirementConflict | None = None
        result: tuple[SkillPlan, AgentRun, Artifact] | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            run = self._decode_agent_run_row(run_row)
            if run.user_id != user_id:
                return None
            if (
                run_row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("Run is not a v1 DeepSearch Run")

            requirement_row = connection.execute(
                """SELECT * FROM deepsearch_requirement_versions
                WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
                (run.id,),
            ).fetchone()
            current_requirement_version = (
                int(requirement_row["version"]) if requirement_row is not None else None
            )
            expiration_code = self._deepsearch_expiration_code(run, checked_at=now)
            if expiration_code is not None:
                if run.status is not AgentRunStatus.CANCELLED:
                    self._cancel_agent_run_tree_in_transaction(
                        connection,
                        run,
                        stored_version=run_row["orchestration_version"],
                        reason=expiration_code,
                        error_code=expiration_code,
                        cancelled_at=now,
                    )
                expired_conflict = DeepSearchRequirementConflict(
                    expiration_code,
                    current_requirement_version=current_requirement_version,
                )
            else:
                existing_plan = connection.execute(
                    "SELECT 1 FROM skill_plans WHERE id = ? OR run_id = ? LIMIT 1",
                    (plan.id, run.id),
                ).fetchone()
                if (
                    run.status is not AgentRunStatus.PLANNING
                    or run.plan_id is not None
                    or existing_plan is not None
                ):
                    raise ResearchStoreConflict("DeepSearch initial Plan state is invalid")
                if requirement_row is None or current_requirement_version != expected_requirement_version:
                    raise DeepSearchRequirementConflict(
                        "deepsearch_requirement_version_conflict",
                        current_requirement_version=current_requirement_version,
                    )
                requirement_data = self._decode_deepsearch_requirement_row(requirement_row)
                requirement = RequirementVersionV1.model_validate(requirement_data)
                if requirement.payload.clarification_questions or any(
                    ambiguity.blocking for ambiguity in requirement.payload.ambiguities
                ):
                    raise ResearchStoreConflict("DeepSearch Plan requires a complete Requirement")

                plan, expected_plan_hash = self._validate_deepsearch_plan_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=plan,
                )
                if (
                    plan.version != 1
                    or plan.status is not SkillPlanStatus.WAITING_APPROVAL
                    or plan.approved_plan_artifact_id is not None
                ):
                    raise ResearchStoreConflict("DeepSearch Plan integrity is invalid")
                run = self._charge_deepsearch_plan_snapshot_in_transaction(
                    connection,
                    run=run,
                    plan_snapshot=plan_snapshot,
                    charged_at=now,
                )
                plan_snapshot = self._insert_deepsearch_plan_snapshot_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=plan,
                    plan_snapshot=plan_snapshot,
                    expected_plan_hash=expected_plan_hash,
                )

                plan.updated_at = now
                self._write_skill_plan(connection, plan)
                run.plan_id = plan.id
                run.status = AgentRunStatus.WAITING_PLAN_APPROVAL
                run.deadline_at = None
                run.interaction_expires_at = now + timedelta(hours=24)
                run.updated_at = now
                connection.execute(
                    "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                    (run.model_dump_json(), now.isoformat(), run.id),
                )
                self._append_agent_run_events(
                    connection,
                    run.id,
                    [
                        (
                            "deepsearch_problem_graph_created",
                            {
                                "requirement_version_id": requirement.id,
                                "problem_graph_hash": plan.problem_graph_hash,
                            },
                        ),
                        (
                            "deepsearch_plan_ready",
                            {
                                "plan_id": plan.id,
                                "plan_version": plan.version,
                                "plan_content_hash": expected_plan_hash,
                                "artifact_id": plan_snapshot.id,
                            },
                        ),
                    ],
                )
                result = plan, run, plan_snapshot
        if expired_conflict is not None:
            raise expired_conflict
        return result

    def update_deepsearch_plan_and_snapshot(
        self,
        *,
        run_id: str,
        user_id: str,
        expected_plan_version: int,
        plan: SkillPlan,
        plan_snapshot: Artifact,
        checked_at: datetime | None = None,
    ) -> tuple[SkillPlan, AgentRun, Artifact] | None:
        """Atomically replace a waiting DeepSearch Plan with its next sealed version."""

        from agentmesh.deepsearch.contracts import RequirementVersionV1

        now = checked_at or now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        expired_conflict: DeepSearchRequirementConflict | None = None
        result: tuple[SkillPlan, AgentRun, Artifact] | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            run = self._decode_agent_run_row(run_row)
            if run.user_id != user_id:
                return None
            if (
                run_row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("Run is not a v1 DeepSearch Run")

            requirement_row = connection.execute(
                """SELECT * FROM deepsearch_requirement_versions
                WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
                (run.id,),
            ).fetchone()
            current_requirement_version = (
                int(requirement_row["version"]) if requirement_row is not None else None
            )
            expiration_code = self._deepsearch_expiration_code(run, checked_at=now)
            if expiration_code is not None:
                if run.status is not AgentRunStatus.CANCELLED:
                    self._cancel_agent_run_tree_in_transaction(
                        connection,
                        run,
                        stored_version=run_row["orchestration_version"],
                        reason=expiration_code,
                        error_code=expiration_code,
                        cancelled_at=now,
                    )
                expired_conflict = DeepSearchRequirementConflict(
                    expiration_code,
                    current_requirement_version=current_requirement_version,
                )
            else:
                current_row = connection.execute(
                    "SELECT payload FROM skill_plans WHERE id = ? AND run_id = ?",
                    (run.plan_id, run.id),
                ).fetchone()
                if requirement_row is None or current_row is None:
                    return None
                current = SkillPlan.model_validate_json(current_row["payload"])
                if (
                    run.status is not AgentRunStatus.WAITING_PLAN_APPROVAL
                    or current.status is not SkillPlanStatus.WAITING_APPROVAL
                    or current.version != expected_plan_version
                ):
                    return None
                requirement = RequirementVersionV1.model_validate(
                    self._decode_deepsearch_requirement_row(requirement_row)
                )
                current, _current_hash = self._validate_deepsearch_plan_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=current,
                )
                plan, expected_plan_hash = self._validate_deepsearch_plan_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=plan,
                )
                immutable_fields = (
                    "id",
                    "run_id",
                    "intent",
                    "routing_result",
                    "candidate_skill_ids",
                    "output_contract",
                    "synthesis_output_contract",
                    "capability_gaps",
                    "capability_check",
                    "planning_mode",
                    "requirement_version_id",
                    "requirement_content_hash",
                    "problem_graph",
                    "problem_graph_hash",
                    "created_at",
                )
                selected_skill_ids = [node.skill_id for node in plan.nodes]
                if (
                    any(getattr(plan, field) != getattr(current, field) for field in immutable_fields)
                    or plan.version != expected_plan_version + 1
                    or plan.status is not SkillPlanStatus.WAITING_APPROVAL
                    or plan.approved_plan_artifact_id is not None
                    or len(plan.preferred_order) != len(set(plan.preferred_order))
                    or set(plan.preferred_order) != set(selected_skill_ids)
                    or current.approved_plan_artifact_id is not None
                    or current.degradation is not None
                    or current.completion_check is not None
                    or current.synthesis is not None
                    or plan.degradation is not None
                    or plan.completion_check is not None
                    or plan.synthesis is not None
                ):
                    raise ResearchStoreConflict("DeepSearch Plan edit is invalid")
                run = self._charge_deepsearch_plan_snapshot_in_transaction(
                    connection,
                    run=run,
                    plan_snapshot=plan_snapshot,
                    charged_at=now,
                )
                plan_snapshot = self._insert_deepsearch_plan_snapshot_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=plan,
                    plan_snapshot=plan_snapshot,
                    expected_plan_hash=expected_plan_hash,
                )

                plan.updated_at = now
                self._write_skill_plan(connection, plan)
                run.status = AgentRunStatus.WAITING_PLAN_APPROVAL
                run.deadline_at = None
                run.interaction_expires_at = now + timedelta(hours=24)
                run.updated_at = now
                connection.execute(
                    "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                    (run.model_dump_json(), now.isoformat(), run.id),
                )
                self._append_agent_run_events(
                    connection,
                    run.id,
                    [
                        (
                            "plan_updated",
                            {
                                "plan_id": plan.id,
                                "version": plan.version,
                                "selected_skill_ids": selected_skill_ids,
                                "plan_content_hash": expected_plan_hash,
                                "artifact_id": plan_snapshot.id,
                            },
                        )
                    ],
                )
                result = plan, run, plan_snapshot
        if expired_conflict is not None:
            raise expired_conflict
        return result

    def approve_deepsearch_plan_and_transition(
        self,
        *,
        run_id: str,
        user_id: str,
        expected_plan_version: int,
        plan: SkillPlan,
        plan_snapshot: Artifact,
        checked_at: datetime | None = None,
    ) -> tuple[SkillPlan, AgentRun, Artifact] | None:
        """Atomically freeze the approved DeepSearch Plan version and start its Run."""

        from agentmesh.deepsearch.contracts import RequirementVersionV1
        from agentmesh.deepsearch.planning import deepsearch_frozen_plan

        now = checked_at or now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        expired_conflict: DeepSearchRequirementConflict | None = None
        result: tuple[SkillPlan, AgentRun, Artifact] | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            run = self._decode_agent_run_row(run_row)
            if run.user_id != user_id:
                return None
            if (
                run_row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("Run is not a v1 DeepSearch Run")

            requirement_row = connection.execute(
                """SELECT * FROM deepsearch_requirement_versions
                WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
                (run.id,),
            ).fetchone()
            current_requirement_version = (
                int(requirement_row["version"]) if requirement_row is not None else None
            )
            expiration_code = self._deepsearch_expiration_code(run, checked_at=now)
            if expiration_code is not None:
                if run.status is not AgentRunStatus.CANCELLED:
                    self._cancel_agent_run_tree_in_transaction(
                        connection,
                        run,
                        stored_version=run_row["orchestration_version"],
                        reason=expiration_code,
                        error_code=expiration_code,
                        cancelled_at=now,
                    )
                expired_conflict = DeepSearchRequirementConflict(
                    expiration_code,
                    current_requirement_version=current_requirement_version,
                )
            else:
                current_row = connection.execute(
                    "SELECT payload FROM skill_plans WHERE id = ? AND run_id = ?",
                    (run.plan_id, run.id),
                ).fetchone()
                if requirement_row is None or current_row is None:
                    return None
                current = SkillPlan.model_validate_json(current_row["payload"])
                if (
                    run.status is not AgentRunStatus.WAITING_PLAN_APPROVAL
                    or current.status is not SkillPlanStatus.WAITING_APPROVAL
                    or current.version != expected_plan_version
                ):
                    return None
                requirement = RequirementVersionV1.model_validate(
                    self._decode_deepsearch_requirement_row(requirement_row)
                )
                current, current_hash = self._validate_deepsearch_plan_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=current,
                )
                plan, expected_plan_hash = self._validate_deepsearch_plan_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=plan,
                )
                if (
                    run.orchestration_mode != "execute"
                    or plan.id != current.id
                    or plan.version != expected_plan_version + 1
                    or plan.status is not SkillPlanStatus.APPROVED
                    or plan.created_at != current.created_at
                    or current.approved_plan_artifact_id is not None
                    or plan.approved_plan_artifact_id != plan_snapshot.id
                    or plan.capability_gaps
                    or plan.capability_check != current.capability_check
                    or current.degradation is not None
                    or current.completion_check is not None
                    or current.synthesis is not None
                    or plan.degradation is not None
                    or plan.completion_check is not None
                    or plan.synthesis is not None
                    or current_hash != expected_plan_hash
                    or deepsearch_frozen_plan(plan) != deepsearch_frozen_plan(current)
                ):
                    raise ResearchStoreConflict("DeepSearch Plan approval is invalid")
                run = self._charge_deepsearch_plan_snapshot_in_transaction(
                    connection,
                    run=run,
                    plan_snapshot=plan_snapshot,
                    charged_at=now,
                )
                plan_snapshot = self._insert_deepsearch_plan_snapshot_in_transaction(
                    connection,
                    run=run,
                    requirement=requirement,
                    plan=plan,
                    plan_snapshot=plan_snapshot,
                    expected_plan_hash=expected_plan_hash,
                )

                plan.updated_at = now
                self._write_skill_plan(connection, plan)
                run.status = AgentRunStatus.RUNNING
                run.interaction_expires_at = None
                run.updated_at = now
                connection.execute(
                    "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                    (run.model_dump_json(), now.isoformat(), run.id),
                )
                self._append_agent_run_events(
                    connection,
                    run.id,
                    [
                        (
                            "plan_approved",
                            {
                                "plan_id": plan.id,
                                "version": plan.version,
                                "plan_content_hash": expected_plan_hash,
                                "artifact_id": plan_snapshot.id,
                            },
                        )
                    ],
                )
                result = plan, run, plan_snapshot
        if expired_conflict is not None:
            raise expired_conflict
        return result

    def save_agent_run(self, run: AgentRun) -> AgentRun:
        if run.orchestration_version == "research-v2":
            raise ResearchStoreConflict("research-v2 runs are historical and read-only")
        if run.orchestration_version == "research-v3":
            raise ResearchStoreConflict("research-v3 is retired and read-only")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run.id,),
            ).fetchone()
            if existing is not None:
                current = AgentRun.model_validate_json(existing["payload"])
                if self._is_retired_research_run(current, existing["orchestration_version"]):
                    raise ResearchStoreConflict("research-v2 runs are historical and read-only")
                if current.planning_mode is AgentPlanningMode.DEEPSEARCH:
                    raise ResearchStoreConflict("DeepSearch Runs require dedicated persistence methods")
                self._require_agent_run_creation_identity(current, run)
            if existing is None:
                self._require_new_deepsearch_run_invariants(run)
            if existing is not None and existing["orchestration_version"] != run.orchestration_version:
                raise ResearchStoreConflict("Agent run orchestration_version is immutable")
            connection.execute(
                """
                INSERT INTO agent_runs(id, payload, updated_at, orchestration_version)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (run.id, run.model_dump_json(), run.updated_at.isoformat(), run.orchestration_version),
            )
        return run

    def pause_agent_run_with_inbox(
        self,
        *,
        run_id: str,
        paused_state: dict[str, object],
        inbox_item: InboxItem,
        interruptions: list[dict[str, str]],
    ) -> AgentRun | None:
        """Atomically persist an ordinary Run pause, event, and approval Inbox."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
            if self._is_retired_research_run(run, row["orchestration_version"]):
                return None
            if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
                raise ResearchStoreConflict("DeepSearch Runs require dedicated persistence methods")
            if run.status != AgentRunStatus.RUNNING:
                return None
            now = now_utc()
            run.status = AgentRunStatus.WAITING_APPROVAL
            run.paused_state = paused_state
            run.updated_at = now
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), now.isoformat(), run.id),
            )
            self._append_agent_run_events(
                connection,
                run.id,
                [("approval_requested", {"interruptions": interruptions})],
            )
            connection.execute(
                """
                INSERT INTO records(collection, id, payload)
                VALUES ('inbox_items', ?, ?)
                ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload
                """,
                (inbox_item.id, inbox_item.model_dump_json()),
            )
        return run

    def fail_deepsearch_planning_run(
        self,
        *,
        run_id: str,
        user_id: str,
        error_code: str,
        checked_at: datetime | None = None,
    ) -> AgentRun | None:
        """Atomically fail a pre-Plan DeepSearch Run without using generic writers."""

        if not error_code or len(error_code) > 120:
            raise ValueError("error_code must contain at most 120 characters")
        now = checked_at or now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
            if run.user_id != user_id:
                return None
            if (
                row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("Run is not a v1 DeepSearch Run")
            if (
                run.status not in {
                    AgentRunStatus.PLANNING,
                    AgentRunStatus.WAITING_CLARIFICATION,
                }
                or run.plan_id is not None
                or connection.execute(
                    "SELECT 1 FROM skill_plans WHERE run_id = ? LIMIT 1",
                    (run.id,),
                ).fetchone()
                is not None
            ):
                return None
            run.deepsearch_budget = self._close_deepsearch_budget_for_terminal(run)
            run.status = AgentRunStatus.FAILED
            run.error_code = error_code
            run.output_text = None
            run.paused_state = None
            run.interaction_expires_at = None
            run.updated_at = now
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), now.isoformat(), run.id),
            )
            self._resolve_open_run_inboxes(
                connection,
                run.id,
                reason=error_code,
                resolved_at=now,
            )
            self._append_agent_run_events(
                connection,
                run.id,
                [("run_failed", {"error_code": error_code})],
            )
        return run

    def expire_deepsearch_run_if_needed(
        self,
        run_id: str,
        *,
        user_id: str,
        checked_at: datetime | None = None,
    ) -> AgentRun | None:
        """Atomically apply DeepSearch absolute or interaction expiry, in that order."""
        now = checked_at or now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
            if run.user_id != user_id:
                return None
            if (
                row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or run.planning_mode != AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("Run is not a v1 DeepSearch Run")
            error_code = self._deepsearch_expiration_code(run, checked_at=now)
            if error_code is not None:
                if run.status is AgentRunStatus.CANCELLED:
                    return run
                return self._cancel_agent_run_tree_in_transaction(
                    connection,
                    run,
                    stored_version=row["orchestration_version"],
                    reason=error_code,
                    error_code=error_code,
                    cancelled_at=now,
                )
            return run

    def cancel_agent_run_tree(self, run_id: str, *, user_id: str) -> AgentRun | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
            if run.user_id != user_id:
                return None
            if run.status not in {
                AgentRunStatus.CREATED,
                AgentRunStatus.PLANNING,
                AgentRunStatus.WAITING_CLARIFICATION,
                AgentRunStatus.RUNNING,
                AgentRunStatus.WAITING_PLAN_APPROVAL,
                AgentRunStatus.WAITING_APPROVAL,
            }:
                return run
            return self._cancel_agent_run_tree_in_transaction(
                connection,
                run,
                stored_version=row["orchestration_version"],
                reason="run_cancelled",
            )

    def expire_agent_run_approval(
        self,
        *,
        run_id: str,
        user_id: str,
        inbox_id: str,
        checked_at: datetime | None = None,
    ) -> bool:
        """Cancel an expired approval only if the Run and Inbox are still waiting."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            inbox_row = connection.execute(
                "SELECT payload FROM records WHERE collection = 'inbox_items' AND id = ?",
                (inbox_id,),
            ).fetchone()
            if run_row is None or inbox_row is None:
                return False
            run = AgentRun.model_validate_json(run_row["payload"])
            item = InboxItem.model_validate_json(inbox_row["payload"])
            if (
                self._is_retired_research_run(run, run_row["orchestration_version"])
                or run.user_id != user_id
                or run.status != AgentRunStatus.WAITING_APPROVAL
                or item.status != "open"
                or item.metadata.get("run_id") != run.id
            ):
                return False
            now = checked_at or now_utc()
            expires_at = item.created_at + timedelta(hours=24)
            raw_expiry = (run.paused_state or {}).get("expires_at")
            if isinstance(raw_expiry, str):
                with suppress(ValueError):
                    expires_at = datetime.fromisoformat(raw_expiry)
            if run.deadline_at is not None:
                expires_at = min(expires_at, run.deadline_at)
            if now < expires_at:
                return False
            self._cancel_agent_run_tree_in_transaction(
                connection,
                run,
                stored_version=run_row["orchestration_version"],
                reason="approval_expired",
            )
        return True

    def save_agent_run_with_event(
        self,
        run: AgentRun,
        event_type: str,
        payload: dict[str, object] | None = None,
        *,
        expected_statuses: set[AgentRunStatus] | None = None,
    ) -> AgentRunEvent | None:
        """Commit a Run state transition and its observable event atomically."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run.id,),
            ).fetchone()
            if row is None:
                return None
            current = AgentRun.model_validate_json(row["payload"])
            if self._is_retired_research_run(current, row["orchestration_version"]):
                return None
            if current.planning_mode is AgentPlanningMode.DEEPSEARCH:
                raise ResearchStoreConflict("DeepSearch Runs require dedicated persistence methods")
            if run.orchestration_version != current.orchestration_version:
                raise ResearchStoreConflict("Agent run orchestration_version is immutable")
            self._require_agent_run_creation_identity(current, run)
            if expected_statuses is not None and current.status not in expected_statuses:
                return None
            run.tool_call_count = max(run.tool_call_count, current.tool_call_count)
            run.deadline_at = current.deadline_at
            run.updated_at = now_utc()
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), run.updated_at.isoformat(), run.id),
            )
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_run_events WHERE run_id = ?",
                (run.id,),
            ).fetchone()[0]
            event = AgentRunEvent(run_id=run.id, sequence=sequence, event_type=event_type, payload=payload or {})
            connection.execute(
                "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (run.id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
            )
        return event

    def finish_skill_plan_and_run(
        self,
        *,
        plan: SkillPlan,
        run: AgentRun,
        expected_plan_statuses: set[SkillPlanStatus],
        expected_run_statuses: set[AgentRunStatus],
        events: list[tuple[str, dict[str, object]]],
    ) -> tuple[SkillPlan, AgentRun] | None:
        """Atomically persist a terminal Plan/Run pair and its ordered events."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan.id,)).fetchone()
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run.id,),
            ).fetchone()
            if plan_row is None or run_row is None:
                return None
            current_plan = SkillPlan.model_validate_json(plan_row["payload"])
            current_run = AgentRun.model_validate_json(run_row["payload"])
            if (
                current_run.planning_mode is AgentPlanningMode.DEEPSEARCH
                or current_plan.planning_mode is AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("DeepSearch Runs require dedicated persistence methods")
            if (
                self._is_retired_research_run(current_run, run_row["orchestration_version"])
                or current_plan.run_id != current_run.id
                or current_plan.status not in expected_plan_statuses
                or current_run.status not in expected_run_statuses
            ):
                return None
            if run.orchestration_version != current_run.orchestration_version:
                raise ResearchStoreConflict("Agent run orchestration_version is immutable")
            self._require_agent_run_creation_identity(current_run, run)
            now = now_utc()
            plan.version = current_plan.version
            plan.created_at = current_plan.created_at
            current_nodes = {node.id: node for node in current_plan.nodes}
            terminal_nodes = {
                SkillPlanNodeStatus.COMPLETED,
                SkillPlanNodeStatus.FAILED,
                SkillPlanNodeStatus.SKIPPED,
                SkillPlanNodeStatus.CANCELLED,
            }
            plan.nodes = [
                current_nodes[node.id]
                if node.id in current_nodes
                and (
                    current_nodes[node.id].status in terminal_nodes
                    or current_nodes[node.id].attempt > node.attempt
                )
                else node
                for node in plan.nodes
            ]
            plan.updated_at = now
            run.tool_call_count = max(run.tool_call_count, current_run.tool_call_count)
            run.deadline_at = current_run.deadline_at
            run.created_at = current_run.created_at
            run.updated_at = now
            self._write_skill_plan(connection, plan)
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), now.isoformat(), run.id),
            )
            if run.status in {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
                AgentRunStatus.FAILED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.CANCELLED,
            }:
                self._resolve_open_run_inboxes(
                    connection,
                    run.id,
                    reason=run.error_code or run.status.value,
                    resolved_at=now,
                )
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM agent_run_events WHERE run_id = ?",
                (run.id,),
            ).fetchone()[0]
            for event_type, payload in events:
                sequence += 1
                event = AgentRunEvent(run_id=run.id, sequence=sequence, event_type=event_type, payload=payload)
                connection.execute(
                    "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (run.id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
                )
        return plan, run

    def consume_agent_run_tool_call(self, run_id: str, *, limit: int = 24) -> int | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
            if self._is_retired_research_run(run, row["orchestration_version"]):
                return None
            if run.status != AgentRunStatus.RUNNING or run.tool_call_count >= limit:
                return None
            run.tool_call_count += 1
            run.updated_at = now_utc()
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), run.updated_at.isoformat(), run.id),
            )
        return run.tool_call_count

    @staticmethod
    def _replay_agent_run_claim(connection: sqlite3.Connection, run: AgentRun) -> AgentRun | None:
        if not run.client_turn_id:
            return None
        receipt = connection.execute(
            "SELECT run_id FROM agent_run_receipts WHERE user_id = ? AND client_turn_id = ?",
            (run.user_id, run.client_turn_id),
        ).fetchone()
        if receipt is None:
            return None
        row = connection.execute(
            "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
            (receipt["run_id"],),
        ).fetchone()
        if row is None:
            raise RuntimeError("Agent run receipt points to a missing run")
        existing = SQLiteStore._decode_agent_run_row(row)
        expected_hash = agent_run_create_request_hash_for_run(run)
        if expected_hash is None:
            raise RuntimeError("Agent run creation receipt is missing its request identity")
        if (
            existing.workspace_id != run.workspace_id
            or existing.project_id != run.project_id
            or not agent_run_create_request_matches(
                existing,
                create_request_hash=expected_hash,
                user_id=run.user_id,
                client_turn_id=run.client_turn_id,
                thread_id=run.thread_id,
                content=run.input_text,
                skill_id=run.skill_id,
                skill_name=run.skill_name,
                orchestration_mode=run.requested_orchestration_mode,
                planning_mode=run.planning_mode,
                retry_of_run_id=run.retry_of_run_id,
                planning_contract_version=run.planning_contract_version,
                execution_contract_version=run.execution_contract_version,
            )
        ):
            raise RuntimeError("client_turn_id was already used for another Agent run")
        return existing

    def _require_agent_run_thread_available(
        self,
        connection: sqlite3.Connection,
        run: AgentRun,
    ) -> None:
        active_rows = connection.execute(
            """
            SELECT payload, orchestration_version FROM agent_runs
            WHERE json_extract(payload, '$.user_id') = ?
              AND json_extract(payload, '$.thread_id') = ?
              AND json_extract(payload, '$.status') IN (?, ?, ?, ?, ?, ?)
            """,
            (
                run.user_id,
                run.thread_id,
                AgentRunStatus.CREATED.value,
                AgentRunStatus.PLANNING.value,
                AgentRunStatus.WAITING_CLARIFICATION.value,
                AgentRunStatus.RUNNING.value,
                AgentRunStatus.WAITING_PLAN_APPROVAL.value,
                AgentRunStatus.WAITING_APPROVAL.value,
            ),
        ).fetchall()
        checked_at = now_utc()
        for active_row in active_rows:
            active = AgentRun.model_validate_json(active_row["payload"])
            if self._is_retired_research_run(active, active_row["orchestration_version"]):
                continue
            if (
                active_row["orchestration_version"] == "v1"
                and active.orchestration_version == "v1"
                and active.planning_mode == AgentPlanningMode.DEEPSEARCH
            ):
                expiration_code = self._deepsearch_expiration_code(active, checked_at=checked_at)
                if expiration_code is not None:
                    self._cancel_agent_run_tree_in_transaction(
                        connection,
                        active,
                        stored_version=active_row["orchestration_version"],
                        reason=expiration_code,
                        error_code=expiration_code,
                        cancelled_at=checked_at,
                    )
                    continue
                raise RuntimeError("Another Agent run is already active for this thread")
            if (
                active.status == AgentRunStatus.WAITING_PLAN_APPROVAL
                and active.deadline_at is not None
                and checked_at >= active.deadline_at
            ):
                self._cancel_agent_run_tree_in_transaction(
                    connection,
                    active,
                    stored_version=active_row["orchestration_version"],
                    reason="plan_approval_expired",
                )
                continue
            if self._waiting_approval_expired(connection, active, checked_at=checked_at):
                self._cancel_agent_run_tree_in_transaction(
                    connection,
                    active,
                    stored_version=active_row["orchestration_version"],
                    reason="approval_expired",
                )
                continue
            raise RuntimeError("Another Agent run is already active for this thread")

    @staticmethod
    def _insert_agent_run_claim(connection: sqlite3.Connection, run: AgentRun) -> None:
        if run.orchestration_version == "research-v2":
            raise ResearchStoreConflict("research-v2 writer is retired")
        if run.orchestration_version == "research-v3":
            raise ResearchStoreConflict("research-v3 writer is retired")
        connection.execute(
            "INSERT INTO agent_runs(id, payload, updated_at, orchestration_version) VALUES (?, ?, ?, ?)",
            (run.id, run.model_dump_json(), run.updated_at.isoformat(), run.orchestration_version),
        )
        if run.client_turn_id:
            connection.execute(
                "INSERT INTO agent_run_receipts(user_id, client_turn_id, run_id) VALUES (?, ?, ?)",
                (run.user_id, run.client_turn_id, run.id),
            )

    @staticmethod
    def _require_deepsearch_run_claim_invariants(run: AgentRun) -> None:
        if run.planning_mode is not AgentPlanningMode.DEEPSEARCH:
            return
        if (
            run.created_at.tzinfo is None
            or run.created_at.utcoffset() is None
            or run.absolute_expires_at != run.created_at + timedelta(days=7)
            or run.deadline_at is not None
            or run.deepsearch_budget is None
        ):
            raise ResearchStoreConflict("DeepSearch Run persistence invariants are invalid")

    @staticmethod
    def _require_planning_contract_mode(run: AgentRun) -> None:
        contract = run.planning_contract_version
        if contract is not None and contract.planning_mode is not run.planning_mode:
            raise ResearchStoreConflict(
                "Agent Run planning contract is incompatible with planning mode"
            )

    @classmethod
    def _require_new_deepsearch_run_invariants(cls, run: AgentRun) -> None:
        cls._require_planning_contract_mode(run)
        cls._require_deepsearch_run_claim_invariants(run)
        if (
            run.planning_mode is AgentPlanningMode.DEEPSEARCH
            and (
                run.status is not AgentRunStatus.PLANNING
                or run.plan_id is not None
                or run.interaction_expires_at is not None
                or run.paused_state is not None
                or run.output_text is not None
                or run.error_code is not None
                or run.tool_call_count != 0
                or run.requested_orchestration_mode is not SkillOrchestrationRequestMode.AUTO
                or run.orchestration_version != "v1"
                or run.orchestration_mode != "execute"
                or run.deepsearch_budget != DeepSearchBudgetV1()
            )
        ):
            raise ResearchStoreConflict("DeepSearch Run persistence invariants are invalid")

    def claim_new_agent_run(self, run: AgentRun) -> tuple[AgentRun, bool]:
        if run.orchestration_version == "research-v2":
            raise ResearchStoreConflict("research-v2 writer is retired")
        if run.orchestration_version == "research-v3":
            raise ResearchStoreConflict("research-v3 writer is retired")
        self._require_new_deepsearch_run_invariants(run)
        if not run.client_turn_id:
            return self.save_agent_run(run), True
        expected_hash = agent_run_create_request_hash_for_run(run)
        if expected_hash is None:
            raise RuntimeError("Agent run creation request identity is incomplete")
        if run.create_request_hash is not None and run.create_request_hash != expected_hash:
            raise RuntimeError("Agent run create_request_hash does not match its request identity")
        run = run.model_copy(update={"create_request_hash": expected_hash})
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._replay_agent_run_claim(connection, run)
            if existing is not None:
                return existing, False
            self._require_agent_run_thread_available(connection, run)
            self._insert_agent_run_claim(connection, run)
        return run, True

    def get_agent_run_by_client_turn(self, user_id: str, client_turn_id: str) -> AgentRun | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ar.payload, ar.orchestration_version
                FROM agent_run_receipts receipt
                JOIN agent_runs ar ON ar.id = receipt.run_id
                WHERE receipt.user_id = ? AND receipt.client_turn_id = ?
                """,
                (user_id, client_turn_id),
            ).fetchone()
        return self._decode_agent_run_row(row) if row is not None else None

    def claim_agent_run_for_resume(
        self,
        run_id: str,
        user_id: str,
        *,
        inbox_id: str | None = None,
        call_ids: set[str] | None = None,
    ) -> AgentRun | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
            if self._is_retired_research_run(run, row["orchestration_version"]):
                return None
            if run.user_id != user_id or run.status != AgentRunStatus.WAITING_APPROVAL or run.paused_state is None:
                return None
            if inbox_id is not None:
                inbox_row = connection.execute(
                    "SELECT payload FROM records WHERE collection = 'inbox_items' AND id = ?",
                    (inbox_id,),
                ).fetchone()
                if inbox_row is None:
                    return None
                inbox_item = InboxItem.model_validate_json(inbox_row["payload"])
                if inbox_item.status != "open" or inbox_item.metadata.get("run_id") != run.id:
                    return None
                expires_at = inbox_item.created_at + timedelta(hours=24)
                raw_expiry = run.paused_state.get("expires_at")
                if isinstance(raw_expiry, str):
                    with suppress(ValueError):
                        expires_at = datetime.fromisoformat(raw_expiry)
                if run.deadline_at is not None:
                    expires_at = min(expires_at, run.deadline_at)
                if now_utc() >= expires_at:
                    self._cancel_agent_run_tree_in_transaction(
                        connection,
                        run,
                        stored_version=row["orchestration_version"],
                        reason="approval_expired",
                    )
                    return None
                if call_ids is not None:
                    try:
                        interruptions = json.loads(inbox_item.metadata.get("interruptions", "[]"))
                    except (TypeError, ValueError):
                        return None
                    pending_call_ids = {
                        str(interruption.get("call_id", ""))
                        for interruption in interruptions
                        if isinstance(interruption, dict)
                    }
                    if not call_ids or not call_ids.issubset(pending_call_ids):
                        return None
            if run.paused_state.get("kind") == "skill_plan_node":
                plan_id = run.paused_state.get("plan_id")
                node_id = run.paused_state.get("node_id")
                if not isinstance(plan_id, str) or not isinstance(node_id, str):
                    return None
                plan_row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan_id,)).fetchone()
                node_row = connection.execute(
                    "SELECT payload FROM skill_plan_nodes WHERE plan_id = ? AND id = ?",
                    (plan_id, node_id),
                ).fetchone()
                if plan_row is None or node_row is None:
                    return None
                plan = SkillPlan.model_validate_json(plan_row["payload"])
                node = SkillPlanNode.model_validate_json(node_row["payload"])
                if (
                    plan.run_id != run.id
                    or plan.status != SkillPlanStatus.RUNNING
                    or node.status != SkillPlanNodeStatus.WAITING_TOOL_APPROVAL
                ):
                    return None
                node.status = SkillPlanNodeStatus.RUNNING
                plan.nodes = [node if item.id == node.id else item for item in plan.nodes]
                plan.updated_at = now_utc()
                self._write_skill_plan(connection, plan)
            run.status = AgentRunStatus.RUNNING
            if run.planning_mode is AgentPlanningMode.DEEPSEARCH:
                run.interaction_expires_at = None
            run.updated_at = now_utc()
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), run.updated_at.isoformat(), run.id),
            )
        return run

    @classmethod
    def _reconcile_runtime_tool_calls_in_transaction(
        cls,
        connection: sqlite3.Connection,
        run: AgentRun,
        *,
        recorded_at: datetime,
    ) -> bool:
        claims, outcomes = cls._runtime_tool_call_history_in_transaction(connection, run.id)
        terminal_ids = {outcome.call_id for outcome in outcomes}
        events: list[tuple[str, dict[str, object]]] = []
        for claim in claims:
            if claim.call_id in terminal_ids:
                continue
            is_read = claim.side_effect == "read"
            outcome = RuntimeToolCallOutcomeV1(
                call_id=claim.call_id,
                run_id=claim.run_id,
                outcome="abandoned" if is_read else "outcome_unknown",
                error_code="process_restarted" if is_read else "external_outcome_unknown",
                recorded_at=recorded_at,
            )
            events.append(
                (
                    "tool_call_abandoned" if is_read else "tool_call_outcome_unknown",
                    outcome.model_dump(mode="json"),
                )
            )
        cls._append_agent_run_events(connection, run.id, events)
        return any(claim.side_effect != "read" for claim in claims)

    def reconcile_orphaned_agent_runs(self) -> int:
        reconciled = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id, payload, orchestration_version FROM agent_runs"
            ).fetchall()
            checked_at = now_utc()
            for row in rows:
                run = AgentRun.model_validate_json(row["payload"])
                if self._is_retired_research_run(run, row["orchestration_version"]):
                    continue
                has_non_read_tool_claim = self._reconcile_runtime_tool_calls_in_transaction(
                    connection,
                    run,
                    recorded_at=checked_at,
                )
                if run.planning_mode == AgentPlanningMode.DEEPSEARCH:
                    continue
                if run.status == AgentRunStatus.WAITING_PLAN_APPROVAL:
                    if run.deadline_at is not None and checked_at >= run.deadline_at:
                        self._cancel_agent_run_tree_in_transaction(
                            connection,
                            run,
                            stored_version=row["orchestration_version"],
                            reason="plan_approval_expired",
                        )
                        reconciled += 1
                    continue
                if run.status == AgentRunStatus.WAITING_APPROVAL:
                    if self._waiting_approval_expired(connection, run, checked_at=checked_at):
                        self._cancel_agent_run_tree_in_transaction(
                            connection,
                            run,
                            stored_version=row["orchestration_version"],
                            reason="approval_expired",
                        )
                        reconciled += 1
                    continue
                if run.status not in {
                    AgentRunStatus.CREATED,
                    AgentRunStatus.PLANNING,
                    AgentRunStatus.RUNNING,
                }:
                    continue
                plan_row = connection.execute(
                    "SELECT payload FROM skill_plans WHERE run_id = ?",
                    (run.id,),
                ).fetchone()
                partial = False
                unknown_write = False
                if plan_row is not None:
                    plan = SkillPlan.model_validate_json(plan_row["payload"])
                    tool_claims, tool_outcomes = self._runtime_tool_call_history_in_transaction(
                        connection,
                        run.id,
                    )
                    terminal_by_call = {
                        outcome.call_id: outcome for outcome in tool_outcomes
                    }
                    unknown_node_ids = {
                        claim.node_id
                        for claim in tool_claims
                        if claim.node_id is not None
                        and claim.side_effect != "read"
                        and (
                            claim.call_id not in terminal_by_call
                            or terminal_by_call[claim.call_id].outcome != "settled"
                        )
                    }
                    for node in plan.nodes:
                        if node.status is SkillPlanNodeStatus.RUNNING:
                            node_unknown = node.id in unknown_node_ids
                            node.status = SkillPlanNodeStatus.FAILED
                            node.error_code = (
                                "external_outcome_unknown"
                                if node_unknown
                                else "process_restarted"
                            )
                            node.completed_at = now_utc()
                            unknown_write = unknown_write or node_unknown
                        elif node.status in {
                            SkillPlanNodeStatus.PENDING,
                            SkillPlanNodeStatus.READY,
                            SkillPlanNodeStatus.WAITING_TOOL_APPROVAL,
                        }:
                            node.status = SkillPlanNodeStatus.CANCELLED
                            node.completed_at = now_utc()
                    if plan.candidate_snapshot is not None:
                        from agentmesh.skill_runtime.universal_plan import has_valid_partial_delivery

                        result_rows = connection.execute(
                            """
                            SELECT payload FROM skill_node_results
                            WHERE plan_id = ? ORDER BY created_at, node_id, attempt
                            """,
                            (plan.id,),
                        ).fetchall()
                        partial = has_valid_partial_delivery(
                            plan=plan,
                            results=[
                                SkillNodeResult.model_validate_json(result_row["payload"])
                                for result_row in result_rows
                            ],
                        )
                    plan.status = SkillPlanStatus.PARTIAL if partial else SkillPlanStatus.FAILED
                    plan.updated_at = now_utc()
                    self._write_skill_plan(connection, plan)
                run.status = AgentRunStatus.PARTIAL if partial else AgentRunStatus.FAILED
                run.error_code = (
                    "external_outcome_unknown"
                    if unknown_write or (plan_row is None and has_non_read_tool_claim)
                    else "process_restarted"
                )
                run.updated_at = now_utc()
                connection.execute(
                    "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                    (run.model_dump_json(), run.updated_at.isoformat(), run.id),
                )
                sequence = connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_run_events WHERE run_id = ?",
                    (run.id,),
                ).fetchone()[0]
                event = AgentRunEvent(
                    run_id=run.id,
                    sequence=sequence,
                    event_type="run_partially_completed" if partial else "run_failed",
                    payload={"error_code": run.error_code or "process_restarted"},
                )
                connection.execute(
                    "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (run.id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
                )
                reconciled += 1
        return reconciled

    @classmethod
    def _universal_quiesce_inventory_in_transaction(
        cls,
        connection: sqlite3.Connection,
    ) -> OrchestrationQuiesceInventoryV1:
        terminal_statuses = {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.PARTIAL,
            AgentRunStatus.FAILED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.CANCELLED,
        }
        rows = connection.execute(
            "SELECT id, payload, orchestration_version FROM agent_runs ORDER BY id"
        ).fetchall()
        run_ids: set[str] = set()
        plan_ids: set[str] = set()
        unresolved_call_ids: set[str] = set()
        unsafe_no_plan_run_ids: set[str] = set()
        anomalies: set[str] = set()
        target_contracts = {
            AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
            AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2,
        }
        for row in rows:
            run = cls._decode_agent_run_row(row)
            claims, outcomes = cls._runtime_tool_call_history_in_transaction(connection, run.id)
            terminal_call_ids = {outcome.call_id for outcome in outcomes}
            unresolved = [claim for claim in claims if claim.call_id not in terminal_call_ids]
            unresolved_call_ids.update(claim.call_id for claim in unresolved)
            active = run.status not in terminal_statuses
            plan_row = connection.execute(
                "SELECT id, payload FROM skill_plans WHERE run_id = ?",
                (run.id,),
            ).fetchone()
            plan = SkillPlan.model_validate_json(plan_row["payload"]) if plan_row is not None else None
            if active and (run.planning_contract_version in target_contracts or claims):
                run_ids.add(run.id)
                if plan is not None:
                    plan_ids.add(plan.id)
                elif any(claim.side_effect != "read" for claim in claims):
                    unsafe_no_plan_run_ids.add(run.id)
            if (
                run.planning_contract_version in target_contracts
                and plan is not None
                and (
                    run.plan_id != plan.id
                    or plan.run_id != run.id
                    or plan.candidate_snapshot is None
                )
            ):
                anomalies.add(f"planning_contract_shape_mismatch:{run.id}")
            if plan is not None and plan.candidate_snapshot is not None and run.planning_contract_version not in target_contracts:
                anomalies.add(f"candidate_snapshot_marker_mismatch:{run.id}")
        orphan_rows = connection.execute(
            """
            SELECT sp.id FROM skill_plans AS sp
            LEFT JOIN agent_runs AS ar ON ar.id = sp.run_id
            WHERE ar.id IS NULL
            ORDER BY sp.id
            """
        ).fetchall()
        anomalies.update(f"orphan_plan:{row['id']}" for row in orphan_rows)
        body = {
            "schema_version": "orchestration-quiesce-inventory-v1",
            "run_ids": sorted(run_ids),
            "plan_ids": sorted(plan_ids),
            "unresolved_tool_call_ids": sorted(unresolved_call_ids),
            "unsafe_no_plan_run_ids": sorted(unsafe_no_plan_run_ids),
            "anomaly_codes": sorted(anomalies),
        }
        return OrchestrationQuiesceInventoryV1(
            **body,
            operation_checksum=canonical_json_sha256(body),
        )

    def universal_quiesce_inventory(self) -> OrchestrationQuiesceInventoryV1:
        with self._read_connect() as connection:
            return self._universal_quiesce_inventory_in_transaction(connection)

    def apply_universal_quiesce(
        self,
        *,
        expected_operation_checksum: str,
    ) -> OrchestrationQuiesceInventoryV1:
        with self._connect() as connection:
            connection.execute("BEGIN EXCLUSIVE")
            inventory = self._universal_quiesce_inventory_in_transaction(connection)
            if inventory.operation_checksum != expected_operation_checksum:
                raise RuntimeToolCallConflict("quiesce_operation_checksum_changed")
            if inventory.anomaly_codes:
                raise RuntimeToolCallConflict("quiesce_inventory_invalid")
            checked_at = now_utc()
            all_claims, all_outcomes = self._all_runtime_tool_call_history(connection)
            terminal_call_ids = {outcome.call_id for outcome in all_outcomes}
            unresolved_by_run: dict[str, list[RuntimeToolCallClaimV1]] = {}
            for claim in all_claims:
                if claim.call_id not in terminal_call_ids:
                    unresolved_by_run.setdefault(claim.run_id, []).append(claim)
            for unresolved_run_id, claims in sorted(unresolved_by_run.items()):
                claim_events: list[tuple[str, dict[str, object]]] = []
                for claim in claims:
                    is_read = claim.side_effect == "read"
                    outcome = RuntimeToolCallOutcomeV1(
                        call_id=claim.call_id,
                        run_id=claim.run_id,
                        outcome="abandoned" if is_read else "outcome_unknown",
                        error_code="process_restarted" if is_read else "external_outcome_unknown",
                        recorded_at=checked_at,
                    )
                    claim_events.append(
                        (
                            "tool_call_abandoned" if is_read else "tool_call_outcome_unknown",
                            outcome.model_dump(mode="json"),
                        )
                    )
                self._append_agent_run_events(connection, unresolved_run_id, claim_events)
            for run_id in inventory.run_ids:
                row = connection.execute(
                    "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeToolCallConflict("quiesce_run_disappeared")
                run = self._decode_agent_run_row(row)
                run_claims, _run_outcomes = self._runtime_tool_call_history_in_transaction(
                    connection,
                    run.id,
                )
                has_non_read_claim = any(claim.side_effect != "read" for claim in run_claims)
                plan_row = connection.execute(
                    "SELECT payload FROM skill_plans WHERE run_id = ?",
                    (run.id,),
                ).fetchone()
                events: list[tuple[str, dict[str, object]]] = []
                has_unknown_write = has_non_read_claim
                partial = False
                if plan_row is not None:
                    plan = SkillPlan.model_validate_json(plan_row["payload"])
                    terminal_nodes = {
                        SkillPlanNodeStatus.COMPLETED,
                        SkillPlanNodeStatus.FAILED,
                        SkillPlanNodeStatus.SKIPPED,
                        SkillPlanNodeStatus.CANCELLED,
                    }
                    for node in plan.nodes:
                        if node.status in terminal_nodes:
                            continue
                        if (
                            node.status is SkillPlanNodeStatus.RUNNING
                            and node.side_effect
                            in {SkillSideEffect.LOCAL_WRITE, SkillSideEffect.EXTERNAL_WRITE}
                        ):
                            node.status = SkillPlanNodeStatus.FAILED
                            node.error_code = "external_outcome_unknown"
                            has_unknown_write = True
                        else:
                            node.status = SkillPlanNodeStatus.CANCELLED
                            node.error_code = "orchestration_quiesced"
                        node.completed_at = checked_at
                        events.append(
                            (
                                "node_failed"
                                if node.error_code == "external_outcome_unknown"
                                else "node_cancelled",
                                {
                                    "plan_id": plan.id,
                                    "node_id": node.id,
                                    "error_code": node.error_code,
                                },
                            )
                        )
                    if plan.candidate_snapshot is not None:
                        from agentmesh.skill_runtime.universal_plan import has_valid_partial_delivery

                        result_rows = connection.execute(
                            """
                            SELECT payload FROM skill_node_results
                            WHERE plan_id = ? ORDER BY created_at, node_id, attempt
                            """,
                            (plan.id,),
                        ).fetchall()
                        partial = has_valid_partial_delivery(
                            plan=plan,
                            results=[
                                SkillNodeResult.model_validate_json(result_row["payload"])
                                for result_row in result_rows
                            ],
                        )
                    plan.status = SkillPlanStatus.PARTIAL if partial else SkillPlanStatus.FAILED
                    plan.updated_at = checked_at
                    self._write_skill_plan(connection, plan)
                run.status = (
                    AgentRunStatus.PARTIAL
                    if partial
                    else AgentRunStatus.FAILED
                    if plan_row is not None or run_claims
                    else AgentRunStatus.CANCELLED
                )
                run.error_code = (
                    "external_outcome_unknown"
                    if has_unknown_write
                    else "process_restarted"
                    if plan_row is not None or run_claims
                    else "orchestration_quiesced"
                )
                run.updated_at = checked_at
                connection.execute(
                    "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                    (run.model_dump_json(), checked_at.isoformat(), run.id),
                )
                events.append(
                    (
                        "run_partially_completed"
                        if run.status is AgentRunStatus.PARTIAL
                        else "run_failed"
                        if run.status is AgentRunStatus.FAILED
                        else "run_cancelled",
                        {"error_code": run.error_code},
                    )
                )
                self._append_agent_run_events(connection, run.id, events)
            return inventory

    def list_active_agent_runs_for_planning_contracts(
        self,
        contracts: set[AgentPlanningContractVersion],
    ) -> list[AgentRun]:
        """Enumerate non-terminal Runs by their immutable JSON contract marker."""

        if not contracts:
            return []
        contract_values = sorted(contract.value for contract in contracts)
        terminal_values = sorted(
            status.value
            for status in {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
                AgentRunStatus.FAILED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.CANCELLED,
            }
        )
        contract_placeholders = ", ".join("?" for _ in contract_values)
        terminal_placeholders = ", ".join("?" for _ in terminal_values)
        with self._read_connect() as connection:
            rows = connection.execute(
                f"""SELECT id, payload, orchestration_version
                FROM agent_runs
                WHERE json_extract(payload, '$.planning_contract_version')
                      IN ({contract_placeholders})
                  AND json_extract(payload, '$.status') NOT IN ({terminal_placeholders})
                ORDER BY updated_at, id""",
                (*contract_values, *terminal_values),
            ).fetchall()
        runs: list[AgentRun] = []
        for row in rows:
            try:
                run = self._decode_agent_run_row(row)
            except (TypeError, ValueError) as error:
                raise ResearchStoreConflict("Planning-contract Run is invalid") from error
            if run.id != row["id"] or run.planning_contract_version not in contracts:
                raise ResearchStoreConflict("Planning-contract Run identity is invalid")
            runs.append(run)
        return runs

    def list_recoverable_deepsearch_runs(self) -> list[AgentRun]:
        """Return persisted non-terminal v1 DeepSearch runs for the coordinator."""

        terminal_statuses = {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.PARTIAL,
            AgentRunStatus.FAILED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.CANCELLED,
        }
        with self._read_connect() as connection:
            rows = connection.execute(
                """SELECT id, payload, orchestration_version
                FROM agent_runs
                WHERE orchestration_version = 'v1'
                ORDER BY updated_at, id"""
            ).fetchall()
        runs: list[AgentRun] = []
        for row in rows:
            try:
                run = AgentRun.model_validate_json(row["payload"])
            except (TypeError, ValueError):
                continue
            if (
                run.id == row["id"]
                and run.orchestration_version == row["orchestration_version"]
                and run.planning_mode is AgentPlanningMode.DEEPSEARCH
                and run.status not in terminal_statuses
            ):
                runs.append(run)
        return runs

    def prepare_deepsearch_execution_recovery(
        self,
        *,
        run_id: str,
        checked_at: datetime | None = None,
    ) -> tuple[SkillPlan, AgentRun] | None:
        """Normalize abandoned node claims before re-entering the one DAG executor."""

        now = checked_at or now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT id, payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            try:
                run = AgentRun.model_validate_json(run_row["payload"])
            except (TypeError, ValueError) as error:
                raise ResearchStoreConflict("DeepSearch recovery Run is invalid") from error
            if (
                run.id != run_row["id"]
                or run_row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("DeepSearch recovery Run identity is invalid")
            if run.status is not AgentRunStatus.RUNNING or run.plan_id is None:
                return None

            plan_row = connection.execute(
                "SELECT id, run_id, version, status, payload FROM skill_plans WHERE id = ?",
                (run.plan_id,),
            ).fetchone()
            if plan_row is None:
                raise ResearchStoreConflict("DeepSearch recovery Plan is missing")
            try:
                plan = SkillPlan.model_validate_json(plan_row["payload"])
            except (TypeError, ValueError) as error:
                raise ResearchStoreConflict("DeepSearch recovery Plan is invalid") from error
            if (
                plan.id != plan_row["id"]
                or plan.run_id != plan_row["run_id"]
                or plan.version != plan_row["version"]
                or plan.status.value != plan_row["status"]
                or plan.run_id != run.id
                or plan.planning_mode is not AgentPlanningMode.DEEPSEARCH
                or plan.status not in {SkillPlanStatus.APPROVED, SkillPlanStatus.RUNNING}
            ):
                raise ResearchStoreConflict("DeepSearch recovery Plan identity is invalid")

            from agentmesh.deepsearch.contracts import (
                ProblemGraphV1,
                RequirementVersionV1,
                validate_problem_graph_against_requirement,
            )
            from agentmesh.deepsearch.planning import plan_content_hash

            requirement_row = connection.execute(
                """SELECT * FROM deepsearch_requirement_versions
                WHERE run_id = ? ORDER BY version DESC LIMIT 1""",
                (run.id,),
            ).fetchone()
            if requirement_row is None:
                raise ResearchStoreConflict("DeepSearch recovery Requirement is missing")
            try:
                requirement = RequirementVersionV1.model_validate(
                    self._decode_deepsearch_requirement_row(requirement_row)
                )
                graph = ProblemGraphV1.model_validate(plan.problem_graph)
                validate_problem_graph_against_requirement(
                    graph=graph,
                    requirement=requirement,
                )
                expected_plan_hash = plan_content_hash(plan)
            except (TypeError, ValueError) as error:
                raise ResearchStoreConflict(
                    "DeepSearch recovery Plan lineage is invalid"
                ) from error
            if (
                plan.requirement_version_id != requirement.id
                or plan.requirement_content_hash != requirement.content_hash
                or plan.problem_graph_hash != graph.content_hash
                or plan.plan_content_hash != expected_plan_hash
            ):
                raise ResearchStoreConflict(
                    "DeepSearch recovery Plan lineage is invalid"
                )
            self._load_deepsearch_plan_snapshot_in_transaction(
                connection,
                run=run,
                requirement=requirement,
                plan=plan,
                expected_plan_hash=expected_plan_hash,
            )

            node_rows = connection.execute(
                """SELECT id, status, payload FROM skill_plan_nodes
                WHERE plan_id = ? ORDER BY id""",
                (plan.id,),
            ).fetchall()
            try:
                persisted_nodes = [
                    SkillPlanNode.model_validate_json(row["payload"])
                    for row in node_rows
                ]
            except (TypeError, ValueError) as error:
                raise ResearchStoreConflict(
                    "DeepSearch recovery node projection is invalid"
                ) from error
            expected_nodes = sorted(plan.nodes, key=lambda item: item.id)
            if (
                len(persisted_nodes) != len(expected_nodes)
                or any(
                    node.id != row["id"]
                    or node.status.value != row["status"]
                    or node != expected
                    for node, row, expected in zip(
                        persisted_nodes,
                        node_rows,
                        expected_nodes,
                        strict=True,
                    )
                )
            ):
                raise ResearchStoreConflict(
                    "DeepSearch recovery node projection is invalid"
                )
            if plan.status is SkillPlanStatus.APPROVED:
                if (
                    plan.finalization_stage is not DeepSearchFinalizationStage.NONE
                    or any(node.status is not SkillPlanNodeStatus.PENDING for node in plan.nodes)
                    or connection.execute(
                        "SELECT 1 FROM skill_node_results WHERE plan_id = ? LIMIT 1",
                        (plan.id,),
                    ).fetchone()
                    is not None
                ):
                    raise ResearchStoreConflict("DeepSearch approved Plan recovery state is invalid")
                return plan, run

            if any(
                node.status is SkillPlanNodeStatus.WAITING_TOOL_APPROVAL
                for node in plan.nodes
            ):
                raise ResearchStoreConflict("DeepSearch running Plan has an orphaned approval")
            terminal_node_statuses = {
                SkillPlanNodeStatus.COMPLETED,
                SkillPlanNodeStatus.FAILED,
                SkillPlanNodeStatus.SKIPPED,
                SkillPlanNodeStatus.CANCELLED,
            }
            if (
                run.paused_state is not None
                or run.interaction_expires_at is not None
                or run.output_text is not None
                or plan.finalization_stage
                is DeepSearchFinalizationStage.TERMINAL_COMMITTED
                or (
                    plan.finalization_stage is not DeepSearchFinalizationStage.NONE
                    and any(
                        node.status not in terminal_node_statuses
                        for node in plan.nodes
                    )
                )
            ):
                raise ResearchStoreConflict(
                    "DeepSearch running Plan recovery state is invalid"
                )

            events: list[tuple[str, dict[str, object]]] = []
            updated_nodes: list[SkillPlanNode] = []
            changed = False
            for node in plan.nodes:
                if node.status is SkillPlanNodeStatus.RUNNING:
                    changed = True
                    node = node.model_copy(
                        update={
                            "status": SkillPlanNodeStatus.FAILED,
                            "error_code": "external_outcome_unknown",
                            "completed_at": now,
                        }
                    )
                    events.append(
                        (
                            "node_failed",
                            {
                                "plan_id": plan.id,
                                "node_id": node.id,
                                "attempt": node.attempt,
                                "error_code": "external_outcome_unknown",
                            },
                        )
                    )
                updated_nodes.append(node)

            if changed:
                plan = SkillPlan.model_validate(
                    {
                        **plan.model_dump(mode="python"),
                        "nodes": updated_nodes,
                        "updated_at": now,
                    }
                )
                self._write_skill_plan(connection, plan)
                self._append_agent_run_events(connection, run.id, events)
            return plan, run

    def fail_deepsearch_recovery_state(
        self,
        *,
        run_id: str,
        error_code: str = "deepsearch_recovery_state_invalid",
        checked_at: datetime | None = None,
    ) -> AgentRun | None:
        """Fail an invalid active recovery state without using generic Run writers."""

        if not error_code or len(error_code) > 120:
            raise ValueError("error_code must contain at most 120 characters")
        now = checked_at or now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("checked_at must include a timezone")
        terminal_statuses = {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.PARTIAL,
            AgentRunStatus.FAILED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.CANCELLED,
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT id, payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            try:
                run = AgentRun.model_validate_json(run_row["payload"])
            except (TypeError, ValueError) as error:
                raise ResearchStoreConflict("DeepSearch recovery Run is invalid") from error
            if (
                run.id != run_row["id"]
                or run_row["orchestration_version"] != "v1"
                or run.orchestration_version != "v1"
                or run.planning_mode is not AgentPlanningMode.DEEPSEARCH
            ):
                raise ResearchStoreConflict("DeepSearch recovery Run identity is invalid")
            if run.status in terminal_statuses:
                return run

            events: list[tuple[str, dict[str, object]]] = []
            plan_row = connection.execute(
                "SELECT id, run_id, payload FROM skill_plans WHERE run_id = ?",
                (run.id,),
            ).fetchone()
            if plan_row is not None:
                try:
                    plan = SkillPlan.model_validate_json(plan_row["payload"])
                except (TypeError, ValueError):
                    plan = None
                from agentmesh.artifacts import ArtifactAccessError, V1VerifiedArtifactStore

                staging_rows = connection.execute(
                    """SELECT payload FROM artifacts
                    WHERE run_id = ?
                      AND artifact_type = 'deepsearch_report'
                      AND verification_state = ?""",
                    (
                        run.id,
                        ArtifactVerificationState.STAGING.value,
                    ),
                ).fetchall()
                artifact_store = V1VerifiedArtifactStore(self)
                for row in staging_rows:
                    try:
                        staging_report = Artifact.model_validate_json(row["payload"])
                        artifact_store.fail_report(
                            staging_report.model_copy(
                                update={
                                    "verification_state": ArtifactVerificationState.FAILED,
                                    "updated_at": now,
                                }
                            ),
                            connection=connection,
                        )
                    except (ArtifactAccessError, TypeError, ValueError):
                        # The Run must still converge to failed if an already
                        # corrupt STAGING row cannot be materialized safely.
                        connection.execute(
                            """UPDATE artifacts SET verification_state = ?, updated_at = ?
                            WHERE run_id = ? AND artifact_type = 'deepsearch_report'
                              AND verification_state = ?""",
                            (
                                ArtifactVerificationState.FAILED.value,
                                now.isoformat(),
                                run.id,
                                ArtifactVerificationState.STAGING.value,
                            ),
                        )
                plan_is_safe_to_rewrite = (
                    plan is not None
                    and plan.id == plan_row["id"]
                    and plan.run_id == plan_row["run_id"]
                    and plan.run_id == run.id
                    and plan.planning_mode is AgentPlanningMode.DEEPSEARCH
                )
                if not plan_is_safe_to_rewrite:
                    connection.execute(
                        "UPDATE skill_plans SET status = ?, updated_at = ? WHERE run_id = ?",
                        (SkillPlanStatus.FAILED.value, now.isoformat(), run.id),
                    )
                    connection.execute(
                        """UPDATE skill_plan_nodes SET status = ?, updated_at = ?
                        WHERE plan_id = ? AND status NOT IN (?, ?, ?, ?)""",
                        (
                            SkillPlanNodeStatus.CANCELLED.value,
                            now.isoformat(),
                            plan_row["id"],
                            SkillPlanNodeStatus.COMPLETED.value,
                            SkillPlanNodeStatus.FAILED.value,
                            SkillPlanNodeStatus.SKIPPED.value,
                            SkillPlanNodeStatus.CANCELLED.value,
                        ),
                    )
                else:
                    assert plan is not None
                    previous_stage = plan.finalization_stage
                    updated_nodes: list[SkillPlanNode] = []
                    terminal_node_statuses = {
                        SkillPlanNodeStatus.COMPLETED,
                        SkillPlanNodeStatus.FAILED,
                        SkillPlanNodeStatus.SKIPPED,
                        SkillPlanNodeStatus.CANCELLED,
                    }
                    for node in plan.nodes:
                        if node.status in terminal_node_statuses:
                            updated_nodes.append(node)
                            continue
                        updated_nodes.append(
                            node.model_copy(
                                update={
                                    "status": SkillPlanNodeStatus.CANCELLED,
                                    "completed_at": now,
                                }
                            )
                        )
                        events.append(
                            (
                                "node_cancelled",
                                {
                                    "plan_id": plan.id,
                                    "node_id": node.id,
                                    "reason": error_code,
                                },
                            )
                        )
                    terminal_hash = canonical_json_sha256(
                        {
                            "kind": "deepsearch-recovery-failure-v1",
                            "run_id": run.id,
                            "plan_id": plan.id,
                            "plan_version": plan.version,
                            "finalization_stage": previous_stage.value,
                            "finalization_version": plan.finalization_version,
                            "error_code": error_code,
                        }
                    )
                    plan = SkillPlan.model_validate(
                        {
                            **plan.model_dump(mode="python"),
                            "status": SkillPlanStatus.FAILED,
                            "nodes": updated_nodes,
                            "report_artifact_id": None,
                            "report_content_hash": None,
                            "finalization_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED,
                            "finalization_version": plan.finalization_version + 1,
                            "finalization_input_hashes": {
                                **plan.finalization_input_hashes,
                                DeepSearchFinalizationStage.TERMINAL_COMMITTED: terminal_hash,
                            },
                            "updated_at": now,
                        }
                    )
                    self._write_skill_plan(connection, plan)
                    events.append(
                        (
                            "deepsearch_finalization_stage_changed",
                            {
                                "plan_id": plan.id,
                                "from_stage": previous_stage.value,
                                "to_stage": DeepSearchFinalizationStage.TERMINAL_COMMITTED.value,
                                "finalization_version": plan.finalization_version,
                                "input_hash": terminal_hash,
                            },
                        )
                    )

            closed_budget = self._close_deepsearch_budget_for_terminal(run)
            run = AgentRun.model_validate(
                {
                    **run.model_dump(mode="python"),
                    "deepsearch_budget": closed_budget,
                    "status": AgentRunStatus.FAILED,
                    "paused_state": None,
                    "interaction_expires_at": None,
                    "output_text": None,
                    "error_code": error_code,
                    "updated_at": now,
                }
            )
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), now.isoformat(), run.id),
            )
            self._resolve_open_run_inboxes(
                connection,
                run.id,
                reason=error_code,
                resolved_at=now,
            )
            self._append_agent_run_events(
                connection,
                run.id,
                [*events, ("run_failed", {"error_code": error_code})],
            )
            return run

    def get_agent_run(self, run_id: str) -> AgentRun | None:
        with self._read_connect() as connection:
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return self._decode_agent_run_row(row) if row is not None else None

    def get_latest_research_run_for_thread(self, thread_id: str, user_id: str) -> AgentRun | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload, orchestration_version FROM agent_runs
                WHERE (
                    orchestration_version = 'research-v2'
                    OR (
                        orchestration_version = 'v1'
                        AND json_extract(payload, '$.planning_mode') = 'deepsearch'
                    )
                )
                  AND json_extract(payload, '$.thread_id') = ?
                  AND json_extract(payload, '$.user_id') = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (thread_id, user_id),
            ).fetchone()
        return self._decode_agent_run_row(row) if row is not None else None

    def user_can_execute_agent_run(
        self,
        user_id: str,
        run_id: str,
        *,
        allowed_statuses: set[AgentRunStatus] | None = None,
    ) -> bool:
        user = self.get_user(user_id)
        run = self.get_agent_run(run_id)
        if user is None or user.status != "active" or run is None or run.user_id != user.id:
            return False
        if allowed_statuses is not None and run.status not in allowed_statuses:
            return False
        project = self.get_project(run.project_id)
        thread = self.get_chat_thread(run.thread_id)
        thread_matches = thread is None or (
            thread.user_id == user.id
            and thread.workspace_id == run.workspace_id
            and thread.project_id == run.project_id
        )
        return bool(
            project is not None
            and project.workspace_id == user.workspace_id == run.workspace_id
            and self.user_can_access_project(user.id, project.id)
            and thread_matches
        )

    def list_agent_runs(self, user_id: str | None = None) -> list[AgentRun]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs ORDER BY updated_at"
            ).fetchall()
        runs = [self._decode_agent_run_row(row) for row in rows]
        return [run for run in runs if user_id is None or run.user_id == user_id]

    def append_agent_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> AgentRunEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run_row is not None:
                run = AgentRun.model_validate_json(run_row["payload"])
                if self._is_retired_research_run(run, run_row["orchestration_version"]):
                    raise ResearchStoreConflict("research-v2 runs are historical and read-only")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            event = AgentRunEvent(run_id=run_id, sequence=sequence, event_type=event_type, payload=payload or {})
            connection.execute(
                "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
            )
        return event

    def claim_runtime_tool_call(self, claim: RuntimeToolCallClaimV1) -> bool:
        """Persist a Tool-call claim once; False means an identical claim already exists."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (claim.run_id,),
            ).fetchone()
            if row is None:
                raise RuntimeToolCallConflict("tool_call_run_missing")
            run = self._decode_agent_run_row(row)
            if run.status not in {AgentRunStatus.PLANNING, AgentRunStatus.RUNNING}:
                raise RuntimeToolCallConflict("tool_call_run_not_running")
            events = connection.execute(
                """
                SELECT payload FROM agent_run_events
                WHERE json_extract(payload, '$.payload.call_id') = ?
                ORDER BY run_id, sequence
                """,
                (claim.call_id,),
            ).fetchall()
            if events:
                parsed = [AgentRunEvent.model_validate_json(event["payload"]) for event in events]
                claimed = [event for event in parsed if event.event_type == "tool_call_claimed"]
                if len(claimed) != 1:
                    raise RuntimeToolCallConflict("tool_call_history_invalid")
                existing = RuntimeToolCallClaimV1.model_validate(claimed[0].payload)
                if existing.model_dump(exclude={"claimed_at"}) != claim.model_dump(
                    exclude={"claimed_at"}
                ):
                    raise RuntimeToolCallConflict("tool_call_identity_conflict")
                return False
            self._append_agent_run_events(
                connection,
                claim.run_id,
                [("tool_call_claimed", claim.model_dump(mode="json"))],
            )
            return True

    def finish_runtime_tool_call(self, outcome: RuntimeToolCallOutcomeV1) -> bool:
        """Append one immutable settlement/abandonment/unknown outcome."""
        event_type = {
            "settled": "tool_call_settled",
            "abandoned": "tool_call_abandoned",
            "outcome_unknown": "tool_call_outcome_unknown",
        }[outcome.outcome]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT payload FROM agent_run_events
                WHERE json_extract(payload, '$.payload.call_id') = ?
                ORDER BY run_id, sequence
                """,
                (outcome.call_id,),
            ).fetchall()
            events = [AgentRunEvent.model_validate_json(row["payload"]) for row in rows]
            claims = [event for event in events if event.event_type == "tool_call_claimed"]
            if len(claims) != 1:
                raise RuntimeToolCallConflict("tool_call_claim_missing")
            claim = RuntimeToolCallClaimV1.model_validate(claims[0].payload)
            if claim.run_id != outcome.run_id:
                raise RuntimeToolCallConflict("tool_call_identity_conflict")
            terminal = [
                event
                for event in events
                if event.event_type
                in {"tool_call_settled", "tool_call_abandoned", "tool_call_outcome_unknown"}
            ]
            if terminal:
                if len(terminal) != 1:
                    raise RuntimeToolCallConflict("tool_call_history_invalid")
                existing = RuntimeToolCallOutcomeV1.model_validate(terminal[0].payload)
                if existing.model_dump(exclude={"recorded_at"}) != outcome.model_dump(
                    exclude={"recorded_at"}
                ):
                    raise RuntimeToolCallConflict("tool_call_outcome_conflict")
                return False
            self._append_agent_run_events(
                connection,
                outcome.run_id,
                [(event_type, outcome.model_dump(mode="json"))],
            )
            return True

    @staticmethod
    def _runtime_tool_call_history_in_transaction(
        connection: sqlite3.Connection,
        run_id: str,
    ) -> tuple[list[RuntimeToolCallClaimV1], list[RuntimeToolCallOutcomeV1]]:
        rows = connection.execute(
            """
            SELECT payload FROM agent_run_events
            WHERE run_id = ?
              AND json_extract(payload, '$.event_type') IN (
                  'tool_call_claimed', 'tool_call_settled',
                  'tool_call_abandoned', 'tool_call_outcome_unknown'
              )
            ORDER BY sequence
            """,
            (run_id,),
        ).fetchall()
        claims: list[RuntimeToolCallClaimV1] = []
        outcomes: list[RuntimeToolCallOutcomeV1] = []
        for row in rows:
            event = AgentRunEvent.model_validate_json(row["payload"])
            if event.event_type == "tool_call_claimed":
                claims.append(RuntimeToolCallClaimV1.model_validate(event.payload))
            else:
                outcomes.append(RuntimeToolCallOutcomeV1.model_validate(event.payload))
        if len({claim.call_id for claim in claims}) != len(claims):
            raise RuntimeToolCallConflict("tool_call_history_invalid")
        if len({outcome.call_id for outcome in outcomes}) != len(outcomes):
            raise RuntimeToolCallConflict("tool_call_history_invalid")
        if not {outcome.call_id for outcome in outcomes}.issubset(
            {claim.call_id for claim in claims}
        ):
            raise RuntimeToolCallConflict("tool_call_history_invalid")
        return claims, outcomes

    def list_runtime_tool_call_history(
        self,
        run_id: str | None = None,
    ) -> tuple[list[RuntimeToolCallClaimV1], list[RuntimeToolCallOutcomeV1]]:
        with self._read_connect() as connection:
            return self._runtime_tool_call_history_in_transaction(connection, run_id) if run_id else self._all_runtime_tool_call_history(connection)

    @classmethod
    def _all_runtime_tool_call_history(
        cls,
        connection: sqlite3.Connection,
    ) -> tuple[list[RuntimeToolCallClaimV1], list[RuntimeToolCallOutcomeV1]]:
        run_rows = connection.execute(
            """
            SELECT DISTINCT run_id FROM agent_run_events
            WHERE json_extract(payload, '$.event_type') IN (
                'tool_call_claimed', 'tool_call_settled',
                'tool_call_abandoned', 'tool_call_outcome_unknown'
            )
            ORDER BY run_id
            """
        ).fetchall()
        claims: list[RuntimeToolCallClaimV1] = []
        outcomes: list[RuntimeToolCallOutcomeV1] = []
        for row in run_rows:
            run_claims, run_outcomes = cls._runtime_tool_call_history_in_transaction(
                connection,
                str(row["run_id"]),
            )
            claims.extend(run_claims)
            outcomes.extend(run_outcomes)
        return claims, outcomes

    def runtime_tool_run_has_unknown_non_read(self, run_id: str) -> bool:
        claims, outcomes = self.list_runtime_tool_call_history(run_id)
        terminal = {outcome.call_id: outcome for outcome in outcomes}
        return any(
            claim.side_effect != "read"
            and (
                claim.call_id not in terminal
                or terminal[claim.call_id].outcome != "settled"
            )
            for claim in claims
        )

    def runtime_tool_node_has_unknown_non_read(
        self,
        run_id: str,
        node_id: str,
    ) -> bool:
        claims, outcomes = self.list_runtime_tool_call_history(run_id)
        terminal = {outcome.call_id: outcome for outcome in outcomes}
        return any(
            claim.node_id == node_id
            and claim.side_effect != "read"
            and (
                claim.call_id not in terminal
                or terminal[claim.call_id].outcome != "settled"
            )
            for claim in claims
        )

    def runtime_tool_retry_block_reason(self, run_id: str) -> str | None:
        run = self.get_agent_run(run_id)
        if run is not None and run.error_code == "external_outcome_unknown":
            return "external_outcome_unknown"
        plan = self.get_skill_plan_for_run(run_id)
        if plan is not None and any(
            node.error_code == "external_outcome_unknown" for node in plan.nodes
        ):
            return "external_outcome_unknown"
        claims, outcomes = self.list_runtime_tool_call_history(run_id)
        terminal = {outcome.call_id: outcome for outcome in outcomes}
        if any(
            claim.side_effect != "read"
            and (
                claim.call_id not in terminal
                or terminal[claim.call_id].outcome != "settled"
            )
            for claim in claims
        ):
            return "external_outcome_unknown"
        if any(claim.side_effect != "read" for claim in claims):
            return "completed_write_requires_new_request"
        return None

    def runtime_tool_retry_blocked(self, run_id: str) -> bool:
        return self.runtime_tool_retry_block_reason(run_id) is not None

    def list_unresolved_runtime_tool_calls(self) -> list[RuntimeToolCallClaimV1]:
        claims, outcomes = self.list_runtime_tool_call_history()
        terminal_ids = {outcome.call_id for outcome in outcomes}
        return [claim for claim in claims if claim.call_id not in terminal_ids]

    def read_agent_run_event_page(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[list[AgentRunEvent], AgentRun | None]:
        if not 1 <= limit <= 100:
            raise ValueError("agent_run_event_page_limit_invalid")
        with self._read_connect() as connection:
            connection.execute("BEGIN")
            event_rows = connection.execute(
                """
                SELECT payload FROM agent_run_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (run_id, after_sequence, limit),
            ).fetchall()
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        events = [AgentRunEvent.model_validate_json(row["payload"]) for row in event_rows]
        run = self._decode_agent_run_row(run_row) if run_row is not None else None
        return events, run

    def list_agent_run_events(self, run_id: str, after_sequence: int = 0) -> list[AgentRunEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM agent_run_events WHERE run_id = ? AND sequence > ? ORDER BY sequence",
                (run_id, after_sequence),
            ).fetchall()
        return [AgentRunEvent.model_validate_json(row["payload"]) for row in rows]

    def prune_agent_stream_events(self, retention_days: int = 30) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=max(1, retention_days))).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM agent_run_events
                WHERE created_at < ?
                  AND json_extract(payload, '$.event_type') = 'sdk_stream_event'
                  AND run_id IN (
                      SELECT id FROM agent_runs
                      WHERE json_extract(payload, '$.status') IN (?, ?, ?, ?, ?)
                        AND orchestration_version NOT IN ('research-v2', 'research-v3')
                        AND json_extract(payload, '$.orchestration_version')
                            NOT IN ('research-v2', 'research-v3')
                  )
                """,
                (
                    cutoff,
                    AgentRunStatus.COMPLETED.value,
                    AgentRunStatus.PARTIAL.value,
                    AgentRunStatus.FAILED.value,
                    AgentRunStatus.REJECTED.value,
                    AgentRunStatus.CANCELLED.value,
                ),
            )
        return max(0, cursor.rowcount)

    @staticmethod
    def _research_agent_run_status(workflow: ResearchWorkflow) -> AgentRunStatus | None:
        if workflow.phase == ResearchPhase.TERMINAL:
            return None
        if workflow.active_gate == ResearchGate.PLAN_CONFIRMATION:
            return AgentRunStatus.WAITING_PLAN_APPROVAL
        if workflow.active_gate == ResearchGate.TOOL_APPROVAL:
            return AgentRunStatus.WAITING_APPROVAL
        if workflow.phase in {ResearchPhase.REQUIREMENT, ResearchPhase.PLANNING}:
            return AgentRunStatus.PLANNING
        return AgentRunStatus.RUNNING


    @staticmethod
    def _validate_research_workflow_links(
        connection: sqlite3.Connection,
        workflow: ResearchWorkflow,
    ) -> None:
        requirement_id = workflow.active_requirement_version_id
        plan_id = workflow.active_plan_version_id
        attempt_id = workflow.active_attempt_id
        if requirement_id is not None:
            row = connection.execute(
                "SELECT run_id FROM research_requirement_versions WHERE id = ?",
                (requirement_id,),
            ).fetchone()
            if row is None or row["run_id"] != workflow.run_id:
                raise ResearchStoreConflict("active requirement does not belong to the workflow run")
        if plan_id is not None:
            row = connection.execute(
                "SELECT run_id, requirement_version_id FROM research_plan_versions WHERE id = ?",
                (plan_id,),
            ).fetchone()
            if (
                row is None
                or row["run_id"] != workflow.run_id
                or requirement_id is None
                or row["requirement_version_id"] != requirement_id
            ):
                raise ResearchStoreConflict("active plan does not match the active requirement")
        if attempt_id is not None:
            row = connection.execute(
                "SELECT run_id, plan_version_id FROM research_attempts WHERE id = ?",
                (attempt_id,),
            ).fetchone()
            if (
                row is None
                or row["run_id"] != workflow.run_id
                or plan_id is None
                or row["plan_version_id"] != plan_id
            ):
                raise ResearchStoreConflict("active attempt does not match the active plan")

    @staticmethod
    def _research_requirement_projection_matches(row: sqlite3.Row, requirement: RequirementVersion) -> bool:
        try:
            content_hash_matches = canonical_sha256(requirement.payload) == requirement.content_hash
        except (TypeError, ValueError):
            return False
        return bool(
            row["id"] == requirement.id
            and row["run_id"] == requirement.run_id
            and row["version"] == requirement.version
            and row["content_hash"] == requirement.content_hash
            and row["created_at"] == requirement.created_at.isoformat()
            and content_hash_matches
        )

    def _load_research_workflow_context(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        owner: ResearchOwnerScope | None = None,
    ) -> WorkflowContext | None:
        from agentmesh.research_orchestration.v2_history import WorkflowContext

        run_row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if run_row is None:
            return None
        try:
            run = AgentRun.model_validate_json(run_row["payload"])
        except (RecursionError, TypeError, ValueError):
            raise ResearchStoreConflict("research Agent run failed integrity verification") from None
        if owner is not None and (
            run.user_id != owner.user_id
            or run.workspace_id != owner.workspace_id
            or run.project_id != owner.project_id
        ):
            return None
        if not self._research_run_projection_matches(run_row, run) or run.orchestration_version != "research-v2":
            raise ResearchStoreConflict("research Agent run failed integrity verification")
        if run.client_turn_id is not None:
            receipt_row = connection.execute(
                "SELECT user_id, client_turn_id, run_id FROM agent_run_receipts WHERE run_id = ?",
                (run.id,),
            ).fetchone()
            if (
                receipt_row is None
                or receipt_row["user_id"] != run.user_id
                or receipt_row["client_turn_id"] != run.client_turn_id
                or receipt_row["run_id"] != run.id
            ):
                raise ResearchStoreConflict("research Agent run receipt failed integrity verification")

        workflow_row = connection.execute(
            "SELECT * FROM research_workflows WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if workflow_row is None:
            return None
        try:
            workflow = ResearchWorkflow.model_validate_json(workflow_row["payload"])
        except (RecursionError, TypeError, ValueError):
            raise ResearchStoreConflict("research workflow failed integrity verification") from None
        if not self._research_workflow_projection_matches(workflow_row, workflow):
            raise ResearchStoreConflict("research workflow failed integrity verification")

        requirement_rows = connection.execute(
            "SELECT * FROM research_requirement_versions WHERE run_id = ? ORDER BY version",
            (run_id,),
        ).fetchall()
        requirements: list[RequirementVersion] = []
        for row in requirement_rows:
            try:
                requirement = RequirementVersion.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research requirement failed integrity verification") from None
            if not self._research_requirement_projection_matches(row, requirement):
                raise ResearchStoreConflict("research requirement failed integrity verification")
            requirements.append(requirement)

        plan_rows = connection.execute(
            "SELECT * FROM research_plan_versions WHERE run_id = ? ORDER BY version",
            (run_id,),
        ).fetchall()
        plans: list[ExecutionPlanVersion] = []
        for row in plan_rows:
            try:
                plan = ExecutionPlanVersion.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research plan failed integrity verification") from None
            if not self._research_plan_projection_matches(row, plan):
                raise ResearchStoreConflict("research plan failed integrity verification")
            plans.append(plan)

        attempt_rows = connection.execute(
            "SELECT * FROM research_attempts WHERE run_id = ? ORDER BY attempt_number",
            (run_id,),
        ).fetchall()
        attempts: list[ExecutionAttempt] = []
        for row in attempt_rows:
            try:
                attempt = ExecutionAttempt.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research attempt failed integrity verification") from None
            if not self._research_attempt_projection_matches(row, attempt):
                raise ResearchStoreConflict("research attempt failed integrity verification")
            attempts.append(attempt)

        active_requirement = next(
            (item for item in requirements if item.id == workflow.active_requirement_version_id),
            None,
        )
        active_plan = next((item for item in plans if item.id == workflow.active_plan_version_id), None)
        active_attempt = next((item for item in attempts if item.id == workflow.active_attempt_id), None)
        if workflow.active_requirement_version_id is not None and active_requirement is None:
            raise ResearchStoreConflict("research workflow active requirement failed integrity verification")
        if workflow.active_plan_version_id is not None and active_plan is None:
            raise ResearchStoreConflict("research workflow active plan failed integrity verification")
        if workflow.active_attempt_id is not None and active_attempt is None:
            raise ResearchStoreConflict("research workflow active attempt failed integrity verification")
        self._validate_research_workflow_links(connection, workflow)

        step_rows = (
            connection.execute(
                "SELECT * FROM research_steps WHERE attempt_id = ? ORDER BY step_number",
                (active_attempt.id,),
            ).fetchall()
            if active_attempt is not None
            else []
        )
        steps: list[ResearchStep] = []
        for row in step_rows:
            try:
                step = ResearchStep.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research step failed integrity verification") from None
            if not self._research_step_projection_matches(row, step):
                raise ResearchStoreConflict("research step failed integrity verification")
            steps.append(step)

        active_tool_approval: InboxItem | None = None
        if workflow.active_gate == ResearchGate.TOOL_APPROVAL:
            if active_attempt is None:
                raise ResearchStoreConflict("research Tool approval gate has no active attempt")
            inbox_rows = connection.execute(
                """
                SELECT payload FROM records
                WHERE collection = 'inbox_items'
                  AND json_extract(payload, '$.item_type') = 'research_tool_approval'
                  AND json_extract(payload, '$.status') = 'open'
                  AND json_extract(payload, '$.metadata.run_id') = ?
                  AND json_extract(payload, '$.metadata.attempt_id') = ?
                ORDER BY id
                """,
                (run.id, active_attempt.id),
            ).fetchall()
            if len(inbox_rows) != 1:
                raise ResearchStoreConflict("research Tool approval gate has no unique Inbox item")
            try:
                active_tool_approval = InboxItem.model_validate_json(inbox_rows[0]["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research Tool approval failed integrity verification") from None
            if (
                active_tool_approval.user_id != run.user_id
                or active_tool_approval.workspace_id != run.workspace_id
                or active_tool_approval.project_id != run.project_id
                or active_tool_approval.metadata.get("plan_version_id") != workflow.active_plan_version_id
            ):
                raise ResearchStoreConflict("research Tool approval failed integrity verification")

        active_recovery_invocation: ToolInvocation | None = None
        if workflow.active_gate == ResearchGate.RECOVERY_DECISION:
            if active_attempt is None:
                raise ResearchStoreConflict("research recovery gate has no active attempt")
            invocation_rows = connection.execute(
                """
                SELECT * FROM research_tool_invocations
                WHERE active_attempt_id = ? AND state = ?
                ORDER BY id
                """,
                (active_attempt.id, InvocationState.UNKNOWN.value),
            ).fetchall()
            if len(invocation_rows) != 1:
                raise ResearchStoreConflict("research recovery gate has no unique unknown invocation")
            invocation_row = invocation_rows[0]
            try:
                active_recovery_invocation = ToolInvocation.model_validate_json(invocation_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
            if (
                not self._research_invocation_projection_matches(invocation_row, active_recovery_invocation)
                or active_recovery_invocation.run_id != run.id
                or active_recovery_invocation.plan_version_id != workflow.active_plan_version_id
            ):
                raise ResearchStoreConflict("research recovery invocation failed integrity verification")

        expected_status = self._research_agent_run_status(workflow)
        terminal_statuses = {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.PARTIAL,
            AgentRunStatus.FAILED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.CANCELLED,
        }
        if expected_status is not None and run.status != expected_status:
            raise ResearchStoreConflict("research run and workflow failed integrity verification")
        if expected_status is None and run.status not in terminal_statuses:
            raise ResearchStoreConflict("terminal research workflow failed integrity verification")
        return WorkflowContext(
            run=run,
            workflow=workflow,
            active_requirement=active_requirement,
            active_plan=active_plan,
            active_attempt=active_attempt,
            steps=tuple(steps),
            requirements=tuple(requirements),
            plans=tuple(plans),
            attempt_count=len(attempts),
            active_tool_approval=active_tool_approval,
            active_recovery_invocation=active_recovery_invocation,
        )


    def load_context(
        self,
        run_id: str,
        *,
        owner: ResearchOwnerScope,
    ) -> WorkflowContext | None:
        with self._read_connect() as connection:
            return self._load_research_workflow_context(connection, run_id, owner=owner)

    @staticmethod
    def _research_attempt_projection_matches(row: sqlite3.Row, attempt: ExecutionAttempt) -> bool:
        return bool(
            row["id"] == attempt.id
            and row["run_id"] == attempt.run_id
            and row["plan_version_id"] == attempt.plan_version_id
            and row["attempt_number"] == attempt.attempt_number
            and row["status"] == attempt.status.value
            and row["lease_owner"] == attempt.lease_owner
            and row["lease_token"] == attempt.lease_token
            and row["fencing_epoch"] == attempt.fencing_epoch
            and row["lease_expires_at"]
            == (attempt.lease_expires_at.isoformat() if attempt.lease_expires_at is not None else None)
            and row["created_at"] == attempt.created_at.isoformat()
            and row["updated_at"] == attempt.updated_at.isoformat()
        )

    @staticmethod
    def _research_workflow_projection_matches(row: sqlite3.Row, workflow: ResearchWorkflow) -> bool:
        return bool(
            row["run_id"] == workflow.run_id
            and row["phase"] == workflow.phase.value
            and row["active_gate"] == workflow.active_gate.value
            and row["active_requirement_version_id"] == workflow.active_requirement_version_id
            and row["active_plan_version_id"] == workflow.active_plan_version_id
            and row["active_attempt_id"] == workflow.active_attempt_id
            and row["state_version"] == workflow.state_version
            and row["created_at"] == workflow.created_at.isoformat()
            and row["updated_at"] == workflow.updated_at.isoformat()
        )

    @staticmethod
    def _research_run_projection_matches(row: sqlite3.Row, run: AgentRun) -> bool:
        return bool(
            row["id"] == run.id
            and row["orchestration_version"] == run.orchestration_version
            and row["updated_at"] == run.updated_at.isoformat()
        )

    @staticmethod
    def _research_plan_projection_matches(row: sqlite3.Row, plan: ExecutionPlanVersion) -> bool:
        try:
            content_hash_matches = canonical_sha256(plan.payload) == plan.plan_hash
        except (TypeError, ValueError):
            return False
        return bool(
            row["id"] == plan.id
            and row["run_id"] == plan.run_id
            and row["requirement_version_id"] == plan.requirement_version_id
            and row["version"] == plan.version
            and row["plan_hash"] == plan.plan_hash
            and row["created_at"] == plan.created_at.isoformat()
            and content_hash_matches
        )

    @staticmethod
    def _research_step_projection_matches(row: sqlite3.Row, step: ResearchStep) -> bool:
        return bool(
            row["attempt_id"] == step.attempt_id
            and row["step_number"] == step.step_number
            and row["status"] == step.status.value
            and row["claim_epoch"] == step.claim_epoch
            and row["result_artifact_id"] == step.result_artifact_id
            and row["updated_at"] == step.updated_at.isoformat()
        )

    @staticmethod
    def _research_invocation_projection_matches(row: sqlite3.Row, invocation: ToolInvocation) -> bool:
        try:
            receipt = (
                ToolReceipt.model_validate_json(row["receipt_payload"])
                if row["receipt_payload"] is not None
                else None
            )
        except (RecursionError, TypeError, ValueError):
            return False
        return bool(
            row["id"] == invocation.id
            and row["run_id"] == invocation.run_id
            and row["plan_version_id"] == invocation.plan_version_id
            and row["step_number"] == invocation.step_number
            and row["operation_key"] == invocation.operation_key
            and row["request_hash"] == invocation.resolved_input_hash
            and row["resolved_input_hash"] == invocation.resolved_input_hash
            and row["request_artifact_id"] == invocation.request_artifact_id
            and row["active_attempt_id"] == invocation.active_attempt_id
            and row["state"] == invocation.state.value
            and row["send_count"] == invocation.send_count
            and row["active_send_sequence"] == invocation.active_send_sequence
            and row["sent_fencing_epoch"] == invocation.sent_fencing_epoch
            and receipt == invocation.receipt
            and row["artifact_id"] == invocation.artifact_id
            and row["provider_operation_id"] == invocation.provider_operation_id
            and row["last_sent_at"]
            == (invocation.last_sent_at.isoformat() if invocation.last_sent_at is not None else None)
            and row["acknowledged_at"]
            == (invocation.acknowledged_at.isoformat() if invocation.acknowledged_at is not None else None)
            and row["unknown_at"]
            == (invocation.unknown_at.isoformat() if invocation.unknown_at is not None else None)
            and row["created_at"] == invocation.created_at.isoformat()
            and row["updated_at"] == invocation.updated_at.isoformat()
        )


    def save_artifact(self, artifact: Artifact) -> Artifact:
        if artifact.verification_state is not None:
            raise ResearchStoreConflict("verified artifacts require the insert-only ArtifactStore")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute(
                "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
                (artifact.run_id,),
            ).fetchone()
            if run_row is None:
                raise ResearchStoreConflict("artifact run does not exist")
            try:
                run = AgentRun.model_validate_json(run_row["payload"])
            except (TypeError, ValueError):
                raise ResearchStoreConflict("artifact run failed integrity verification") from None
            if run.orchestration_version != "v1" or run_row["orchestration_version"] != "v1":
                raise ResearchStoreConflict("versioned research artifacts require their version-specific repository")
            if (
                run.user_id != artifact.user_id
                or run.workspace_id != artifact.workspace_id
                or run.project_id != artifact.project_id
            ):
                raise ResearchStoreConflict("artifact owner does not match its run")
            row = connection.execute(
                "SELECT payload, verification_state FROM artifacts WHERE id = ?",
                (artifact.id,),
            ).fetchone()
            if row is not None:
                existing = Artifact.model_validate_json(row["payload"])
                if (
                    row["verification_state"] is not None
                    or existing.verification_state is not None
                    or existing.run_id != artifact.run_id
                    or existing.workspace_id != artifact.workspace_id
                    or existing.project_id != artifact.project_id
                    or existing.user_id != artifact.user_id
                ):
                    raise ResearchStoreConflict("artifact identity is immutable")
            connection.execute(
                """
                INSERT INTO artifacts(
                    id, run_id, payload, created_at, workspace_id, project_id, user_id,
                    artifact_type, content_type, truncated, verification_state, schema_version,
                    content_hash, size_bytes, requirement_version_id, plan_version_id,
                    attempt_id, step_number, purged_at, purged_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    workspace_id = excluded.workspace_id,
                    project_id = excluded.project_id,
                    user_id = excluded.user_id,
                    artifact_type = excluded.artifact_type,
                    content_type = excluded.content_type,
                    truncated = excluded.truncated,
                    verification_state = excluded.verification_state,
                    schema_version = excluded.schema_version,
                    content_hash = excluded.content_hash,
                    size_bytes = excluded.size_bytes,
                    requirement_version_id = excluded.requirement_version_id,
                    plan_version_id = excluded.plan_version_id,
                    attempt_id = excluded.attempt_id,
                    step_number = excluded.step_number,
                    purged_at = excluded.purged_at,
                    purged_by = excluded.purged_by,
                    updated_at = excluded.updated_at
                """,
                (
                    artifact.id,
                    artifact.run_id,
                    artifact.model_dump_json(),
                    artifact.created_at.isoformat(),
                    artifact.workspace_id,
                    artifact.project_id,
                    artifact.user_id,
                    artifact.artifact_type,
                    artifact.content_type,
                    int(artifact.truncated),
                    artifact.verification_state.value if artifact.verification_state is not None else None,
                    artifact.schema_version,
                    artifact.content_hash,
                    artifact.size_bytes,
                    artifact.requirement_version_id,
                    artifact.plan_version_id,
                    artifact.attempt_id,
                    artifact.step_number,
                    artifact.purged_at.isoformat() if artifact.purged_at is not None else None,
                    artifact.purged_by,
                    artifact.updated_at.isoformat() if artifact.updated_at is not None else None,
                ),
            )
        return artifact

    def save_deepsearch_runtime_artifact(
        self,
        *,
        artifact: Artifact,
        budget_invocation_key: str,
        actual_usage: DeepSearchBudgetUsageV1,
    ) -> Artifact:
        """Insert one legacy runtime Artifact and settle its reservation atomically."""

        from agentmesh.artifacts import _row_payload_matches_indexes, _strict_mapping

        allowed_types = {"tool_output", "skill_node_result"}
        try:
            actual = DeepSearchBudgetUsageV1.model_validate(
                actual_usage.model_dump(mode="python")
            )
            canonical_content = canonical_json_bytes(strict_json_loads(artifact.content))
        except (AttributeError, TypeError, ValueError) as error:
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid") from error
        expected_usage = DeepSearchBudgetUsageV1(artifact_bytes=len(canonical_content))
        artifact_identity = {
            "artifact_id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "run_id": artifact.run_id,
        }
        expected_logical_key = f"artifact:{canonical_json_sha256(artifact_identity)}"
        if (
            not isinstance(budget_invocation_key, str)
            or not budget_invocation_key
            or artifact.verification_state is not None
            or artifact.artifact_type not in allowed_types
            or artifact.content_type != "application/json"
            or not artifact.truncated
            or canonical_content.decode("utf-8") != artifact.content
            or len(canonical_content) > 1_048_576
            or actual != expected_usage
        ):
            raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._load_deepsearch_budget_run_in_transaction(
                connection,
                run_id=artifact.run_id,
            )
            if (
                run.user_id != artifact.user_id
                or run.workspace_id != artifact.workspace_id
                or run.project_id != artifact.project_id
            ):
                raise ResearchStoreConflict("artifact owner does not match its run")
            budget = run.deepsearch_budget
            assert budget is not None
            matches = [
                item
                for item in budget.reservations
                if item.invocation_key == budget_invocation_key
            ]
            if len(matches) != 1:
                raise DeepSearchBudgetConflict("deepsearch_budget_reservation_not_found")
            current = matches[0]
            if (
                current.scope != "standard"
                or current.tool_invocation is not None
                or current.logical_operation_key != expected_logical_key
                or current.invocation_key
                != f"{expected_logical_key}:attempt:{current.physical_attempt}"
                or current.resource_maxima != expected_usage
            ):
                raise DeepSearchBudgetConflict("deepsearch_budget_request_invalid")

            row = connection.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (artifact.id,),
            ).fetchone()
            replayed_artifact: Artifact | None = None
            if row is not None:
                try:
                    payload = _strict_mapping(row["payload"])
                    replayed_artifact = Artifact.model_validate(payload)
                except (TypeError, ValueError) as error:
                    raise ResearchStoreConflict("artifact failed integrity verification") from error
                if (
                    replayed_artifact != artifact
                    or row["verification_state"] is not None
                    or not _row_payload_matches_indexes(row, payload)
                ):
                    raise ResearchStoreConflict("artifact identity is immutable")

            if current.status == "settled":
                if replayed_artifact is None or current.actual_usage not in {
                    actual,
                    DeepSearchBudgetUsageV1(),
                }:
                    raise DeepSearchBudgetConflict("deepsearch_budget_settlement_conflict")
                return replayed_artifact

            now = now_utc()
            if not self._deepsearch_budget_status_allowed(
                run,
                scope=current.scope,
                checked_at=now,
            ):
                raise DeepSearchBudgetConflict("deepsearch_budget_state_conflict")

            settled_actual = DeepSearchBudgetUsageV1() if replayed_artifact is not None else actual
            try:
                settled_reservation = DeepSearchBudgetReservationV1(
                    **current.model_dump(mode="python", exclude={"status", "actual_usage"}),
                    status="settled",
                    actual_usage=settled_actual,
                )
                reservations = [
                    settled_reservation if item.invocation_key == budget_invocation_key else item
                    for item in budget.reservations
                ]
                updated_budget = DeepSearchBudgetV1.model_validate(
                    {
                        **budget.model_dump(mode="python"),
                        "version": budget.version + 1,
                        "consumed": self._billed_deepsearch_budget_usage(reservations),
                        "reservations": reservations,
                    }
                )
                self._validate_deepsearch_budget_ledger(updated_budget)
            except (TypeError, ValueError) as error:
                raise DeepSearchBudgetConflict("deepsearch_budget_settlement_invalid") from error

            if replayed_artifact is None:
                connection.execute(
                    """
                    INSERT INTO artifacts(
                        id, run_id, payload, created_at, workspace_id, project_id, user_id,
                        artifact_type, content_type, truncated, verification_state, schema_version,
                        content_hash, size_bytes, requirement_version_id, plan_version_id,
                        attempt_id, step_number, purged_at, purged_by, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.id,
                        artifact.run_id,
                        artifact.model_dump_json(),
                        artifact.created_at.isoformat(),
                        artifact.workspace_id,
                        artifact.project_id,
                        artifact.user_id,
                        artifact.artifact_type,
                        artifact.content_type,
                        int(artifact.truncated),
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    ),
                )
            self._write_deepsearch_budget_run(
                connection,
                run=run,
                budget=updated_budget,
                updated_at=now,
            )
        return artifact if replayed_artifact is None else replayed_artifact

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return Artifact.model_validate_json(row["payload"]) if row is not None else None

    def save_model_definition(self, model: ModelDefinition) -> ModelDefinition:
        self._upsert("model_definitions", model)
        return model

    def save_risk_policy_rule(self, rule: RiskPolicyRule) -> RiskPolicyRule:
        self._upsert("risk_policy_rules", rule)
        return rule

    def save_permission_policy_rule(self, rule: PermissionPolicyRule) -> PermissionPolicyRule:
        self._upsert("permission_policy_rules", rule)
        return rule

    def save_scheduled_agent_task_definition(
        self,
        definition: ScheduledAgentTaskDefinition,
    ) -> ScheduledAgentTaskDefinition:
        self._upsert("scheduled_agent_task_definitions", definition)
        return definition

    def save_agent_tool_grant(self, grant: AgentToolGrant) -> AgentToolGrant:
        self._upsert("agent_tool_grants", grant)
        return grant

    def save_user(self, user: User) -> User:
        self._upsert("users", user)
        return user

    def save_auth_credential(self, credential: AuthCredential) -> AuthCredential:
        self._upsert("auth_credentials", credential)
        return credential

    def save_auth_session(self, session: AuthSession) -> AuthSession:
        self._upsert("auth_sessions", session)
        return session

    def save_team(self, team: Team) -> Team:
        self._upsert("teams", team)
        return team

    def save_team_membership(self, membership: TeamMembership) -> TeamMembership:
        self._upsert("team_memberships", membership)
        return membership


    def add_inbox_item(self, item: InboxItem) -> InboxItem:
        self._upsert("inbox_items", item)
        return item

    def save_inbox_item(self, item: InboxItem) -> InboxItem:
        self._upsert("inbox_items", item)
        return item

    def add_memory_item(self, item: MemoryItem) -> MemoryItem:
        self._upsert("memory_items", item)
        return item

    def save_memory_item(self, item: MemoryItem) -> MemoryItem:
        self._upsert("memory_items", item)
        return item

    def add_user_memory_item(self, item: UserMemoryItem) -> UserMemoryItem:
        self._upsert("user_memory_items", item)
        return item

    def add_daily_summary_if_absent(self, item: UserMemoryItem) -> tuple[UserMemoryItem, bool]:
        if (
            item.layer != MemoryLayer.SHORT_TERM
            or item.source_kind != "daily_summary"
            or item.memory_type != "daily_summary"
            or item.project_id is None
        ):
            raise ValueError("daily summary identity is invalid")

        work: VectorWork | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT payload
                FROM records
                WHERE collection = 'user_memory_items'
                  AND json_extract(payload, '$.user_id') = ?
                  AND json_extract(payload, '$.project_id') = ?
                  AND json_extract(payload, '$.memory_date') = ?
                  AND json_extract(payload, '$.memory_type') = 'daily_summary'
                  AND json_extract(payload, '$.status') = 'active'
                LIMIT 1
                """,
                (item.user_id, item.project_id, item.memory_date.isoformat()),
            ).fetchone()
            if row is not None:
                return UserMemoryItem.model_validate_json(row["payload"]), False

            connection.execute(
                "INSERT INTO records(collection, id, payload) VALUES (?, ?, ?)",
                ("user_memory_items", item.id, item.model_dump_json()),
            )
            self._sync_fts(connection, "user_memory_items", item)
            doc = _extract_fts_doc("user_memory_items", item)
            if doc is not None:
                work = self.vector_index.prepare(
                    connection,
                    "user_memory_items",
                    item.id,
                    f"{doc.title} {doc.body}".strip(),
                )

        if work is not None:
            from agentmesh.embedding import EMBEDDING_ENABLED

            if EMBEDDING_ENABLED:
                self.vector_index.process(work)
        return item, True

    def save_user_memory_item(self, item: UserMemoryItem) -> UserMemoryItem:
        self._upsert("user_memory_items", item)
        return item

    def add_source(self, source: Source) -> Source:
        existing = self.get_source(source.id)
        if existing is not None:
            identity = (
                "title",
                "source_type",
                "reference",
                "workspace_id",
                "project_id",
                "user_id",
                "run_id",
                "skill_id",
            )
            if any(getattr(existing, field) != getattr(source, field) for field in identity):
                raise ValueError("source_identity_conflict")
            return existing
        self._upsert("sources", source)
        return source

    def add_document(self, document: DocumentRecord) -> DocumentRecord:
        self._upsert("documents", document)
        return document

    def save_document(self, document: DocumentRecord) -> DocumentRecord:
        self._upsert("documents", document)
        return document

    def confirm_brief(
        self,
        item_id: str,
        owner_user_id: str,
        text: str,
        expected_document_version: int,
    ) -> BriefConfirmationResult:
        """Atomically edit and confirm one owned Brief draft."""
        vector_work: list[VectorWork] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            inbox_row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("inbox_items", item_id),
            ).fetchone()
            if inbox_row is None:
                raise BriefConfirmationError("not_found", "Inbox item not found")
            item = InboxItem.model_validate_json(inbox_row["payload"])
            if item.user_id != owner_user_id:
                raise BriefConfirmationError("forbidden", "Only the Inbox owner can confirm this Brief")

            document_id = item.metadata.get("document_id")
            if (
                item.item_type != "decision_review"
                or item.metadata.get("artifact_type") != "brief_draft"
                or not document_id
            ):
                raise BriefConfirmationError("invalid", "Inbox item is not a Brief draft")
            if item.status != "open" or item.metadata.get("confirmed_memory_id"):
                raise BriefConfirmationError("conflict", "Brief draft is no longer open")

            document_row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("documents", document_id),
            ).fetchone()
            if document_row is None:
                raise BriefConfirmationError("not_found", "Brief draft document not found")
            document = DocumentRecord.model_validate_json(document_row["payload"])
            if (
                document.uploaded_by != owner_user_id
                or document.workspace_id != item.workspace_id
                or document.project_id != item.project_id
            ):
                raise BriefConfirmationError("forbidden", "Brief draft document is not owned by the Inbox owner")
            if document.version != expected_document_version:
                raise BriefConfirmationError("conflict", "Brief draft document version is stale")

            now = now_utc()
            document.text = text
            document.version += 1
            document.expected_chunks = 0
            document.completed_chunks = 0
            document.updated_at = now
            document.metadata["edited_by"] = owner_user_id
            document.metadata["edited_at"] = now.isoformat()
            memory = MemoryItem(
                title=f"候选团队记忆：{document.title}",
                summary=" ".join(text.split())[:800] or "用户已确认 Brief 草稿，可进入团队候选记忆审核。",
                memory_type="brief_decision",
                scope=Scope.TEAM_CANDIDATE,
                owner_user_id=owner_user_id,
                workspace_id=item.workspace_id,
                project_id=item.project_id,
                sources=[document.source],
                metadata={
                    "document_id": document.id,
                    "document_version": str(document.version),
                    "artifact_type": "brief_draft",
                    "inbox_item_id": item.id,
                },
            )
            item.status = "resolved"
            item.acknowledged_at = item.acknowledged_at or now
            item.resolved_at = now
            item.updated_at = now
            item.snooze_until = None
            item.metadata["confirmed_memory_id"] = memory.id
            item.metadata["confirmed_document_id"] = document.id
            audit = AuditEvent(
                actor=owner_user_id,
                action="confirm_brief_draft",
                target_type="inbox_item",
                target_id=item.id,
                metadata={
                    "document_id": document.id,
                    "document_version": document.version,
                    "memory_id": memory.id,
                },
            )

            for collection, record in (
                ("documents", document),
                ("memory_items", memory),
                ("inbox_items", item),
                ("audit_events", audit),
            ):
                connection.execute(
                    """
                    INSERT INTO records(collection, id, payload)
                    VALUES (?, ?, ?)
                    ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload
                    """,
                    (collection, record.id, record.model_dump_json()),
                )
                self._sync_fts(connection, collection, record)
                searchable = _extract_fts_doc(collection, record)
                if searchable is not None:
                    work = self.vector_index.prepare(
                        connection,
                        collection,
                        record.id,
                        f"{searchable.title} {searchable.body}".strip(),
                    )
                    if work is not None:
                        vector_work.append(work)

        if vector_work:
            from agentmesh.embedding import EMBEDDING_ENABLED

            if EMBEDDING_ENABLED:
                for work in vector_work:
                    self.vector_index.process(work)
        return BriefConfirmationResult(inbox_item=item, document=document, memory_item=memory)

    def save_document_if_version(self, document: DocumentRecord, expected_version: int) -> bool:
        """Atomically save a document only while its persisted version matches."""
        work: VectorWork | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("documents", document.id),
            ).fetchone()
            if row is None or DocumentRecord.model_validate_json(row["payload"]).version != expected_version:
                connection.rollback()
                return False
            connection.execute(
                "UPDATE records SET payload = ? WHERE collection = ? AND id = ?",
                (document.model_dump_json(), "documents", document.id),
            )
            self._sync_fts(connection, "documents", document)
            searchable = _extract_fts_doc("documents", document)
            if searchable is not None:
                work = self.vector_index.prepare(
                    connection,
                    "documents",
                    document.id,
                    f"{searchable.title} {searchable.body}".strip(),
                )

        if work is not None:
            from agentmesh.embedding import EMBEDDING_ENABLED

            if EMBEDDING_ENABLED:
                self.vector_index.process(work)
        return True

    def save_document_parse_job(self, job: DocumentParseJob) -> DocumentParseJob:
        self._upsert("document_parse_jobs", job)
        return job

    def save_document_parse_job_if_document_version(
        self,
        job: DocumentParseJob,
        document_id: str,
        version: int,
    ) -> bool:
        """Finalize a parse job only while its document version is still current."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM records WHERE collection = ? AND id = ?",
                ("documents", document_id),
            ).fetchone()
            if row is None or DocumentRecord.model_validate_json(row["payload"]).version != version:
                connection.rollback()
                return False
            connection.execute(
                """
                INSERT INTO records(collection, id, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(collection, id) DO UPDATE SET payload = excluded.payload
                """,
                ("document_parse_jobs", job.id, job.model_dump_json()),
            )
        return True

    def add_audit_event(self, event: AuditEvent) -> AuditEvent:
        self._upsert("audit_events", event)
        return event

    def add_consent_grant(self, grant: ConsentGrant) -> ConsentGrant:
        self._upsert("consent_grants", grant)
        return grant

    def save_consent_grant(self, grant: ConsentGrant) -> ConsentGrant:
        self._upsert("consent_grants", grant)
        return grant

    def get_active_consent_grant(self, grantor_id: str, grantee_id: str) -> ConsentGrant | None:
        for grant in self.consent_grants:
            if grant.grantor_id == grantor_id and grant.grantee_id == grantee_id and grant.active:
                return grant
        return None

    def add_contribution_point(self, point: ContributionPoint) -> ContributionPoint:
        self._upsert("contribution_points", point)
        return point

    def list_contribution_points(self, awarded_to_id: str | None = None) -> list[ContributionPoint]:
        items = self.contribution_points
        if awarded_to_id is not None:
            items = [point for point in items if point.awarded_to_id == awarded_to_id]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def add_memory_relation(self, relation: MemoryRelation) -> MemoryRelation:
        self._upsert("memory_relations", relation)
        return relation

    def get_inbox_item(self, item_id: str) -> InboxItem | None:
        return self._get("inbox_items", item_id, InboxItem)

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        return self._get("workspaces", workspace_id, Workspace)

    def get_project(self, project_id: str) -> Project | None:
        return self._get("projects", project_id, Project)

    def get_memory_item(self, item_id: str) -> MemoryItem | None:
        return self._get("memory_items", item_id, MemoryItem)

    def get_user_memory_item(self, item_id: str) -> UserMemoryItem | None:
        return self._get("user_memory_items", item_id, UserMemoryItem)

    def get_chat_thread(self, thread_id: str) -> ChatThread | None:
        return self._get("chat_threads", thread_id, ChatThread)

    def list_user_chat_threads(
        self,
        user_id: str,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> list[ChatThread]:
        items = [
            thread
            for thread in self.chat_threads
            if thread.user_id == user_id and thread.status == "active"
        ]
        if workspace_id is not None:
            items = [thread for thread in items if thread.workspace_id == workspace_id]
        if project_id is not None:
            items = [thread for thread in items if thread.project_id == project_id]
        return sorted(items, key=lambda thread: (thread.pinned, thread.updated_at, thread.id), reverse=True)

    def get_task(self, task_id: str) -> Task | None:
        return self._get("tasks", task_id, Task)

    def get_blackboard_post(self, post_id: str) -> BlackboardPost | None:
        return self._get("blackboard_posts", post_id, BlackboardPost)

    def get_source(self, source_id: str) -> Source | None:
        return self._get("sources", source_id, Source)

    def get_agent(self, agent_id: str) -> Agent | None:
        return self._get("agents", agent_id, Agent)

    def get_document(self, document_id: str) -> DocumentRecord | None:
        return self._get("documents", document_id, DocumentRecord)


    def get_vector_state(self, collection: str, record_id: str) -> VectorStatus | None:
        return self.vector_index.status(collection, record_id)

    def count_ready_vectors(self, collection: str, record_id: str) -> int:
        return self.vector_index.count_ready(collection, record_id)
    def get_document_parse_job(self, job_id: str) -> DocumentParseJob | None:
        return self._get("document_parse_jobs", job_id, DocumentParseJob)

    def get_tool_definition(self, tool_id: str) -> ToolDefinition | None:
        return self._get("tool_definitions", tool_id, ToolDefinition)

    def get_model_definition(self, model_id: str) -> ModelDefinition | None:
        return self._get("model_definitions", model_id, ModelDefinition)

    def get_risk_policy_rule(self, rule_id: str) -> RiskPolicyRule | None:
        return self._get("risk_policy_rules", rule_id, RiskPolicyRule)

    def get_permission_policy_rule(self, rule_id: str) -> PermissionPolicyRule | None:
        return self._get("permission_policy_rules", rule_id, PermissionPolicyRule)

    def get_scheduled_agent_task_definition(self, definition_id: str) -> ScheduledAgentTaskDefinition | None:
        return self._get("scheduled_agent_task_definitions", definition_id, ScheduledAgentTaskDefinition)

    def get_user(self, user_id: str) -> User | None:
        return self._get("users", user_id, User)

    def get_auth_credential(self, user_id: str) -> AuthCredential | None:
        return self._get("auth_credentials", user_id, AuthCredential)

    def get_auth_session(self, session_id: str) -> AuthSession | None:
        return self._get("auth_sessions", session_id, AuthSession)

    def get_auth_session_by_token_hash(self, token_hash: str) -> AuthSession | None:
        for session in self.auth_sessions:
            if session.token_hash == token_hash:
                return session
        return None

    def get_team(self, team_id: str) -> Team | None:
        return self._get("teams", team_id, Team)

    def get_team_membership(self, membership_id: str) -> TeamMembership | None:
        return self._get("team_memberships", membership_id, TeamMembership)

    def list_teams(self, workspace_id: str | None = None) -> list[Team]:
        items = self.teams
        if workspace_id is not None:
            items = [team for team in items if team.workspace_id == workspace_id]
        return sorted(items, key=lambda item: item.created_at)

    def list_team_memberships(
        self,
        team_id: str | None = None,
        user_id: str | None = None,
    ) -> list[TeamMembership]:
        items = self.team_memberships
        if team_id is not None:
            items = [membership for membership in items if membership.team_id == team_id]
        if user_id is not None:
            items = [membership for membership in items if membership.user_id == user_id]
        return sorted(items, key=lambda item: item.created_at)

    def remove_team_membership(self, membership_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM records WHERE collection = ? AND id = ?",
                ("team_memberships", membership_id),
            )
            return cursor.rowcount > 0

    def list_agent_tool_grants(self, agent_id: str) -> list[AgentToolGrant]:
        return [grant for grant in self.agent_tool_grants if grant.agent_id == agent_id]

    def list_recent_thread_messages(
        self,
        thread_id: str,
        *,
        limit: int = 6,
        max_content_bytes: int = 4096,
    ) -> list[ChatMessage]:
        if not 1 <= limit <= 100:
            raise ValueError("recent_message_limit_invalid")
        if not 1 <= max_content_bytes <= 64 * 1024:
            raise ValueError("recent_message_byte_limit_invalid")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM records
                WHERE collection = 'chat_messages'
                  AND json_extract(payload, '$.thread_id') = ?
                ORDER BY json_extract(payload, '$.created_at') DESC, id DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        newest_first = [ChatMessage.model_validate_json(row["payload"]) for row in rows]
        selected: list[ChatMessage] = []
        consumed = 0
        for message in newest_first:
            size = len(message.content.encode("utf-8"))
            if consumed + size > max_content_bytes:
                break
            selected.append(message)
            consumed += size
        return list(reversed(selected))

    def list_thread_messages(self, thread_id: str) -> list[ChatMessage]:
        items = [message for message in self.chat_messages if message.thread_id == thread_id]
        return sorted(items, key=lambda message: (message.created_at, message.id))

    def list_thread_turn_traces(self, thread_id: str) -> list[ChatTurnTrace]:
        traces = [trace for trace in self.chat_turn_traces if trace.thread_id == thread_id]
        return sorted(traces, key=lambda trace: (trace.created_at, trace.id))

    def list_user_memory_items(
        self,
        user_id: str,
        layer: str | None = None,
        project_id: str | None = None,
        memory_date: dt_date | None = None,
        memory_type: str | None = None,
    ) -> list[UserMemoryItem]:
        items = [item for item in self.user_memory_items if item.user_id == user_id]
        if layer is not None:
            items = [item for item in items if item.layer == layer]
        if project_id is not None:
            items = [item for item in items if item.project_id == project_id]
        if memory_date is not None:
            items = [item for item in items if item.memory_date == memory_date]
        if memory_type is not None:
            items = [item for item in items if item.memory_type == memory_type]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def list_personal_activity(self) -> list[ActivityLog]:
        return [log for log in self.activity_logs if log.category == "personal"]

    def list_external_activity(self) -> list[ActivityLog]:
        return [log for log in self.activity_logs if log.category == "external_agent"]

    def search(
        self,
        query: str,
        allowed_scopes: set[Scope],
        workspace_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
        max_results: int = 20,
        max_chars: int = 8000,
        result_types: set[str] | None = None,
        allowed_record_ids: set[str] | None = None,
    ) -> list[SearchResult]:
        needle = query.strip()
        if not needle or not allowed_scopes:
            return []

        scope_values = [s.value for s in allowed_scopes]
        placeholders = ",".join("?" for _ in scope_values)
        allowed_collections: set[str] | None = set(_KNOWLEDGE_FTS_COLLECTIONS)
        if result_types is not None:
            allowed_collections = {
                collection
                for result_type, collection in _RESULT_TYPE_COLLECTIONS.items()
                if result_type in result_types
            }
            if not allowed_collections:
                return []
        if allowed_record_ids is not None and not allowed_record_ids:
            return []


        with self._connect() as connection:
            fts_rows = self._fts_match(
                connection,
                needle,
                scope_values,
                placeholders,
                allowed_collections,
                allowed_record_ids,
                workspace_id,
                project_id,
                user_id,
            )
            if not fts_rows:
                fts_rows = self._fts_like_fallback(
                    connection,
                    needle,
                    scope_values,
                    placeholders,
                    allowed_collections,
                    allowed_record_ids,
                    workspace_id,
                    project_id,
                    user_id,
                )
            vec_rows = self._vec_search(
                connection,
                needle,
                scope_values,
                placeholders,
                allowed_collections,
                allowed_record_ids,
                workspace_id,
                project_id,
                user_id,
            )

        if allowed_collections is not None:
            fts_rows = [row for row in fts_rows if row["collection"] in allowed_collections]
            vec_rows = [row for row in vec_rows if row["collection"] in allowed_collections]
        if allowed_record_ids is not None:
            fts_rows = [row for row in fts_rows if row["record_id"] in allowed_record_ids]
            vec_rows = [row for row in vec_rows if row["record_id"] in allowed_record_ids]

        rows = self._rrf_merge(fts_rows, vec_rows)

        if not rows:
            return []

        results: list[SearchResult] = []
        threads_by_id: dict[str, ChatThread] | None = None
        tasks_by_id: dict[str, Task] | None = None

        for row in rows:
            collection = row["collection"]
            record_id = row["record_id"]
            row_workspace_id = row["workspace_id"] or None
            row_project_id = row["project_id"] or None
            row_user_id = row["user_id"] or None

            if collection == "chat_messages":
                if threads_by_id is None:
                    threads_by_id = {thread.id: thread for thread in self.chat_threads}
                msg = self._get("chat_messages", record_id, ChatMessage)
                if msg is None:
                    continue
                thread = threads_by_id.get(msg.thread_id)
                if (
                    thread is None
                    or thread.status != "active"
                    or not self._thread_matches(thread, workspace_id, project_id)
                ):
                    continue
                if msg.scope == Scope.PRIVATE and (
                    user_id is None or thread is None or thread.user_id != user_id
                ):
                    continue
                results.append(
                    SearchResult(
                        id=msg.id,
                        result_type="chat_message",
                        title="对话记录",
                        summary=msg.content,
                        scope=msg.scope,
                        sources=msg.sources,
                        created_at=msg.created_at,
                    )
                )

            elif collection == "activity_logs":
                if not self._project_fields_match(row_workspace_id, row_project_id, workspace_id, project_id):
                    continue
                log = self._get("activity_logs", record_id, ActivityLog)
                if log is None:
                    continue
                if not self.activity_log_visible_to_user(log, user_id):
                    continue
                results.append(
                    SearchResult(
                        id=log.id,
                        result_type="activity_log",
                        title=log.title,
                        summary=log.summary,
                        scope=log.scope,
                        created_at=log.created_at,
                    )
                )

            elif collection == "blackboard_posts":
                post = self._get("blackboard_posts", record_id, BlackboardPost)
                if post is None or post.post_type != BlackboardPostType.EVIDENCE:
                    continue
                if threads_by_id is None:
                    threads_by_id = {thread.id: thread for thread in self.chat_threads}
                if tasks_by_id is None:
                    tasks_by_id = {task.id: task for task in self.tasks}
                task = tasks_by_id.get(post.task_id)
                thread = threads_by_id.get(task.thread_id) if task else None
                if not self._thread_matches(thread, workspace_id, project_id):
                    continue
                results.append(
                    SearchResult(
                        id=post.id,
                        result_type="blackboard_evidence",
                        title=post.title,
                        summary=post.content,
                        scope=post.scope,
                        sources=post.sources,
                        project_id=thread.project_id if thread else None,
                        created_at=post.created_at,
                    )
                )

            elif collection == "memory_items":
                if not self._project_fields_match(row_workspace_id, row_project_id, workspace_id, project_id):
                    continue
                item = self._get("memory_items", record_id, MemoryItem)
                if item is None:
                    continue
                if not self.memory_item_visible_to_user(item, user_id):
                    continue
                if (
                    item.scope == Scope.PROJECT
                    and user_id
                    and item.project_id
                    and not self.user_can_access_project(user_id, item.project_id)
                ):
                    continue
                if (
                    item.team_id
                    and user_id
                    and item.scope in (Scope.TEAM_ACCEPTED, Scope.TEAM_CANDIDATE)
                    and not self._user_in_team(user_id, item.team_id)
                ):
                    continue
                results.append(
                    SearchResult(
                        id=item.id,
                        result_type="memory_item",
                        title=item.title,
                        summary=item.summary,
                        scope=item.scope,
                        sources=item.sources,
                        project_id=item.project_id,
                        team_id=item.team_id,
                        created_at=item.created_at,
                    )
                )

            elif collection == "user_memory_items":
                if Scope.PRIVATE not in allowed_scopes or user_id is None:
                    continue
                if row_user_id != user_id:
                    continue
                if not self._project_fields_match(row_workspace_id, row_project_id, workspace_id, project_id):
                    continue
                item = self._get("user_memory_items", record_id, UserMemoryItem)
                if item is None or item.status != "active":
                    continue
                results.append(
                    SearchResult(
                        id=item.id,
                        result_type="user_memory_item",
                        title=item.title,
                        summary=item.summary,
                        scope=item.scope,
                        sources=item.sources,
                        project_id=item.project_id,
                        created_at=item.created_at,
                    )
                )

            elif collection == "documents":
                if Scope.PRIVATE not in allowed_scopes or user_id is None:
                    continue
                if row_user_id != user_id:
                    continue
                if not self._project_fields_match(row_workspace_id, row_project_id, workspace_id, project_id):
                    continue
                document = self._get("documents", record_id, DocumentRecord)
                if document is None:
                    continue
                results.append(
                    SearchResult(
                        id=document.id,
                        result_type="document",
                        title=document.title,
                        summary=document.text[:500],
                        scope=Scope.PRIVATE,
                        sources=[document.source],
                        project_id=document.project_id,
                        created_at=document.created_at,
                    )
                )

        # Filter record kinds before applying the result/character budget so
        # unrelated same-scope records cannot crowd out strict memory results.
        if result_types is not None:
            results = [result for result in results if result.result_type in result_types]
        if allowed_record_ids is not None:
            results = [result for result in results if result.id in allowed_record_ids]
        return self._apply_budget(results, max_results, max_chars)

    @staticmethod
    def _apply_budget(results: list[SearchResult], max_results: int, max_chars: int) -> list[SearchResult]:
        output: list[SearchResult] = []
        chars_used = 0
        for result in results:
            if len(output) >= max_results:
                break
            result_chars = len(result.title) + len(result.summary)
            if chars_used + result_chars > max_chars and output:
                break
            output.append(result)
            chars_used += result_chars
        return output

    @staticmethod
    def _fts_match(
        connection: sqlite3.Connection,
        needle: str,
        scope_values: list[str],
        placeholders: str,
        allowed_collections: set[str] | None = None,
        allowed_record_ids: set[str] | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> list[sqlite3.Row]:
        if not _can_use_fts_match(needle):
            return []
        fts_query = _build_fts_query(needle)
        collection_values = sorted(allowed_collections) if allowed_collections is not None else []
        collection_clause = ""
        if collection_values:
            collection_placeholders = ",".join("?" for _ in collection_values)
            collection_clause = f" AND collection IN ({collection_placeholders})"
        record_id_values = sorted(allowed_record_ids) if allowed_record_ids is not None else []
        record_id_clause = ""
        if record_id_values:
            record_id_placeholders = ",".join("?" for _ in record_id_values)
            record_id_clause = f" AND record_id IN ({record_id_placeholders})"
        tenant_clauses: list[str] = []
        tenant_values: list[str] = []
        if workspace_id is not None:
            tenant_clauses.append("AND workspace_id = ?")
            tenant_values.append(workspace_id)
        if project_id is not None:
            tenant_clauses.append("AND project_id = ?")
            tenant_values.append(project_id)
        if user_id is not None:
            tenant_clauses.append("AND (scope != ? OR user_id = ?)")
            tenant_values.extend([Scope.PRIVATE.value, user_id])
        tenant_clause = " ".join(tenant_clauses)
        try:
            return connection.execute(
                f"""
                SELECT collection, record_id, scope, workspace_id, project_id,
                       user_id, created_at, bm25(records_fts) AS score
                FROM records_fts
                WHERE records_fts MATCH ?
                  AND scope IN ({placeholders})
                  {collection_clause}
                  {record_id_clause}
                  {tenant_clause}
                ORDER BY score
                LIMIT 200
                """,
                [fts_query, *scope_values, *collection_values, *record_id_values, *tenant_values],
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    @staticmethod
    def _fts_like_fallback(
        connection: sqlite3.Connection,
        needle: str,
        scope_values: list[str],
        placeholders: str,
        allowed_collections: set[str] | None = None,
        allowed_record_ids: set[str] | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> list[sqlite3.Row]:
        like_pattern = f"%{needle}%"
        collection_values = sorted(allowed_collections) if allowed_collections is not None else []
        collection_clause = ""
        if collection_values:
            collection_placeholders = ",".join("?" for _ in collection_values)
            collection_clause = f" AND collection IN ({collection_placeholders})"
        record_id_values = sorted(allowed_record_ids) if allowed_record_ids is not None else []
        record_id_clause = ""
        if record_id_values:
            record_id_placeholders = ",".join("?" for _ in record_id_values)
            record_id_clause = f" AND record_id IN ({record_id_placeholders})"
        tenant_clauses: list[str] = []
        tenant_values: list[str] = []
        if workspace_id is not None:
            tenant_clauses.append("AND workspace_id = ?")
            tenant_values.append(workspace_id)
        if project_id is not None:
            tenant_clauses.append("AND project_id = ?")
            tenant_values.append(project_id)
        if user_id is not None:
            tenant_clauses.append("AND (scope != ? OR user_id = ?)")
            tenant_values.extend([Scope.PRIVATE.value, user_id])
        tenant_clause = " ".join(tenant_clauses)
        return connection.execute(
            f"""
            SELECT collection, record_id, scope, workspace_id, project_id,
                   user_id, created_at
            FROM records_fts
            WHERE (title LIKE ? OR body LIKE ?)
              AND scope IN ({placeholders})
              {collection_clause}
              {record_id_clause}
              {tenant_clause}
            LIMIT 200
            """,
            [like_pattern, like_pattern, *scope_values, *collection_values, *record_id_values, *tenant_values],
        ).fetchall()

    @staticmethod
    def _vec_search(
        connection: sqlite3.Connection,
        needle: str,
        scope_values: list[str],
        placeholders: str,
        allowed_collections: set[str] | None = None,
        allowed_record_ids: set[str] | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        from agentmesh.embedding import EMBEDDING_ENABLED, cosine_similarity, deserialize_embedding, embed_text

        if not EMBEDDING_ENABLED:
            return []
        query_embedding = embed_text(needle)
        if query_embedding is None:
            return []
        collection_values = sorted(allowed_collections) if allowed_collections is not None else []
        collection_clause = ""
        if collection_values:
            collection_placeholders = ",".join("?" for _ in collection_values)
            collection_clause = f" AND rf.collection IN ({collection_placeholders})"
        record_id_values = sorted(allowed_record_ids) if allowed_record_ids is not None else []
        record_id_clause = ""
        if record_id_values:
            record_id_placeholders = ",".join("?" for _ in record_id_values)
            record_id_clause = f" AND rf.record_id IN ({record_id_placeholders})"
        tenant_clauses: list[str] = []
        tenant_values: list[str] = []
        if workspace_id is not None:
            tenant_clauses.append("AND rf.workspace_id = ?")
            tenant_values.append(workspace_id)
        if project_id is not None:
            tenant_clauses.append("AND rf.project_id = ?")
            tenant_values.append(project_id)
        if user_id is not None:
            tenant_clauses.append("AND (rf.scope != ? OR rf.user_id = ?)")
            tenant_values.extend([Scope.PRIVATE.value, user_id])
        tenant_clause = " ".join(tenant_clauses)
        rows = connection.execute(
            f"""
            SELECT rv.collection, rv.record_id, rv.embedding,
                   rf.scope, rf.workspace_id, rf.project_id, rf.user_id, rf.created_at
            FROM records_vec rv
            JOIN vector_states vs
              ON vs.collection = rv.collection AND vs.record_id = rv.record_id
            JOIN records_fts rf
              ON rv.collection = rf.collection AND rv.record_id = rf.record_id
            WHERE rf.scope IN ({placeholders})
              AND vs.state = ?
              {tenant_clause}
              {collection_clause}
              {record_id_clause}
            """,
            [
                *scope_values,
                VectorState.READY.value,
                *tenant_values,
                *collection_values,
                *record_id_values,
            ],
        ).fetchall()
        scored: list[tuple[float, dict]] = []
        for row in rows:
            embedding = deserialize_embedding(row["embedding"])
            score = cosine_similarity(query_embedding, embedding)
            scored.append((score, {
                "collection": row["collection"],
                "record_id": row["record_id"],
                "scope": row["scope"],
                "workspace_id": row["workspace_id"],
                "project_id": row["project_id"],
                "user_id": row["user_id"],
                "created_at": row["created_at"],
            }))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:50]]

    @staticmethod
    def _rrf_merge(fts_rows: list, vec_rows: list, k: int = 60) -> list[dict]:
        """Reciprocal Rank Fusion: merge FTS and vector results."""
        scores: dict[tuple[str, str], float] = {}
        row_data: dict[tuple[str, str], dict] = {}

        for rank, row in enumerate(fts_rows):
            key = (row["collection"], row["record_id"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in row_data:
                row_data[key] = dict(row) if hasattr(row, "keys") else row

        for rank, row in enumerate(vec_rows):
            key = (row["collection"], row["record_id"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in row_data:
                row_data[key] = row

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return [row_data[key] for key, _ in ranked[:200]]

    @staticmethod
    def _thread_matches(thread: ChatThread | None, workspace_id: str | None, project_id: str | None) -> bool:
        if thread is None:
            return workspace_id is None and project_id is None
        return SQLiteStore._project_fields_match(thread.workspace_id, thread.project_id, workspace_id, project_id)

    @staticmethod
    def _project_fields_match(
        item_workspace_id: str | None,
        item_project_id: str | None,
        workspace_id: str | None,
        project_id: str | None,
    ) -> bool:
        if workspace_id is not None and item_workspace_id != workspace_id:
            return False
        return not (project_id is not None and item_project_id != project_id)

    def user_can_access_project(self, user_id: str, project_id: str) -> bool:
        project = self.get_project(project_id)
        if project is None:
            return False
        if not project.member_ids:
            return True
        return user_id in project.member_ids

    def learned_skill_visible_to_user(
        self,
        skill: LearnedSkill,
        user_id: str,
        *,
        project_id: str | None = None,
    ) -> bool:
        user = self.get_user(user_id)
        if user is None:
            return False
        if skill.workspace_id is not None and skill.workspace_id != user.workspace_id:
            return False
        if skill.scope == Scope.PROJECT:
            if (
                skill.workspace_id != user.workspace_id
                or skill.project_id is None
                or (project_id is not None and skill.project_id != project_id)
            ):
                return False
            project = self.get_project(skill.project_id)
            if (
                project is None
                or project.workspace_id != user.workspace_id
                or not self.user_can_access_project(user.id, project.id)
            ):
                return False
            return skill.user_id == user.id or skill.status == SkillStatus.ACTIVE
        return skill.user_id == user.id

    def memory_item_visible_to_user(self, item: MemoryItem, user_id: str | None) -> bool:
        if user_id is None:
            return item.scope != Scope.PRIVATE
        user = self.get_user(user_id)
        if user is None:
            return False
        if item.workspace_id is not None and item.workspace_id != user.workspace_id:
            return False
        if item.scope == Scope.PRIVATE:
            return item.owner_user_id == user.id
        if item.scope == Scope.PROJECT:
            return item.project_id is not None and self.user_can_access_project(user.id, item.project_id)
        if item.scope == Scope.TEAM_CANDIDATE:
            if item.owner_user_id == user.id:
                return True
            if user.role not in (UserRole.TEAM_LEAD, UserRole.ADMIN):
                return False
        return item.team_id is None or self._user_in_team(user.id, item.team_id)

    def activity_log_visible_to_user(self, log: ActivityLog, user_id: str | None) -> bool:
        if user_id is None:
            return log.scope != Scope.PRIVATE
        user = self.get_user(user_id)
        if user is None:
            return False
        if log.workspace_id is not None and log.workspace_id != user.workspace_id:
            return False
        if log.scope == Scope.PRIVATE:
            return log.user_id == user.id
        if log.project_id is not None:
            return self.user_can_access_project(user.id, log.project_id)
        return True

    def _user_in_team(self, user_id: str, team_id: str) -> bool:
        user = self.get_user(user_id)
        if user and user.role in (UserRole.ADMIN, UserRole.TEAM_LEAD):
            return True
        memberships = self.list_team_memberships(team_id=team_id, user_id=user_id)
        return len(memberships) > 0


class LazySQLiteStore:
    """Initialize the process-owned SQLite writer only on first application use."""

    def __init__(self) -> None:
        self._instance: SQLiteStore | None = None
        self._lock = threading.Lock()

    def initialize(self) -> SQLiteStore:
        with self._lock:
            if self._instance is None:
                self._instance = SQLiteStore(enforce_writer_lock=True)
            return self._instance

    def __getattr__(self, name: str):  # noqa: ANN204
        return getattr(self.initialize(), name)


store = LazySQLiteStore()
