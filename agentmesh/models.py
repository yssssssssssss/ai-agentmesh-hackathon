from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from datetime import date as dt_date
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.provider_status import ProviderStatus
from agentmesh.task_routing.contracts import CompletionCheckResult, TaskRoutingResult


def now_utc() -> datetime:
    return datetime.now(UTC)


MEMORY_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def memory_date_for(instant: datetime | None = None) -> dt_date:
    value = instant or now_utc()
    return value.astimezone(MEMORY_TIME_ZONE).date()


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
    oauth_provider: str | None = None
    oauth_subject: str | None = None
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


class SkillPackageStatus(StrEnum):
    QUARANTINED = "quarantined"
    ACTIVE = "active"
    DISABLED = "disabled"


class SkillPackage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("skill_package"))
    name: str
    version: str
    source_uri: str
    content_hash: str
    root_path: str
    status: SkillPackageStatus = SkillPackageStatus.QUARANTINED
    resources: list[str] = Field(default_factory=list)
    diagnostics: list[dict[str, str]] = Field(default_factory=list)
    license: str | None = None
    compatibility: str | None = None
    created_by: str
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class SkillSourceScope(StrEnum):
    BUILTIN = "builtin"
    WORKSPACE = "workspace"
    PROJECT = "project"


class SkillMemoryWritePolicy(StrEnum):
    NONE = "none"
    PRIVATE_SHORT_TERM = "private_short_term"
    PROJECT_CANDIDATE = "project_candidate"


class SkillActivationPolicy(StrEnum):
    EXPLICIT_ONLY = "explicit_only"
    MODEL_ALLOWED = "model_allowed"


class SkillLifecycleStage(StrEnum):
    PRE_DESIGN = "pre_design"
    DURING_DESIGN = "during_design"
    POST_DESIGN = "post_design"
    PLATFORM = "platform"


class SkillCapabilityType(StrEnum):
    RETRIEVAL = "retrieval"
    RESEARCH = "research"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"
    PLANNING = "planning"
    GENERATION = "generation"
    TRANSFORMATION = "transformation"
    REVIEW = "review"
    DELIVERY = "delivery"
    KNOWLEDGE = "knowledge"
    PLATFORM = "platform"


class SkillSideEffect(StrEnum):
    READ = "read"
    DRAFT = "draft"
    LOCAL_WRITE = "local_write"
    EXTERNAL_WRITE = "external_write"


class SkillDefinition(BaseModel):
    """A parsed, versioned Agent Skills definition available to AgentMesh."""

    id: str
    name: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1024)
    instructions: str
    source_path: str
    source_scope: SkillSourceScope
    content_hash: str
    version: str = "1"
    license: str | None = None
    compatibility: str | None = Field(default=None, max_length=500)
    metadata: dict[str, str] = Field(default_factory=dict)
    host_fields: dict[str, Any] = Field(default_factory=dict)
    requested_tools: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    argument_hint: str | None = None
    requires_input: bool = True
    activation_policy: SkillActivationPolicy = SkillActivationPolicy.EXPLICIT_ONLY
    memory_write_policy: SkillMemoryWritePolicy = SkillMemoryWritePolicy.NONE
    enabled: bool = True
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    @property
    def command(self) -> str:
        return f"${self.name}"


class SkillBinding(BaseModel):
    """Enables a Skill for an Agent without mutating the immutable parsed definition."""

    id: str = Field(default_factory=lambda: new_id("skill_binding"))
    agent_id: str
    skill_id: str
    enabled: bool = True
    aliases: list[str] = Field(default_factory=list)
    granted_by: str
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class SkillCapabilityProfile(BaseModel):
    """Planner-safe metadata. It never contains Skill instructions or credentials."""

    id: str
    skill_id: str
    skill_name: str = Field(min_length=1, max_length=64)
    skill_title: str = Field(default="", max_length=160)
    skill_aliases: list[str] = Field(default_factory=list, max_length=10)
    skill_version: str = Field(min_length=1, max_length=40)
    skill_content_hash: str = Field(min_length=1, max_length=128)
    profile_version: str = Field(min_length=1, max_length=40)
    profile_content_hash: str = Field(min_length=1, max_length=128)
    display_description: str | None = Field(default=None, max_length=100)
    primary_stage: SkillLifecycleStage
    lifecycle_tags: list[SkillLifecycleStage] = Field(default_factory=list)
    capability_type: SkillCapabilityType
    input_kinds: list[str] = Field(default_factory=list)
    output_kinds: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    negative_examples: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    task_types: list[str] = Field(default_factory=list)
    archetypes: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    required_resources: list[str] = Field(default_factory=list)
    input_schema_ref: str | None = Field(default=None, max_length=240)
    output_schema_ref: str | None = Field(default=None, max_length=240)
    produces_factual_claims: bool = False
    report_policy: Literal["never", "on_request", "default"] = "never"
    cost_level: Literal["low", "medium", "high"] = "low"
    risk_level: Literal["low", "medium", "high"] = "low"
    owner: str = Field(default="platform", min_length=1, max_length=120)
    side_effect: SkillSideEffect = SkillSideEffect.READ
    planner_eligible: bool = True
    updated_at: datetime = Field(default_factory=now_utc)

    def search_text(self, title: str = "", description: str = "") -> str:
        title = title or self.skill_title
        description = description or self.display_description or ""
        return " ".join(
            [
                self.skill_name,
                title,
                description,
                *self.skill_aliases,
                self.primary_stage.value,
                self.capability_type.value,
                *self.input_kinds,
                *self.output_kinds,
                *self.task_types,
                *self.archetypes,
                *self.examples,
            ]
        )


class SkillCatalogItem(BaseModel):
    id: str
    command: str
    title: str
    description: str
    usage: str
    placeholder: str
    aliases: list[str] = Field(default_factory=list)
    requires_input: bool = True
    source: SkillSourceScope
    version: str
    activation_policy: SkillActivationPolicy
    enabled: bool
    binding_enabled: bool
    planner_eligible: bool
    readiness: Literal["ready", "unavailable"]
    execution_readiness: Literal["complete", "tool_limited", "unavailable"] = "complete"
    missing_tools: list[str] = Field(default_factory=list)
    primary_stage: SkillLifecycleStage | None = None
    capability_type: SkillCapabilityType | None = None
    input_kinds: list[str] = Field(default_factory=list)
    output_kinds: list[str] = Field(default_factory=list)
    side_effect: SkillSideEffect | None = None


class SkillCatalogResponse(BaseModel):
    items: list[SkillCatalogItem]


class SkillCatalogItemResponse(BaseModel):
    item: SkillCatalogItem


class SkillMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000, pattern=r"\S")
    limit: int = Field(default=5, ge=1, le=5)


