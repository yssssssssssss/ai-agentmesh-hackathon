from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.agent_runtime.service import AgentRuntimeService
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256, strict_json_loads
from agentmesh.deepsearch.budget import DeepSearchBudgetMeter
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    Artifact,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    SkillDefinition,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillSourceScope,
    ToolDefinition,
    now_utc,
)
from agentmesh.seed import USER
from agentmesh.store import SQLiteStore
from agentmesh.tool_runtime.factory import AgentMeshToolFactory


def _deepsearch_run(repository: SQLiteStore, run_id: str) -> AgentRun:
    created_at = now_utc()
    run, created = repository.claim_new_agent_run(
        AgentRun(
            id=run_id,
            thread_id=f"thread_{run_id}",
            user_id="user_artifact_budget",
            workspace_id="workspace_artifact_budget",
            project_id="project_artifact_budget",
            input_text="Create one large runtime artifact",
            client_turn_id=f"turn_{run_id}",
            status=AgentRunStatus.PLANNING,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
            requested_orchestration_mode=SkillOrchestrationRequestMode.AUTO,
            orchestration_version="v1",
            orchestration_mode="execute",
            absolute_expires_at=created_at + timedelta(days=7),
            deepsearch_budget=DeepSearchBudgetV1(),
            created_at=created_at,
            updated_at=created_at,
        )
    )
    assert created is True
    running = run.model_copy(update={"status": AgentRunStatus.RUNNING})
    with repository._connect() as connection:
        connection.execute(
            "UPDATE agent_runs SET payload = ? WHERE id = ?",
            (running.model_dump_json(), running.id),
        )
    return running


