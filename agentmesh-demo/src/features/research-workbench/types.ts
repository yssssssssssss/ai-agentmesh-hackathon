// Feature-local projection types mirror the frozen research-workbench-aggregate-v1 schema.
// They intentionally do not depend on generated production API types: research-v3 is not routed in production.

export type WorkbenchState =
  | 'idle'
  | 'clarify'
  | 'candidates'
  | 'plan'
  | 'approval'
  | 'dag_or_executing'
  | 'paused'
  | 'text_report'

export type ActorType = 'tool' | 'skill' | 'llm' | 'reviewer'
export type StepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'
export type ApprovalRole = 'owner' | 'legal' | 'security'

export interface WorkbenchProjectionProvenance {
  baseline_state_id: WorkbenchState | string
  projected_at: string
  projection_schema_version: 'research-workbench-aggregate-v1'
  source_kind: 'isolated_fixture' | 'v2_history_adapter'
  source_state_version: number
}

export interface WorkbenchWorkflow {
  state: WorkbenchState
  state_version: number
  gate: {
    kind: 'none' | 'clarification' | 'candidate_selection' | 'plan_confirmation' | 'role_approval' | 'recovery'
    status: 'inactive' | 'pending' | 'satisfied' | 'blocked'
    required_role: ApprovalRole | null
  }
}

export interface ResearchAssumption {
  key: string
  value: string
  editable: boolean
}

export interface ResearchTaskV3 {
  schema_version: 'research-task-v3'
  task_type: 'competitive_research'
  business_domain: string
  research_goal: string
  target_audience: string[]
  scope: string[]
  comparison_dimensions: string[] | null
  constraints: Array<{ id: string; statement: string; source: string }>
  success_criteria: Array<{ id: string; statement: string }>
  expected_deliverables: string[]
  assumptions: ResearchAssumption[]
  ambiguities: Array<{ id: string; statement: string; blocking: boolean }>
  clarification_questions: Array<{ key: string; question: string; rationale: string }>
  blocking_issues: Array<{ key: string; reason: string; kind: string }>
  sensitivity: 'public' | 'internal' | 'confidential'
  pii_detected: boolean
}

export interface RequirementVersionV3 {
  id: string
  run_id: string
  version: number
  schema_version: 'research-task-v3'
  task_type: 'competitive_research'
  payload: ResearchTaskV3
  content_hash: string
  created_at: string
}

export interface ExpectedOutputV3 {
  pointer: string
  description: string
}

export interface PlanStepProposalV3 {
  proposed_step_number: number
  name: string
  actor_type: ActorType
  actor_id: string
  question_ids: string[]
  depends_on: number[]
  input: Record<string, unknown>
  input_bindings: Array<{
    source_step_number: number
    source_pointer: string
    target_pointer: string
  }>
  expected_outputs: ExpectedOutputV3[]
  acceptance_criteria: string[]
  requires_approval: boolean
  approval_role: ApprovalRole | null
}

export interface PlanCandidateV3 {
  candidate_id: 'depth' | 'speed'
  title: string
  rationale: string
  tradeoffs: string
  assumptions: ResearchAssumption[]
  proposed_steps: PlanStepProposalV3[]
}

export interface PlanCandidateSetV3 {
  schema_version: 'plan-candidates-v3'
  candidates: [PlanCandidateV3, PlanCandidateV3]
}

export interface CapabilityGapV3 {
  capability_type: ActorType
  capability_id: string
  code: string
  message: string
  required: boolean
}

export interface PlanStepV3 {
  step_number: number
  name: string
  actor_type: ActorType
  actor_id: string
  question_ids: string[]
  depends_on: number[]
  expected_outputs: ExpectedOutputV3[]
  acceptance_criteria: string[]
  required: boolean
  requires_approval: boolean
  approval_role: ApprovalRole | null
  timeout_seconds: number
}

export interface ExecutionPlanVersionV3 {
  id: string
  run_id: string
  requirement_version_id: string
  version: number
  schema_version: 'execution-plan-v3'
  plan_hash: string
  created_at: string
  payload: {
    schema_version: 'execution-plan-v3'
    task_type: 'competitive_research'
    requirement_version_id: string
    candidate_id: 'depth' | 'speed'
    candidate_title: string
    candidate_rationale: string
    candidate_tradeoffs: string
    deliverable_type: 'competitive_analysis_report'
    payload_schema_version: 'competitive-analysis-text-v1'
    activated_nodes: string[]
    capability_gaps: CapabilityGapV3[]
    steps: PlanStepV3[]
  }
}

export interface WorkbenchApprovalV1 {
  gate_key: string
  plan_version_id: string
  role: ApprovalRole
  decision: 'pending' | 'approved' | 'rejected'
  receipt_id: string | null
}

