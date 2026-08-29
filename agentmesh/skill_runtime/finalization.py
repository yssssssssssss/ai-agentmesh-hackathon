from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from urllib.parse import urlparse

from agentmesh.artifacts import (
    ArtifactAccessError,
    ArtifactAccessScope,
    DeepSearchArtifactSchemaRegistry,
    TrustedEvidenceEnvelopeV1,
    UniversalSynthesisEnvelopeV1,
    V1ArtifactReader,
    V1VerifiedArtifactStore,
)
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    ArtifactVerificationState,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSynthesisResult,
    now_utc,
)
from agentmesh.skill_runtime.synthesis import render_synthesis
from agentmesh.skill_runtime.universal_plan import (
    evaluate_universal_completion,
    has_valid_partial_delivery,
)
from agentmesh.store import SQLiteStore
from agentmesh.task_routing.completion import evaluate_plan_completion


@dataclass(frozen=True, slots=True)
class NodePause:
    sdk_state: dict[str, object]
    interruptions: tuple[dict[str, str], ...]
    grant_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanExecutionOutcome:
    plan: SkillPlan
    run: AgentRun
    synthesis: SkillSynthesisResult | None = None
    pause: NodePause | None = None
    paused_node_id: str | None = None
    synthesis_fallback: bool = False


SynthesisRunner = Callable[[SkillPlan, list[SkillNodeResult]], Awaitable[tuple[SkillSynthesisResult, bool]]]


class PlanFinalizationStrategy(Protocol):
    async def finalize(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
    ) -> PlanExecutionOutcome: ...


