"""Strict, versioned contracts for DeepSearch requirement refinement."""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.models import (
    AgentRun,
    CandidateSnapshotPublicViewV1,
    DeepSearchEvidenceCoverageV1,
    DeepSearchFinalizationStage,
    DeepSearchReviewOutcomeV1,
    ScenarioAssignmentOptionV1,
    SkillIntent,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSideEffect,
)
from agentmesh.task_routing.contracts import TaskRoutingResult

REQUIREMENT_SCHEMA_VERSION = "deepsearch-requirement-v1"
PROBLEM_GRAPH_SCHEMA_VERSION = "deepsearch-problem-graph-v1"
PLANNING_INPUT_SCHEMA_VERSION = "deepsearch-planning-input-v1"
MAX_CLARIFICATION_ROUNDS = 3
MAX_QUESTIONS_PER_ROUND = 5
MAX_ANSWER_LENGTH = 2_000
MAX_NORMALIZED_ANSWERS_BYTES = 8_000
MAX_REQUEST_IDENTITY_DEPTH = 8
MAX_REQUEST_IDENTITY_NODES = 256

_HASH_PATTERN = r"^[0-9a-f]{64}$"
_QUESTION_ID_PATTERN = r"^q_[1-9][0-9]*_[1-5]_[0-9a-f]{8}$"
_PROBLEM_QUESTION_ID_PATTERN = r"^question_[0-9a-f]{16}$"

type ClarificationAnswerValue = str | list[str]
type _ScopeItem = Annotated[str, Field(min_length=1, max_length=1_000)]
type _Option = Annotated[str, Field(min_length=1, max_length=MAX_ANSWER_LENGTH)]
type _Deliverable = Annotated[str, Field(min_length=1, max_length=1_000)]
type _ProblemQuestionId = Annotated[str, Field(pattern=_PROBLEM_QUESTION_ID_PATTERN)]
type _ProblemReference = Annotated[str, Field(min_length=1, max_length=120)]
type _ProblemStatement = Annotated[str, Field(min_length=1, max_length=MAX_ANSWER_LENGTH)]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ClarificationAnswerKind(StrEnum):
    TEXT = "text"
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"


class RequirementConstraintKind(StrEnum):
    TIME = "time"
    COST = "cost"
    SOURCE = "source"
    PERMISSION = "permission"
    FORMAT = "format"


class DeepSearchRetryDisposition(StrEnum):
    RETRY_RUN = "retry_run"
    REVISE_GOAL = "revise_goal"
    NONE = "none"


class RequirementScopeV1(_FrozenContract):
    objects: list[_ScopeItem] = Field(default_factory=list, max_length=20)
    regions: list[_ScopeItem] = Field(default_factory=list, max_length=20)
    time_range: str | None = Field(default=None, min_length=1, max_length=1_000)
    audiences: list[_ScopeItem] = Field(default_factory=list, max_length=20)
    boundaries: list[_ScopeItem] = Field(default_factory=list, max_length=20)


class RequirementConstraintV1(_FrozenContract):
    kind: RequirementConstraintKind
    statement: str = Field(min_length=1, max_length=2_000)


class RequirementSuccessCriterionV1(_FrozenContract):
    id: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=2_000)


class RequirementAssumptionV1(_FrozenContract):
    id: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=2_000)
    source: str = Field(min_length=1, max_length=120)
    editable_before_plan: bool = Field(strict=True)


class RequirementAmbiguityV1(_FrozenContract):
    id: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=2_000)
    blocking: bool = Field(strict=True)


def _normalize_text_answer(value: str, *, max_length: int = MAX_ANSWER_LENGTH) -> str:
    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized:
        raise ValueError("clarification answer must not be empty")
    if len(normalized) > max_length:
        raise ValueError("clarification answer exceeds max_length")
    return normalized


def problem_question_id(question: str) -> str:
    """Return the stable server-owned ID for one normalized research question."""

    normalized = _normalize_text_answer(question)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"question_{digest}"


