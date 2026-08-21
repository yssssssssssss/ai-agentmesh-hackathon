"""In-memory research-v3 adapters for isolated execution/report tests only.

These adapters intentionally do not import or delegate to the production ``Store``. They
provide append-only behavior and verified readback for this isolated Slice 1 lane.
"""

from __future__ import annotations

from threading import RLock
from typing import TypeVar

from pydantic import BaseModel

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.common import (
    EvidenceManifestArtifactRefV3,
    Identifier,
    ProblemGraphArtifactRefV3,
    SealedArtifactRefV3,
)
from agentmesh.research_orchestration.v3.deliverable import ResearchDeliverableV3
from agentmesh.research_orchestration.v3.evidence import EvidenceManifestV3, VerifiedArtifactContentV3
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanVersionV3, PlanCandidateSetV3
from agentmesh.research_orchestration.v3.ports import ActorExecutionResultV3
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3
from agentmesh.research_orchestration.v3.review import ReportReviewV3
from agentmesh.research_orchestration.v3.snapshots import ResearchControlSnapshotV3

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class InMemoryAppendError(ValueError):
    pass


def _copy_model(value: _ModelT) -> _ModelT:
    return type(value).model_validate(value.model_dump(mode="python", round_trip=True))


def _artifact_id(*, run_id: str, kind: str, content_hash: str) -> str:
    identity_hash = canonical_json_v3_sha256(
        {"run_id": run_id, "kind": kind, "content_hash": content_hash}
    )
    return f"artifact_{kind}_{identity_hash[:24]}"


