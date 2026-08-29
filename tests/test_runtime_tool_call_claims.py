from __future__ import annotations

import pytest

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentRun,
    AgentRunEvent,
    AgentRunStatus,
    RuntimeToolCallClaimV1,
    RuntimeToolCallOutcomeV1,
    SkillIntent,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillSideEffect,
)
from agentmesh.routes.agent_runs import _public_agent_run_event
from agentmesh.store import RuntimeToolCallConflict, SQLiteStore


def _run(run_id: str, *, status: AgentRunStatus = AgentRunStatus.RUNNING) -> AgentRun:
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id="usr_test",
        workspace_id="ws_test",
        project_id="prj_test",
        input_text="run tool",
        status=status,
    )


def _claim(run_id: str, call_id: str = "call_1") -> RuntimeToolCallClaimV1:
    identity = {
        "run_id": run_id,
        "call_id": call_id,
        "tool_definition_id": "tool_write",
        "arguments_hash": "a" * 64,
    }
    return RuntimeToolCallClaimV1(
        call_id=call_id,
        run_id=run_id,
        tool_definition_id="tool_write",
        tool_name="write_tool",
        implementation_id="provider.write",
        implementation_version="1",
        side_effect="external",
        operation_identity=canonical_json_sha256(identity),
    )


def test_public_tool_events_omit_internal_implementation_and_operation_identity() -> None:
    claim = _claim("run_public", "call_public")
    public_claim = _public_agent_run_event(
        AgentRunEvent(
            run_id=claim.run_id,
            sequence=1,
            event_type="tool_call_claimed",
            payload=claim.model_dump(mode="json"),
        )
    )
    outcome = RuntimeToolCallOutcomeV1(
        call_id=claim.call_id,
        run_id=claim.run_id,
        outcome="settled",
        result_hash="b" * 64,
    )
    public_outcome = _public_agent_run_event(
        AgentRunEvent(
            run_id=claim.run_id,
            sequence=2,
            event_type="tool_call_settled",
            payload=outcome.model_dump(mode="json"),
        )
    )

    serialized = public_claim.model_dump_json() + public_outcome.model_dump_json()
    assert "provider.write" not in serialized
    assert "operation_identity" not in serialized
    assert "tool_definition_id" not in serialized
    assert "result_hash" not in serialized
    assert public_claim.payload["tool_name"] == "write_tool"
    assert public_outcome.payload["outcome"] == "settled"


def test_runtime_tool_claim_and_settlement_are_append_only_and_idempotent(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "tool-claims.sqlite3")
    repository.save_agent_run(_run("run_claim"))
    claim = _claim("run_claim")

    assert repository.claim_runtime_tool_call(claim) is True
    assert repository.claim_runtime_tool_call(_claim("run_claim")) is False
    assert repository.list_unresolved_runtime_tool_calls() == [claim]

    outcome = RuntimeToolCallOutcomeV1(
        call_id=claim.call_id,
        run_id=claim.run_id,
        outcome="settled",
        result_hash="b" * 64,
    )
    assert repository.finish_runtime_tool_call(outcome) is True
    repeated = outcome.model_copy(update={"recorded_at": outcome.recorded_at})
    assert repository.finish_runtime_tool_call(repeated) is False
    assert repository.list_unresolved_runtime_tool_calls() == []
    claims, outcomes = repository.list_runtime_tool_call_history(claim.run_id)
    assert claims == [claim]
    assert outcomes == [outcome]


def test_runtime_tool_claim_rejects_identity_collision_and_non_running_parent(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "tool-claim-conflicts.sqlite3")
    repository.save_agent_run(_run("run_one"))
    repository.save_agent_run(_run("run_two"))
    repository.save_agent_run(_run("run_waiting", status=AgentRunStatus.WAITING_APPROVAL))
    claim = _claim("run_one", "shared_call")
    assert repository.claim_runtime_tool_call(claim) is True

    with pytest.raises(RuntimeToolCallConflict, match="tool_call_identity_conflict"):
        repository.claim_runtime_tool_call(_claim("run_two", "shared_call"))
    with pytest.raises(RuntimeToolCallConflict, match="tool_call_run_not_running"):
        repository.claim_runtime_tool_call(_claim("run_waiting", "waiting_call"))


def test_startup_reconciliation_marks_unresolved_calls_and_no_plan_parent(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "tool-claim-reconcile.sqlite3")
    read_run = repository.save_agent_run(_run("run_read"))
    write_run = repository.save_agent_run(_run("run_write"))
    read_claim = _claim(read_run.id, "read_call").model_copy(update={"side_effect": "read"})
    write_claim = _claim(write_run.id, "write_call")
    repository.claim_runtime_tool_call(read_claim)
    repository.claim_runtime_tool_call(write_claim)

    assert repository.reconcile_orphaned_agent_runs() == 2

    stored_read = repository.get_agent_run(read_run.id)
    stored_write = repository.get_agent_run(write_run.id)
    assert stored_read is not None and stored_read.error_code == "process_restarted"
    assert stored_write is not None and stored_write.error_code == "external_outcome_unknown"
    _claims, read_outcomes = repository.list_runtime_tool_call_history(read_run.id)
    _claims, write_outcomes = repository.list_runtime_tool_call_history(write_run.id)
    assert [outcome.outcome for outcome in read_outcomes] == ["abandoned"]
    assert [outcome.outcome for outcome in write_outcomes] == ["outcome_unknown"]