class ProblemQuestionV1(_FrozenContract):
    id: _ProblemQuestionId
    question: str = Field(min_length=1, max_length=MAX_ANSWER_LENGTH)
    required: bool = Field(strict=True)
    success_criterion_ids: list[_ProblemReference] = Field(default_factory=list, max_length=20)
    evidence_requirements: list[_ProblemStatement] = Field(default_factory=list, max_length=20)
    acceptance_criteria: list[_ProblemStatement] = Field(default_factory=list, max_length=20)
    depends_on: list[_ProblemQuestionId] = Field(default_factory=list, max_length=20)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        return _normalize_text_answer(value)

    @model_validator(mode="after")
    def validate_question(self) -> ProblemQuestionV1:
        if self.id != problem_question_id(self.question):
            raise ValueError("problem question ID does not match its normalized question")
        for label, values in (
            ("success criterion", self.success_criterion_ids),
            ("evidence requirement", self.evidence_requirements),
            ("acceptance criterion", self.acceptance_criteria),
            ("dependency", self.depends_on),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"problem question {label} values must be unique")
        if self.id in self.depends_on:
            raise ValueError("problem question cannot depend on itself")
        if self.required and not self.success_criterion_ids:
            raise ValueError("required problem question must reference a success criterion")
        if self.required and not self.evidence_requirements:
            raise ValueError("required problem question must define evidence requirements")
        if self.required and not self.acceptance_criteria:
            raise ValueError("required problem question must define acceptance criteria")
        return self


class _ProblemGraphContentV1(_FrozenContract):
    schema_version: Literal["deepsearch-problem-graph-v1"] = PROBLEM_GRAPH_SCHEMA_VERSION
    requirement_version_id: str = Field(min_length=1, max_length=120)
    questions: list[ProblemQuestionV1] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_dependency_graph(self) -> _ProblemGraphContentV1:
        question_by_id = {question.id: question for question in self.questions}
        if len(question_by_id) != len(self.questions):
            raise ValueError("problem question IDs must be unique")
        if not any(question.required for question in self.questions):
            raise ValueError("problem graph must contain a required question")

        for question in self.questions:
            if question.id != problem_question_id(question.question):
                raise ValueError("problem question ID does not match its normalized question")
            unknown = set(question.depends_on) - set(question_by_id)
            if unknown:
                raise ValueError("problem question references an unknown dependency")
            if question.required and any(
                not question_by_id[dependency_id].required for dependency_id in question.depends_on
            ):
                raise ValueError("required problem question cannot depend on an optional question")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(question_id: str) -> None:
            if question_id in visited:
                return
            if question_id in visiting:
                raise ValueError("problem graph contains a dependency cycle")
            visiting.add(question_id)
            for dependency_id in question_by_id[question_id].depends_on:
                visit(dependency_id)
            visiting.remove(question_id)
            visited.add(question_id)

        for question_id in question_by_id:
            visit(question_id)
        return self


def problem_graph_hash(graph: _ProblemGraphContentV1 | Mapping[str, Any]) -> str:
    """Hash the immutable ProblemGraph projection, excluding its own hash."""

    if isinstance(graph, BaseModel):
        payload = graph.model_dump(mode="python", exclude={"content_hash"})
    else:
        payload = {key: value for key, value in graph.items() if key != "content_hash"}
    content = _ProblemGraphContentV1.model_validate(payload)
    return canonical_json_sha256(content.model_dump(mode="python"))


class ProblemGraphV1(_ProblemGraphContentV1):
    content_hash: str = Field(pattern=_HASH_PATTERN)

    @model_validator(mode="after")
    def validate_content_hash(self) -> ProblemGraphV1:
        if self.content_hash != problem_graph_hash(self):
            raise ValueError("ProblemGraph content_hash does not match the canonical graph")
        return self


def _normalize_answer_shape(value: object) -> ClarificationAnswerValue:
    if isinstance(value, str):
        return _normalize_text_answer(value)
    if isinstance(value, list):
        if not value:
            raise ValueError("clarification answer must not be empty")
        if any(not isinstance(item, str) for item in value):
            raise ValueError("clarification answer list must contain only strings")
        normalized = [_normalize_text_answer(item) for item in value]
        return sorted(normalized)
    raise ValueError("clarification answer must be a string or a list of strings")


