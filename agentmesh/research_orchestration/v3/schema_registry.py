from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel

from agentmesh.research_orchestration.v3.deliverable import ResearchDeliverableV3
from agentmesh.research_orchestration.v3.execution_plan import ExecutionPlanVersionV3
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3
from agentmesh.research_orchestration.v3.review import ReportReviewV3

V2_HISTORICAL_IDENTITIES = frozenset(
    {
        "research-v2",
        "claim-ledger-v1",
        "competitive-analysis-output-v1",
        "competitive-analysis-review-v1",
        "deliverable-document-v1",
        "deterministic-review-v1",
        "evidence-manifest-v1",
        "evidence-policy-v1",
        "evidence-source-v1",
        "execution-plan-v2",
        "problem-contract-v1",
        "report-document-v1",
        "research-task-v2",
    }
)
V3_GENERATION_IDENTITIES = frozenset(
    {
        "research-v3",
        "research-task-v3",
        "execution-plan-v3",
        "research-deliverable-v3",
        "report-review-v3",
        "report-document-v3",
    }
)
SOURCE_ONLY_IDENTITIES = frozenset(
    {
        "research-task-v2",
        "current-execution-plan",
        "research-deliverable-v1",
        "report-review-v1",
        "report-document-v1",
    }
)
assert V2_HISTORICAL_IDENTITIES.isdisjoint(V3_GENERATION_IDENTITIES)
assert SOURCE_ONLY_IDENTITIES.isdisjoint(V3_GENERATION_IDENTITIES)

V3_TARGET_REGISTRY: dict[tuple[str, str, str], type[BaseModel]] = {
    ("research-v3", "requirement", "research-task-v3"): RequirementVersionV3,
    ("research-v3", "plan", "execution-plan-v3"): ExecutionPlanVersionV3,
    ("research-v3", "deliverable", "research-deliverable-v3"): ResearchDeliverableV3,
    ("research-v3", "review", "report-review-v3"): ReportReviewV3,
    ("research-v3", "report", "report-document-v3"): ReportDocumentV3,
}

ArtifactRole = Literal["deliverable", "review", "report"]


def _decode(
    *,
    orchestration_version: str,
    role: str,
    schema_version: str,
    payload: Mapping[str, Any],
) -> BaseModel:
    key = (orchestration_version, role, schema_version)
    model_type = V3_TARGET_REGISTRY.get(key)
    if model_type is None:
        raise ValueError(f"unregistered research-v3 contract identity: {key!r}")
    body_discriminator = payload.get("schema_version")
    if role in {"requirement", "plan"}:
        nested = payload.get("payload")
        if not isinstance(nested, Mapping):
            raise ValueError(f"{role} envelope requires a typed payload")
        body_discriminator = nested.get("schema_version")
    if payload.get("schema_version") != schema_version or body_discriminator != schema_version:
        raise ValueError("registry, envelope, and body schema discriminators must agree")
    return model_type.model_validate(payload)


def decode_requirement(
    *,
    orchestration_version: str,
    schema_version: str,
    payload: Mapping[str, Any],
) -> RequirementVersionV3:
    decoded = _decode(
        orchestration_version=orchestration_version,
        role="requirement",
        schema_version=schema_version,
        payload=payload,
    )
    if not isinstance(decoded, RequirementVersionV3):
        raise TypeError("requirement registry returned an unexpected model")
    return decoded


def decode_plan(
    *,
    orchestration_version: str,
    schema_version: str,
    payload: Mapping[str, Any],
) -> ExecutionPlanVersionV3:
    decoded = _decode(
        orchestration_version=orchestration_version,
        role="plan",
        schema_version=schema_version,
        payload=payload,
    )
    if not isinstance(decoded, ExecutionPlanVersionV3):
        raise TypeError("plan registry returned an unexpected model")
    return decoded


def decode_artifact(
    *,
    orchestration_version: str,
    role: ArtifactRole,
    schema_version: str,
    payload: Mapping[str, Any],
) -> ResearchDeliverableV3 | ReportReviewV3 | ReportDocumentV3:
    decoded = _decode(
        orchestration_version=orchestration_version,
        role=role,
        schema_version=schema_version,
        payload=payload,
    )
    if not isinstance(decoded, (ResearchDeliverableV3, ReportReviewV3, ReportDocumentV3)):
        raise TypeError("artifact registry returned an unexpected model")
    return decoded