def test_startup_reconciliation_propagates_unknown_write_to_plan_node(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "tool-claim-plan-reconcile.sqlite3")
    run = repository.save_agent_run(_run("run_write_plan"))
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_write_unknown",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal="write externally"),
            nodes=[
                SkillPlanNode(
                    id="node_write_unknown",
                    skill_id="skill_write",
                    skill_version="1",
                    skill_content_hash="a" * 64,
                    reason="write",
                    side_effect=SkillSideEffect.EXTERNAL_WRITE,
                    status=SkillPlanNodeStatus.RUNNING,
                ),
                SkillPlanNode(
                    id="node_ready_unclaimed",
                    skill_id="skill_ready",
                    skill_version="1",
                    skill_content_hash="b" * 64,
                    reason="not claimed",
                    status=SkillPlanNodeStatus.READY,
                ),
            ],
        )
    )
    repository.save_agent_run(run.model_copy(update={"plan_id": plan.id}))
    claim = _claim(run.id, "write_unknown").model_copy(
        update={"plan_id": plan.id, "node_id": "node_write_unknown"}
    )
    repository.claim_runtime_tool_call(claim)

    assert repository.reconcile_orphaned_agent_runs() == 1

    reconciled_plan = repository.get_skill_plan(plan.id)
    reconciled_run = repository.get_agent_run(run.id)
    assert reconciled_plan is not None and reconciled_run is not None
    assert reconciled_plan.nodes[0].status is SkillPlanNodeStatus.FAILED
    assert reconciled_plan.nodes[0].error_code == "external_outcome_unknown"
    assert reconciled_plan.nodes[1].status is SkillPlanNodeStatus.CANCELLED
    assert reconciled_plan.nodes[1].error_code is None
    assert reconciled_plan.status is SkillPlanStatus.FAILED
    assert reconciled_run.status is AgentRunStatus.FAILED
    assert reconciled_run.error_code == "external_outcome_unknown"


def test_settled_non_read_claim_still_blocks_incomplete_no_plan_parent(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "tool-claim-settled-parent.sqlite3")
    run = repository.save_agent_run(_run("run_settled_write"))
    claim = _claim(run.id, "settled_write")
    repository.claim_runtime_tool_call(claim)
    repository.finish_runtime_tool_call(
        RuntimeToolCallOutcomeV1(
            call_id=claim.call_id,
            run_id=run.id,
            outcome="settled",
            result_hash="d" * 64,
        )
    )

    assert repository.runtime_tool_retry_blocked(run.id) is True
    assert repository.runtime_tool_retry_block_reason(run.id) == "completed_write_requires_new_request"
    assert repository.reconcile_orphaned_agent_runs() == 1

    stored = repository.get_agent_run(run.id)
    assert stored is not None
    assert stored.status is AgentRunStatus.FAILED
    assert stored.error_code == "external_outcome_unknown"


def test_user_cancellation_propagates_an_inflight_unknown_write(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "tool-claim-cancel.sqlite3")
    run = repository.save_agent_run(_run("run_cancel_write"))
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_cancel_write",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal="write externally"),
            nodes=[
                SkillPlanNode(
                    id="node_cancel_write",
                    skill_id="skill_write",
                    skill_version="1",
                    skill_content_hash="a" * 64,
                    reason="write",
                    side_effect=SkillSideEffect.EXTERNAL_WRITE,
                    status=SkillPlanNodeStatus.RUNNING,
                )
            ],
        )
    )
    repository.save_agent_run(run.model_copy(update={"plan_id": plan.id}))
    repository.claim_runtime_tool_call(
        _claim(run.id, "cancel_write").model_copy(
            update={"plan_id": plan.id, "node_id": "node_cancel_write"}
        )
    )

    cancelled = repository.cancel_agent_run_tree(run.id, user_id=run.user_id)

    stored_plan = repository.get_skill_plan(plan.id)
    assert cancelled is not None and cancelled.status is AgentRunStatus.FAILED
    assert cancelled.error_code == "external_outcome_unknown"
    assert stored_plan is not None and stored_plan.status is SkillPlanStatus.FAILED
    assert stored_plan.nodes[0].status is SkillPlanNodeStatus.FAILED
    assert stored_plan.nodes[0].error_code == "external_outcome_unknown"


def test_runtime_tool_outcome_requires_a_claim_and_cannot_be_rewritten(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "tool-outcome-conflicts.sqlite3")
    repository.save_agent_run(_run("run_outcome"))
    claim = _claim("run_outcome")
    repository.claim_runtime_tool_call(claim)

    unknown = RuntimeToolCallOutcomeV1(
        call_id=claim.call_id,
        run_id=claim.run_id,
        outcome="outcome_unknown",
        error_code="external_outcome_unknown",
    )
    assert repository.finish_runtime_tool_call(unknown) is True
    with pytest.raises(RuntimeToolCallConflict, match="tool_call_outcome_conflict"):
        repository.finish_runtime_tool_call(
            RuntimeToolCallOutcomeV1(
                call_id=claim.call_id,
                run_id=claim.run_id,
                outcome="settled",
                result_hash="c" * 64,
            )
        )
    with pytest.raises(RuntimeToolCallConflict, match="tool_call_claim_missing"):
        repository.finish_runtime_tool_call(
            RuntimeToolCallOutcomeV1(
                call_id="missing",
                run_id=claim.run_id,
                outcome="abandoned",
                error_code="process_restarted",
            )
        )
