from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as dt_date
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from agentmesh.models import (
    ActivityLog,
    Agent,
    AgentMemoryBinding,
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
    ChatRole,
    ChatThread,
    ChatTurnReceipt,
    ChatTurnReceiptStatus,
    ChatTurnTrace,
    ChatWorkflowTrace,
    ConsentGrant,
    ContributionPoint,
    DocumentParseJob,
    DocumentRecord,
    InboxItem,
    Intent,
    LearnedSkill,
    MarketParticipation,
    MemoryItem,
    MemoryRelation,
    ModelDefinition,
    PermissionPolicyRule,
    Project,
    RetrievalMetrics,
    RiskPolicyRule,
    ScheduledAgentTaskDefinition,
    Scope,
    SDKSessionRecord,
    SearchResult,
    SkillBinding,
    SkillCapabilityProfile,
    SkillDefinition,
    SkillNodeResult,
    SkillPackage,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
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
    AttemptStatus,
    ExecutionAttempt,
    ExecutionLease,
    ExecutionPlanVersion,
    InvocationState,
    ModelCallReceipt,
    RequirementVersion,
    ResearchCommandReceipt,
    ResearchGate,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    ToolInvocation,
    ToolReceipt,
    canonical_json_bytes,
    canonical_sha256,
)
from agentmesh.research_orchestration.current import (
    RESEARCH_WRITER_CONTROL_KEY,
    RESEARCH_WRITER_CONTROL_SEED_HASH,
    ResearchVersionInitializer,
    ResearchWriterControlV1,
    ResearchWriterGeneration,
)
from agentmesh.vector_index import VectorIndex, VectorState, VectorStatus, VectorWork

if TYPE_CHECKING:
    from agentmesh.research_orchestration.api import ResearchCommandType, ResearchOwnerScope
    from agentmesh.research_orchestration.workflow import (
        CommandCommitResult,
        CommandMutation,
        PlanningMutation,
        WorkflowContext,
    )

ModelT = TypeVar("ModelT", bound=BaseModel)

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "data" / "agentmesh.sqlite3"

class BriefConfirmationError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ResearchStoreConflict(RuntimeError):
    """A durable research invariant or compare-and-swap precondition failed."""


class ResearchToolApprovalError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(slots=True)
class BriefConfirmationResult:
    inbox_item: InboxItem
    document: DocumentRecord
    memory_item: MemoryItem


@dataclass(frozen=True, slots=True)
class ResearchToolApprovalResult:
    inbox_item: InboxItem
    run: AgentRun
    attempt_id: str | None
    expired: bool = False


# --- FTS5 infrastructure ---

_FTS_COLLECTIONS = frozenset(
    {
        "chat_messages",
        "activity_logs",
        "blackboard_posts",
        "memory_items",
        "user_memory_items",
        "documents",
        "skill_capability_profiles",
    }
)

_KNOWLEDGE_FTS_COLLECTIONS = frozenset(_FTS_COLLECTIONS - {"skill_capability_profiles"})

_RESULT_TYPE_COLLECTIONS = {
    "chat_message": "chat_messages",
    "activity_log": "activity_logs",
    "blackboard_evidence": "blackboard_posts",
    "memory_item": "memory_items",
    "user_memory_item": "user_memory_items",
    "document": "documents",
}


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
        title = getattr(item, "skill_name", "")
        body = " ".join(
            [
                getattr(item, "capability_type", ""),
                *getattr(item, "input_kinds", []),
                *getattr(item, "output_kinds", []),
                *getattr(item, "examples", []),
            ]
        )
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
    "skill_capability_profiles": SkillCapabilityProfile,
}