class _QuestionFields(_FrozenContract):
    prompt: str = Field(min_length=1, max_length=2_000)
    required: bool = Field(strict=True)
    answer_kind: ClarificationAnswerKind
    options: list[_Option] = Field(default_factory=list, max_length=20)
    max_length: int = Field(default=MAX_ANSWER_LENGTH, ge=1, le=MAX_ANSWER_LENGTH, strict=True)
    default_value: ClarificationAnswerValue | None = None

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return unicodedata.normalize("NFC", value)

    @field_validator("options")
    @classmethod
    def normalize_options(cls, value: list[str]) -> list[str]:
        return [unicodedata.normalize("NFC", item) for item in value]

    @field_validator("default_value", mode="before")
    @classmethod
    def reject_non_answer_defaults(cls, value: object) -> object:
        if value is None:
            return None
        return _normalize_answer_shape(value)

    @model_validator(mode="after")
    def validate_kind_contract(self) -> _QuestionFields:
        if len(set(self.options)) != len(self.options):
            raise ValueError("clarification question options must be unique")
        if any(not option for option in self.options):
            raise ValueError("clarification question options must not be empty")

        if self.answer_kind is ClarificationAnswerKind.TEXT:
            if self.options:
                raise ValueError("text clarification questions cannot define options")
            if self.default_value is not None and not isinstance(self.default_value, str):
                raise ValueError("text clarification question default must be a string")
            if isinstance(self.default_value, str) and len(self.default_value) > self.max_length:
                raise ValueError("clarification question default exceeds max_length")
            return self

        if not self.options:
            raise ValueError("choice clarification questions require options")
        if self.answer_kind is ClarificationAnswerKind.SINGLE_CHOICE:
            if self.default_value is not None and not isinstance(self.default_value, str):
                raise ValueError("single-choice clarification question default must be a string")
            if isinstance(self.default_value, str) and self.default_value not in self.options:
                raise ValueError("single-choice clarification question default is not an option")
            return self

        if self.default_value is not None and not isinstance(self.default_value, list):
            raise ValueError("multi-choice clarification question default must be a list")
        if isinstance(self.default_value, list):
            if len(set(self.default_value)) != len(self.default_value):
                raise ValueError("multi-choice clarification question default must be unique")
            if any(item not in self.options for item in self.default_value):
                raise ValueError("multi-choice clarification question default is not an option")
        return self


class ClarificationQuestionDraftV1(_QuestionFields):
    """Model-facing question draft; IDs are deliberately absent and server-owned."""


class ClarificationQuestionV1(_QuestionFields):
    id: str = Field(pattern=_QUESTION_ID_PATTERN)


def clarification_question_id(*, version: int, ordinal: int, prompt: str) -> str:
    """Return the stable server-owned ID for a question in one Requirement version."""

    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("requirement version must be positive")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1 or ordinal > MAX_QUESTIONS_PER_ROUND:
        raise ValueError("clarification question ordinal must be between one and five")
    normalized_prompt = _normalize_text_answer(prompt)
    prompt_hash = hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest()[:8]
    return f"q_{version}_{ordinal}_{prompt_hash}"


def materialize_clarification_questions(
    *,
    version: int,
    drafts: Sequence[ClarificationQuestionDraftV1],
) -> list[ClarificationQuestionV1]:
    """Attach deterministic IDs to at most one round of model-produced drafts."""

    if len(drafts) > MAX_QUESTIONS_PER_ROUND:
        raise ValueError("a clarification round cannot contain more than five questions")
    return [
        ClarificationQuestionV1(
            id=clarification_question_id(version=version, ordinal=ordinal, prompt=draft.prompt),
            **draft.model_dump(mode="python"),
        )
        for ordinal, draft in enumerate(drafts, start=1)
    ]


def normalize_clarification_answers(
    *,
    questions: Sequence[ClarificationQuestionV1],
    answers: Mapping[str, object],
) -> dict[str, ClarificationAnswerValue]:
    """Validate answers against one frozen question set and return canonical values."""

    if len(answers) > MAX_QUESTIONS_PER_ROUND:
        raise ValueError("a clarification round cannot contain more than five answers")
    question_by_id = {question.id: question for question in questions}
    if len(question_by_id) != len(questions):
        raise ValueError("clarification question IDs must be unique")
    unknown = set(answers) - set(question_by_id)
    if unknown:
        raise ValueError("clarification answers contain unknown question IDs")
    missing = {question.id for question in questions if question.required and question.id not in answers}
    if missing:
        raise ValueError("required clarification answers are missing")

    normalized: dict[str, ClarificationAnswerValue] = {}
    for question_id, raw_value in answers.items():
        question = question_by_id[question_id]
        value = _normalize_answer_shape(raw_value)
        if question.answer_kind is ClarificationAnswerKind.TEXT:
            if not isinstance(value, str):
                raise ValueError("text clarification answer must be a string")
            normalized[question_id] = _normalize_text_answer(value, max_length=question.max_length)
        elif question.answer_kind is ClarificationAnswerKind.SINGLE_CHOICE:
            if not isinstance(value, str) or value not in question.options:
                raise ValueError("single-choice clarification answer must be one listed option")
            normalized[question_id] = value
        else:
            if not isinstance(value, list):
                raise ValueError("multi-choice clarification answer must be a list")
            if len(set(value)) != len(value):
                raise ValueError("multi-choice clarification answer must be unique")
            if any(item not in question.options for item in value):
                raise ValueError("multi-choice clarification answer must contain only listed options")
            normalized[question_id] = sorted(value)

    if len(canonical_json_bytes(normalized)) > MAX_NORMALIZED_ANSWERS_BYTES:
        raise ValueError("normalized clarification answers exceed 8000 bytes")
    return normalized


