from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    CandidateIdentityV1,
    CandidateSnapshotV1,
    DeepSearchBudgetV1,
    DeliverableAtomV1,
    RuntimeToolCallClaimV1,
    SkillIntent,
    SkillNodeResult,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
)
from agentmesh.store import SQLiteStore
from scripts.quiesce_skill_orchestration import QuiesceCommandError, main


def _run(run_id: str, *, contract=None) -> AgentRun:  # noqa: ANN001
    return AgentRun(
        id=run_id,
        thread_id=f"thread_{run_id}",
        user_id="usr_test",
        workspace_id="ws_test",
        project_id="prj_test",
        input_text="pending work",
        status=AgentRunStatus.PLANNING if contract else AgentRunStatus.RUNNING,
        planning_contract_version=contract,
    )


def _candidate_snapshot() -> CandidateSnapshotV1:
    atom = DeliverableAtomV1(
        id="deliverable:analysis_result",
        label="Analysis result",
        output_kind="analysis_result",
    )
    card = {
        "skill_id": "skill_partial",
        "name": "partial",
        "title": "Partial",
        "description": "Produce an analysis result.",
        "aliases": [],
        "primary_stage": "pre_design",
        "capability_type": "analysis",
        "input_kinds": ["request"],
        "output_kinds": ["analysis_result"],
        "side_effect": "read",
        "cost_level": "low",
        "risk_level": "low",
        "required_tools": [],
    }
    candidate = CandidateIdentityV1(
        skill_id="skill_partial",
        skill_name="partial",
        skill_version="1",
        skill_content_hash="a" * 64,
        profile_version="1",
        profile_content_hash="b" * 64,
        capability_card=card,
        capability_card_hash=canonical_json_sha256(card),
        covered_requirement_ids=(atom.id,),
    )
    body = {
        "schema_version": "candidate-snapshot-v1",
        "retrieval_policy_version": "universal-profile-rrf-v2",
        "required_coverage_atoms": [atom.model_dump(mode="json")],
        "plannable_coverage_atom_ids": [atom.id],
        "required_synthesis_output_ids": [],
        "coverage_witness_skill_ids": [candidate.skill_id],
        "candidates": [candidate.model_dump(mode="json")],
    }
    return CandidateSnapshotV1(**body, content_hash=canonical_json_sha256(body))


def test_quiesce_command_dry_run_and_apply_are_checksum_bound(tmp_path: Path, capsys) -> None:
    database = tmp_path / "quiesce.sqlite3"
    repository = SQLiteStore(database)
    universal = repository.save_agent_run(
        _run(
            "run_universal_quiesce",
            contract=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    deepsearch_v2 = repository.save_agent_run(
        AgentRun(
            id="run_deepsearch_v2_quiesce",
            thread_id="thread_deepsearch_v2_quiesce",
            user_id="usr_test",
            workspace_id="ws_test",
            project_id="prj_test",
            input_text="pending DeepSearch v2 planning",
            status=AgentRunStatus.PLANNING,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            planning_contract_version=AgentPlanningContractVersion.DEEPSEARCH_FROZEN_V2,
            orchestration_mode="execute",
            requested_orchestration_mode="auto",
            absolute_expires_at=universal.created_at + timedelta(days=7),
            deepsearch_budget=DeepSearchBudgetV1(),
            created_at=universal.created_at,
            updated_at=universal.created_at,
        )
    )
    direct = repository.save_agent_run(_run("run_direct_write"))
    claim_body = {
        "run_id": direct.id,
        "call_id": "call_direct_write",
        "tool_definition_id": "tool_write",
        "arguments_hash": "a" * 64,
    }
    repository.claim_runtime_tool_call(
        RuntimeToolCallClaimV1(
            call_id="call_direct_write",
            run_id=direct.id,
            tool_definition_id="tool_write",
            tool_name="write_tool",
            implementation_id="provider.write",
            implementation_version="1",
            side_effect="external",
            operation_identity=canonical_json_sha256(claim_body),
        )
    )
    inventory = repository.universal_quiesce_inventory()
    assert inventory.run_ids == (deepsearch_v2.id, direct.id, universal.id)
    assert inventory.unresolved_tool_call_ids == ("call_direct_write",)

    assert main(["--database", str(database)]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["mode"] == "dry-run"
    assert dry_run["inventory"]["operation_checksum"] == inventory.operation_checksum

    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "schema_version": "orchestration-quiesce-approval-v1",
                "operation_checksum": inventory.operation_checksum,
                "approved_by": ["@operator-one", "@operator-two"],
            }
        ),
        encoding="utf-8",
    )
    backup = tmp_path / "quiesce.backup.sqlite3"
    assert main(
        [
            "--database",
            str(database),
            "--apply",
            "--expected-operation-checksum",
            inventory.operation_checksum,
            "--backup",
            str(backup),
            "--approval-file",
            str(approval),
        ]
    ) == 0
    applied = json.loads(capsys.readouterr().out)

    assert backup.is_file()
    assert applied["backup_sha256"]
    assert repository.universal_quiesce_inventory().run_ids == ()
    stored_universal = repository.get_agent_run(universal.id)
    stored_deepsearch_v2 = repository.get_agent_run(deepsearch_v2.id)
    stored_direct = repository.get_agent_run(direct.id)
    assert stored_universal is not None and stored_universal.status is AgentRunStatus.CANCELLED
    assert stored_deepsearch_v2 is not None and stored_deepsearch_v2.status is AgentRunStatus.CANCELLED
    assert stored_direct is not None and stored_direct.status is AgentRunStatus.FAILED
    assert stored_direct.error_code == "external_outcome_unknown"


