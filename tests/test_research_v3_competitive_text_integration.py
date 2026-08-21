from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal, cast

import pytest

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_bytes
from agentmesh.research_orchestration.v3.competitive_text_integration import (
    CompetitiveTextIntegrationHarness,
)
from agentmesh.research_orchestration.v3.execution import ExecutionOutcome, RecoveryStatus
from agentmesh.research_orchestration.v3.web_projection import (
    ResearchV3WorkbenchAggregateV1,
    WorkbenchAggregateV1,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "research_v3_integration" / "competitive_text_depth.json"


def test_harness_stops_for_clarification_selects_a_plan_and_enforces_approval() -> None:
    harness = CompetitiveTextIntegrationHarness()
    prepared = asyncio.run(harness.prepare(run_id="run_integration_gate", candidate_id="depth"))

    assert prepared.blocked.requirement.payload.planning_blocked is True
    assert prepared.blocked.problem_graph is None
    assert prepared.blocked.capabilities is None
    assert prepared.blocked.candidates is None
    assert prepared.ready.requirement.version == 2
    assert prepared.ready.requirement.payload.planning_blocked is False
    assert prepared.ready.problem_graph is not None
    assert prepared.ready.problem_graph.requirement_version_id == prepared.ready.requirement.id
    assert prepared.ready.capabilities is not None
    assert not any(gap.required for gap in prepared.ready.capabilities.gaps)
    assert prepared.ready.candidates is not None
    assert tuple(candidate.candidate_id for candidate in prepared.ready.candidates.candidates) == (
        "depth",
        "speed",
    )
    assert prepared.selected_candidate_id == "depth"
    assert prepared.selected_plan.payload.candidate_id == "depth"

    with pytest.raises(ValueError, match="approval proofs"):
        asyncio.run(
            harness.execute(
                prepared,
                attempt_id="attempt_without_approval",
                approved=False,
            )
        )


@pytest.mark.parametrize(("candidate_id", "step_count"), (("depth", 4), ("speed", 3)))
def test_harness_completes_depth_and_speed_as_pass_reviewed_text_aggregates(
    candidate_id: str,
    step_count: int,
) -> None:
    completed = asyncio.run(
        CompetitiveTextIntegrationHarness().run_success(
            run_id=f"run_integration_{candidate_id}",
            candidate_id=cast(Literal["depth", "speed"], candidate_id),
        )
    )

    assert completed.executed.execution.outcome == ExecutionOutcome.SUCCEEDED
    assert len(completed.executed.execution.actor_results) == step_count
    assert len(completed.evidence_manifest.evidence) == 2
    assert completed.review.verdict == "pass"
    assert all(check.passed for check in completed.review.deterministic_checks)
    assert completed.report.presentation_mode == "text"
    assert completed.report.review_verdict == "pass"
    root = completed.workbench.root
    assert isinstance(root, ResearchV3WorkbenchAggregateV1)
    assert root.report is not None
    assert completed.prepared.repository.get_report(root.report.artifact) == completed.report

    serialized_json = canonical_json_v3_bytes(root)
    serialized = json.loads(serialized_json)
    reparsed = WorkbenchAggregateV1.model_validate_json(serialized_json)
    assert isinstance(reparsed.root, ResearchV3WorkbenchAggregateV1)
    assert reparsed.root.workflow.state == "text_report"
    assert reparsed.root.selected_plan is not None
    assert reparsed.root.selected_plan.payload.candidate_id == candidate_id
    assert reparsed.root.attempt is not None
    assert reparsed.root.attempt.status == "completed"

    if candidate_id == "depth":
        assert serialized == json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_harness_revises_after_an_optional_failure_and_runs_speed_successor() -> None:
    demonstration = asyncio.run(
        CompetitiveTextIntegrationHarness().demonstrate_optional_plan_revision(
            run_id="run_integration_revision"
        )
    )

    assert demonstration.source_plan.payload.candidate_id == "depth"
    assert demonstration.source_plan.payload.steps[1].required is False
    assert demonstration.failed_attempt.execution.outcome == ExecutionOutcome.PLAN_REVISION_REQUIRED
    assert demonstration.failed_attempt.execution.optional_gap_step_numbers == (2,)
    assert demonstration.recovery.status == RecoveryStatus.RUNNING
    assert demonstration.recovery.source_plan_version_id == demonstration.source_plan.id
    assert demonstration.recovery.source_attempt_id == demonstration.failed_attempt.attempt_id
    assert demonstration.successor_plan.payload.candidate_id == "speed"
    assert demonstration.recovery.plan_version_id == demonstration.successor_plan.id
    assert demonstration.successor_attempt.execution.outcome == ExecutionOutcome.SUCCEEDED
