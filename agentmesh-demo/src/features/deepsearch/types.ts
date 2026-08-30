import type { components } from '../../api/generated/schema'
import type { AgentRun } from '../workspace/types'

export type AgentPlanningMode = components['schemas']['AgentPlanningMode']
export type DeepSearchAvailability = components['schemas']['DeepSearchAvailability']

export type ClarificationAnswer = string | string[]
export type ClarificationAnswerKind = 'text' | 'single_choice' | 'multi_choice'

export interface DeepSearchClarificationQuestion {
  id: string
  prompt: string
  required: boolean
  answer_kind: ClarificationAnswerKind
  options: string[]
  max_length: number
  default_value?: ClarificationAnswer | null
}

export interface DeepSearchClarificationRound {
  round: number
  questions: DeepSearchClarificationQuestion[]
  answers: Record<string, ClarificationAnswer>
}

export interface DeepSearchRequirement {
  id: string
  run_id: string
  version: number
  schema_version: 'deepsearch-requirement-v1'
  content_hash: string
  payload: {
    goal: string
    scope: {
      objects: string[]
      regions: string[]
      time_range?: string | null
      audiences: string[]
      boundaries: string[]
    }
    constraints: Array<{
      kind: 'time' | 'cost' | 'source' | 'permission' | 'format'
      statement: string
    }>
    success_criteria: Array<{ id: string; statement: string }>
    deliverables: string[]
    assumptions: Array<{
      id: string
      statement: string
      source: string
      editable_before_plan: boolean
    }>
    ambiguities: Array<{ id: string; statement: string; blocking: boolean }>
    clarification_questions: DeepSearchClarificationQuestion[]
    clarification_history: DeepSearchClarificationRound[]
    clarification_round: number
  }
}

export interface DeepSearchProblemGraph {
  schema_version: 'deepsearch-problem-graph-v1'
  requirement_version_id: string
  content_hash: string
  questions: Array<{
    id: string
    question: string
    required: boolean
    success_criterion_ids: string[]
    evidence_requirements: string[]
    acceptance_criteria: string[]
    depends_on: string[]
  }>
}

export interface DeepSearchEvidenceCoverage {
  revision_count: number
  required_question_ids: string[]
  covered_question_ids: string[]
  uncovered_question_ids: string[]
  required_success_criterion_ids: string[]
  covered_success_criterion_ids: string[]
  uncovered_success_criterion_ids: string[]
  validated_claim_ids: string[]
  invalid_claim_ids: string[]
  validated_source_ids: string[]
  invalid_source_ids: string[]
  validated_node_result_ids: string[]
  invalid_node_result_ids: string[]
  external_evidence_is_real: boolean
  passed: boolean
  gap_codes: string[]
}

export interface DeepSearchReportReview {
  revision_count: number
  outcome: 'not_run' | 'pass' | 'revise' | 'block' | 'error'
  reason_code?: string | null
  unsupported_claim_ids: string[]
  contradictory_claim_ids: string[]
  missing_section_ids: string[]
  limitation_codes: string[]
}

export type DeepSearchFinalizationStage =
  | 'none'
  | 'nodes_terminal'
  | 'evidence_manifest_sealed'
  | 'synthesis_v0_saved'
  | 'coverage_v0_checked'
  | 'review_v0_checked'
  | 'synthesis_v1_saved'
  | 'coverage_v1_checked'
  | 'review_v1_checked'
  | 'terminal_committed'

export type DeepSearchPlanNode = components['schemas']['DeepSearchPlanNodeViewV1']
export type DeepSearchPlan = components['schemas']['DeepSearchPlanViewV1']

export interface DeepSearchState {
  run: AgentRun
  active_requirement: DeepSearchRequirement | null
  problem_graph: DeepSearchProblemGraph | null
  plan: DeepSearchPlan | null
  evidence_coverage: DeepSearchEvidenceCoverage | null
  report_review: DeepSearchReportReview | null
  scenario_assignment_options?: components['schemas']['DeepSearchStateResponse']['scenario_assignment_options']
  blocked_matches?: components['schemas']['DeepSearchStateResponse']['blocked_matches']
  capability_gap_details?: components['schemas']['DeepSearchStateResponse']['capability_gap_details']
  retry_disposition: 'retry_run' | 'revise_goal' | 'none'
}

export interface DeepSearchClarifyRequest {
  client_turn_id: string
  expected_requirement_version: number
  answers: Record<string, ClarificationAnswer>
}

export interface DeepSearchReportClaim {
  id: string
  text: string
  node_result_ids: string[]
  evidence_item_ids: string[]
  source_ids: string[]
  question_ids: string[]
  success_criterion_ids: string[]
  recommendation: boolean
}

export interface DeepSearchReport {
  schema_version: 'deepsearch-report-v1'
  run_id: string
  requirement_version_id: string
  plan_id: string
  plan_version: number
  review_outcome: 'not_run' | 'pass' | 'revise' | 'block' | 'error'
  review_reason_code?: string | null
  report_status: 'complete' | 'partial'
  title: string
  claims: DeepSearchReportClaim[]
  executive_summary_claim_ids: string[]
  sections: Array<{ section_id: string; server_heading: string; claim_ids: string[] }>
  sources: Array<{
    source_id: string
    title: string
    normalized_reference: string
    content_hash: string
  }>
  limitations: Array<{ code: string; related_ids: string[]; description: string }>
  rendered_text: string
}