class InMemoryResearchV3Repository:
    """Append-only test adapter implementing ``ResearchV3RepositoryPort`` in memory."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._state_versions: dict[str, int] = {}
        self._requirements: dict[tuple[str, str], RequirementVersionV3] = {}
        self._requirement_versions: set[tuple[str, int]] = set()
        self._candidate_sets: dict[tuple[str, str], PlanCandidateSetV3] = {}
        self._problem_graphs: dict[str, tuple[ProblemGraphArtifactRefV3, ProblemGraphV1]] = {}
        self._plans: dict[tuple[str, str], ExecutionPlanVersionV3] = {}
        self._plan_versions: set[tuple[str, int]] = set()
        self._control_snapshots: dict[
            str, tuple[SealedArtifactRefV3, ResearchControlSnapshotV3]
        ] = {}
        self._actor_results: dict[
            tuple[str, str, str, int], ActorExecutionResultV3
        ] = {}
        self._evidence_manifests: dict[
            str, tuple[EvidenceManifestArtifactRefV3, EvidenceManifestV3]
        ] = {}
        self._deliverables: dict[str, tuple[SealedArtifactRefV3, ResearchDeliverableV3]] = {}
        self._reviews: dict[str, tuple[SealedArtifactRefV3, ReportReviewV3]] = {}
        self._reports: dict[str, tuple[SealedArtifactRefV3, ReportDocumentV3]] = {}

    def state_version(self, run_id: Identifier) -> int:
        with self._lock:
            return self._state_versions.get(run_id, 0)

    def _check_version(self, run_id: str, expected_state_version: int) -> None:
        actual = self._state_versions.get(run_id, 0)
        if expected_state_version != actual:
            raise InMemoryAppendError(
                f"state version conflict for {run_id}: expected {expected_state_version}, actual {actual}"
            )

    def _advance(self, run_id: str) -> None:
        self._state_versions[run_id] = self._state_versions.get(run_id, 0) + 1

    def get_requirement(
        self,
        run_id: Identifier,
        version_id: Identifier,
    ) -> RequirementVersionV3 | None:
        with self._lock:
            value = self._requirements.get((run_id, version_id))
            return _copy_model(value) if value is not None else None

    def append_requirement(
        self,
        requirement: RequirementVersionV3,
        *,
        expected_state_version: int,
    ) -> None:
        with self._lock:
            self._check_version(requirement.run_id, expected_state_version)
            key = (requirement.run_id, requirement.id)
            version_key = (requirement.run_id, requirement.version)
            if key in self._requirements or version_key in self._requirement_versions:
                raise InMemoryAppendError("Requirement identity or version was already appended")
            self._requirements[key] = _copy_model(requirement)
            self._requirement_versions.add(version_key)
            self._advance(requirement.run_id)

    def get_candidate_set(
        self,
        run_id: Identifier,
        requirement_version_id: Identifier,
    ) -> PlanCandidateSetV3 | None:
        with self._lock:
            value = self._candidate_sets.get((run_id, requirement_version_id))
            return _copy_model(value) if value is not None else None

    def append_candidate_set(
        self,
        run_id: Identifier,
        requirement_version_id: Identifier,
        candidate_set: PlanCandidateSetV3,
        *,
        expected_state_version: int,
    ) -> None:
        with self._lock:
            self._check_version(run_id, expected_state_version)
            key = (run_id, requirement_version_id)
            if key in self._candidate_sets:
                raise InMemoryAppendError("Plan candidate set was already appended")
            self._candidate_sets[key] = _copy_model(candidate_set)
            self._advance(run_id)

    def get_problem_graph(self, artifact: ProblemGraphArtifactRefV3) -> ProblemGraphV1 | None:
        with self._lock:
            stored = self._problem_graphs.get(artifact.artifact_id)
            if stored is None or stored[0] != artifact:
                return None
            return _copy_model(stored[1])

    def seal_problem_graph(
        self,
        run_id: Identifier,
        graph: ProblemGraphV1,
        *,
        expected_state_version: int,
    ) -> ProblemGraphArtifactRefV3:
        content_hash = canonical_json_v3_sha256(graph)
        artifact = ProblemGraphArtifactRefV3(
            artifact_id=_artifact_id(
                run_id=run_id,
                kind="problem_graph",
                content_hash=content_hash,
            ),
            kind="problem_graph",
            schema_version="problem-graph-v1",
            content_hash=content_hash,
        )
        with self._lock:
            self._check_version(run_id, expected_state_version)
            if artifact.artifact_id in self._problem_graphs:
                raise InMemoryAppendError("ProblemGraph Artifact was already sealed")
            self._problem_graphs[artifact.artifact_id] = (artifact, _copy_model(graph))
            self._advance(run_id)
        return artifact

    def get_plan(
        self,
        run_id: Identifier,
        version_id: Identifier,
    ) -> ExecutionPlanVersionV3 | None:
        with self._lock:
            value = self._plans.get((run_id, version_id))
            return _copy_model(value) if value is not None else None

    def append_plan(
        self,
        plan: ExecutionPlanVersionV3,
        *,
        expected_state_version: int,
    ) -> None:
        with self._lock:
            self._check_version(plan.run_id, expected_state_version)
            key = (plan.run_id, plan.id)
            version_key = (plan.run_id, plan.version)
            if key in self._plans or version_key in self._plan_versions:
                raise InMemoryAppendError("Execution Plan identity or version was already appended")
            self._plans[key] = _copy_model(plan)
            self._plan_versions.add(version_key)
            self._advance(plan.run_id)

    def get_control_snapshot(
        self,
        artifact: SealedArtifactRefV3,
    ) -> ResearchControlSnapshotV3 | None:
        with self._lock:
            stored = self._control_snapshots.get(artifact.artifact_id)
            if stored is None or stored[0] != artifact:
                return None
            return _copy_model(stored[1])

    def read_control_snapshot(
        self,
        artifact: SealedArtifactRefV3,
    ) -> ResearchControlSnapshotV3 | None:
        """Execution-facing verified read seam for a sealed control snapshot."""

        return self.get_control_snapshot(artifact)

    def append_control_snapshot(
        self,
        run_id: Identifier,
        snapshot: ResearchControlSnapshotV3,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3:
        artifact = self._sealed_ref(
            run_id=run_id,
            kind="research_control_snapshot",
            schema_version="research-control-snapshot-v3",
            value=snapshot,
        )
        with self._lock:
            self._check_version(run_id, expected_state_version)
            if artifact.artifact_id in self._control_snapshots:
                raise InMemoryAppendError("control snapshot Artifact was already appended")
            self._control_snapshots[artifact.artifact_id] = (artifact, _copy_model(snapshot))
            self._advance(run_id)
        return artifact

    def get_actor_results(
        self,
        run_id: Identifier,
        plan_version_id: Identifier,
        attempt_id: Identifier,
    ) -> tuple[ActorExecutionResultV3, ...]:
        with self._lock:
            values = [
                value
                for (stored_run, stored_plan, stored_attempt, _), value in self._actor_results.items()
                if (stored_run, stored_plan, stored_attempt)
                == (run_id, plan_version_id, attempt_id)
            ]
            return tuple(_copy_model(value) for value in sorted(values, key=lambda item: item.step_number))

    def append_actor_result(
        self,
        result: ActorExecutionResultV3,
        *,
        expected_state_version: int,
    ) -> None:
        key = (result.run_id, result.plan_version_id, result.attempt_id, result.step_number)
        with self._lock:
            self._check_version(result.run_id, expected_state_version)
            if key in self._actor_results:
                raise InMemoryAppendError("Actor result for this execution Step was already appended")
            self._actor_results[key] = _copy_model(result)
            self._advance(result.run_id)

    def get_evidence_manifest(
        self,
        artifact: EvidenceManifestArtifactRefV3,
    ) -> EvidenceManifestV3 | None:
        with self._lock:
            stored = self._evidence_manifests.get(artifact.artifact_id)
            if stored is None or stored[0] != artifact:
                return None
            return _copy_model(stored[1])

    def append_evidence_manifest(
        self,
        manifest: EvidenceManifestV3,
        *,
        expected_state_version: int,
    ) -> EvidenceManifestArtifactRefV3:
        content_hash = canonical_json_v3_sha256(manifest)
        artifact = EvidenceManifestArtifactRefV3(
            artifact_id=_artifact_id(
                run_id=manifest.run_id,
                kind="evidence_manifest",
                content_hash=content_hash,
            ),
            kind="evidence_manifest",
            schema_version="evidence-manifest-v3",
            content_hash=content_hash,
        )
        with self._lock:
            self._check_version(manifest.run_id, expected_state_version)
            if artifact.artifact_id in self._evidence_manifests:
                raise InMemoryAppendError("Evidence Manifest Artifact was already appended")
            self._evidence_manifests[artifact.artifact_id] = (artifact, _copy_model(manifest))
            self._advance(manifest.run_id)
        return artifact

    def get_deliverable(self, artifact: SealedArtifactRefV3) -> ResearchDeliverableV3 | None:
        return self._get_artifact(self._deliverables, artifact)

    def append_deliverable(
        self,
        deliverable: ResearchDeliverableV3,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3:
        return self._append_artifact(
            collection=self._deliverables,
            run_id=deliverable.run_id,
            kind="research_deliverable",
            schema_version="research-deliverable-v3",
            value=deliverable,
            expected_state_version=expected_state_version,
        )

    def get_review(self, artifact: SealedArtifactRefV3) -> ReportReviewV3 | None:
        return self._get_artifact(self._reviews, artifact)

    def append_review(
        self,
        review: ReportReviewV3,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3:
        return self._append_artifact(
            collection=self._reviews,
            run_id=review.run_id,
            kind="report_review",
            schema_version="report-review-v3",
            value=review,
            expected_state_version=expected_state_version,
        )

    def get_report(self, artifact: SealedArtifactRefV3) -> ReportDocumentV3 | None:
        return self._get_artifact(self._reports, artifact)

    def append_report(
        self,
        report: ReportDocumentV3,
        *,
        expected_state_version: int,
    ) -> SealedArtifactRefV3:
        return self._append_artifact(
            collection=self._reports,
            run_id=report.run_id,
            kind="report_document",
            schema_version="report-document-v3",
            value=report,
            expected_state_version=expected_state_version,
        )

    @staticmethod
    def _sealed_ref(
        *,
        run_id: str,
        kind: str,
        schema_version: str,
        value: BaseModel,
    ) -> SealedArtifactRefV3:
        content_hash = canonical_json_v3_sha256(value)
        return SealedArtifactRefV3(
            artifact_id=_artifact_id(run_id=run_id, kind=kind, content_hash=content_hash),
            kind=kind,
            schema_version=schema_version,
            content_hash=content_hash,
        )

    def _append_artifact(
        self,
        *,
        collection: dict[str, tuple[SealedArtifactRefV3, _ModelT]],
        run_id: str,
        kind: str,
        schema_version: str,
        value: _ModelT,
        expected_state_version: int,
    ) -> SealedArtifactRefV3:
        artifact = self._sealed_ref(
            run_id=run_id,
            kind=kind,
            schema_version=schema_version,
            value=value,
        )
        with self._lock:
            self._check_version(run_id, expected_state_version)
            if artifact.artifact_id in collection:
                raise InMemoryAppendError(f"{kind} Artifact was already appended")
            collection[artifact.artifact_id] = (artifact, _copy_model(value))
            self._advance(run_id)
        return artifact

    def _get_artifact(
        self,
        collection: dict[str, tuple[SealedArtifactRefV3, _ModelT]],
        artifact: SealedArtifactRefV3,
    ) -> _ModelT | None:
        with self._lock:
            stored = collection.get(artifact.artifact_id)
            if stored is None or stored[0] != artifact:
                return None
            return _copy_model(stored[1])


class InMemoryArtifactReadAdapter:
    """Append-only verified JSON Artifact adapter for isolated tests, never production use."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._artifacts: dict[str, VerifiedArtifactContentV3] = {}

    def append_verified_json(self, content: VerifiedArtifactContentV3) -> None:
        stored = _copy_model(content)
        with self._lock:
            if stored.artifact.artifact_id in self._artifacts:
                raise InMemoryAppendError("verified Actor Artifact was already appended")
            self._artifacts[stored.artifact.artifact_id] = stored

    def read_verified_json(
        self,
        *,
        run_id: Identifier,
        plan_version_id: Identifier,
        attempt_id: Identifier,
        step_number: int,
        artifact: SealedArtifactRefV3,
    ) -> VerifiedArtifactContentV3 | None:
        with self._lock:
            stored = self._artifacts.get(artifact.artifact_id)
            if stored is None:
                return None
            if (
                stored.run_id,
                stored.plan_version_id,
                stored.attempt_id,
                stored.step_number,
                stored.artifact,
            ) != (run_id, plan_version_id, attempt_id, step_number, artifact):
                return None
            return _copy_model(stored)
