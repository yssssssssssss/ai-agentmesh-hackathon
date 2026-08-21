// Feature-local canonical validation shapes and the distinct render projection consumed by the
// isolated workbench. The canonical shapes are never exposed to React: unknown input is validated
// against the frozen schema and semantic invariants before canonical identities are stripped.

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

interface WorkbenchProjectionProvenanceBase {
  baseline_state_id: WorkbenchState | null
  projected_at: string
  projection_schema_version: 'research-workbench-aggregate-v1'
  source_state_version: number
}

export interface IsolatedFixtureProvenance extends WorkbenchProjectionProvenanceBase {
  source_kind: 'isolated_fixture'
  baseline_state_id: WorkbenchState
}

export interface RepositoryProjectionProvenance extends WorkbenchProjectionProvenanceBase {
  source_kind: 'repository_projection'
  baseline_state_id: null
}

export interface V2HistoryAdapterProvenance extends WorkbenchProjectionProvenanceBase {
  source_kind: 'v2_history_adapter'
  baseline_state_id: null
}

export type CurrentWorkbenchProjectionProvenance =
  | IsolatedFixtureProvenance
  | RepositoryProjectionProvenance
export type WorkbenchProjectionProvenance =
  | CurrentWorkbenchProjectionProvenance
  | V2HistoryAdapterProvenance

export interface WorkbenchGateByState {
  idle: { kind: 'none'; status: 'inactive'; required_role: null }
  clarify: { kind: 'clarification'; status: 'pending' | 'blocked'; required_role: null }
  candidates: { kind: 'candidate_selection'; status: 'pending' | 'blocked'; required_role: null }
  plan: { kind: 'plan_confirmation'; status: 'pending' | 'satisfied' | 'blocked'; required_role: null }
  approval: { kind: 'role_approval'; status: 'pending'; required_role: ApprovalRole }
  dag_or_executing: { kind: 'none'; status: 'inactive'; required_role: null }
  paused: { kind: 'recovery'; status: 'blocked'; required_role: null }
  text_report: { kind: 'none'; status: 'inactive'; required_role: null }
}

export type WorkbenchWorkflow<S extends WorkbenchState = WorkbenchState> = S extends WorkbenchState ? {
  state: S
  state_version: number
  gate: WorkbenchGateByState[S]
} : never

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

interface PlanCandidateV3Base {
  title: string
  rationale: string
  tradeoffs: string
  assumptions: ResearchAssumption[]
  proposed_steps: PlanStepProposalV3[]
}

export interface DepthPlanCandidateV3 extends PlanCandidateV3Base {
  candidate_id: 'depth'
}

export interface SpeedPlanCandidateV3 extends PlanCandidateV3Base {
  candidate_id: 'speed'
}

export type PlanCandidateV3 = DepthPlanCandidateV3 | SpeedPlanCandidateV3

export interface PlanCandidateSetV3 {
  schema_version: 'plan-candidates-v3'
  candidates: [DepthPlanCandidateV3, SpeedPlanCandidateV3]
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
  contract_hash: string
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
    requirement_content_hash: string
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

export interface SealedArtifactRefV3 {
  artifact_id: string
  content_hash: string
  kind: string
  schema_version: string
}

export interface ActorExecutionResultV3 {
  result_artifact: SealedArtifactRefV3
  run_id: string
  plan_version_id: string
  attempt_id: string
  step_number: number
  actor_type: ActorType
  actor_id: string
  step_contract_hash: string
  receipt_id: string
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
  result: ActorExecutionResultV3 | null
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
    artifact: SealedArtifactRefV3
    run_id: string
    plan_version_id: string
    attempt_id: string
    actor_type: 'tool'
    actor_id: string
    step_number: number
    step_contract_hash: string
    receipt_id: string
  }
}

export interface WorkbenchEvidenceV1 {
  artifact: SealedArtifactRefV3
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
  deliverable_artifact: SealedArtifactRefV3
  review_artifact: SealedArtifactRefV3
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
  run_id: string
  requirement_version_id: string
  plan_version_id: string
  attempt_id: string
  evidence_manifest_artifact: SealedArtifactRefV3
  capability_provenance: Array<{
    actor_type: ActorType
    actor_id: string
    result_artifact: SealedArtifactRefV3
  }>
  method_summary: string
  risks_and_open_issues: string[]
  recommendations: Array<{
    id: string
    statement: string
    priority: 'P0' | 'P1' | 'P2' | 'P3'
    finding_ids: string[]
  }>
}

export interface ReportReviewV3 {
  run_id: string
  requirement_version_id: string
  plan_version_id: string
  attempt_id: string
  verdict: 'pass' | 'revise' | 'block'
  deliverable_artifact: SealedArtifactRefV3
}

interface ResearchV3WorkbenchAggregateBase<S extends WorkbenchState> {
  schema_version: 'research-workbench-aggregate-v1'
  projection_kind: 'research-v3-current'
  orchestration_version: 'research-v3'
  run_id: string
  workflow: WorkbenchWorkflow<S>
  approvals: WorkbenchApprovalV1[]
  provenance: CurrentWorkbenchProjectionProvenance
}

type IdleWorkbenchAggregate = ResearchV3WorkbenchAggregateBase<'idle'> & {
  requirement: null
  candidates: null
  selected_plan: null
  attempt: null
  recovery: null
  evidence: null
  deliverable: null
  review: null
  report: null
}

