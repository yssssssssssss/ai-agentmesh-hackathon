"""Project-scoped delegated queries, confirmation, restricted results and adoption.

No independent runtime: PersonalAgent performs the existing synchronous synthesis.
The query owns its insert-only Artifact; the legacy artifacts.run_id column stores
this query's execution identity, without creating or impersonating an SDK AgentRun.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.memory_context.origin import memory_origin_available
from agentmesh.memory_governance.lifecycle import memory_content_hash
from agentmesh.models import (
    Agent,
    AgentMemoryBinding,
    AnswerConfidence,
    Artifact,
    ArtifactVerificationState,
    AuditEvent,
    ConsentGrant,
    ContributionPoint,
    InboxItem,
    MemoryLayer,
    MemoryRelation,
    Project,
    Scope,
    Source,
    User,
    UserMemoryItem,
    new_id,
    now_utc,
)
from agentmesh.store import MemoryContextConflict, SQLiteStore
from agentmesh.tool_runtime.guardrails import unsafe_tool_output_reason

QueryStatus = Literal['pending', 'awaiting_confirm', 'answered', 'insufficient_evidence', 'blocked', 'denied', 'failed']
_QUERY_COLLECTION = 'delegated_queries'
_ARTIFACT_SCHEMA = 'delegated-answer-artifact-v1'
_HASH = r'^[0-9a-f]{64}$'


class DelegatedQueryError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        self.code, self.status_code = code, status_code
        super().__init__(code)


class DelegatedQueryCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: str = Field(min_length=1, max_length=120)
    target_id: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=2000)
    command_id: str = Field(min_length=1, max_length=120)

    @field_validator('question')
    @classmethod
    def valid_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('question_required')
        return value.strip()


class QueryResolveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['approve', 'deny']
    expected_version: int = Field(ge=1)


class QueryAdoptRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    command_id: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1)
    artifact_hash: str = Field(pattern=_HASH)


class QueryConsentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: str = Field(min_length=1, max_length=120)
    grantee_id: str = Field(min_length=1, max_length=120)
    enabled: bool
    expected_version: int = Field(ge=0)
    command_id: str = Field(min_length=1, max_length=120)


class QueryConsentView(BaseModel):
    grantee_id: str
    enabled: bool
    version: int


class QueryConsentList(BaseModel):
    items: list[QueryConsentView]


class QueryAdoptionV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    command_id: str
    memory_id: str
    point_id: str
    relation_id: str
    artifact_hash: str = Field(pattern=_HASH)


class QueryMemoryProofV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    memory_id: str
    version: int = Field(ge=1)
    content_hash: str = Field(pattern=_HASH)
    record_hash: str = Field(pattern=_HASH)


class DelegatedQueryV1(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['delegated-query-v1'] = 'delegated-query-v1'
    id: str
    workspace_id: str
    project_id: str
    requester_id: str
    target_id: str
    command_id: str
    request_hash: str = Field(pattern=_HASH)
    question: str = Field(min_length=1, max_length=2000)
    question_version: Literal[1] = 1
    question_hash: str = Field(pattern=_HASH)
    version: int = Field(default=1, ge=1)
    status: QueryStatus
    evidence: list[QueryMemoryProofV1] = Field(default_factory=list, max_length=8)
    consent_hash: str | None = None
    participation_hash: str | None = None
    approval_mode: Literal['standing', 'once'] | None = None
    approved_by: str | None = None
    inbox_item_id: str | None = None
    claim_id: str | None = None
    claim_deadline: AwareDatetime | None = None
    artifact_id: str | None = None
    artifact_hash: str | None = None
    last_error_code: str | None = None
    adoption: QueryAdoptionV1 | None = None
    created_at: AwareDatetime = Field(default_factory=now_utc)
    updated_at: AwareDatetime = Field(default_factory=now_utc)

    @model_validator(mode='after')
    def validate_question_identity(self) -> DelegatedQueryV1:
        request = DelegatedQueryCreate(project_id=self.project_id, target_id=self.target_id,
                                       question=self.question, command_id=self.command_id)
        if self.request_hash != _hash(request) or self.question_hash != canonical_json_sha256({
            'version': self.question_version, 'question': self.question,
        }):
            raise ValueError('query_question_identity_invalid')
        return self


class DelegatedAnswerArtifactV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal['delegated-answer-artifact-v1'] = _ARTIFACT_SCHEMA
    query_id: str
    question_hash: str = Field(pattern=_HASH)
    answer: str = Field(min_length=1, max_length=8192)
    confidence: AnswerConfidence
    evidence_hash: str = Field(pattern=_HASH)
    # References to private source titles/URLs are deliberately not copied.
    citation: Source


class DelegatedQueryView(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    project_id: str
    requester_id: str
    target_id: str
    question: str
    version: int
    status: QueryStatus
    inbox_item_id: str | None = None
    answer: str | None = None
    confidence: AnswerConfidence = AnswerConfidence.NONE
    citations: list[Source] = Field(default_factory=list)
    artifact_hash: str | None = None
    current_available: bool = False
    unavailable_reason: str | None = None
    adoption: QueryAdoptionV1 | None = None
    created_at: AwareDatetime


class DelegatedQueryList(BaseModel):
    items: list[DelegatedQueryView]


def _record[RecordT: BaseModel](
    connection: sqlite3.Connection, collection: str, record_id: str | None, model: type[RecordT],
) -> RecordT | None:
    try:
        value = SQLiteStore._get_in_transaction(connection, collection, record_id, model)
    except ValueError:
        raise DelegatedQueryError('query_record_invalid') from None
    if value is not None and value.id != record_id:
        raise DelegatedQueryError('query_record_invalid')
    return value


def _hash(value: BaseModel) -> str:
    return canonical_json_sha256(value.model_dump(mode='json'))


def _authority(connection: sqlite3.Connection, query: DelegatedQueryV1, actor: User) -> tuple[User, User]:
    requester = _record(connection, 'users', query.requester_id, User)
    target = _record(connection, 'users', query.target_id, User)
    project = _record(connection, 'projects', query.project_id, Project)
    if (actor.id not in {query.requester_id, query.target_id} or actor.workspace_id != query.workspace_id
        or requester is None or target is None or project is None
        or requester.status != 'active' or target.status != 'active' or project.status != 'active'
        or requester.workspace_id != query.workspace_id or target.workspace_id != query.workspace_id
        or project.workspace_id != query.workspace_id
        or (project.member_ids and (requester.id not in project.member_ids or target.id not in project.member_ids))):
        raise DelegatedQueryError('delegated_query_not_found', 404)
    for user in (requester, target):
        agent = _record(connection, 'agents', user.personal_agent_id, Agent)
        if (agent is None or agent.owner_user_id != user.id or agent.workspace_id != query.workspace_id
            or agent.agent_type != 'personal' or agent.status != 'online'):
            raise DelegatedQueryError('query_agent_unavailable', 404)
    return requester, target


def _memory_binding(connection: sqlite3.Connection, query: DelegatedQueryV1) -> AgentMemoryBinding | None:
    target = _record(connection, 'users', query.target_id, User)
    if target is None:
        raise DelegatedQueryError('query_agent_unavailable', 404)
    try:
        return SQLiteStore._memory_binding_in_transaction(connection, target.personal_agent_id)
    except MemoryContextConflict:
        raise DelegatedQueryError('query_memory_binding_unavailable') from None


def _binding_allows(binding: AgentMemoryBinding | None, query: DelegatedQueryV1, item: UserMemoryItem) -> bool:
    return binding is None or (
        Scope.PRIVATE in (binding.allowed_scopes or [Scope.PRIVATE])
        and (not binding.allowed_project_ids or query.project_id in binding.allowed_project_ids)
        and binding.allows_memory_type(item.memory_type)
    )


def _consent(connection: sqlite3.Connection, query: DelegatedQueryV1) -> ConsentGrant | None:
    row = connection.execute(
        """SELECT payload FROM records WHERE collection = 'consent_grants'
            AND json_extract(payload, '$.grantor_id') = ? AND json_extract(payload, '$.grantee_id') = ?
            AND json_extract(payload, '$.workspace_id') = ? AND json_extract(payload, '$.project_id') = ?
            ORDER BY created_order DESC LIMIT 1""",
        (query.target_id, query.requester_id, query.workspace_id, query.project_id),
    ).fetchone()
    return ConsentGrant.model_validate_json(row['payload']) if row else None


def _participation(connection: sqlite3.Connection, query: DelegatedQueryV1) -> tuple[bool, str]:
    rows = connection.execute(
        "SELECT payload FROM records WHERE collection = 'market_participation' AND id IN (?, ?) ORDER BY id",
        (query.requester_id, query.target_id),
    ).fetchall()
    values = [json.loads(row['payload']) for row in rows]
    return len(values) == 2 and all(item.get('enabled') for item in values), canonical_json_sha256(values)


def _proof(item: UserMemoryItem) -> QueryMemoryProofV1:
    return QueryMemoryProofV1(memory_id=item.id, version=item.version,
                              content_hash=memory_content_hash(item), record_hash=_hash(item))


def _current_evidence(connection: sqlite3.Connection, query: DelegatedQueryV1,
                      *, ancestors: frozenset[str] = frozenset()) -> list[UserMemoryItem]:
    evidence = []
    binding = _memory_binding(connection, query)
    if binding is not None and len(query.evidence) > binding.max_results_per_query:
        raise DelegatedQueryError('query_memory_binding_unavailable')
    for proof in query.evidence:
        memory = _record(connection, 'user_memory_items', proof.memory_id, UserMemoryItem)
        if (memory is None or memory.user_id != query.target_id or memory.workspace_id != query.workspace_id
            or memory.project_id != query.project_id or memory.scope is not Scope.PRIVATE
            or memory.status != 'active' or memory.archived_at is not None or memory.facts or memory.procedure
            or _proof(memory) != proof or not _binding_allows(binding, query, memory)
            or not memory_origin_available(connection, memory, ancestors=ancestors)
            or unsafe_tool_output_reason(memory.model_dump_json()) is not None):
            raise DelegatedQueryError('query_evidence_changed')
        evidence.append(memory)
    return evidence


def _current_approval(connection: sqlite3.Connection, query: DelegatedQueryV1) -> None:
    consent = _consent(connection, query)
    if (_hash(consent) if consent else None) != query.consent_hash:
        raise DelegatedQueryError('query_consent_changed')
    if query.approval_mode == 'standing':
        enabled, digest = _participation(connection, query)
        if not consent or not consent.active or not enabled or digest != query.participation_hash:
            raise DelegatedQueryError('query_consent_changed')
    elif query.approval_mode != 'once' or query.approved_by != query.target_id:
        raise DelegatedQueryError('query_confirmation_required')


def _answer_artifact(connection: sqlite3.Connection, query: DelegatedQueryV1) -> DelegatedAnswerArtifactV1:
    row = connection.execute('SELECT * FROM artifacts WHERE id = ?', (query.artifact_id,)).fetchone()
    if row is None:
        raise DelegatedQueryError('query_artifact_unavailable')
    try:
        artifact = Artifact.model_validate_json(row['payload'])
        envelope = DelegatedAnswerArtifactV1.model_validate_json(artifact.content)
    except ValueError:
        raise DelegatedQueryError('query_artifact_unavailable') from None
    expected_indexes = {'id': query.artifact_id, 'run_id': query.id, 'workspace_id': query.workspace_id, 'project_id': query.project_id,
                        'user_id': query.requester_id, 'artifact_type': 'delegated_answer',
                        'content_type': 'application/json',
                        'schema_version': _ARTIFACT_SCHEMA, 'content_hash': query.artifact_hash,
                        'verification_state': 'sealed', 'requirement_version_id': query.question_hash}
    if (any(row[key] != value or getattr(artifact, key) != value for key, value in expected_indexes.items())
        or row['size_bytes'] != artifact.size_bytes or artifact.truncated or artifact.purged_at is not None
        or envelope.query_id != query.id or envelope.question_hash != query.question_hash
        or envelope.evidence_hash != canonical_json_sha256([proof.model_dump(mode='json') for proof in query.evidence])
        or envelope.citation.user_id != query.requester_id or envelope.citation.workspace_id != query.workspace_id
        or envelope.citation.project_id != query.project_id
        or envelope.citation.source_type != 'delegated_answer'
        or envelope.citation.reference != f'delegated-query://{query.id}'):
        raise DelegatedQueryError('query_artifact_unavailable')
    return envelope


def delegated_source_available(connection: sqlite3.Connection, source: Source,
                               *, ancestors: frozenset[str] = frozenset()) -> bool:
    """Adoption grants the delivered answer, never access to the helper's memory."""
    if not source.reference.startswith('delegated-query://') or len(ancestors) >= 4:
        return False
    query = _record(connection, _QUERY_COLLECTION, source.reference.removeprefix('delegated-query://'), DelegatedQueryV1)
    if query is None or query.id in ancestors or query.status != 'answered' or source.user_id != query.requester_id:
        return False
    requester = _record(connection, 'users', query.requester_id, User)
    try:
        if requester is None:
            return False
        _authority(connection, query, requester)
        _current_approval(connection, query)
        _current_evidence(connection, query, ancestors=ancestors | {query.id})
        return _answer_artifact(connection, query).citation == source
    except DelegatedQueryError:
        return False


