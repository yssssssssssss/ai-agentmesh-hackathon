from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as dt_date
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def now_utc() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Scope(StrEnum):
    PRIVATE = "private"
    PROJECT = "project"
    TEAM_CANDIDATE = "team_candidate"
    TEAM_ACCEPTED = "team_accepted"


class MemoryStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    DEPRECATED = "deprecated"
    EXPIRED = "expired"


class MemoryLayer(StrEnum):
    SHORT_TERM = "short_term"
    MID_TERM = "mid_term"
    LONG_TERM = "long_term"

class MemorySearchScope(StrEnum):
    AUTO = "auto"
    PERSONAL = "personal"
    PROJECT = "project"
    TEAM = "team"


class MemoryKind(StrEnum):
    PERSONAL = "personal"
    PROJECT = "project"
    TEAM = "team"


class TaskStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_EXTERNAL_AGENT = "waiting_external_agent"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"


class CollaborationStage(StrEnum):
    DISCUSSION = "discussion"
    EXECUTION = "execution"
    REVIEW = "review"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class BlackboardPostType(StrEnum):
    REQUEST = "request"
    EVIDENCE = "evidence"
    RISK = "risk"
    DIGEST = "digest"
    DECISION = "decision"
    HANDOFF = "handoff"
    ARCHIVE = "archive"
    CORRECTION = "correction"
    MEMORY_CANDIDATE = "memory_candidate"
    MARKETPLACE_SIGNAL = "marketplace_signal"
    MARKETPLACE_MATCH = "marketplace_match"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Intent(StrEnum):
    GENERAL_CHAT = "general_chat"
    ASK_MEMORY = "ask_memory"
    GENERATE_BRIEF = "generate_brief"
    RECORD_PRIVATE_NOTE = "record_private_note"
    REQUEST_EXTERNAL_RESEARCH = "request_external_research"
    REQUEST_DATA_QUERY = "request_data_query"
    REQUEST_RISK_REVIEW = "request_risk_review"
    CREATE_MEMORY_CANDIDATE = "create_memory_candidate"
    ASK_SYSTEM_INFO = "ask_system_info"


class Workspace(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ws"))
    name: str
    description: str
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prj"))
    workspace_id: str
    name: str
    goal: str
    member_ids: list[str] = Field(default_factory=list)
    status: str = "active"
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)


class ProjectCreateRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=1000)


class User(BaseModel):
    id: str = Field(default_factory=lambda: new_id("usr"))
    workspace_id: str
    default_project_id: str
    name: str
    role: str
    status: str = "active"
    personal_agent_id: str
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class UserRole(StrEnum):
    USER = "user"
    TEAM_LEAD = "team_lead"
    ADMIN = "admin"


class Team(BaseModel):
    id: str = Field(default_factory=lambda: new_id("team"))
    workspace_id: str
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class TeamMembership(BaseModel):
    id: str = Field(default_factory=lambda: new_id("team_mem"))
    team_id: str
    user_id: str
    role: UserRole = UserRole.USER
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class AuthCredential(BaseModel):
    id: str
    user_id: str
    password_hash: str
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class AuthSession(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sess"))
    user_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=now_utc)
    revoked_at: datetime | None = None


class Agent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("agent"))
    workspace_id: str
    name: str
    agent_type: str
    description: str
    status: str = "online"
    runtime_status: str = "idle"
    current_task_id: str | None = None
    current_task_title: str | None = None
    last_active_at: datetime | None = None
    model_id: str | None = None
    owner_user_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ModelDefinition(BaseModel):
    id: str
    label: str
    provider: str
    model_name: str
    enabled: bool = True
    configured: bool = False
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ToolDefinition(BaseModel):
    id: str
    name: str
    description: str
    category: str
    enabled: bool = True
    risk_level: str = "low"
    provider: str = "system"
    external_name: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class AgentToolGrant(BaseModel):
    id: str = Field(default_factory=lambda: new_id("grant"))
    agent_id: str
    tool_id: str
    enabled: bool = True
    granted_by: str
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class AgentMemoryBinding(BaseModel):
    """Constrains which memory an Agent can access during search."""

    id: str = Field(default_factory=lambda: new_id("amb"))
    agent_id: str
    allowed_scopes: list[Scope] = Field(default_factory=lambda: [Scope.PRIVATE, Scope.PROJECT, Scope.TEAM_ACCEPTED])
    allowed_memory_types: list[str] = Field(default_factory=list)
    allowed_project_ids: list[str] = Field(default_factory=list)
    max_results_per_query: int = 10
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ScheduledAgentTaskDefinition(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sched"))
    agent_id: str
    title: str
    prompt: str
    schedule: str
    enabled: bool = True
    created_by: str
    last_run_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class RiskPolicyRule(BaseModel):
    id: str = Field(default_factory=lambda: new_id("risk_rule"))
    rule_id: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    signal: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=300)
    decision: str = Field(default="needs_review", min_length=1, max_length=40)
    enabled: bool = True
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class PermissionPolicyRule(BaseModel):
    id: str = Field(default_factory=lambda: new_id("perm_rule"))
    role: UserRole
    action: str = Field(min_length=1, max_length=120)
    effect: str = Field(default="allow", pattern="^(allow|deny)$")
    enabled: bool = True
    description: str = Field(default="", max_length=300)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ChatThread(BaseModel):
    id: str = Field(default_factory=lambda: new_id("thread"))
    workspace_id: str
    project_id: str
    user_id: str
    title: str
    status: str = "active"
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class Source(BaseModel):
    id: str = Field(default_factory=lambda: new_id("src"))
    title: str
    source_type: str
    reference: str
    created_at: datetime = Field(default_factory=now_utc)


class DocumentRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    title: str
    file_name: str
    content_type: str
    text: str
    source: Source
    workspace_id: str
    project_id: str
    uploaded_by: str
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)


class DocumentUpdateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class DocumentParseJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc_job"))
    file_name: str
    content_type: str
    workspace_id: str
    project_id: str
    uploaded_by: str
    status: str = "queued"
    document_id: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ExecutionLock(BaseModel):
    owner_agent_id: str = Field(min_length=1, max_length=120)
    owner_label: str = Field(min_length=1, max_length=120)
    acquired_at: datetime = Field(default_factory=now_utc)
    released_at: datetime | None = None
    released_reason: str | None = Field(default=None, max_length=200)

    @property
    def active(self) -> bool:
        return self.released_at is None


class StructuredHandoffPacket(BaseModel):
    goal: str = Field(min_length=1, max_length=240)
    current_result: str = Field(min_length=1, max_length=800)
    done_when: str = Field(min_length=1, max_length=240)
    next_owner_agent_id: str = Field(min_length=1, max_length=120)
    blockers: list[str] = Field(default_factory=list)
    requires_input_from: list[str] = Field(default_factory=list)


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    thread_id: str
    role: ChatRole
    content: str
    scope: Scope = Scope.PRIVATE
    sources: list[Source] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now_utc)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    thread_id: str
    intent: Intent
    status: TaskStatus = TaskStatus.CREATED
    collaboration_stage: CollaborationStage = CollaborationStage.DISCUSSION
    current_owner_agent_id: str | None = None
    current_owner_label: str | None = None
    execution_lock: ExecutionLock | None = None
    done_when: str | None = None
    title: str
    steps: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class BlackboardPost(BaseModel):
    id: str = Field(default_factory=lambda: new_id("bb"))
    task_id: str
    post_type: BlackboardPostType
    actor: str
    title: str
    content: str
    scope: Scope
    permission: str
    status: str = "published"
    sources: list[Source] = Field(default_factory=list)
    read_by_agents: list[str] = Field(default_factory=list)
    related_post_id: str | None = None
    collaboration_stage: CollaborationStage = CollaborationStage.DISCUSSION
    current_owner_agent_id: str | None = None
    current_owner_label: str | None = None
    execution_lock: ExecutionLock | None = None
    done_when: str | None = None
    handoff: StructuredHandoffPacket | None = None
    created_at: datetime = Field(default_factory=now_utc)


class AutoBlackboardPostRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("auto_bb"))
    task_id: str
    post_type: BlackboardPostType
    actor: str
    title: str
    content: str
    scope: Scope = Scope.PROJECT
    permission: str = "project_visible"
    status: str = "queued"
    related_post_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    published_at: datetime | None = None
    blackboard_post_id: str | None = None


class ActivityLog(BaseModel):
    id: str = Field(default_factory=lambda: new_id("act"))
    actor: str
    title: str
    summary: str
    category: str
    scope: Scope = Scope.PRIVATE
    workspace_id: str | None = None
    project_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)


class InboxItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inbox"))
    title: str
    summary: str
    item_type: str
    scope: Scope
    user_id: str | None = None
    status: str = "open"
    workspace_id: str | None = None
    project_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    acknowledged_at: datetime | None = None
    snooze_until: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mem"))
    title: str
    summary: str
    memory_type: str
    scope: Scope
    status: MemoryStatus = MemoryStatus.PROPOSED
    workspace_id: str | None = None
    project_id: str | None = None
    team_id: str | None = None
    sources: list[Source] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)


class UserMemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("umem"))
    user_id: str
    layer: MemoryLayer
    title: str
    summary: str
    source_kind: str = Field(min_length=1, max_length=80)
    memory_type: str = Field(default="note", min_length=1, max_length=80)
    memory_date: dt_date = Field(default_factory=lambda: now_utc().date())
    sensitivity: str = Field(default="normal", min_length=1, max_length=20)
    scope: Scope = Scope.PRIVATE
    workspace_id: str
    project_id: str | None = None
    source_thread_id: str | None = None
    source_task_id: str | None = None
    sources: list[Source] = Field(default_factory=list)
    status: str = "active"
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("audit"))
    actor: str
    action: str
    target_type: str
    target_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)


class ConsentGrant(BaseModel):
    """A per-person standing consent: grantor allows grantee's twin to query theirs.

    Absence of an active grant means deny-auto — every delegated query routes
    through the confirmation gate. Revocation is prospective (sets revoked_at).
    """

    id: str = Field(default_factory=lambda: new_id("consent"))
    grantor_id: str
    grantee_id: str
    workspace_id: str
    created_at: datetime = Field(default_factory=now_utc)
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class ContributionPoint(BaseModel):
    """Record-only shadow contribution point. Not redeemable in this phase."""

    id: str = Field(default_factory=lambda: new_id("contrib"))
    awarded_to_id: str
    awarded_by_id: str
    reason: str = ""
    redeemable: bool = False
    workspace_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)


class MemoryRelation(BaseModel):
    """A lineage edge from a memory item to the source it was derived from."""

    id: str = Field(default_factory=lambda: new_id("memrel"))
    from_memory_id: str
    to_source_id: str
    relation_type: str = "derived_from"
    created_at: datetime = Field(default_factory=now_utc)


class MarketParticipation(BaseModel):
    """Per-user opt-in to the autonomous market. Absent record = not participating.

    On top of the global master switch: even when the market is globally enabled, a user's
    twins only publish signals / answer peers when that user has opted in.
    """

    id: str  # == user_id (one record per user)
    user_id: str
    enabled: bool = False
    updated_at: datetime = Field(default_factory=now_utc)


class MarketParticipationRequest(BaseModel):
    enabled: bool


class DelegatedAnswerStatus(StrEnum):
    ANSWERED = "answered"
    AWAITING_CONFIRM = "awaiting_confirm"
    DENIED = "denied"


class AnswerConfidence(StrEnum):
    UNSET = ""
    NONE = "none"
    LOW = "low"
    HIGH = "high"


class DelegatedAnswer(BaseModel):
    """Result of a cross-person delegated query (④ answer-only gateway).

    Only the abstracted ``answer`` and ``citations`` (source titles) ever cross
    back to the asker — never the target's raw personal-memory bodies.
    """

    status: DelegatedAnswerStatus
    answer: str | None = None
    citations: list[Source] = Field(default_factory=list)
    confidence: AnswerConfidence = AnswerConfidence.UNSET
    inbox_item: InboxItem | None = None


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class LoginRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=200)


class UserCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: UserRole = UserRole.USER
    password: str = Field(min_length=8, max_length=200)
    workspace_id: str | None = None
    default_project_id: str | None = None


class UserUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: UserRole | None = None
    status: str | None = Field(default=None, min_length=1, max_length=40)
    workspace_id: str | None = None
    default_project_id: str | None = None


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    workspace_id: str | None = None


class TeamMembershipRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    role: UserRole = UserRole.USER


class ChatThreadCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class InboxUpdateRequest(BaseModel):
    status: str | None = Field(default=None, min_length=1, max_length=40)
    ttl_minutes: int | None = Field(default=None, ge=1, le=7 * 24 * 60)
    snooze_until: datetime | None = None


class MemoryCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    memory_type: str = Field(min_length=1, max_length=80)
    scope: Scope = Scope.TEAM_CANDIDATE
    workspace_id: str | None = None
    project_id: str | None = None


class MemoryUpdateRequest(BaseModel):
    status: MemoryStatus | None = None
    scope: Scope | None = None


class UserMemoryCreateRequest(BaseModel):
    layer: MemoryLayer = MemoryLayer.SHORT_TERM
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    source_kind: str = Field(default="manual", min_length=1, max_length=80)
    memory_type: str = Field(default="manual", min_length=1, max_length=80)
    memory_date: dt_date | None = None
    project_id: str | None = None


class DailyMemorySummaryRequest(BaseModel):
    date: dt_date | None = None
    project_id: str | None = None


