from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentmesh.research_orchestration.contracts import (
    ExecutionPlanVersion,
    ProblemContract,
    RequirementVersion,
    ResearchTaskV2,
    Sha256Hex,
    canonical_json_bytes,
    canonical_sha256,
)


class PlanCompileError(RuntimeError):
    def __init__(self, *codes: str):
        self.codes = list(dict.fromkeys(codes))
        super().__init__(", ".join(self.codes))


class FrozenDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: Any
    content_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> FrozenDocument:
        if canonical_sha256(self.content) != self.content_hash:
            raise ValueError("frozen document hash does not match content")
        return self


class FrozenTextDocument(BaseModel):
    """A byte-faithful UTF-8 control document such as SKILL.md or agentmesh.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    content_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> FrozenTextDocument:
        if hashlib.sha256(self.content.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("frozen text hash does not match UTF-8 content")
        return self


class FrozenResourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=120)
    schema_version: Literal["resource-snapshot-v1"] = "resource-snapshot-v1"
    content_hash: Sha256Hex
    size_bytes: int = Field(ge=2, le=1024 * 1024)
    manifest: FrozenDocument

    @model_validator(mode="after")
    def validate_manifest(self) -> FrozenResourceSnapshot:
        if self.manifest.content_hash != self.content_hash:
            raise ValueError("resource snapshot artifact and manifest hashes differ")
        if len(canonical_json_bytes(self.manifest.content)) != self.size_bytes:
            raise ValueError("resource snapshot size does not match canonical manifest")
        payload = self.manifest.content
        files = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or set(payload) != {"files"}:
            raise ValueError("resource snapshot manifest is invalid")
        if not isinstance(files, list) or not files:
            raise ValueError("resource snapshot needs at least one file")
        paths: list[str] = []
        for item in files:
            if not isinstance(item, dict) or set(item) != {"path", "content_hash", "size_bytes"}:
                raise ValueError("resource snapshot file entries are invalid")
            raw_path = item["path"]
            if not isinstance(raw_path, str):
                raise ValueError("resource snapshot path is invalid")
            path = PurePosixPath(raw_path)
            if (
                path.is_absolute()
                or not path.parts
                or path.as_posix() != raw_path
                or "\\" in raw_path
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise ValueError("resource snapshot path is outside the approved relative namespace")
            paths.append(raw_path)
            content_hash = item["content_hash"]
            if (
                not isinstance(content_hash, str)
                or len(content_hash) != 64
                or any(character not in "0123456789abcdef" for character in content_hash)
            ):
                raise ValueError("resource snapshot file hash is invalid")
            if (
                not isinstance(item["size_bytes"], int)
                or isinstance(item["size_bytes"], bool)
                or item["size_bytes"] < 0
            ):
                raise ValueError("resource snapshot file size is invalid")
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("resource snapshot paths must be unique and sorted")
        return self


class FrozenSkillActor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill_id: str = Field(min_length=1, max_length=120)
    skill_name: Literal["competitive-analysis"]
    skill_version: str = Field(min_length=1, max_length=40)
    skill_content_hash: Sha256Hex
    profile_content_hash: Sha256Hex
    binding_id: str | None = Field(default=None, max_length=120)
    enabled: bool
    binding_enabled: bool
    planner_eligible: bool
    task_types: list[str]
    archetypes: list[str]
    required_tools: list[str]
    required_resources: list[str]
    input_schema_ref: str
    output_schema_ref: str
    produces_factual_claims: bool
    report_policy: Literal["never", "on_request", "default"]
    instructions: FrozenTextDocument
    profile: FrozenTextDocument
    input_schema: FrozenDocument
    output_schema: FrozenDocument

    @model_validator(mode="after")
    def validate_control_hashes(self) -> FrozenSkillActor:
        if self.skill_content_hash != self.instructions.content_hash:
            raise ValueError("Skill registry hash does not match frozen SKILL.md")
        if self.profile_content_hash != self.profile.content_hash:
            raise ValueError("Skill profile hash does not match frozen profile YAML")
        return self


class FrozenToolActor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: Literal["tool_web_research"]
    tool_name: Literal["web_research"]
    implementation_id: str = Field(min_length=1, max_length=240)
    implementation_version: str = Field(min_length=1, max_length=80)
    execution_mode: Literal["real", "fake"]
    enabled: bool
    granted: bool
    grant_id: str = Field(min_length=1, max_length=120)
    granted_to_agent_id: str = Field(min_length=1, max_length=120)
    health_state: Literal["healthy", "unavailable", "unknown", "stale"]
    health_checked_at: datetime
    health_ttl_seconds: int = Field(default=60, ge=1, le=300)
    side_effect: Literal["read", "idempotent_write", "non_idempotent_write"]
    idempotency_support: Literal["provider", "reconcile_only", "none"]
    approval_required: bool
    evidence_class: Literal["provider_summary", "page_observation", "document", "internal"]
    timeout_seconds: int = Field(ge=1, le=300)
    input_schema: FrozenDocument
    output_schema: FrozenDocument
    published_output_schema: FrozenDocument

    @field_validator("health_checked_at")
    @classmethod
    def require_aware_health_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Tool health timestamp must be timezone-aware")
        return value


class FrozenModelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_model_id: str = Field(min_length=1, max_length=120)
    structured_output_mode: Literal["json_schema", "json_object"]
    adapter_compatibility_id: str = Field(min_length=1, max_length=240)

    @field_validator("requested_model_id", "adapter_compatibility_id")
    @classmethod
    def require_canonical_non_blank_identity(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("model policy identities must be non-blank and canonical")
        return value


class CompetitiveCapabilitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolved_for_agent_id: str = Field(min_length=1, max_length=120)
    resolved_at: datetime
    model_policy: FrozenModelPolicy
    skill: FrozenSkillActor
    tool: FrozenToolActor
    resource_snapshot: FrozenResourceSnapshot
    deliverable_contract: FrozenDocument
    evidence_policy: FrozenDocument
    review_rubric: FrozenDocument

    @field_validator("resolved_at")
    @classmethod
    def require_aware_resolution_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("capability resolution timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_principal(self) -> CompetitiveCapabilitySnapshot:
        if self.tool.granted_to_agent_id != self.resolved_for_agent_id:
            raise ValueError("Tool grant principal differs from capability principal")
        return self


def tool_actor_output_schema(skill_input_schema: dict[str, Any]) -> dict[str, Any]:
    evidence_inputs = skill_input_schema.get("properties", {}).get("evidence_inputs")
    if not isinstance(evidence_inputs, dict):
        raise ValueError("Skill input schema does not define evidence_inputs")
    return {
        "type": "object",
        "required": ["evidence_inputs", "evidence_manifest_ref"],
        "properties": {
            "evidence_inputs": copy.deepcopy(evidence_inputs),
            "evidence_manifest_ref": {
                "type": "object",
                "required": ["artifact_id", "content_hash"],
                "properties": {
                    "artifact_id": {"type": "string", "minLength": 1, "maxLength": 120},
                    "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


class PlanActorType(StrEnum):
    TOOL = "tool"
    SKILL = "skill"


class PlanInputBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_step: int = Field(ge=1)
    source_pointer: str = Field(pattern="^/", max_length=240)
    target_pointer: str = Field(pattern="^/", max_length=240)


class PlanStepContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_number: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    actor_type: PlanActorType
    actor_id: str = Field(min_length=1, max_length=120)
    question_ids: list[str] = Field(min_length=1, max_length=20)
    depends_on: list[int] = Field(default_factory=list, max_length=8)
    initial_input: dict[str, Any]
    input_bindings: list[PlanInputBinding] = Field(default_factory=list, max_length=20)
    expected_outputs: list[str] = Field(min_length=1, max_length=20)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)
    required: bool = True
    approval_required: bool = False
    timeout_seconds: int = Field(ge=1, le=300)
    max_sends: int = Field(default=1, ge=1, le=3)
    invocation_semantics: Literal["read_replayable", "skill_once"]
    actor_snapshot_hash: Sha256Hex
    input_schema_hash: Sha256Hex
    output_schema_hash: Sha256Hex
    contract_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_contract_hash(self) -> PlanStepContract:
        payload = self.model_dump(mode="json", exclude={"contract_hash"})
        if canonical_sha256(payload) != self.contract_hash:
            raise ValueError("step contract hash does not match content")
        return self


class ExecutionPlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["execution-plan-v2"] = "execution-plan-v2"
    task_type: Literal["competitive_research"] = "competitive_research"
    requirement_version_id: str
    requirement_content_hash: Sha256Hex
    recommended: Literal[True] = True
    execution_budget_seconds: int = Field(default=300, ge=1, le=300)
    max_tool_calls: int = Field(default=4, ge=1, le=4)
    problem_contract: ProblemContract
    steps: list[PlanStepContract] = Field(min_length=2, max_length=2)
    control_snapshot: CompetitiveCapabilitySnapshot

    @model_validator(mode="after")
    def validate_fixed_slice(self) -> ExecutionPlanBody:
        if [step.step_number for step in self.steps] != [1, 2]:
            raise ValueError("Slice A plan must contain steps 1 and 2")
        tool_step, skill_step = self.steps
        if tool_step.actor_type != PlanActorType.TOOL or skill_step.actor_type != PlanActorType.SKILL:
            raise ValueError("Slice A requires Tool then Skill")
        if tool_step.depends_on or skill_step.depends_on != [1]:
            raise ValueError("Slice A dependency must be Tool -> Skill")
        if any(binding.source_step != 1 for binding in skill_step.input_bindings):
            raise ValueError("Skill bindings must consume the Tool step")
        snapshot = self.control_snapshot
        if tool_step.actor_id != snapshot.tool.tool_id or skill_step.actor_id != snapshot.skill.skill_id:
            raise ValueError("plan actor IDs differ from the frozen snapshot")
        if tool_step.actor_snapshot_hash != canonical_sha256(snapshot.tool):
            raise ValueError("Tool step snapshot hash is invalid")
        if skill_step.actor_snapshot_hash != canonical_sha256(snapshot.skill):
            raise ValueError("Skill step snapshot hash is invalid")
        if (
            tool_step.input_schema_hash != snapshot.tool.input_schema.content_hash
            or tool_step.output_schema_hash != snapshot.tool.published_output_schema.content_hash
            or skill_step.input_schema_hash != snapshot.skill.input_schema.content_hash
            or skill_step.output_schema_hash != snapshot.skill.output_schema.content_hash
        ):
            raise ValueError("step schema hashes differ from the frozen actors")
        return self


def _build_step(**payload: Any) -> PlanStepContract:
    return PlanStepContract(**payload, contract_hash=canonical_sha256(payload))


def _build_research_query(task: ResearchTaskV2) -> str:
    parts = [task.research_goal.strip()]
    if task.competitor_scope and task.competitor_scope not in task.research_goal:
        parts.append(f"竞品范围：{task.competitor_scope}")
    if task.analysis_dimensions:
        parts.append(f"分析维度：{'、'.join(task.analysis_dimensions)}")
    return "\n".join(parts)[:4000]


def _build_question_queries(task: ResearchTaskV2) -> list[dict[str, object]]:
    scope = (task.competitor_scope or task.research_goal).strip()
    if not task.analysis_dimensions:
        return [
            {
                "query": f"{scope} 官方文档 产品能力 适用场景 局限 来源"[:4000],
                "question_ids": ["q_evidence_comparison", "q_scenarios"],
            }
        ]
    return [
        {
            "query": f"{scope} {dimension} 官方文档 功能 支持 限制"[:4000],
            "question_ids": ["q_evidence_comparison", "q_scenarios"],
        }
        for dimension in task.analysis_dimensions[:3]
    ]


def _schema_error(document: FrozenDocument) -> bool:
    if not isinstance(document.content, dict):
        return True
    try:
        Draft202012Validator.check_schema(document.content)
    except SchemaError:
        return True
    return False


def _decode_pointer(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must start with a slash")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _schema_at_pointer(schema: dict[str, Any], pointer: str) -> dict[str, Any] | None:
    current: Any = schema
    for token in _decode_pointer(pointer):
        if not isinstance(current, dict):
            return None
        properties = current.get("properties")
        if not isinstance(properties, dict) or token not in properties:
            return None
        current = properties[token]
    return current if isinstance(current, dict) else None


def _partial_schema(schema: dict[str, Any], bindings: list[PlanInputBinding]) -> dict[str, Any]:
    partial = copy.deepcopy(schema)
    required = partial.get("required")
    if isinstance(required, list):
        bound_roots = {_decode_pointer(binding.target_pointer)[0] for binding in bindings}
        partial["required"] = [item for item in required if item not in bound_roots]
    return partial


def _profile_snapshot_errors(skill: FrozenSkillActor) -> list[str]:
    try:
        profile = yaml.safe_load(skill.profile.content)
    except yaml.YAMLError:
        return ["skill_profile_invalid"]
    if not isinstance(profile, dict):
        return ["skill_profile_invalid"]
    expected = {
        "skill_version": skill.skill_version,
        "skill_content_hash": skill.skill_content_hash,
        "task_types": skill.task_types,
        "archetypes": skill.archetypes,
        "required_tools": skill.required_tools,
        "required_resources": skill.required_resources,
        "input_schema_ref": skill.input_schema_ref,
        "output_schema_ref": skill.output_schema_ref,
        "produces_factual_claims": skill.produces_factual_claims,
        "report_policy": skill.report_policy,
        "planner_eligible": skill.planner_eligible,
    }
    return ["skill_profile_mismatch"] if any(profile.get(key) != value for key, value in expected.items()) else []


def _plan_contract_errors(body: ExecutionPlanBody) -> list[str]:
    errors: list[str] = []
    snapshot = body.control_snapshot
    tool_step, skill_step = body.steps
    schema_documents = (
        snapshot.tool.input_schema,
        snapshot.tool.output_schema,
        snapshot.tool.published_output_schema,
        snapshot.skill.input_schema,
        snapshot.skill.output_schema,
    )
    if any(_schema_error(document) for document in schema_documents):
        return ["actor_schema_invalid"]
    try:
        Draft202012Validator(snapshot.tool.input_schema.content).validate(tool_step.initial_input)
    except JsonSchemaValidationError:
        errors.append("tool_initial_input_invalid")
    try:
        Draft202012Validator(
            _partial_schema(snapshot.skill.input_schema.content, skill_step.input_bindings)
        ).validate(skill_step.initial_input)
    except (JsonSchemaValidationError, ValueError):
        errors.append("skill_initial_input_invalid")

    known_questions = {question.id for question in body.problem_contract.questions}
    if any(not set(step.question_ids).issubset(known_questions) for step in body.steps):
        errors.append("unknown_problem_question")

    seen_targets: set[str] = set()
    ancestors = {tool_step.step_number} if tool_step.step_number in skill_step.depends_on else set()
    for binding in skill_step.input_bindings:
        if binding.source_step not in ancestors:
            errors.append("binding_source_not_ancestor")
        if binding.target_pointer in seen_targets:
            errors.append("binding_target_duplicate")
        seen_targets.add(binding.target_pointer)
        source_schema = _schema_at_pointer(snapshot.tool.published_output_schema.content, binding.source_pointer)
        target_schema = _schema_at_pointer(snapshot.skill.input_schema.content, binding.target_pointer)
        if source_schema is None:
            errors.append("binding_source_missing")
            continue
        if target_schema is None:
            errors.append("binding_target_missing")
            continue
        if canonical_sha256(source_schema) != canonical_sha256(target_schema):
            errors.append("binding_type_mismatch")
        target_root = _decode_pointer(binding.target_pointer)[0]
        if target_root in skill_step.initial_input:
            errors.append("binding_target_already_set")
    return list(dict.fromkeys(errors))


class CompetitivePlanCompiler:
    def compile(
        self,
        requirement: RequirementVersion,
        snapshot: CompetitiveCapabilitySnapshot,
        *,
        plan_version: int,
        now: datetime | None = None,
    ) -> ExecutionPlanVersion:
        effective_now = now or datetime.now(UTC)
        errors = self._eligibility_errors(requirement, snapshot, now=effective_now)
        if errors:
            raise PlanCompileError(*errors)
        task = ResearchTaskV2.model_validate(requirement.payload["requirement"])
        problem_contract = ProblemContract.model_validate(requirement.payload["problem_contract"])
        tool_step = _build_step(
            step_number=1,
            name="Research external evidence",
            actor_type=PlanActorType.TOOL,
            actor_id=snapshot.tool.tool_id,
            question_ids=["q_evidence_comparison", "q_scenarios"],
            depends_on=[],
            initial_input={
                "query": _build_research_query(task),
                "question_queries": _build_question_queries(task),
            },
            input_bindings=[],
            expected_outputs=["sealed_evidence_manifest"],
            acceptance_criteria=[
                "Provider payload matches the frozen raw Tool schema",
                "host publishes only verified EvidenceSource Artifact references",
            ],
            required=True,
            approval_required=snapshot.tool.approval_required,
            timeout_seconds=snapshot.tool.timeout_seconds,
            max_sends=2,
            invocation_semantics="read_replayable",
            actor_snapshot_hash=canonical_sha256(snapshot.tool),
            input_schema_hash=snapshot.tool.input_schema.content_hash,
            output_schema_hash=snapshot.tool.published_output_schema.content_hash,
        )
        skill_step = _build_step(
            step_number=2,
            name="Build competitive analysis",
            actor_type=PlanActorType.SKILL,
            actor_id=snapshot.skill.skill_id,
            question_ids=[question.id for question in problem_contract.questions],
            depends_on=[1],
            initial_input={
                "research_goal": task.research_goal,
                "competitor_scope": task.competitor_scope,
                "own_product_context": None,
                "analysis_dimensions": task.analysis_dimensions,
            },
            input_bindings=[
                PlanInputBinding(
                    source_step=1,
                    source_pointer="/evidence_inputs",
                    target_pointer="/evidence_inputs",
                )
            ],
            expected_outputs=["competitive_analysis_draft"],
            acceptance_criteria=[
                "output matches the frozen Skill schema",
                "factual statements cite only supplied evidence IDs",
            ],
            required=True,
            approval_required=False,
            timeout_seconds=120,
            max_sends=1,
            invocation_semantics="skill_once",
            actor_snapshot_hash=canonical_sha256(snapshot.skill),
            input_schema_hash=snapshot.skill.input_schema.content_hash,
            output_schema_hash=snapshot.skill.output_schema.content_hash,
        )
        body = ExecutionPlanBody(
            requirement_version_id=requirement.id,
            requirement_content_hash=requirement.content_hash,
            problem_contract=problem_contract,
            steps=[tool_step, skill_step],
            control_snapshot=snapshot,
        )
        contract_errors = _plan_contract_errors(body)
        if contract_errors:
            raise PlanCompileError(*contract_errors)
        payload = body.model_dump(mode="json")
        return ExecutionPlanVersion(
            run_id=requirement.run_id,
            requirement_version_id=requirement.id,
            version=plan_version,
            schema_version=body.schema_version,
            plan_hash=canonical_sha256(payload),
            payload=payload,
        )

    @staticmethod
    def _eligibility_errors(
        requirement: RequirementVersion,
        snapshot: CompetitiveCapabilitySnapshot,
        *,
        now: datetime,
    ) -> list[str]:
        errors: list[str] = []
        if now.tzinfo is None or now.utcoffset() is None:
            return ["clock_not_timezone_aware"]
        if canonical_sha256(requirement.payload) != requirement.content_hash:
            return ["requirement_hash_mismatch"]
        try:
            task = ResearchTaskV2.model_validate(requirement.payload["requirement"])
            problem_contract = ProblemContract.model_validate(requirement.payload["problem_contract"])
        except (KeyError, ValueError, TypeError):
            return ["requirement_contract_invalid"]
        criterion_ids = [criterion.id for criterion in task.success_criteria]
        if criterion_ids != problem_contract.success_criterion_ids:
            errors.append("requirement_problem_contract_mismatch")
        if any(item.blocking for item in task.ambiguities):
            errors.append("requirement_blocked")
        skill = snapshot.skill
        if not skill.enabled or not skill.binding_enabled or not skill.planner_eligible:
            errors.append("skill_not_eligible")
        if task.task_type not in skill.task_types or task.task_archetype not in skill.archetypes:
            errors.append("skill_task_mismatch")
        if snapshot.tool.tool_id not in skill.required_tools:
            errors.append("required_tool_not_frozen")
        if "wiki.corpus" not in skill.required_resources:
            errors.append("required_resource_not_frozen")
        if not skill.produces_factual_claims or skill.report_policy != "default":
            errors.append("skill_policy_mismatch")
        errors.extend(_profile_snapshot_errors(skill))
        if any(
            _schema_error(document)
            for document in (skill.input_schema, skill.output_schema, snapshot.deliverable_contract)
        ):
            errors.append("skill_control_document_invalid")

        model_policy = getattr(snapshot, "model_policy", None)
        if model_policy is None or not model_policy.requested_model_id.strip():
            errors.append("model_policy_not_frozen")
        elif not model_policy.adapter_compatibility_id.strip():
            errors.append("model_adapter_compatibility_not_frozen")

        tool = snapshot.tool
        if not tool.enabled or not tool.granted:
            errors.append("tool_not_authorized")
        if tool.execution_mode != "real":
            errors.append("tool_not_real")
        if tool.health_state != "healthy":
            errors.append("tool_unhealthy")
        checked_at = tool.health_checked_at.astimezone(UTC)
        current = now.astimezone(UTC)
        if checked_at - current > timedelta(seconds=5):
            errors.append("tool_health_from_future")
        elif current - checked_at > timedelta(seconds=tool.health_ttl_seconds):
            errors.append("tool_health_stale")
        if tool.side_effect != "read" or tool.evidence_class != "provider_summary":
            errors.append("tool_manifest_mismatch")
        if any(
            _schema_error(document)
            for document in (tool.input_schema, tool.output_schema, tool.published_output_schema)
        ):
            errors.append("tool_schema_invalid")
        return list(dict.fromkeys(errors))


def validate_execution_plan_version(plan: ExecutionPlanVersion) -> ExecutionPlanBody:
    if canonical_sha256(plan.payload) != plan.plan_hash:
        raise PlanCompileError("plan_hash_mismatch")
    try:
        body = ExecutionPlanBody.model_validate(plan.payload)
    except (TypeError, ValueError):
        raise PlanCompileError("plan_contract_invalid") from None
    errors = _plan_contract_errors(body)
    if errors:
        raise PlanCompileError(*errors)
    return body


def recompute_plan_hash(plan: ExecutionPlanVersion) -> str:
    return canonical_sha256(plan.payload)