type ClarifyWorkbenchAggregate = ResearchV3WorkbenchAggregateBase<'clarify'> & {
  requirement: RequirementVersionV3
  candidates: null
  selected_plan: null
  attempt: null
  recovery: null
  evidence: null
  deliverable: null
  review: null
  report: null
}

type CandidatesWorkbenchAggregate = ResearchV3WorkbenchAggregateBase<'candidates'> & {
  requirement: RequirementVersionV3
  candidates: PlanCandidateSetV3
  selected_plan: null
  attempt: null
  recovery: null
  evidence: null
  deliverable: null
  review: null
  report: null
}

type PlanWorkbenchAggregate = ResearchV3WorkbenchAggregateBase<'plan' | 'approval'> & {
  requirement: RequirementVersionV3
  candidates: PlanCandidateSetV3
  selected_plan: ExecutionPlanVersionV3
  attempt: null
  recovery: null
  evidence: null
  deliverable: null
  review: null
  report: null
}

type ExecutingWorkbenchAggregate = ResearchV3WorkbenchAggregateBase<'dag_or_executing'> & {
  requirement: RequirementVersionV3
  candidates: PlanCandidateSetV3
  selected_plan: ExecutionPlanVersionV3
  attempt: WorkbenchAttemptV1
  recovery: null
  evidence: null
  deliverable: null
  review: null
  report: null
}

type PausedWorkbenchAggregate = ResearchV3WorkbenchAggregateBase<'paused'> & {
  requirement: RequirementVersionV3
  candidates: PlanCandidateSetV3
  selected_plan: ExecutionPlanVersionV3
  attempt: WorkbenchAttemptV1
  recovery: WorkbenchRecoveryV1
  evidence: null
  deliverable: null
  review: null
  report: null
}

type TextReportWorkbenchAggregate = ResearchV3WorkbenchAggregateBase<'text_report'> & {
  requirement: RequirementVersionV3
  candidates: PlanCandidateSetV3
  selected_plan: ExecutionPlanVersionV3
  attempt: WorkbenchAttemptV1
  recovery: null
  evidence: WorkbenchEvidenceV1
  deliverable: { content: ResearchDeliverableV3; artifact: SealedArtifactRefV3 }
  review: { content: ReportReviewV3; artifact: SealedArtifactRefV3 }
  report: { content: ReportDocumentV3; artifact: SealedArtifactRefV3 }
}

export type ResearchV3WorkbenchAggregateV1 =
  | IdleWorkbenchAggregate
  | ClarifyWorkbenchAggregate
  | CandidatesWorkbenchAggregate
  | PlanWorkbenchAggregate
  | ExecutingWorkbenchAggregate
  | PausedWorkbenchAggregate
  | TextReportWorkbenchAggregate

export interface ResearchV2HistoryWorkbenchAggregateV1 {
  schema_version: 'research-workbench-aggregate-v1'
  projection_kind: 'research-v2-history'
  orchestration_version: 'research-v2'
  read_only: true
  run_id: string
  history_payload: Record<string, unknown>
  provenance: V2HistoryAdapterProvenance
}

export type WorkbenchAggregateV1 = ResearchV3WorkbenchAggregateV1 | ResearchV2HistoryWorkbenchAggregateV1

type CanonicalIdentityKey =
  | 'schema_version'
  | 'projection_kind'
  | 'orchestration_version'
  | 'content_hash'
  | 'plan_hash'
  | 'contract_hash'
  | 'step_contract_hash'
  | 'artifact'
  | 'result_artifact'
  | 'deliverable_artifact'
  | 'review_artifact'
  | 'evidence_manifest_artifact'

export type RenderProjection<T> = T extends readonly (infer Item)[]
  ? RenderProjection<Item>[]
  : T extends object
    ? { [Key in keyof T as Key extends CanonicalIdentityKey ? never : Key]: RenderProjection<T[Key]> }
    : T

interface ResearchWorkbenchRenderIdentity {
  render_schema_version: 'research-workbench-render-v1'
  source_schema_version: 'research-workbench-aggregate-v1'
}

export type ResearchTaskRenderV1 = RenderProjection<ResearchTaskV3>
export type PlanCandidateRenderV1 = RenderProjection<PlanCandidateV3>
export type ExecutionPlanVersionRenderV1 = RenderProjection<ExecutionPlanVersionV3>
export type WorkbenchApprovalRenderV1 = RenderProjection<WorkbenchApprovalV1>
export type ReportBlockRenderV1 = RenderProjection<ReportBlockV3>
export type PlanStepRenderV1 = RenderProjection<PlanStepV3>
export type WorkbenchStepRenderV1 = RenderProjection<WorkbenchStepV1>

export type ResearchV3WorkbenchRenderV1 = RenderProjection<ResearchV3WorkbenchAggregateV1> &
  ResearchWorkbenchRenderIdentity & { render_kind: 'current' }

export type ResearchV2HistoryWorkbenchRenderV1 = RenderProjection<ResearchV2HistoryWorkbenchAggregateV1> &
  ResearchWorkbenchRenderIdentity & { render_kind: 'history' }

export type ResearchWorkbenchRenderV1 = ResearchV3WorkbenchRenderV1 | ResearchV2HistoryWorkbenchRenderV1

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