class ProjectMemorySummaryRequest(BaseModel):
    project_id: str | None = None


class ProjectArchiveRequest(BaseModel):
    project_id: str | None = None


class GroupMemorySummaryRequest(BaseModel):
    project_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    memory_type: str = Field(default="group_chat_summary", min_length=1, max_length=80)
    memory_date: dt_date | None = None
    source_thread_id: str | None = Field(default=None, max_length=120)


class DataSourceQueryRequest(BaseModel):
    connector_name: str = Field(min_length=1, max_length=120)
    operation: str = Field(default="query", min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)


class BlackboardPostCreateRequest(BaseModel):
    post_type: BlackboardPostType
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    actor: str = Field(default="personal_agent", min_length=1, max_length=120)
    scope: Scope = Scope.PROJECT
    permission: str = Field(default="project_visible", min_length=1, max_length=80)
    related_post_id: str | None = None
    collaboration_stage: CollaborationStage = CollaborationStage.DISCUSSION
    done_when: str | None = Field(default=None, max_length=240)
    handoff: StructuredHandoffPacket | None = None


class ExecutionLockAcquireRequest(BaseModel):
    owner_agent_id: str = Field(min_length=1, max_length=120)
    owner_label: str | None = Field(default=None, max_length=120)


class ExecutionLockReleaseRequest(BaseModel):
    reason: str = Field(default="manual_release", min_length=1, max_length=200)


class BlackboardHandoffRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=240)
    current_result: str = Field(min_length=1, max_length=800)
    done_when: str = Field(min_length=1, max_length=240)
    next_owner_agent_id: str = Field(min_length=1, max_length=120)
    blockers: list[str] = Field(default_factory=list)
    requires_input_from: list[str] = Field(default_factory=list)


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    capabilities: list[str] | None = None


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    capabilities: list[str] = Field(default_factory=list)


class AgentModelUpdateRequest(BaseModel):
    model_id: str | None = Field(default=None, max_length=120)


class AgentToolsUpdateRequest(BaseModel):
    tool_ids: list[str] = Field(default_factory=list)


class ScheduledAgentTaskCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=2000)
    schedule: str = Field(min_length=1, max_length=120)
    enabled: bool = True


class ScheduledAgentTaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=1, max_length=2000)
    schedule: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None


class RiskPolicyRuleCreateRequest(BaseModel):
    rule_id: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    signal: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=300)
    decision: str = Field(default="needs_review", min_length=1, max_length=40)
    enabled: bool = True


class RiskPolicyRuleUpdateRequest(BaseModel):
    rule_id: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    signal: str | None = Field(default=None, min_length=1, max_length=200)
    message: str | None = Field(default=None, min_length=1, max_length=300)
    decision: str | None = Field(default=None, min_length=1, max_length=40)
    enabled: bool | None = None


class PermissionPolicyRuleCreateRequest(BaseModel):
    role: UserRole
    action: str = Field(min_length=1, max_length=120)
    effect: str = Field(default="allow", pattern="^(allow|deny)$")
    enabled: bool = True
    description: str = Field(default="", max_length=300)


class PermissionPolicyRuleUpdateRequest(BaseModel):
    role: UserRole | None = None
    action: str | None = Field(default=None, min_length=1, max_length=120)
    effect: str | None = Field(default=None, pattern="^(allow|deny)$")
    enabled: bool | None = None
    description: str | None = Field(default=None, max_length=300)


class SearchResult(BaseModel):
    id: str
    result_type: str
    title: str
    summary: str
    scope: Scope
    sources: list[Source] = Field(default_factory=list)
    created_at: datetime
    project_id: str | None = None
    team_id: str | None = None

class RetrievedMemoryEvidence(BaseModel):
    result_id: str
    result_type: str
    memory_kind: MemoryKind
    citation_label: str
    title: str
    summary: str
    rank: int
    scope: Scope
    project_id: str | None = None
    team_id: str | None = None
    sources: list[Source] = Field(default_factory=list)


class MemorySearchTrace(BaseModel):
    requested_scope: MemorySearchScope = MemorySearchScope.AUTO
    personal_count: int = 0
    project_count: int = 0
    team_count: int = 0
    results: list[RetrievedMemoryEvidence] = Field(default_factory=list)


class BootstrapMetrics(BaseModel):
    personal_activity_count: int
    external_activity_count: int
    memory_candidate_count: int
    source_count: int
    inbox_open_count: int


class BootstrapState(BaseModel):
    workspace: Workspace
    project: Project
    user: User
    users: list[User]
    teams: list[Team] = Field(default_factory=list)
    team_memberships: list[TeamMembership] = Field(default_factory=list)
    agents: list[Agent]
    metrics: BootstrapMetrics