class SQLiteStore:
    def __init__(self, db_path: str | Path | None = None):
        configured_path = db_path or os.getenv("AGENTMESH_DB_PATH") or DEFAULT_DB_PATH
        self.db_path = Path(configured_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vector_index = VectorIndex(self.db_path)
        self._init_schema()
        self._backfill_artifact_projections()
        self._backfill_fts()
        self._backfill_vec()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema(connection)
        connection.commit()
        return connection

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_writer_control (
                control_key TEXT PRIMARY KEY CHECK(control_key = 'global'),
                active_generation TEXT NOT NULL
                    CHECK(active_generation IN ('research-v2', 'research-v3')),
                generation_epoch INTEGER NOT NULL CHECK(generation_epoch >= 1),
                decision_receipt_hash TEXT NOT NULL CHECK(length(decision_receipt_hash) = 64),
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO research_writer_control(
                control_key, active_generation, generation_epoch,
                decision_receipt_hash, updated_at
            ) VALUES (?, 'research-v2', 1, ?, ?)
            """,
            (
                RESEARCH_WRITER_CONTROL_KEY,
                RESEARCH_WRITER_CONTROL_SEED_HASH,
                now_utc().isoformat(),
            ),
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS research_writer_generation_fence
            BEFORE INSERT ON agent_runs
            WHEN NEW.orchestration_version IN ('research-v2', 'research-v3')
              AND NEW.orchestration_version <> (
                  SELECT active_generation FROM research_writer_control WHERE control_key = 'global'
              )
            BEGIN
                SELECT RAISE(ABORT, 'research writer generation fenced');
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
        from agentmesh.research_orchestration.v3.sqlite_repository import (
            SQLiteResearchV3Repository,
        )

        SQLiteResearchV3Repository.initialize_schema_in_connection(connection)
        VectorIndex.ensure_schema(connection)

    def reset(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM records")
            connection.execute("DELETE FROM records_fts")
            connection.execute("DELETE FROM records_vec")
            connection.execute("DELETE FROM vector_states")
            connection.execute("DELETE FROM agent_run_events")
            connection.execute("DELETE FROM agent_run_receipts")
            connection.execute("DELETE FROM research_model_call_receipts")
            connection.execute("DELETE FROM research_v3_verified_artifacts")
            connection.execute("DELETE FROM research_v3_invocations")
            connection.execute("DELETE FROM research_v3_attempts")
            connection.execute("DELETE FROM research_v3_command_receipts")
            connection.execute("DELETE FROM research_v3_records")
            connection.execute("DELETE FROM research_v3_runs")
            connection.execute(
                """UPDATE research_writer_control
                SET active_generation = 'research-v2', generation_epoch = 1,
                    decision_receipt_hash = ?, updated_at = ?
                WHERE control_key = ?""",
                (
                    RESEARCH_WRITER_CONTROL_SEED_HASH,
                    now_utc().isoformat(),
                    RESEARCH_WRITER_CONTROL_KEY,
                ),
            )
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

    def _upsert(self, collection: str, item: BaseModel) -> None:
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
                work = self.vector_index.prepare(
                    connection,
                    collection,
                    item.id,
                    f"{doc.title} {doc.body}".strip(),
                )
            elif collection in _FTS_COLLECTIONS:
                self.vector_index.mark_stale(connection, collection, item.id)

        if work is not None:
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
                       CASE WHEN rv.record_id IS NULL THEN 0 ELSE 1 END AS has_vector
                FROM records r
                LEFT JOIN records_vec rv
                  ON rv.collection = r.collection AND rv.record_id = r.id
                LEFT JOIN vector_states vs
                  ON vs.collection = r.collection AND vs.record_id = r.id
                WHERE r.collection IN ({placeholders}) AND vs.record_id IS NULL
                ORDER BY r.created_order
                """
            ).fetchall()
            for row in rows:
                model_cls = _FTS_COLLECTION_MODELS.get(row["collection"])
                if model_cls is None:
                    continue
                item = model_cls.model_validate_json(row["payload"])
                doc = _extract_fts_doc(row["collection"], item)
                if doc is None:
                    continue
                text = f"{doc.title} {doc.body}".strip()
                if row["has_vector"]:
                    self.vector_index.adopt_ready(connection, row["collection"], row["id"], text)
                    continue
                work = self.vector_index.prepare(connection, row["collection"], row["id"], text)
                if work is not None:
                    pending.append(work)

        if EMBEDDING_ENABLED:
            for work in pending[:100]:
                self.vector_index.process(work)

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

    def save_skill_definition(self, skill: SkillDefinition) -> SkillDefinition:
        self._upsert("skill_definitions", skill)
        return skill

    def save_skill_capability_profile(self, profile: SkillCapabilityProfile) -> SkillCapabilityProfile:
        self._upsert("skill_capability_profiles", profile)
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

    def rank_skill_profiles(
        self,
        query: str,
        allowed_skill_ids: set[str],
    ) -> tuple[list[str], list[str], list[str]]:
        """Return isolated lexical/vector rankings for already-authorized profiles."""
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
        from agentmesh.embedding import EMBEDDING_ENABLED, deserialize_embedding, embed_text

        if EMBEDDING_ENABLED:
            query_embedding = embed_text(query)
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
                      AND collection = 'skill_capability_profiles'
                      AND record_id IN ({placeholders})
                    ORDER BY bm25(records_fts)
                    LIMIT 50
                    """,
                    [match_query, *allowed],
                ).fetchall()
                fts_ids = [str(row["record_id"]) for row in rows]
            vector_ids: list[str] = []
            if query_embedding is not None:
                from agentmesh.embedding import cosine_similarity

                rows = connection.execute(
                    f"""
                    SELECT record_id, embedding
                    FROM records_vec
                    WHERE collection = 'skill_capability_profiles'
                      AND record_id IN ({placeholders})
                    """,
                    allowed,
                ).fetchall()
                scores = [
                    (cosine_similarity(query_embedding, deserialize_embedding(row["embedding"])), str(row["record_id"]))
                    for row in rows
                ]
                scores.sort(reverse=True)
                vector_ids = [skill_id for _score, skill_id in scores]
        return fts_ids, vector_ids, diagnostics

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

    def _close_unsettled_research_execution(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        cancelled_at: datetime,
        reason: str,
        attempt_status: AttemptStatus = AttemptStatus.CANCELLED,
        step_status: StepStatus = StepStatus.CANCELLED,
    ) -> None:
        invocation_rows = connection.execute(
            """
            SELECT * FROM research_tool_invocations
            WHERE run_id = ? AND state IN (?, ?)
            """,
            (run_id, InvocationState.PREPARED.value, InvocationState.SENT.value),
        ).fetchall()
        for row in invocation_rows:
            try:
                current = ToolInvocation.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
            if not self._research_invocation_projection_matches(row, current):
                raise ResearchStoreConflict("Tool invocation failed integrity verification")
            if current.state == InvocationState.PREPARED:
                updated = current.model_copy(
                    update={
                        "state": InvocationState.CANCELLED,
                        "error_code": reason,
                        "updated_at": cancelled_at,
                    }
                )
            else:
                updated = current.model_copy(
                    update={
                        "state": InvocationState.UNKNOWN,
                        "unknown_at": cancelled_at,
                        "error_code": "cancelled_after_send_result_unknown",
                        "updated_at": cancelled_at,
                    }
                )
            connection.execute(
                """
                UPDATE research_tool_invocations
                SET state = ?, unknown_at = ?, payload = ?, updated_at = ?
                WHERE id = ? AND state = ? AND active_send_sequence = ?
                  AND sent_fencing_epoch IS ? AND updated_at = ?
                """,
                (
                    updated.state.value,
                    updated.unknown_at.isoformat() if updated.unknown_at is not None else None,
                    updated.model_dump_json(),
                    cancelled_at.isoformat(),
                    current.id,
                    current.state.value,
                    current.active_send_sequence,
                    current.sent_fencing_epoch,
                    current.updated_at.isoformat(),
                ),
            )

        attempt_rows = connection.execute(
            "SELECT * FROM research_attempts WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        for attempt_row in attempt_rows:
            try:
                attempt = ExecutionAttempt.model_validate_json(attempt_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research attempt failed integrity verification") from None
            if not self._research_attempt_projection_matches(attempt_row, attempt):
                raise ResearchStoreConflict("research attempt failed integrity verification")
            if attempt.status in {AttemptStatus.COMPLETED, AttemptStatus.FAILED, AttemptStatus.CANCELLED}:
                continue
            step_rows = connection.execute(
                "SELECT * FROM research_steps WHERE attempt_id = ?",
                (attempt.id,),
            ).fetchall()
            for step_row in step_rows:
                try:
                    step = ResearchStep.model_validate_json(step_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("research step failed integrity verification") from None
                if not self._research_step_projection_matches(step_row, step):
                    raise ResearchStoreConflict("research step failed integrity verification")
                if step.status in {
                    StepStatus.COMPLETED,
                    StepStatus.FAILED,
                    StepStatus.SKIPPED,
                    StepStatus.CANCELLED,
                }:
                    continue
                closed_step = step.model_copy(
                    update={
                        "status": step_status,
                        "result_artifact_id": None,
                        "error_code": reason,
                        "completed_at": cancelled_at,
                        "updated_at": cancelled_at,
                    }
                )
                connection.execute(
                    """
                    UPDATE research_steps
                    SET status = ?, result_artifact_id = ?, payload = ?, updated_at = ?
                    WHERE attempt_id = ? AND step_number = ? AND status = ?
                      AND claim_epoch = ? AND updated_at = ?
                    """,
                    (
                        closed_step.status.value,
                        closed_step.result_artifact_id,
                        closed_step.model_dump_json(),
                        cancelled_at.isoformat(),
                        step.attempt_id,
                        step.step_number,
                        step.status.value,
                        step.claim_epoch,
                        step.updated_at.isoformat(),
                    ),
                )
            closed_attempt = attempt.model_copy(
                update={
                    "status": attempt_status,
                    "lease_owner": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "completed_at": cancelled_at,
                    "updated_at": cancelled_at,
                }
            )
            connection.execute(
                """
                UPDATE research_attempts
                SET status = ?, lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    payload = ?, updated_at = ?
                WHERE id = ? AND status = ? AND fencing_epoch = ? AND updated_at = ?
                """,
                (
                    closed_attempt.status.value,
                    closed_attempt.model_dump_json(),
                    cancelled_at.isoformat(),
                    attempt.id,
                    attempt.status.value,
                    attempt.fencing_epoch,
                    attempt.updated_at.isoformat(),
                ),
            )

    def _cancel_agent_run_tree_in_transaction(
        self,
        connection: sqlite3.Connection,
        run: AgentRun,
        *,
        reason: str,
    ) -> AgentRun:
        cancelled_at = now_utc()
        events: list[tuple[str, dict[str, object]]] = []
        plan_row = connection.execute(
            "SELECT payload FROM skill_plans WHERE run_id = ?",
            (run.id,),
        ).fetchone()
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
                node.status = SkillPlanNodeStatus.CANCELLED
                node.completed_at = cancelled_at
                events.append(("node_cancelled", {"plan_id": plan.id, "node_id": node.id}))
            plan.status = SkillPlanStatus.CANCELLED
            plan.updated_at = cancelled_at
            self._write_skill_plan(connection, plan)
        if run.orchestration_version == "research-v2":
            self._close_unsettled_research_execution(
                connection,
                run.id,
                cancelled_at=cancelled_at,
                reason=reason,
            )
            workflow_row = connection.execute(
                "SELECT payload, state_version FROM research_workflows WHERE run_id = ?",
                (run.id,),
            ).fetchone()
            if workflow_row is not None:
                workflow = ResearchWorkflow.model_validate_json(workflow_row["payload"])
                if workflow.phase != ResearchPhase.TERMINAL:
                    workflow.phase = ResearchPhase.TERMINAL
                    workflow.active_gate = ResearchGate.NONE
                    workflow.state_version = workflow_row["state_version"] + 1
                    workflow.updated_at = cancelled_at
                    connection.execute(
                        """
                        UPDATE research_workflows
                        SET phase = ?, active_gate = ?, state_version = ?, payload = ?, updated_at = ?
                        WHERE run_id = ? AND state_version = ?
                        """,
                        (
                            workflow.phase.value,
                            workflow.active_gate.value,
                            workflow.state_version,
                            workflow.model_dump_json(),
                            cancelled_at.isoformat(),
                            run.id,
                            workflow_row["state_version"],
                        ),
                    )
                    events.append(
                        (
                            "research_updated",
                            {
                                "state_version": workflow.state_version,
                                "phase": workflow.phase.value,
                                "active_gate": workflow.active_gate.value,
                            },
                        )
                    )
        run.status = AgentRunStatus.CANCELLED
        run.paused_state = None
        run.error_code = None
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
        events.append(("run_cancelled", {"reason": reason}))
        self._append_agent_run_events(connection, run.id, events)
        return run

    def save_skill_plan(self, plan: SkillPlan) -> SkillPlan:
        plan.updated_at = now_utc()
        with self._connect() as connection:
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
            run_row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (plan.run_id,)).fetchone()
            if row is None or run_row is None:
                return False
            current = SkillPlan.model_validate_json(row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
            if (
                current.run_id != run.id
                or current.version != expected_version
                or current.status != SkillPlanStatus.WAITING_APPROVAL
                or plan.status != SkillPlanStatus.WAITING_APPROVAL
                or run.status != AgentRunStatus.WAITING_PLAN_APPROVAL
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
            run_row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if plan_row is None or run_row is None:
                return None
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
            if (
                plan.run_id != run.id
                or plan.version != expected_version
                or plan.status != expected_plan_status
                or run.status != expected_run_status
            ):
                return None
            now = now_utc()
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

    def claim_skill_plan_for_execution(self, plan_id: str, run_id: str) -> SkillPlan | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute("SELECT payload FROM skill_plans WHERE id = ?", (plan_id,)).fetchone()
            run_row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if plan_row is None or run_row is None:
                return None
            plan = SkillPlan.model_validate_json(plan_row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
            if plan.run_id != run.id or plan.status != SkillPlanStatus.APPROVED or run.status != AgentRunStatus.RUNNING:
                return None
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
            run_row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (plan.run_id,)).fetchone()
            if run_row is None:
                return None
            run = AgentRun.model_validate_json(run_row["payload"])
            node = SkillPlanNode.model_validate_json(node_row["payload"])
            if (
                plan.status != SkillPlanStatus.RUNNING
                or run.status != AgentRunStatus.RUNNING
                or node.status != SkillPlanNodeStatus.READY
                or node.attempt >= 2
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
            run_row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
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
                plan.run_id != run.id
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
            run_row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
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
                plan.run_id != run.id
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
            if not any(item.id == node.id for item in plan.nodes):
                return None
            plan.nodes = [node if item.id == node.id else item for item in plan.nodes]
            plan.updated_at = now_utc()
            self._write_skill_plan(connection, plan)
        return plan

    def save_skill_node_result(self, plan_id: str, result: SkillNodeResult) -> SkillNodeResult:
        with self._connect() as connection:
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

    def save_agent_run(self, run: AgentRun) -> AgentRun:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT orchestration_version FROM agent_runs WHERE id = ?",
                (run.id,),
            ).fetchone()
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
            row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
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

    def cancel_agent_run_tree(self, run_id: str, *, user_id: str) -> AgentRun | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
            if run.user_id != user_id:
                return None
            if run.status not in {
                AgentRunStatus.CREATED,
                AgentRunStatus.PLANNING,
                AgentRunStatus.RUNNING,
                AgentRunStatus.WAITING_PLAN_APPROVAL,
                AgentRunStatus.WAITING_APPROVAL,
            }:
                return run
            return self._cancel_agent_run_tree_in_transaction(connection, run, reason="run_cancelled")

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
            run_row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            inbox_row = connection.execute(
                "SELECT payload FROM records WHERE collection = 'inbox_items' AND id = ?",
                (inbox_id,),
            ).fetchone()
            if run_row is None or inbox_row is None:
                return False
            run = AgentRun.model_validate_json(run_row["payload"])
            item = InboxItem.model_validate_json(inbox_row["payload"])
            if (
                run.user_id != user_id
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
            self._cancel_agent_run_tree_in_transaction(connection, run, reason="approval_expired")
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
            row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run.id,)).fetchone()
            if row is None:
                return None
            current = AgentRun.model_validate_json(row["payload"])
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
            run_row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run.id,)).fetchone()
            if plan_row is None or run_row is None:
                return None
            current_plan = SkillPlan.model_validate_json(plan_row["payload"])
            current_run = AgentRun.model_validate_json(run_row["payload"])
            if (
                current_plan.run_id != current_run.id
                or current_plan.status not in expected_plan_statuses
                or current_run.status not in expected_run_statuses
            ):
                return None
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
            row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
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
    def _research_writer_control_from_row(row: sqlite3.Row | None) -> ResearchWriterControlV1:
        if row is None:
            raise ResearchStoreConflict("research writer control row is missing")
        try:
            return ResearchWriterControlV1(
                control_key=row["control_key"],
                active_generation=row["active_generation"],
                generation_epoch=row["generation_epoch"],
                decision_receipt_hash=row["decision_receipt_hash"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        except (TypeError, ValueError):
            raise ResearchStoreConflict("research writer control row failed integrity validation") from None

    @classmethod
    def _read_research_writer_control(cls, connection: sqlite3.Connection) -> ResearchWriterControlV1:
        row = connection.execute(
            "SELECT * FROM research_writer_control WHERE control_key = ?",
            (RESEARCH_WRITER_CONTROL_KEY,),
        ).fetchone()
        return cls._research_writer_control_from_row(row)

    def get_research_writer_control(self) -> ResearchWriterControlV1:
        with self._connect() as connection:
            return self._read_research_writer_control(connection)

    def compare_and_swap_research_writer_control(
        self,
        *,
        expected_generation: ResearchWriterGeneration,
        expected_generation_epoch: int,
        target_generation: ResearchWriterGeneration,
        decision_receipt_hash: str,
        changed_at: datetime | None = None,
    ) -> ResearchWriterControlV1:
        """Advance the global generation once; production exposes no caller for this in Gate 2."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._read_research_writer_control(connection)
            if (
                current.active_generation != expected_generation
                or current.generation_epoch != expected_generation_epoch
            ):
                raise ResearchStoreConflict("research writer generation compare-and-swap conflict")
            if current.active_generation == ResearchWriterGeneration.V3:
                raise ResearchStoreConflict("research-v3 writer generation cannot roll back to research-v2")
            if target_generation != ResearchWriterGeneration.V3:
                raise ResearchStoreConflict("research writer generation may advance only from v2 to v3")
            updated = ResearchWriterControlV1(
                active_generation=target_generation,
                generation_epoch=current.generation_epoch + 1,
                decision_receipt_hash=decision_receipt_hash,
                updated_at=changed_at or now_utc(),
            )
            cursor = connection.execute(
                """
                UPDATE research_writer_control
                SET active_generation = ?, generation_epoch = ?,
                    decision_receipt_hash = ?, updated_at = ?
                WHERE control_key = ? AND active_generation = ? AND generation_epoch = ?
                """,
                (
                    updated.active_generation.value,
                    updated.generation_epoch,
                    updated.decision_receipt_hash,
                    updated.updated_at.isoformat(),
                    RESEARCH_WRITER_CONTROL_KEY,
                    current.active_generation.value,
                    current.generation_epoch,
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchStoreConflict("research writer generation compare-and-swap conflict")
        return updated

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
            "SELECT payload FROM agent_runs WHERE id = ?",
            (receipt["run_id"],),
        ).fetchone()
        if row is None:
            raise RuntimeError("Agent run receipt points to a missing run")
        existing = AgentRun.model_validate_json(row["payload"])
        mode_conflict = (
            existing.requested_orchestration_mode is not None
            and run.requested_orchestration_mode is not None
            and existing.requested_orchestration_mode != run.requested_orchestration_mode
        )
        if (
            existing.input_text != run.input_text
            or existing.thread_id != run.thread_id
            or existing.workspace_id != run.workspace_id
            or existing.project_id != run.project_id
            or existing.skill_id != run.skill_id
            or existing.skill_name != run.skill_name
            or mode_conflict
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
            SELECT payload FROM agent_runs
            WHERE json_extract(payload, '$.user_id') = ?
              AND json_extract(payload, '$.thread_id') = ?
              AND json_extract(payload, '$.status') IN (?, ?, ?, ?, ?)
            """,
            (
                run.user_id,
                run.thread_id,
                AgentRunStatus.CREATED.value,
                AgentRunStatus.PLANNING.value,
                AgentRunStatus.RUNNING.value,
                AgentRunStatus.WAITING_PLAN_APPROVAL.value,
                AgentRunStatus.WAITING_APPROVAL.value,
            ),
        ).fetchall()
        checked_at = now_utc()
        for active_row in active_rows:
            active = AgentRun.model_validate_json(active_row["payload"])
            if (
                active.status == AgentRunStatus.WAITING_PLAN_APPROVAL
                and active.deadline_at is not None
                and checked_at >= active.deadline_at
            ):
                self._cancel_agent_run_tree_in_transaction(
                    connection,
                    active,
                    reason="plan_approval_expired",
                )
                continue
            if self._waiting_approval_expired(connection, active, checked_at=checked_at):
                self._cancel_agent_run_tree_in_transaction(
                    connection,
                    active,
                    reason="approval_expired",
                )
                continue
            raise RuntimeError("Another Agent run is already active for this thread")

    @staticmethod
    def _insert_agent_run_claim(connection: sqlite3.Connection, run: AgentRun) -> None:
        connection.execute(
            "INSERT INTO agent_runs(id, payload, updated_at, orchestration_version) VALUES (?, ?, ?, ?)",
            (run.id, run.model_dump_json(), run.updated_at.isoformat(), run.orchestration_version),
        )
        if run.client_turn_id:
            connection.execute(
                "INSERT INTO agent_run_receipts(user_id, client_turn_id, run_id) VALUES (?, ?, ?)",
                (run.user_id, run.client_turn_id, run.id),
            )

    def claim_new_agent_run(self, run: AgentRun) -> tuple[AgentRun, bool]:
        if not run.client_turn_id:
            return self.save_agent_run(run), True
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._replay_agent_run_claim(connection, run)
            if existing is not None:
                return existing, False
            self._require_agent_run_thread_available(connection, run)
            self._insert_agent_run_claim(connection, run)
        return run, True

    def claim_research_agent_run(
        self,
        run: AgentRun,
        *,
        expected_generation: ResearchWriterGeneration,
        expected_generation_epoch: int,
        initialize_version_state: ResearchVersionInitializer,
    ) -> tuple[AgentRun, bool]:
        """Claim a versioned research Run and its first version state in one transaction."""

        if not run.client_turn_id:
            raise ValueError("versioned research Run creation requires client_turn_id")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._replay_agent_run_claim(connection, run)
            if existing is not None:
                return existing, False
            control = self._read_research_writer_control(connection)
            if (
                control.active_generation != expected_generation
                or control.generation_epoch != expected_generation_epoch
                or run.orchestration_version != expected_generation.value
                or run.writer_generation_epoch != expected_generation_epoch
            ):
                raise ResearchStoreConflict("research writer generation changed before Run creation")
            self._require_agent_run_thread_available(connection, run)
            self._insert_agent_run_claim(connection, run)
            initialize_version_state(connection, run)
        return run, True

    def get_agent_run_by_client_turn(self, user_id: str, client_turn_id: str) -> AgentRun | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ar.payload
                FROM agent_run_receipts receipt
                JOIN agent_runs ar ON ar.id = receipt.run_id
                WHERE receipt.user_id = ? AND receipt.client_turn_id = ?
                """,
                (user_id, client_turn_id),
            ).fetchone()
        return AgentRun.model_validate_json(row["payload"]) if row is not None else None

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
            row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            run = AgentRun.model_validate_json(row["payload"])
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
                    self._cancel_agent_run_tree_in_transaction(connection, run, reason="approval_expired")
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
            run.updated_at = now_utc()
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), run.updated_at.isoformat(), run.id),
            )
        return run

    def reconcile_orphaned_agent_runs(self) -> int:
        reconciled = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT id, payload FROM agent_runs").fetchall()
            checked_at = now_utc()
            for row in rows:
                run = AgentRun.model_validate_json(row["payload"])
                if run.orchestration_version == "research-v2":
                    continue
                if run.status == AgentRunStatus.WAITING_PLAN_APPROVAL:
                    if run.deadline_at is not None and checked_at >= run.deadline_at:
                        self._cancel_agent_run_tree_in_transaction(
                            connection,
                            run,
                            reason="plan_approval_expired",
                        )
                        reconciled += 1
                    continue
                if run.status == AgentRunStatus.WAITING_APPROVAL:
                    if self._waiting_approval_expired(connection, run, checked_at=checked_at):
                        self._cancel_agent_run_tree_in_transaction(
                            connection,
                            run,
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
                if plan_row is not None:
                    plan = SkillPlan.model_validate_json(plan_row["payload"])
                    for node in plan.nodes:
                        if node.status in {SkillPlanNodeStatus.RUNNING, SkillPlanNodeStatus.READY}:
                            node.status = SkillPlanNodeStatus.FAILED
                            node.error_code = "process_restarted"
                            node.completed_at = now_utc()
                        elif node.status in {
                            SkillPlanNodeStatus.PENDING,
                            SkillPlanNodeStatus.WAITING_TOOL_APPROVAL,
                        }:
                            node.status = SkillPlanNodeStatus.CANCELLED
                            node.completed_at = now_utc()
                    plan.status = SkillPlanStatus.FAILED
                    plan.updated_at = now_utc()
                    self._write_skill_plan(connection, plan)
                run.status = AgentRunStatus.FAILED
                run.error_code = "process_restarted"
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
                    event_type="run_failed",
                    payload={"error_code": "process_restarted"},
                )
                connection.execute(
                    "INSERT INTO agent_run_events(run_id, sequence, id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (run.id, sequence, event.id, event.model_dump_json(), event.created_at.isoformat()),
                )
                reconciled += 1
        return reconciled

    def get_agent_run(self, run_id: str) -> AgentRun | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        return AgentRun.model_validate_json(row["payload"]) if row is not None else None

    def get_latest_research_run_for_thread(self, thread_id: str, user_id: str) -> AgentRun | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM agent_runs
                WHERE orchestration_version IN ('research-v2', 'research-v3')
                  AND json_extract(payload, '$.thread_id') = ?
                  AND json_extract(payload, '$.user_id') = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (thread_id, user_id),
            ).fetchone()
        return AgentRun.model_validate_json(row["payload"]) if row is not None else None

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
            rows = connection.execute("SELECT payload FROM agent_runs ORDER BY updated_at").fetchall()
        runs = [AgentRun.model_validate_json(row["payload"]) for row in rows]
        return [run for run in runs if user_id is None or run.user_id == user_id]

    def append_agent_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> AgentRunEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
    def _require_research_run(connection: sqlite3.Connection, run_id: str) -> AgentRun:
        row = connection.execute(
            "SELECT payload, orchestration_version FROM agent_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ResearchStoreConflict("research record requires an existing Agent run")
        run = AgentRun.model_validate_json(row["payload"])
        if run.orchestration_version != "research-v2" or row["orchestration_version"] != "research-v2":
            raise ResearchStoreConflict("research record requires a research-v2 Agent run")
        return run

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

    @staticmethod
    def _research_command_projection_matches(row: sqlite3.Row, receipt: ResearchCommandReceipt) -> bool:
        try:
            response_payload = json.loads(row["response_payload"])
        except (RecursionError, TypeError, ValueError):
            return False
        return bool(
            row["run_id"] == receipt.run_id
            and row["idempotency_key"] == receipt.idempotency_key
            and row["command_type"] == receipt.command_type
            and row["request_hash"] == receipt.request_hash
            and row["response_status"] == receipt.response_status
            and response_payload == receipt.response_payload
            and row["created_at"] == receipt.created_at.isoformat()
        )

    @staticmethod
    def _research_run_identity_matches(current: AgentRun, supplied: AgentRun) -> bool:
        immutable_fields = (
            "id",
            "thread_id",
            "user_id",
            "workspace_id",
            "project_id",
            "input_text",
            "client_turn_id",
            "skill_id",
            "skill_name",
            "orchestration_version",
            "orchestration_mode",
            "writer_generation_epoch",
            "requested_orchestration_mode",
            "agent_definition_version",
            "project_chat",
        )
        return all(getattr(current, field) == getattr(supplied, field) for field in immutable_fields)

    @staticmethod
    def _insert_research_requirement(
        connection: sqlite3.Connection,
        requirement: RequirementVersion,
    ) -> None:
        if canonical_sha256(requirement.payload) != requirement.content_hash:
            raise ResearchStoreConflict("research requirement content hash mismatch")
        if connection.execute(
            "SELECT 1 FROM research_requirement_versions WHERE id = ? OR (run_id = ? AND version = ?)",
            (requirement.id, requirement.run_id, requirement.version),
        ).fetchone() is not None:
            raise ResearchStoreConflict("requirement versions are immutable")
        connection.execute(
            """
            INSERT INTO research_requirement_versions(id, run_id, version, content_hash, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                requirement.id,
                requirement.run_id,
                requirement.version,
                requirement.content_hash,
                requirement.model_dump_json(),
                requirement.created_at.isoformat(),
            ),
        )

    @staticmethod
    def _insert_research_plan(
        connection: sqlite3.Connection,
        plan: ExecutionPlanVersion,
    ) -> None:
        if canonical_sha256(plan.payload) != plan.plan_hash:
            raise ResearchStoreConflict("research plan content hash mismatch")
        requirement_row = connection.execute(
            "SELECT run_id FROM research_requirement_versions WHERE id = ?",
            (plan.requirement_version_id,),
        ).fetchone()
        if requirement_row is None or requirement_row["run_id"] != plan.run_id:
            raise ResearchStoreConflict("research plan requires a requirement from the same run")
        if connection.execute(
            """
            SELECT 1 FROM research_plan_versions
            WHERE id = ? OR (run_id = ? AND (version = ? OR plan_hash = ?))
            """,
            (plan.id, plan.run_id, plan.version, plan.plan_hash),
        ).fetchone() is not None:
            raise ResearchStoreConflict("plan versions are immutable")
        connection.execute(
            """
            INSERT INTO research_plan_versions(
                id, run_id, requirement_version_id, version, plan_hash, payload, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan.id,
                plan.run_id,
                plan.requirement_version_id,
                plan.version,
                plan.plan_hash,
                plan.model_dump_json(),
                plan.created_at.isoformat(),
            ),
        )

    @staticmethod
    def _insert_research_attempt(connection: sqlite3.Connection, attempt: ExecutionAttempt) -> None:
        connection.execute(
            """
            INSERT INTO research_attempts(
                id, run_id, plan_version_id, attempt_number, status,
                lease_owner, lease_token, fencing_epoch, lease_expires_at,
                payload, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.id,
                attempt.run_id,
                attempt.plan_version_id,
                attempt.attempt_number,
                attempt.status.value,
                attempt.lease_owner,
                attempt.lease_token,
                attempt.fencing_epoch,
                attempt.lease_expires_at.isoformat() if attempt.lease_expires_at is not None else None,
                attempt.model_dump_json(),
                attempt.created_at.isoformat(),
                attempt.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def _insert_research_step(connection: sqlite3.Connection, step: ResearchStep) -> None:
        connection.execute(
            """
            INSERT INTO research_steps(
                attempt_id, step_number, status, claim_epoch,
                result_artifact_id, payload, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step.attempt_id,
                step.step_number,
                step.status.value,
                step.claim_epoch,
                step.result_artifact_id,
                step.model_dump_json(),
                step.updated_at.isoformat(),
            ),
        )

    def _load_research_workflow_context(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        owner: ResearchOwnerScope | None = None,
    ) -> WorkflowContext | None:
        from agentmesh.research_orchestration.workflow import WorkflowContext

        run_row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if run_row is None:
            return None
        try:
            run = AgentRun.model_validate_json(run_row["payload"])
        except (RecursionError, TypeError, ValueError):
            raise ResearchStoreConflict("research Agent run failed integrity verification") from None
        if not self._research_run_projection_matches(run_row, run) or run.orchestration_version != "research-v2":
            raise ResearchStoreConflict("research Agent run failed integrity verification")
        if owner is not None and (
            run.user_id != owner.user_id
            or run.workspace_id != owner.workspace_id
            or run.project_id != owner.project_id
        ):
            return None
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

    def ensure_workflow(self, run: AgentRun, workflow: ResearchWorkflow) -> WorkflowContext:
        if run.id != workflow.run_id or run.orchestration_version != "research-v2":
            raise ResearchStoreConflict("research workflow identity is invalid")
        if workflow.state_version != 1:
            raise ResearchStoreConflict("new research workflows must start at state_version 1")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run.id,)).fetchone()
            workflow_row = connection.execute(
                "SELECT 1 FROM research_workflows WHERE run_id = ?",
                (run.id,),
            ).fetchone()
            if workflow_row is not None:
                context = self._load_research_workflow_context(connection, run.id)
                if context is None or not self._research_run_identity_matches(context.run, run):
                    raise ResearchStoreConflict("research workflow identity conflicts with an existing run")
                return context

            writer_control = self._read_research_writer_control(connection)
            if writer_control.active_generation != ResearchWriterGeneration.V2 or (
                run.writer_generation_epoch is not None
                and run.writer_generation_epoch != writer_control.generation_epoch
            ):
                raise ResearchStoreConflict("research-v2 writer generation is fenced")
            effective_workflow = workflow.model_copy(
                update={"created_at": workflow.created_at, "updated_at": workflow.updated_at}
            )
            next_status = self._research_agent_run_status(effective_workflow)
            if next_status is None:
                raise ResearchStoreConflict("new research workflow cannot be terminal")
            if run_row is None:
                stored_run = run.model_copy(update={"status": next_status, "updated_at": effective_workflow.updated_at})
                connection.execute(
                    "INSERT INTO agent_runs(id, payload, updated_at, orchestration_version) VALUES (?, ?, ?, ?)",
                    (
                        stored_run.id,
                        stored_run.model_dump_json(),
                        stored_run.updated_at.isoformat(),
                        stored_run.orchestration_version,
                    ),
                )
            else:
                try:
                    current_run = AgentRun.model_validate_json(run_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("research Agent run failed integrity verification") from None
                if (
                    not self._research_run_projection_matches(run_row, current_run)
                    or not self._research_run_identity_matches(current_run, run)
                ):
                    raise ResearchStoreConflict("research workflow identity conflicts with an existing run")
                stored_run = current_run.model_copy(
                    update={"status": next_status, "updated_at": effective_workflow.updated_at}
                )
                connection.execute(
                    "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                    (stored_run.model_dump_json(), stored_run.updated_at.isoformat(), stored_run.id),
                )

            if stored_run.client_turn_id is not None:
                receipt_row = connection.execute(
                    """
                    SELECT user_id, client_turn_id, run_id FROM agent_run_receipts
                    WHERE (user_id = ? AND client_turn_id = ?) OR run_id = ?
                    """,
                    (stored_run.user_id, stored_run.client_turn_id, stored_run.id),
                ).fetchone()
                if receipt_row is None:
                    connection.execute(
                        "INSERT INTO agent_run_receipts(user_id, client_turn_id, run_id) VALUES (?, ?, ?)",
                        (stored_run.user_id, stored_run.client_turn_id, stored_run.id),
                    )
                elif (
                    receipt_row["user_id"] != stored_run.user_id
                    or receipt_row["client_turn_id"] != stored_run.client_turn_id
                    or receipt_row["run_id"] != stored_run.id
                ):
                    raise ResearchStoreConflict("research workflow identity conflicts with an existing receipt")

            self._validate_research_workflow_links(connection, effective_workflow)
            connection.execute(
                """
                INSERT INTO research_workflows(
                    run_id, phase, active_gate, active_requirement_version_id,
                    active_plan_version_id, active_attempt_id, state_version,
                    payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    effective_workflow.run_id,
                    effective_workflow.phase.value,
                    effective_workflow.active_gate.value,
                    effective_workflow.active_requirement_version_id,
                    effective_workflow.active_plan_version_id,
                    effective_workflow.active_attempt_id,
                    effective_workflow.state_version,
                    effective_workflow.model_dump_json(),
                    effective_workflow.created_at.isoformat(),
                    effective_workflow.updated_at.isoformat(),
                ),
            )
            if connection.execute(
                "SELECT 1 FROM agent_run_events WHERE run_id = ? LIMIT 1",
                (run.id,),
            ).fetchone() is None:
                self._append_agent_run_events(
                    connection,
                    run.id,
                    [("run_started", {"orchestration_version": "research-v2"})],
                )
            context = self._load_research_workflow_context(connection, run.id)
            if context is None:
                raise ResearchStoreConflict("research workflow creation failed integrity verification")
            return context

    def load_context(
        self,
        run_id: str,
        *,
        owner: ResearchOwnerScope,
    ) -> WorkflowContext | None:
        with self._connect() as connection:
            connection.execute("BEGIN")
            return self._load_research_workflow_context(connection, run_id, owner=owner)

    def replay_command(
        self,
        run_id: str,
        *,
        owner: ResearchOwnerScope,
        idempotency_key: str,
        command_type: ResearchCommandType,
        request_hash: str,
    ) -> ResearchCommandReceipt | None:
        with self._connect() as connection:
            connection.execute("BEGIN")
            if self._load_research_workflow_context(connection, run_id, owner=owner) is None:
                return None
            row = connection.execute(
                "SELECT * FROM research_commands WHERE run_id = ? AND idempotency_key = ?",
                (run_id, idempotency_key),
            ).fetchone()
            if row is None:
                return None
            try:
                receipt = ResearchCommandReceipt.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research command failed integrity verification") from None
            if not self._research_command_projection_matches(row, receipt):
                raise ResearchStoreConflict("research command failed integrity verification")
            if receipt.command_type != command_type or receipt.request_hash != request_hash:
                raise ResearchStoreConflict("idempotency key was used for a different research command")
            return receipt

    def publish_planning(self, mutation: PlanningMutation) -> WorkflowContext:
        if mutation.run_id != mutation.workflow.run_id:
            raise ResearchStoreConflict("research planning identity is invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._load_research_workflow_context(connection, mutation.run_id)
            if context is None:
                raise ResearchStoreConflict("research workflow does not exist")
            if context.workflow.state_version != mutation.expected_state_version:
                raise ResearchStoreConflict("research workflow state version conflict")
            if context.workflow.phase == ResearchPhase.TERMINAL:
                raise ResearchStoreConflict("terminal research workflow cannot be planned")

            requirement = mutation.requirement
            if requirement is not None:
                if requirement.run_id != mutation.run_id or requirement.version != len(context.requirements) + 1:
                    raise ResearchStoreConflict("research requirement lineage is invalid")
                self._insert_research_requirement(connection, requirement)
            plan = mutation.plan
            if plan is not None:
                expected_requirement_id = requirement.id if requirement is not None else mutation.workflow.active_requirement_version_id
                if (
                    plan.run_id != mutation.run_id
                    or plan.requirement_version_id != expected_requirement_id
                    or plan.version != len(context.plans) + 1
                ):
                    raise ResearchStoreConflict("research plan lineage is invalid")
                self._insert_research_plan(connection, plan)

            expected_requirement_id = requirement.id if requirement is not None else (
                context.active_requirement.id if context.active_requirement is not None else None
            )
            expected_plan_id = plan.id if plan is not None else (
                None
                if requirement is not None
                else (context.active_plan.id if context.active_plan is not None else None)
            )
            if mutation.workflow.active_requirement_version_id != expected_requirement_id:
                raise ResearchStoreConflict("active requirement does not match the planning mutation")
            if mutation.workflow.active_plan_version_id != expected_plan_id:
                raise ResearchStoreConflict("active plan does not match the planning mutation")

            updated_at = now_utc()
            updated = mutation.workflow.model_copy(
                update={
                    "state_version": mutation.expected_state_version + 1,
                    "created_at": context.workflow.created_at,
                    "updated_at": updated_at,
                }
            )
            self._validate_research_workflow_links(connection, updated)
            terminal_statuses = {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
                AgentRunStatus.FAILED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.CANCELLED,
            }
            if updated.phase == ResearchPhase.TERMINAL:
                if mutation.terminal_status not in terminal_statuses:
                    raise ResearchStoreConflict("terminal planning requires a terminal Agent run status")
                next_status = mutation.terminal_status
            else:
                if mutation.terminal_status is not None:
                    raise ResearchStoreConflict("non-terminal planning cannot set a terminal status")
                next_status = self._research_agent_run_status(updated)
                if next_status is None:
                    raise ResearchStoreConflict("research planning status is invalid")

            cursor = connection.execute(
                """
                UPDATE research_workflows
                SET phase = ?, active_gate = ?, active_requirement_version_id = ?,
                    active_plan_version_id = ?, active_attempt_id = ?, state_version = ?,
                    payload = ?, updated_at = ?
                WHERE run_id = ? AND state_version = ?
                """,
                (
                    updated.phase.value,
                    updated.active_gate.value,
                    updated.active_requirement_version_id,
                    updated.active_plan_version_id,
                    updated.active_attempt_id,
                    updated.state_version,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    updated.run_id,
                    mutation.expected_state_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchStoreConflict("research workflow state version conflict")
            run = context.run.model_copy(
                update={
                    "status": next_status,
                    "error_code": mutation.error_code,
                    "updated_at": updated_at,
                }
            )
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), updated_at.isoformat(), run.id),
            )
            events: list[tuple[str, dict[str, object]]] = [
                (
                    "research_updated",
                    {
                        "state_version": updated.state_version,
                        "phase": updated.phase.value,
                        "active_gate": updated.active_gate.value,
                    },
                )
            ]
            if updated.phase == ResearchPhase.TERMINAL:
                self._resolve_open_run_inboxes(
                    connection,
                    run.id,
                    reason=mutation.error_code or next_status.value,
                    resolved_at=updated_at,
                )
                events.append((f"run_{next_status.value}", {"error_code": mutation.error_code}))
            self._append_agent_run_events(connection, run.id, events)
            result = self._load_research_workflow_context(connection, mutation.run_id)
            if result is None:
                raise ResearchStoreConflict("research planning commit failed integrity verification")
            return result

    def commit_command(self, mutation: CommandMutation) -> CommandCommitResult:
        from agentmesh.research_orchestration.workflow import CommandCommitResult

        receipt = mutation.receipt
        if receipt.run_id != mutation.workflow.run_id:
            raise ResearchStoreConflict("research command identity is invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute(
                "SELECT * FROM research_commands WHERE run_id = ? AND idempotency_key = ?",
                (receipt.run_id, receipt.idempotency_key),
            ).fetchone()
            if existing_row is not None:
                try:
                    existing = ResearchCommandReceipt.model_validate_json(existing_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("research command failed integrity verification") from None
                if not self._research_command_projection_matches(existing_row, existing):
                    raise ResearchStoreConflict("research command failed integrity verification")
                if existing.command_type != receipt.command_type or existing.request_hash != receipt.request_hash:
                    raise ResearchStoreConflict("idempotency key was used for a different research command")
                replay_context = self._load_research_workflow_context(connection, receipt.run_id)
                if replay_context is None:
                    raise ResearchStoreConflict("research command points to a missing workflow")
                return CommandCommitResult(receipt=existing, context=replay_context, created=False)

            context = self._load_research_workflow_context(connection, receipt.run_id)
            if context is None:
                raise ResearchStoreConflict("research workflow does not exist")
            if context.workflow.state_version != mutation.expected_state_version:
                raise ResearchStoreConflict("research workflow state version conflict")
            if context.workflow.phase == ResearchPhase.TERMINAL:
                raise ResearchStoreConflict("terminal research workflow cannot accept commands")
            if (mutation.superseded_attempt_id is None) != (mutation.superseded_attempt_status is None):
                raise ResearchStoreConflict("superseded attempt identity and status must be set together")
            if (mutation.recovery_invocation_id is None) != (mutation.recovery_action is None):
                raise ResearchStoreConflict("recovery invocation and action must be set together")
            if receipt.command_type == "execute":
                if (
                    mutation.attempt is None
                    or mutation.superseded_attempt_id is not None
                    or mutation.recovery_invocation_id is not None
                    or mutation.terminal_status is not None
                ):
                    raise ResearchStoreConflict("execute command mutation is invalid")
            elif receipt.command_type == "recover":
                if mutation.approval_inbox is not None:
                    raise ResearchStoreConflict("recover command cannot create a Tool approval")
                if mutation.superseded_attempt_id is None or mutation.recovery_invocation_id is None:
                    raise ResearchStoreConflict("recover command mutation is invalid")
                if mutation.recovery_action == "retry" and (
                    mutation.attempt is None or mutation.terminal_status is not None
                ):
                    raise ResearchStoreConflict("recover retry command mutation is invalid")
                if mutation.recovery_action == "abort" and (
                    mutation.attempt is not None or mutation.terminal_status != AgentRunStatus.CANCELLED
                ):
                    raise ResearchStoreConflict("recover abort command mutation is invalid")
            elif any(
                (
                    mutation.attempt is not None,
                    bool(mutation.steps),
                    mutation.approval_inbox is not None,
                    mutation.superseded_attempt_id is not None,
                    mutation.recovery_invocation_id is not None,
                    mutation.terminal_status is not None,
                )
            ):
                raise ResearchStoreConflict("research command type does not match its mutation")

            completed_at = now_utc()
            approval_event: tuple[str, dict[str, object]] | None = None
            recovery_invocation: ToolInvocation | None = None
            if mutation.recovery_invocation_id is not None:
                invocation_row = connection.execute(
                    "SELECT * FROM research_tool_invocations WHERE id = ?",
                    (mutation.recovery_invocation_id,),
                ).fetchone()
                if invocation_row is None:
                    raise ResearchStoreConflict("recovery Tool invocation does not exist")
                try:
                    recovery_invocation = ToolInvocation.model_validate_json(invocation_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
                if not self._research_invocation_projection_matches(invocation_row, recovery_invocation):
                    raise ResearchStoreConflict("Tool invocation failed integrity verification")
                if (
                    context.active_attempt is None
                    or recovery_invocation.run_id != receipt.run_id
                    or recovery_invocation.plan_version_id != context.workflow.active_plan_version_id
                    or recovery_invocation.active_attempt_id != context.active_attempt.id
                    or recovery_invocation.state != InvocationState.UNKNOWN
                ):
                    raise ResearchStoreConflict("recovery Tool invocation is not the active unknown operation")
            if mutation.superseded_attempt_id is not None:
                if (
                    context.active_attempt is None
                    or context.active_attempt.id != mutation.superseded_attempt_id
                    or context.active_attempt.status != AttemptStatus.RECOVERY_REQUIRED
                    or mutation.superseded_attempt_status not in {AttemptStatus.FAILED, AttemptStatus.CANCELLED}
                ):
                    raise ResearchStoreConflict("superseded research attempt is invalid")
                superseded = context.active_attempt.model_copy(
                    update={
                        "status": mutation.superseded_attempt_status,
                        "lease_owner": None,
                        "lease_token": None,
                        "lease_expires_at": None,
                        "completed_at": completed_at,
                        "updated_at": completed_at,
                    }
                )
                cursor = connection.execute(
                    """
                    UPDATE research_attempts
                    SET status = ?, lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                        payload = ?, updated_at = ?
                    WHERE id = ? AND status = ? AND updated_at = ?
                    """,
                    (
                        superseded.status.value,
                        superseded.model_dump_json(),
                        superseded.updated_at.isoformat(),
                        context.active_attempt.id,
                        AttemptStatus.RECOVERY_REQUIRED.value,
                        context.active_attempt.updated_at.isoformat(),
                    ),
                )
                if cursor.rowcount != 1:
                    raise ResearchStoreConflict("superseded research attempt changed concurrently")
                for step in context.steps:
                    if step.status in {
                        StepStatus.COMPLETED,
                        StepStatus.FAILED,
                        StepStatus.SKIPPED,
                        StepStatus.CANCELLED,
                    }:
                        continue
                    cancelled_step = step.model_copy(
                        update={
                            "status": StepStatus.CANCELLED,
                            "result_artifact_id": None,
                            "error_code": "attempt_superseded",
                            "completed_at": completed_at,
                            "updated_at": completed_at,
                        }
                    )
                    cursor = connection.execute(
                        """
                        UPDATE research_steps
                        SET status = ?, result_artifact_id = NULL, payload = ?, updated_at = ?
                        WHERE attempt_id = ? AND step_number = ? AND status = ?
                          AND claim_epoch = ? AND updated_at = ?
                        """,
                        (
                            cancelled_step.status.value,
                            cancelled_step.model_dump_json(),
                            cancelled_step.updated_at.isoformat(),
                            step.attempt_id,
                            step.step_number,
                            step.status.value,
                            step.claim_epoch,
                            step.updated_at.isoformat(),
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ResearchStoreConflict("superseded research step changed concurrently")

            if mutation.attempt is not None:
                attempt = mutation.attempt
                if (
                    attempt.run_id != receipt.run_id
                    or context.active_plan is None
                    or attempt.plan_version_id != context.active_plan.id
                    or attempt.attempt_number != context.attempt_count + 1
                    or attempt.status != AttemptStatus.PENDING
                    or attempt.lease_owner is not None
                    or attempt.fencing_epoch != 0
                ):
                    raise ResearchStoreConflict("research attempt lineage is invalid")
                if attempt.attempt_number == 1 and attempt.retry_of_attempt_id is not None:
                    raise ResearchStoreConflict("the first research attempt cannot be a retry")
                if attempt.attempt_number > 1 and (
                    mutation.superseded_attempt_id is None
                    or attempt.retry_of_attempt_id != mutation.superseded_attempt_id
                    or mutation.superseded_attempt_status != AttemptStatus.FAILED
                ):
                    raise ResearchStoreConflict("retry attempt lineage is invalid")
                if mutation.workflow.active_attempt_id != attempt.id:
                    raise ResearchStoreConflict("active attempt does not match the command mutation")
                plan_steps = context.active_plan.payload.get("steps")
                if not isinstance(plan_steps, list) or len(plan_steps) != len(mutation.steps):
                    raise ResearchStoreConflict("research command steps do not match the active plan")
                expected_numbers = [item.get("step_number") for item in plan_steps if isinstance(item, dict)]
                if expected_numbers != [step.step_number for step in mutation.steps]:
                    raise ResearchStoreConflict("research command steps do not match the active plan")
                if any(step.attempt_id != attempt.id or step.claim_epoch != 0 for step in mutation.steps):
                    raise ResearchStoreConflict("research command step lineage is invalid")
                expected_statuses = [StepStatus.READY, *([StepStatus.PENDING] * (len(mutation.steps) - 1))]
                if [step.status for step in mutation.steps] != expected_statuses:
                    raise ResearchStoreConflict("research command step readiness is invalid")
                if receipt.command_type == "execute":
                    tool_step = plan_steps[0] if plan_steps and isinstance(plan_steps[0], dict) else None
                    approval_required = bool(tool_step and tool_step.get("approval_required"))
                    if approval_required != (mutation.workflow.active_gate == ResearchGate.TOOL_APPROVAL):
                        raise ResearchStoreConflict("research Tool approval gate does not match the frozen plan")
                    if approval_required != (mutation.approval_inbox is not None):
                        raise ResearchStoreConflict("research Tool approval Inbox does not match the frozen plan")
                    if mutation.approval_inbox is not None:
                        item = mutation.approval_inbox
                        expected_call_id = f"research-tool:{attempt.id}:{mutation.steps[0].step_number}"
                        if (
                            item.item_type != "research_tool_approval"
                            or item.status != "open"
                            or item.scope != Scope.PRIVATE
                            or item.user_id != context.run.user_id
                            or item.workspace_id != context.run.workspace_id
                            or item.project_id != context.run.project_id
                            or item.metadata.get("run_id") != receipt.run_id
                            or item.metadata.get("attempt_id") != attempt.id
                            or item.metadata.get("plan_version_id") != context.active_plan.id
                            or item.metadata.get("step_number") != str(mutation.steps[0].step_number)
                            or item.metadata.get("call_id") != expected_call_id
                        ):
                            raise ResearchStoreConflict("research Tool approval Inbox is invalid")
                self._insert_research_attempt(connection, attempt)
                for step in mutation.steps:
                    self._insert_research_step(connection, step)
                if mutation.approval_inbox is not None:
                    try:
                        connection.execute(
                            "INSERT INTO records(collection, id, payload) VALUES ('inbox_items', ?, ?)",
                            (mutation.approval_inbox.id, mutation.approval_inbox.model_dump_json()),
                        )
                    except sqlite3.IntegrityError as error:
                        raise ResearchStoreConflict("research Tool approval Inbox already exists") from error
                    approval_event = (
                        "approval_requested",
                        {
                            "inbox_item_id": mutation.approval_inbox.id,
                            "attempt_id": attempt.id,
                            "call_id": mutation.approval_inbox.metadata["call_id"],
                            "tool_name": mutation.approval_inbox.metadata["tool_name"],
                        },
                    )
                if recovery_invocation is not None:
                    rebound = ToolInvocation.model_validate(
                        recovery_invocation.model_copy(
                            update={
                                "active_attempt_id": attempt.id,
                                "state": InvocationState.PREPARED,
                                "sent_fencing_epoch": None,
                                "provider_operation_id": None,
                                "receipt": None,
                                "artifact_id": None,
                                "error_code": None,
                                "last_sent_at": None,
                                "acknowledged_at": None,
                                "unknown_at": None,
                                "updated_at": completed_at,
                            }
                        ).model_dump()
                    )
                    cursor = connection.execute(
                        """
                        UPDATE research_tool_invocations
                        SET active_attempt_id = ?, state = ?, sent_fencing_epoch = NULL,
                            receipt_payload = NULL, artifact_id = NULL, provider_operation_id = NULL,
                            last_sent_at = NULL, acknowledged_at = NULL, unknown_at = NULL,
                            payload = ?, updated_at = ?
                        WHERE id = ? AND state = ? AND active_attempt_id = ? AND updated_at = ?
                        """,
                        (
                            rebound.active_attempt_id,
                            rebound.state.value,
                            rebound.model_dump_json(),
                            rebound.updated_at.isoformat(),
                            recovery_invocation.id,
                            InvocationState.UNKNOWN.value,
                            recovery_invocation.active_attempt_id,
                            recovery_invocation.updated_at.isoformat(),
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ResearchStoreConflict("recovery Tool invocation changed concurrently")
                    self._append_agent_run_events(
                        connection,
                        receipt.run_id,
                        [
                            (
                                "research_tool_invocation_retry_authorized",
                                {
                                    "invocation_id": recovery_invocation.id,
                                    "operation_key": recovery_invocation.operation_key,
                                    "previous_attempt_id": recovery_invocation.active_attempt_id,
                                    "retry_attempt_id": attempt.id,
                                    "previous_send_sequence": recovery_invocation.active_send_sequence,
                                    "unknown_at": recovery_invocation.unknown_at.isoformat(),
                                },
                            )
                        ],
                    )
            elif mutation.steps:
                raise ResearchStoreConflict("research steps require a new attempt")

            updated = mutation.workflow.model_copy(
                update={
                    "state_version": mutation.expected_state_version + 1,
                    "created_at": context.workflow.created_at,
                    "updated_at": completed_at,
                }
            )
            if updated.active_requirement_version_id != context.workflow.active_requirement_version_id:
                raise ResearchStoreConflict("research commands cannot replace the active requirement")
            if updated.active_plan_version_id != context.workflow.active_plan_version_id:
                raise ResearchStoreConflict("research commands cannot replace the active plan")
            self._validate_research_workflow_links(connection, updated)
            terminal_statuses = {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
                AgentRunStatus.FAILED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.CANCELLED,
            }
            if updated.phase == ResearchPhase.TERMINAL:
                if mutation.terminal_status not in terminal_statuses:
                    raise ResearchStoreConflict("terminal command requires a terminal Agent run status")
                next_status = mutation.terminal_status
            else:
                if mutation.terminal_status is not None:
                    raise ResearchStoreConflict("non-terminal command cannot set a terminal status")
                next_status = self._research_agent_run_status(updated)
                if next_status is None:
                    raise ResearchStoreConflict("research command status is invalid")

            cursor = connection.execute(
                """
                UPDATE research_workflows
                SET phase = ?, active_gate = ?, active_requirement_version_id = ?,
                    active_plan_version_id = ?, active_attempt_id = ?, state_version = ?,
                    payload = ?, updated_at = ?
                WHERE run_id = ? AND state_version = ?
                """,
                (
                    updated.phase.value,
                    updated.active_gate.value,
                    updated.active_requirement_version_id,
                    updated.active_plan_version_id,
                    updated.active_attempt_id,
                    updated.state_version,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    updated.run_id,
                    mutation.expected_state_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchStoreConflict("research workflow state version conflict")
            run = context.run.model_copy(
                update={
                    "status": next_status,
                    "error_code": mutation.error_code,
                    "paused_state": None if updated.phase == ResearchPhase.TERMINAL else context.run.paused_state,
                    "updated_at": completed_at,
                }
            )
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), completed_at.isoformat(), run.id),
            )
            if updated.phase == ResearchPhase.TERMINAL:
                self._resolve_open_run_inboxes(
                    connection,
                    run.id,
                    reason=mutation.error_code or next_status.value,
                    resolved_at=completed_at,
                )
            self._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "research_updated",
                        {
                            "state_version": updated.state_version,
                            "phase": updated.phase.value,
                            "active_gate": updated.active_gate.value,
                        },
                    ),
                    *([approval_event] if approval_event is not None else []),
                    *(
                        [(f"run_{next_status.value}", {"error_code": mutation.error_code})]
                        if updated.phase == ResearchPhase.TERMINAL
                        else []
                    ),
                ],
            )
            connection.execute(
                """
                INSERT INTO research_commands(
                    run_id, idempotency_key, command_type, request_hash,
                    response_status, response_payload, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.run_id,
                    receipt.idempotency_key,
                    receipt.command_type,
                    receipt.request_hash,
                    receipt.response_status,
                    json.dumps(receipt.response_payload, ensure_ascii=False, separators=(",", ":")),
                    receipt.model_dump_json(),
                    receipt.created_at.isoformat(),
                ),
            )
            committed_context = self._load_research_workflow_context(connection, receipt.run_id)
            if committed_context is None:
                raise ResearchStoreConflict("research command commit failed integrity verification")
            return CommandCommitResult(receipt=receipt, context=committed_context, created=True)

    def create_research_workflow(self, workflow: ResearchWorkflow) -> ResearchWorkflow:
        if workflow.state_version != 1:
            raise ResearchStoreConflict("new research workflows must start at state_version 1")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = self._require_research_run(connection, workflow.run_id)
            self._validate_research_workflow_links(connection, workflow)
            try:
                connection.execute(
                    """
                    INSERT INTO research_workflows(
                        run_id, phase, active_gate, active_requirement_version_id,
                        active_plan_version_id, active_attempt_id, state_version,
                        payload, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow.run_id,
                        workflow.phase.value,
                        workflow.active_gate.value,
                        workflow.active_requirement_version_id,
                        workflow.active_plan_version_id,
                        workflow.active_attempt_id,
                        workflow.state_version,
                        workflow.model_dump_json(),
                        workflow.created_at.isoformat(),
                        workflow.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ResearchStoreConflict("research workflow already exists") from error
            next_status = self._research_agent_run_status(workflow)
            if next_status is not None:
                run.status = next_status
                run.updated_at = workflow.updated_at
                connection.execute(
                    "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                    (run.model_dump_json(), run.updated_at.isoformat(), run.id),
                )
        return workflow

    def get_research_workflow(self, run_id: str) -> ResearchWorkflow | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM research_workflows WHERE run_id = ?", (run_id,)).fetchone()
        return ResearchWorkflow.model_validate_json(row["payload"]) if row is not None else None

    def compare_and_swap_research_workflow(
        self,
        workflow: ResearchWorkflow,
        *,
        expected_state_version: int,
    ) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, state_version FROM research_workflows WHERE run_id = ?",
                (workflow.run_id,),
            ).fetchone()
            if row is None or row["state_version"] != expected_state_version:
                return False
            current = ResearchWorkflow.model_validate_json(row["payload"])
            run = self._require_research_run(connection, workflow.run_id)
            terminal_run_statuses = {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
                AgentRunStatus.FAILED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.CANCELLED,
            }
            if (
                current.phase == ResearchPhase.TERMINAL
                or workflow.phase == ResearchPhase.TERMINAL
                or run.status in terminal_run_statuses
            ):
                return False
            now = now_utc()
            updated = workflow.model_copy(
                update={
                    "state_version": expected_state_version + 1,
                    "created_at": current.created_at,
                    "updated_at": now,
                }
            )
            self._validate_research_workflow_links(connection, updated)
            cursor = connection.execute(
                """
                UPDATE research_workflows
                SET phase = ?, active_gate = ?, active_requirement_version_id = ?,
                    active_plan_version_id = ?, active_attempt_id = ?, state_version = ?,
                    payload = ?, updated_at = ?
                WHERE run_id = ? AND state_version = ?
                """,
                (
                    updated.phase.value,
                    updated.active_gate.value,
                    updated.active_requirement_version_id,
                    updated.active_plan_version_id,
                    updated.active_attempt_id,
                    updated.state_version,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    updated.run_id,
                    expected_state_version,
                ),
            )
            if cursor.rowcount != 1:
                return False
            next_status = self._research_agent_run_status(updated)
            if next_status is not None:
                run.status = next_status
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
                        "research_updated",
                        {
                            "state_version": updated.state_version,
                            "phase": updated.phase.value,
                            "active_gate": updated.active_gate.value,
                        },
                    )
                ],
            )
        workflow.state_version = updated.state_version
        workflow.created_at = updated.created_at
        workflow.updated_at = updated.updated_at
        return True

    def finish_research_workflow(
        self,
        run_id: str,
        *,
        expected_state_version: int,
        terminal_status: AgentRunStatus,
        error_code: str | None = None,
        output_text: str | None = None,
    ) -> tuple[ResearchWorkflow, AgentRun] | None:
        terminal_statuses = {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.PARTIAL,
            AgentRunStatus.FAILED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.CANCELLED,
        }
        if terminal_status not in terminal_statuses:
            raise ValueError("terminal_status must be an AgentRun terminal status")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, state_version FROM research_workflows WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None or row["state_version"] != expected_state_version:
                return None
            current = ResearchWorkflow.model_validate_json(row["payload"])
            run = self._require_research_run(connection, run_id)
            if current.phase == ResearchPhase.TERMINAL or run.status in terminal_statuses:
                return None
            now = now_utc()
            workflow = current.model_copy(
                update={
                    "phase": ResearchPhase.TERMINAL,
                    "active_gate": ResearchGate.NONE,
                    "state_version": expected_state_version + 1,
                    "updated_at": now,
                }
            )
            cursor = connection.execute(
                """
                UPDATE research_workflows
                SET phase = ?, active_gate = ?, state_version = ?, payload = ?, updated_at = ?
                WHERE run_id = ? AND state_version = ?
                """,
                (
                    workflow.phase.value,
                    workflow.active_gate.value,
                    workflow.state_version,
                    workflow.model_dump_json(),
                    now.isoformat(),
                    run_id,
                    expected_state_version,
                ),
            )
            if cursor.rowcount != 1:
                return None
            run.status = terminal_status
            run.error_code = error_code
            run.output_text = output_text
            run.paused_state = None
            run.updated_at = now
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), now.isoformat(), run.id),
            )
            self._resolve_open_run_inboxes(
                connection,
                run.id,
                reason=error_code or terminal_status.value,
                resolved_at=now,
            )
            self._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "research_updated",
                        {
                            "state_version": workflow.state_version,
                            "phase": workflow.phase.value,
                            "active_gate": workflow.active_gate.value,
                        },
                    ),
                    (f"run_{terminal_status.value}", {"error_code": error_code} if error_code else {}),
                ],
            )
        return workflow, run

    def _load_research_execution_terminal_context(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        attempt_id: str,
        lease: ExecutionLease,
        expected_state_version: int,
        completed_at: datetime,
    ) -> tuple[
        ResearchWorkflow,
        AgentRun,
        ExecutionAttempt,
        ExecutionPlanVersion,
        list[tuple[ResearchStep, dict[str, object]]],
    ] | None:
        workflow_row = connection.execute(
            "SELECT * FROM research_workflows WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if workflow_row is None or workflow_row["state_version"] != expected_state_version:
            return None
        run_row = connection.execute(
            "SELECT * FROM agent_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if run_row is None:
            return None
        try:
            workflow = ResearchWorkflow.model_validate_json(workflow_row["payload"])
            run = AgentRun.model_validate_json(run_row["payload"])
        except (RecursionError, TypeError, ValueError):
            raise ResearchStoreConflict("research execution state failed integrity verification") from None
        if (
            not self._research_workflow_projection_matches(workflow_row, workflow)
            or not self._research_run_projection_matches(run_row, run)
        ):
            raise ResearchStoreConflict("research execution state failed integrity verification")
        if (
            workflow.phase != ResearchPhase.EXECUTION
            or workflow.active_gate != ResearchGate.NONE
            or workflow.active_attempt_id != attempt_id
            or run.status != AgentRunStatus.RUNNING
            or run.orchestration_version != "research-v2"
            or run.orchestration_mode != "execute"
        ):
            return None
        attempt = self._live_research_attempt_for_lease(
            connection,
            attempt_id,
            lease=lease,
            now=completed_at,
        )
        if attempt is None or attempt.run_id != run_id:
            return None
        plan_row = connection.execute(
            "SELECT * FROM research_plan_versions WHERE id = ?",
            (attempt.plan_version_id,),
        ).fetchone()
        if plan_row is None:
            raise ResearchStoreConflict("research execution plan is missing")
        try:
            plan = ExecutionPlanVersion.model_validate_json(plan_row["payload"])
        except (RecursionError, TypeError, ValueError):
            raise ResearchStoreConflict("research execution plan failed integrity verification") from None
        if not self._research_plan_projection_matches(plan_row, plan):
            raise ResearchStoreConflict("research execution plan failed integrity verification")
        if (
            plan.run_id != run_id
            or workflow.active_plan_version_id != plan.id
            or workflow.active_requirement_version_id != plan.requirement_version_id
        ):
            raise ResearchStoreConflict("research execution lineage failed integrity verification")
        plan_steps = plan.payload.get("steps") if isinstance(plan.payload, dict) else None
        if not isinstance(plan_steps, list) or len(plan_steps) != 2:
            raise ResearchStoreConflict("research execution requires the frozen two-step plan")
        contracts: dict[int, dict[str, object]] = {}
        for item in plan_steps:
            if not isinstance(item, dict):
                raise ResearchStoreConflict("research execution plan step is invalid")
            step_number = item.get("step_number")
            actor_type = item.get("actor_type")
            if (
                isinstance(step_number, bool)
                or not isinstance(step_number, int)
                or step_number < 1
                or step_number in contracts
                or actor_type not in {"tool", "skill"}
            ):
                raise ResearchStoreConflict("research execution plan step is invalid")
            contracts[step_number] = item
        if {item.get("actor_type") for item in contracts.values()} != {"tool", "skill"}:
            raise ResearchStoreConflict("research execution requires one Tool and one Skill step")

        step_rows = connection.execute(
            "SELECT * FROM research_steps WHERE attempt_id = ? ORDER BY step_number",
            (attempt.id,),
        ).fetchall()
        if len(step_rows) != len(contracts) or {row["step_number"] for row in step_rows} != set(contracts):
            return None
        steps: list[tuple[ResearchStep, dict[str, object]]] = []
        for row in step_rows:
            try:
                step = ResearchStep.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research step failed integrity verification") from None
            if not self._research_step_projection_matches(row, step):
                raise ResearchStoreConflict("research step failed integrity verification")
            steps.append((step, contracts[step.step_number]))
        return workflow, run, attempt, plan, steps

    def _close_research_execution(
        self,
        connection: sqlite3.Connection,
        *,
        workflow: ResearchWorkflow,
        run: AgentRun,
        attempt: ExecutionAttempt,
        attempt_status: AttemptStatus,
        run_status: AgentRunStatus,
        error_code: str | None,
        output_text: str | None,
        completed_at: datetime,
    ) -> tuple[ResearchWorkflow, AgentRun]:
        closed_attempt = attempt.model_copy(
            update={
                "status": attempt_status,
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "completed_at": completed_at,
                "updated_at": completed_at,
            }
        )
        attempt_cursor = connection.execute(
            """
            UPDATE research_attempts
            SET status = ?, lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                payload = ?, updated_at = ?
            WHERE id = ? AND status = ? AND lease_owner = ? AND lease_token = ?
              AND fencing_epoch = ? AND lease_expires_at = ? AND updated_at = ?
            """,
            (
                closed_attempt.status.value,
                closed_attempt.model_dump_json(),
                completed_at.isoformat(),
                attempt.id,
                attempt.status.value,
                attempt.lease_owner,
                attempt.lease_token,
                attempt.fencing_epoch,
                attempt.lease_expires_at.isoformat() if attempt.lease_expires_at is not None else None,
                attempt.updated_at.isoformat(),
            ),
        )
        if attempt_cursor.rowcount != 1:
            raise ResearchStoreConflict("research attempt finish lost its compare-and-swap")

        closed_workflow = workflow.model_copy(
            update={
                "phase": ResearchPhase.TERMINAL,
                "active_gate": ResearchGate.NONE,
                "state_version": workflow.state_version + 1,
                "updated_at": completed_at,
            }
        )
        workflow_cursor = connection.execute(
            """
            UPDATE research_workflows
            SET phase = ?, active_gate = ?, state_version = ?, payload = ?, updated_at = ?
            WHERE run_id = ? AND state_version = ? AND updated_at = ?
            """,
            (
                closed_workflow.phase.value,
                closed_workflow.active_gate.value,
                closed_workflow.state_version,
                closed_workflow.model_dump_json(),
                completed_at.isoformat(),
                workflow.run_id,
                workflow.state_version,
                workflow.updated_at.isoformat(),
            ),
        )
        if workflow_cursor.rowcount != 1:
            raise ResearchStoreConflict("research workflow finish lost its compare-and-swap")

        closed_run = run.model_copy(
            update={
                "status": run_status,
                "error_code": error_code,
                "output_text": output_text,
                "paused_state": None,
                "updated_at": completed_at,
            }
        )
        run_cursor = connection.execute(
            """
            UPDATE agent_runs SET payload = ?, updated_at = ?
            WHERE id = ? AND orchestration_version = ? AND updated_at = ?
            """,
            (
                closed_run.model_dump_json(),
                completed_at.isoformat(),
                run.id,
                run.orchestration_version,
                run.updated_at.isoformat(),
            ),
        )
        if run_cursor.rowcount != 1:
            raise ResearchStoreConflict("Agent run finish lost its compare-and-swap")
        if run_status in {AgentRunStatus.COMPLETED, AgentRunStatus.PARTIAL} and output_text:
            receipt_row = connection.execute(
                """
                SELECT payload FROM research_model_call_receipts
                WHERE run_id = ? AND owner_kind = 'attempt' AND owner_id = ?
                  AND stage = 'competitive-analysis'
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (run.id, attempt.id),
            ).fetchone()
            receipt = (
                ModelCallReceipt.model_validate_json(receipt_row["payload"])
                if receipt_row is not None
                else None
            )
            message = ChatMessage(
                id=f"msg_research_{hashlib.sha256(run.id.encode()).hexdigest()[:24]}",
                thread_id=run.thread_id,
                role=ChatRole.ASSISTANT,
                content=output_text,
                scope=Scope.PRIVATE,
                workflow_trace=ChatWorkflowTrace(
                    intent=Intent.REQUEST_EXTERNAL_RESEARCH,
                    confidence=1.0,
                    source="skill",
                    selected_workflow="$competitive-analysis",
                    persisted=True,
                    llm_used=True,
                    requested_provider=receipt.requested_provider if receipt is not None else None,
                    actual_provider=receipt.actual_provider if receipt is not None else None,
                    requested_model=receipt.requested_model if receipt is not None else None,
                    actual_model=receipt.actual_model if receipt is not None else None,
                    provider_mode="real",
                ),
                created_at=completed_at,
            )
            existing_message = connection.execute(
                "SELECT payload FROM records WHERE collection = 'chat_messages' AND id = ?",
                (message.id,),
            ).fetchone()
            if existing_message is not None:
                if ChatMessage.model_validate_json(existing_message["payload"]) != message:
                    raise ResearchStoreConflict("research chat projection identity conflicts")
            else:
                connection.execute(
                    "INSERT INTO records(collection, id, payload) VALUES ('chat_messages', ?, ?)",
                    (message.id, message.model_dump_json()),
                )
                self._sync_fts(connection, "chat_messages", message)
            thread_row = connection.execute(
                "SELECT payload FROM records WHERE collection = 'chat_threads' AND id = ?",
                (run.thread_id,),
            ).fetchone()
            if thread_row is not None:
                thread = ChatThread.model_validate_json(thread_row["payload"])
                thread.updated_at = completed_at
                connection.execute(
                    "UPDATE records SET payload = ? WHERE collection = 'chat_threads' AND id = ?",
                    (thread.model_dump_json(), thread.id),
                )
        self._resolve_open_run_inboxes(
            connection,
            run.id,
            reason=error_code or run_status.value,
            resolved_at=completed_at,
        )
        self._append_agent_run_events(
            connection,
            run.id,
            [
                (
                    f"research_attempt_{attempt_status.value}",
                    {
                        "attempt_id": attempt.id,
                        "fencing_epoch": attempt.fencing_epoch,
                        **({"error_code": error_code} if error_code else {}),
                    },
                ),
                (
                    "research_updated",
                    {
                        "state_version": closed_workflow.state_version,
                        "phase": closed_workflow.phase.value,
                        "active_gate": closed_workflow.active_gate.value,
                    },
                ),
                (f"run_{run_status.value}", {"error_code": error_code} if error_code else {}),
            ],
        )
        return closed_workflow, closed_run

    def finish_research_execution(
        self,
        run_id: str,
        *,
        attempt_id: str,
        lease: ExecutionLease,
        expected_state_version: int,
        claim_ledger_artifact_id: str,
        deliverable_artifact_id: str,
        review_artifact_id: str,
        report_artifact_id: str | None = None,
        terminal_status: AgentRunStatus = AgentRunStatus.COMPLETED,
        output_text: str | None = None,
        completed_at: datetime,
    ) -> tuple[ResearchWorkflow, AgentRun] | None:
        if terminal_status not in {AgentRunStatus.COMPLETED, AgentRunStatus.PARTIAL}:
            raise ValueError("successful research execution must finish completed or partial")
        effective_completed_at = self._aware_research_time(completed_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._load_research_execution_terminal_context(
                connection,
                run_id,
                attempt_id=attempt_id,
                lease=lease,
                expected_state_version=expected_state_version,
                completed_at=effective_completed_at,
            )
            if context is None:
                return None
            workflow, run, attempt, plan, steps = context
            if any(step.status != StepStatus.COMPLETED for step, _contract in steps):
                return None
            for step, contract in steps:
                expected_kind = {
                    "tool": "tool_actor_output",
                    "skill": "skill_result",
                }[str(contract["actor_type"])]
                self._require_research_artifact(
                    connection,
                    step.result_artifact_id or "",
                    run_id=run_id,
                    requirement_version_id=plan.requirement_version_id,
                    plan_version_id=plan.id,
                    attempt_id=attempt.id,
                    step_number=step.step_number,
                    expected_kind=expected_kind,
                )
            skill_step = next(step for step, contract in steps if contract["actor_type"] == "skill")
            delivery_artifacts = [
                (claim_ledger_artifact_id, "claim_ledger"),
                (deliverable_artifact_id, "deliverable"),
                (review_artifact_id, "review"),
            ]
            if report_artifact_id is not None:
                delivery_artifacts.append((report_artifact_id, "report"))
            if len({artifact_id for artifact_id, _kind in delivery_artifacts}) != len(delivery_artifacts):
                raise ResearchStoreConflict("research delivery Artifact identities must be distinct")
            verified: dict[str, Artifact] = {}
            for artifact_id, kind in delivery_artifacts:
                verified[kind] = self._require_research_artifact(
                    connection,
                    artifact_id,
                    run_id=run_id,
                    requirement_version_id=plan.requirement_version_id,
                    plan_version_id=plan.id,
                    attempt_id=attempt.id,
                    step_number=skill_step.step_number,
                    expected_kind=kind,
                )
            try:
                review_payload = json.loads(verified["review"].content)
            except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research Review Artifact failed integrity verification") from None
            if not isinstance(review_payload, dict) or review_payload.get("status") != "pass":
                return None
            return self._close_research_execution(
                connection,
                workflow=workflow,
                run=run,
                attempt=attempt,
                attempt_status=AttemptStatus.COMPLETED,
                run_status=terminal_status,
                error_code=None,
                output_text=output_text,
                completed_at=effective_completed_at,
            )

    def fail_research_execution(
        self,
        run_id: str,
        *,
        attempt_id: str,
        lease: ExecutionLease,
        expected_state_version: int,
        error_code: str,
        completed_at: datetime,
        review_artifact_id: str | None = None,
    ) -> tuple[ResearchWorkflow, AgentRun] | None:
        if not error_code:
            raise ValueError("failed research execution requires an error code")
        effective_completed_at = self._aware_research_time(completed_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            context = self._load_research_execution_terminal_context(
                connection,
                run_id,
                attempt_id=attempt_id,
                lease=lease,
                expected_state_version=expected_state_version,
                completed_at=effective_completed_at,
            )
            if context is None:
                return None
            workflow, run, attempt, plan, steps = context
            statuses = {step.status for step, _contract in steps}
            if StepStatus.RUNNING in statuses:
                return None
            has_failed_step = StepStatus.FAILED in statuses
            review_blocked = False
            if not has_failed_step and statuses == {StepStatus.COMPLETED} and review_artifact_id is not None:
                skill_step = next(step for step, contract in steps if contract["actor_type"] == "skill")
                review = self._require_research_artifact(
                    connection,
                    review_artifact_id,
                    run_id=run_id,
                    requirement_version_id=plan.requirement_version_id,
                    plan_version_id=plan.id,
                    attempt_id=attempt.id,
                    step_number=skill_step.step_number,
                    expected_kind="review",
                )
                try:
                    review_payload = json.loads(review.content)
                except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("research Review Artifact failed integrity verification") from None
                review_blocked = isinstance(review_payload, dict) and review_payload.get("status") == "block"
            if not has_failed_step and not review_blocked:
                return None
            return self._close_research_execution(
                connection,
                workflow=workflow,
                run=run,
                attempt=attempt,
                attempt_status=AttemptStatus.FAILED,
                run_status=AgentRunStatus.FAILED,
                error_code=error_code,
                output_text=None,
                completed_at=effective_completed_at,
            )

    def add_research_requirement_version(self, requirement: RequirementVersion) -> RequirementVersion:
        if canonical_sha256(requirement.payload) != requirement.content_hash:
            raise ResearchStoreConflict("research requirement content hash mismatch")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_research_run(connection, requirement.run_id)
            try:
                connection.execute(
                    """
                    INSERT INTO research_requirement_versions(id, run_id, version, content_hash, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requirement.id,
                        requirement.run_id,
                        requirement.version,
                        requirement.content_hash,
                        requirement.model_dump_json(),
                        requirement.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ResearchStoreConflict("requirement versions are immutable") from error
        return requirement

    def get_research_requirement_version(self, requirement_id: str) -> RequirementVersion | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash, payload FROM research_requirement_versions WHERE id = ?",
                (requirement_id,),
            ).fetchone()
        if row is None:
            return None
        requirement = RequirementVersion.model_validate_json(row["payload"])
        if row["content_hash"] != requirement.content_hash or canonical_sha256(requirement.payload) != requirement.content_hash:
            raise ResearchStoreConflict("stored research requirement failed integrity verification")
        return requirement

    def list_research_requirement_versions(self, run_id: str) -> list[RequirementVersion]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT content_hash, payload FROM research_requirement_versions WHERE run_id = ? ORDER BY version",
                (run_id,),
            ).fetchall()
        requirements = [RequirementVersion.model_validate_json(row["payload"]) for row in rows]
        if any(
            row["content_hash"] != requirement.content_hash
            or canonical_sha256(requirement.payload) != requirement.content_hash
            for row, requirement in zip(rows, requirements, strict=True)
        ):
            raise ResearchStoreConflict("stored research requirement failed integrity verification")
        return requirements

    def add_research_plan_version(self, plan: ExecutionPlanVersion) -> ExecutionPlanVersion:
        if canonical_sha256(plan.payload) != plan.plan_hash:
            raise ResearchStoreConflict("research plan content hash mismatch")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_research_run(connection, plan.run_id)
            requirement_row = connection.execute(
                "SELECT run_id FROM research_requirement_versions WHERE id = ?",
                (plan.requirement_version_id,),
            ).fetchone()
            if requirement_row is None or requirement_row["run_id"] != plan.run_id:
                raise ResearchStoreConflict("research plan requires a requirement from the same run")
            try:
                connection.execute(
                    """
                    INSERT INTO research_plan_versions(
                        id, run_id, requirement_version_id, version, plan_hash, payload, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.id,
                        plan.run_id,
                        plan.requirement_version_id,
                        plan.version,
                        plan.plan_hash,
                        plan.model_dump_json(),
                        plan.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ResearchStoreConflict("plan versions are immutable") from error
        return plan

    def get_research_plan_version(self, plan_id: str) -> ExecutionPlanVersion | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT plan_hash, payload FROM research_plan_versions WHERE id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        plan = ExecutionPlanVersion.model_validate_json(row["payload"])
        if row["plan_hash"] != plan.plan_hash or canonical_sha256(plan.payload) != plan.plan_hash:
            raise ResearchStoreConflict("stored research plan failed integrity verification")
        return plan

    def list_research_plan_versions(self, run_id: str) -> list[ExecutionPlanVersion]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT plan_hash, payload FROM research_plan_versions WHERE run_id = ? ORDER BY version",
                (run_id,),
            ).fetchall()
        plans = [ExecutionPlanVersion.model_validate_json(row["payload"]) for row in rows]
        if any(
            row["plan_hash"] != plan.plan_hash or canonical_sha256(plan.payload) != plan.plan_hash
            for row, plan in zip(rows, plans, strict=True)
        ):
            raise ResearchStoreConflict("stored research plan failed integrity verification")
        return plans

    def apply_research_workflow_command(
        self,
        receipt: ResearchCommandReceipt,
        workflow: ResearchWorkflow,
        *,
        expected_state_version: int,
    ) -> tuple[ResearchCommandReceipt, ResearchWorkflow, bool]:
        if receipt.run_id != workflow.run_id:
            raise ResearchStoreConflict("research command and workflow must belong to the same run")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM research_commands WHERE run_id = ? AND idempotency_key = ?",
                (receipt.run_id, receipt.idempotency_key),
            ).fetchone()
            if row is not None:
                existing = ResearchCommandReceipt.model_validate_json(row["payload"])
                if existing.request_hash != receipt.request_hash or existing.command_type != receipt.command_type:
                    raise ResearchStoreConflict("idempotency key was used for a different research command")
                current = connection.execute(
                    "SELECT payload FROM research_workflows WHERE run_id = ?",
                    (receipt.run_id,),
                ).fetchone()
                if current is None:
                    raise ResearchStoreConflict("research command points to a missing workflow")
                return existing, ResearchWorkflow.model_validate_json(current["payload"]), False
            workflow_row = connection.execute(
                "SELECT payload, state_version FROM research_workflows WHERE run_id = ?",
                (receipt.run_id,),
            ).fetchone()
            if workflow_row is None or workflow_row["state_version"] != expected_state_version:
                raise ResearchStoreConflict("research workflow state version conflict")
            current = ResearchWorkflow.model_validate_json(workflow_row["payload"])
            run = self._require_research_run(connection, receipt.run_id)
            terminal_statuses = {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.PARTIAL,
                AgentRunStatus.FAILED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.CANCELLED,
            }
            if (
                current.phase == ResearchPhase.TERMINAL
                or workflow.phase == ResearchPhase.TERMINAL
                or run.status in terminal_statuses
            ):
                raise ResearchStoreConflict("terminal research workflow cannot accept commands")
            now = now_utc()
            updated = workflow.model_copy(
                update={
                    "state_version": expected_state_version + 1,
                    "created_at": current.created_at,
                    "updated_at": now,
                }
            )
            self._validate_research_workflow_links(connection, updated)
            cursor = connection.execute(
                """
                UPDATE research_workflows
                SET phase = ?, active_gate = ?, active_requirement_version_id = ?,
                    active_plan_version_id = ?, active_attempt_id = ?, state_version = ?,
                    payload = ?, updated_at = ?
                WHERE run_id = ? AND state_version = ?
                """,
                (
                    updated.phase.value,
                    updated.active_gate.value,
                    updated.active_requirement_version_id,
                    updated.active_plan_version_id,
                    updated.active_attempt_id,
                    updated.state_version,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    updated.run_id,
                    expected_state_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchStoreConflict("research workflow state version conflict")
            next_status = self._research_agent_run_status(updated)
            if next_status is None:
                raise ResearchStoreConflict("terminal workflow requires finish_research_workflow")
            run.status = next_status
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
                        "research_updated",
                        {
                            "state_version": updated.state_version,
                            "phase": updated.phase.value,
                            "active_gate": updated.active_gate.value,
                        },
                    )
                ],
            )
            connection.execute(
                """
                INSERT INTO research_commands(
                    run_id, idempotency_key, command_type, request_hash,
                    response_status, response_payload, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.run_id,
                    receipt.idempotency_key,
                    receipt.command_type,
                    receipt.request_hash,
                    receipt.response_status,
                    json.dumps(receipt.response_payload, ensure_ascii=False, separators=(",", ":")),
                    receipt.model_dump_json(),
                    receipt.created_at.isoformat(),
                ),
            )
        workflow.state_version = updated.state_version
        workflow.created_at = updated.created_at
        workflow.updated_at = updated.updated_at
        return receipt, updated, True

    def add_research_attempt(self, attempt: ExecutionAttempt) -> ExecutionAttempt:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_research_run(connection, attempt.run_id)
            plan_row = connection.execute(
                "SELECT run_id FROM research_plan_versions WHERE id = ?",
                (attempt.plan_version_id,),
            ).fetchone()
            if plan_row is None or plan_row["run_id"] != attempt.run_id:
                raise ResearchStoreConflict("research attempt requires a plan from the same run")
            if attempt.attempt_number == 1 and attempt.retry_of_attempt_id is not None:
                raise ResearchStoreConflict("the first research attempt cannot be a retry")
            if attempt.attempt_number > 1:
                prior = connection.execute(
                    "SELECT run_id, plan_version_id, attempt_number, status FROM research_attempts WHERE id = ?",
                    (attempt.retry_of_attempt_id,),
                ).fetchone()
                if (
                    prior is None
                    or prior["run_id"] != attempt.run_id
                    or prior["plan_version_id"] != attempt.plan_version_id
                    or prior["attempt_number"] != attempt.attempt_number - 1
                    or prior["status"] not in {"completed", "failed", "cancelled"}
                ):
                    raise ResearchStoreConflict("retry attempt lineage is invalid")
            try:
                connection.execute(
                    """
                    INSERT INTO research_attempts(
                        id, run_id, plan_version_id, attempt_number, status,
                        lease_owner, lease_token, fencing_epoch, lease_expires_at,
                        payload, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt.id,
                        attempt.run_id,
                        attempt.plan_version_id,
                        attempt.attempt_number,
                        attempt.status.value,
                        attempt.lease_owner,
                        attempt.lease_token,
                        attempt.fencing_epoch,
                        attempt.lease_expires_at.isoformat() if attempt.lease_expires_at is not None else None,
                        attempt.model_dump_json(),
                        attempt.created_at.isoformat(),
                        attempt.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ResearchStoreConflict("research attempt already exists") from error
        return attempt

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

    @staticmethod
    def _aware_research_time(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("research execution timestamps must be timezone-aware")
        return value

    def _live_research_attempt_for_lease(
        self,
        connection: sqlite3.Connection,
        attempt_id: str,
        *,
        lease: ExecutionLease,
        now: datetime,
        require_gate_none: bool = True,
        allow_off: bool = False,
    ) -> ExecutionAttempt | None:
        row = connection.execute(
            """
            SELECT a.*, w.phase AS workflow_phase, w.active_gate AS workflow_gate,
                   w.active_attempt_id AS workflow_attempt_id, w.payload AS workflow_payload,
                   r.payload AS run_payload, r.orchestration_version AS run_orchestration_version
            FROM research_attempts a
            JOIN research_workflows w ON w.run_id = a.run_id
            JOIN agent_runs r ON r.id = a.run_id
            WHERE a.id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            attempt = ExecutionAttempt.model_validate_json(row["payload"])
            workflow = ResearchWorkflow.model_validate_json(row["workflow_payload"])
            run = AgentRun.model_validate_json(row["run_payload"])
        except (RecursionError, TypeError, ValueError):
            raise ResearchStoreConflict("research execution state failed integrity verification") from None
        if (
            not self._research_attempt_projection_matches(row, attempt)
            or workflow.phase.value != row["workflow_phase"]
            or workflow.active_gate.value != row["workflow_gate"]
            or workflow.active_attempt_id != row["workflow_attempt_id"]
            or run.orchestration_version != row["run_orchestration_version"]
        ):
            raise ResearchStoreConflict("research execution state failed integrity verification")
        if (
            attempt.status != AttemptStatus.RUNNING
            or attempt.lease_owner != lease.owner
            or attempt.lease_token != lease.token
            or attempt.fencing_epoch != lease.fencing_epoch
            or attempt.lease_expires_at is None
            or attempt.lease_expires_at <= now
            or workflow.phase != ResearchPhase.EXECUTION
            or workflow.active_attempt_id != attempt.id
            or (require_gate_none and workflow.active_gate != ResearchGate.NONE)
            or run.status != AgentRunStatus.RUNNING
            or run.orchestration_version != "research-v2"
            or (not allow_off and run.orchestration_mode != "execute")
        ):
            return None
        return attempt

    def claim_research_attempt(
        self,
        attempt_id: str,
        *,
        owner: str,
        token: str,
        now: datetime,
        lease_ttl: timedelta = timedelta(seconds=60),
    ) -> ExecutionAttempt | None:
        checked_at = self._aware_research_time(now)
        if not owner or not token or lease_ttl <= timedelta(0):
            raise ValueError("attempt claim requires owner, token, and a positive lease TTL")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT a.*, w.phase AS workflow_phase, w.active_gate AS workflow_gate,
                       w.active_attempt_id AS workflow_attempt_id, w.payload AS workflow_payload,
                       r.payload AS run_payload, r.orchestration_version AS run_orchestration_version
                FROM research_attempts a
                JOIN research_workflows w ON w.run_id = a.run_id
                JOIN agent_runs r ON r.id = a.run_id
                WHERE a.id = ?
                """,
                (attempt_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                current = ExecutionAttempt.model_validate_json(row["payload"])
                workflow = ResearchWorkflow.model_validate_json(row["workflow_payload"])
                run = AgentRun.model_validate_json(row["run_payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research execution state failed integrity verification") from None
            if (
                not self._research_attempt_projection_matches(row, current)
                or workflow.phase.value != row["workflow_phase"]
                or workflow.active_gate.value != row["workflow_gate"]
                or workflow.active_attempt_id != row["workflow_attempt_id"]
                or run.orchestration_version != row["run_orchestration_version"]
            ):
                raise ResearchStoreConflict("research execution state failed integrity verification")
            if (
                workflow.phase != ResearchPhase.EXECUTION
                or workflow.active_gate != ResearchGate.NONE
                or workflow.active_attempt_id != current.id
                or run.status != AgentRunStatus.RUNNING
                or run.orchestration_version != "research-v2"
                or run.orchestration_mode != "execute"
                or current.deadline_at <= checked_at
            ):
                return None
            if (
                current.status == AttemptStatus.RUNNING
                and current.lease_owner == owner
                and current.lease_token == token
                and current.lease_expires_at is not None
                and current.lease_expires_at > checked_at
            ):
                return current
            pending = current.status == AttemptStatus.PENDING
            expired = (
                current.status == AttemptStatus.RUNNING
                and current.lease_expires_at is not None
                and current.lease_expires_at <= checked_at
            )
            if not pending and not expired:
                return None
            expires_at = min(checked_at + lease_ttl, current.deadline_at)
            if expires_at <= checked_at:
                return None
            claimed = current.model_copy(
                update={
                    "status": AttemptStatus.RUNNING,
                    "lease_owner": owner,
                    "lease_token": token,
                    "fencing_epoch": current.fencing_epoch + 1,
                    "lease_expires_at": expires_at,
                    "updated_at": checked_at,
                }
            )
            cursor = connection.execute(
                """
                UPDATE research_attempts
                SET status = ?, lease_owner = ?, lease_token = ?, fencing_epoch = ?,
                    lease_expires_at = ?, payload = ?, updated_at = ?
                WHERE id = ? AND status = ? AND fencing_epoch = ?
                  AND COALESCE(lease_owner, '') = COALESCE(?, '')
                  AND COALESCE(lease_token, '') = COALESCE(?, '')
                  AND COALESCE(lease_expires_at, '') = COALESCE(?, '')
                """,
                (
                    claimed.status.value,
                    claimed.lease_owner,
                    claimed.lease_token,
                    claimed.fencing_epoch,
                    claimed.lease_expires_at.isoformat(),
                    claimed.model_dump_json(),
                    checked_at.isoformat(),
                    claimed.id,
                    current.status.value,
                    current.fencing_epoch,
                    current.lease_owner,
                    current.lease_token,
                    current.lease_expires_at.isoformat() if current.lease_expires_at is not None else None,
                ),
            )
            if cursor.rowcount != 1:
                return None
            takeover_events: list[tuple[str, dict[str, object]]] = []
            if expired:
                invocation_rows = connection.execute(
                    """
                    SELECT * FROM research_tool_invocations
                    WHERE active_attempt_id = ? AND state = ?
                    ORDER BY id
                    """,
                    (claimed.id, InvocationState.SENT.value),
                ).fetchall()
                for invocation_row in invocation_rows:
                    try:
                        invocation = ToolInvocation.model_validate_json(invocation_row["payload"])
                    except (RecursionError, TypeError, ValueError):
                        raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
                    if not self._research_invocation_projection_matches(invocation_row, invocation):
                        raise ResearchStoreConflict("Tool invocation failed integrity verification")
                    unknown = invocation.model_copy(
                        update={
                            "state": InvocationState.UNKNOWN,
                            "unknown_at": checked_at,
                            "error_code": "provider_result_unknown",
                            "updated_at": checked_at,
                        }
                    )
                    invocation_cursor = connection.execute(
                        """
                        UPDATE research_tool_invocations
                        SET state = ?, unknown_at = ?, payload = ?, updated_at = ?
                        WHERE id = ? AND state = ? AND active_attempt_id = ?
                          AND active_send_sequence = ? AND sent_fencing_epoch = ?
                          AND updated_at = ?
                        """,
                        (
                            unknown.state.value,
                            checked_at.isoformat(),
                            unknown.model_dump_json(),
                            checked_at.isoformat(),
                            invocation.id,
                            InvocationState.SENT.value,
                            claimed.id,
                            invocation.active_send_sequence,
                            invocation.sent_fencing_epoch,
                            invocation.updated_at.isoformat(),
                        ),
                    )
                    if invocation_cursor.rowcount != 1:
                        raise ResearchStoreConflict("Tool invocation takeover lost its compare-and-swap")
                    takeover_events.append(
                        (
                            "research_tool_invocation_unknown",
                            {
                                "invocation_id": invocation.id,
                                "send_sequence": invocation.active_send_sequence,
                                "reason": "attempt_takeover",
                            },
                        )
                    )
            self._append_agent_run_events(
                connection,
                claimed.run_id,
                [
                    (
                        "research_attempt_claimed",
                        {
                            "attempt_id": claimed.id,
                            "fencing_epoch": claimed.fencing_epoch,
                            "takeover": expired,
                        },
                    ),
                    *takeover_events,
                ],
            )
        return claimed

    def heartbeat_research_attempt(
        self,
        attempt_id: str,
        *,
        lease: ExecutionLease,
        now: datetime,
        lease_ttl: timedelta = timedelta(seconds=60),
    ) -> ExecutionAttempt | None:
        checked_at = self._aware_research_time(now)
        if lease_ttl <= timedelta(0):
            raise ValueError("attempt heartbeat requires a positive lease TTL")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._live_research_attempt_for_lease(
                connection,
                attempt_id,
                lease=lease,
                now=checked_at,
                allow_off=True,
            )
            if current is None or current.deadline_at <= checked_at:
                return None
            expires_at = min(checked_at + lease_ttl, current.deadline_at)
            if expires_at <= checked_at:
                return None
            updated = current.model_copy(update={"lease_expires_at": expires_at, "updated_at": checked_at})
            cursor = connection.execute(
                """
                UPDATE research_attempts
                SET lease_expires_at = ?, payload = ?, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ? AND lease_token = ?
                  AND fencing_epoch = ? AND lease_expires_at = ?
                """,
                (
                    expires_at.isoformat(),
                    updated.model_dump_json(),
                    checked_at.isoformat(),
                    current.id,
                    AttemptStatus.RUNNING.value,
                    lease.owner,
                    lease.token,
                    lease.fencing_epoch,
                    current.lease_expires_at.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                return None
        return updated

    def get_research_attempt(self, attempt_id: str) -> ExecutionAttempt | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM research_attempts WHERE id = ?", (attempt_id,)).fetchone()
        return ExecutionAttempt.model_validate_json(row["payload"]) if row is not None else None

    def list_expired_research_attempt_ids(self, now: datetime) -> list[str]:
        checked_at = self._aware_research_time(now)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM research_attempts
                WHERE status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?
                ORDER BY lease_expires_at, id
                """,
                (AttemptStatus.RUNNING.value, checked_at.isoformat()),
            ).fetchall()
            expired: list[str] = []
            for row in rows:
                try:
                    attempt = ExecutionAttempt.model_validate_json(row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("research attempt failed integrity verification") from None
                if not self._research_attempt_projection_matches(row, attempt):
                    raise ResearchStoreConflict("research attempt failed integrity verification")
                if (
                    attempt.status != AttemptStatus.RUNNING
                    or attempt.lease_expires_at is None
                    or attempt.lease_expires_at > checked_at
                    or attempt.deadline_at <= checked_at
                ):
                    continue
                workflow_row = connection.execute(
                    "SELECT * FROM research_workflows WHERE run_id = ?",
                    (attempt.run_id,),
                ).fetchone()
                run_row = connection.execute(
                    "SELECT * FROM agent_runs WHERE id = ?",
                    (attempt.run_id,),
                ).fetchone()
                if workflow_row is None or run_row is None:
                    continue
                try:
                    workflow = ResearchWorkflow.model_validate_json(workflow_row["payload"])
                    run = AgentRun.model_validate_json(run_row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("research execution state failed integrity verification") from None
                if (
                    not self._research_workflow_projection_matches(workflow_row, workflow)
                    or not self._research_run_projection_matches(run_row, run)
                ):
                    raise ResearchStoreConflict("research execution state failed integrity verification")
                if (
                    workflow.phase != ResearchPhase.EXECUTION
                    or workflow.active_gate != ResearchGate.NONE
                    or workflow.active_attempt_id != attempt.id
                    or workflow.active_plan_version_id != attempt.plan_version_id
                    or run.id != attempt.run_id
                    or run.status != AgentRunStatus.RUNNING
                    or run.orchestration_version != "research-v2"
                    or run.orchestration_mode != "execute"
                ):
                    continue
                expired.append(attempt.id)
        return expired

    def list_recoverable_research_attempt_ids(self, now: datetime) -> list[str]:
        """List PENDING and lease-expired attempts that may be claimed safely."""

        checked_at = self._aware_research_time(now)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT a.*, w.payload AS workflow_payload, r.payload AS run_payload,
                       w.phase AS workflow_phase, w.active_gate AS workflow_gate,
                       w.active_attempt_id AS workflow_attempt_id,
                       r.orchestration_version AS run_orchestration_version
                FROM research_attempts a
                JOIN research_workflows w ON w.run_id = a.run_id
                JOIN agent_runs r ON r.id = a.run_id
                WHERE a.status IN (?, ?)
                ORDER BY a.created_at, a.id
                """,
                (AttemptStatus.PENDING.value, AttemptStatus.RUNNING.value),
            ).fetchall()
        eligible: list[str] = []
        for row in rows:
            try:
                attempt = ExecutionAttempt.model_validate_json(row["payload"])
                workflow = ResearchWorkflow.model_validate_json(row["workflow_payload"])
                run = AgentRun.model_validate_json(row["run_payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research execution state failed integrity verification") from None
            if (
                not self._research_attempt_projection_matches(row, attempt)
                or workflow.phase.value != row["workflow_phase"]
                or workflow.active_gate.value != row["workflow_gate"]
                or workflow.active_attempt_id != row["workflow_attempt_id"]
                or run.orchestration_version != row["run_orchestration_version"]
            ):
                raise ResearchStoreConflict("research execution state failed integrity verification")
            pending = attempt.status == AttemptStatus.PENDING
            expired = (
                attempt.status == AttemptStatus.RUNNING
                and attempt.lease_expires_at is not None
                and attempt.lease_expires_at <= checked_at
            )
            if (
                not (pending or expired)
                or attempt.deadline_at <= checked_at
                or workflow.phase != ResearchPhase.EXECUTION
                or workflow.active_gate != ResearchGate.NONE
                or workflow.active_attempt_id != attempt.id
                or workflow.active_plan_version_id != attempt.plan_version_id
                or run.id != attempt.run_id
                or run.status != AgentRunStatus.RUNNING
                or run.orchestration_version != "research-v2"
                or run.orchestration_mode != "execute"
            ):
                continue
            eligible.append(attempt.id)
        return eligible

    def expire_research_attempt_deadlines(
        self,
        now: datetime,
        *,
        error_code: str = "research_execution_deadline_exceeded",
    ) -> int:
        """Fail active executions that can no longer be claimed within their frozen budget."""

        checked_at = self._aware_research_time(now)
        expired_count = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT a.run_id
                FROM research_attempts a
                JOIN research_workflows w ON w.run_id = a.run_id
                JOIN agent_runs r ON r.id = a.run_id
                WHERE a.status IN (?, ?)
                  AND json_extract(a.payload, '$.deadline_at') <= ?
                  AND w.phase = ?
                  AND w.active_gate IN (?, ?)
                  AND w.active_attempt_id = a.id
                  AND r.orchestration_version = 'research-v2'
                ORDER BY json_extract(a.payload, '$.deadline_at'), a.id
                """,
                (
                    AttemptStatus.PENDING.value,
                    AttemptStatus.RUNNING.value,
                    checked_at.isoformat(),
                    ResearchPhase.EXECUTION.value,
                    ResearchGate.NONE.value,
                    ResearchGate.TOOL_APPROVAL.value,
                ),
            ).fetchall()
            for row in rows:
                context = self._load_research_workflow_context(connection, str(row["run_id"]))
                if context is None or context.active_attempt is None:
                    continue
                workflow = context.workflow
                run = context.run
                attempt = context.active_attempt
                gate_allows_deadline_closure = workflow.active_gate == ResearchGate.NONE or (
                    workflow.active_gate == ResearchGate.TOOL_APPROVAL
                    and attempt.status == AttemptStatus.PENDING
                    and context.active_tool_approval is not None
                )
                if (
                    attempt.status not in {AttemptStatus.PENDING, AttemptStatus.RUNNING}
                    or attempt.deadline_at > checked_at
                    or workflow.phase != ResearchPhase.EXECUTION
                    or not gate_allows_deadline_closure
                    or workflow.active_attempt_id != attempt.id
                    or workflow.active_plan_version_id != attempt.plan_version_id
                    or run.status != self._research_agent_run_status(workflow)
                    or run.orchestration_version != "research-v2"
                    or run.orchestration_mode != "execute"
                ):
                    continue

                self._close_unsettled_research_execution(
                    connection,
                    run.id,
                    cancelled_at=checked_at,
                    reason=error_code,
                    attempt_status=AttemptStatus.FAILED,
                    step_status=StepStatus.FAILED,
                )
                closed_workflow = workflow.model_copy(
                    update={
                        "phase": ResearchPhase.TERMINAL,
                        "active_gate": ResearchGate.NONE,
                        "state_version": workflow.state_version + 1,
                        "updated_at": checked_at,
                    }
                )
                workflow_cursor = connection.execute(
                    """
                    UPDATE research_workflows
                    SET phase = ?, active_gate = ?, state_version = ?, payload = ?, updated_at = ?
                    WHERE run_id = ? AND state_version = ? AND updated_at = ?
                    """,
                    (
                        closed_workflow.phase.value,
                        closed_workflow.active_gate.value,
                        closed_workflow.state_version,
                        closed_workflow.model_dump_json(),
                        checked_at.isoformat(),
                        run.id,
                        workflow.state_version,
                        workflow.updated_at.isoformat(),
                    ),
                )
                if workflow_cursor.rowcount != 1:
                    raise ResearchStoreConflict("research deadline closure lost its workflow compare-and-swap")
                closed_run = run.model_copy(
                    update={
                        "status": AgentRunStatus.FAILED,
                        "error_code": error_code,
                        "paused_state": None,
                        "updated_at": checked_at,
                    }
                )
                run_cursor = connection.execute(
                    """
                    UPDATE agent_runs SET payload = ?, updated_at = ?
                    WHERE id = ? AND orchestration_version = ? AND updated_at = ?
                    """,
                    (
                        closed_run.model_dump_json(),
                        checked_at.isoformat(),
                        run.id,
                        run.orchestration_version,
                        run.updated_at.isoformat(),
                    ),
                )
                if run_cursor.rowcount != 1:
                    raise ResearchStoreConflict("research deadline closure lost its run compare-and-swap")
                self._resolve_open_run_inboxes(
                    connection,
                    run.id,
                    reason=error_code,
                    resolved_at=checked_at,
                )
                self._append_agent_run_events(
                    connection,
                    run.id,
                    [
                        (
                            "research_attempt_failed",
                            {
                                "attempt_id": attempt.id,
                                "fencing_epoch": attempt.fencing_epoch,
                                "error_code": error_code,
                            },
                        ),
                        (
                            "research_updated",
                            {
                                "state_version": closed_workflow.state_version,
                                "phase": closed_workflow.phase.value,
                                "active_gate": closed_workflow.active_gate.value,
                            },
                        ),
                        ("run_failed", {"error_code": error_code}),
                    ],
                )
                expired_count += 1
        return expired_count

    def add_research_step(self, step: ResearchStep) -> ResearchStep:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            lineage = connection.execute(
                """
                SELECT a.run_id, a.plan_version_id, p.requirement_version_id, p.plan_hash, p.payload AS plan_payload
                FROM research_attempts a
                JOIN research_plan_versions p ON p.id = a.plan_version_id AND p.run_id = a.run_id
                WHERE a.id = ?
                """,
                (step.attempt_id,),
            ).fetchone()
            if lineage is None:
                raise ResearchStoreConflict("research step requires an existing attempt")
            try:
                plan = ExecutionPlanVersion.model_validate_json(lineage["plan_payload"])
            except (TypeError, ValueError):
                raise ResearchStoreConflict("research step plan failed integrity verification") from None
            if lineage["plan_hash"] != plan.plan_hash or canonical_sha256(plan.payload) != plan.plan_hash:
                raise ResearchStoreConflict("research step plan failed integrity verification")
            plan_steps = plan.payload.get("steps") if isinstance(plan.payload, dict) else None
            step_contract = next(
                (
                    item
                    for item in plan_steps or []
                    if isinstance(item, dict) and item.get("step_number") == step.step_number
                ),
                None,
            )
            if step_contract is None:
                raise ResearchStoreConflict("research step is not part of the frozen plan")
            if step.result_artifact_id is not None:
                expected_kind = {
                    "tool": "tool_result",
                    "skill": "skill_result",
                }.get(step_contract.get("actor_type"))
                self._require_research_artifact(
                    connection,
                    step.result_artifact_id,
                    run_id=lineage["run_id"],
                    requirement_version_id=lineage["requirement_version_id"],
                    plan_version_id=lineage["plan_version_id"],
                    attempt_id=step.attempt_id,
                    step_number=step.step_number,
                    expected_kind=expected_kind,
                )
            try:
                connection.execute(
                    """
                    INSERT INTO research_steps(
                        attempt_id, step_number, status, claim_epoch,
                        result_artifact_id, payload, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        step.attempt_id,
                        step.step_number,
                        step.status.value,
                        step.claim_epoch,
                        step.result_artifact_id,
                        step.model_dump_json(),
                        step.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ResearchStoreConflict("research step already exists") from error
        return step

    def get_research_step(self, attempt_id: str, step_number: int) -> ResearchStep | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM research_steps WHERE attempt_id = ? AND step_number = ?",
                (attempt_id, step_number),
            ).fetchone()
        return ResearchStep.model_validate_json(row["payload"]) if row is not None else None

    def claim_research_step(
        self,
        attempt_id: str,
        step_number: int,
        *,
        lease: ExecutionLease,
        now: datetime,
    ) -> ResearchStep | None:
        checked_at = self._aware_research_time(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            attempt = self._live_research_attempt_for_lease(
                connection,
                attempt_id,
                lease=lease,
                now=checked_at,
            )
            if attempt is None:
                return None
            row = connection.execute(
                "SELECT * FROM research_steps WHERE attempt_id = ? AND step_number = ?",
                (attempt_id, step_number),
            ).fetchone()
            if row is None:
                return None
            try:
                current = ResearchStep.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research step failed integrity verification") from None
            if not self._research_step_projection_matches(row, current):
                raise ResearchStoreConflict("research step failed integrity verification")
            if current.status == StepStatus.RUNNING and current.claim_epoch == lease.fencing_epoch:
                return current
            fresh_claim = current.status == StepStatus.READY and current.claim_epoch == 0
            takeover = (
                current.status == StepStatus.RUNNING
                and current.claim_epoch > 0
                and current.claim_epoch < lease.fencing_epoch
            )
            if not fresh_claim and not takeover:
                return None
            claimed = current.model_copy(
                update={
                    "status": StepStatus.RUNNING,
                    "claim_epoch": lease.fencing_epoch,
                    "started_at": current.started_at if takeover else checked_at,
                    "updated_at": checked_at,
                }
            )
            cursor = connection.execute(
                """
                UPDATE research_steps
                SET status = ?, claim_epoch = ?, result_artifact_id = ?, payload = ?, updated_at = ?
                WHERE attempt_id = ? AND step_number = ? AND status = ? AND claim_epoch = ?
                  AND updated_at = ?
                """,
                (
                    claimed.status.value,
                    claimed.claim_epoch,
                    claimed.result_artifact_id,
                    claimed.model_dump_json(),
                    checked_at.isoformat(),
                    attempt_id,
                    step_number,
                    current.status.value,
                    current.claim_epoch,
                    current.updated_at.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                return None
            self._append_agent_run_events(
                connection,
                attempt.run_id,
                [
                    (
                        "research_step_claimed",
                        {
                            "attempt_id": attempt_id,
                            "step_number": step_number,
                            "fencing_epoch": lease.fencing_epoch,
                            "takeover": takeover,
                        },
                    )
                ],
            )
        return claimed

    def compare_and_swap_research_step(
        self,
        attempt_id: str,
        step_number: int,
        *,
        lease: ExecutionLease,
        expected_status: StepStatus,
        next_status: StepStatus,
        result_artifact_id: str | None = None,
        error_code: str | None = None,
        now: datetime,
    ) -> ResearchStep | None:
        checked_at = self._aware_research_time(now)
        allowed = {
            (StepStatus.PENDING, StepStatus.READY),
            (StepStatus.READY, StepStatus.SKIPPED),
            (StepStatus.RUNNING, StepStatus.COMPLETED),
            (StepStatus.RUNNING, StepStatus.FAILED),
        }
        if (expected_status, next_status) not in allowed:
            raise ValueError("unsupported research step transition")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            attempt = self._live_research_attempt_for_lease(
                connection,
                attempt_id,
                lease=lease,
                now=checked_at,
                allow_off=expected_status == StepStatus.RUNNING,
            )
            if attempt is None:
                return None
            row = connection.execute(
                "SELECT * FROM research_steps WHERE attempt_id = ? AND step_number = ?",
                (attempt_id, step_number),
            ).fetchone()
            if row is None:
                return None
            try:
                current = ResearchStep.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research step failed integrity verification") from None
            if not self._research_step_projection_matches(row, current):
                raise ResearchStoreConflict("research step failed integrity verification")
            if current.status != expected_status:
                return None
            expected_epoch = lease.fencing_epoch if expected_status == StepStatus.RUNNING else 0
            if current.claim_epoch != expected_epoch:
                return None

            updates: dict[str, object] = {"status": next_status, "updated_at": checked_at}
            if next_status == StepStatus.READY:
                if result_artifact_id is not None or error_code is not None:
                    raise ValueError("ready steps cannot carry terminal fields")
            elif next_status == StepStatus.COMPLETED:
                if result_artifact_id is None or error_code is not None:
                    raise ValueError("completed steps require only a result Artifact")
                plan_row = connection.execute(
                    """
                    SELECT p.requirement_version_id, p.payload
                    FROM research_attempts a
                    JOIN research_plan_versions p ON p.id = a.plan_version_id
                    WHERE a.id = ?
                    """,
                    (attempt_id,),
                ).fetchone()
                if plan_row is None:
                    raise ResearchStoreConflict("research step plan is missing")
                plan = ExecutionPlanVersion.model_validate_json(plan_row["payload"])
                contract = next(
                    (
                        item
                        for item in plan.payload.get("steps", [])
                        if isinstance(item, dict) and item.get("step_number") == step_number
                    ),
                    None,
                )
                expected_kind = {
                    "tool": "tool_actor_output",
                    "skill": "skill_result",
                }.get(contract.get("actor_type") if isinstance(contract, dict) else None)
                self._require_research_artifact(
                    connection,
                    result_artifact_id,
                    run_id=attempt.run_id,
                    requirement_version_id=plan_row["requirement_version_id"],
                    plan_version_id=attempt.plan_version_id,
                    attempt_id=attempt_id,
                    step_number=step_number,
                    expected_kind=expected_kind,
                )
                if expected_kind == "tool_actor_output":
                    acknowledged = connection.execute(
                        """
                        SELECT 1 FROM research_tool_invocations
                        WHERE active_attempt_id = ? AND step_number = ? AND state = ?
                        LIMIT 1
                        """,
                        (attempt_id, step_number, InvocationState.ACKNOWLEDGED.value),
                    ).fetchone()
                    if acknowledged is None:
                        raise ResearchStoreConflict("Tool step requires an acknowledged invocation")
                updates.update(
                    {
                        "result_artifact_id": result_artifact_id,
                        "error_code": None,
                        "completed_at": checked_at,
                    }
                )
            elif next_status == StepStatus.FAILED:
                if not error_code or result_artifact_id is not None:
                    raise ValueError("failed steps require only an error code")
                updates.update(
                    {
                        "result_artifact_id": None,
                        "error_code": error_code,
                        "completed_at": checked_at,
                    }
                )
            else:
                if result_artifact_id is not None:
                    raise ValueError("skipped steps cannot contain a result Artifact")
                updates.update({"error_code": error_code, "completed_at": checked_at})
            updated = current.model_copy(update=updates)
            cursor = connection.execute(
                """
                UPDATE research_steps
                SET status = ?, claim_epoch = ?, result_artifact_id = ?, payload = ?, updated_at = ?
                WHERE attempt_id = ? AND step_number = ? AND status = ? AND claim_epoch = ?
                """,
                (
                    updated.status.value,
                    updated.claim_epoch,
                    updated.result_artifact_id,
                    updated.model_dump_json(),
                    checked_at.isoformat(),
                    attempt_id,
                    step_number,
                    current.status.value,
                    current.claim_epoch,
                ),
            )
            if cursor.rowcount != 1:
                return None
            self._append_agent_run_events(
                connection,
                attempt.run_id,
                [
                    (
                        f"research_step_{next_status.value}",
                        {
                            "attempt_id": attempt_id,
                            "step_number": step_number,
                            **({"error_code": error_code} if error_code else {}),
                        },
                    )
                ],
            )
        return updated

    def add_research_tool_invocation(self, invocation: ToolInvocation) -> tuple[ToolInvocation, bool]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            plan_row = connection.execute(
                "SELECT run_id, requirement_version_id FROM research_plan_versions WHERE id = ?",
                (invocation.plan_version_id,),
            ).fetchone()
            if plan_row is None or plan_row["run_id"] != invocation.run_id:
                raise ResearchStoreConflict("Tool invocation requires a plan from the same run")
            self._require_research_run(connection, invocation.run_id)
            attempt_row = connection.execute(
                "SELECT run_id, plan_version_id, status, fencing_epoch FROM research_attempts WHERE id = ?",
                (invocation.active_attempt_id,),
            ).fetchone()
            step_row = connection.execute(
                "SELECT status, claim_epoch FROM research_steps WHERE attempt_id = ? AND step_number = ?",
                (invocation.active_attempt_id, invocation.step_number),
            ).fetchone()
            if (
                attempt_row is None
                or attempt_row["run_id"] != invocation.run_id
                or attempt_row["plan_version_id"] != invocation.plan_version_id
                or attempt_row["status"] != "running"
                or step_row is None
                or step_row["status"] != "running"
                or step_row["claim_epoch"] != attempt_row["fencing_epoch"]
            ):
                raise ResearchStoreConflict("Tool invocation requires the matching attempt step")
            self._require_research_artifact(
                connection,
                invocation.request_artifact_id,
                run_id=invocation.run_id,
                requirement_version_id=plan_row["requirement_version_id"],
                plan_version_id=invocation.plan_version_id,
                attempt_id=invocation.active_attempt_id,
                step_number=invocation.step_number,
                expected_kind="tool_request",
                expected_content_hash=invocation.resolved_input_hash,
            )
            if invocation.artifact_id is not None:
                self._require_research_artifact(
                    connection,
                    invocation.artifact_id,
                    run_id=invocation.run_id,
                    requirement_version_id=plan_row["requirement_version_id"],
                    plan_version_id=invocation.plan_version_id,
                    attempt_id=invocation.active_attempt_id,
                    step_number=invocation.step_number,
                    expected_kind="tool_result",
                )
            row = connection.execute(
                "SELECT * FROM research_tool_invocations WHERE run_id = ? AND operation_key = ?",
                (invocation.run_id, invocation.operation_key),
            ).fetchone()
            if row is not None:
                try:
                    existing = ToolInvocation.model_validate_json(row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
                if not self._research_invocation_projection_matches(row, existing):
                    raise ResearchStoreConflict("Tool invocation failed integrity verification")
                if (
                    existing.resolved_input_hash != invocation.resolved_input_hash
                    or existing.plan_version_id != invocation.plan_version_id
                    or existing.step_number != invocation.step_number
                    or existing.active_attempt_id != invocation.active_attempt_id
                    or existing.request_artifact_id != invocation.request_artifact_id
                ):
                    raise ResearchStoreConflict("operation key was used for a different Tool request")
                return existing, False
            try:
                connection.execute(
                    """
                    INSERT INTO research_tool_invocations(
                        id, run_id, plan_version_id, step_number, operation_key,
                        request_hash, resolved_input_hash, request_artifact_id, active_attempt_id,
                        state, send_count, active_send_sequence, sent_fencing_epoch,
                        receipt_payload, artifact_id, provider_operation_id, last_sent_at,
                        acknowledged_at, unknown_at, payload, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invocation.id,
                        invocation.run_id,
                        invocation.plan_version_id,
                        invocation.step_number,
                        invocation.operation_key,
                        invocation.resolved_input_hash,
                        invocation.resolved_input_hash,
                        invocation.request_artifact_id,
                        invocation.active_attempt_id,
                        invocation.state.value,
                        invocation.send_count,
                        invocation.active_send_sequence,
                        invocation.sent_fencing_epoch,
                        invocation.receipt.model_dump_json() if invocation.receipt is not None else None,
                        invocation.artifact_id,
                        invocation.provider_operation_id,
                        invocation.last_sent_at.isoformat() if invocation.last_sent_at is not None else None,
                        invocation.acknowledged_at.isoformat() if invocation.acknowledged_at is not None else None,
                        invocation.unknown_at.isoformat() if invocation.unknown_at is not None else None,
                        invocation.model_dump_json(),
                        invocation.created_at.isoformat(),
                        invocation.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ResearchStoreConflict("Tool invocation already exists") from error
        return invocation, True

    def prepare_research_tool_invocation(
        self,
        invocation: ToolInvocation,
        *,
        lease: ExecutionLease,
        now: datetime,
    ) -> tuple[ToolInvocation, bool]:
        checked_at = self._aware_research_time(now)
        if invocation.state != InvocationState.PREPARED or invocation.send_count != 0:
            raise ResearchStoreConflict("runtime Tool invocation must start prepared")
        prepared = invocation.model_copy(update={"created_at": checked_at, "updated_at": checked_at})
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            attempt = self._live_research_attempt_for_lease(
                connection,
                prepared.active_attempt_id,
                lease=lease,
                now=checked_at,
            )
            if (
                attempt is None
                or attempt.run_id != prepared.run_id
                or attempt.plan_version_id != prepared.plan_version_id
            ):
                raise ResearchStoreConflict("Tool invocation requires the active execution lease")
            step_row = connection.execute(
                "SELECT * FROM research_steps WHERE attempt_id = ? AND step_number = ?",
                (prepared.active_attempt_id, prepared.step_number),
            ).fetchone()
            if step_row is None:
                raise ResearchStoreConflict("Tool invocation requires the matching attempt step")
            try:
                step = ResearchStep.model_validate_json(step_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research step failed integrity verification") from None
            if (
                not self._research_step_projection_matches(step_row, step)
                or step.status != StepStatus.RUNNING
                or step.claim_epoch != lease.fencing_epoch
            ):
                raise ResearchStoreConflict("Tool invocation requires the matching attempt step")
            plan_row = connection.execute(
                "SELECT run_id, requirement_version_id FROM research_plan_versions WHERE id = ?",
                (prepared.plan_version_id,),
            ).fetchone()
            if plan_row is None or plan_row["run_id"] != prepared.run_id:
                raise ResearchStoreConflict("Tool invocation requires a plan from the same run")
            self._require_research_artifact(
                connection,
                prepared.request_artifact_id,
                run_id=prepared.run_id,
                requirement_version_id=plan_row["requirement_version_id"],
                plan_version_id=prepared.plan_version_id,
                attempt_id=prepared.active_attempt_id,
                step_number=prepared.step_number,
                expected_kind="tool_request",
                expected_content_hash=prepared.resolved_input_hash,
            )
            row = connection.execute(
                "SELECT * FROM research_tool_invocations WHERE run_id = ? AND operation_key = ?",
                (prepared.run_id, prepared.operation_key),
            ).fetchone()
            if row is not None:
                try:
                    existing = ToolInvocation.model_validate_json(row["payload"])
                except (RecursionError, TypeError, ValueError):
                    raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
                if not self._research_invocation_projection_matches(row, existing):
                    raise ResearchStoreConflict("Tool invocation failed integrity verification")
                if (
                    existing.resolved_input_hash != prepared.resolved_input_hash
                    or existing.plan_version_id != prepared.plan_version_id
                    or existing.step_number != prepared.step_number
                    or existing.active_attempt_id != prepared.active_attempt_id
                    or existing.request_artifact_id != prepared.request_artifact_id
                ):
                    raise ResearchStoreConflict("operation key was used for a different Tool request")
                return existing, False
            try:
                connection.execute(
                    """
                    INSERT INTO research_tool_invocations(
                        id, run_id, plan_version_id, step_number, operation_key,
                        request_hash, resolved_input_hash, request_artifact_id, active_attempt_id,
                        state, send_count, active_send_sequence, sent_fencing_epoch,
                        receipt_payload, artifact_id, provider_operation_id, last_sent_at,
                        acknowledged_at, unknown_at, payload, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prepared.id,
                        prepared.run_id,
                        prepared.plan_version_id,
                        prepared.step_number,
                        prepared.operation_key,
                        prepared.resolved_input_hash,
                        prepared.resolved_input_hash,
                        prepared.request_artifact_id,
                        prepared.active_attempt_id,
                        prepared.state.value,
                        prepared.send_count,
                        prepared.active_send_sequence,
                        prepared.sent_fencing_epoch,
                        None,
                        None,
                        prepared.provider_operation_id,
                        None,
                        None,
                        None,
                        prepared.model_dump_json(),
                        checked_at.isoformat(),
                        checked_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ResearchStoreConflict("Tool invocation already exists") from error
            self._append_agent_run_events(
                connection,
                prepared.run_id,
                [
                    (
                        "research_tool_invocation_prepared",
                        {"invocation_id": prepared.id, "step_number": prepared.step_number},
                    )
                ],
            )
        return prepared, True

    def mark_research_tool_invocation_sent(
        self,
        invocation_id: str,
        *,
        lease: ExecutionLease,
        sent_at: datetime,
    ) -> ToolInvocation | None:
        effective_sent_at = self._aware_research_time(sent_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM research_tool_invocations WHERE id = ?",
                (invocation_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                current = ToolInvocation.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
            if not self._research_invocation_projection_matches(row, current):
                raise ResearchStoreConflict("Tool invocation failed integrity verification")
            if current.state not in {InvocationState.PREPARED, InvocationState.SENT}:
                return None
            attempt = self._live_research_attempt_for_lease(
                connection,
                current.active_attempt_id,
                lease=lease,
                now=effective_sent_at,
            )
            if attempt is None:
                return None
            step_row = connection.execute(
                "SELECT * FROM research_steps WHERE attempt_id = ? AND step_number = ?",
                (current.active_attempt_id, current.step_number),
            ).fetchone()
            if step_row is None:
                return None
            try:
                step = ResearchStep.model_validate_json(step_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research step failed integrity verification") from None
            if (
                not self._research_step_projection_matches(step_row, step)
                or step.status != StepStatus.RUNNING
                or step.claim_epoch != lease.fencing_epoch
            ):
                return None
            if current.state == InvocationState.SENT:
                return current if current.sent_fencing_epoch == lease.fencing_epoch else None
            sent = current.model_copy(
                update={
                    "state": InvocationState.SENT,
                    "send_count": current.send_count + 1,
                    "active_send_sequence": current.active_send_sequence + 1,
                    "sent_fencing_epoch": lease.fencing_epoch,
                    "last_sent_at": effective_sent_at,
                    "updated_at": effective_sent_at,
                }
            )
            cursor = connection.execute(
                """
                UPDATE research_tool_invocations
                SET state = ?, send_count = ?, active_send_sequence = ?, sent_fencing_epoch = ?,
                    last_sent_at = ?, payload = ?, updated_at = ?
                WHERE id = ? AND state = ? AND active_send_sequence = ?
                  AND sent_fencing_epoch IS ? AND updated_at = ?
                """,
                (
                    sent.state.value,
                    sent.send_count,
                    sent.active_send_sequence,
                    sent.sent_fencing_epoch,
                    effective_sent_at.isoformat(),
                    sent.model_dump_json(),
                    effective_sent_at.isoformat(),
                    current.id,
                    current.state.value,
                    current.active_send_sequence,
                    current.sent_fencing_epoch,
                    current.updated_at.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                return None
            self._append_agent_run_events(
                connection,
                current.run_id,
                [
                    (
                        "research_tool_invocation_sent",
                        {
                            "invocation_id": current.id,
                            "send_sequence": sent.active_send_sequence,
                        },
                    )
                ],
            )
        return sent

    def mark_research_tool_invocation_unknown(
        self,
        invocation_id: str,
        *,
        expected_send_sequence: int,
        expected_sent_fencing_epoch: int,
        unknown_at: datetime,
        error_code: str = "provider_result_unknown",
    ) -> ToolInvocation | None:
        effective_unknown_at = self._aware_research_time(unknown_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM research_tool_invocations WHERE id = ?",
                (invocation_id,),
            ).fetchone()
            if row is None:
                return None
            try:
                current = ToolInvocation.model_validate_json(row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
            if not self._research_invocation_projection_matches(row, current):
                raise ResearchStoreConflict("Tool invocation failed integrity verification")
            if (
                current.state == InvocationState.UNKNOWN
                and current.active_send_sequence == expected_send_sequence
                and current.sent_fencing_epoch == expected_sent_fencing_epoch
            ):
                return current
            if (
                current.state != InvocationState.SENT
                or current.active_send_sequence != expected_send_sequence
                or current.sent_fencing_epoch != expected_sent_fencing_epoch
            ):
                return None
            unknown = current.model_copy(
                update={
                    "state": InvocationState.UNKNOWN,
                    "unknown_at": effective_unknown_at,
                    "error_code": error_code,
                    "updated_at": effective_unknown_at,
                }
            )
            cursor = connection.execute(
                """
                UPDATE research_tool_invocations
                SET state = ?, unknown_at = ?, payload = ?, updated_at = ?
                WHERE id = ? AND state = ? AND active_send_sequence = ?
                  AND sent_fencing_epoch = ? AND updated_at = ?
                """,
                (
                    unknown.state.value,
                    effective_unknown_at.isoformat(),
                    unknown.model_dump_json(),
                    effective_unknown_at.isoformat(),
                    current.id,
                    InvocationState.SENT.value,
                    expected_send_sequence,
                    expected_sent_fencing_epoch,
                    current.updated_at.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                return None
            self._append_agent_run_events(
                connection,
                current.run_id,
                [
                    (
                        "research_tool_invocation_unknown",
                        {
                            "invocation_id": current.id,
                            "send_sequence": expected_send_sequence,
                        },
                    )
                ],
            )
        return unknown

    def enter_research_recovery_decision(
        self,
        attempt_id: str,
        *,
        error_code: str,
        now: datetime,
    ) -> ToolInvocation | None:
        """Fence a running attempt after an UNKNOWN Tool result and open the user recovery gate."""

        effective_now = self._aware_research_time(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            attempt_row = connection.execute(
                "SELECT * FROM research_attempts WHERE id = ?",
                (attempt_id,),
            ).fetchone()
            if attempt_row is None:
                return None
            try:
                attempt = ExecutionAttempt.model_validate_json(attempt_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research attempt failed integrity verification") from None
            if not self._research_attempt_projection_matches(attempt_row, attempt):
                raise ResearchStoreConflict("research attempt failed integrity verification")
            workflow_row = connection.execute(
                "SELECT * FROM research_workflows WHERE run_id = ?",
                (attempt.run_id,),
            ).fetchone()
            run_row = connection.execute(
                "SELECT * FROM agent_runs WHERE id = ?",
                (attempt.run_id,),
            ).fetchone()
            if workflow_row is None or run_row is None:
                return None
            try:
                workflow = ResearchWorkflow.model_validate_json(workflow_row["payload"])
                run = AgentRun.model_validate_json(run_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research recovery state failed integrity verification") from None
            if (
                not self._research_workflow_projection_matches(workflow_row, workflow)
                or not self._research_run_projection_matches(run_row, run)
            ):
                raise ResearchStoreConflict("research recovery state failed integrity verification")
            invocation_rows = connection.execute(
                """
                SELECT * FROM research_tool_invocations
                WHERE active_attempt_id = ? AND state = ?
                ORDER BY id
                """,
                (attempt.id, InvocationState.UNKNOWN.value),
            ).fetchall()
            if len(invocation_rows) != 1:
                return None
            invocation_row = invocation_rows[0]
            try:
                invocation = ToolInvocation.model_validate_json(invocation_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
            if not self._research_invocation_projection_matches(invocation_row, invocation):
                raise ResearchStoreConflict("Tool invocation failed integrity verification")
            if (
                attempt.status == AttemptStatus.RECOVERY_REQUIRED
                and workflow.phase == ResearchPhase.EXECUTION
                and workflow.active_gate == ResearchGate.RECOVERY_DECISION
                and workflow.active_attempt_id == attempt.id
            ):
                return invocation
            if (
                attempt.status != AttemptStatus.RUNNING
                or workflow.phase != ResearchPhase.EXECUTION
                or workflow.active_gate != ResearchGate.NONE
                or workflow.active_attempt_id != attempt.id
                or run.status != AgentRunStatus.RUNNING
                or run.orchestration_version != "research-v2"
            ):
                return None
            recovery_attempt = attempt.model_copy(
                update={
                    "status": AttemptStatus.RECOVERY_REQUIRED,
                    "lease_owner": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "updated_at": effective_now,
                }
            )
            attempt_cursor = connection.execute(
                """
                UPDATE research_attempts
                SET status = ?, lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    payload = ?, updated_at = ?
                WHERE id = ? AND status = ? AND fencing_epoch = ? AND updated_at = ?
                """,
                (
                    recovery_attempt.status.value,
                    recovery_attempt.model_dump_json(),
                    recovery_attempt.updated_at.isoformat(),
                    attempt.id,
                    AttemptStatus.RUNNING.value,
                    attempt.fencing_epoch,
                    attempt.updated_at.isoformat(),
                ),
            )
            if attempt_cursor.rowcount != 1:
                return None
            recovery_workflow = workflow.model_copy(
                update={
                    "active_gate": ResearchGate.RECOVERY_DECISION,
                    "state_version": workflow.state_version + 1,
                    "updated_at": effective_now,
                }
            )
            workflow_cursor = connection.execute(
                """
                UPDATE research_workflows
                SET active_gate = ?, state_version = ?, payload = ?, updated_at = ?
                WHERE run_id = ? AND state_version = ? AND active_gate = ?
                """,
                (
                    recovery_workflow.active_gate.value,
                    recovery_workflow.state_version,
                    recovery_workflow.model_dump_json(),
                    recovery_workflow.updated_at.isoformat(),
                    workflow.run_id,
                    workflow.state_version,
                    ResearchGate.NONE.value,
                ),
            )
            if workflow_cursor.rowcount != 1:
                raise ResearchStoreConflict("research recovery workflow changed concurrently")
            self._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "research_recovery_required",
                        {
                            "attempt_id": attempt.id,
                            "invocation_id": invocation.id,
                            "error_code": error_code,
                            "state_version": recovery_workflow.state_version,
                        },
                    )
                ],
            )
            return invocation

    @staticmethod
    def _require_research_artifact(
        connection: sqlite3.Connection,
        artifact_id: str,
        *,
        run_id: str,
        requirement_version_id: str,
        plan_version_id: str,
        attempt_id: str,
        step_number: int,
        expected_kind: str | None = None,
        expected_content_hash: str | None = None,
    ) -> Artifact:
        row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        if row is None or row["verification_state"] != ArtifactVerificationState.SEALED.value:
            raise ResearchStoreConflict("research Artifact reference is missing or not sealed")
        try:
            artifact = Artifact.model_validate_json(row["payload"])
        except (TypeError, ValueError):
            raise ResearchStoreConflict("research Artifact failed integrity verification") from None
        indexed_values = {
            "id": artifact.id,
            "run_id": artifact.run_id,
            "workspace_id": artifact.workspace_id,
            "project_id": artifact.project_id,
            "user_id": artifact.user_id,
            "artifact_type": artifact.artifact_type,
            "content_type": artifact.content_type,
            "truncated": int(artifact.truncated),
            "verification_state": artifact.verification_state.value if artifact.verification_state else None,
            "schema_version": artifact.schema_version,
            "content_hash": artifact.content_hash,
            "size_bytes": artifact.size_bytes,
            "requirement_version_id": artifact.requirement_version_id,
            "plan_version_id": artifact.plan_version_id,
            "attempt_id": artifact.attempt_id,
            "step_number": artifact.step_number,
            "purged_at": artifact.purged_at.isoformat() if artifact.purged_at is not None else None,
            "purged_by": artifact.purged_by,
            "created_at": artifact.created_at.isoformat(),
            "updated_at": artifact.updated_at.isoformat() if artifact.updated_at is not None else None,
        }
        if any(row[key] != value for key, value in indexed_values.items()):
            raise ResearchStoreConflict("research Artifact failed integrity verification")
        if artifact.content_type == "application/json":
            try:
                canonical_content = canonical_json_bytes(json.loads(artifact.content)).decode("utf-8")
            except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                raise ResearchStoreConflict("research Artifact failed integrity verification") from None
            if canonical_content != artifact.content:
                raise ResearchStoreConflict("research Artifact failed integrity verification")
        if (
            artifact.run_id != run_id
            or artifact.requirement_version_id != requirement_version_id
            or artifact.plan_version_id != plan_version_id
            or artifact.attempt_id != attempt_id
            or artifact.step_number != step_number
            or (expected_kind is not None and artifact.artifact_type != expected_kind)
            or (expected_content_hash is not None and artifact.content_hash != expected_content_hash)
        ):
            raise ResearchStoreConflict("research Artifact provenance does not match its consumer")
        return artifact

    def get_research_tool_invocation(self, invocation_id: str) -> ToolInvocation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_tool_invocations WHERE id = ?",
                (invocation_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            invocation = ToolInvocation.model_validate_json(row["payload"])
        except (RecursionError, TypeError, ValueError):
            raise ResearchStoreConflict("Tool invocation failed integrity verification") from None
        if not self._research_invocation_projection_matches(row, invocation):
            raise ResearchStoreConflict("Tool invocation failed integrity verification")
        return invocation

    def add_research_model_call_receipt(self, receipt: ModelCallReceipt) -> ModelCallReceipt:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_research_run(connection, receipt.run_id)
            owner_tables = {
                "requirement_version": "research_requirement_versions",
                "plan_version": "research_plan_versions",
                "attempt": "research_attempts",
            }
            owner_table = owner_tables[receipt.owner_kind]
            owner = connection.execute(
                f"SELECT run_id FROM {owner_table} WHERE id = ?",
                (receipt.owner_id,),
            ).fetchone()
            if owner is None or owner["run_id"] != receipt.run_id:
                raise ResearchStoreConflict("model call receipt owner does not belong to the run")
            try:
                connection.execute(
                    """
                    INSERT INTO research_model_call_receipts(
                        id, run_id, owner_kind, owner_id, stage, call_key, payload, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt.id,
                        receipt.run_id,
                        receipt.owner_kind,
                        receipt.owner_id,
                        receipt.stage,
                        receipt.call_key,
                        receipt.model_dump_json(),
                        receipt.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ResearchStoreConflict("model call receipt already exists") from error
        return receipt

    def get_research_model_call_receipt(self, receipt_id: str) -> ModelCallReceipt | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM research_model_call_receipts WHERE id = ?",
                (receipt_id,),
            ).fetchone()
        return ModelCallReceipt.model_validate_json(row["payload"]) if row is not None else None

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
                raise ResearchStoreConflict("research-v2 artifacts require ArtifactStore")
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

    def resolve_research_tool_approval(
        self,
        item_id: str,
        *,
        owner_user_id: str,
        action: str,
        call_id: str,
        resolved_at: datetime | None = None,
    ) -> ResearchToolApprovalResult:
        """Atomically approve one research attempt or reject its whole workflow."""

        if action not in {"approve", "reject"}:
            raise ResearchToolApprovalError("invalid", "action must be 'approve' or 'reject'")
        now = self._aware_research_time(resolved_at or now_utc())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            item_row = connection.execute(
                "SELECT payload FROM records WHERE collection = 'inbox_items' AND id = ?",
                (item_id,),
            ).fetchone()
            if item_row is None:
                raise ResearchToolApprovalError("not_found", "Inbox item not found")
            try:
                item = InboxItem.model_validate_json(item_row["payload"])
            except (RecursionError, TypeError, ValueError):
                raise ResearchToolApprovalError("conflict", "Tool approval failed integrity verification") from None
            if item.user_id != owner_user_id:
                raise ResearchToolApprovalError("forbidden", "Only the research owner can resolve this approval")
            if item.item_type != "research_tool_approval":
                raise ResearchToolApprovalError("invalid", "Inbox item is not a research Tool approval")
            if item.status != "open":
                raise ResearchToolApprovalError("conflict", "Tool approval is no longer open")
            if not call_id or item.metadata.get("call_id") != call_id:
                raise ResearchToolApprovalError("conflict", "Tool approval call identity does not match")
            run_id = item.metadata.get("run_id", "")
            context = self._load_research_workflow_context(connection, run_id)
            if context is None:
                raise ResearchToolApprovalError("not_found", "Research run not found")
            if (
                context.run.user_id != owner_user_id
                or context.workflow.phase != ResearchPhase.EXECUTION
                or context.workflow.active_gate != ResearchGate.TOOL_APPROVAL
                or context.active_attempt is None
                or context.active_attempt.status != AttemptStatus.PENDING
                or context.active_tool_approval is None
                or context.active_tool_approval.id != item.id
                or item.metadata.get("attempt_id") != context.active_attempt.id
                or item.metadata.get("plan_version_id") != context.workflow.active_plan_version_id
            ):
                raise ResearchToolApprovalError("conflict", "Research Tool approval is stale")

            expired = now - item.created_at > timedelta(hours=24) or context.active_attempt.deadline_at <= now
            effective_action = "reject" if expired else action
            reason = "tool_approval_expired" if expired else "tool_approval_rejected"
            workflow = context.workflow.model_copy(
                update={
                    "phase": (
                        ResearchPhase.TERMINAL
                        if effective_action == "reject"
                        else context.workflow.phase
                    ),
                    "active_gate": ResearchGate.NONE,
                    "state_version": context.workflow.state_version + 1,
                    "updated_at": now,
                }
            )
            if effective_action == "reject":
                self._close_unsettled_research_execution(
                    connection,
                    context.run.id,
                    cancelled_at=now,
                    reason=reason,
                )
            workflow_cursor = connection.execute(
                """
                UPDATE research_workflows
                SET phase = ?, active_gate = ?, state_version = ?, payload = ?, updated_at = ?
                WHERE run_id = ? AND state_version = ? AND active_gate = ?
                """,
                (
                    workflow.phase.value,
                    workflow.active_gate.value,
                    workflow.state_version,
                    workflow.model_dump_json(),
                    now.isoformat(),
                    workflow.run_id,
                    context.workflow.state_version,
                    ResearchGate.TOOL_APPROVAL.value,
                ),
            )
            if workflow_cursor.rowcount != 1:
                raise ResearchToolApprovalError("conflict", "Research Tool approval changed concurrently")

            next_status = AgentRunStatus.RUNNING if effective_action == "approve" else AgentRunStatus.REJECTED
            run = context.run.model_copy(
                update={
                    "status": next_status,
                    "error_code": None if effective_action == "approve" else reason,
                    "updated_at": now,
                }
            )
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
                (run.model_dump_json(), now.isoformat(), run.id),
            )
            item.status = "resolved"
            item.acknowledged_at = item.acknowledged_at or now
            item.resolved_at = now
            item.updated_at = now
            item.metadata["approval_action"] = effective_action
            if expired:
                item.metadata["approval_failure"] = reason
            connection.execute(
                "UPDATE records SET payload = ? WHERE collection = 'inbox_items' AND id = ?",
                (item.model_dump_json(), item.id),
            )
            if effective_action == "reject":
                self._resolve_open_run_inboxes(connection, run.id, reason=reason, resolved_at=now)
            self._append_agent_run_events(
                connection,
                run.id,
                [
                    (
                        "approval_resolved",
                        {
                            "inbox_item_id": item.id,
                            "attempt_id": context.active_attempt.id,
                            "call_id": call_id,
                            "action": effective_action,
                        },
                    ),
                    (
                        "research_updated",
                        {
                            "state_version": workflow.state_version,
                            "phase": workflow.phase.value,
                            "active_gate": workflow.active_gate.value,
                        },
                    ),
                    *(
                        [("run_rejected", {"error_code": reason})]
                        if effective_action == "reject"
                        else []
                    ),
                ],
            )
        return ResearchToolApprovalResult(
            inbox_item=item,
            run=run,
            attempt_id=context.active_attempt.id if effective_action == "approve" else None,
            expired=expired,
        )

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
        items = [thread for thread in self.chat_threads if thread.user_id == user_id]
        if workspace_id is not None:
            items = [thread for thread in items if thread.workspace_id == workspace_id]
        if project_id is not None:
            items = [thread for thread in items if thread.project_id == project_id]
        return sorted(items, key=lambda thread: (thread.updated_at, thread.id), reverse=True)

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
                if not self._thread_matches(thread, workspace_id, project_id):
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


store = SQLiteStore()
