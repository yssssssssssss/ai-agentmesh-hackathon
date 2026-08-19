from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from agentmesh.models import AgentRun, AgentRunStatus
from agentmesh.research_orchestration.artifacts import ArtifactLease, ArtifactLineage, ArtifactStore
from agentmesh.research_orchestration.compiler import (
    CompetitiveCapabilitySnapshot,
    CompetitivePlanCompiler,
    FrozenDocument,
    FrozenModelPolicy,
    FrozenResourceSnapshot,
    FrozenSkillActor,
    FrozenTextDocument,
    FrozenToolActor,
    tool_actor_output_schema,
)
from agentmesh.research_orchestration.contracts import (
    AttemptStatus,
    ExecutionAttempt,
    ExecutionPlanVersion,
    RequirementVersion,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    canonical_json_bytes,
    canonical_sha256,
)
from agentmesh.research_orchestration.planning import (
    CompetitiveRequirementPlanner,
    requirement_version_from_result,
)
from agentmesh.store import SQLiteStore
from agentmesh.tools import WEB_RESEARCH_OUTPUT_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "agentmesh" / "builtin_skills" / "competitive-analysis"


@dataclass(frozen=True)
class ResearchExecutionContext:
    repository: SQLiteStore
    artifacts: ArtifactStore
    requirement: RequirementVersion
    plan: ExecutionPlanVersion
    lineage_step_1: ArtifactLineage
    lineage_step_2: ArtifactLineage
    lease: ArtifactLease


def _frozen(value) -> FrozenDocument:
    return FrozenDocument(content=value, content_hash=canonical_sha256(value))


def _frozen_text(value: str) -> FrozenTextDocument:
    return FrozenTextDocument(content=value, content_hash=hashlib.sha256(value.encode()).hexdigest())