export interface WorkbenchStepV1 {
  step_number: number
  actor_type: ActorType
  actor_id: string
  step_contract_hash: string
  expected_outputs: ExpectedOutputV3[]
  status: StepStatus
  failure_code: string | null
  // The aggregate exposes only a sealed result reference. Renderers must not expose it.
  result: unknown | null
}

export interface WorkbenchAttemptV1 {
  attempt_id: string
  run_id: string
  plan_version_id: string
  status: 'running' | 'paused' | 'completed'
  steps: WorkbenchStepV1[]
}

export interface WorkbenchRecoveryV1 {
  failed_step_number: number
  reason_code: string
  allowed_actions: Array<'retry' | 'skip' | 'abort'>
  decision_required: true
}

export interface WorkbenchEvidenceItemV1 {
  evidence_id: string
  source_id: string
  title: string
  url: string
  quote: string
  gap_metadata: {
    redaction: 'none' | 'masked'
    truncated: boolean
    conflict_status: 'none' | 'corroborated' | 'conflicting'
    risk_flags: string[]
  }
  provenance: {
    source_kind: 'public_web'
    retrieved_at: string
    registrable_domain: string
    independence_group: string
    actor_type: 'tool'
    actor_id: string
    step_number: number
  }
}

export interface WorkbenchEvidenceV1 {
  presentation_mode: 'text'
  run_id: string
  plan_version_id: string
  attempt_id: string
  evidence: WorkbenchEvidenceItemV1[]
}

export interface ReportParagraphBlockV3 {
  id: string
  type: 'paragraph'
  text: string
}

export interface ReportFactBlockV3 {
  id: string
  type: 'fact'
  text: string
  evidence_ids: string[]
}

export interface ReportMetricBlockV3 {
  id: string
  type: 'metric'
  label: string
  value: number
  evidence_ids: string[]
}

export interface ReportListBlockV3 {
  id: string
  type: 'list'
  items: string[]
}

export type ReportBlockV3 =
  | ReportParagraphBlockV3
  | ReportFactBlockV3
  | ReportMetricBlockV3
  | ReportListBlockV3

export interface ReportDocumentV3 {
  schema_version: 'report-document-v3'
  presentation_mode: 'text'
  review_verdict: 'pass'
  run_id: string
  requirement_version_id: string
  plan_version_id: string
  attempt_id: string
  title: string
  subtitle: string
  executive_summary: string
  sections: Array<{
    id: string
    title: string
    question_ids: string[]
    blocks: ReportBlockV3[]
  }>
}

export interface ResearchDeliverableV3 {
  method_summary: string
  risks_and_open_issues: string[]
  recommendations: Array<{
    id: string
    statement: string
    priority: 'P0' | 'P1' | 'P2' | 'P3'
    finding_ids: string[]
  }>
}

export interface ResearchV3WorkbenchAggregateV1 {
  schema_version: 'research-workbench-aggregate-v1'
  projection_kind: 'research-v3-current'
  orchestration_version: 'research-v3'
  run_id: string
  workflow: WorkbenchWorkflow
  requirement: RequirementVersionV3 | null
  candidates: PlanCandidateSetV3 | null
  selected_plan: ExecutionPlanVersionV3 | null
  approvals: WorkbenchApprovalV1[]
  attempt: WorkbenchAttemptV1 | null
  recovery: WorkbenchRecoveryV1 | null
  evidence: (WorkbenchEvidenceV1 & { artifact?: unknown }) | null
  deliverable: ({ content: ResearchDeliverableV3; artifact?: unknown }) | null
  review: ({ content: { verdict: 'pass' | 'revise' | 'block' }; artifact?: unknown }) | null
  report: ({ content: ReportDocumentV3; artifact?: unknown }) | null
  provenance: WorkbenchProjectionProvenance
}

export interface ResearchV2HistoryWorkbenchAggregateV1 {
  schema_version: 'research-workbench-aggregate-v1'
  projection_kind: 'research-v2-history'
  orchestration_version: 'research-v2'
  read_only: true
  run_id: string
  history_payload: Record<string, unknown>
  provenance: WorkbenchProjectionProvenance
}

export type WorkbenchAggregateV1 = ResearchV3WorkbenchAggregateV1 | ResearchV2HistoryWorkbenchAggregateV1

export interface ResearchWorkbenchActions {
  onSuggestion?: (suggestion: string) => void
  onClarificationSubmit?: (answers: Readonly<Record<string, string>>) => void
  onCandidateSelect?: (candidateId: 'depth' | 'speed') => void
  onPlanConfirm?: () => void
  onPlanRevise?: () => void
  onApprove?: (gateKey: string) => void
  onExecute?: () => void
  onRecoveryAction?: (action: 'retry' | 'skip' | 'abort') => void
  onRetryLoad?: () => void
}
