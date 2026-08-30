from __future__ import annotations

import hashlib
import json
import stat
from datetime import timedelta
from pathlib import Path

import pytest

import scripts.quiesce_skill_orchestration as quiesce_command
from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.models import (
    AgentPlanningContractVersion,
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    CandidateIdentityV1,
    CandidateSnapshotV1,
    ChatWorkflowTrace,
    DeepSearchBudgetV1,
    DeliverableAtomV1,
    Intent,
    RunDispatchReceiptV1,
    RunDispatchState,
    RuntimeToolCallClaimV1,
    RuntimeToolCallOutcomeV1,
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


def _approval_file(
    directory: Path,
    checksum: str,
    *,
    name: str,
    approved_by: list[str] | None = None,
) -> Path:
    path = directory / name
    path.write_text(
        json.dumps(
            {
                "schema_version": "orchestration-quiesce-approval-v1",
                "operation_checksum": checksum,
                "approved_by": approved_by or ["@operator-one", "@operator-two"],
            }
        ),
        encoding="utf-8",
    )
    return path


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
    backup = tmp_path / "backups" / "quiesce.backup.sqlite3"
    receipt = tmp_path / "evidence" / "quiesce-apply-receipt.json"
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
            "--receipt",
            str(receipt),
        ]
    ) == 0
    applied = json.loads(capsys.readouterr().out)

    assert backup.is_file()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert receipt.is_file()
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    durable_receipt = json.loads(receipt.read_text(encoding="utf-8"))
    assert durable_receipt["status"] == "verified"
    assert durable_receipt["backup"]["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert durable_receipt["operation_checksum"] == inventory.operation_checksum
    assert applied["receipt"] == str(receipt.resolve())
    assert applied["receipt_status"] == "verified"
    assert applied["backup_sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert applied["backup_bytes"] == backup.stat().st_size
    assert applied["backup_source"]["integrity_check"] == "ok"
    assert applied["backup_snapshot"]["table_counts"] == applied["backup_source"]["table_counts"]
    assert applied["restore_smoke"]["integrity_check"] == "ok"
    assert (
        applied["restore_smoke"]["inventory_operation_checksum"]
        == inventory.operation_checksum
    )
    assert repository.universal_quiesce_inventory().run_ids == ()
    stored_universal = repository.get_agent_run(universal.id)
    stored_deepsearch_v2 = repository.get_agent_run(deepsearch_v2.id)
    stored_direct = repository.get_agent_run(direct.id)
    assert stored_universal is not None and stored_universal.status is AgentRunStatus.CANCELLED
    assert stored_deepsearch_v2 is not None and stored_deepsearch_v2.status is AgentRunStatus.CANCELLED
    assert stored_direct is not None and stored_direct.status is AgentRunStatus.FAILED
    assert stored_direct.error_code == "external_outcome_unknown"


def test_quiesce_apply_requires_a_separate_backup_directory(tmp_path: Path) -> None:
    database = tmp_path / "quiesce-backup-directory.sqlite3"
    repository = SQLiteStore(database)
    inventory = repository.universal_quiesce_inventory()
    approval = tmp_path / "backup-directory-approval.json"
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
    backup = tmp_path / "invalid-same-directory-backup.sqlite3"
    receipt = tmp_path / "evidence" / "same-directory-receipt.json"

    with pytest.raises(QuiesceCommandError, match="backup_directory_must_differ"):
        main(
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
                "--receipt",
                str(receipt),
            ]
        )

    assert not backup.exists()


def test_quiesce_backup_publish_race_never_overwrites_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "quiesce-backup-race.sqlite3"
    repository = SQLiteStore(database)
    inventory = repository.universal_quiesce_inventory()
    approval = _approval_file(
        tmp_path,
        inventory.operation_checksum,
        name="backup-race-approval.json",
    )
    backup = tmp_path / "backups" / "race.sqlite3"
    receipt = tmp_path / "evidence" / "race-receipt.json"
    original_link = quiesce_command.os.link

    def racing_link(source, target, *, follow_symlinks=True):  # noqa: ANN001, ANN202
        if Path(target) == backup:
            backup.write_bytes(b"do-not-overwrite")
        return original_link(source, target, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(quiesce_command.os, "link", racing_link)

    with pytest.raises(QuiesceCommandError, match="backup_path_exists"):
        main(
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
                "--receipt",
                str(receipt),
            ]
        )

    assert backup.read_bytes() == b"do-not-overwrite"
    assert not receipt.exists()
    assert not list(backup.parent.glob(".*.tmp"))


def test_quiesce_backup_rejects_dangling_symlink_destination(tmp_path: Path) -> None:
    database = tmp_path / "quiesce-backup-symlink.sqlite3"
    repository = SQLiteStore(database)
    inventory = repository.universal_quiesce_inventory()
    approval = _approval_file(
        tmp_path,
        inventory.operation_checksum,
        name="backup-symlink-approval.json",
    )
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir()
    target = backup_directory / "missing-target.sqlite3"
    backup = backup_directory / "symlink.sqlite3"
    backup.symlink_to(target)

    with pytest.raises(QuiesceCommandError, match="backup_path_exists"):
        main(
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
                "--receipt",
                str(tmp_path / "evidence" / "symlink-receipt.json"),
            ]
        )

    assert backup.is_symlink()
    assert not target.exists()