def competitive_snapshot(now: datetime | None = None) -> CompetitiveCapabilitySnapshot:
    effective_now = now or datetime.now(UTC)
    instructions = _frozen_text((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
    profile_text = (SKILL_ROOT / "agents" / "agentmesh.yaml").read_text(encoding="utf-8")
    profile_document = yaml.safe_load(profile_text)
    profile = _frozen_text(profile_text)
    input_schema = json.loads((SKILL_ROOT / "input.schema.json").read_text(encoding="utf-8"))
    output_schema = json.loads((SKILL_ROOT / "output.schema.json").read_text(encoding="utf-8"))
    published_output_schema = tool_actor_output_schema(input_schema)
    resource_manifest = {
        "files": [
            {
                "path": "methods/toolbox/analysis/competitive-analysis.md",
                "content_hash": "3" * 64,
                "size_bytes": 42,
            }
        ]
    }
    resource_document = _frozen(resource_manifest)
    deliverable_schema = json.loads(
        (ROOT / "agentmesh" / "schemas" / "deliverables" / "competitive-analysis-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    evidence_policy = yaml.safe_load(
        (ROOT / "agentmesh" / "research_orchestration" / "config" / "evidence-policy-v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    review_rubric = yaml.safe_load(
        (
            ROOT
            / "agentmesh"
            / "research_orchestration"
            / "config"
            / "review-rubrics"
            / "competitive-analysis-v1.yaml"
        ).read_text(encoding="utf-8")
    )
    return CompetitiveCapabilitySnapshot(
        resolved_for_agent_id="agent_research",
        resolved_at=effective_now,
        model_policy=FrozenModelPolicy(
            requested_model_id="gpt-primary",
            structured_output_mode="json_schema",
            adapter_compatibility_id="openai-agents-sdk.chat-completions.json-schema:v1",
        ),
        skill=FrozenSkillActor(
            skill_id="skill_competitive",
            skill_name="competitive-analysis",
            skill_version=str(profile_document["skill_version"]),
            skill_content_hash=instructions.content_hash,
            profile_content_hash=profile.content_hash,
            binding_id="binding_competitive",
            enabled=True,
            binding_enabled=True,
            planner_eligible=True,
            task_types=["competitive_research"],
            archetypes=["evidence_synthesis"],
            required_tools=["tool_web_research"],
            required_resources=["wiki.corpus"],
            input_schema_ref="input.schema.json",
            output_schema_ref="output.schema.json",
            produces_factual_claims=True,
            report_policy="default",
            instructions=instructions,
            profile=profile,
            input_schema=_frozen(input_schema),
            output_schema=_frozen(output_schema),
        ),
        tool=FrozenToolActor(
            tool_id="tool_web_research",
            tool_name="web_research",
            implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
            implementation_version="1",
            execution_mode="real",
            enabled=True,
            granted=True,
            grant_id="grant_web",
            granted_to_agent_id="agent_research",
            health_state="healthy",
            health_checked_at=effective_now,
            health_ttl_seconds=60,
            side_effect="read",
            idempotency_support="none",
            approval_required=False,
            evidence_class="provider_summary",
            timeout_seconds=45,
            input_schema=_frozen(
                {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                    "additionalProperties": False,
                }
            ),
            output_schema=_frozen(WEB_RESEARCH_OUTPUT_SCHEMA),
            published_output_schema=_frozen(published_output_schema),
        ),
        resource_snapshot=FrozenResourceSnapshot(
            artifact_id="artifact_resource_snapshot",
            content_hash=resource_document.content_hash,
            size_bytes=len(canonical_json_bytes(resource_manifest)),
            manifest=resource_document,
        ),
        deliverable_contract=_frozen(deliverable_schema),
        evidence_policy=_frozen(evidence_policy),
        review_rubric=_frozen(review_rubric),
    )


def compiled_competitive_plan(
    run_id: str,
    *,
    now: datetime | None = None,
) -> tuple[RequirementVersion, ExecutionPlanVersion]:
    effective_now = now or datetime.now(UTC)
    result = asyncio.run(
        CompetitiveRequirementPlanner().plan(
            "对比淘宝和京东面向企业产品团队的研究能力，分析证据、恢复和协作场景",
        )
    )
    requirement = requirement_version_from_result(run_id, 1, result)
    plan = CompetitivePlanCompiler().compile(
        requirement,
        competitive_snapshot(effective_now),
        plan_version=1,
        now=effective_now,
    )
    return requirement, plan


def research_execution_context(database, *, run_id: str = "run_research") -> ResearchExecutionContext:
    now = datetime.now(UTC)
    requirement, plan = compiled_competitive_plan(run_id, now=now)
    repository = SQLiteStore(database)
    repository.save_agent_run(
        AgentRun(
            id=run_id,
            thread_id=f"thread_{run_id}",
            user_id="user_1",
            workspace_id="workspace_1",
            project_id="project_1",
            input_text="compare",
            status=AgentRunStatus.PLANNING,
            orchestration_version="research-v2",
            orchestration_mode="execute",
        )
    )
    repository.add_research_requirement_version(requirement)
    repository.add_research_plan_version(plan)
    attempt = repository.add_research_attempt(
        ExecutionAttempt(
            id=f"attempt_{run_id}",
            run_id=run_id,
            plan_version_id=plan.id,
            attempt_number=1,
            status=AttemptStatus.RUNNING,
            lease_owner="worker_1",
            lease_token="lease_1",
            fencing_epoch=1,
            lease_expires_at=now + timedelta(minutes=10),
            deadline_at=now + timedelta(minutes=20),
        )
    )
    for step_number in (1, 2):
        repository.add_research_step(
            ResearchStep(
                attempt_id=attempt.id,
                step_number=step_number,
                status=StepStatus.RUNNING,
                claim_epoch=1,
                started_at=now,
            )
        )
    repository.create_research_workflow(
        ResearchWorkflow(
            run_id=run_id,
            phase=ResearchPhase.EXECUTION,
            active_requirement_version_id=requirement.id,
            active_plan_version_id=plan.id,
            active_attempt_id=attempt.id,
        )
    )
    base_lineage = dict(
        run_id=run_id,
        user_id="user_1",
        workspace_id="workspace_1",
        project_id="project_1",
        requirement_version_id=requirement.id,
        plan_version_id=plan.id,
        attempt_id=attempt.id,
    )
    return ResearchExecutionContext(
        repository=repository,
        artifacts=ArtifactStore(repository),
        requirement=requirement,
        plan=plan,
        lineage_step_1=ArtifactLineage(**base_lineage, step_number=1),
        lineage_step_2=ArtifactLineage(**base_lineage, step_number=2),
        lease=ArtifactLease(owner="worker_1", token="lease_1", fencing_epoch=1),
    )
