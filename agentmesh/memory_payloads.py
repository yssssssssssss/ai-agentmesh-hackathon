"""Versioned payloads attached to existing governed Memory identities."""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identity = Annotated[str, Field(min_length=1, max_length=120)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Instruction = Annotated[str, Field(min_length=1, max_length=1000)]
SubjectType = Literal["project", "task", "user", "term"]


def normalize_term_name(name: str) -> str:
    normalized = ' '.join(unicodedata.normalize('NFC', name).casefold().split())
    if (not normalized or len(normalized) > 100 or '::' in normalized
            or any(unicodedata.category(character).startswith('C') for character in normalized)):
        raise ValueError('term_name_invalid')
    return normalized


class ProjectTermAliasesV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    schema_version: Literal['project-term-aliases-v1'] = 'project-term-aliases-v1'
    version: int = Field(ge=0)
    aliases: dict[Identity, Identity] = Field(default_factory=dict, max_length=200)
    confirmed_by: Identity | None = None
    confirmed_at: AwareDatetime | None = None

    @model_validator(mode='after')
    def validate_aliases(self) -> ProjectTermAliasesV1:
        if (self.confirmed_by is None) != (self.confirmed_at is None) or (
            self.version == 0 and (self.aliases or self.confirmed_by is not None)
        ) or (self.version > 0 and self.confirmed_by is None):
            raise ValueError('term_alias_confirmation_invalid')
        if any(normalize_term_name(alias) != alias or normalize_term_name(canonical) != canonical
               or alias == canonical or canonical in self.aliases for alias, canonical in self.aliases.items()):
            raise ValueError('term_alias_mapping_invalid')
        return self


class TermResolutionV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    canonical_subject_id: Identity
    matched_subject_ids: list[Identity] = Field(min_length=1, max_length=201)
    alias_version: int = Field(ge=1)
    confirmed_by: Identity
    confirmed_at: AwareDatetime


class MemoryEvidenceRefV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal["document", "artifact", "source", "source_span", "task_review"]
    record_id: Identity
    version: int = Field(ge=1)
    content_hash: Hash


class FactAssertionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    subject_type: SubjectType
    subject_id: Identity
    predicate: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    value: str = Field(min_length=1, max_length=2000)
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None
    time_precision: Literal["instant", "day", "month", "unknown"] = "instant"

    @model_validator(mode="after")
    def validate_interval(self) -> FactAssertionV1:
        if self.time_precision == "unknown":
            if self.valid_from is not None or self.valid_to is not None:
                raise ValueError("unknown precision cannot invent valid-time bounds")
        elif self.valid_from is None:
            raise ValueError("known precision requires valid_from")
        if self.valid_to is not None and (self.valid_from is None or self.valid_to <= self.valid_from):
            raise ValueError("valid_to must follow valid_from; intervals are half-open")
        if self.time_precision in {"day", "month"}:
            for boundary in (self.valid_from, self.valid_to):
                if boundary is not None and (
                    any((boundary.hour, boundary.minute, boundary.second, boundary.microsecond))
                    or (self.time_precision == "month" and boundary.day != 1)
                ):
                    raise ValueError("coarse precision requires matching local calendar boundaries")
        return self


class MemoryFactV1(FactAssertionV1):
    schema_version: Literal["memory-fact-v1"] = "memory-fact-v1"
    observed_at: AwareDatetime
    evidence_refs: list[MemoryEvidenceRefV1] = Field(min_length=1, max_length=20)
    source_classification: Literal["human_confirmed", "system_observation", "model_inference"]
    conflict_group: Identity | None = None


class ProcedureDraftV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    goal_patterns: list[Instruction] = Field(min_length=1, max_length=8)
    preconditions: list[Instruction] = Field(default_factory=list, max_length=12)
    tool_versions: dict[Identity, Identity] = Field(default_factory=dict, max_length=16)
    environment_versions: dict[Identity, Identity] = Field(default_factory=dict, max_length=16)
    steps: list[Instruction] = Field(min_length=1, max_length=20)
    validation_conditions: list[Instruction] = Field(min_length=1, max_length=12)


class ProcedureRunEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Identity
    review_ref: MemoryEvidenceRefV1
    artifact_refs: list[MemoryEvidenceRefV1] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_reference_types(self) -> ProcedureRunEvidenceV1:
        if self.review_ref.record_type != "task_review" or any(
            ref.record_type != "artifact" for ref in self.artifact_refs
        ):
            raise ValueError("procedure evidence requires a Review and Artifact references")
        return self


class ProcedureMemoryV1(ProcedureDraftV1):
    schema_version: Literal["procedure-memory-v1"] = "procedure-memory-v1"
    successful_runs: list[ProcedureRunEvidenceV1] = Field(default_factory=list, max_length=12)
    failed_runs: list[Identity] = Field(default_factory=list, max_length=12)
    human_confirmed_by: Identity | None = None
    human_confirmed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_confirmation(self) -> ProcedureMemoryV1:
        if (self.human_confirmed_by is None) != (self.human_confirmed_at is None):
            raise ValueError("human confirmation requires both actor and time")
        if self.human_confirmed_by is not None and not self.successful_runs:
            raise ValueError("confirmed procedure requires a successful reviewed run")
        if len({item.run_id for item in self.successful_runs}) != len(self.successful_runs):
            raise ValueError("procedure successful runs must be unique")
        if set(self.failed_runs) & {item.run_id for item in self.successful_runs}:
            raise ValueError("a procedure run cannot be both successful and failed")
        return self


def structured_request_content(request: BaseModel, *, preserve_explicit_null: bool = False) -> dict:
    """Keep old command hashes byte-compatible when new optional payloads are absent."""
    absent = {
        name for name in ("facts", "procedure") if getattr(request, name, None) is None
        and (not preserve_explicit_null or name not in request.model_fields_set)
    }
    return request.model_dump(mode="json", exclude=absent)


class FactRememberV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    command_id: Identity
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    project_id: Identity
    source_document_id: Identity
    source_version: int = Field(ge=1)
    source_hash: Hash
    facts: list[FactAssertionV1] = Field(min_length=1, max_length=32)
    supersedes_memory_id: Identity | None = None
    expected_memory_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_revision(self) -> FactRememberV1:
        if (self.supersedes_memory_id is None) != (self.expected_memory_version is None):
            raise ValueError("personal corrections require source Memory and expected version")
        return self


class FactQueryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: Identity
    subject_type: SubjectType
    subject_id: Identity
    predicate: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    as_of: AwareDatetime | None = None
    interval_from: AwareDatetime | None = None
    interval_to: AwareDatetime | None = None
    observed_before: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_query_time(self) -> FactQueryV1:
        if (self.interval_from is None) != (self.interval_to is None):
            raise ValueError("interval queries require both bounds")
        if self.interval_from is not None and (
            self.as_of is not None or self.interval_to <= self.interval_from
        ):
            raise ValueError("query must select a point or a positive interval")
        return self


class FactHitV1(BaseModel):
    memory_id: Identity
    memory_record_type: Literal["memory_item", "user_memory_item"]
    memory_version: int = Field(ge=1)
    memory_hash: Hash
    scope: str
    status: str
    fact: MemoryFactV1


class FactConflictV1(BaseModel):
    group_id: Identity
    fact_indexes: list[int] = Field(min_length=2)


class FactQueryResultV1(BaseModel):
    schema_version: Literal["fact-query-result-v1"] = "fact-query-result-v1"
    project_id: Identity
    snapshot_at: AwareDatetime
    outcome: Literal["known", "unknown", "conflict", "insufficient_evidence"]
    facts: list[FactHitV1] = Field(default_factory=list, max_length=100)
    conflicts: list[FactConflictV1] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    automatic_context_eligible: bool = False
    term_resolution: TermResolutionV1 | None = Field(default=None, exclude_if=lambda value: value is None)