def test_private_receipt_writer_rejects_dangling_symlink(tmp_path: Path) -> None:
    target = tmp_path / "missing-receipt-target.json"
    receipt = tmp_path / "receipt-link.json"
    receipt.symlink_to(target)

    with pytest.raises(QuiesceCommandError, match="receipt_path_exists"):
        quiesce_command._write_private_json(
            receipt,
            {"status": "backup_verified"},
            create_only=True,
        )

    assert receipt.is_symlink()
    assert not target.exists()


def test_private_receipt_writer_handles_short_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "evidence" / "short-write-receipt.json"
    payload: dict[str, object] = {
        "schema_version": "orchestration-quiesce-apply-receipt-v1",
        "status": "backup_verified",
        "operation_checksum": "a" * 64,
        "backup": {"sha256": "b" * 64},
    }
    original_write = quiesce_command.os.write
    write_calls = 0

    def short_write(descriptor: int, data) -> int:  # noqa: ANN001
        nonlocal write_calls
        write_calls += 1
        chunk_size = max(1, len(data) // 3)
        return original_write(descriptor, data[:chunk_size])

    monkeypatch.setattr(quiesce_command.os, "write", short_write)

    quiesce_command._write_private_json(receipt, payload, create_only=True)

    assert write_calls > 1
    assert json.loads(receipt.read_text(encoding="utf-8")) == payload
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "approved_by",
    [
        ["@operator-one"],
        ["@operator-one", "@operator-one"],
        ["operator-one", "@operator-two"],
    ],
)
def test_quiesce_apply_rejects_invalid_approval_identities(
    tmp_path: Path,
    approved_by: list[str],
) -> None:
    database = tmp_path / "quiesce-invalid-approval.sqlite3"
    repository = SQLiteStore(database)
    inventory = repository.universal_quiesce_inventory()
    approval = _approval_file(
        tmp_path,
        inventory.operation_checksum,
        name="invalid-approval.json",
        approved_by=approved_by,
    )

    with pytest.raises(QuiesceCommandError, match="quiesce_approval_invalid"):
        main(
            [
                "--database",
                str(database),
                "--apply",
                "--expected-operation-checksum",
                inventory.operation_checksum,
                "--backup",
                str(tmp_path / "backups" / "invalid-approval.sqlite3"),
                "--approval-file",
                str(approval),
                "--receipt",
                str(tmp_path / "evidence" / "invalid-approval.json"),
            ]
        )


