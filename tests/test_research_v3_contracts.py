from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from inspect import signature
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentmesh.research_orchestration.v3.canonical import (
    canonical_json_v3_bytes,
    canonical_json_v3_sha256,
    strict_json_v3_loads,
)
from agentmesh.research_orchestration.v3.common import FrozenJsonObject
from agentmesh.research_orchestration.v3.deliverable import ResearchDeliverableV3
from agentmesh.research_orchestration.v3.execution_plan import (
    ExecutionPlanV3,
    ExecutionPlanVersionV3,
    PlanCandidateSetV3,
)
from agentmesh.research_orchestration.v3.ports import ActorExecutionRequestV3, CandidateCompilerPort
from agentmesh.research_orchestration.v3.problem_graph import (
    EvidenceRequirementV1,
    ProblemGraphV1,
    validate_problem_graph_for_task,
)
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3, ResearchTaskV3
from agentmesh.research_orchestration.v3.review import ReportReviewV3
from agentmesh.research_orchestration.v3.schema_registry import (
    SOURCE_ONLY_IDENTITIES,
    V2_HISTORICAL_IDENTITIES,
    V3_CURRENT_IDENTITIES,
    V3_GENERATION_IDENTITIES,
    V3_PERSISTED_RESOURCE_IDENTITIES,
    V3_PERSISTED_SCHEMA_IDENTITIES,
    V3_SUPPORTING_SCHEMA_IDENTITIES,
    V3_TARGET_REGISTRY,
    V3_WEB_SCHEMA_IDENTITIES,
    decode_plan,
    decode_requirement,
)
from agentmesh.research_orchestration.v3.snapshots import FrozenDocumentV3
from research_v3_contract_samples import (
    candidate_set_body,
    deliverable_body,
    plan_body,
    problem_graph_body,
    report_body,
    requirement_body,
    requirement_envelope,
    review_body,
)


def test_canonical_json_v3_preserves_json_numbers_without_changing_v2() -> None:
    value = {"z": Decimal("1.2300"), "negative_zero": Decimal("-0"), "nested": [2, Decimal("1E+3")]}
    assert canonical_json_v3_bytes(value) == b'{"negative_zero":0,"nested":[2,1000],"z":1.23}'
    assert canonical_json_v3_sha256(value) == canonical_json_v3_sha256(strict_json_v3_loads(canonical_json_v3_bytes(value)))
    with pytest.raises(TypeError, match="binary floating point"):
        canonical_json_v3_bytes({"score": 0.5})
    with pytest.raises(ValueError, match="duplicate normalized keys"):
        strict_json_v3_loads('{"e\u0301": 1, "é": 2}')


def test_requirement_and_problem_graph_are_typed_immutable_and_covered() -> None:
    task = ResearchTaskV3.model_validate(requirement_body())
    envelope = RequirementVersionV3.model_validate(requirement_envelope())
    graph = ProblemGraphV1.model_validate(problem_graph_body())
    policy = EvidenceRequirementV1(
        id="competitive-analysis-report",
        accepted_classes=("public_source",),
        minimum_count=1,
        required=True,
    )
    validate_problem_graph_for_task(graph, task, policy_requirements=(policy,))
    assert isinstance(task.scope, tuple)
    assert envelope.payload == task
    with pytest.raises(ValidationError, match="frozen"):
        task.research_goal = "mutated"  # type: ignore[misc]


def test_version_first_decoders_reject_cross_generation_or_discriminator_mismatch() -> None:
    requirement = requirement_envelope()
    assert decode_requirement(
        orchestration_version="research-v3",
        schema_version="research-task-v3",
        payload=requirement,
    ).id == "requirement_1"
    with pytest.raises(ValueError, match="unregistered"):
        decode_requirement(
            orchestration_version="research-v2",
            schema_version="research-task-v3",
            payload=requirement,
        )
    mismatched = deepcopy(requirement)
    mismatched["payload"]["schema_version"] = "research-task-v2"
    with pytest.raises(ValueError, match="must agree"):
        decode_requirement(
            orchestration_version="research-v3",
            schema_version="research-task-v3",
            payload=mismatched,
        )

    body_model = ExecutionPlanV3.model_validate(plan_body())
    body = body_model.model_dump(mode="python")
    plan = {
        "id": "plan_1",
        "run_id": "run_1",
        "requirement_version_id": "requirement_1",
        "version": 1,
        "schema_version": "execution-plan-v3",
        "plan_hash": canonical_json_v3_sha256(body),
        "payload": body,
        "created_at": "2026-08-21T00:00:00Z",
    }
    assert isinstance(
        decode_plan(
            orchestration_version="research-v3",
            schema_version="execution-plan-v3",
            payload=plan,
        ),
        ExecutionPlanVersionV3,
    )


def test_all_requested_target_discriminators_validate() -> None:
    assert ExecutionPlanV3.model_validate(plan_body()).schema_version == "execution-plan-v3"
    assert ResearchDeliverableV3.model_validate(deliverable_body()).schema_version == "research-deliverable-v3"
    assert ReportReviewV3.model_validate(review_body()).schema_version == "report-review-v3"
    assert ReportDocumentV3.model_validate(report_body()).schema_version == "report-document-v3"