class SkillMatchItem(BaseModel):
    skill_id: str
    skill_name: str
    command: str
    title: str
    description: str
    primary_stage: SkillLifecycleStage | None = None
    score: float = Field(ge=0)
    reason: str
    planner_eligible: bool
    readiness: Literal["ready", "unavailable"]
    execution_readiness: Literal["complete", "tool_limited", "unavailable"] = "complete"
    missing_tools: list[str] = Field(default_factory=list)


class SkillMatchResponse(BaseModel):
    items: list[SkillMatchItem]
    mode: Literal["lexical", "hybrid", "llm_reranked", "fallback"] = "lexical"
    clarification: str | None = Field(default=None, max_length=300)
    diagnostics: list[str] = Field(default_factory=list)


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
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False})
    output_schema: dict[str, Any] | None = None
    side_effect: Literal["read", "write", "external", "idempotent_write", "non_idempotent_write"] = "read"
    implementation_id: str | None = Field(default=None, max_length=240)
    implementation_version: str = Field(default="1", min_length=1, max_length=80)
    idempotency_support: Literal["provider", "reconcile_only", "none"] = "none"
    approval_required: bool = False
    evidence_class: Literal["provider_summary", "page_observation", "document", "internal"] | None = None
    health_ttl_seconds: int = Field(default=60, ge=1, le=300)
    timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    sdk_metadata: dict[str, Any] = Field(default_factory=dict)
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
    pinned: bool = False
    status: str = "active"
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ChatWorkflowTrace(BaseModel):
    intent: Intent
    confidence: float
    source: str
    selected_workflow: str
    persisted: bool
    llm_used: bool
    requested_provider: str | None = None
    actual_provider: str | None = None
    requested_model: str | None = None
    actual_model: str | None = None
    provider_mode: str | None = Field(default=None, pattern="^(real|fallback)$")
    latency_ms: float | None = Field(default=None, ge=0)
    fallback_reason: str | None = None
    model_fallback_reason: str | None = None


class Source(BaseModel):
    id: str = Field(default_factory=lambda: new_id("src"))
    title: str
    source_type: str
    reference: str
    workspace_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    run_id: str | None = None
    skill_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)


class DocumentJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


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
    version: int = Field(default=1, ge=1)
    expected_chunks: int = Field(default=0, ge=0)
    completed_chunks: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class DocumentUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=100_000)


class DocumentParseJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc_job"))
    file_name: str
    content_type: str
    workspace_id: str
    project_id: str
    uploaded_by: str
    status: DocumentJobStatus = DocumentJobStatus.QUEUED
    document_id: str | None = None
    version: int = Field(default=1, ge=1)
    expected_chunks: int = Field(default=0, ge=0)
    completed_chunks: int = Field(default=0, ge=0)
    error: str | None = None
    error_type: str | None = None
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
    workflow_trace: ChatWorkflowTrace | None = None
    created_at: datetime = Field(default_factory=now_utc)


class ChatThreadListResponse(BaseModel):
    items: list[ChatThread]


class ChatThreadDetailResponse(BaseModel):
    thread: ChatThread
    messages: list[ChatMessage]
    turn_traces: list[ChatTurnTrace]
    latest_research_run_id: str | None = None


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
    metadata: dict[str, str] = Field(default_factory=dict)
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
    submitted_by_user_id: str | None = None
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


class AutoBlackboardPostCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=120)
    post_type: BlackboardPostType
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    scope: Scope = Scope.PROJECT
    permission: str = Field(default="project_visible", min_length=1, max_length=80)
    related_post_id: str | None = None


class ActivityLog(BaseModel):
    id: str = Field(default_factory=lambda: new_id("act"))
    actor: str
    user_id: str | None = None
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
    owner_user_id: str | None = None
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
    memory_date: dt_date = Field(default_factory=memory_date_for)
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
    workspace_id: str | None = None
    project_id: str | None = None
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


class MarketMePresence(BaseModel):
    """Header presence tiles for the current user's market page."""

    memory_count: int
    signal_on: bool
    signal_refreshed_at: datetime | None = None
    received_count: int
    given_count: int


class MarketMeGraphNode(BaseModel):
    """A node in the personal market knowledge graph."""

    id: str
    name: str
    group: str = ""
    size: int = 20
    tie_role: Literal["me", "incoming", "outgoing", "peer"] = "peer"
    offer: str = ""
    need: str = ""
    ties: int = 0


