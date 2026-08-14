from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date as dt_date
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from agentmesh.models import (
    ActivityLog,
    Agent,
    AgentMemoryBinding,
    AgentToolGrant,
    AuditEvent,
    AuthCredential,
    AuthSession,
    AutoBlackboardPostRequest,
    BlackboardPost,
    BlackboardPostType,
    ChatMessage,
    ChatThread,
    ChatTurnTrace,
    ConsentGrant,
    ContributionPoint,
    DocumentParseJob,
    DocumentRecord,
    InboxItem,
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
    SearchResult,
    Source,
    Task,
    Team,
    TeamMembership,
    ToolDefinition,
    User,
    UserMemoryItem,
    UserRole,
    Workspace,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "data" / "agentmesh.sqlite3"

# --- FTS5 infrastructure ---

_FTS_COLLECTIONS = frozenset(
    {"chat_messages", "activity_logs", "blackboard_posts", "memory_items", "user_memory_items", "documents"}
)

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
        created_at = _dt_str(getattr(item, "created_at", None))
    elif collection == "user_memory_items":
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
}


class SQLiteStore:
    def __init__(self, db_path: str | Path | None = None):
        configured_path = db_path or os.getenv("AGENTMESH_DB_PATH") or DEFAULT_DB_PATH
        self.db_path = Path(configured_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._backfill_fts()
        self._backfill_vec()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        self._ensure_schema(connection)
        return connection

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            self._ensure_schema(connection)

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

    def reset(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM records")
            connection.execute("DELETE FROM records_fts")
            connection.execute("DELETE FROM records_vec")

    def _upsert(self, collection: str, item: BaseModel) -> None:
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
            self._sync_vec(connection, collection, item)

    def _sync_fts(self, connection: sqlite3.Connection, collection: str, item: BaseModel) -> None:
        doc = _extract_fts_doc(collection, item)
        if doc is None:
            return
        connection.execute(
            "DELETE FROM records_fts WHERE collection = ? AND record_id = ?",
            (doc.collection, doc.record_id),
        )
        connection.execute(
            "INSERT INTO records_fts(collection, record_id, title, body, scope, workspace_id, project_id, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc.collection, doc.record_id, doc.title, doc.body, doc.scope, doc.workspace_id, doc.project_id, doc.user_id, doc.created_at),
        )

    def _sync_vec(self, connection: sqlite3.Connection, collection: str, item: BaseModel) -> None:
        doc = _extract_fts_doc(collection, item)
        if doc is None:
            return
        text = f"{doc.title} {doc.body}".strip()
        if not text:
            return
        from agentmesh.embedding import embed_text, serialize_embedding

        embedding = embed_text(text)
        if embedding is None:
            return
        connection.execute(
            "DELETE FROM records_vec WHERE collection = ? AND record_id = ?",
            (doc.collection, doc.record_id),
        )
        connection.execute(
            "INSERT INTO records_vec(collection, record_id, embedding) VALUES (?, ?, ?)",
            (doc.collection, doc.record_id, serialize_embedding(embedding)),
        )

    def _backfill_fts(self) -> None:
        """Rebuild FTS index from records if out of sync."""
        with self._connect() as connection:
            placeholders = ",".join(f"'{c}'" for c in _FTS_COLLECTIONS)
            records_count = connection.execute(
                f"SELECT COUNT(*) FROM records WHERE collection IN ({placeholders})"
            ).fetchone()[0]
            fts_count = connection.execute("SELECT COUNT(*) FROM records_fts").fetchone()[0]
            if fts_count >= records_count:
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
        """Backfill missing vector embeddings. Skips records that already have embeddings."""
        from agentmesh.embedding import EMBEDDING_ENABLED

        if not EMBEDDING_ENABLED:
            return
        with self._connect() as connection:
            placeholders = ",".join(f"'{c}'" for c in _FTS_COLLECTIONS)
            missing = connection.execute(
                f"""
                SELECT r.collection, r.id, r.payload FROM records r
                WHERE r.collection IN ({placeholders})
                  AND NOT EXISTS (
                    SELECT 1 FROM records_vec rv
                    WHERE rv.collection = r.collection AND rv.record_id = r.id
                  )
                ORDER BY r.created_order
                LIMIT 100
                """
            ).fetchall()
            if not missing:
                return
            for row in missing:
                collection = row["collection"]
                model_cls = _FTS_COLLECTION_MODELS.get(collection)
                if model_cls is None:
                    continue
                item = model_cls.model_validate_json(row["payload"])
                self._sync_vec(connection, collection, item)

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

    def add_chat_message(self, message: ChatMessage) -> ChatMessage:
        self._upsert("chat_messages", message)
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

    def save_user_memory_item(self, item: UserMemoryItem) -> UserMemoryItem:
        self._upsert("user_memory_items", item)
        return item

    def add_source(self, source: Source) -> Source:
        self._upsert("sources", source)
        return source

    def add_document(self, document: DocumentRecord) -> DocumentRecord:
        self._upsert("documents", document)
        return document

    def save_document(self, document: DocumentRecord) -> DocumentRecord:
        self._upsert("documents", document)
        return document

    def save_document_parse_job(self, job: DocumentParseJob) -> DocumentParseJob:
        self._upsert("document_parse_jobs", job)
        return job

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
        return [message for message in self.chat_messages if message.thread_id == thread_id]

    def list_thread_turn_traces(self, thread_id: str) -> list[ChatTurnTrace]:
        traces = [trace for trace in self.chat_turn_traces if trace.thread_id == thread_id]
        return sorted(traces, key=lambda trace: trace.created_at)

    def list_chat_threads(self, user_id: str) -> list[ChatThread]:
        threads = [thread for thread in self.chat_threads if thread.user_id == user_id]
        return sorted(
            threads,
            key=lambda thread: (thread.updated_at, thread.created_at, thread.id),
            reverse=True,
        )


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
        if not needle:
            return []

        scope_values = [s.value for s in allowed_scopes]
        placeholders = ",".join("?" for _ in scope_values)
        allowed_collections: set[str] | None = None
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
            )
            if not fts_rows:
                fts_rows = self._fts_like_fallback(
                    connection,
                    needle,
                    scope_values,
                    placeholders,
                    allowed_collections,
                    allowed_record_ids,
                )
            vec_rows = self._vec_search(
                connection,
                needle,
                scope_values,
                placeholders,
                allowed_collections,
                allowed_record_ids,
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
                if item.scope == Scope.PROJECT and user_id and item.project_id:
                    if not self._user_can_access_project(user_id, item.project_id):
                        continue
                if item.team_id and user_id and item.scope in (Scope.TEAM_ACCEPTED, Scope.TEAM_CANDIDATE):
                    if not self._user_in_team(user_id, item.team_id):
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
                if item is None:
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
                ORDER BY score
                LIMIT 200
                """,
                [fts_query, *scope_values, *collection_values, *record_id_values],
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
        return connection.execute(
            f"""
            SELECT collection, record_id, scope, workspace_id, project_id,
                   user_id, created_at
            FROM records_fts
            WHERE (title LIKE ? OR body LIKE ?)
              AND scope IN ({placeholders})
              {collection_clause}
              {record_id_clause}
            LIMIT 200
            """,
            [like_pattern, like_pattern, *scope_values, *collection_values, *record_id_values],
        ).fetchall()

    @staticmethod
    def _vec_search(
        connection: sqlite3.Connection,
        needle: str,
        scope_values: list[str],
        placeholders: str,
        allowed_collections: set[str] | None = None,
        allowed_record_ids: set[str] | None = None,
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
        rows = connection.execute(
            f"""
            SELECT rv.collection, rv.record_id, rv.embedding,
                   rf.scope, rf.workspace_id, rf.project_id, rf.user_id, rf.created_at
            FROM records_vec rv
            JOIN records_fts rf ON rv.collection = rf.collection AND rv.record_id = rf.record_id
            WHERE rf.scope IN ({placeholders})
              {collection_clause}
              {record_id_clause}
            """,
            [*scope_values, *collection_values, *record_id_values],
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

    def _user_can_access_project(self, user_id: str, project_id: str) -> bool:
        project = self.get_project(project_id)
        if project is None:
            return False
        if not project.member_ids:
            return True
        user = self.get_user(user_id)
        if user and user.role in (UserRole.ADMIN, UserRole.TEAM_LEAD):
            return True
        return user_id in project.member_ids

    def _user_in_team(self, user_id: str, team_id: str) -> bool:
        user = self.get_user(user_id)
        if user and user.role in (UserRole.ADMIN, UserRole.TEAM_LEAD):
            return True
        memberships = self.list_team_memberships(team_id=team_id, user_id=user_id)
        return len(memberships) > 0


store = SQLiteStore()
