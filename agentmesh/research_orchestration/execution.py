from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from typing import Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict

from agentmesh.models import AgentRun, AgentRunStatus, Artifact, new_id, now_utc
from agentmesh.research_orchestration.actors import (
    TOOL_ACTOR_OUTPUT_KIND,
    TOOL_ACTOR_OUTPUT_SCHEMA,
    ActorError,
    SkillActor,
    ToolActor,
    ToolActorOutput,
    skill_call_key,
)
from agentmesh.research_orchestration.artifacts import (
    ArtifactLineage,
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
)
from agentmesh.research_orchestration.compiler import (
    PlanActorType,
    PlanCompileError,
    PlanStepContract,
    validate_execution_plan_version,
)
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionLease,
    ExecutionPlanVersion,
    ResearchGate,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    canonical_sha256,
)
from agentmesh.research_orchestration.delivery import (
    REPORT_KIND,
    REPORT_SCHEMA,
    SKILL_RESULT_KIND,
    SKILL_RESULT_SCHEMA,
    DeliveryError,
    DeliveryOutcome,
    ReportDocument,
    ResultPipeline,
)
from agentmesh.research_orchestration.evidence import (
    EVIDENCE_MANIFEST_KIND,
    EVIDENCE_MANIFEST_SCHEMA,
    EvidenceError,
    EvidenceManifest,
    resolve_json_pointer,
)
from agentmesh.store import ResearchStoreConflict, SQLiteStore


class ExecutionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ExecutionClock(Protocol):
    def now(self) -> datetime: ...


class SystemExecutionClock:
    def now(self) -> datetime:
        return now_utc()


class ExecutionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    attempt_id: str
    terminal_status: AgentRunStatus
    delivery: DeliveryOutcome
    gap_codes: list[str]


class RecoveryOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: str
    outcome: ExecutionOutcome | None = None
    error_code: str | None = None


class _ExecutionContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    run: AgentRun
    workflow: ResearchWorkflow
    attempt: ExecutionAttempt
    plan: ExecutionPlanVersion
    tool_step: PlanStepContract
    skill_step: PlanStepContract
    tool_lineage: ArtifactLineage
    skill_lineage: ArtifactLineage


def _decode_pointer(pointer: str) -> list[str]:
    if not pointer.startswith("/") or pointer == "/" or len(pointer) > 1000:
        raise ExecutionError("binding_pointer_invalid")
    raw_tokens = pointer[1:].split("/")
    if len(raw_tokens) > 64:
        raise ExecutionError("binding_pointer_invalid")
    tokens: list[str] = []
    for raw in raw_tokens:
        decoded: list[str] = []
        index = 0
        while index < len(raw):
            if raw[index] != "~":
                decoded.append(raw[index])
                index += 1
                continue
            if index + 1 >= len(raw) or raw[index + 1] not in {"0", "1"}:
                raise ExecutionError("binding_pointer_invalid")
            decoded.append("~" if raw[index + 1] == "0" else "/")
            index += 2
        token = "".join(decoded)
        if not token:
            raise ExecutionError("binding_pointer_invalid")
        tokens.append(token)
    return tokens


def _set_json_pointer_once(document: dict[str, object], pointer: str, value: object) -> None:
    tokens = _decode_pointer(pointer)
    current: object = document
    for token in tokens[:-1]:
        if not isinstance(current, dict) or token not in current:
            raise ExecutionError("binding_target_parent_missing")
        current = current[token]
    if not isinstance(current, dict):
        raise ExecutionError("binding_target_parent_invalid")
    target = tokens[-1]
    if target in current:
        raise ExecutionError("binding_target_already_set")
    current[target] = copy.deepcopy(value)


def resolve_step_input(
    contract: PlanStepContract,
    *,
    upstream: dict[int, dict[str, object]],
    input_schema: dict[str, object],
) -> dict[str, object]:
    resolved: dict[str, object] = copy.deepcopy(contract.initial_input)
    for binding in contract.input_bindings:
        source = upstream.get(binding.source_step)
        if source is None:
            raise ExecutionError("binding_source_unavailable")
        try:
            value = resolve_json_pointer(source, binding.source_pointer)
        except (EvidenceError, RecursionError, TypeError, ValueError):
            raise ExecutionError("binding_source_invalid") from None
        _set_json_pointer_once(resolved, binding.target_pointer, value)
    try:
        Draft202012Validator(input_schema).validate(resolved)
    except JsonSchemaValidationError:
        raise ExecutionError("resolved_input_schema_invalid") from None
    return resolved