class MarketMeGraphEdge(BaseModel):
    """A directed relation between two graph nodes.

    Uses ``from_`` with a ``from`` alias because ``from`` is a Python keyword.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    direction: Literal["incoming", "outgoing", "peer"] = "peer"


class MarketMeTimelineItem(BaseModel):
    """One entry in the personal market timeline (my request / received / given)."""

    id: str
    at: datetime
    category: Literal["request", "incoming", "outgoing"]
    title: str
    counterpart: dict[str, str] | None = None
    topic: str = ""
    status: Literal["answered", "awaiting_confirm", "denied", "open"] = "open"
    sensitivity: Literal["low", "medium", "high"] = "low"
    meta: str = ""
    detail: str = ""
    # For awaiting_confirm incoming/outgoing rows: the inbox item id the target resolves.
    action_ref: str = ""


class MarketMeWorkerState(BaseModel):
    running: bool
    interval_seconds: int
    last_run_at: str | None = None


class MarketMeGraph(BaseModel):
    nodes: list[MarketMeGraphNode]
    edges: list[MarketMeGraphEdge]


class MarketMeUser(BaseModel):
    id: str
    name: str
    group: str = ""


class MarketMeView(BaseModel):
    """Aggregated response for GET /api/market/me."""

    user: MarketMeUser
    presence: MarketMePresence
    workers: dict[str, MarketMeWorkerState]
    graph: MarketMeGraph
    timeline: list[MarketMeTimelineItem]
    enabled: bool


class MarketActivityItem(BaseModel):
    """One entry in the global market activity feed (all agents' collaboration).

    Unlike the personal timeline, this spans every participant so the demo shows
    a live "trading floor" of agents helping each other. ``text`` is the fully
    composed one-liner the frontend renders as-is.
    """

    id: str
    at: datetime
    kind: Literal["signal", "match"]
    status: Literal["answered", "awaiting_confirm", "denied", "open"] = "open"
    actor_name: str = ""
    counterpart_name: str = ""
    topic: str = ""
    text: str = ""
    involves_me: bool = False


class MarketActivityFeed(BaseModel):
    """Aggregated response for GET /api/market/activity."""

    items: list[MarketActivityItem]
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


class SkillIntentComplexity(StrEnum):
    DIRECT = "direct"
    ASSISTED = "assisted"
    WORKFLOW = "workflow"


class AgentPlanningMode(StrEnum):
    STANDARD = "standard"
    DEEPSEARCH = "deepsearch"


class AgentPlanningContractVersion(StrEnum):
    STANDARD_LEGACY_V1 = "standard_legacy_v1"
    STANDARD_UNIVERSAL_V1 = "standard_universal_v1"
    DEEPSEARCH_FROZEN_V1 = "deepsearch_frozen_v1"
    DEEPSEARCH_FROZEN_V2 = "deepsearch_frozen_v2"

    @property
    def planning_mode(self) -> AgentPlanningMode:
        if self in {
            AgentPlanningContractVersion.STANDARD_LEGACY_V1,
            AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        }:
            return AgentPlanningMode.STANDARD
        return AgentPlanningMode.DEEPSEARCH


class SkillIntentConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_write: bool = False
    project_scope: Literal["current"] = "current"
    time_budget_seconds: int | None = Field(default=None, ge=1, le=300)


class SkillIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=1000)
    primary_stage: SkillLifecycleStage = SkillLifecycleStage.PRE_DESIGN
    input_kinds: list[str] = Field(default_factory=list, max_length=20)
    deliverables: list[str] = Field(default_factory=list, max_length=20)
    analysis_requirements: list[str] = Field(default_factory=list, max_length=20)
    presentation_requirements: list[str] = Field(default_factory=list, max_length=20)
    external_evidence_required: bool = False
    constraints: SkillIntentConstraints = Field(default_factory=SkillIntentConstraints)
    explicit_skill_names: list[str] = Field(default_factory=list, max_length=10)
    complexity: SkillIntentComplexity = SkillIntentComplexity.DIRECT


class SkillCandidateScore(BaseModel):
    fts: float = Field(default=0, ge=0)
    embedding: float = Field(default=0, ge=0)
    stage: float = Field(default=0, ge=0)
    inputs: float = Field(default=0, ge=0)
    outputs: float = Field(default=0, ge=0)
    examples: float = Field(default=0, ge=0)
    recent_success: float = Field(default=0, ge=0)
    negative: float = Field(default=0, ge=0)
    total: float = 0


class DeliverableAtomV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["deliverable"] = "deliverable"
    id: str = Field(pattern=r"^deliverable:[a-z][a-z0-9_]*$", max_length=180)
    label: str = Field(min_length=1, max_length=200)
    output_kind: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=120)


class ScenarioOutputAtomV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["scenario_output"] = "scenario_output"
    id: str = Field(
        pattern=r"^scenario:[a-z0-9]+(?:-[a-z0-9]+)*:output:[a-z][a-z0-9_]*$",
        max_length=300,
    )
    label: str = Field(min_length=1, max_length=200)
    scenario_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    output_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=120)
    compatible_output_kinds: tuple[str, ...] = Field(min_length=1, max_length=20)


class EvidenceAtomV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["evidence"] = "evidence"
    id: Literal["evidence:trusted_external_path"] = "evidence:trusted_external_path"
    label: str = Field(default="Trusted external evidence", min_length=1, max_length=200)
    requirement_key: Literal["trusted_external_path"] = "trusted_external_path"
    evidence_policy_id: str = Field(default="deepsearch-evidence-v1", min_length=1, max_length=120)
    evidence_policy_version: str = Field(default="1", min_length=1, max_length=40)
    evidence_policy_hash: str = Field(default="phase1a-readiness-only", min_length=1, max_length=128)


CoverageAtomV1 = Annotated[
    DeliverableAtomV1 | ScenarioOutputAtomV1 | EvidenceAtomV1,
    Field(discriminator="kind"),
]


class CapabilityGapV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1, max_length=300)
    label: str = Field(min_length=1, max_length=200)
    diagnostics: tuple[str, ...] = Field(default_factory=tuple, max_length=20)


class SkillCandidate(BaseModel):
    skill_id: str
    skill_name: str
    title: str
    description: str
    profile: SkillCapabilityProfile
    score: SkillCandidateScore
    reason: str
    match_reason_codes: list[str] = Field(default_factory=list, max_length=20)
    coverage_witness_scenario_id: str | None = Field(default=None, max_length=120)
    covered_requirement_ids: list[str] = Field(default_factory=list, max_length=24)
    ready: bool = True
    diagnostics: list[str] = Field(default_factory=list)


class SkillRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(default=None, max_length=120)


class SkillRecommendationResponse(BaseModel):
    intent: SkillIntent
    candidates: list[SkillCandidate]
    diagnostics: list[str] = Field(default_factory=list)


class SkillPlanStatus(StrEnum):
    PLANNING = "planning"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SkillPlanNodeStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_TOOL_APPROVAL = "waiting_tool_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class DeepSearchFinalizationStage(StrEnum):
    NONE = "none"
    NODES_TERMINAL = "nodes_terminal"
    EVIDENCE_MANIFEST_SEALED = "evidence_manifest_sealed"
    SYNTHESIS_V0_SAVED = "synthesis_v0_saved"
    COVERAGE_V0_CHECKED = "coverage_v0_checked"
    REVIEW_V0_CHECKED = "review_v0_checked"
    SYNTHESIS_V1_SAVED = "synthesis_v1_saved"
    COVERAGE_V1_CHECKED = "coverage_v1_checked"
    REVIEW_V1_CHECKED = "review_v1_checked"
    TERMINAL_COMMITTED = "terminal_committed"


class DeepSearchEvidenceBindingDraft(BaseModel):
    """Model-produced evidence references without server-owned identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_ids: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        default_factory=list,
        max_length=100,
    )
    success_criterion_ids: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(default_factory=list, max_length=100)
    source_id: str | None = Field(default=None, min_length=1, max_length=160)
    evidence_artifact_id: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_references(self) -> DeepSearchEvidenceBindingDraft:
        if len(self.question_ids) != len(set(self.question_ids)) or len(
            self.success_criterion_ids
        ) != len(set(self.success_criterion_ids)):
            raise ValueError("evidence references must be unique")
        return self


class DeepSearchEvidenceItemV1(DeepSearchEvidenceBindingDraft):
    """Server-owned semantic binding to one sealed evidence artifact."""

    id: str = Field(min_length=1, max_length=160)
    node_result_id: str = Field(min_length=1, max_length=160)


class DeepSearchToolInvocationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=120)
    requirement_version_id: str = Field(min_length=1, max_length=120)
    plan_id: str = Field(min_length=1, max_length=120)
    plan_version: int = Field(ge=1)
    node_id: str = Field(min_length=1, max_length=120)
    node_attempt: int = Field(ge=1, le=2)
    tool_definition_id: str = Field(min_length=1, max_length=160)
    implementation_id: str = Field(min_length=1, max_length=160)
    implementation_version: str = Field(min_length=1, max_length=120)
    tool_call_id: str = Field(min_length=1, max_length=160)
    operation_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_arguments_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeepSearchSynthesisClaimDraft(BaseModel):
    """Model-produced claim fields; identity is always assigned by the server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=8192)
    question_ids: list[str] = Field(default_factory=list, max_length=100)
    success_criterion_ids: list[str] = Field(default_factory=list, max_length=100)
    node_result_ids: list[str] = Field(default_factory=list, max_length=20)
    evidence_item_ids: list[str] = Field(default_factory=list, max_length=60)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    recommendation: bool = False

    @model_validator(mode="after")
    def validate_references(self) -> DeepSearchSynthesisClaimDraft:
        references = (
            self.question_ids,
            self.success_criterion_ids,
            self.node_result_ids,
            self.evidence_item_ids,
            self.source_ids,
        )
        if any(len(values) != len(set(values)) for values in references):
            raise ValueError("synthesis claim references must be unique")
        return self


class DeepSearchSynthesisDraftV1(BaseModel):
    """Strict model response for one synthesis attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claims: list[DeepSearchSynthesisClaimDraft] = Field(min_length=1, max_length=100)


class DeepSearchSynthesisClaimV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=8192)
    question_ids: list[str] = Field(default_factory=list, max_length=100)
    success_criterion_ids: list[str] = Field(default_factory=list, max_length=100)
    node_result_ids: list[str] = Field(default_factory=list, max_length=20)
    evidence_item_ids: list[str] = Field(default_factory=list, max_length=60)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    recommendation: bool = False

    @model_validator(mode="after")
    def validate_references(self) -> DeepSearchSynthesisClaimV1:
        references = (
            self.question_ids,
            self.success_criterion_ids,
            self.node_result_ids,
            self.evidence_item_ids,
            self.source_ids,
        )
        if any(len(values) != len(set(values)) for values in references):
            raise ValueError("synthesis claim references must be unique")
        return self