class ClarificationHistoryRoundV1(_FrozenContract):
    round: int = Field(ge=1, le=MAX_CLARIFICATION_ROUNDS, strict=True)
    questions: list[ClarificationQuestionV1] = Field(min_length=1, max_length=MAX_QUESTIONS_PER_ROUND)
    answers: dict[str, ClarificationAnswerValue] = Field(default_factory=dict, max_length=MAX_QUESTIONS_PER_ROUND)

    @model_validator(mode="after")
    def validate_answers(self) -> ClarificationHistoryRoundV1:
        normalized = normalize_clarification_answers(questions=self.questions, answers=self.answers)
        if normalized != self.answers:
            raise ValueError("clarification history answers must already be normalized")
        return self


class _RequirementContentV1(_FrozenContract):
    goal: str = Field(min_length=1, max_length=4_000)
    scope: RequirementScopeV1
    constraints: list[RequirementConstraintV1] = Field(default_factory=list, max_length=20)
    success_criteria: list[RequirementSuccessCriterionV1] = Field(min_length=1, max_length=20)
    deliverables: list[_Deliverable] = Field(min_length=1, max_length=10)
    assumptions: list[RequirementAssumptionV1] = Field(default_factory=list, max_length=20)
    ambiguities: list[RequirementAmbiguityV1] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_content_ids(self) -> _RequirementContentV1:
        for label, items in (
            ("success criterion", self.success_criteria),
            ("assumption", self.assumptions),
            ("ambiguity", self.ambiguities),
        ):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} IDs must be unique")
        return self


class RequirementRefinementDraftV1(_RequirementContentV1):
    """Model-facing Requirement draft with no server-owned history, round, or question IDs."""

    clarification_questions: list[ClarificationQuestionDraftV1] = Field(
        default_factory=list,
        max_length=MAX_QUESTIONS_PER_ROUND,
    )

    @model_validator(mode="after")
    def validate_questions_follow_ambiguities(self) -> RequirementRefinementDraftV1:
        if self.clarification_questions and not any(item.blocking for item in self.ambiguities):
            raise ValueError("clarification questions require a blocking ambiguity")
        return self