class ExecutionEngine:
    def __init__(
        self,
        repository: SQLiteStore,
        artifacts: ArtifactStore,
        tool_actor: ToolActor,
        skill_actor: SkillActor,
        pipeline: ResultPipeline,
        *,
        clock: ExecutionClock | None = None,
        worker_id: str = "research-inline-worker",
        lease_ttl: timedelta = timedelta(minutes=5),
    ):
        if not worker_id or lease_ttl <= timedelta(0):
            raise ValueError("execution worker and lease TTL are required")
        self.repository = repository
        self.artifacts = artifacts
        self.tool_actor = tool_actor
        self.skill_actor = skill_actor
        self.pipeline = pipeline
        self.clock = clock or SystemExecutionClock()
        self.worker_id = worker_id
        self.lease_ttl = lease_ttl

    def claim(self, attempt_id: str, *, token: str) -> ExecutionLease:
        now = self.clock.now()
        claimed = self.repository.claim_research_attempt(
            attempt_id,
            owner=self.worker_id,
            token=token,
            now=now,
            lease_ttl=self.lease_ttl,
        )
        if claimed is None:
            raise ExecutionError("attempt_claim_lost")
        return ExecutionLease(
            owner=self.worker_id,
            token=token,
            fencing_epoch=claimed.fencing_epoch,
        )

    async def claim_and_run(self, attempt_id: str, *, token: str | None = None) -> ExecutionOutcome:
        token = token or new_id("research_lease")
        return await self.run(attempt_id, self.claim(attempt_id, token=token))

    async def recover_expired(self) -> list[RecoveryOutcome]:
        recovered: list[RecoveryOutcome] = []
        for attempt_id in self.repository.list_expired_research_attempt_ids(self.clock.now()):
            try:
                outcome = await self.claim_and_run(attempt_id)
            except (ActorError, ArtifactStoreError, DeliveryError, ExecutionError, ResearchStoreConflict) as error:
                recovered.append(
                    RecoveryOutcome(
                        attempt_id=attempt_id,
                        error_code=str(getattr(error, "code", "execution_recovery_failed")),
                    )
                )
            else:
                recovered.append(RecoveryOutcome(attempt_id=attempt_id, outcome=outcome))
        return recovered

    async def run(self, attempt_id: str, lease: ExecutionLease) -> ExecutionOutcome:
        context = self._load_context(attempt_id, lease)
        tool_step = self._claim_step(context.attempt, context.tool_step, lease)
        if tool_step.status != StepStatus.COMPLETED:
            tool_input = resolve_step_input(
                context.tool_step,
                upstream={},
                input_schema=validate_execution_plan_version(context.plan).control_snapshot.tool.input_schema.content,
            )
            try:
                tool_result = await self.tool_actor.run(
                    plan=context.plan,
                    step=context.tool_step,
                    resolved_input=tool_input,
                    lineage=context.tool_lineage,
                    lease=lease,
                    run=context.run,
                )
            except ActorError as error:
                if error.code in {"tool_invocation_in_flight", "tool_result_unknown"}:
                    raise ExecutionError(error.code) from None
                self._fail_running_step(context, context.tool_step, lease, error.code)
                raise ExecutionError(error.code) from None
            except (ArtifactStoreError, EvidenceError, ResearchStoreConflict) as error:
                code = str(getattr(error, "code", "tool_result_invalid"))
                self._fail_running_step(context, context.tool_step, lease, code)
                raise ExecutionError(code) from None
            except Exception:
                # ToolActor persists SENT -> UNKNOWN before re-raising Provider failures.
                # Only an explicit recover command may decide whether to reconcile or retry.
                raise ExecutionError("tool_result_unknown") from None
            tool_step = self._complete_step(
                context.attempt,
                context.tool_step,
                lease,
                result_artifact_id=tool_result.output_ref.artifact_id,
            )
        _tool_ref, tool_output = self._read_tool_output(tool_step, context.tool_lineage)

        self._ready_skill_step(context.attempt, context.skill_step, lease)
        skill_step = self._claim_step(context.attempt, context.skill_step, lease)
        body = validate_execution_plan_version(context.plan)
        skill_input = resolve_step_input(
            context.skill_step,
            upstream={context.tool_step.step_number: tool_output.model_dump(mode="json")},
            input_schema=body.control_snapshot.skill.input_schema.content,
        )
        receipt_id = f"model_call_{skill_call_key(context.plan, context.skill_step, canonical_sha256(skill_input))[:32]}"
        if skill_step.status != StepStatus.COMPLETED:
            try:
                skill_result = await self.skill_actor.run(
                    plan=context.plan,
                    step=context.skill_step,
                    resolved_input=skill_input,
                    tool_output=tool_output,
                    evidence_lineage=context.tool_lineage,
                    skill_lineage=context.skill_lineage,
                    lease=lease,
                    run=context.run,
                )
            except ActorError as error:
                self._fail_running_step(context, context.skill_step, lease, error.code)
                raise ExecutionError(error.code) from None
            except (ArtifactStoreError, EvidenceError, ResearchStoreConflict) as error:
                code = str(getattr(error, "code", "skill_result_invalid"))
                self._fail_running_step(context, context.skill_step, lease, code)
                raise ExecutionError(code) from None
            except Exception:
                self._fail_running_step(context, context.skill_step, lease, "skill_model_call_failed")
                raise ExecutionError("skill_model_call_failed") from None
            receipt_id = skill_result.receipt.id
            try:
                delivery = self.pipeline.finalize(
                    plan=context.plan,
                    skill_artifact_ref=skill_result.output_ref,
                    skill_lineage=context.skill_lineage,
                    evidence_manifest_ref=tool_output.evidence_manifest_ref,
                    evidence_lineage=context.tool_lineage,
                    lease=lease,
                    model_call_receipt_id=receipt_id,
                )
            except (ArtifactStoreError, DeliveryError, ResearchStoreConflict) as error:
                code = str(getattr(error, "code", "delivery_failed"))
                self._fail_running_step(context, context.skill_step, lease, code)
                raise ExecutionError(code) from None
            skill_step = self._complete_step(
                context.attempt,
                context.skill_step,
                lease,
                result_artifact_id=skill_result.output_ref.artifact_id,
            )
        else:
            skill_ref = self._verified_ref(
                skill_step.result_artifact_id,
                lineage=context.skill_lineage,
                expected_kind=SKILL_RESULT_KIND,
                expected_schema=SKILL_RESULT_SCHEMA,
            )
            delivery = self.pipeline.finalize(
                plan=context.plan,
                skill_artifact_ref=skill_ref,
                skill_lineage=context.skill_lineage,
                evidence_manifest_ref=tool_output.evidence_manifest_ref,
                evidence_lineage=context.tool_lineage,
                lease=lease,
                model_call_receipt_id=receipt_id,
            )

        manifest = self._read_manifest(tool_output.evidence_manifest_ref, context.tool_lineage)
        gaps = [item.value for item in manifest.gap_codes]
        if delivery.status == "block":
            failed = self.repository.fail_research_execution(
                context.run.id,
                attempt_id=context.attempt.id,
                lease=lease,
                expected_state_version=context.workflow.state_version,
                error_code="deterministic_review_blocked",
                review_artifact_id=delivery.review_ref.artifact_id,
                completed_at=self.clock.now(),
            )
            if failed is None:
                raise ExecutionError("execution_finish_conflict")
            raise ExecutionError("deterministic_review_blocked")
        terminal_status = AgentRunStatus.PARTIAL if gaps else AgentRunStatus.COMPLETED
        output_text = self._output_text(delivery, context.skill_lineage)
        finished = self.repository.finish_research_execution(
            context.run.id,
            attempt_id=context.attempt.id,
            lease=lease,
            expected_state_version=context.workflow.state_version,
            claim_ledger_artifact_id=delivery.claim_ledger_ref.artifact_id,
            deliverable_artifact_id=delivery.deliverable_ref.artifact_id,
            review_artifact_id=delivery.review_ref.artifact_id,
            report_artifact_id=(delivery.report_ref.artifact_id if delivery.report_ref is not None else None),
            terminal_status=terminal_status,
            output_text=output_text,
            completed_at=self.clock.now(),
        )
        if finished is None:
            raise ExecutionError("execution_finish_conflict")
        return ExecutionOutcome(
            run_id=context.run.id,
            attempt_id=context.attempt.id,
            terminal_status=terminal_status,
            delivery=delivery,
            gap_codes=gaps,
        )

    def _load_context(self, attempt_id: str, lease: ExecutionLease) -> _ExecutionContext:
        now = self.clock.now()
        attempt = self.repository.get_research_attempt(attempt_id)
        if (
            attempt is None
            or attempt.status != AttemptStatus.RUNNING
            or attempt.lease_owner != lease.owner
            or attempt.lease_token != lease.token
            or attempt.fencing_epoch != lease.fencing_epoch
            or attempt.lease_expires_at is None
            or attempt.lease_expires_at <= now
            or attempt.deadline_at <= now
        ):
            raise ExecutionError("execution_lease_invalid")
        run = self.repository.get_agent_run(attempt.run_id)
        workflow = self.repository.get_research_workflow(attempt.run_id)
        plan = self.repository.get_research_plan_version(attempt.plan_version_id)
        if (
            run is None
            or workflow is None
            or plan is None
            or run.status != AgentRunStatus.RUNNING
            or run.orchestration_version != "research-v2"
            or run.orchestration_mode != "execute"
            or workflow.phase != ResearchPhase.EXECUTION
            or workflow.active_gate != ResearchGate.NONE
            or workflow.active_attempt_id != attempt.id
            or workflow.active_plan_version_id != plan.id
            or workflow.active_requirement_version_id != plan.requirement_version_id
            or plan.run_id != run.id
        ):
            raise ExecutionError("execution_context_invalid")
        try:
            body = validate_execution_plan_version(plan)
        except PlanCompileError:
            raise ExecutionError("execution_plan_invalid") from None
        tool_step, skill_step = body.steps
        if tool_step.actor_type != PlanActorType.TOOL or skill_step.actor_type != PlanActorType.SKILL:
            raise ExecutionError("execution_plan_invalid")
        common = {
            "run_id": run.id,
            "user_id": run.user_id,
            "workspace_id": run.workspace_id,
            "project_id": run.project_id,
            "requirement_version_id": plan.requirement_version_id,
            "plan_version_id": plan.id,
            "attempt_id": attempt.id,
        }
        return _ExecutionContext(
            run=run,
            workflow=workflow,
            attempt=attempt,
            plan=plan,
            tool_step=tool_step,
            skill_step=skill_step,
            tool_lineage=ArtifactLineage(**common, step_number=tool_step.step_number),
            skill_lineage=ArtifactLineage(**common, step_number=skill_step.step_number),
        )

    def _claim_step(
        self,
        attempt: ExecutionAttempt,
        contract: PlanStepContract,
        lease: ExecutionLease,
    ) -> ResearchStep:
        current = self.repository.get_research_step(attempt.id, contract.step_number)
        if current is None:
            raise ExecutionError("execution_step_missing")
        if current.status == StepStatus.COMPLETED:
            return current
        claimed = self.repository.claim_research_step(
            attempt.id,
            contract.step_number,
            lease=lease,
            now=self.clock.now(),
        )
        if claimed is None:
            raise ExecutionError("execution_step_claim_lost")
        return claimed

    def _ready_skill_step(
        self,
        attempt: ExecutionAttempt,
        contract: PlanStepContract,
        lease: ExecutionLease,
    ) -> None:
        current = self.repository.get_research_step(attempt.id, contract.step_number)
        if current is None:
            raise ExecutionError("execution_step_missing")
        if current.status != StepStatus.PENDING:
            return
        ready = self.repository.compare_and_swap_research_step(
            attempt.id,
            contract.step_number,
            lease=lease,
            expected_status=StepStatus.PENDING,
            next_status=StepStatus.READY,
            now=self.clock.now(),
        )
        if ready is None:
            raise ExecutionError("execution_step_ready_conflict")

    def _complete_step(
        self,
        attempt: ExecutionAttempt,
        contract: PlanStepContract,
        lease: ExecutionLease,
        *,
        result_artifact_id: str,
    ) -> ResearchStep:
        completed = self.repository.compare_and_swap_research_step(
            attempt.id,
            contract.step_number,
            lease=lease,
            expected_status=StepStatus.RUNNING,
            next_status=StepStatus.COMPLETED,
            result_artifact_id=result_artifact_id,
            now=self.clock.now(),
        )
        if completed is None:
            replay = self.repository.get_research_step(attempt.id, contract.step_number)
            if replay is not None and replay.status == StepStatus.COMPLETED and replay.result_artifact_id == result_artifact_id:
                return replay
            raise ExecutionError("execution_step_commit_lost")
        return completed

    def _fail_running_step(
        self,
        context: _ExecutionContext,
        contract: PlanStepContract,
        lease: ExecutionLease,
        error_code: str,
    ) -> None:
        safe_code = (error_code or "execution_failed")[:120]
        failed_step = self.repository.compare_and_swap_research_step(
            context.attempt.id,
            contract.step_number,
            lease=lease,
            expected_status=StepStatus.RUNNING,
            next_status=StepStatus.FAILED,
            error_code=safe_code,
            now=self.clock.now(),
        )
        if failed_step is None:
            raise ExecutionError("execution_step_fail_conflict")
        failed = self.repository.fail_research_execution(
            context.run.id,
            attempt_id=context.attempt.id,
            lease=lease,
            expected_state_version=context.workflow.state_version,
            error_code=safe_code,
            completed_at=self.clock.now(),
        )
        if failed is None:
            raise ExecutionError("execution_finish_conflict")

    def _read_tool_output(
        self,
        step: ResearchStep,
        lineage: ArtifactLineage,
    ) -> tuple[ArtifactRef, ToolActorOutput]:
        reference = self._verified_ref(
            step.result_artifact_id,
            lineage=lineage,
            expected_kind=TOOL_ACTOR_OUTPUT_KIND,
            expected_schema=TOOL_ACTOR_OUTPUT_SCHEMA,
        )
        artifact = self.artifacts.read_verified(
            reference,
            scope=lineage,
            expected_kind=TOOL_ACTOR_OUTPUT_KIND,
            expected_schema_version=TOOL_ACTOR_OUTPUT_SCHEMA,
        )
        try:
            output = ToolActorOutput.model_validate_json(artifact.content)
        except (RecursionError, TypeError, ValueError):
            raise ExecutionError("tool_actor_output_invalid") from None
        return reference, output

    def _verified_ref(
        self,
        artifact_id: str | None,
        *,
        lineage: ArtifactLineage,
        expected_kind: str,
        expected_schema: str,
    ) -> ArtifactRef:
        if not artifact_id:
            raise ExecutionError("execution_result_missing")
        artifact: Artifact | None = self.repository.get_artifact(artifact_id)
        if artifact is None or artifact.content_hash is None:
            raise ExecutionError("execution_result_missing")
        reference = ArtifactRef(artifact_id=artifact.id, content_hash=artifact.content_hash)
        try:
            self.artifacts.read_verified(
                reference,
                scope=lineage,
                expected_kind=expected_kind,
                expected_schema_version=expected_schema,
            )
        except ArtifactStoreError:
            raise ExecutionError("execution_result_invalid") from None
        return reference

    def _read_manifest(self, reference: ArtifactRef, lineage: ArtifactLineage) -> EvidenceManifest:
        try:
            artifact = self.artifacts.read_verified(
                reference,
                scope=lineage,
                expected_kind=EVIDENCE_MANIFEST_KIND,
                expected_schema_version=EVIDENCE_MANIFEST_SCHEMA,
            )
            return EvidenceManifest.model_validate_json(artifact.content)
        except (ArtifactStoreError, RecursionError, TypeError, ValueError):
            raise ExecutionError("evidence_manifest_invalid") from None

    def _output_text(self, delivery: DeliveryOutcome, lineage: ArtifactLineage) -> str | None:
        if delivery.report_ref is None:
            return None
        try:
            artifact = self.artifacts.read_verified(
                delivery.report_ref,
                scope=lineage,
                expected_kind=REPORT_KIND,
                expected_schema_version=REPORT_SCHEMA,
            )
            report = ReportDocument.model_validate_json(artifact.content)
        except (ArtifactStoreError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
            raise ExecutionError("execution_report_invalid") from None
        return report.markdown


__all__ = [
    "ExecutionEngine",
    "ExecutionError",
    "ExecutionOutcome",
    "RecoveryOutcome",
    "SystemExecutionClock",
    "resolve_step_input",
]