class DeepSearchSynthesisV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepsearch-synthesis-v1"] = "deepsearch-synthesis-v1"
    revision_count: int = Field(ge=0, le=1)
    synthesis_mode: Literal["model", "deterministic_evidence_digest"]
    claims: list[DeepSearchSynthesisClaimV1] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_claims(self) -> DeepSearchSynthesisV1:
        claim_ids = [claim.id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("synthesis claim IDs must be unique")
        payload_hashes = [
            canonical_json_sha256(claim.model_dump(mode="python", exclude={"id"}))
            for claim in self.claims
        ]
        if len(payload_hashes) != len(set(payload_hashes)):
            raise ValueError("canonical claim payloads must be unique")
        return self


class DeepSearchEvidenceCoverageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepsearch-evidence-coverage-v1"] = "deepsearch-evidence-coverage-v1"
    revision_count: int = Field(ge=0, le=1)
    synthesis_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_question_ids: list[str] = Field(default_factory=list, max_length=100)
    covered_question_ids: list[str] = Field(default_factory=list, max_length=100)
    uncovered_question_ids: list[str] = Field(default_factory=list, max_length=100)
    required_success_criterion_ids: list[str] = Field(default_factory=list, max_length=100)
    covered_success_criterion_ids: list[str] = Field(default_factory=list, max_length=100)
    uncovered_success_criterion_ids: list[str] = Field(default_factory=list, max_length=100)
    validated_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    invalid_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    validated_source_ids: list[str] = Field(default_factory=list, max_length=100)
    invalid_source_ids: list[str] = Field(default_factory=list, max_length=100)
    validated_node_result_ids: list[str] = Field(default_factory=list, max_length=100)
    invalid_node_result_ids: list[str] = Field(default_factory=list, max_length=100)
    external_evidence_is_real: bool
    passed: bool
    gap_codes: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_coverage(self) -> DeepSearchEvidenceCoverageV1:
        collections = (
            self.required_question_ids,
            self.covered_question_ids,
            self.uncovered_question_ids,
            self.required_success_criterion_ids,
            self.covered_success_criterion_ids,
            self.uncovered_success_criterion_ids,
            self.validated_claim_ids,
            self.invalid_claim_ids,
            self.validated_source_ids,
            self.invalid_source_ids,
            self.validated_node_result_ids,
            self.invalid_node_result_ids,
            self.gap_codes,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("evidence coverage IDs and gap codes must be unique")
        if (
            set(self.covered_question_ids) | set(self.uncovered_question_ids)
            != set(self.required_question_ids)
            or set(self.covered_question_ids) & set(self.uncovered_question_ids)
        ):
            raise ValueError("question coverage must partition required IDs")
        if (
            set(self.covered_success_criterion_ids) | set(self.uncovered_success_criterion_ids)
            != set(self.required_success_criterion_ids)
            or set(self.covered_success_criterion_ids) & set(self.uncovered_success_criterion_ids)
        ):
            raise ValueError("success criterion coverage must partition required IDs")
        reference_partitions = (
            (self.validated_claim_ids, self.invalid_claim_ids),
            (self.validated_source_ids, self.invalid_source_ids),
            (self.validated_node_result_ids, self.invalid_node_result_ids),
        )
        if any(set(validated) & set(invalid) for validated, invalid in reference_partitions):
            raise ValueError("validated and invalid evidence references must be disjoint")
        return self


class DeepSearchReportReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepsearch-report-review-v1"] = "deepsearch-report-review-v1"
    requirement_version_id: str = Field(min_length=1, max_length=120)
    requirement_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    problem_graph_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_id: str = Field(min_length=1, max_length=120)
    plan_version: int = Field(ge=1)
    plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    synthesis_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["pass", "revise", "block"]
    unsupported_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    contradictory_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    missing_section_ids: list[str] = Field(default_factory=list, max_length=100)
    limitation_codes: list[str] = Field(default_factory=list, max_length=100)
    revision_count: int = Field(ge=0, le=1)
    reviewer_type: str = Field(min_length=1, max_length=80)
    reviewed_at: datetime

    @model_validator(mode="after")
    def validate_review_references(self) -> DeepSearchReportReviewV1:
        collections = (
            self.unsupported_claim_ids,
            self.contradictory_claim_ids,
            self.missing_section_ids,
            self.limitation_codes,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("review references and limitation codes must be unique")
        if set(self.unsupported_claim_ids).intersection(self.contradictory_claim_ids):
            raise ValueError("a claim cannot be both unsupported and contradictory")
        if self.verdict == "pass" and any(collections):
            raise ValueError("passing reviews cannot report blocking issues")
        if self.verdict != "pass" and not any(collections):
            raise ValueError("non-passing reviews require actionable IDs or codes")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return self


class DeepSearchReportReviewDraftV1(BaseModel):
    """Model-produced review fields; lineage and timestamps stay server-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Literal["pass", "revise", "block"]
    unsupported_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    contradictory_claim_ids: list[str] = Field(default_factory=list, max_length=100)
    missing_section_ids: list[str] = Field(default_factory=list, max_length=100)
    limitation_codes: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_references(self) -> DeepSearchReportReviewDraftV1:
        collections = (
            self.unsupported_claim_ids,
            self.contradictory_claim_ids,
            self.missing_section_ids,
            self.limitation_codes,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("review references and limitation codes must be unique")
        if self.verdict == "pass" and any(collections):
            raise ValueError("passing reviews cannot report blocking issues")
        if self.verdict != "pass" and not any(collections):
            raise ValueError("non-passing reviews require actionable IDs or codes")
        return self


class DeepSearchReviewOutcomeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepsearch-review-outcome-v1"] = "deepsearch-review-outcome-v1"
    revision_count: int = Field(ge=0, le=1)
    synthesis_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["not_run", "pass", "revise", "block", "error"]
    review: DeepSearchReportReviewV1 | None = None
    reason_code: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_outcome(self) -> DeepSearchReviewOutcomeV1:
        if self.outcome in {"pass", "revise", "block"}:
            if (
                self.review is None
                or self.review.verdict != self.outcome
                or self.review.revision_count != self.revision_count
                or self.review.synthesis_content_hash != self.synthesis_content_hash
                or self.reason_code is not None
            ):
                raise ValueError("review verdict outcome must match its review checkpoint")
            return self
        if self.outcome == "not_run":
            if (
                self.review is not None
                or self.reason_code
                not in {"coverage_failed", "budget_unavailable", "deterministic_digest"}
            ):
                raise ValueError("not_run review outcomes require a stable pre-review reason code")
            return self
        if self.review is not None or self.reason_code is None:
            raise ValueError("error review outcomes require a reason code and no review")
        return self


class SkillPlanKnowledgeBindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(default_factory=list, max_length=100)
    optional: list[str] = Field(default_factory=list, max_length=100)
    excluded: list[str] = Field(default_factory=list, max_length=100)


class SkillResourceManifestV1(BaseModel):
    """Immutable allowlist of Skill resources approved for one Plan node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["skill-resource-manifest-v1"] = "skill-resource-manifest-v1"
    required_resources: list[
        Annotated[str, Field(min_length=1, max_length=160)]
    ] = Field(default_factory=list, max_length=20)
    resource_hashes: dict[
        Annotated[str, Field(min_length=1, max_length=500)],
        Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
    ] = Field(default_factory=dict, max_length=256)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> SkillResourceManifestV1:
        if self.required_resources != sorted(set(self.required_resources)):
            raise ValueError("required_resources must be uniquely sorted")
        expected_hash = canonical_json_sha256(
            self.model_dump(mode="python", exclude={"content_hash"})
        )
        if self.content_hash != expected_hash:
            raise ValueError("resource manifest content_hash does not match its canonical content")
        return self


class SkillPlanNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("node"))
    skill_id: str
    skill_version: str
    skill_content_hash: str
    reason: str = Field(min_length=1, max_length=1000)
    task_id: str | None = Field(default=None, max_length=120)
    scenario_id: str | None = Field(default=None, max_length=120)
    skill_registry_id: str | None = Field(default=None, max_length=160)
    skill_status: Literal["draft", "reviewed", "validated"] | None = None
    required: bool = True
    depends_on: list[str] = Field(default_factory=list, max_length=6)
    parallel_group: str | None = Field(default=None, max_length=120)
    condition: str | None = Field(default=None, max_length=500)
    question_ids: list[
        Annotated[str, Field(pattern=r"^question_[0-9a-f]{16}$")]
    ] = Field(default_factory=list, max_length=20)
    input_bindings: list[str] = Field(default_factory=list, max_length=20)
    output_contract: list[str] = Field(default_factory=list, max_length=20)
    knowledge_bindings: SkillPlanKnowledgeBindings = Field(default_factory=SkillPlanKnowledgeBindings)
    required_tool_names: list[str] = Field(default_factory=list, max_length=20)
    resource_manifest: SkillResourceManifestV1 | None = None
    completion_criteria: list[str] = Field(default_factory=list, max_length=20)
    side_effect: SkillSideEffect = SkillSideEffect.READ
    status: SkillPlanNodeStatus = SkillPlanNodeStatus.PENDING
    attempt: int = Field(default=0, ge=0, le=2)
    error_code: str | None = Field(default=None, max_length=120)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_question_ids(self) -> SkillPlanNode:
        if len(self.question_ids) != len(set(self.question_ids)):
            raise ValueError("question_ids must be unique")
        return self


class SkillPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_contract: list[str] = Field(default_factory=list, max_length=20)
    synthesis_output_contract: list[str] = Field(default_factory=list, max_length=20)
    capability_gaps: list[str] = Field(default_factory=list, max_length=100)
    nodes: list[SkillPlanNode] = Field(default_factory=list, max_length=6)


class SkillPlan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("plan"))
    run_id: str
    version: int = Field(default=1, ge=1)
    status: SkillPlanStatus = SkillPlanStatus.PLANNING
    intent: SkillIntent
    routing_result: TaskRoutingResult | None = None
    candidate_skill_ids: list[str] = Field(default_factory=list, max_length=12)
    output_contract: list[str] = Field(default_factory=list, max_length=20)
    synthesis_output_contract: list[str] = Field(default_factory=list, max_length=20)
    capability_gaps: list[str] = Field(default_factory=list, max_length=100)
    preferred_order: list[str] = Field(default_factory=list, max_length=6)
    nodes: list[SkillPlanNode] = Field(default_factory=list, max_length=6)
    planning_mode: AgentPlanningMode = AgentPlanningMode.STANDARD
    requirement_version_id: str | None = Field(default=None, max_length=120)
    requirement_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    problem_graph: dict[str, Any] | None = None
    problem_graph_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    plan_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    approved_plan_artifact_id: str | None = Field(default=None, max_length=120)
    capability_check: dict[str, Any] | None = None
    evidence_manifest_artifact_id: str | None = Field(default=None, max_length=120)
    evidence_manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_coverage: DeepSearchEvidenceCoverageV1 | None = None
    deepsearch_syntheses: list[DeepSearchSynthesisV1] = Field(default_factory=list, max_length=2)
    synthesis_content_hashes: list[
        Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    ] = Field(default_factory=list, max_length=2)
    review_outcomes: list[DeepSearchReviewOutcomeV1] = Field(default_factory=list, max_length=2)
    report_revision_count: int = Field(default=0, ge=0, le=1)
    report_artifact_id: str | None = Field(default=None, max_length=120)
    report_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    finalization_stage: DeepSearchFinalizationStage = DeepSearchFinalizationStage.NONE
    finalization_version: int = Field(default=0, ge=0)
    finalization_input_hashes: dict[
        DeepSearchFinalizationStage,
        Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
    ] = Field(default_factory=dict, max_length=10)
    degradation: str | None = Field(default=None, max_length=1000)
    completion_check: CompletionCheckResult | None = None
    synthesis: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def validate_finalization_state(self) -> SkillPlan:
        expected_revisions = list(range(len(self.deepsearch_syntheses)))
        if [item.revision_count for item in self.deepsearch_syntheses] != expected_revisions:
            raise ValueError("DeepSearch syntheses must contain contiguous append-only revisions")
        expected_hashes = [
            canonical_json_sha256(item.model_dump(mode="python"))
            for item in self.deepsearch_syntheses
        ]
        if self.synthesis_content_hashes != expected_hashes:
            raise ValueError("synthesis content hashes must match their canonical revisions")
        if self.evidence_coverage is not None:
            coverage_revision = self.evidence_coverage.revision_count
            if (
                coverage_revision >= len(self.synthesis_content_hashes)
                or self.evidence_coverage.synthesis_content_hash
                != self.synthesis_content_hashes[coverage_revision]
            ):
                raise ValueError("evidence coverage must match a synthesis revision")
        expected_review_revisions = list(range(len(self.review_outcomes)))
        if [item.revision_count for item in self.review_outcomes] != expected_review_revisions or any(
            outcome.revision_count >= len(self.synthesis_content_hashes)
            or outcome.synthesis_content_hash
            != self.synthesis_content_hashes[outcome.revision_count]
            for outcome in self.review_outcomes
        ):
            raise ValueError("review outcomes must match synthesis revisions in append-only order")
        if (self.evidence_manifest_artifact_id is None) != (self.evidence_manifest_hash is None):
            raise ValueError("evidence manifest artifact and hash must be set together")
        if (self.report_artifact_id is None) != (self.report_content_hash is None):
            raise ValueError("report artifact and hash must be set together")
        expected_report_revision = (
            self.deepsearch_syntheses[-1].revision_count if self.deepsearch_syntheses else 0
        )
        if self.report_revision_count != expected_report_revision:
            raise ValueError("report revision must match the latest synthesis")
        if self.finalization_stage is DeepSearchFinalizationStage.NONE:
            if self.finalization_version != 0:
                raise ValueError("none finalization stage requires version zero")
            if self.finalization_input_hashes:
                raise ValueError("none finalization stage cannot carry input hashes")
        elif self.finalization_version == 0:
            raise ValueError("started finalization requires a positive version")
        return self


class SkillPlanUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    selected_skill_ids: list[str] = Field(min_length=1, max_length=6)
    preferred_order: list[str] = Field(default_factory=list, max_length=6)


class SkillPlanVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class SkillNodeUsage(BaseModel):
    total_tokens: int = Field(default=0, ge=0)


class SkillResultSource(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=300)
    source_type: str = Field(min_length=1, max_length=80)
    reference: str = Field(default="", max_length=2000)


class SkillNodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("node_result"))
    node_id: str
    skill_id: str
    summary: str = Field(min_length=1, max_length=8000)
    deliverable_markdown: str = Field(default="", max_length=60_000)
    findings: list[str] = Field(default_factory=list, max_length=100)
    recommendations: list[str] = Field(default_factory=list, max_length=100)
    scenario_outputs: list[str] = Field(default_factory=list, max_length=100)
    completion_criteria_met: list[str] = Field(default_factory=list, max_length=100)
    sources: list[SkillResultSource] = Field(default_factory=list, max_length=100)
    evidence_items: list[DeepSearchEvidenceItemV1] = Field(default_factory=list, max_length=60)
    confidence: float = Field(default=0.5, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)
    usage: SkillNodeUsage = Field(default_factory=SkillNodeUsage)
    degradation: str | None = Field(default=None, max_length=1000)
    reused_from_run_id: str | None = Field(default=None, max_length=120)
    reused_from_result_id: str | None = Field(default=None, max_length=120)
    attempt: int = Field(default=1, ge=1, le=2)
    created_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def validate_evidence_items(self) -> SkillNodeResult:
        evidence_item_ids = [item.id for item in self.evidence_items]
        if len(evidence_item_ids) != len(set(evidence_item_ids)):
            raise ValueError("evidence item IDs must be unique")
        if any(item.node_result_id != self.id for item in self.evidence_items):
            raise ValueError("evidence item lineage must match its node result")
        return self


