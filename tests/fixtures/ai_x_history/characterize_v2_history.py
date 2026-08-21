#!/usr/bin/env python3
"""Build and characterize one sanitized research-v2 historical SQLite fixture offline.

This is a focused executable characterization, not a pytest test. It uses the
research-v2 production modules at target base dec6b55 plus the current research
testkit's deterministic compiler snapshot. No network or Provider adapter is
constructed or called.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = Path("build/agentmesh-v2-history-gate0")
OUTPUT = REPO / DEFAULT_OUTPUT
FIXTURE = OUTPUT / "research-v2-history.sqlite3"
ATTESTATION = OUTPUT / "attestation.json"
HASHES = OUTPUT / "SHA256SUMS"
TARGET_BASE = "dec6b55b3e97913c052ee2b665c063aec77a9dd3"
RUN_ID = "run_v2_history_001"
THREAD_ID = "thread_v2_history_001"
USER_ID = "user_fixture_owner"
FOREIGN_USER_ID = "user_fixture_foreign"
WORKSPACE_ID = "workspace_fixture"
PROJECT_ID = "project_fixture"
REQUIREMENT_ID = "requirement_v2_history_001"
PLAN_ID = "research_plan_v2_history_001"
ATTEMPT_ID = "attempt_v2_history_001"
BASE_TIME = datetime(2026, 8, 20, 0, 0, 0, tzinfo=UTC)
EXECUTION_TIME = BASE_TIME + timedelta(minutes=1)
TOMBSTONE_TIME = EXECUTION_TIME + timedelta(hours=50)
PURGE_TIME = BASE_TIME + timedelta(days=10)

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import agentmesh.models as models_module  # noqa: E402
import agentmesh.research_orchestration.actors as actors_module  # noqa: E402
import agentmesh.research_orchestration.artifacts as artifacts_module  # noqa: E402
from agentmesh.models import (  # noqa: E402
    AgentRun,
    AgentRunEvent,
    AgentRunStatus,
    AgentToolGrant,
    Artifact,
    ArtifactVerificationState,
    AuditEvent,
    Project,
    ToolDefinition,
    User,
    Workspace,
)
from agentmesh.research_orchestration.actors import (  # noqa: E402
    SkillActor,
    StoreToolCapabilityGuard,
    ToolActor,
)
from agentmesh.research_orchestration.api import (  # noqa: E402
    ResearchConflictError,
    ResearchNotFoundError,
    ResearchOwnerScope,
    ResearchPurgeRequest,
)
from agentmesh.research_orchestration.artifacts import (  # noqa: E402
    ArtifactDraft,
    ArtifactLease,
    ArtifactLineage,
    ArtifactStore,
)
from agentmesh.research_orchestration.compiler import (  # noqa: E402
    CompetitivePlanCompiler,
    FrozenModelPolicy,
    validate_execution_plan_version,
)
from agentmesh.research_orchestration.contracts import (  # noqa: E402
    AttemptStatus,
    ExecutionAttempt,
    ResearchPhase,
    ResearchStep,
    ResearchWorkflow,
    StepStatus,
    canonical_sha256,
)
from agentmesh.research_orchestration.delivery import ResultPipeline  # noqa: E402
from agentmesh.research_orchestration.execution import ExecutionEngine  # noqa: E402
from agentmesh.research_orchestration.ports import (  # noqa: E402
    SkillGenerationContract,
    SkillModelResult,
    ToolPortResult,
)
from agentmesh.research_orchestration.workflow import ResearchWorkflowService  # noqa: E402
from agentmesh.store import SQLiteStore  # noqa: E402
from agentmesh.tool_runtime.gateway import ToolRuntimeDescriptor  # noqa: E402
from research_orchestration_testkit import compiled_competitive_plan, competitive_snapshot  # noqa: E402

SOURCE_PATHS = [
    "agentmesh/models.py",
    "agentmesh/store.py",
    "agentmesh/research_orchestration/actors.py",
    "agentmesh/research_orchestration/artifacts.py",
    "agentmesh/research_orchestration/compiler.py",
    "agentmesh/research_orchestration/contracts.py",
    "agentmesh/research_orchestration/delivery.py",
    "agentmesh/research_orchestration/evidence.py",
    "agentmesh/research_orchestration/execution.py",
    "agentmesh/research_orchestration/result_projection.py",
    "agentmesh/research_orchestration/workflow.py",
    "tests/research_orchestration_testkit.py",
]


@dataclass(frozen=True)
class FixedClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class OfflineToolPort:
    """In-memory deterministic Tool port; it never contacts a Provider."""

    def __init__(self, clock: FixedClock):
        self.clock = clock
        self.calls = 0

    def describe(self, tool_name: str) -> ToolRuntimeDescriptor | None:
        if tool_name != "web_research":
            return None
        return ToolRuntimeDescriptor(
            implementation_id="agentmesh.tool_runtime.gateway.ToolGateway.web_research",
            implementation_version="1",
            execution_mode="real",
            health_state="healthy",
            health_checked_at=self.clock.now(),
        )

    async def invoke(
        self,
        *,
        context,
        tool_name: str,
        arguments: dict[str, Any],
        operation_key: str,
    ) -> ToolPortResult:
        del tool_name, arguments, operation_key
        self.calls += 1
        sources = [
            ("source_alpha", "Synthetic Alpha source", "https://alpha.example/research"),
            ("source_beta", "Synthetic Beta source", "https://beta.example/report"),
        ]
        return ToolPortResult(
            payload={
                "title": "Synthetic competitive research",
                "content": "Product Alpha emphasizes traceability. Product Beta emphasizes restart recovery.",
                "sources": [
                    {
                        "id": source_id,
                        "title": title,
                        "source_type": "web_page",
                        "reference": reference,
                        "workspace_id": context.workspace_id,
                        "project_id": context.project_id,
                        "user_id": context.user_id,
                        "run_id": context.run_id,
                        "skill_id": context.skill_id,
                        "created_at": self.clock.now().isoformat(),
                    }
                    for source_id, title, reference in sources
                ],
                "permission": "project_visible",
                "metadata": {"actual_provider": "offline-synthetic", "mode": "real"},
            },
            transport_request_id="offline_request_001",
            provider_operation_id="offline_operation_001",
            status_code=200,
        )

    async def reconcile(self, *, operation_key: str, provider_operation_id: str | None) -> ToolPortResult | None:
        del operation_key, provider_operation_id
        return None


class OfflineModelPort:
    """In-memory deterministic model port; it never invokes an LLM or Provider."""

    def __init__(self):
        self.calls = 0

    async def generate(
        self,
        *,
        run: AgentRun,
        frozen_skill,
        model_policy: FrozenModelPolicy,
        generation_contract: SkillGenerationContract,
        resolved_input: dict[str, Any],
        evidence: list[dict[str, Any]],
        resources: list[dict[str, str]],
        timeout_seconds: int,
    ) -> SkillModelResult:
        del run, frozen_skill, generation_contract, resolved_input, resources, timeout_seconds
        self.calls += 1
        evidence_id = str(evidence[0]["evidence_id"])
        return SkillModelResult(
            payload={
                "summary": "Synthetic products differ in traceability and recovery behavior.",
                "facts": [
                    {
                        "claim_id": "claim_fixture_fact",
                        "statement": "Product Alpha and Product Beta emphasize different operational controls.",
                        "evidence_ids": [evidence_id],
                        "parent_claim_ids": [],
                        "question_ids": ["q_evidence_comparison", "q_scenarios"],
                        "success_criterion_ids": ["sc_evidence_comparison", "sc_scenarios"],
                        "confidence": "medium",
                        "conflict_status": "unknown",
                    }
                ],
                "inferences": [
                    {
                        "claim_id": "claim_fixture_inference",
                        "statement": "Selection can depend on whether traceability or restart recovery is prioritized.",
                        "evidence_ids": [evidence_id],
                        "parent_claim_ids": ["claim_fixture_fact"],
                        "question_ids": ["q_scenarios"],
                        "success_criterion_ids": ["sc_scenarios"],
                        "confidence": "medium",
                        "conflict_status": "unknown",
                    }
                ],
                "recommendations": [
                    {
                        "claim_id": "claim_fixture_recommendation",
                        "statement": "Use a bounded synthetic pilot to compare the prioritized control.",
                        "evidence_ids": [],
                        "parent_claim_ids": ["claim_fixture_inference"],
                        "question_ids": ["q_recommendations"],
                        "success_criterion_ids": ["sc_recommendations"],
                        "confidence": "low",
                        "conflict_status": "unknown",
                    }
                ],
                "gaps": [],
            },
            requested_provider="offline-synthetic",
            requested_model=model_policy.requested_model_id,
            actual_provider="offline-synthetic",
            actual_model="offline-model-v1",
            usage={"requests": 1, "total_tokens": 1},
            provider_receipt_id="offline_model_receipt_001",
        )


class OfflineResourceLoader:
    def load(self, run: AgentRun, frozen_skill, snapshot: object) -> list[dict[str, str]]:
        del run, frozen_skill, snapshot
        return [{"path": "synthetic/method.md", "content": "Synthetic offline method."}]


class UnsupportedStoredVersion(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(REPO), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def configure_deterministic_runtime() -> None:
    counter = {"value": 0}

    class DeterministicDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            value = EXECUTION_TIME
            return value if tz is None else value.astimezone(tz)

    def deterministic_new_id(prefix: str) -> str:
        counter["value"] += 1
        return f"{prefix}_fixture_{counter['value']:04d}"

    models_module.new_id = deterministic_new_id
    artifacts_module.now_utc = lambda: EXECUTION_TIME
    artifacts_module.datetime = DeterministicDateTime
    actors_module.monotonic = lambda: 1000.0


def fixed_requirement_and_plan():
    generated_requirement, _generated_plan = compiled_competitive_plan(RUN_ID, now=BASE_TIME)
    requirement = generated_requirement.model_copy(
        update={"id": REQUIREMENT_ID, "run_id": RUN_ID, "created_at": BASE_TIME}
    )
    plan = CompetitivePlanCompiler().compile(
        requirement,
        competitive_snapshot(BASE_TIME),
        plan_version=1,
        now=BASE_TIME,
    ).model_copy(update={"id": PLAN_ID, "created_at": BASE_TIME})
    return requirement, plan


def normalize_events(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT sequence, payload FROM agent_run_events WHERE run_id = ? ORDER BY sequence",
            (RUN_ID,),
        ).fetchall()
        for row in rows:
            sequence = int(row["sequence"])
            event = AgentRunEvent.model_validate_json(row["payload"]).model_copy(
                update={
                    "id": f"run_event_fixture_{sequence:03d}",
                    "created_at": BASE_TIME + timedelta(seconds=sequence),
                }
            )
            connection.execute(
                "UPDATE agent_run_events SET id = ?, payload = ?, created_at = ? WHERE run_id = ? AND sequence = ?",
                (event.id, event.model_dump_json(), event.created_at.isoformat(), RUN_ID, sequence),
            )
        audit_rows = connection.execute(
            "SELECT id, payload FROM records WHERE collection = 'audit_events' ORDER BY id"
        ).fetchall()
        audits = sorted(
            (AuditEvent.model_validate_json(row["payload"]) for row in audit_rows),
            key=lambda item: (item.created_at, item.action, item.target_id),
        )
        connection.execute("DELETE FROM records WHERE collection = 'audit_events'")
        for index, audit in enumerate(audits, start=1):
            normalized = audit.model_copy(update={"id": f"audit_fixture_{index:03d}"})
            connection.execute(
                "INSERT INTO records(collection, id, payload) VALUES ('audit_events', ?, ?)",
                (normalized.id, normalized.model_dump_json()),
            )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("VACUUM")


def canonicalize_database(database: Path) -> None:
    """Return SQLite to a byte-stable, checkpointed DELETE-journal file."""

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("VACUUM")


def build_fixture(database: Path) -> dict[str, Any]:
    if database.exists():
        database.unlink()
    configure_deterministic_runtime()
    requirement, plan = fixed_requirement_and_plan()
    repository = SQLiteStore(database)
    repository.save_workspace(
        Workspace(
            id=WORKSPACE_ID,
            name="Synthetic Workspace",
            description="Sanitized historical compatibility fixture",
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )
    )
    repository.save_project(
        Project(
            id=PROJECT_ID,
            workspace_id=WORKSPACE_ID,
            name="Synthetic Project",
            goal="Offline compatibility characterization",
            member_ids=[USER_ID],
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )
    )
    repository.save_user(
        User(
            id=USER_ID,
            workspace_id=WORKSPACE_ID,
            default_project_id=PROJECT_ID,
            name="Fixture Owner",
            role="user",
            personal_agent_id="agent_fixture_owner",
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )
    )
    run = AgentRun(
        id=RUN_ID,
        thread_id=THREAD_ID,
        user_id=USER_ID,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        input_text="Compare Product Alpha and Product Beta using synthetic public evidence.",
        status=AgentRunStatus.RUNNING,
        skill_id="skill_competitive",
        skill_name="competitive-analysis",
        orchestration_version="research-v2",
        orchestration_mode="execute",
        requested_orchestration_mode="auto",
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )
    repository.save_agent_run(run)
    repository.add_research_requirement_version(requirement)
    repository.add_research_plan_version(plan)
    attempt = repository.add_research_attempt(
        ExecutionAttempt(
            id=ATTEMPT_ID,
            run_id=RUN_ID,
            plan_version_id=PLAN_ID,
            attempt_number=1,
            status=AttemptStatus.RUNNING,
            lease_owner="worker_fixture",
            lease_token="lease_fixture",
            fencing_epoch=1,
            lease_expires_at=BASE_TIME + timedelta(minutes=20),
            deadline_at=BASE_TIME + timedelta(minutes=30),
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )
    )
    for step_number in (1, 2):
        repository.add_research_step(
            ResearchStep(
                attempt_id=ATTEMPT_ID,
                step_number=step_number,
                status=StepStatus.RUNNING,
                claim_epoch=1,
                started_at=BASE_TIME,
                updated_at=BASE_TIME,
            )
        )
    repository.create_research_workflow(
        ResearchWorkflow(
            run_id=RUN_ID,
            phase=ResearchPhase.EXECUTION,
            active_requirement_version_id=REQUIREMENT_ID,
            active_plan_version_id=PLAN_ID,
            active_attempt_id=ATTEMPT_ID,
            state_version=1,
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )
    )
    frozen_tool = validate_execution_plan_version(plan).control_snapshot.tool
    repository.save_tool_definition(
        ToolDefinition(
            id=frozen_tool.tool_id,
            name=frozen_tool.tool_name,
            description="Synthetic offline research tool",
            category="research",
            provider="offline-synthetic",
            enabled=True,
            implementation_id=frozen_tool.implementation_id,
            implementation_version=frozen_tool.implementation_version,
            input_schema=frozen_tool.input_schema.content,
            output_schema=frozen_tool.output_schema.content,
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )
    )
    repository.save_agent_tool_grant(
        AgentToolGrant(
            id=frozen_tool.grant_id,
            agent_id=frozen_tool.granted_to_agent_id,
            tool_id=frozen_tool.tool_id,
            enabled=True,
            granted_by=USER_ID,
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )
    )

    artifacts = ArtifactStore(repository)
    lineage = {
        "run_id": RUN_ID,
        "user_id": USER_ID,
        "workspace_id": WORKSPACE_ID,
        "project_id": PROJECT_ID,
        "requirement_version_id": REQUIREMENT_ID,
        "plan_version_id": PLAN_ID,
        "attempt_id": ATTEMPT_ID,
    }
    tool_lineage = ArtifactLineage(**lineage, step_number=1)
    lease = ArtifactLease(owner="worker_fixture", token="lease_fixture", fencing_epoch=1)
    artifacts.stage(
        tool_lineage,
        kind="transient_fixture",
        schema_version="transient-fixture-v1",
        lease=lease,
        artifact_id="artifact_fixture_tombstone",
        content_type="text/plain",
    )
    # Artifact's Pydantic default factory is intentionally real-time; normalize
    # the staged-only row before exercising the production cleanup transition.
    with repository._connect() as connection:
        row = connection.execute(
            "SELECT payload FROM artifacts WHERE id = 'artifact_fixture_tombstone'"
        ).fetchone()
        staged = Artifact.model_validate_json(row["payload"]).model_copy(update={"created_at": EXECUTION_TIME})
        connection.execute(
            "UPDATE artifacts SET payload = ?, created_at = ? WHERE id = ?",
            (staged.model_dump_json(), staged.created_at.isoformat(), staged.id),
        )

    clock = FixedClock(EXECUTION_TIME)
    tool_port = OfflineToolPort(clock)
    model_port = OfflineModelPort()
    engine = ExecutionEngine(
        repository,
        artifacts,
        ToolActor(
            repository,
            artifacts,
            tool_port,
            StoreToolCapabilityGuard(repository, tool_port),
            clock=clock,
        ),
        SkillActor(
            repository,
            artifacts,
            model_port,
            OfflineResourceLoader(),
            clock=clock,
        ),
        ResultPipeline(artifacts),
        clock=clock,
        worker_id="worker_fixture",
    )
    outcome = asyncio.run(engine.run(ATTEMPT_ID, lease))
    first_cleanup = artifacts.cleanup_expired_transients(now=EXECUTION_TIME + timedelta(hours=25))
    second_cleanup = artifacts.cleanup_expired_transients(now=TOMBSTONE_TIME)
    if first_cleanup != 1 or second_cleanup != 1:
        raise AssertionError(f"unexpected transient cleanup transitions: {first_cleanup}, {second_cleanup}")
    if outcome.terminal_status != AgentRunStatus.COMPLETED or tool_port.calls != 1 or model_port.calls != 1:
        raise AssertionError("offline execution did not produce one completed deterministic run")
    normalize_events(database)
    return {
        "offline_tool_stub_calls": tool_port.calls,
        "offline_model_stub_calls": model_port.calls,
        "external_provider_calls": 0,
        "terminal_status": outcome.terminal_status.value,
        "report_ref": outcome.delivery.report_ref.artifact_id if outcome.delivery.report_ref else None,
    }


def service_for(repository: SQLiteStore, *, now: datetime = PURGE_TIME) -> ResearchWorkflowService:
    return ResearchWorkflowService(
        repository,
        planning=None,  # type: ignore[arg-type]
        execution=None,  # type: ignore[arg-type]
        purger=ArtifactStore(repository),
        clock=FixedClock(now),
        execution_allowed=lambda: False,
    )


def exact_stored_version_read(
    repository: SQLiteStore,
    run_id: str,
    owner: ResearchOwnerScope,
):
    """Exact harness dispatch: stored value first, then the current v2 reader.

    The target base has one current v2 reader rather than a multi-version registry.
    This wrapper deliberately has no shape fallback or current/latest alias.
    """

    with repository._connect() as connection:
        row = connection.execute(
            "SELECT orchestration_version FROM agent_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        raise ResearchNotFoundError(run_id)
    stored_version = str(row["orchestration_version"])
    if stored_version != "research-v2":
        raise UnsupportedStoredVersion(stored_version)
    return service_for(repository).get_projection(run_id, owner=owner), stored_version


def recursive_forbidden_action_keys(value: object, path: str = "$") -> list[str]:
    forbidden = {
        "actions",
        "available_actions",
        "commands",
        "mutation_actions",
        "mutations",
        "can_confirm",
        "can_execute",
        "can_recover",
        "can_retry",
        "can_revise",
    }
    matches: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in forbidden:
                matches.append(child)
            matches.extend(recursive_forbidden_action_keys(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            matches.extend(recursive_forbidden_action_keys(item, f"{path}[{index}]"))
    return matches


def table_count(connection: sqlite3.Connection, table: str, where: str = "", values: tuple = ()) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table} {where}", values).fetchone()[0])


def fixture_inventory(database: Path) -> dict[str, Any]:
    repository = SQLiteStore(database)
    run = repository.get_agent_run(RUN_ID)
    workflow = repository.get_research_workflow(RUN_ID)
    requirement = repository.get_research_requirement_version(REQUIREMENT_ID)
    plan = repository.get_research_plan_version(PLAN_ID)
    attempt = repository.get_research_attempt(ATTEMPT_ID)
    invocation_rows: list[sqlite3.Row]
    with repository._connect() as connection:
        artifact_rows = connection.execute(
            "SELECT id, artifact_type, verification_state, schema_version, content_hash, size_bytes, "
            "purged_at, purged_by FROM artifacts WHERE run_id = ? ORDER BY id",
            (RUN_ID,),
        ).fetchall()
        invocation_rows = connection.execute(
            "SELECT id, state, artifact_id FROM research_tool_invocations WHERE run_id = ? ORDER BY id",
            (RUN_ID,),
        ).fetchall()
        event_rows = connection.execute(
            "SELECT sequence, payload FROM agent_run_events WHERE run_id = ? ORDER BY sequence",
            (RUN_ID,),
        ).fetchall()
        receipt_count = table_count(
            connection,
            "research_model_call_receipts",
            "WHERE run_id = ?",
            (RUN_ID,),
        )
    return {
        "run": {
            "id": run.id if run else None,
            "status": run.status.value if run else None,
            "orchestration_version": run.orchestration_version if run else None,
            "owner_scope": {
                "user_id": run.user_id if run else None,
                "workspace_id": run.workspace_id if run else None,
                "project_id": run.project_id if run else None,
            },
        },
        "workflow": {
            "phase": workflow.phase.value if workflow else None,
            "state_version": workflow.state_version if workflow else None,
        },
        "requirement": {
            "id": requirement.id if requirement else None,
            "schema_version": requirement.schema_version if requirement else None,
        },
        "plan": {
            "id": plan.id if plan else None,
            "schema_version": plan.schema_version if plan else None,
        },
        "attempt": {
            "id": attempt.id if attempt else None,
            "status": attempt.status.value if attempt else None,
        },
        "invocations": [dict(row) for row in invocation_rows],
        "model_call_receipt_count": receipt_count,
        "artifacts": [dict(row) for row in artifact_rows],
        "artifact_types": sorted({str(row["artifact_type"]) for row in artifact_rows}),
        "events": [
            {
                "sequence": int(row["sequence"]),
                "event_type": AgentRunEvent.model_validate_json(row["payload"]).event_type,
            }
            for row in event_rows
        ],
    }


def sanitization_scan(database: Path) -> dict[str, Any]:
    sensitive_keys = {
        "api_key",
        "apikey",
        "access_token",
        "authorization",
        "bearer_token",
        "client_secret",
        "cookie",
        "credentials",
        "password",
        "refresh_token",
        "secret",
        "set_cookie",
        "token",
    }
    forbidden_patterns = (
        re.compile(r"(?i)(?<![a-z0-9])sk-[a-z0-9]{8,}(?![a-z0-9])"),
        re.compile(r"(?i)\bbearer[ \t]+[a-z0-9._~+/=-]{8,}(?![a-z0-9._~+/=-])"),
        re.compile(r"(?i)-----begin (?:rsa |ec |openssh )?private key-----"),
    )
    key_hits: list[str] = []
    value_hits: list[str] = []

    def visit(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).lower().replace("-", "_").replace(" ", "_")
                if normalized in sensitive_keys and item not in (None, "", [], {}):
                    key_hits.append(f"{path}.{key}")
                visit(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
        elif isinstance(value, str):
            if any(pattern.search(value) for pattern in forbidden_patterns):
                value_hits.append(path)

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        for table in (
            "agent_runs",
            "research_workflows",
            "research_requirement_versions",
            "research_plan_versions",
            "research_attempts",
            "research_steps",
            "research_tool_invocations",
            "research_model_call_receipts",
            "artifacts",
            "agent_run_events",
        ):
            for index, row in enumerate(connection.execute(f"SELECT payload FROM {table}")):
                try:
                    visit(json.loads(row["payload"]), f"{table}[{index}]")
                except (json.JSONDecodeError, TypeError):
                    value_hits.append(f"{table}[{index}]:invalid-json")
        for index, row in enumerate(connection.execute("SELECT collection, payload FROM records")):
            try:
                visit(json.loads(row["payload"]), f"records:{row['collection']}[{index}]")
            except (json.JSONDecodeError, TypeError):
                value_hits.append(f"records[{index}]:invalid-json")
    return {
        "passed": not key_hits and not value_hits,
        "nonempty_sensitive_key_hits": key_hits,
        "credential_pattern_hits": value_hits,
        "identities": "synthetic fixture IDs only",
    }


def characterize(database: Path) -> dict[str, Any]:
    owner = ResearchOwnerScope(user_id=USER_ID, workspace_id=WORKSPACE_ID, project_id=PROJECT_ID)
    foreign = ResearchOwnerScope(
        user_id=FOREIGN_USER_ID,
        workspace_id="workspace_fixture_foreign",
        project_id="project_fixture_foreign",
    )
    work = OUTPUT / ".characterization"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()

    read_db = work / "read.sqlite3"
    shutil.copyfile(database, read_db)
    repository = SQLiteStore(read_db)
    events_before = [event.model_dump(mode="json") for event in repository.list_agent_run_events(RUN_ID)]
    first_service = service_for(repository)
    tasks_before = first_service.background_task_count
    projection, stored_version = exact_stored_version_read(repository, RUN_ID, owner)
    tasks_after = first_service.background_task_count
    events_after = [event.model_dump(mode="json") for event in repository.list_agent_run_events(RUN_ID)]
    projection_json = projection.model_dump(mode="json")
    projection_hash = canonical_sha256(projection_json)
    required_artifact_ids = {
        "evidence_manifest": projection.artifacts.evidence_manifest_id,
        "claim_ledger": projection.artifacts.claim_ledger_id,
        "deliverable": projection.artifacts.deliverable_id,
        "review": projection.artifacts.review_id,
        "report": projection.artifacts.report_id,
    }
    owner_ok = bool(
        stored_version == "research-v2"
        and projection.orchestration_version == "research-v2"
        and projection.workflow.phase == ResearchPhase.TERMINAL
        and projection.attempt is not None
        and projection.attempt.status == AttemptStatus.COMPLETED.value
        and all(required_artifact_ids.values())
        and projection.result.evidence
        and projection.result.claims
        and projection.result.deliverable is not None
        and projection.result.review is not None
        and projection.result.report is not None
        and not projection.integrity_errors
    )

    foreign_hidden = False
    foreign_exception = ""
    try:
        exact_stored_version_read(repository, RUN_ID, foreign)
    except ResearchNotFoundError as error:
        foreign_hidden = True
        foreign_exception = type(error).__name__

    restarted_repository = SQLiteStore(read_db)
    restarted_projection, restarted_version = exact_stored_version_read(restarted_repository, RUN_ID, owner)
    restarted_hash = canonical_sha256(restarted_projection.model_dump(mode="json"))
    restart_ok = restarted_version == "research-v2" and restarted_hash == projection_hash

    action_keys = recursive_forbidden_action_keys(projection_json)
    pure_read_ok = not action_keys and tasks_before == tasks_after == 0 and events_before == events_after

    corrupt_db = work / "corrupt.sqlite3"
    shutil.copyfile(database, corrupt_db)
    with sqlite3.connect(corrupt_db) as connection:
        payload = json.loads(
            connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (RUN_ID,)).fetchone()[0]
        )
        payload["orchestration_version"] = "research-v3"
        connection.execute(
            "UPDATE agent_runs SET payload = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False, separators=(",", ":")), RUN_ID),
        )
    corruption_rejected = False
    corruption_exception = ""
    corruption_detail = ""
    try:
        exact_stored_version_read(SQLiteStore(corrupt_db), RUN_ID, owner)
    except ResearchConflictError as error:
        corruption_rejected = True
        corruption_exception = type(error).__name__
        corruption_detail = str(error)

    purge_db = work / "purge.sqlite3"
    shutil.copyfile(database, purge_db)
    purge_repository = SQLiteStore(purge_db)
    with purge_repository._connect() as connection:
        before_artifacts = {
            row["id"]: dict(row)
            for row in connection.execute(
                "SELECT id, verification_state, content_hash, size_bytes, purged_at, purged_by "
                "FROM artifacts WHERE run_id = ? ORDER BY id",
                (RUN_ID,),
            ).fetchall()
        }
    preexisting_tombstones = {
        artifact_id for artifact_id, row in before_artifacts.items() if row["verification_state"] == "purged"
    }
    expected_new_tombstones = len(before_artifacts) - len(preexisting_tombstones)
    purge_response = asyncio.run(
        service_for(purge_repository).purge(
            RUN_ID,
            ResearchPurgeRequest(expected_state_version=2),
            owner=owner,
            idempotency_key="purge-fixture-history-001",
        )
    )
    with purge_repository._connect() as connection:
        after_artifact_rows = connection.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY id",
            (RUN_ID,),
        ).fetchall()
        after_artifacts = [Artifact.model_validate_json(row["payload"]) for row in after_artifact_rows]
        run_after = AgentRun.model_validate_json(
            connection.execute("SELECT payload FROM agent_runs WHERE id = ?", (RUN_ID,)).fetchone()[0]
        )
        research_counts = {
            "workflows": table_count(connection, "research_workflows", "WHERE run_id = ?", (RUN_ID,)),
            "requirements": table_count(
                connection, "research_requirement_versions", "WHERE run_id = ?", (RUN_ID,)
            ),
            "plans": table_count(connection, "research_plan_versions", "WHERE run_id = ?", (RUN_ID,)),
            "attempts": table_count(connection, "research_attempts", "WHERE run_id = ?", (RUN_ID,)),
            "invocations": table_count(
                connection, "research_tool_invocations", "WHERE run_id = ?", (RUN_ID,)
            ),
            "model_receipts": table_count(
                connection, "research_model_call_receipts", "WHERE run_id = ?", (RUN_ID,)
            ),
            "steps": table_count(connection, "research_steps"),
            "purge_commands": table_count(
                connection,
                "research_commands",
                "WHERE run_id = ? AND command_type = 'purge'",
                (RUN_ID,),
            ),
        }
        audit_events = [
            AuditEvent.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT payload FROM records WHERE collection = 'audit_events' ORDER BY id"
            ).fetchall()
        ]
        purge_events = [
            AgentRunEvent.model_validate_json(row[0]).event_type
            for row in connection.execute(
                "SELECT payload FROM agent_run_events WHERE run_id = ? ORDER BY sequence",
                (RUN_ID,),
            ).fetchall()
        ]
    tombstones_valid = all(
        artifact.verification_state == ArtifactVerificationState.PURGED
        and artifact.content == ""
        and artifact.content_hash == before_artifacts[artifact.id]["content_hash"]
        and artifact.size_bytes == before_artifacts[artifact.id]["size_bytes"]
        and artifact.run_id == RUN_ID
        and artifact.workspace_id == WORKSPACE_ID
        and artifact.project_id == PROJECT_ID
        and artifact.user_id == USER_ID
        for artifact in after_artifacts
    )
    owner_purge_metadata_valid = all(
        artifact.id in preexisting_tombstones
        or (artifact.purged_by == USER_ID and artifact.purged_at == PURGE_TIME)
        for artifact in after_artifacts
    )
    preexisting_metadata_preserved = all(
        artifact.purged_by == before_artifacts[artifact.id]["purged_by"]
        and artifact.purged_at.isoformat() == before_artifacts[artifact.id]["purged_at"]
        for artifact in after_artifacts
        if artifact.id in preexisting_tombstones
    )
    post_purge_hidden = False
    try:
        exact_stored_version_read(purge_repository, RUN_ID, owner)
    except ResearchNotFoundError:
        post_purge_hidden = True
    purge_ok = bool(
        purge_response.purged_artifact_count == expected_new_tombstones
        and tombstones_valid
        and owner_purge_metadata_valid
        and preexisting_metadata_preserved
        and all(value == 0 for key, value in research_counts.items() if key != "purge_commands")
        and research_counts["purge_commands"] == 1
        and run_after.status == AgentRunStatus.COMPLETED
        and run_after.input_text == "Compare Product Alpha and Product Beta using synthetic public evidence."
        and run_after.output_text is None
        and any(event.action == "purge_research_data" and event.target_id == RUN_ID for event in audit_events)
        and "research_data_purged" in purge_events
        and post_purge_hidden
    )

    shutil.rmtree(work)
    return {
        "owner_read": {
            "passed": owner_ok,
            "stored_version": stored_version,
            "response_discriminator": projection.orchestration_version,
            "projection_sha256": projection_hash,
            "artifact_refs": required_artifact_ids,
            "integrity_errors": projection.integrity_errors,
        },
        "foreign_owner_hidden": {
            "passed": foreign_hidden,
            "semantics": "not-found without projection or existence disclosure",
            "exception": foreign_exception,
        },
        "integrity_corruption_rejected": {
            "passed": corruption_rejected,
            "corruption": "agent_runs payload discriminator changed while indexed stored version remained research-v2",
            "exception": corruption_exception,
            "detail": corruption_detail,
        },
        "restart_read": {
            "passed": restart_ok,
            "first_projection_sha256": projection_hash,
            "restarted_projection_sha256": restarted_hash,
        },
        "history_projection_no_mutation_actions": {
            "passed": pure_read_ok,
            "forbidden_action_keys_found": action_keys,
            "background_tasks_before": tasks_before,
            "background_tasks_after": tasks_after,
            "events_unchanged": events_before == events_after,
        },
        "purge_tombstones": {
            "passed": purge_ok,
            "expected_new_tombstones": expected_new_tombstones,
            "reported_purged_artifact_count": purge_response.purged_artifact_count,
            "preexisting_tombstone_ids": sorted(preexisting_tombstones),
            "all_artifacts_are_valid_tombstones": tombstones_valid,
            "owner_purge_metadata_valid": owner_purge_metadata_valid,
            "preexisting_metadata_preserved": preexisting_metadata_preserved,
            "research_rows_after_purge": research_counts,
            "run_input_retained": run_after.input_text,
            "run_output_cleared": run_after.output_text is None,
            "post_purge_history_hidden": post_purge_hidden,
        },
    }


def source_attestation() -> dict[str, Any]:
    resolved = str(git("rev-parse", "dec6b55"))
    if resolved != TARGET_BASE:
        raise AssertionError(f"target base mismatch: {resolved}")
    files = []
    for relative in SOURCE_PATHS:
        target_bytes = git("show", f"{TARGET_BASE}:{relative}", binary=True)
        current_bytes = (REPO / relative).read_bytes()
        files.append(
            {
                "path": relative,
                "target_sha256": hashlib.sha256(target_bytes).hexdigest(),
                "current_sha256": hashlib.sha256(current_bytes).hexdigest(),
                "matches_target_base": target_bytes == current_bytes,
            }
        )
    return {
        "target_base": TARGET_BASE,
        "target_subject": git("show", "-s", "--format=%s", TARGET_BASE),
        "worktree_head": git("rev-parse", "HEAD"),
        "all_runtime_sources_match_target_base": all(item["matches_target_base"] for item in files),
        "files": files,
    }


def configure_output(relative_output: Path) -> None:
    """Configure a repository-relative evidence output without machine-local paths."""

    global OUTPUT, FIXTURE, ATTESTATION, HASHES
    if relative_output.is_absolute() or ".." in relative_output.parts:
        raise ValueError("--output must be a repository-relative path without parent traversal")
    OUTPUT = (REPO / relative_output).resolve()
    try:
        OUTPUT.relative_to(REPO)
    except ValueError as exc:
        raise ValueError("--output must remain inside the repository") from exc
    FIXTURE = OUTPUT / "research-v2-history.sqlite3"
    ATTESTATION = OUTPUT / "attestation.json"
    HASHES = OUTPUT / "SHA256SUMS"


def main(relative_output: Path = DEFAULT_OUTPUT) -> int:
    configure_output(relative_output)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.name not in {Path(__file__).name}:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    source = source_attestation()
    build = build_fixture(FIXTURE)
    second = OUTPUT / ".determinism-check.sqlite3"
    build_fixture(second)

    # Exercise the same current-store initialization against both independent
    # builds, then restore canonical single-file bytes before comparison.
    inventory = fixture_inventory(FIXTURE)
    fixture_inventory(second)
    canonicalize_database(FIXTURE)
    canonicalize_database(second)
    fixture_hash = sha256_file(FIXTURE)
    second_hash = sha256_file(second)
    deterministic = fixture_hash == second_hash
    if not deterministic:
        raise AssertionError(f"fixture byte determinism failed: {fixture_hash} != {second_hash}")

    sanitization = sanitization_scan(FIXTURE)
    checks = characterize(FIXTURE)
    final_fixture_hash = sha256_file(FIXTURE)
    deterministic = deterministic and final_fixture_hash == fixture_hash
    fixture_hash = final_fixture_hash
    second.unlink()
    if not deterministic:
        raise AssertionError(f"fixture bytes changed during characterization: {fixture_hash}")
    overall = bool(
        source["all_runtime_sources_match_target_base"]
        and deterministic
        and sanitization["passed"]
        and all(item["passed"] for item in checks.values())
    )
    script_path = Path(__file__).resolve()
    attestation = {
        "attestation_version": "agentmesh-research-v2-history-gate0-v1",
        "overall": "passed" if overall else "failed",
        "generated_at": BASE_TIME.isoformat(),
        "source": source,
        "execution": {
            "kind": "focused offline characterization script (not a test suite)",
            "network_used": False,
            "provider_adapters_constructed": False,
            **build,
        },
        "dispatch": {
            "strategy": "exact stored orchestration_version lookup, then current ResearchWorkflowService v2 reader",
            "stored_identity": "research-v2",
            "shape_fallback": False,
            "current_or_latest_alias": False,
            "target_base_native_multi_version_reader_registry": False,
        },
        "determinism": {
            "passed": deterministic,
            "independent_build_1_sha256": fixture_hash,
            "independent_build_2_sha256": second_hash,
            "fixed_clock": BASE_TIME.isoformat(),
            "synthetic_ids": True,
        },
        "sanitization": sanitization,
        "fixture": {
            "path": (OUTPUT.relative_to(REPO) / FIXTURE.name).as_posix(),
            "bytes": FIXTURE.stat().st_size,
            "sha256": fixture_hash,
            "inventory": inventory,
        },
        "checks": checks,
        "file_hashes": {
            FIXTURE.name: fixture_hash,
            script_path.name: sha256_file(script_path),
        },
        "limitations": [
            "Target base dec6b55 has a single research-v2 reader, not a native multi-version reader registry; the harness performs exact stored-version lookup before invoking that current reader.",
            "The fixture proves offline historical read and purge semantics only; it does not exercise network Providers or authorize a future v2-to-current rewrite.",
        ],
    }
    ATTESTATION.write_text(
        json.dumps(attestation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    hash_paths = [FIXTURE, script_path, ATTESTATION]
    HASHES.write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in hash_paths),
        encoding="utf-8",
    )
    print(json.dumps({"overall": attestation["overall"], "attestation": str(ATTESTATION)}, sort_keys=True))
    return 0 if overall else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="repository-relative output directory (default: build/agentmesh-v2-history-gate0)",
    )
    arguments = parser.parse_args()
    raise SystemExit(main(arguments.output))