class RequirementPayloadV1(_RequirementContentV1):
    clarification_questions: list[ClarificationQuestionV1] = Field(
        default_factory=list,
        max_length=MAX_QUESTIONS_PER_ROUND,
    )
    clarification_history: list[ClarificationHistoryRoundV1] = Field(
        default_factory=list,
        max_length=MAX_CLARIFICATION_ROUNDS,
    )
    clarification_round: int = Field(default=0, ge=0, le=MAX_CLARIFICATION_ROUNDS, strict=True)

    @model_validator(mode="after")
    def validate_requirement(self) -> RequirementPayloadV1:
        question_ids = [item.id for item in self.clarification_questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("clarification question IDs must be unique")

        history_rounds = [item.round for item in self.clarification_history]
        if history_rounds != list(range(1, len(history_rounds) + 1)):
            raise ValueError("clarification history rounds must be contiguous and ordered")
        if any(round_number > self.clarification_round for round_number in history_rounds):
            raise ValueError("clarification history cannot exceed the current round")
        if self.clarification_round == 0 and (self.clarification_questions or self.clarification_history):
            raise ValueError("round zero cannot contain clarification questions or history")
        expected_history_count = (
            self.clarification_round - 1
            if self.clarification_questions
            else self.clarification_round
        )
        if len(history_rounds) != expected_history_count:
            raise ValueError("clarification round must match its history and current questions")

        has_blocking_ambiguity = any(item.blocking for item in self.ambiguities)
        if self.clarification_questions and not has_blocking_ambiguity:
            raise ValueError("clarification questions require a blocking ambiguity")
        clarification_exhausted = (
            self.clarification_round == MAX_CLARIFICATION_ROUNDS
            and history_rounds
            and history_rounds[-1] == MAX_CLARIFICATION_ROUNDS
        )
        if has_blocking_ambiguity and not self.clarification_questions and not clarification_exhausted:
            raise ValueError("a blocking ambiguity requires clarification questions")

        historical_id_list = [
            question.id for history_round in self.clarification_history for question in history_round.questions
        ]
        if len(historical_id_list) != len(set(historical_id_list)):
            raise ValueError("historical clarification question IDs must not be reused")
        if set(historical_id_list).intersection(question.id for question in self.clarification_questions):
            raise ValueError("current clarification question IDs cannot reuse historical IDs")
        return self


def materialize_requirement_payload(
    *,
    previous: RequirementVersionV1 | None,
    draft: RequirementRefinementDraftV1,
    answers: Mapping[str, object],
    target_version: int,
) -> RequirementPayloadV1:
    """Build a persisted Requirement without trusting model-owned lifecycle fields."""

    expected_version = 1 if previous is None else previous.version + 1
    if isinstance(target_version, bool) or not isinstance(target_version, int) or target_version != expected_version:
        raise ValueError("target Requirement version is not the next version")

    history: list[ClarificationHistoryRoundV1]
    if previous is None:
        if answers:
            raise ValueError("initial Requirement cannot contain clarification answers")
        history = []
        previous_round = 0
    else:
        if not previous.payload.clarification_questions:
            raise ValueError("active Requirement has no clarification questions")
        normalized_answers = normalize_clarification_answers(
            questions=previous.payload.clarification_questions,
            answers=answers,
        )
        history = [
            *previous.payload.clarification_history,
            ClarificationHistoryRoundV1(
                round=previous.payload.clarification_round,
                questions=previous.payload.clarification_questions,
                answers=normalized_answers,
            ),
        ]
        previous_round = previous.payload.clarification_round

    has_blocking_ambiguity = any(item.blocking for item in draft.ambiguities)
    if not has_blocking_ambiguity and draft.clarification_questions:
        raise ValueError("clarification questions require a blocking ambiguity")

    if has_blocking_ambiguity and previous_round >= MAX_CLARIFICATION_ROUNDS:
        clarification_round = MAX_CLARIFICATION_ROUNDS
        questions: list[ClarificationQuestionV1] = []
    elif has_blocking_ambiguity:
        if not draft.clarification_questions:
            raise ValueError("a blocking ambiguity requires clarification questions")
        clarification_round = previous_round + 1
        questions = materialize_clarification_questions(version=target_version, drafts=draft.clarification_questions)
    else:
        clarification_round = previous_round
        questions = []

    content = draft.model_dump(mode="python", exclude={"clarification_questions"})
    return RequirementPayloadV1(
        **content,
        clarification_questions=questions,
        clarification_history=history,
        clarification_round=clarification_round,
    )


def requirement_content_hash(
    payload: RequirementPayloadV1 | Mapping[str, Any],
    *,
    schema_version: str = REQUIREMENT_SCHEMA_VERSION,
) -> str:
    """Hash the immutable Requirement schema version and payload only."""

    if schema_version != REQUIREMENT_SCHEMA_VERSION:
        raise ValueError("unsupported DeepSearch Requirement schema version")
    validated = payload if isinstance(payload, RequirementPayloadV1) else RequirementPayloadV1.model_validate(payload)
    return canonical_json_sha256(
        {
            "schema_version": schema_version,
            "payload": validated.model_dump(mode="python"),
        }
    )


class RequirementVersionV1(_FrozenContract):
    id: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1, strict=True)
    schema_version: Literal["deepsearch-requirement-v1"] = REQUIREMENT_SCHEMA_VERSION
    request_key: str = Field(min_length=1, max_length=120)
    request_hash: str = Field(pattern=_HASH_PATTERN)
    content_hash: str = Field(pattern=_HASH_PATTERN)
    derived_from_requirement_version_id: str | None = Field(default=None, min_length=1, max_length=120)
    payload: RequirementPayloadV1
    created_at: datetime

    @model_validator(mode="after")
    def validate_integrity(self) -> RequirementVersionV1:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Requirement version created_at must include a timezone")
        if self.derived_from_requirement_version_id == self.id:
            raise ValueError("Requirement version cannot derive from itself")
        expected_hash = requirement_content_hash(self.payload, schema_version=self.schema_version)
        if self.content_hash != expected_hash:
            raise ValueError("Requirement content_hash does not match the canonical payload")
        for ordinal, question in enumerate(self.payload.clarification_questions, start=1):
            expected_id = clarification_question_id(
                version=self.version,
                ordinal=ordinal,
                prompt=question.prompt,
            )
            if question.id != expected_id:
                raise ValueError("clarification question ID does not match its Requirement version")
        return self