class SkillSynthesisClaim(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    node_result_ids: list[str] = Field(min_length=1, max_length=20)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    recommendation: bool = False


class SkillSynthesisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=8000)
    sections: list[str] = Field(default_factory=list, max_length=100)
    presentation_outputs: list[str] = Field(default_factory=list, max_length=20)
    claims: list[SkillSynthesisClaim] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    next_actions: list[str] = Field(default_factory=list, max_length=100)
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)


class SkillPlanDetailResponse(BaseModel):
    plan: SkillPlan
    results: list[SkillNodeResult] = Field(default_factory=list)
    synthesis: SkillSynthesisResult | None = None


class SkillOrchestrationRequestMode(StrEnum):
    AUTO = "auto"
    SINGLE = "single"


class DeepSearchBudgetUsageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active_seconds: float = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    evidence_items: int = Field(default=0, ge=0)
    evidence_bytes: int = Field(default=0, ge=0)
    artifact_bytes: int = Field(default=0, ge=0)


class DeepSearchBudgetLimitsV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active_seconds: Literal[1800] = 1800
    llm_calls: Literal[64] = 64
    tokens: Literal[250000] = 250000
    tool_calls: Literal[24] = 24
    evidence_items: Literal[60] = 60
    evidence_bytes: Literal[524288] = 524288
    artifact_bytes: Literal[10485760] = 10485760


class DeepSearchFinalizationReserveV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    active_seconds: Literal[300] = 300
    artifact_bytes: Literal[1179648] = 1179648


class DeepSearchBudgetReservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_operation_key: str = Field(min_length=1, max_length=160)
    invocation_key: str = Field(min_length=1, max_length=160)
    physical_attempt: int = Field(ge=1, le=3)
    scope: Literal["standard", "finalization"] = "standard"
    resource_maxima: DeepSearchBudgetUsageV1
    status: Literal["reserved", "settled"]
    actual_usage: DeepSearchBudgetUsageV1 | None = None
    tool_invocation: DeepSearchToolInvocationV1 | None = None

    @model_validator(mode="after")
    def validate_settlement(self) -> DeepSearchBudgetReservationV1:
        if (self.status == "settled") != (self.actual_usage is not None):
            raise ValueError("settled reservations require actual_usage")
        if self.actual_usage is not None:
            for field in DeepSearchBudgetUsageV1.model_fields:
                if getattr(self.actual_usage, field) > getattr(self.resource_maxima, field):
                    raise ValueError("actual usage cannot exceed its reservation")
        if self.tool_invocation is not None:
            non_tool_usage = self.resource_maxima.model_dump(
                mode="python",
                exclude={"active_seconds", "tool_calls"},
            )
            if (
                self.scope != "standard"
                or self.logical_operation_key != self.tool_invocation.operation_key
                or self.invocation_key != self.tool_invocation.operation_key
                or self.physical_attempt != 1
                or self.resource_maxima.tool_calls != 1
                or any(non_tool_usage.values())
            ):
                raise ValueError("tool invocation reservation identity is invalid")
        return self


