"""Non-production research-v3 foundation contracts.

Importing this package does not register a route, Store codec, writer, Provider, or UI
branch. Production research-v2 remains the only reachable research writer.
"""

from agentmesh.research_orchestration.v3.canonical import (
    CANONICAL_JSON_V3_ALGORITHM,
    canonical_json_v3_bytes,
    canonical_json_v3_sha256,
    strict_json_v3_loads,
)
from agentmesh.research_orchestration.v3.catalog import CompetitiveTextCatalog, load_competitive_text_catalog
from agentmesh.research_orchestration.v3.deliverable import (
    CompetitiveAnalysisTextPayloadV1,
    FindingGraphV3,
    ResearchDeliverableV3,
)
from agentmesh.research_orchestration.v3.execution_plan import (
    ExecutionPlanV3,
    ExecutionPlanVersionV3,
    PlanCandidateSetV3,
    PlanCandidateV3,
)
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.report_document import ReportDocumentV3
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3, ResearchTaskV3
from agentmesh.research_orchestration.v3.review import ReportReviewV3
from agentmesh.research_orchestration.v3.schema_registry import V2_HISTORICAL_IDENTITIES, V3_GENERATION_IDENTITIES
from agentmesh.research_orchestration.v3.snapshots import ResearchControlSnapshotV3

__all__ = [
    "CANONICAL_JSON_V3_ALGORITHM",
    "CompetitiveAnalysisTextPayloadV1",
    "CompetitiveTextCatalog",
    "ExecutionPlanV3",
    "ExecutionPlanVersionV3",
    "FindingGraphV3",
    "PlanCandidateSetV3",
    "PlanCandidateV3",
    "ProblemGraphV1",
    "ReportDocumentV3",
    "ReportReviewV3",
    "RequirementVersionV3",
    "ResearchControlSnapshotV3",
    "ResearchDeliverableV3",
    "ResearchTaskV3",
    "V2_HISTORICAL_IDENTITIES",
    "V3_GENERATION_IDENTITIES",
    "canonical_json_v3_bytes",
    "canonical_json_v3_sha256",
    "load_competitive_text_catalog",
    "strict_json_v3_loads",
]