class DelegatedQueryService:
    def __init__(self, repository: SQLiteStore, *, llm_client=None):
        self.store, self.llm_client = repository, llm_client

    def _save(self, connection: sqlite3.Connection, query: DelegatedQueryV1) -> None:
        query.updated_at = now_utc()
        self.store._upsert_plain_record(connection, _QUERY_COLLECTION, query)

    def _load(self, connection: sqlite3.Connection, query_id: str) -> DelegatedQueryV1:
        query = _record(connection, _QUERY_COLLECTION, query_id, DelegatedQueryV1)
        if query is None:
            raise DelegatedQueryError('delegated_query_not_found', 404)
        return query

    @staticmethod
    def _authorize_project(connection: sqlite3.Connection, actor: User, project_id: str) -> tuple[User, Project]:
        current = _record(connection, 'users', actor.id, User)
        project = _record(connection, 'projects', project_id, Project)
        if (current is None or current.status != 'active' or current.workspace_id != actor.workspace_id
            or project is None or project.status != 'active' or project.workspace_id != actor.workspace_id
            or (project.member_ids and actor.id not in project.member_ids)):
            raise DelegatedQueryError('delegated_query_not_found', 404)
        return current, project

    def consents(self, actor: User, project_id: str) -> QueryConsentList:
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            _, project = self._authorize_project(connection, actor, project_id)
            rows = connection.execute(
                """SELECT payload FROM records WHERE collection = 'consent_grants'
                    AND json_extract(payload, '$.grantor_id') = ? AND json_extract(payload, '$.workspace_id') = ?
                    AND json_extract(payload, '$.project_id') = ? ORDER BY created_order DESC LIMIT 200""",
                (actor.id, actor.workspace_id, project.id),
            ).fetchall()
            grants = [ConsentGrant.model_validate_json(row['payload']) for row in rows]
            return QueryConsentList(items=[QueryConsentView(grantee_id=grant.grantee_id, enabled=grant.active,
                                                            version=grant.version) for grant in grants])

    def set_consent(self, actor: User, request: QueryConsentRequest) -> QueryConsentView:
        if actor.id == request.grantee_id:
            raise DelegatedQueryError('cannot_consent_to_self', 400)
        grant_id = 'consent_query_' + hashlib.sha256(
            f'{actor.workspace_id}\0{request.project_id}\0{actor.id}\0{request.grantee_id}'.encode(),
        ).hexdigest()[:40]
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            _, project = self._authorize_project(connection, actor, request.project_id)
            peer = _record(connection, 'users', request.grantee_id, User)
            if (peer is None or peer.status != 'active' or peer.workspace_id != actor.workspace_id
                or (project.member_ids and peer.id not in project.member_ids)):
                raise DelegatedQueryError('query_peer_not_found', 404)
            grant = _record(connection, 'consent_grants', grant_id, ConsentGrant)
            if grant and grant.command_id == request.command_id:
                if grant.command_hash != _hash(request):
                    raise DelegatedQueryError('query_command_conflict')
            else:
                if (grant.version if grant else 0) != request.expected_version:
                    raise DelegatedQueryError('query_version_conflict')
                grant = ConsentGrant(id=grant_id, grantor_id=actor.id, grantee_id=peer.id,
                                     workspace_id=actor.workspace_id, project_id=project.id,
                                     version=(grant.version if grant else 0) + 1,
                                     created_at=grant.created_at if grant else now_utc(),
                                     revoked_at=None if request.enabled else now_utc(),
                                     command_id=request.command_id, command_hash=_hash(request))
                self.store._upsert_plain_record(connection, 'consent_grants', grant)
            return QueryConsentView(grantee_id=peer.id, enabled=grant.active, version=grant.version)

    def _view(self, connection: sqlite3.Connection, query: DelegatedQueryV1, actor: User) -> DelegatedQueryView:
        _authority(connection, query, actor)
        view = DelegatedQueryView(**query.model_dump(include={
            'id', 'project_id', 'requester_id', 'target_id', 'question', 'version', 'status',
            'inbox_item_id', 'adoption', 'created_at',
        }))
        if query.status == 'answered':
            try:
                _current_approval(connection, query)
                _current_evidence(connection, query, ancestors=frozenset({query.id}))
                answer = _answer_artifact(connection, query)
                view.answer, view.citations = answer.answer, [answer.citation]
                view.confidence = answer.confidence
                view.artifact_hash, view.current_available = query.artifact_hash, True
            except DelegatedQueryError as error:
                view.unavailable_reason = error.code
        else:
            view.unavailable_reason = query.last_error_code
        return view

    def _match(self, connection: sqlite3.Connection, query: DelegatedQueryV1) -> list[UserMemoryItem]:
        from agentmesh.agents import PersonalAgent

        terms = sorted(PersonalAgent._search_terms(query.question),
                       key=lambda term: (len(term) != 2, query.question.lower().find(term), len(term)))[:8]
        if not terms:
            return []
        binding = _memory_binding(connection, query)
        maximum = min(8, binding.max_results_per_query) if binding else 8
        types = binding.effective_memory_types if binding else None
        type_filter = json.dumps(sorted(types)) if types is not None else None
        if maximum < 1:
            return []
        like = " OR ".join("(lower(json_extract(payload, '$.title') || ' ' || json_extract(payload, '$.summary')) "
                           "LIKE ? ESCAPE '\\')" for _ in terms)
        parameters = [f"%{term.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%" for term in terms]
        rows = connection.execute(
            """SELECT payload FROM records WHERE collection = 'user_memory_items'
                AND json_extract(payload, '$.user_id') = ? AND json_extract(payload, '$.workspace_id') = ?
                AND json_extract(payload, '$.project_id') = ? AND json_extract(payload, '$.scope') = 'private'
                AND json_extract(payload, '$.status') = 'active' AND json_extract(payload, '$.archived_at') IS NULL
                AND json_extract(payload, '$.facts') IS NULL AND json_extract(payload, '$.procedure') IS NULL
                AND (? IS NULL OR COALESCE(json_extract(payload, '$.memory_type'), 'note')
                     IN (SELECT value FROM json_each(?)))
                AND (""" + like + ") ORDER BY created_order DESC LIMIT 200",
            (query.target_id, query.workspace_id, query.project_id, type_filter, type_filter, *parameters),
        ).fetchall()
        matched, size = [], 0
        for row in rows:
            memory = UserMemoryItem.model_validate_json(row['payload'])
            cost = len(memory.title) + len(memory.summary)
            if (cost > 6000 or size + cost > 16000 or not _binding_allows(binding, query, memory)
                or not memory_origin_available(connection, memory)
                or unsafe_tool_output_reason(memory.model_dump_json()) is not None):
                continue
            matched.append(memory)
            size += cost
            if len(matched) == maximum:
                break
        return matched

    def create(self, actor: User, request: DelegatedQueryCreate) -> DelegatedQueryView:
        query_id = 'dq_' + hashlib.sha256(f'{actor.id}\0{request.command_id}'.encode()).hexdigest()[:40]
        query = DelegatedQueryV1(id=query_id, workspace_id=actor.workspace_id, project_id=request.project_id,
                                 requester_id=actor.id, target_id=request.target_id, command_id=request.command_id,
                                 request_hash=_hash(request), question=request.question,
                                 question_hash=canonical_json_sha256({'version': 1, 'question': request.question}),
                                 status='pending')
        if actor.id == request.target_id:
            raise DelegatedQueryError('cannot_query_self', 400)
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            requester, target = _authority(connection, query, actor)
            old = _record(connection, _QUERY_COLLECTION, query_id, DelegatedQueryV1)
            if old:
                if old.request_hash != query.request_hash:
                    raise DelegatedQueryError('query_command_conflict')
                return self._view(connection, old, actor)
            matched = self._match(connection, query)
            query.evidence = [_proof(item) for item in matched]
            consent = _consent(connection, query)
            query.consent_hash = _hash(consent) if consent else None
            enabled, participation_hash = _participation(connection, query)
            automatic = bool(consent and consent.active and enabled and not any(item.sensitivity == 'high' for item in matched))
            if automatic:
                query.approval_mode, query.participation_hash = 'standing', participation_hash
            else:
                query.status = 'awaiting_confirm'
                inbox = InboxItem(title='确认项目代答请求', summary=f'{requester.name} 请求由你的分身回答：{query.question[:120]}',
                                  item_type='delegated_answer_confirmation', scope=Scope.PRIVATE,
                                  user_id=target.id, workspace_id=query.workspace_id, project_id=query.project_id,
                                  metadata={'query_id': query.id, 'target_id': target.id, 'asker_id': requester.id,
                                            'reason': 'high_sensitivity' if any(item.sensitivity == 'high' for item in matched)
                                            else 'explicit_confirmation_required'})
                query.inbox_item_id = inbox.id
                self.store._upsert_plain_record(connection, 'inbox_items', inbox)
            self._save(connection, query)
        if automatic:
            return self._execute(actor, query.id)
        return self.get(actor, query.id)

    def resolve(self, actor: User, query_id: str, *, action: Literal['approve', 'deny'],
                expected_version: int) -> DelegatedQueryView:
        if action not in {'approve', 'deny'}:
            raise DelegatedQueryError('invalid_query_action', 400)
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            query = self._load(connection, query_id)
            _authority(connection, query, actor)
            if actor.id != query.target_id:
                raise DelegatedQueryError('query_confirmation_owner_required', 403)
            if query.status != 'awaiting_confirm' or query.version != expected_version:
                raise DelegatedQueryError('query_version_conflict')
            inbox = _record(connection, 'inbox_items', query.inbox_item_id, InboxItem)
            if (inbox is None or inbox.status not in {'open', 'snoozed'} or inbox.user_id != actor.id
                or inbox.metadata.get('query_id') != query.id or inbox.workspace_id != query.workspace_id
                or inbox.project_id != query.project_id):
                raise DelegatedQueryError('query_confirmation_unavailable')
            if action == 'approve':
                _current_evidence(connection, query)
                if [_proof(item) for item in self._match(connection, query)] != query.evidence:
                    raise DelegatedQueryError('query_evidence_changed')
                consent = _consent(connection, query)
                query.consent_hash = _hash(consent) if consent else None
                query.approval_mode, query.approved_by, query.status = 'once', actor.id, 'pending'
            else:
                query.status = 'denied'
            query.version += 1
            inbox.status, inbox.resolved_at, inbox.updated_at = 'resolved', now_utc(), now_utc()
            self.store._upsert_plain_record(connection, 'inbox_items', inbox)
            self._save(connection, query)
        return self._execute(actor, query.id) if action == 'approve' else self.get(actor, query.id)

    def _execute(self, actor: User, query_id: str) -> DelegatedQueryView:
        from agentmesh.agents import PersonalAgent
        from agentmesh.artifacts import V1VerifiedArtifactStore

        claim = new_id('query_claim')
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            query = self._load(connection, query_id)
            _, target = _authority(connection, query, actor)
            if query.status != 'pending' or query.claim_id is not None:
                return self._view(connection, query, actor)
            _current_approval(connection, query)
            matched = _current_evidence(connection, query)
            if [_proof(item) for item in self._match(connection, query)] != query.evidence:
                raise DelegatedQueryError('query_evidence_changed')
            query.claim_id, query.claim_deadline = claim, now_utc() + timedelta(seconds=90)
            query.version += 1
            self._save(connection, query)
        try:
            result = PersonalAgent(self.store, llm_client=self.llm_client)._synthesize_delegated_answer(
                target, query.question, matched,
            )
        except Exception:
            from agentmesh.models import DelegatedAnswer, DelegatedAnswerStatus

            result = DelegatedAnswer(status=DelegatedAnswerStatus.BLOCKED, confidence=AnswerConfidence.NONE)
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self._load(connection, query.id)
            if current.status != 'pending' or current.claim_id != claim:
                return self._view(connection, current, actor)
            try:
                _authority(connection, current, actor)
                _current_approval(connection, current)
                _current_evidence(connection, current)
                if current.claim_deadline is None or current.claim_deadline <= now_utc():
                    raise DelegatedQueryError('query_deadline_expired')
                if [_proof(item) for item in self._match(connection, current)] != current.evidence:
                    raise DelegatedQueryError('query_evidence_changed')
                current.status = result.status.value
                if result.status == 'answered':
                    if not result.answer or len(result.answer) > 8192 or not result.citations:
                        raise DelegatedQueryError('query_answer_invalid')
                    citation = Source(title='经本人授权的代答结果', source_type='delegated_answer',
                                      reference=f'delegated-query://{current.id}', workspace_id=current.workspace_id,
                                      project_id=current.project_id, user_id=current.requester_id)
                    envelope = DelegatedAnswerArtifactV1(query_id=current.id, question_hash=current.question_hash,
                        answer=result.answer, citation=citation, confidence=result.confidence,
                        evidence_hash=canonical_json_sha256([proof.model_dump(mode='json') for proof in current.evidence]))
                    content = envelope.model_dump_json()
                    artifact = Artifact(run_id=current.id, workspace_id=current.workspace_id, project_id=current.project_id,
                                        user_id=current.requester_id, artifact_type='delegated_answer', content_type='application/json',
                                        content=content, verification_state=ArtifactVerificationState.SEALED,
                                        schema_version=_ARTIFACT_SCHEMA, requirement_version_id=current.question_hash,
                                        content_hash=hashlib.sha256(content.encode()).hexdigest(), size_bytes=len(content.encode()))
                    V1VerifiedArtifactStore._insert_row(connection, artifact)
                    self.store._upsert_plain_record(connection, 'sources', citation)
                    current.artifact_id, current.artifact_hash = artifact.id, artifact.content_hash
            except DelegatedQueryError as error:
                current.status, current.last_error_code = 'blocked', error.code
            current.version += 1
            self._save(connection, current)
        return self.get(actor, current.id)

    def get(self, actor: User, query_id: str) -> DelegatedQueryView:
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            query = self._load(connection, query_id)
            _authority(connection, query, actor)
            if query.status == 'pending' and query.claim_deadline and query.claim_deadline <= now_utc():
                query.status, query.last_error_code = 'failed', 'query_interrupted_requires_new_request'
                query.version += 1
                self._save(connection, query)
            return self._view(connection, query, actor)

    def resume(self, actor: User, query_id: str) -> DelegatedQueryView:
        """Resume only an approved request which has never claimed a model call."""
        current = self.get(actor, query_id)
        return self._execute(actor, query_id) if current.status == 'pending' else current

    def list(self, actor: User, project_id: str, *, limit: int = 50) -> DelegatedQueryList:
        if not 1 <= limit <= 50:
            raise DelegatedQueryError('query_page_invalid', 400)
        with closing(self.store._read_connect()) as connection, connection:
            connection.execute('BEGIN')
            self._authorize_project(connection, actor, project_id)
            rows = connection.execute(
                """SELECT payload FROM records WHERE collection = ? AND json_extract(payload, '$.workspace_id') = ?
                    AND json_extract(payload, '$.project_id') = ? AND (json_extract(payload, '$.requester_id') = ?
                    OR json_extract(payload, '$.target_id') = ?) ORDER BY created_order DESC LIMIT ?""",
                (_QUERY_COLLECTION, actor.workspace_id, project_id, actor.id, actor.id, limit),
            ).fetchall()
            items = []
            for row in rows:
                try:
                    items.append(self._view(connection, DelegatedQueryV1.model_validate_json(row['payload']), actor))
                except DelegatedQueryError:
                    continue
            return DelegatedQueryList(items=items)

    def adopt(self, actor: User, query_id: str, request: QueryAdoptRequest) -> QueryAdoptionV1:
        with closing(self.store._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            query = self._load(connection, query_id)
            _, target = _authority(connection, query, actor)
            if actor.id != query.requester_id:
                raise DelegatedQueryError('query_requester_required', 403)
            _current_approval(connection, query)
            _current_evidence(connection, query, ancestors=frozenset({query.id}))
            answer = _answer_artifact(connection, query)
            if query.status != 'answered' or query.artifact_hash != request.artifact_hash:
                raise DelegatedQueryError('verified_query_answer_required')
            if query.adoption:
                return query.adoption
            if query.version != request.expected_version:
                raise DelegatedQueryError('query_version_conflict')
            memory = UserMemoryItem(user_id=actor.id, workspace_id=query.workspace_id, project_id=query.project_id,
                                    layer=MemoryLayer.SHORT_TERM, scope=Scope.PRIVATE, source_kind='delegated_answer',
                                    title=f'采纳自 {target.name} 的代答', summary=answer.answer, sources=[answer.citation])
            point = ContributionPoint(awarded_to_id=target.id, awarded_by_id=actor.id, workspace_id=query.workspace_id,
                                      reason='delegated_answer_adopted', redeemable=False)
            relation = MemoryRelation(from_memory_id=memory.id, to_source_id=answer.citation.id, relation_type='derived_from')
            for collection, record in (('user_memory_items', memory), ('contribution_points', point), ('memory_relations', relation)):
                self.store._upsert_plain_record(connection, collection, record)
            self.store._sync_fts(connection, 'user_memory_items', memory)
            self.store.vector_index.mark_stale(connection, 'user_memory_items', memory.id)
            query.adoption = QueryAdoptionV1(command_id=request.command_id, memory_id=memory.id, point_id=point.id,
                                            relation_id=relation.id, artifact_hash=query.artifact_hash)
            query.version += 1
            self._save(connection, query)
            audit = AuditEvent(actor=actor.id, action='adopt_delegated_query', target_type='delegated_query',
                               target_id=query.id, workspace_id=query.workspace_id, project_id=query.project_id,
                               metadata={'artifact_hash': query.artifact_hash, 'memory_id': memory.id, 'point_id': point.id})
            self.store._upsert_plain_record(connection, 'audit_events', audit)
            return query.adoption