class DeepSearchBudgetV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepsearch-budget-v1"] = "deepsearch-budget-v1"
    version: int = Field(default=1, ge=1)
    limits: DeepSearchBudgetLimitsV1 = Field(default_factory=DeepSearchBudgetLimitsV1)
    consumed: DeepSearchBudgetUsageV1 = Field(default_factory=DeepSearchBudgetUsageV1)
    reservations: list[DeepSearchBudgetReservationV1] = Field(default_factory=list, max_length=256)
    finalization_reserve: DeepSearchFinalizationReserveV1 = Field(default_factory=DeepSearchFinalizationReserveV1)
    stage_recovery_attempts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_budget(self) -> DeepSearchBudgetV1:
        for field in DeepSearchBudgetUsageV1.model_fields:
            if getattr(self.consumed, field) > getattr(self.limits, field):
                raise ValueError("consumed DeepSearch budget exceeds its limit")
        if len({item.invocation_key for item in self.reservations}) != len(self.reservations):
            raise ValueError("DeepSearch reservation invocation keys must be unique")
        if any(attempt < 0 or attempt > 3 for attempt in self.stage_recovery_attempts.values()):
            raise ValueError("DeepSearch stage recovery attempts must be between zero and three")
        return self


class AgentRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)
    client_turn_id: str = Field(min_length=1, max_length=120)
    thread_id: str | None = None
    skill_name: str | None = Field(default=None, max_length=64)
    explicit_skill_name: str | None = Field(default=None, max_length=64)
    orchestration_mode: SkillOrchestrationRequestMode = SkillOrchestrationRequestMode.AUTO
    planning_mode: AgentPlanningMode = AgentPlanningMode.STANDARD


class AgentRunRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_turn_id: str = Field(min_length=1, max_length=120)


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None
    client_turn_id: str = Field(default_factory=lambda: new_id("turn"), min_length=1, max_length=120)


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


class ChatThreadUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> ChatThreadUpdateRequest:
        if self.title is None and self.pinned is None:
            raise ValueError("title or pinned is required")
        return self


class InboxUpdateRequest(BaseModel):
    status: str | None = Field(default=None, min_length=1, max_length=40)
    ttl_minutes: int | None = Field(default=None, ge=1, le=7 * 24 * 60)
    snooze_until: datetime | None = None

class BriefConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100_000)
    expected_document_version: int = Field(ge=1)


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
    model_config = ConfigDict(extra="forbid")

    post_type: BlackboardPostType
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    scope: Scope = Scope.PROJECT
    permission: str = Field(default="project_visible", min_length=1, max_length=80)


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


class SkillBindingUpdateRequest(BaseModel):
    enabled: bool
    aliases: list[str] | None = None


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


class DeepSearchAvailabilityReason(StrEnum):
    DISABLED = "disabled"
    EXECUTION_UNAVAILABLE = "execution_unavailable"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    MODEL_UNAVAILABLE = "model_unavailable"
    PLANNER_UNAVAILABLE = "planner_unavailable"


class DeepSearchAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    enabled: bool
    runtime_mode: Literal["off", "preview", "execute"]
    core_ready: bool
    reason_code: DeepSearchAvailabilityReason | None = None


class BootstrapState(BaseModel):
    workspace: Workspace
    project: Project
    user: User
    users: list[User]
    teams: list[Team] = Field(default_factory=list)
    team_memberships: list[TeamMembership] = Field(default_factory=list)
    agents: list[Agent]
    metrics: BootstrapMetrics
    capabilities: list[str] = Field(default_factory=list)
    agent_runtime_enabled: bool = False
    skill_orchestration_mode: Literal["off", "preview", "execute"] = "off"
    deepsearch_availability: DeepSearchAvailability


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




class SDKSessionRecord(BaseModel):
    id: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    synced_chat_message_ids: list[str] = Field(default_factory=list)
    version: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class AgentRunStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    WAITING_CLARIFICATION = "waiting_clarification"
    RUNNING = "running"
    WAITING_PLAN_APPROVAL = "waiting_plan_approval"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class AgentRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    thread_id: str
    user_id: str
    workspace_id: str
    project_id: str
    input_text: str
    client_turn_id: str | None = Field(default=None, max_length=120)
    status: AgentRunStatus = AgentRunStatus.CREATED
    skill_id: str | None = None
    skill_name: str | None = None
    plan_id: str | None = None
    retry_of_run_id: str | None = Field(default=None, max_length=120)
    planning_mode: AgentPlanningMode = AgentPlanningMode.STANDARD
    planning_contract_version: AgentPlanningContractVersion | None = None
    create_request_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    orchestration_version: Literal["v1", "research-v2", "research-v3"] = "v1"
    orchestration_mode: Literal["off", "preview", "execute"] = "off"
    writer_generation_epoch: int | None = Field(default=None, ge=1)
    requested_orchestration_mode: SkillOrchestrationRequestMode | None = None
    agent_definition_version: str = "1"
    project_chat: bool = False
    tool_call_count: int = Field(default=0, ge=0, le=24)
    deadline_at: datetime | None = None
    interaction_expires_at: datetime | None = None
    absolute_expires_at: datetime | None = None
    deepsearch_budget: DeepSearchBudgetV1 | None = None
    paused_state: dict[str, Any] | None = None
    output_text: str | None = None
    error_code: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    @model_validator(mode="after")
    def validate_planning_contract(self) -> AgentRun:
        if (
            self.planning_contract_version is not None
            and self.planning_contract_version.planning_mode is not self.planning_mode
        ):
            raise ValueError("planning_contract_version is incompatible with planning_mode")
        return self


class SkillPlanTransitionResponse(BaseModel):
    plan: SkillPlan
    run: AgentRun


class AgentRunEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run_event"))
    run_id: str
    sequence: int = Field(ge=1)
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)


class AgentRunEventsResponse(BaseModel):
    items: list[AgentRunEvent]


