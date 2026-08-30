from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest

from agentmesh.acquisition import AcquiredEvidenceItem
from agentmesh.agent_runtime.models import AgentMeshRunContext
from agentmesh.artifacts import (
    ArtifactAccessError,
    TrustedEvidenceEnvelopeV1,
    V1VerifiedArtifactStore,
)
from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.deepsearch.contracts import (
    RequirementPayloadV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    requirement_content_hash,
)
from agentmesh.deepsearch.planning import build_deepsearch_plan_snapshot, plan_content_hash
from agentmesh.models import (
    AgentPlanningMode,
    AgentRun,
    AgentRunStatus,
    DeepSearchBudgetUsageV1,
    DeepSearchBudgetV1,
    DeepSearchToolInvocationV1,
    SkillIntent,
    SkillOrchestrationRequestMode,
    SkillPlan,
    SkillPlanNode,
    SkillPlanNodeStatus,
    SkillPlanStatus,
    SkillResourceManifestV1,
    Source,
    ToolDefinition,
    now_utc,
)
from agentmesh.store import DeepSearchEvidenceConflict, SQLiteStore
from agentmesh.tool_runtime.deepsearch import (
    DeepSearchToolEvidenceBatch,
    DeepSearchToolRuntimeError,
    build_deepsearch_tool_invocation,
    normalize_deepsearch_tool_evidence,
)
from agentmesh.tool_runtime.gateway import ToolGateway, ToolRuntimeDescriptor


def _evidence(source_id: str, excerpt: str, *, retrieved_at):  # noqa: ANN001
    return AcquiredEvidenceItem(
        source_id=source_id,
        content_provider="test-provider",
        excerpt=excerpt,
        retrieved_at=retrieved_at,
        content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    )