def canonical_planning_input(requirement: RequirementVersionV1) -> str:
    """Serialize the one immutable Requirement input consumed by every planning stage."""

    requirement = RequirementVersionV1.model_validate(requirement.model_dump(mode="python"))
    if requirement.payload.clarification_questions or any(
        ambiguity.blocking for ambiguity in requirement.payload.ambiguities
    ):
        raise ValueError("canonical planning input requires a complete Requirement")
    return canonical_json_bytes(
        {
            "schema_version": PLANNING_INPUT_SCHEMA_VERSION,
            "requirement_version_id": requirement.id,
            "requirement_content_hash": requirement.content_hash,
            "requirement": requirement.payload.model_dump(mode="python"),
        }
    ).decode("utf-8")


def validate_problem_graph_against_requirement(
    *,
    graph: ProblemGraphV1,
    requirement: RequirementVersionV1,
) -> None:
    """Validate graph lineage and semantic coverage against one frozen Requirement."""

    graph = ProblemGraphV1.model_validate(graph.model_dump(mode="python"))
    requirement = RequirementVersionV1.model_validate(requirement.model_dump(mode="python"))
    if graph.requirement_version_id != requirement.id:
        raise ValueError("ProblemGraph does not belong to the current Requirement version")

    known_criterion_ids = {criterion.id for criterion in requirement.payload.success_criteria}
    referenced_criterion_ids = {
        criterion_id
        for question in graph.questions
        for criterion_id in question.success_criterion_ids
    }
    unknown_criterion_ids = referenced_criterion_ids - known_criterion_ids
    if unknown_criterion_ids:
        raise ValueError("ProblemGraph references an unknown success criterion")

    required_coverage = {
        criterion_id
        for question in graph.questions
        if question.required
        for criterion_id in question.success_criterion_ids
    }
    if known_criterion_ids - required_coverage:
        raise ValueError("Requirement success criteria are not covered by required questions")


def validate_plan_question_coverage(
    *,
    graph: ProblemGraphV1,
    nodes: Sequence[SkillPlanNode],
) -> None:
    """Validate the public ProblemQuestion references frozen into Plan nodes."""

    graph = ProblemGraphV1.model_validate(graph.model_dump(mode="python"))
    validated_nodes = [
        SkillPlanNode.model_validate(node.model_dump(mode="python"))
        for node in nodes
    ]
    known_question_ids = {question.id for question in graph.questions}
    referenced_question_ids = {
        question_id
        for node in validated_nodes
        for question_id in node.question_ids
    }
    if referenced_question_ids - known_question_ids:
        raise ValueError("Plan node references an unknown ProblemQuestion")

    required_question_ids = {
        question.id for question in graph.questions if question.required
    }
    required_node_coverage = {
        question_id
        for node in validated_nodes
        if node.required
        for question_id in node.question_ids
    }
    if required_question_ids - required_node_coverage:
        raise ValueError("required ProblemQuestions are not covered by required Plan nodes")


def build_problem_graph(
    *,
    requirement: RequirementVersionV1,
    questions: Sequence[ProblemQuestionV1],
) -> ProblemGraphV1:
    """Freeze and hash a ProblemGraph owned by one validated Requirement version."""

    requirement = RequirementVersionV1.model_validate(requirement.model_dump(mode="python"))
    content = _ProblemGraphContentV1(
        requirement_version_id=requirement.id,
        questions=list(questions),
    )
    graph = ProblemGraphV1(
        **content.model_dump(mode="python"),
        content_hash=problem_graph_hash(content),
    )
    validate_problem_graph_against_requirement(graph=graph, requirement=requirement)
    return graph


class DeepSearchClarifyRequestV1(_FrozenContract):
    """Wire request; answer semantics are intentionally checked after the stale-version fence."""

    client_turn_id: str = Field(min_length=1, max_length=120)
    expected_requirement_version: int = Field(ge=1, strict=True)
    answers: dict[str, Any]