def test_v2_identifiers_remain_disjoint_and_no_source_alias_is_registered() -> None:
    assert V2_HISTORICAL_IDENTITIES.isdisjoint(V3_CURRENT_IDENTITIES)
    assert V2_HISTORICAL_IDENTITIES.isdisjoint(V3_PERSISTED_RESOURCE_IDENTITIES)
    assert SOURCE_ONLY_IDENTITIES.isdisjoint(V3_CURRENT_IDENTITIES)
    assert {key[2] for key in V3_TARGET_REGISTRY}.isdisjoint(SOURCE_ONLY_IDENTITIES)
    assert len(V2_HISTORICAL_IDENTITIES) == 13
    assert V3_GENERATION_IDENTITIES == {
        "research-v3",
        "research-task-v3",
        "execution-plan-v3",
        "research-deliverable-v3",
        "report-review-v3",
        "report-document-v3",
    }
    assert V3_SUPPORTING_SCHEMA_IDENTITIES == {
        "problem-graph-v1",
        "plan-candidates-v3",
        "research-control-snapshot-v3",
        "competitive-analysis-text-v1",
        "evidence-manifest-v3",
    }
    assert V3_PERSISTED_SCHEMA_IDENTITIES == (
        (V3_GENERATION_IDENTITIES - {"research-v3"}) | V3_SUPPORTING_SCHEMA_IDENTITIES
    )
    assert V3_PERSISTED_RESOURCE_IDENTITIES == V3_CURRENT_IDENTITIES
    assert V3_WEB_SCHEMA_IDENTITIES == {"research-workbench-aggregate-v1"}
    assert V3_WEB_SCHEMA_IDENTITIES.isdisjoint(V3_PERSISTED_RESOURCE_IDENTITIES)


def test_canonical_json_fields_are_transitively_immutable_and_defensively_serialized() -> None:
    plan = ExecutionPlanV3.model_validate(plan_body())
    plan_hash = canonical_json_v3_sha256(plan)
    assert isinstance(plan.steps[0].input, FrozenJsonObject)
    with pytest.raises(TypeError):
        plan.steps[0].input["query"] = "mutated"  # type: ignore[index]
    assert canonical_json_v3_sha256(plan) == plan_hash

    candidate_input = candidate_set_body()
    candidate = PlanCandidateSetV3.model_validate(candidate_input)
    candidate_input["candidates"][0]["proposed_steps"][0]["input"]["filters"][0]["language"] = "zh"
    assert candidate.candidates[0].proposed_steps[0].input["filters"][0]["language"] == "en"
    with pytest.raises(TypeError):
        candidate.candidates[0].proposed_steps[0].input["filters"][0]["language"] = "fr"  # type: ignore[index]

    request = ActorExecutionRequestV3(
        run_id="run_1",
        plan_version_id="plan_1",
        attempt_id="attempt_1",
        step=plan.steps[0],
        resolved_input={"nested": [{"value": "sealed"}]},
    )
    with pytest.raises(TypeError):
        request.resolved_input["nested"][0]["value"] = "changed"  # type: ignore[index]
    dumped = request.model_dump(mode="json")
    dumped["resolved_input"]["nested"][0]["value"] = "boundary-copy"
    assert request.resolved_input["nested"][0]["value"] == "sealed"


def test_frozen_document_recomputes_content_hash_and_rejects_nested_mutation() -> None:
    source_content = {"schema": {"required": ["query"]}}
    content_bytes = canonical_json_v3_bytes(source_content)
    document = FrozenDocumentV3(
        document_id="schema_search",
        kind="json_schema",
        media_type="application/json",
        content_hash=canonical_json_v3_sha256(source_content),
        size_bytes=len(content_bytes),
        content=source_content,
    )
    source_content["schema"]["required"].append("limit")
    with pytest.raises(TypeError):
        document.content["schema"]["required"][0] = "changed"  # type: ignore[index]
    assert canonical_json_v3_sha256(document.content) == document.content_hash
    assert document.content["schema"]["required"] == ("query",)

    with pytest.raises(ValidationError, match="content_hash"):
        FrozenDocumentV3(
            document_id="schema_search",
            kind="json_schema",
            media_type="application/json",
            content_hash="0" * 64,
            size_bytes=len(content_bytes),
            content={"schema": {"required": ["query"]}},
        )


def test_candidate_compiler_requires_the_sealed_problem_graph_reference() -> None:
    parameters = signature(CandidateCompilerPort.compile).parameters
    assert tuple(parameters).index("problem_graph_artifact") == tuple(parameters).index("problem_graph") + 1


def test_foundation_does_not_make_research_v3_reachable() -> None:
    production_files = (
        "agentmesh/models.py",
        "agentmesh/store.py",
        "agentmesh/app.py",
        "agentmesh/routes/agent_runs.py",
        "agentmesh/routes/research.py",
        "agentmesh/research_orchestration/__init__.py",
    )
    for filename in production_files:
        assert "research-v3" not in Path(filename).read_text(encoding="utf-8"), filename