def test_quiesce_apply_rejects_checksum_drift_without_writing(tmp_path: Path) -> None:
    database = tmp_path / "quiesce-drift.sqlite3"
    repository = SQLiteStore(database)
    run = repository.save_agent_run(
        _run(
            "run_quiesce_drift",
            contract=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "schema_version": "orchestration-quiesce-approval-v1",
                "operation_checksum": "0" * 64,
                "approved_by": ["@operator-one", "@operator-two"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(QuiesceCommandError, match="quiesce_operation_checksum_required"):
        main(
            [
                "--database",
                str(database),
                "--apply",
                "--expected-operation-checksum",
                "0" * 64,
                "--backup",
                str(tmp_path / "unused.sqlite3"),
                "--approval-file",
                str(approval),
            ]
        )

    assert repository.get_agent_run(run.id).status is AgentRunStatus.PLANNING


def test_quiesce_apply_preserves_verified_partial_delivery(tmp_path: Path) -> None:
    repository = SQLiteStore(tmp_path / "quiesce-partial.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            **_run(
                "run_quiesce_partial",
                contract=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
            ).model_dump(exclude={"status"}),
            status=AgentRunStatus.RUNNING,
        )
    )
    snapshot = _candidate_snapshot()
    node = SkillPlanNode(
        id="node_quiesce_partial",
        skill_id="skill_partial",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="deliver",
        output_contract=["analysis_result"],
        status=SkillPlanNodeStatus.COMPLETED,
    )
    plan = repository.save_skill_plan(
        SkillPlan(
            id="plan_quiesce_partial",
            run_id=run.id,
            status=SkillPlanStatus.RUNNING,
            intent=SkillIntent(goal="partial", deliverables=["analysis_result"]),
            candidate_skill_ids=["skill_partial"],
            candidate_snapshot=snapshot,
            output_contract=["analysis_result"],
            nodes=[node],
        )
    )
    repository.save_agent_run(run.model_copy(update={"plan_id": plan.id}))
    repository.save_skill_node_result(
        plan.id,
        SkillNodeResult(
            id="result_quiesce_partial",
            node_id=node.id,
            skill_id=node.skill_id,
            summary="Delivered",
            deliverable_markdown="Verified analysis",
            delivered_output_kinds=["analysis_result"],
        ),
    )
    inventory = repository.universal_quiesce_inventory()

    repository.apply_universal_quiesce(
        expected_operation_checksum=inventory.operation_checksum,
    )

    stored_plan = repository.get_skill_plan(plan.id)
    stored_run = repository.get_agent_run(run.id)
    assert stored_plan is not None and stored_plan.status is SkillPlanStatus.PARTIAL
    assert stored_run is not None and stored_run.status is AgentRunStatus.PARTIAL


def test_quiesce_apply_rejects_inconsistent_universal_plan_shape(tmp_path: Path) -> None:
    database = tmp_path / "quiesce-anomaly.sqlite3"
    repository = SQLiteStore(database)
    run = repository.save_agent_run(
        _run(
            "run_quiesce_anomaly",
            contract=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    plan = SkillPlan(
        id="plan_quiesce_anomaly",
        run_id=run.id,
        status=SkillPlanStatus.PLANNING,
        intent=SkillIntent(goal="broken"),
    )
    with repository._connect() as connection:
        repository._write_skill_plan(connection, plan)
    run.plan_id = plan.id
    repository.save_agent_run(run)
    inventory = repository.universal_quiesce_inventory()
    assert inventory.anomaly_codes == (f"planning_contract_shape_mismatch:{run.id}",)
    approval = tmp_path / "anomaly-approval.json"
    approval.write_text(
        json.dumps(
            {
                "schema_version": "orchestration-quiesce-approval-v1",
                "operation_checksum": inventory.operation_checksum,
                "approved_by": ["@operator-one", "@operator-two"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(QuiesceCommandError, match="quiesce_inventory_invalid"):
        main(
            [
                "--database",
                str(database),
                "--apply",
                "--expected-operation-checksum",
                inventory.operation_checksum,
                "--backup",
                str(tmp_path / "anomaly-backup.sqlite3"),
                "--approval-file",
                str(approval),
            ]
        )
