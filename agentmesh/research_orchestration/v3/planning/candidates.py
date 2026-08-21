from __future__ import annotations

from agentmesh.research_orchestration.v3.execution_plan import (
    CapabilityResolutionV3,
    DepthPlanCandidateV3,
    ExpectedOutputV3,
    PlanCandidateSetV3,
    PlanInputBindingV3,
    PlanStepProposalV3,
    SpeedPlanCandidateV3,
)
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.requirement import RequirementVersionV3


class CandidateGenerationError(ValueError):
    def __init__(self, *codes: str) -> None:
        self.codes = tuple(dict.fromkeys(codes))
        super().__init__(", ".join(self.codes))


def _eligible_decisions(capabilities: CapabilityResolutionV3) -> set[tuple[str, str]]:
    return {
        (decision.actor_type, decision.actor_id)
        for decision in capabilities.decisions
        if decision.status == "eligible"
    }


class CompetitiveTextCandidateGenerator:
    """Produces the ordered, bounded depth and speed proposals for Competitive Text."""

    async def generate(
        self,
        *,
        requirement: RequirementVersionV3,
        problem_graph: ProblemGraphV1,
        capabilities: CapabilityResolutionV3,
    ) -> PlanCandidateSetV3:
        if requirement.payload.planning_blocked:
            raise CandidateGenerationError("requirement_clarification_required")
        if problem_graph.requirement_version_id != requirement.id:
            raise CandidateGenerationError("problem_graph_requirement_mismatch")
        required_gaps = tuple(item.code for item in capabilities.gaps if item.required)
        if required_gaps:
            raise CandidateGenerationError(*required_gaps)
        eligible = _eligible_decisions(capabilities)
        required_decisions = {
            ("tool", "tavily-web-search"),
            ("skill", "competitive-web-research"),
            ("skill", "competitive-analysis"),
        }
        missing = sorted(required_decisions - eligible)
        if missing:
            raise CandidateGenerationError(*(f"actor_not_eligible:{kind}:{actor_id}" for kind, actor_id in missing))
        required_questions = tuple(
            question.id for question in problem_graph.questions if question.priority == "required"
        )
        if not required_questions:
            raise CandidateGenerationError("required_problem_questions_missing")
        query = " ".join((*requirement.payload.scope, requirement.payload.research_goal)).strip()
        assumptions = requirement.payload.assumptions

        search = PlanStepProposalV3(
            proposed_step_number=2,
            name="Collect public competitive evidence",
            actor_type="tool",
            actor_id="tavily-web-search",
            question_ids=required_questions,
            depends_on=(),
            input={"query": query, "max_results": 12, "search_depth": "advanced"},
            input_bindings=(),
            expected_outputs=(
                ExpectedOutputV3(pointer="/results", description="Public-source search results."),
            ),
            acceptance_criteria=("Return public URLs and source snippets for every required question.",),
            requires_approval=True,
            approval_role="owner",
        )
        web_research = PlanStepProposalV3(
            proposed_step_number=4,
            name="Organize web research evidence",
            actor_type="skill",
            actor_id="competitive-web-research",
            question_ids=required_questions,
            depends_on=(2,),
            input={"evidence": None, "research_goal": requirement.payload.research_goal},
            input_bindings=(
                PlanInputBindingV3(
                    source_step_number=2,
                    source_pointer="/results",
                    target_pointer="/evidence",
                ),
            ),
            expected_outputs=(
                ExpectedOutputV3(pointer="/payload", description="Organized public research payload."),
            ),
            acceptance_criteria=("Separate observed public facts from analysis and inference.",),
            requires_approval=False,
        )
        depth_analysis = PlanStepProposalV3(
            proposed_step_number=6,
            name="Apply the competitive analysis method",
            actor_type="skill",
            actor_id="competitive-analysis",
            question_ids=required_questions,
            depends_on=(4,),
            input={"evidence": None, "dimensions": requirement.payload.comparison_dimensions or ()},
            input_bindings=(
                PlanInputBindingV3(
                    source_step_number=4,
                    source_pointer="/payload",
                    target_pointer="/evidence",
                ),
            ),
            expected_outputs=(
                ExpectedOutputV3(pointer="/payload", description="Traceable competitive analysis payload."),
            ),
            acceptance_criteria=("Cover each required question and preserve evidence references.",),
            requires_approval=False,
        )
        depth_synthesis = PlanStepProposalV3(
            proposed_step_number=8,
            name="Synthesize the Competitive Text narrative",
            actor_type="llm",
            actor_id="competitive-text-synthesis-v1",
            question_ids=required_questions,
            depends_on=(6,),
            input={"analysis": None},
            input_bindings=(
                PlanInputBindingV3(
                    source_step_number=6,
                    source_pointer="/payload",
                    target_pointer="/analysis",
                ),
            ),
            expected_outputs=(
                ExpectedOutputV3(pointer="/text", description="Evidence-backed text synthesis."),
            ),
            acceptance_criteria=("Do not present inference as public fact.",),
            requires_approval=False,
        )

        speed_analysis = depth_analysis.model_copy(
            update={
                "proposed_step_number": 4,
                "name": "Analyze the minimum public evidence set",
                "depends_on": (2,),
                "input_bindings": (
                    PlanInputBindingV3(
                        source_step_number=2,
                        source_pointer="/results",
                        target_pointer="/evidence",
                    ),
                ),
            }
        )
        speed_synthesis = depth_synthesis.model_copy(
            update={
                "proposed_step_number": 6,
                "depends_on": (4,),
                "input_bindings": (
                    PlanInputBindingV3(
                        source_step_number=4,
                        source_pointer="/payload",
                        target_pointer="/analysis",
                    ),
                ),
            }
        )
        return PlanCandidateSetV3(
            schema_version="plan-candidates-v3",
            candidates=(
                DepthPlanCandidateV3(
                    candidate_id="depth",
                    title="Depth",
                    rationale="Use an explicit research organization stage before method analysis and synthesis.",
                    tradeoffs="More complete organization with one additional model-backed Skill step.",
                    assumptions=assumptions,
                    proposed_steps=(search, web_research, depth_analysis, depth_synthesis),
                ),
                SpeedPlanCandidateV3(
                    candidate_id="speed",
                    title="Speed",
                    rationale="Use the shortest evidence-to-analysis-to-synthesis path.",
                    tradeoffs="Less intermediate organization and therefore less diagnostic detail.",
                    assumptions=assumptions,
                    proposed_steps=(search, speed_analysis, speed_synthesis),
                ),
            ),
        )