class ArtifactVerificationState(StrEnum):
    STAGING = "staging"
    SEALED = "sealed"
    FAILED = "failed"
    LEGACY_UNVERIFIED = "legacy_unverified"
    PURGED = "purged"


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("artifact"))
    run_id: str
    workspace_id: str
    project_id: str
    user_id: str
    artifact_type: str
    content_type: str
    content: str
    truncated: bool = False
    verification_state: ArtifactVerificationState | None = None
    schema_version: str | None = Field(default=None, max_length=120)
    content_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)
    requirement_version_id: str | None = Field(default=None, max_length=120)
    plan_version_id: str | None = Field(default=None, max_length=120)
    attempt_id: str | None = Field(default=None, max_length=120)
    step_number: int | None = Field(default=None, ge=1)
    purged_at: datetime | None = None
    purged_by: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_verification_state(self) -> Artifact:
        if self.verification_state is None and any(
            value is not None
            for value in (
                self.schema_version,
                self.content_hash,
                self.size_bytes,
                self.requirement_version_id,
                self.plan_version_id,
                self.attempt_id,
                self.step_number,
                self.purged_at,
                self.purged_by,
            )
        ):
            raise ValueError("legacy artifacts cannot carry v2 verification metadata")
        if self.verification_state in {
            ArtifactVerificationState.STAGING,
            ArtifactVerificationState.SEALED,
            ArtifactVerificationState.FAILED,
        } and (self.schema_version is None or self.requirement_version_id is None):
            raise ValueError("v2 artifacts require schema and requirement lineage")
        if self.plan_version_id is None and (self.attempt_id is not None or self.step_number is not None):
            raise ValueError("attempt and step lineage require a plan")
        if (self.attempt_id is None) != (self.step_number is None):
            raise ValueError("attempt and step lineage must be set together")
        if self.verification_state == ArtifactVerificationState.STAGING and (
            self.content
            or self.content_hash is not None
            or self.size_bytes is not None
            or self.purged_at is not None
            or self.purged_by is not None
            or self.schema_version is None
        ):
            raise ValueError("staging artifacts require a schema and cannot contain sealed content")
        if self.verification_state == ArtifactVerificationState.SEALED:
            content_bytes = self.content.encode("utf-8")
            if self.schema_version is None or self.content_hash is None or self.size_bytes is None:
                raise ValueError("sealed artifacts require schema_version, content_hash, and size_bytes")
            if self.content_hash != hashlib.sha256(content_bytes).hexdigest() or self.size_bytes != len(content_bytes):
                raise ValueError("sealed artifact hash or size does not match content")
        if self.verification_state == ArtifactVerificationState.FAILED and (
            self.purged_at is not None or self.purged_by is not None
        ):
            raise ValueError("failed artifacts cannot be marked purged")
        if self.verification_state == ArtifactVerificationState.PURGED and (
            self.purged_at is None
            or self.purged_by is None
            or self.content
            or self.content_hash is None
            or self.size_bytes is None
        ):
            raise ValueError("purged artifacts keep a tombstone hash/size and empty content")
        return self


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
    confidence: float = 0.0
    requested_provider: str | None = None
    actual_provider: str | None = None
    requested_model: str | None = None
    actual_model: str | None = None
    provider_mode: str | None = Field(default=None, pattern="^(real|fallback)$")
    latency_ms: float | None = Field(default=None, ge=0)
    fallback_reason: str | None = None
    model_fallback_reason: str | None = None
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


class ChatTurnReceiptStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ChatTurnReceipt(BaseModel):
    id: str
    client_turn_id: str = Field(min_length=1, max_length=120)
    user_id: str
    workspace_id: str
    project_id: str
    requested_thread_id: str | None = None
    thread_id: str
    content: str = Field(min_length=1, max_length=4000)
    status: ChatTurnReceiptStatus = ChatTurnReceiptStatus.PROCESSING
    response: ChatResponse | None = None
    error_code: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ChatTurnReceiptView(BaseModel):
    client_turn_id: str
    status: ChatTurnReceiptStatus
    thread_id: str
    response: ChatResponse | None = None


class InboxItemView(InboxItem):
    """Visible Inbox item with server-derived commands."""

    allowed_actions: list[str] = Field(default_factory=list)


class MemoryItemView(MemoryItem):
    """Visible governed memory with server-derived commands."""

    allowed_actions: list[str] = Field(default_factory=list)


class BlackboardPostView(BlackboardPost):
    """Visible Blackboard post with server-derived commands."""

    allowed_actions: list[str] = Field(default_factory=list)


class InboxItemsResponse(BaseModel):
    items: list[InboxItemView]


class MemoryItemsResponse(BaseModel):
    items: list[MemoryItemView]


class BlackboardPostsResponse(BaseModel):
    items: list[BlackboardPostView]
    total: int
    page: int
    page_size: int
    has_next: bool


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
    latest_post: BlackboardPostView | None = None
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
    target_post_id: str | None = None
    allowed_actions: list[str] = Field(default_factory=list)


class BlackboardTaskCardsResponse(BaseModel):
    """黑板任务卡片列表响应。"""
    items: list[BlackboardTaskCard]


class BlackboardTaskDetail(BaseModel):
    """One visible task card and its filtered Blackboard timeline."""

    task_card: BlackboardTaskCard
    posts: list[BlackboardPostView]



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


class ProviderDiagnostic(ProviderStatus):
    """Canonical secret-safe provider status with optional non-sensitive diagnostics."""

    model_config = ConfigDict(extra="allow")


class ProviderHealthCheckResponse(BaseModel):
    """Provider 健康检查响应。"""

    overall: str
    providers: list[ProviderDiagnostic]


class MemoryOverviewSections(BaseModel):
    short: list[UserMemoryItem]
    project: list[UserMemoryItem]
    archive: list[UserMemoryItem]
    team: list[MemoryItemView]


class MemoryOverviewCounts(BaseModel):
    short: int
    project: int
    archive: int
    team: int


class MemoryOverviewResponse(BaseModel):
    project_id: str
    sections: MemoryOverviewSections
    counts: MemoryOverviewCounts
    daily_summary_worker: dict[str, Any] = Field(default_factory=dict)


class UsersResponse(BaseModel):
    items: list[User]


class UserItemResponse(BaseModel):
    item: User


class AgentsResponse(BaseModel):
    items: list[Agent]


class ModelsResponse(BaseModel):
    items: list[ModelDefinition]


class ToolsResponse(BaseModel):
    items: list[ToolDefinition]


class PermissionPoliciesResponse(BaseModel):
    items: list[PermissionPolicyRule]


class RiskPoliciesResponse(BaseModel):
    items: list[RiskPolicyRule]


class O2LoginStatus(BaseModel):
    available: bool
    logged_in: bool


class O2StatusResponse(BaseModel):
    installed: bool
    binary: str
    version: str | None = None
    login: O2LoginStatus
    setup_checks: list[dict[str, Any]] = Field(default_factory=list)