def test_restore_inventory_mismatch_prevents_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "quiesce-restore-mismatch.sqlite3"
    repository = SQLiteStore(database)
    run = repository.save_agent_run(
        _run(
            "run_restore_mismatch",
            contract=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    inventory = repository.universal_quiesce_inventory()
    approval = _approval_file(
        tmp_path,
        inventory.operation_checksum,
        name="restore-mismatch-approval.json",
    )
    backup = tmp_path / "backups" / "restore-mismatch.sqlite3"
    receipt = tmp_path / "evidence" / "restore-mismatch-receipt.json"
    original_inventory = SQLiteStore.universal_quiesce_inventory

    def mismatched_restore(self):  # noqa: ANN001, ANN202
        current = original_inventory(self)
        if self.db_path.resolve() != database.resolve():
            return current.model_copy(update={"operation_checksum": "0" * 64})
        return current

    monkeypatch.setattr(SQLiteStore, "universal_quiesce_inventory", mismatched_restore)

    with pytest.raises(
        QuiesceCommandError,
        match="backup_restore_inventory_mismatch",
    ):
        main(
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
                "--receipt",
                str(receipt),
            ]
        )

    assert not backup.exists()
    assert not receipt.exists()
    assert repository.get_agent_run(run.id).status is AgentRunStatus.PLANNING  # type: ignore[union-attr]


def test_postcheck_failure_retains_durable_backup_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "quiesce-postcheck.sqlite3"
    repository = SQLiteStore(database)
    run = repository.save_agent_run(
        _run(
            "run_quiesce_postcheck",
            contract=AgentPlanningContractVersion.STANDARD_UNIVERSAL_V1,
        )
    )
    inventory = repository.universal_quiesce_inventory()
    approval = _approval_file(
        tmp_path,
        inventory.operation_checksum,
        name="postcheck-approval.json",
    )
    backup = tmp_path / "backups" / "postcheck.sqlite3"
    receipt = tmp_path / "evidence" / "postcheck-receipt.json"
    original_inventory = SQLiteStore.universal_quiesce_inventory
    source_inventory_calls = 0

    def failing_postcheck(self):  # noqa: ANN001, ANN202
        nonlocal source_inventory_calls
        current = original_inventory(self)
        if self.db_path.resolve() == database.resolve():
            source_inventory_calls += 1
            if source_inventory_calls == 2:
                return current.model_copy(update={"run_ids": ("postcheck_failed",)})
        return current

    monkeypatch.setattr(SQLiteStore, "universal_quiesce_inventory", failing_postcheck)

    with pytest.raises(QuiesceCommandError, match="quiesce_postcheck_failed"):
        main(
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
                "--receipt",
                str(receipt),
            ]
        )

    durable_receipt = json.loads(receipt.read_text(encoding="utf-8"))
    assert durable_receipt["status"] == "postcheck_failed"
    assert durable_receipt["error_code"] == "quiesce_postcheck_failed"
    assert durable_receipt["backup"]["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert repository.get_agent_run(run.id).status is AgentRunStatus.CANCELLED  # type: ignore[union-attr]


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
    write_claim = RuntimeToolCallClaimV1(
        call_id="call_quiesce_settled_write",
        run_id=run.id,
        plan_id=plan.id,
        node_id=node.id,
        tool_definition_id="tool_write",
        tool_name="write_tool",
        implementation_id="provider.write",
        implementation_version="1",
        side_effect="external",
        operation_identity="c" * 64,
    )
    assert repository.claim_runtime_tool_call(write_claim)
    repository.finish_runtime_tool_call(
        RuntimeToolCallOutcomeV1(
            call_id=write_claim.call_id,
            run_id=run.id,
            outcome="settled",
            result_hash="d" * 64,
        )
    )
    inventory = repository.universal_quiesce_inventory()

    repository.apply_universal_quiesce(
        expected_operation_checksum=inventory.operation_checksum,
    )

    stored_plan = repository.get_skill_plan(plan.id)
    stored_run = repository.get_agent_run(run.id)
    assert stored_plan is not None and stored_plan.status is SkillPlanStatus.PARTIAL
    assert stored_run is not None and stored_run.status is AgentRunStatus.PARTIAL
    assert stored_run.error_code == "process_restarted"


def test_quiesce_preserves_terminal_run_and_requires_projection_before_settlement(
    tmp_path: Path,
) -> None:
    repository = SQLiteStore(tmp_path / "quiesce-terminal-dispatch.sqlite3")
    run = _run("run_quiesce_terminal_dispatch").model_copy(
        update={
            "status": AgentRunStatus.COMPLETED,
            "output_text": "Completed output",
        }
    )
    receipt = RunDispatchReceiptV1(
        operation_key="dispatch:"
        + canonical_json_sha256(
            {
                "run_id": run.id,
                "operation_kind": "standard_direct",
                "generation": 1,
            }
        ),
        run_id=run.id,
        operation_kind="standard_direct",
    )
    repository.claim_new_agent_run(run, dispatch=receipt)

    blocked_inventory = repository.universal_quiesce_inventory()
    assert blocked_inventory.anomaly_codes == (
        f"terminal_projection_pending:{run.id}",
    )
    with pytest.raises(RuntimeError, match="quiesce_inventory_invalid"):
        repository.apply_universal_quiesce(
            expected_operation_checksum=blocked_inventory.operation_checksum,
        )
    assert repository.get_agent_run(run.id).status is AgentRunStatus.COMPLETED  # type: ignore[union-attr]

    repository.project_terminal_run_output(
        run_id=run.id,
        content=run.output_text or "",
        workflow_trace=ChatWorkflowTrace(
            intent=Intent.GENERAL_CHAT,
            confidence=1.0,
            source="chat",
            selected_workflow="chat",
            persisted=True,
            llm_used=True,
        ),
    )
    inventory = repository.universal_quiesce_inventory()
    assert inventory.anomaly_codes == ()
    assert run.id not in inventory.run_ids

    repository.apply_universal_quiesce(
        expected_operation_checksum=inventory.operation_checksum,
    )

    preserved = repository.get_agent_run(run.id)
    settled = repository.get_run_dispatch(receipt.operation_key)
    assert preserved is not None and preserved.status is AgentRunStatus.COMPLETED
    assert preserved.output_text == "Completed output"
    assert settled is not None and settled.state is RunDispatchState.SETTLED


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