class RetrievalMetrics(BaseModel):
    """Tracks search recall quality for optimization feedback loop."""

    id: str = Field(default_factory=lambda: new_id("rmet"))
    query_text: str
    user_id: str
    results_returned: int
    results_cited: int = 0
    source_ids_returned: list[str] = Field(default_factory=list)
    source_ids_cited: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    llm_used: bool = False
    requested_scope: MemorySearchScope = MemorySearchScope.AUTO
    task_id: str | None = None
    thread_id: str | None = None
    assistant_message_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)


class SkillStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class LearnedSkill(BaseModel):
    """A reusable workflow pattern extracted from repeated successful traces."""

    id: str = Field(default_factory=lambda: new_id("skill"))
    title: str
    trigger_pattern: str
    steps: list[str] = Field(default_factory=list)
    validation_rules: list[str] = Field(default_factory=list)
    source_workflow_ids: list[str] = Field(default_factory=list)
    version: int = 1
    status: SkillStatus = SkillStatus.DRAFT
    scope: Scope = Scope.PRIVATE
    workspace_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    occurrence_count: int = 0
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ChatWorkflowTrace(BaseModel):
    intent: Intent
    confidence: float
    source: str
    selected_workflow: str
    persisted: bool
    llm_used: bool
    fallback_reason: str | None = None


class ChatTurnTrace(BaseModel):
    id: str = Field(default_factory=lambda: new_id("trace"))
    thread_id: str
    user_message_id: str
    assistant_message_id: str
    task_id: str | None = None
    intent: Intent
    source: str
    selected_workflow: str
    persisted: bool
    llm_used: bool
    fallback_reason: str | None = None
    steps: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    memory_search: MemorySearchTrace | None = None
    created_at: datetime = Field(default_factory=now_utc)


class ChatResponse(BaseModel):
    thread_id: str
    user_message: ChatMessage
    assistant_message: ChatMessage
    task: Task | None = None
    request_post: BlackboardPost | None = None
    evidence_post: BlackboardPost | None = None
    risk_post: BlackboardPost | None = None
    activity_logs: list[ActivityLog]
    inbox_items: list[InboxItem]
    memory_items: list[MemoryItem]
    user_memory_items: list[UserMemoryItem] = Field(default_factory=list)
    workflow_trace: ChatWorkflowTrace | None = None
    turn_trace: ChatTurnTrace | None = None


# --- API Response Wrappers ---


class ItemResponse(BaseModel):
    """单条记录响应包装。"""
    item: Any


class ItemsResponse(BaseModel):
    """列表响应包装。"""
    items: list[Any]


class PaginatedResponse(BaseModel):
    """分页列表响应包装。"""
    items: list[Any]
    total: int
    page: int
    page_size: int
    has_next: bool


class StatusResponse(BaseModel):
    """简单状态响应。"""
    status: str


class UserResponse(BaseModel):
    """用户信息响应。"""
    user: User


class AuditListResponse(BaseModel):
    """审计事件列表响应。"""
    items: list[AuditEvent]
    total: int
    limit: int
    counts: dict[str, int]


class ActivityTodayResponse(BaseModel):
    """今日活动响应。"""
    personal: list[ActivityLog]
    external: list[ActivityLog]


class BlackboardTaskCard(BaseModel):
    """黑板任务卡片。"""
    task: Task
    latest_post: BlackboardPost | None = None
    stage: CollaborationStage | None = None
    owner: str | None = None
    done_when: str | None = None
    active_lock: ExecutionLock | None = None
    post_count: int = 0
    initiator_user_id: str | None = None
    initiated_by_current_user: bool = False
    claimed_by_personal_agent: bool = False
    upstream_agents: list[str] = Field(default_factory=list)
    downstream_agents: list[str] = Field(default_factory=list)


class BlackboardTaskCardsResponse(BaseModel):
    """黑板任务卡片列表响应。"""
    items: list[BlackboardTaskCard]


class DataAgentQueryResponse(BaseModel):
    """数据 Agent 查询响应。"""
    result: Any
    post: BlackboardPost


class O2SyncResponse(BaseModel):
    """O2 工具同步响应。"""
    items: list[ToolDefinition]
    count: int


class DrainAutoPostsResponse(BaseModel):
    """自动帖子排空响应。"""
    posted: int
    items: list[AutoBlackboardPostRequest]


class ProviderHealthCheckResponse(BaseModel):
    """Provider 健康检查响应。"""
    overall: str
    providers: list[dict[str, Any]]
