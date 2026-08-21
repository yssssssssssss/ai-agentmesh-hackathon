from __future__ import annotations

from collections.abc import Mapping

from agentmesh.research_orchestration.v3.catalog import (
    CompetitiveTextCatalog,
    load_catalog_document,
    load_competitive_text_catalog,
)
from agentmesh.research_orchestration.v3.problem_graph import (
    EvidenceRequirementV1,
    ProblemGraphV1,
    validate_problem_graph_for_task,
)
from agentmesh.research_orchestration.v3.requirement import ResearchTaskV3


def competitive_text_evidence_requirements(
    catalog: CompetitiveTextCatalog,
) -> tuple[EvidenceRequirementV1, ...]:
    verified_catalog = load_competitive_text_catalog()
    if catalog != verified_catalog:
        raise ValueError("Competitive Text planning requires the verified frozen catalog")
    deliverable = catalog.deliverables[0]
    document = load_catalog_document(catalog, deliverable.evidence_policy)
    if not isinstance(document, Mapping):
        raise ValueError("Competitive Text evidence policy must be an object")
    if (
        document.get("schema_version") != "evidence-policy-v3"
        or document.get("task_type") != "competitive_research"
        or document.get("deliverable_type") != "competitive_analysis_report"
    ):
        raise ValueError("Competitive Text evidence policy identity does not match the catalog")
    raw_requirements = document.get("requirements")
    if not isinstance(raw_requirements, list):
        raise ValueError("Competitive Text evidence policy requirements are missing")
    requirements = tuple(EvidenceRequirementV1.model_validate(item) for item in raw_requirements)
    if not requirements or any(item.accepted_classes != ("public_source",) for item in requirements):
        raise ValueError("Competitive Text policy must require public_source evidence")
    return requirements


def validate_competitive_problem_graph(
    graph: ProblemGraphV1,
    task: ResearchTaskV3,
    catalog: CompetitiveTextCatalog,
) -> tuple[EvidenceRequirementV1, ...]:
    policy = competitive_text_evidence_requirements(catalog)
    validate_problem_graph_for_task(graph, task, policy_requirements=policy)
    policy_by_id = {item.id: item for item in policy}
    for question in graph.questions:
        for requirement in question.evidence_requirements:
            expected = policy_by_id.get(requirement.id)
            if expected is None:
                raise ValueError("ProblemGraph contains evidence outside the frozen Competitive Text policy")
            if requirement.accepted_classes != expected.accepted_classes:
                raise ValueError("ProblemGraph evidence classes differ from the frozen Competitive Text policy")
            if requirement.minimum_count < expected.minimum_count:
                raise ValueError("ProblemGraph evidence minimum is below the frozen Competitive Text policy")
        if question.priority == "required":
            required_ids = {
                item.id
                for item in question.evidence_requirements
                if item.required
            }
            if required_ids != set(policy_by_id):
                raise ValueError("every required ProblemGraph question must apply the complete evidence policy")
    return policy