def _normalize_request_identity_value(
    value: Any,
    *,
    depth: int = 0,
    remaining_nodes: list[int] | None = None,
) -> Any:
    """Canonicalize JSON syntax without deciding whether it is a valid answer."""

    if remaining_nodes is None:
        remaining_nodes = [MAX_REQUEST_IDENTITY_NODES]
    if remaining_nodes[0] <= 0:
        raise ValueError("clarification request answer is too complex")
    remaining_nodes[0] -= 1
    if depth > MAX_REQUEST_IDENTITY_DEPTH:
        raise ValueError("clarification request answer is nested too deeply")
    if isinstance(value, str):
        if (
            len(value) > MAX_NORMALIZED_ANSWERS_BYTES
            or len(value.encode("utf-8")) > MAX_NORMALIZED_ANSWERS_BYTES
        ):
            raise ValueError("normalized clarification answers exceed 8000 bytes")
        return unicodedata.normalize("NFC", value.strip())
    if value is None or isinstance(value, (bool, int, Decimal)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("clarification request contains a non-finite number")
        return Decimal(str(value))
    if isinstance(value, list):
        if len(value) > remaining_nodes[0]:
            raise ValueError("clarification request answer is too complex")
        normalized = [
            _normalize_request_identity_value(
                item,
                depth=depth + 1,
                remaining_nodes=remaining_nodes,
            )
            for item in value
        ]
        if all(isinstance(item, str) for item in normalized):
            normalized.sort()
        return normalized
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("clarification request object keys must be strings")
        if len(value) > remaining_nodes[0]:
            raise ValueError("clarification request answer is too complex")
        normalized_mapping: dict[str, Any] = {}
        for key, item in value.items():
            if (
                len(key) > MAX_NORMALIZED_ANSWERS_BYTES
                or len(key.encode("utf-8")) > MAX_NORMALIZED_ANSWERS_BYTES
            ):
                raise ValueError("normalized clarification answers exceed 8000 bytes")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized_mapping:
                raise ValueError("clarification request contains duplicate normalized keys")
            normalized_mapping[normalized_key] = _normalize_request_identity_value(
                item,
                depth=depth + 1,
                remaining_nodes=remaining_nodes,
            )
        return normalized_mapping
    raise ValueError("clarification request answer is not a JSON value")


def normalize_clarification_request_answers(answers: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize raw JSON solely for idempotency; semantic checks happen after the version fence."""

    if len(answers) > MAX_QUESTIONS_PER_ROUND:
        raise ValueError("a clarification round cannot contain more than five answers")
    if any(not isinstance(question_id, str) for question_id in answers):
        raise ValueError("clarification answer keys must be strings")
    normalized: dict[str, Any] = {}
    remaining_nodes = [MAX_REQUEST_IDENTITY_NODES]
    for question_id, value in answers.items():
        if (
            len(question_id) > MAX_NORMALIZED_ANSWERS_BYTES
            or len(question_id.encode("utf-8")) > MAX_NORMALIZED_ANSWERS_BYTES
        ):
            raise ValueError("normalized clarification answers exceed 8000 bytes")
        normalized_id = unicodedata.normalize("NFC", question_id)
        if normalized_id in normalized:
            raise ValueError("clarification request contains duplicate normalized question IDs")
        normalized[normalized_id] = _normalize_request_identity_value(
            value,
            depth=1,
            remaining_nodes=remaining_nodes,
        )
    if len(canonical_json_bytes(normalized)) > MAX_NORMALIZED_ANSWERS_BYTES:
        raise ValueError("normalized clarification answers exceed 8000 bytes")
    return normalized


def clarification_request_hash(
    *,
    run_id: str,
    expected_requirement_version: int,
    normalized_answers: Mapping[str, Any],
) -> str:
    """Hash the immutable identity of one clarification submission."""

    if not run_id:
        raise ValueError("run_id must not be empty")
    if (
        isinstance(expected_requirement_version, bool)
        or not isinstance(expected_requirement_version, int)
        or expected_requirement_version < 1
    ):
        raise ValueError("expected Requirement version must be positive")
    canonical_answers = normalize_clarification_request_answers(normalized_answers)
    return canonical_json_sha256(
        {
            "run_id": run_id,
            "expected_requirement_version": expected_requirement_version,
            "normalized_answers": canonical_answers,
        }
    )


class DeepSearchPlanNodeViewV1(_FrozenContract):
    """Public Plan node projection without resource hashes or hidden prompts."""

    id: str
    skill_id: str
    skill_version: str
    reason: str
    task_id: str | None = None
    scenario_id: str | None = None
    required: bool
    depends_on: list[str]
    parallel_group: str | None = None
    question_ids: list[str]
    output_contract: list[str]
    required_tool_names: list[str]
    completion_criteria: list[str]
    side_effect: SkillSideEffect
    status: SkillPlanNodeStatus
    attempt: int
    error_code: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_plan_node(cls, node: SkillPlanNode) -> DeepSearchPlanNodeViewV1:
        return cls.model_validate(
            node.model_dump(
                mode="python",
                include=set(cls.model_fields),
            )
        )


class DeepSearchPlanViewV1(_FrozenContract):
    """Public Plan projection; finalization payload bodies stay server-only."""

    id: str
    run_id: str
    version: int
    status: SkillPlanStatus
    intent: SkillIntent
    routing_result: TaskRoutingResult | None = None
    candidate_skill_ids: list[str]
    candidate_snapshot: CandidateSnapshotPublicViewV1 | None = None
    output_contract: list[str]
    synthesis_output_contract: list[str]
    capability_gaps: list[str]
    preferred_order: list[str]
    nodes: list[DeepSearchPlanNodeViewV1]
    requirement_version_id: str
    requirement_content_hash: str
    problem_graph_hash: str
    plan_content_hash: str
    approved_plan_artifact_id: str | None = None
    evidence_manifest_artifact_id: str | None = None
    evidence_manifest_hash: str | None = None
    report_artifact_id: str | None = None
    report_content_hash: str | None = None
    report_revision_count: int
    finalization_stage: DeepSearchFinalizationStage
    finalization_version: int
    degradation: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_plan(cls, plan: SkillPlan) -> DeepSearchPlanViewV1:
        payload = plan.model_dump(
            mode="python",
            include=set(cls.model_fields) - {"nodes", "candidate_snapshot"},
        )
        payload["nodes"] = [DeepSearchPlanNodeViewV1.from_plan_node(node) for node in plan.nodes]
        payload["candidate_snapshot"] = (
            CandidateSnapshotPublicViewV1.from_snapshot(plan.candidate_snapshot)
            if plan.candidate_snapshot is not None
            else None
        )
        return cls.model_validate(payload)


class DeepSearchPlanDetailResponse(_FrozenContract):
    """Public response for the shared Plan endpoint when the Run is DeepSearch."""

    plan: DeepSearchPlanViewV1
    results: list[SkillNodeResult] = Field(default_factory=list)
    synthesis: None = None
    scenario_assignment_options: dict[str, list[ScenarioAssignmentOptionV1]] = Field(
        default_factory=dict
    )


class DeepSearchPlanTransitionResponse(_FrozenContract):
    """Public response for DeepSearch Plan approval and rejection."""

    plan: DeepSearchPlanViewV1
    run: AgentRun


class DeepSearchReviewViewV1(_FrozenContract):
    """Review identifiers and codes only; no reviewer-generated prose."""

    revision_count: int
    outcome: Literal["not_run", "pass", "revise", "block", "error"]
    reason_code: str | None = None
    unsupported_claim_ids: list[str] = Field(default_factory=list)
    contradictory_claim_ids: list[str] = Field(default_factory=list)
    missing_section_ids: list[str] = Field(default_factory=list)
    limitation_codes: list[str] = Field(default_factory=list)

    @classmethod
    def from_outcome(cls, outcome: DeepSearchReviewOutcomeV1) -> DeepSearchReviewViewV1:
        review = outcome.review
        return cls(
            revision_count=outcome.revision_count,
            outcome=outcome.outcome,
            reason_code=outcome.reason_code,
            unsupported_claim_ids=(review.unsupported_claim_ids if review is not None else []),
            contradictory_claim_ids=(
                review.contradictory_claim_ids if review is not None else []
            ),
            missing_section_ids=(review.missing_section_ids if review is not None else []),
            limitation_codes=(review.limitation_codes if review is not None else []),
        )


class DeepSearchStateResponse(_FrozenContract):
    """Authoritative DeepSearch aggregate used for reload and conflict recovery."""

    run: AgentRun
    active_requirement: RequirementVersionV1 | None
    problem_graph: ProblemGraphV1 | None = None
    plan: DeepSearchPlanViewV1 | None = None
    evidence_coverage: DeepSearchEvidenceCoverageV1 | None = None
    report_review: DeepSearchReviewViewV1 | None = None
    scenario_assignment_options: dict[str, list[ScenarioAssignmentOptionV1]] = Field(
        default_factory=dict
    )
    retry_disposition: DeepSearchRetryDisposition = DeepSearchRetryDisposition.NONE