def test_deepsearch_oversized_tool_output_reserves_before_save_and_settles_exact_utf8_bytes(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-tool-artifact-budget.sqlite3")
    run = _deepsearch_run(repository, "run_tool_artifact_budget")
    output = '{"z":"' + ("汉" * 18_000) + '","a":1}'
    expected_content = canonical_json_bytes(strict_json_loads(output)).decode("utf-8")
    expected_usage = DeepSearchBudgetUsageV1(
        artifact_bytes=len(expected_content.encode("utf-8")),
    )
    observed_before_save: list[DeepSearchBudgetUsageV1] = []
    save_artifact = repository.save_deepsearch_runtime_artifact

    def observe_reservation(**kwargs):  # noqa: ANN003, ANN202
        persisted = repository.get_agent_run(run.id)
        assert persisted is not None and persisted.deepsearch_budget is not None
        reservation = persisted.deepsearch_budget.reservations[-1]
        assert reservation.status == "reserved"
        assert reservation.scope == "standard"
        observed_before_save.append(reservation.resource_maxima)
        return save_artifact(**kwargs)

    monkeypatch.setattr(repository, "save_deepsearch_runtime_artifact", observe_reservation)
    factory = AgentMeshToolFactory(repository, gateway=SimpleNamespace())  # type: ignore[arg-type]
    context = AgentMeshRunContext(
        user_id=run.user_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        thread_id=run.thread_id,
        run_id=run.id,
    )

    visible, artifact_id = factory._bounded_output(
        context,
        ToolDefinition(
            id="tool_large_output",
            name="large_output",
            description="Return a large payload",
            category="test",
        ),
        output,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
    )

    assert artifact_id is not None
    assert "Output truncated" in visible
    assert observed_before_save == [expected_usage]
    artifact = repository.get_artifact(artifact_id)
    assert artifact is not None and artifact.content == expected_content
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    assert persisted.deepsearch_budget.consumed == expected_usage
    reservation = persisted.deepsearch_budget.reservations[-1]
    assert reservation.scope == "standard"
    assert reservation.status == "settled"
    assert reservation.resource_maxima == expected_usage
    assert reservation.actual_usage == expected_usage


def test_standard_oversized_tool_output_preserves_legacy_artifact_behavior(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "standard-tool-artifact.sqlite3")
    run = repository.save_agent_run(
        AgentRun(
            id="run_standard_tool_artifact",
            thread_id="thread_standard_tool_artifact",
            user_id="user_artifact_budget",
            workspace_id="workspace_artifact_budget",
            project_id="project_artifact_budget",
            input_text="Create one ordinary artifact",
            status=AgentRunStatus.RUNNING,
        )
    )

    def unexpected_budget_call(**_kwargs):  # noqa: ANN202
        raise AssertionError("standard Artifacts must bypass the DeepSearch budget")

    def unexpected_run_lookup(_run_id):  # noqa: ANN001, ANN202
        raise AssertionError("standard Artifact persistence must remain a direct path")

    monkeypatch.setattr(repository, "get_agent_run", unexpected_run_lookup)
    monkeypatch.setattr(repository, "reserve_deepsearch_budget", unexpected_budget_call)
    monkeypatch.setattr(repository, "settle_deepsearch_budget", unexpected_budget_call)
    factory = AgentMeshToolFactory(repository, gateway=SimpleNamespace())  # type: ignore[arg-type]
    output = '{"z":"' + ("汉" * 18_000) + '", "a":1}'

    _visible, artifact_id = factory._bounded_output(
        AgentMeshRunContext(
            user_id=run.user_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            thread_id=run.thread_id,
            run_id=run.id,
        ),
        ToolDefinition(
            id="tool_standard_large_output",
            name="standard_large_output",
            description="Return a large payload",
            category="test",
        ),
        output,
    )

    assert artifact_id is not None
    artifact = repository.get_artifact(artifact_id)
    assert artifact is not None and artifact.content == output


def test_deepsearch_artifact_save_failure_settles_the_reserved_maximum(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-artifact-save-failure.sqlite3")
    run = _deepsearch_run(repository, "run_artifact_save_failure")
    output = '{"payload":"' + ("x" * 52_000) + '"}'
    expected_bytes = len(canonical_json_bytes(strict_json_loads(output)))

    def fail_save(**_kwargs):  # noqa: ANN202
        raise OSError("disk full")

    monkeypatch.setattr(repository, "save_deepsearch_runtime_artifact", fail_save)
    factory = AgentMeshToolFactory(repository, gateway=SimpleNamespace())  # type: ignore[arg-type]

    with pytest.raises(OSError, match="disk full"):
        factory._bounded_output(
            AgentMeshRunContext(
                user_id=run.user_id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                thread_id=run.thread_id,
                run_id=run.id,
            ),
            ToolDefinition(
                id="tool_failing_large_output",
                name="failing_large_output",
                description="Fail to persist a large payload",
                category="test",
            ),
            output,
            planning_mode=AgentPlanningMode.DEEPSEARCH,
        )

    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    reservation = persisted.deepsearch_budget.reservations[-1]
    expected_usage = DeepSearchBudgetUsageV1(artifact_bytes=expected_bytes)
    assert reservation.status == "settled"
    assert reservation.resource_maxima == expected_usage
    assert reservation.actual_usage == expected_usage
    assert persisted.deepsearch_budget.consumed == expected_usage


def test_deepsearch_large_node_result_charges_only_its_canonical_artifact_bytes(
    tmp_path,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-node-artifact-budget.sqlite3")
    run = _deepsearch_run(repository, "run_node_artifact_budget")
    node = SkillPlanNode(
        id="node_artifact_budget",
        skill_id="skill_artifact_budget",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="Create a large analysis",
        attempt=1,
    )
    plan = SkillPlan(
        id="plan_artifact_budget",
        run_id=run.id,
        version=2,
        intent=SkillIntent(goal=run.input_text),
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id="requirement_artifact_budget_v1",
    )
    skill = SkillDefinition(
        id=node.skill_id,
        name="artifact-budget",
        title="Artifact budget",
        description="Create a large analysis",
        instructions="Return the analysis",
        source_path="/tmp/artifact-budget/SKILL.md",
        source_scope=SkillSourceScope.BUILTIN,
        content_hash=node.skill_content_hash,
    )
    runtime = object.__new__(AgentRuntimeService)
    runtime.repository = repository
    user = USER.model_copy(
        update={
            "id": run.user_id,
            "workspace_id": run.workspace_id,
            "default_project_id": run.project_id,
        }
    )

    result = runtime._normalize_skill_node_result(
        {
            "node_id": node.id,
            "skill_id": skill.id,
            "summary": "Large analysis",
            "findings": ["汉" * 18_000],
        },
        total_tokens=9,
        plan=plan,
        node=node,
        skill=skill,
        run=run.model_copy(update={"plan_id": plan.id}),
        user=user,
        allowed_source_ids=set(),
        allowed_artifact_ids=set(),
        allowed_resource_references=set(),
        upstream_source_origins={},
    )

    assert len(result.artifact_ids) == 1
    artifact = repository.get_artifact(result.artifact_ids[0])
    assert artifact is not None
    artifact_bytes = artifact.content.encode("utf-8")
    assert canonical_json_bytes(strict_json_loads(artifact.content)) == artifact_bytes
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    reservation = persisted.deepsearch_budget.reservations[-1]
    expected_usage = DeepSearchBudgetUsageV1(artifact_bytes=len(artifact_bytes))
    assert reservation.scope == "standard"
    assert reservation.resource_maxima == expected_usage
    assert reservation.actual_usage == expected_usage
    assert reservation.actual_usage.tool_calls == 0
    assert reservation.actual_usage.evidence_items == 0
    assert reservation.actual_usage.evidence_bytes == 0


def _runtime_artifact(run: AgentRun, *, artifact_id: str, content: str) -> Artifact:
    return Artifact(
        id=artifact_id,
        run_id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        user_id=run.user_id,
        artifact_type="tool_output",
        content_type="application/json",
        content=canonical_json_bytes(strict_json_loads(content)).decode("utf-8"),
        truncated=True,
    )


def _artifact_operation_key(artifact: Artifact) -> str:
    return "artifact:" + canonical_json_sha256(
        {
            "artifact_id": artifact.id,
            "artifact_type": artifact.artifact_type,
            "run_id": artifact.run_id,
        }
    )


def test_store_rolls_back_runtime_artifact_when_atomic_budget_write_fails(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-artifact-atomic-rollback.sqlite3")
    run = _deepsearch_run(repository, "run_artifact_atomic_rollback")
    artifact = _runtime_artifact(
        run,
        artifact_id="artifact_atomic_rollback",
        content='{"result":"汉字"}',
    )
    usage = DeepSearchBudgetUsageV1(
        artifact_bytes=len(artifact.content.encode("utf-8")),
    )
    logical_operation_key = _artifact_operation_key(artifact)
    invocation_key = f"{logical_operation_key}:attempt:1"
    DeepSearchBudgetMeter(repository).reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key=logical_operation_key,
        invocation_key=invocation_key,
        physical_attempt=1,
        resource_maxima=usage,
        scope="standard",
    )

    def fail_budget_write(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("injected budget write failure")

    monkeypatch.setattr(repository, "_write_deepsearch_budget_run", fail_budget_write)

    with pytest.raises(RuntimeError, match="injected budget write failure"):
        repository.save_deepsearch_runtime_artifact(
            artifact=artifact,
            budget_invocation_key=invocation_key,
            actual_usage=usage,
        )

    assert repository.get_artifact(artifact.id) is None
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    reservation = persisted.deepsearch_budget.reservations[-1]
    assert reservation.status == "reserved"
    assert reservation.actual_usage is None
    assert reservation.resource_maxima == usage


def test_store_settles_identical_runtime_artifact_retry_at_zero_bytes(
    tmp_path,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-artifact-idempotent-retry.sqlite3")
    run = _deepsearch_run(repository, "run_artifact_idempotent_retry")
    artifact = _runtime_artifact(
        run,
        artifact_id="artifact_idempotent_retry",
        content='{"result":"stable"}',
    )
    usage = DeepSearchBudgetUsageV1(
        artifact_bytes=len(artifact.content.encode("utf-8")),
    )
    logical_operation_key = _artifact_operation_key(artifact)
    meter = DeepSearchBudgetMeter(repository)
    first_invocation = f"{logical_operation_key}:attempt:1"
    first = meter.reserve(
        run_id=run.id,
        expected_budget_version=1,
        logical_operation_key=logical_operation_key,
        invocation_key=first_invocation,
        physical_attempt=1,
        resource_maxima=usage,
        scope="standard",
    )
    repository.save_deepsearch_runtime_artifact(
        artifact=artifact,
        budget_invocation_key=first_invocation,
        actual_usage=usage,
    )
    second_invocation = f"{logical_operation_key}:attempt:2"
    meter.reserve(
        run_id=run.id,
        expected_budget_version=first.budget.version + 1,
        logical_operation_key=logical_operation_key,
        invocation_key=second_invocation,
        physical_attempt=2,
        resource_maxima=usage,
        scope="standard",
    )

    replayed = repository.save_deepsearch_runtime_artifact(
        artifact=artifact,
        budget_invocation_key=second_invocation,
        actual_usage=usage,
    )

    assert replayed == artifact
    persisted = repository.get_agent_run(run.id)
    assert persisted is not None and persisted.deepsearch_budget is not None
    assert persisted.deepsearch_budget.consumed == usage
    assert persisted.deepsearch_budget.reservations[-1].status == "settled"
    assert persisted.deepsearch_budget.reservations[-1].actual_usage == DeepSearchBudgetUsageV1()


def test_deepsearch_remaining_run_time_uses_absolute_expiry_not_legacy_five_minutes() -> None:
    now = now_utc()
    run = AgentRun(
        id="run_deepsearch_long_window",
        thread_id="thread_deepsearch_long_window",
        user_id="user_artifact_budget",
        workspace_id="workspace_artifact_budget",
        project_id="project_artifact_budget",
        input_text="Run a multi-node DeepSearch",
        status=AgentRunStatus.RUNNING,
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        deadline_at=None,
        absolute_expires_at=now + timedelta(hours=2),
        deepsearch_budget=DeepSearchBudgetV1(),
    )

    remaining = AgentRuntimeService._remaining_run_seconds(run)

    assert 7_190 < remaining <= 7_200


def test_standard_remaining_run_time_keeps_legacy_five_minute_fallback() -> None:
    run = AgentRun(
        id="run_standard_legacy_window",
        thread_id="thread_standard_legacy_window",
        user_id="user_artifact_budget",
        workspace_id="workspace_artifact_budget",
        project_id="project_artifact_budget",
        input_text="Run ordinary work",
        status=AgentRunStatus.RUNNING,
        deadline_at=None,
    )

    assert AgentRuntimeService._remaining_run_seconds(run) == 300.0
