"""Isolated Competitive Text planning implementations.

This package implements the frozen research-v3 planning ports without wiring them to
production routes, persistence, or Provider adapters.
"""

from agentmesh.research_orchestration.v3.planning.capabilities import CompetitiveTextCapabilityResolver
from agentmesh.research_orchestration.v3.planning.candidates import CompetitiveTextCandidateGenerator
from agentmesh.research_orchestration.v3.planning.compiler import CompetitiveTextCandidateCompiler
from agentmesh.research_orchestration.v3.planning.facade import CompetitiveTextPlanningFacade
from agentmesh.research_orchestration.v3.planning.models import (
    ActorRuntimeDescriptorV3,
    CapabilityResolutionResultV3,
    CompetitiveTextPlanningBundleV3,
    PlanningModelCallReceiptV3,
    ProblemGraphPlanningResultV3,
    RequirementPlanningResultV3,
)
from agentmesh.research_orchestration.v3.planning.problem_graphs import (
    CompetitiveTextProblemGraphPlanner,
    DeterministicProblemGraphProposalFake,
)
from agentmesh.research_orchestration.v3.planning.requirements import (
    CompetitiveTextRequirementPlanner,
    DeterministicRequirementProposalFake,
)

__all__ = [
    "ActorRuntimeDescriptorV3",
    "CapabilityResolutionResultV3",
    "CompetitiveTextCandidateCompiler",
    "CompetitiveTextCandidateGenerator",
    "CompetitiveTextCapabilityResolver",
    "CompetitiveTextPlanningBundleV3",
    "CompetitiveTextPlanningFacade",
    "CompetitiveTextProblemGraphPlanner",
    "CompetitiveTextRequirementPlanner",
    "DeterministicProblemGraphProposalFake",
    "DeterministicRequirementProposalFake",
    "PlanningModelCallReceiptV3",
    "ProblemGraphPlanningResultV3",
    "RequirementPlanningResultV3",
]