def _prepare_batch(
    repository: SQLiteStore,
    *,
    reserve: bool = True,
) -> tuple[DeepSearchToolEvidenceBatch, DeepSearchToolInvocationV1]:
    created_at = now_utc()
    run, created = repository.claim_new_agent_run(
        AgentRun(
            id="run_evidence_batch",
            thread_id="thread_evidence_batch",
            user_id="user_evidence_batch",
            workspace_id="workspace_evidence_batch",
            project_id="project_evidence_batch",
            input_text="Compare two sources",
            client_turn_id="turn_evidence_batch",
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
    assert run.client_turn_id is not None and run.create_request_hash is not None
    payload = RequirementPayloadV1(
        goal=run.input_text,
        scope=RequirementScopeV1(),
        success_criteria=[
            RequirementSuccessCriterionV1(
                id="criterion_sources",
                statement="Use traceable sources",
            )
        ],
        deliverables=["Evidence-backed report"],
    )
    requirement = RequirementVersionV1(
        id="requirement_evidence_batch_v1",
        run_id=run.id,
        version=1,
        request_key=run.client_turn_id,
        request_hash=run.create_request_hash,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=created_at,
    )
    appended = repository.append_deepsearch_requirement_and_transition(
        run_id=run.id,
        user_id=run.user_id,
        requirement=requirement.model_dump(mode="json"),
        expected_requirement_version=None,
        expected_run_status=AgentRunStatus.PLANNING,
        next_run_status=AgentRunStatus.PLANNING,
        events=[],
        checked_at=created_at,
    )
    assert appended is not None

    resource_manifest_payload = {
        "schema_version": "skill-resource-manifest-v1",
        "required_resources": [],
        "resource_hashes": {},
    }
    node = SkillPlanNode(
        id="node_evidence_batch",
        skill_id="skill_evidence_batch",
        skill_version="1",
        skill_content_hash="a" * 64,
        reason="Collect public evidence",
        required_tool_names=["web_research"],
        resource_manifest=SkillResourceManifestV1(
            **resource_manifest_payload,
            content_hash=canonical_json_sha256(resource_manifest_payload),
        ),
        status=SkillPlanNodeStatus.RUNNING,
        attempt=1,
        started_at=created_at,
    )
    plan = SkillPlan(
        id="plan_evidence_batch",
        run_id=run.id,
        version=2,
        status=SkillPlanStatus.RUNNING,
        intent=SkillIntent(goal=run.input_text),
        candidate_skill_ids=[node.skill_id],
        preferred_order=[node.skill_id],
        nodes=[node],
        planning_mode=AgentPlanningMode.DEEPSEARCH,
        requirement_version_id=requirement.id,
        requirement_content_hash=requirement.content_hash,
        problem_graph_hash="b" * 64,
        created_at=created_at,
        updated_at=created_at,
    )
    plan.plan_content_hash = plan_content_hash(plan)
    running_run = appended.run.model_copy(
        update={
            "plan_id": plan.id,
            "status": AgentRunStatus.RUNNING,
            "updated_at": created_at,
        }
    )
    snapshot = build_deepsearch_plan_snapshot(
        run=running_run,
        plan=plan,
        created_at=created_at,
    )
    plan.approved_plan_artifact_id = snapshot.id
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE id = ?",
            (running_run.model_dump_json(), running_run.updated_at.isoformat(), running_run.id),
        )
        repository._write_skill_plan(connection, plan)
    V1VerifiedArtifactStore(repository).insert_sealed(snapshot)

    definition = repository.save_tool_definition(
        ToolDefinition(
            id="tool_web_research",
            name="web_research",
            description="Search public sources",
            category="research",
            side_effect="read",
            implementation_id="test.web_research",
            implementation_version="1",
        )
    )
    context = AgentMeshRunContext(
        user_id=running_run.user_id,
        workspace_id=running_run.workspace_id,
        project_id=running_run.project_id,
        thread_id=running_run.thread_id,
        run_id=running_run.id,
        requirement_version_id=requirement.id,
        plan_id=plan.id,
        plan_version=plan.version,
        node_id=node.id,
        node_step_number=1,
        node_attempt=node.attempt,
        skill_id=node.skill_id,
    )
    invocation = build_deepsearch_tool_invocation(
        context=context,
        definition=definition,
        arguments={"query": "market"},
        tool_call_id="tool_call_evidence_batch",
    )
    if reserve:
        repository.reserve_deepsearch_budget(
            run_id=run.id,
            expected_budget_version=1,
            logical_operation_key=invocation.operation_key,
            invocation_key=invocation.operation_key,
            physical_attempt=1,
            resource_maxima=DeepSearchBudgetUsageV1(
                active_seconds=definition.timeout_seconds,
                tool_calls=1,
            ),
            tool_invocation=invocation,
        )

    retrieved_at = created_at + timedelta(minutes=1)
    rows = [
        (
            Source(
                id="provider_b",
                title="B source",
                source_type="web_page",
                reference=" https://b.test ",
            ),
            _evidence("provider_b", "Evidence B", retrieved_at=retrieved_at),
        ),
        (
            Source(
                id="provider_a",
                title="A source",
                source_type="web_page",
                reference="https://a.test",
            ),
            _evidence("provider_a", "Evidence A", retrieved_at=retrieved_at),
        ),
    ]
    batch = normalize_deepsearch_tool_evidence(
        context=context,
        definition=definition,
        invocation=invocation,
        value={
            "sources": [source.model_dump(mode="python") for source, _item in rows],
            "source_evidence": [item.model_dump(mode="python") for _source, item in rows],
        },
        execution_mode="real",
    )
    return batch, invocation


def test_evidence_batch_is_atomic_and_exact_replay_is_idempotent(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-evidence-batch.sqlite3")
    batch, invocation = _prepare_batch(repository)

    first = repository.save_deepsearch_evidence_batch(
        invocation=invocation,
        sources=batch.sources,
        artifacts=batch.artifacts,
    )
    replay = repository.save_deepsearch_evidence_batch(
        invocation=invocation,
        sources=tuple(reversed(batch.sources)),
        artifacts=tuple(reversed(batch.artifacts)),
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert first.sources == replay.sources == batch.sources
    assert first.artifacts == replay.artifacts == batch.artifacts
    assert all(repository.get_source(source.id) == source for source in batch.sources)
    assert all(repository.get_artifact(artifact.id) == artifact for artifact in batch.artifacts)
    stored_run = repository.get_agent_run(invocation.run_id)
    assert stored_run is not None and stored_run.deepsearch_budget is not None
    evidence_reservations = [
        item
        for item in stored_run.deepsearch_budget.reservations
        if item.logical_operation_key == f"evidence:{invocation.operation_key}"
    ]
    assert len(evidence_reservations) == 1
    assert evidence_reservations[0].status == "settled"
    assert evidence_reservations[0].actual_usage is not None
    assert evidence_reservations[0].actual_usage.evidence_items == len(batch.artifacts)
    assert evidence_reservations[0].actual_usage.evidence_bytes == sum(
        envelope.size_bytes for envelope in batch.envelopes
    )
    assert evidence_reservations[0].actual_usage.artifact_bytes == sum(
        artifact.size_bytes or 0 for artifact in batch.artifacts
    )
    with repository._read_connect() as connection:
        source_count = connection.execute(
            "SELECT COUNT(*) FROM records WHERE collection = 'sources'"
        ).fetchone()[0]
        artifact_count = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE artifact_type = 'deepsearch_tool_evidence'"
        ).fetchone()[0]
    assert source_count == len(batch.sources)
    assert artifact_count == len(batch.artifacts)


def test_evidence_batch_rolls_back_every_source_and_artifact_on_late_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-evidence-batch-rollback.sqlite3")
    batch, invocation = _prepare_batch(repository)
    original = V1VerifiedArtifactStore.insert_sealed
    failing_artifact_id = batch.artifacts[-1].id

    def fail_second_artifact(self, artifact, *, connection=None):  # noqa: ANN001
        if artifact.id == failing_artifact_id:
            raise ArtifactAccessError("artifact_identity_conflict")
        return original(self, artifact, connection=connection)

    monkeypatch.setattr(V1VerifiedArtifactStore, "insert_sealed", fail_second_artifact)

    with pytest.raises(
        DeepSearchEvidenceConflict,
        match="deepsearch_evidence_identity_conflict",
    ):
        repository.save_deepsearch_evidence_batch(
            invocation=invocation,
            sources=batch.sources,
            artifacts=batch.artifacts,
        )

    assert all(repository.get_source(source.id) is None for source in batch.sources)
    assert all(repository.get_artifact(artifact.id) is None for artifact in batch.artifacts)
    stored_run = repository.get_agent_run(invocation.run_id)
    assert stored_run is not None and stored_run.deepsearch_budget is not None
    assert all(
        item.logical_operation_key != f"evidence:{invocation.operation_key}"
        for item in stored_run.deepsearch_budget.reservations
    )


def test_evidence_batch_requires_prior_tool_budget_reservation(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-evidence-batch-reservation.sqlite3")
    batch, invocation = _prepare_batch(repository, reserve=False)

    with pytest.raises(
        DeepSearchEvidenceConflict,
        match="deepsearch_evidence_reservation_missing",
    ):
        repository.save_deepsearch_evidence_batch(
            invocation=invocation,
            sources=batch.sources,
            artifacts=batch.artifacts,
        )

    assert all(repository.get_source(source.id) is None for source in batch.sources)
    assert all(repository.get_artifact(artifact.id) is None for artifact in batch.artifacts)


def test_evidence_batch_rejects_reservation_without_full_tool_invocation(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-evidence-batch-generic-reservation.sqlite3")
    batch, invocation = _prepare_batch(repository, reserve=False)
    run = repository.get_agent_run(invocation.run_id)
    definition = repository.get_tool_definition(invocation.tool_definition_id)
    assert run is not None and run.deepsearch_budget is not None and definition is not None
    repository.reserve_deepsearch_budget(
        run_id=run.id,
        expected_budget_version=run.deepsearch_budget.version,
        logical_operation_key=invocation.operation_key,
        invocation_key=invocation.operation_key,
        physical_attempt=1,
        resource_maxima=DeepSearchBudgetUsageV1(
            active_seconds=definition.timeout_seconds,
            tool_calls=1,
        ),
    )

    with pytest.raises(
        DeepSearchEvidenceConflict,
        match="deepsearch_evidence_reservation_missing",
    ):
        repository.save_deepsearch_evidence_batch(
            invocation=invocation,
            sources=batch.sources,
            artifacts=batch.artifacts,
        )


def test_evidence_batch_rejects_wrong_plan_step_without_partial_writes(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-evidence-batch-step.sqlite3")
    batch, invocation = _prepare_batch(repository)
    invalid_artifacts = (
        batch.artifacts[0].model_copy(update={"step_number": 2}),
        *batch.artifacts[1:],
    )

    with pytest.raises(
        DeepSearchEvidenceConflict,
        match="deepsearch_evidence_integrity_failed",
    ):
        repository.save_deepsearch_evidence_batch(
            invocation=invocation,
            sources=batch.sources,
            artifacts=invalid_artifacts,
        )

    assert all(repository.get_source(source.id) is None for source in batch.sources)
    assert all(repository.get_artifact(artifact.id) is None for artifact in batch.artifacts)


def test_evidence_batch_rejects_source_identity_drift_after_commit(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-evidence-batch-drift.sqlite3")
    batch, invocation = _prepare_batch(repository)
    repository.save_deepsearch_evidence_batch(
        invocation=invocation,
        sources=batch.sources,
        artifacts=batch.artifacts,
    )
    changed_sources = (
        batch.sources[0].model_copy(update={"title": "Changed title"}),
        *batch.sources[1:],
    )

    with pytest.raises(
        DeepSearchEvidenceConflict,
        match="deepsearch_evidence_identity_conflict",
    ):
        repository.save_deepsearch_evidence_batch(
            invocation=invocation,
            sources=changed_sources,
            artifacts=batch.artifacts,
        )

    assert repository.get_source(batch.sources[0].id) == batch.sources[0]


def test_evidence_batch_rejects_content_drift_for_the_same_operation(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-evidence-batch-content-drift.sqlite3")
    batch, invocation = _prepare_batch(repository)
    repository.save_deepsearch_evidence_batch(
        invocation=invocation,
        sources=batch.sources,
        artifacts=batch.artifacts,
    )
    original_artifact = batch.artifacts[0]
    envelope = TrustedEvidenceEnvelopeV1.model_validate_json(original_artifact.content)
    changed_excerpt = envelope.excerpt + " changed"
    changed_envelope = envelope.model_copy(
        update={
            "excerpt": changed_excerpt,
            "content_hash": hashlib.sha256(changed_excerpt.encode("utf-8")).hexdigest(),
            "size_bytes": len(changed_excerpt.encode("utf-8")),
        }
    )
    changed_content = canonical_json_bytes(
        changed_envelope.model_dump(mode="python")
    ).decode("utf-8")
    changed_artifact = original_artifact.model_copy(
        update={
            "content": changed_content,
            "content_hash": hashlib.sha256(changed_content.encode("utf-8")).hexdigest(),
            "size_bytes": len(changed_content.encode("utf-8")),
        }
    )

    with pytest.raises(
        DeepSearchEvidenceConflict,
        match="deepsearch_evidence_identity_conflict",
    ):
        repository.save_deepsearch_evidence_batch(
            invocation=invocation,
            sources=batch.sources,
            artifacts=(changed_artifact, *batch.artifacts[1:]),
        )

    assert repository.get_artifact(original_artifact.id) == original_artifact


def test_gateway_persists_invocation_and_evidence_before_returning(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-gateway.sqlite3")
    batch, invocation = _prepare_batch(repository, reserve=False)
    definition = repository.get_tool_definition(invocation.tool_definition_id)
    assert definition is not None
    calls: list[str] = []

    class Gateway(ToolGateway):
        def __init__(self) -> None:
            self.repository = repository

        def describe(self, _tool_name: str) -> ToolRuntimeDescriptor:
            return ToolRuntimeDescriptor(
                implementation_id=invocation.implementation_id,
                implementation_version=invocation.implementation_version,
                execution_mode="real",
                health_state="healthy",
                health_checked_at=now_utc(),
            )

        def web_research(  # noqa: ANN201
            self,
            _context,
            _arguments,
            *,
            operation_key=None,
            persist_sources=True,
        ):
            calls.append(operation_key)
            assert persist_sources is False
            return {
                "title": "Evidence",
                "content": "Evidence A\nEvidence B",
                "sources": [item.model_dump(mode="json") for item in batch.sources],
                "source_evidence": [
                    item.model_dump(mode="json") for item in batch.source_evidence
                ],
                "provider_calls": [],
                "permission": "project_visible",
                "metadata": {"mode": "real"},
            }

    context = AgentMeshRunContext(
        user_id="user_evidence_batch",
        workspace_id="workspace_evidence_batch",
        project_id="project_evidence_batch",
        thread_id="thread_evidence_batch",
        run_id=invocation.run_id,
        requirement_version_id=invocation.requirement_version_id,
        plan_id=invocation.plan_id,
        plan_version=invocation.plan_version,
        node_id=invocation.node_id,
        node_step_number=1,
        node_attempt=invocation.node_attempt,
        skill_id="skill_evidence_batch",
    )
    gateway = Gateway()

    with pytest.raises(DeepSearchToolRuntimeError, match="deepsearch_tool_lineage_mismatch"):
        gateway.invoke(
            context=context,
            definition=definition,
            arguments={"query": "different"},
            invocation=invocation,
        )
    assert calls == []

    value = gateway.invoke(
        context=context,
        definition=definition,
        arguments={"query": "market"},
        invocation=invocation,
    )

    assert calls == [invocation.operation_key]
    assert [item["evidence_artifact_id"] for item in value["evidence_bindings"]] == [
        artifact.id for artifact in batch.artifacts
    ]
    assert context.artifact_ids == [artifact.id for artifact in batch.artifacts]
    stored_run = repository.get_agent_run(invocation.run_id)
    assert stored_run is not None and stored_run.deepsearch_budget is not None
    reservation = next(
        item
        for item in stored_run.deepsearch_budget.reservations
        if item.invocation_key == invocation.operation_key
    )
    assert reservation.tool_invocation == invocation
    assert reservation.status == "settled"
    assert all(repository.get_source(source.id) == source for source in batch.sources)
    assert all(repository.get_artifact(artifact.id) == artifact for artifact in batch.artifacts)

    with pytest.raises(DeepSearchToolRuntimeError, match="external_outcome_unknown"):
        gateway.invoke(
            context=context,
            definition=definition,
            arguments={"query": "market"},
            invocation=invocation,
        )
    assert calls == [invocation.operation_key]


def test_gateway_does_not_replay_a_reserved_invocation_after_unknown_outcome(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "deepsearch-gateway-unknown.sqlite3")
    _batch, invocation = _prepare_batch(repository, reserve=False)
    definition = repository.get_tool_definition(invocation.tool_definition_id)
    assert definition is not None
    calls: list[str] = []

    class Gateway(ToolGateway):
        def __init__(self) -> None:
            self.repository = repository

        def describe(self, _tool_name: str) -> ToolRuntimeDescriptor:
            return ToolRuntimeDescriptor(
                implementation_id=invocation.implementation_id,
                implementation_version=invocation.implementation_version,
                execution_mode="real",
                health_state="healthy",
                health_checked_at=now_utc(),
            )

        def web_research(  # noqa: ANN201
            self,
            _context,
            _arguments,
            *,
            operation_key=None,
            persist_sources=True,
        ):
            del persist_sources
            calls.append(operation_key)
            raise TimeoutError("provider result is unknown")

    context = AgentMeshRunContext(
        user_id="user_evidence_batch",
        workspace_id="workspace_evidence_batch",
        project_id="project_evidence_batch",
        thread_id="thread_evidence_batch",
        run_id=invocation.run_id,
        requirement_version_id=invocation.requirement_version_id,
        plan_id=invocation.plan_id,
        plan_version=invocation.plan_version,
        node_id=invocation.node_id,
        node_step_number=1,
        node_attempt=invocation.node_attempt,
        skill_id="skill_evidence_batch",
    )
    gateway = Gateway()

    for _attempt in range(2):
        with pytest.raises(DeepSearchToolRuntimeError, match="external_outcome_unknown"):
            gateway.invoke(
                context=context,
                definition=definition,
                arguments={"query": "market"},
                invocation=invocation,
            )

    assert calls == [invocation.operation_key]
    stored_run = repository.get_agent_run(invocation.run_id)
    assert stored_run is not None and stored_run.deepsearch_budget is not None
    reservations = [
        item
        for item in stored_run.deepsearch_budget.reservations
        if item.invocation_key == invocation.operation_key
    ]
    assert len(reservations) == 1
    assert reservations[0].tool_invocation == invocation
    assert reservations[0].status == "reserved"