class StandardPlanFinalizer:
    """Finalize an ordinary Skill Plan without exposing DeepSearch semantics."""

    def __init__(self, repository: SQLiteStore, *, synthesis_runner: SynthesisRunner) -> None:
        self.repository = repository
        self.synthesis_runner = synthesis_runner

    def _load_active_plan(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
    ) -> tuple[SkillPlan, AgentRun]:
        plan = self.repository.get_skill_plan(plan_id)
        run = self.repository.get_agent_run(run_id)
        if (
            plan is None
            or run is None
            or plan.run_id != run.id
            or plan.version != expected_plan_version
            or plan.status is not SkillPlanStatus.RUNNING
            or run.status is not AgentRunStatus.RUNNING
        ):
            raise RuntimeError("plan_terminal_transition_conflict")
        if (
            plan.planning_mode is AgentPlanningMode.DEEPSEARCH
            or run.planning_mode is AgentPlanningMode.DEEPSEARCH
        ):
            raise RuntimeError("deepsearch_finalization_strategy_required")
        terminal_statuses = {
            SkillPlanNodeStatus.COMPLETED,
            SkillPlanNodeStatus.FAILED,
            SkillPlanNodeStatus.SKIPPED,
            SkillPlanNodeStatus.CANCELLED,
        }
        if any(node.status not in terminal_statuses for node in plan.nodes):
            raise RuntimeError("plan_nodes_not_terminal")
        return plan, run

    async def finalize(
        self,
        *,
        run_id: str,
        plan_id: str,
        expected_plan_version: int,
    ) -> PlanExecutionOutcome:
        plan, run = self._load_active_plan(
            run_id=run_id,
            plan_id=plan_id,
            expected_plan_version=expected_plan_version,
        )
        results = self.repository.list_skill_node_results(plan.id)

        artifact_reader = V1ArtifactReader(self.repository)
        evidence_cache: dict[
            str,
            tuple[Artifact, TrustedEvidenceEnvelopeV1] | None,
        ] = {}

        def evidence_record(
            artifact_id: str,
        ) -> tuple[Artifact, TrustedEvidenceEnvelopeV1] | None:
            if artifact_id in evidence_cache:
                return evidence_cache[artifact_id]
            try:
                artifact = artifact_reader.read_for_owner(
                    artifact_id,
                    reader_scope=ArtifactAccessScope(
                        user_id=run.user_id,
                        workspace_id=run.workspace_id,
                        project_id=run.project_id,
                        run_id=run.id,
                    ),
                )
                envelope = TrustedEvidenceEnvelopeV1.model_validate(
                    DeepSearchArtifactSchemaRegistry.parse(
                        artifact.artifact_type,
                        artifact.schema_version or "",
                        artifact.content,
                    )
                )
            except (ArtifactAccessError, TypeError, ValueError):
                evidence_cache[artifact_id] = None
                return None
            record = (
                (artifact, envelope)
                if artifact.artifact_type == "universal_tool_evidence"
                and artifact.schema_version == "universal-tool-evidence-v1"
                and artifact.plan_version_id == f"{plan.id}:v{plan.version}"
                else None
            )
            evidence_cache[artifact_id] = record
            return record

        def evidence_artifact_valid(artifact_id: str) -> bool:
            return evidence_record(artifact_id) is not None

        def evidence_source_identity(source_id: str) -> str | None:
            source = self.repository.get_source(source_id)
            if source is None:
                return None
            parsed = urlparse(source.reference)
            return (parsed.hostname or source.reference).casefold() or None

        def evidence_freshness_valid(artifact_id: str, freshness: str) -> bool:
            record = evidence_record(artifact_id)
            if record is None:
                return False
            _artifact, envelope = record
            if envelope.retrieved_at < now_utc() - timedelta(days=7):
                return False
            years = set(re.findall(r"\b20\d{2}\b", freshness))
            if not years:
                return freshness.casefold() in {
                    "current public sources",
                    "current",
                    "latest",
                    "recent",
                    "最新",
                    "最近",
                    "今年",
                }
            source = self.repository.get_source(envelope.source_id or "")
            searchable = (
                f"{source.title} {source.reference} {envelope.excerpt}"
                if source is not None
                else envelope.excerpt
            )
            return bool(years.intersection(re.findall(r"\b20\d{2}\b", searchable)))

        universal = plan.candidate_snapshot is not None
        provisional_completion = (
            None if universal else evaluate_plan_completion(plan, results)
        )
        if provisional_completion is not None:
            plan.completion_check = provisional_completion
        completed_nodes = {result.node_id for result in results}
        if universal:
            available_outputs = {
                output
                for result in results
                for output in (result.delivered_output_kinds or [])
            }
            has_usable_result = has_valid_partial_delivery(
                plan=plan,
                results=results,
                evidence_artifact_valid=evidence_artifact_valid,
            ) or any(
                result.node_id in completed_nodes
                and bool(result.deliverable_markdown.strip() or result.artifact_ids)
                for result in results
            )
        else:
            available_outputs = {
                output
                for node in plan.nodes
                if node.id in completed_nodes
                for output in node.output_contract
            } | {"executive_summary", "summary", "synthesis", *plan.synthesis_output_contract}
            has_usable_result = any(
                node.required and node.id in completed_nodes for node in plan.nodes
            )
        required_before_synthesis = (
            set(plan.output_contract) - set(plan.synthesis_output_contract)
            if universal
            else set(plan.output_contract)
        )
        if not has_usable_result or (
            not universal and not required_before_synthesis.issubset(available_outputs)
        ):
            causes = [
                {
                    "node_id": node.id,
                    "error_code": node.error_code,
                    "attempt": node.attempt,
                }
                for node in plan.nodes
                if node.status is SkillPlanNodeStatus.FAILED and node.error_code
            ]
            missing_outputs = sorted(required_before_synthesis - available_outputs)
            plan.status = SkillPlanStatus.FAILED
            run = self.repository.get_agent_run(run.id) or run
            run.status = AgentRunStatus.FAILED
            run.error_code = "output_contract_unsatisfied"
            transition = self.repository.finish_skill_plan_and_run(
                plan=plan,
                run=run,
                expected_plan_statuses={SkillPlanStatus.RUNNING},
                expected_run_statuses={AgentRunStatus.RUNNING},
                events=[
                    (
                        "run_failed",
                        {
                            "error_code": run.error_code,
                            "causes": causes,
                            "missing_outputs": missing_outputs,
                        },
                    )
                ],
            )
            if transition is None:
                raise RuntimeError("plan_terminal_transition_conflict")
            plan, run = transition
            return PlanExecutionOutcome(plan=plan, run=run)

        self.repository.append_agent_run_event(run.id, "synthesis_started", {"plan_id": plan.id})
        remaining = 300.0
        if run.deadline_at is not None:
            remaining = max(0.0, (run.deadline_at - now_utc()).total_seconds())
        if remaining <= 0:
            raise TimeoutError("parent_run_deadline_exceeded")
        async with asyncio.timeout(remaining):
            synthesis, fallback = await self.synthesis_runner(plan, results)
        sealed_synthesis_artifact_id: str | None = None
        if universal:
            requirement_version_id = (
                "candidate_snapshot:" + plan.candidate_snapshot.content_hash[:64]
            )
            envelope = UniversalSynthesisEnvelopeV1(
                run_id=run.id,
                requirement_version_id=requirement_version_id,
                plan_id=plan.id,
                plan_version=plan.version,
                synthesis=synthesis,
            )
            content_payload = envelope.model_dump(mode="json")
            content = canonical_json_bytes(content_payload).decode()
            content_hash = canonical_json_sha256(content_payload)
            artifact = Artifact(
                id="artifact_universal_synthesis_"
                + canonical_json_sha256(
                    {
                        "run_id": run.id,
                        "plan_id": plan.id,
                        "plan_version": plan.version,
                        "content_hash": content_hash,
                    }
                )[:24],
                run_id=run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                user_id=run.user_id,
                artifact_type="universal_synthesis",
                content_type="application/json",
                content=content,
                verification_state=ArtifactVerificationState.SEALED,
                schema_version="universal-synthesis-v1",
                content_hash=content_hash,
                size_bytes=len(content.encode()),
                requirement_version_id=requirement_version_id,
                plan_version_id=f"{plan.id}:v{plan.version}",
            )
            V1VerifiedArtifactStore(self.repository).insert_sealed(artifact)
            sealed_synthesis_artifact_id = artifact.id
            synthesis.artifact_ids = list(
                dict.fromkeys([*synthesis.artifact_ids, artifact.id])
            )
        if universal:
            synthesis_artifacts_sealed = (
                not plan.candidate_snapshot.required_synthesis_output_ids
                or sealed_synthesis_artifact_id is not None
                and sealed_synthesis_artifact_id in synthesis.artifact_ids
            )
            completion_check = evaluate_universal_completion(
                plan=plan,
                results=results,
                synthesis=synthesis,
                synthesis_artifacts_sealed=synthesis_artifacts_sealed,
                evidence_artifact_valid=evidence_artifact_valid,
                evidence_source_identity=evidence_source_identity,
                evidence_freshness_valid=evidence_freshness_valid,
            )
        else:
            completion_check = evaluate_plan_completion(plan, results, synthesis=synthesis)
        if completion_check is not None:
            plan.completion_check = completion_check
            if not completion_check.completed:
                completion_gap = "completion_check_partial:" + ",".join(completion_check.gaps)
                plan.degradation = ";".join(
                    item for item in (plan.degradation, completion_gap) if item
                )[:1000]
        plan.synthesis = synthesis.model_dump(mode="json")
        degraded = (
            fallback
            or bool(plan.degradation)
            or any(result.degradation for result in results)
            or any(
                node.status in {SkillPlanNodeStatus.FAILED, SkillPlanNodeStatus.SKIPPED}
                for node in plan.nodes
            )
        )
        if universal and completion_check is not None and not completion_check.completed:
            partial = has_valid_partial_delivery(
                plan=plan,
                results=results,
                synthesis=synthesis,
                synthesis_artifacts_sealed=synthesis_artifacts_sealed,
                evidence_artifact_valid=evidence_artifact_valid,
                evidence_source_identity=evidence_source_identity,
                evidence_freshness_valid=evidence_freshness_valid,
            )
            plan.status = SkillPlanStatus.PARTIAL if partial else SkillPlanStatus.FAILED
        else:
            plan.status = SkillPlanStatus.PARTIAL if degraded else SkillPlanStatus.COMPLETED
        run = self.repository.get_agent_run(run.id) or run
        run.status = (
            AgentRunStatus.PARTIAL
            if plan.status is SkillPlanStatus.PARTIAL
            else AgentRunStatus.FAILED
            if plan.status is SkillPlanStatus.FAILED
            else AgentRunStatus.COMPLETED
        )
        run.error_code = (
            "output_contract_unsatisfied"
            if run.status is AgentRunStatus.FAILED
            else None
        )
        published_synthesis = (
            synthesis
            if run.status in {AgentRunStatus.COMPLETED, AgentRunStatus.PARTIAL}
            else None
        )
        run.output_text = render_synthesis(published_synthesis) if published_synthesis else None
        run.paused_state = None
        event_type = (
            "run_failed"
            if run.status is AgentRunStatus.FAILED
            else "run_partial"
            if run.status is AgentRunStatus.PARTIAL
            else "run_completed"
        )
        transition = self.repository.finish_skill_plan_and_run(
            plan=plan,
            run=run,
            expected_plan_statuses={SkillPlanStatus.RUNNING},
            expected_run_statuses={AgentRunStatus.RUNNING},
            events=[
                ("synthesis_completed", {"plan_id": plan.id, "fallback": fallback}),
                (event_type, {"plan_id": plan.id, "synthesis_fallback": fallback}),
            ],
        )
        if transition is None:
            raise RuntimeError("plan_terminal_transition_conflict")
        plan, run = transition
        return PlanExecutionOutcome(
            plan=plan,
            run=run,
            synthesis=published_synthesis,
            synthesis_fallback=fallback,
        )
