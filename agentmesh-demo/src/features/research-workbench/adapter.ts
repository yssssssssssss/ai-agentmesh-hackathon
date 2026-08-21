import { sha256 } from '@noble/hashes/sha256'
import { bytesToHex } from '@noble/hashes/utils'

import { validateCanonicalWorkbenchSchema } from './canonicalValidation'
import type {
  ActorExecutionResultV3,
  ActorType,
  ApprovalRole,
  CurrentWorkbenchProjectionProvenance,
  DepthPlanCandidateV3,
  ExecutionPlanVersionV3,
  ExpectedOutputV3,
  PlanCandidateSetV3,
  PlanCandidateV3,
  PlanStepProposalV3,
  ReportBlockV3,
  ReportDocumentV3,
  ReportReviewV3,
  ResearchAssumption,
  ResearchDeliverableV3,
  ResearchTaskV3,
  ResearchWorkbenchRenderV1,
  ResearchV2HistoryWorkbenchAggregateV1,
  ResearchV3WorkbenchAggregateV1,
  RequirementVersionV3,
  SealedArtifactRefV3,
  SpeedPlanCandidateV3,
  WorkbenchAggregateV1,
  WorkbenchApprovalV1,
  WorkbenchAttemptV1,
  WorkbenchEvidenceV1,
  WorkbenchProjectionProvenance,
  WorkbenchRecoveryV1,
  WorkbenchState,
  WorkbenchWorkflow,
} from './types'

const CURRENT_STATES = [
  'idle',
  'clarify',
  'candidates',
  'plan',
  'approval',
  'dag_or_executing',
  'paused',
  'text_report',
] as const

const TOP_LEVEL_CURRENT_FIELDS = [
  'schema_version', 'projection_kind', 'orchestration_version', 'run_id', 'workflow', 'requirement',
  'candidates', 'selected_plan', 'approvals', 'attempt', 'recovery', 'evidence', 'deliverable', 'review',
  'report', 'provenance',
] as const

const FIELD_MATRIX: Record<WorkbenchState, ReadonlySet<string>> = {
  idle: new Set(),
  clarify: new Set(['requirement']),
  candidates: new Set(['requirement', 'candidates']),
  plan: new Set(['requirement', 'candidates', 'selected_plan']),
  approval: new Set(['requirement', 'candidates', 'selected_plan']),
  dag_or_executing: new Set(['requirement', 'candidates', 'selected_plan', 'attempt']),
  paused: new Set(['requirement', 'candidates', 'selected_plan', 'attempt', 'recovery']),
  text_report: new Set([
    'requirement', 'candidates', 'selected_plan', 'attempt', 'evidence', 'deliverable', 'review', 'report',
  ]),
}

const PROJECTED_FIELDS = [
  'requirement', 'candidates', 'selected_plan', 'attempt', 'recovery', 'evidence', 'deliverable', 'review', 'report',
] as const

const ARTIFACT_IDENTITIES = {
  controlSnapshot: { kind: 'research_control_snapshot', schema_version: 'research-control-snapshot-v3' },
  deliverable: { kind: 'research_deliverable', schema_version: 'research-deliverable-v3' },
  evidenceManifest: { kind: 'evidence_manifest', schema_version: 'evidence-manifest-v3' },
  problemGraph: { kind: 'problem_graph', schema_version: 'problem-graph-v1' },
  report: { kind: 'report_document', schema_version: 'report-document-v3' },
  review: { kind: 'report_review', schema_version: 'report-review-v3' },
} as const satisfies Record<string, Pick<SealedArtifactRefV3, 'kind' | 'schema_version'>>

function canonicalJson(value: unknown): string {
  if (value === null) return 'null'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('canonical JSON forbids non-finite numbers')
    return Object.is(value, -0) ? '0' : String(value)
  }
  if (typeof value === 'string') return JSON.stringify(value.normalize('NFC'))
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (typeof value === 'object') {
    const normalized = new Map<string, unknown>()
    for (const [key, item] of Object.entries(value)) {
      const normalizedKey = key.normalize('NFC')
      if (normalized.has(normalizedKey)) throw new TypeError('canonical JSON contains duplicate normalized keys')
      normalized.set(normalizedKey, item)
    }
    const encoder = new TextEncoder()
    const keys = [...normalized.keys()].sort((left, right) => {
      const a = encoder.encode(left)
      const b = encoder.encode(right)
      for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
        if (a[index] !== b[index]) return a[index] - b[index]
      }
      return a.length - b.length
    })
    return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(normalized.get(key))}`).join(',')}}`
  }
  throw new TypeError(`unsupported canonical JSON value: ${typeof value}`)
}

export function canonicalSha256(value: unknown): string {
  return bytesToHex(sha256(new TextEncoder().encode(canonicalJson(value))))
}

function requireCanonicalHash(content: unknown, expected: unknown, label: string): void {
  if (canonicalSha256(content) !== expected) throw new TypeError(`${label} does not match canonical content`)
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`)
  }
  return value as Record<string, unknown>
}

function exactKeys(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const allowedKeys = new Set(allowed)
  const unknownKey = Object.keys(value).find((key) => !allowedKeys.has(key))
  if (unknownKey) throw new TypeError(`${label} contains unsupported field ${unknownKey}`)
  const missingKey = allowed.find((key) => !Object.prototype.hasOwnProperty.call(value, key))
  if (missingKey) throw new TypeError(`${label} is missing required field ${missingKey}`)
}

function requireString(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new TypeError(`${label} must be a non-empty string`)
  return value
}

function requireBoolean(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') throw new TypeError(`${label} must be a boolean`)
  return value
}

function requireNumber(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError(`${label} must be a finite number`)
  return value
}

function requireInteger(value: unknown, label: string, minimum = 0): number {
  if (!Number.isInteger(value) || (value as number) < minimum) {
    throw new TypeError(`${label} must be an integer greater than or equal to ${minimum}`)
  }
  return value as number
}

function requireArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new TypeError(`${label} must be an array`)
  return value
}

function requireLiteral<const T extends string | boolean>(
  value: unknown,
  expected: T,
  label: string,
): T {
  if (value !== expected) throw new TypeError(`${label} must be ${String(expected)}`)
  return expected
}

function requireOneOf<const T extends readonly string[]>(value: unknown, allowed: T, label: string): T[number] {
  if (typeof value !== 'string' || !allowed.some((item) => item === value)) {
    throw new TypeError(`${label} has an unsupported value`)
  }
  return value as T[number]
}

function nullableString(value: unknown, label: string): string | null {
  return value === null ? null : requireString(value, label)
}

function strings(value: unknown, label: string): string[] {
  return requireArray(value, label).map((item, index) => requireString(item, `${label}[${index}]`))
}

function integers(value: unknown, label: string): number[] {
  return requireArray(value, label).map((item, index) => requireInteger(item, `${label}[${index}]`))
}

function parseDateTime(value: unknown, label: string): string {
  const timestamp = requireString(value, label)
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(timestamp) || Number.isNaN(Date.parse(timestamp))) {
    throw new TypeError(`${label} must be a timezone-aware date-time`)
  }
  return timestamp
}

function parseActorType(value: unknown, label: string): ActorType {
  return requireOneOf(value, ['tool', 'skill', 'llm', 'reviewer'] as const, label)
}

function parseApprovalRole(value: unknown, label: string): ApprovalRole {
  return requireOneOf(value, ['owner', 'legal', 'security'] as const, label)
}

function parseArtifact(
  value: unknown,
  label: string,
  expectedIdentity?: Pick<SealedArtifactRefV3, 'kind' | 'schema_version'>,
): SealedArtifactRefV3 {
  const item = record(value, label)
  return {
    artifact_id: requireString(item.artifact_id, `${label}.artifact_id`),
    content_hash: requireString(item.content_hash, `${label}.content_hash`),
    kind: expectedIdentity
      ? requireLiteral(item.kind, expectedIdentity.kind, `${label}.kind`)
      : requireString(item.kind, `${label}.kind`),
    schema_version: expectedIdentity
      ? requireLiteral(item.schema_version, expectedIdentity.schema_version, `${label}.schema_version`)
      : requireString(item.schema_version, `${label}.schema_version`),
  }
}

function sameArtifact(left: SealedArtifactRefV3, right: SealedArtifactRefV3): boolean {
  return left.artifact_id === right.artifact_id
    && left.content_hash === right.content_hash
    && left.kind === right.kind
    && left.schema_version === right.schema_version
}

function parseProvenance(value: unknown, label: string): WorkbenchProjectionProvenance {
  const item = record(value, label)
  const sourceKind = requireOneOf(
    item.source_kind,
    ['isolated_fixture', 'repository_projection', 'v2_history_adapter'] as const,
    `${label}.source_kind`,
  )
  const common = {
    projected_at: parseDateTime(item.projected_at, `${label}.projected_at`),
    projection_schema_version: requireLiteral(
      item.projection_schema_version,
      'research-workbench-aggregate-v1',
      `${label}.projection_schema_version`,
    ),
    source_state_version: requireInteger(item.source_state_version, `${label}.source_state_version`),
  }
  if (sourceKind === 'isolated_fixture') {
    return {
      ...common,
      source_kind: sourceKind,
      baseline_state_id: requireOneOf(item.baseline_state_id, CURRENT_STATES, `${label}.baseline_state_id`),
    }
  }
  if (item.baseline_state_id !== null) {
    throw new TypeError(`${label}.baseline_state_id must be null for non-fixture projections`)
  }
  return { ...common, source_kind: sourceKind, baseline_state_id: null }
}

function parseWorkflow(value: unknown): WorkbenchWorkflow {
  const item = record(value, 'workflow')
  const state = requireOneOf(item.state, CURRENT_STATES, 'workflow.state')
  const stateVersion = requireInteger(item.state_version, 'workflow.state_version')
  const gate = record(item.gate, 'workflow.gate')
  const kind = requireOneOf(
    gate.kind,
    ['none', 'clarification', 'candidate_selection', 'plan_confirmation', 'role_approval', 'recovery'] as const,
    'workflow.gate.kind',
  )
  const status = requireOneOf(gate.status, ['inactive', 'pending', 'satisfied', 'blocked'] as const, 'workflow.gate.status')
  const requiredRole = gate.required_role === null ? null : parseApprovalRole(gate.required_role, 'workflow.gate.required_role')
  const expectedKind = {
    idle: 'none',
    clarify: 'clarification',
    candidates: 'candidate_selection',
    plan: 'plan_confirmation',
    approval: 'role_approval',
    dag_or_executing: 'none',
    paused: 'recovery',
    text_report: 'none',
  } as const
  const allowedStatuses = {
    idle: ['inactive'],
    clarify: ['pending', 'blocked'],
    candidates: ['pending', 'blocked'],
    plan: ['pending', 'satisfied', 'blocked'],
    approval: ['pending'],
    dag_or_executing: ['inactive'],
    paused: ['blocked'],
    text_report: ['inactive'],
  } as const
  if (
    kind !== expectedKind[state]
    || !(allowedStatuses[state] as readonly string[]).includes(status)
  ) {
    throw new TypeError('Workbench workflow state and active gate do not agree')
  }
  if ((state === 'approval') !== (requiredRole !== null)) {
    throw new TypeError('Only the approval state may require an approval role')
  }

  if (state === 'idle') return { state, state_version: stateVersion, gate: { kind: 'none', status: 'inactive', required_role: null } }
  if (state === 'clarify') return { state, state_version: stateVersion, gate: { kind: 'clarification', status: status as 'pending' | 'blocked', required_role: null } }
  if (state === 'candidates') return { state, state_version: stateVersion, gate: { kind: 'candidate_selection', status: status as 'pending' | 'blocked', required_role: null } }
  if (state === 'plan') return { state, state_version: stateVersion, gate: { kind: 'plan_confirmation', status: status as 'pending' | 'satisfied' | 'blocked', required_role: null } }
  if (state === 'approval') return { state, state_version: stateVersion, gate: { kind: 'role_approval', status: 'pending', required_role: requiredRole as ApprovalRole } }
  if (state === 'dag_or_executing') return { state, state_version: stateVersion, gate: { kind: 'none', status: 'inactive', required_role: null } }
  if (state === 'paused') return { state, state_version: stateVersion, gate: { kind: 'recovery', status: 'blocked', required_role: null } }
  return { state, state_version: stateVersion, gate: { kind: 'none', status: 'inactive', required_role: null } }
}

function parseAssumptions(value: unknown, label: string): ResearchAssumption[] {
  return requireArray(value, label).map((raw, index) => {
    const item = record(raw, `${label}[${index}]`)
    return {
      key: requireString(item.key, `${label}[${index}].key`),
      value: requireString(item.value, `${label}[${index}].value`),
      editable: requireBoolean(item.editable, `${label}[${index}].editable`),
    }
  })
}

function parseTask(value: unknown): ResearchTaskV3 {
  const item = record(value, 'requirement.payload')
  const comparisonDimensions = item.comparison_dimensions === null
    ? null
    : strings(item.comparison_dimensions, 'requirement.payload.comparison_dimensions')
  return {
    schema_version: requireLiteral(item.schema_version, 'research-task-v3', 'requirement.payload.schema_version'),
    task_type: requireLiteral(item.task_type, 'competitive_research', 'requirement.payload.task_type'),
    business_domain: requireString(item.business_domain, 'requirement.payload.business_domain'),
    research_goal: requireString(item.research_goal, 'requirement.payload.research_goal'),
    target_audience: strings(item.target_audience, 'requirement.payload.target_audience'),
    scope: strings(item.scope, 'requirement.payload.scope'),
    comparison_dimensions: comparisonDimensions,
    constraints: requireArray(item.constraints, 'requirement.payload.constraints').map((raw, index) => {
      const constraint = record(raw, `requirement.payload.constraints[${index}]`)
      return {
        id: requireString(constraint.id, `requirement.payload.constraints[${index}].id`),
        statement: requireString(constraint.statement, `requirement.payload.constraints[${index}].statement`),
        source: requireString(constraint.source, `requirement.payload.constraints[${index}].source`),
      }
    }),
    success_criteria: requireArray(item.success_criteria, 'requirement.payload.success_criteria').map((raw, index) => {
      const criterion = record(raw, `requirement.payload.success_criteria[${index}]`)
      return {
        id: requireString(criterion.id, `requirement.payload.success_criteria[${index}].id`),
        statement: requireString(criterion.statement, `requirement.payload.success_criteria[${index}].statement`),
      }
    }),
    expected_deliverables: strings(item.expected_deliverables, 'requirement.payload.expected_deliverables'),
    assumptions: parseAssumptions(item.assumptions, 'requirement.payload.assumptions'),
    ambiguities: requireArray(item.ambiguities, 'requirement.payload.ambiguities').map((raw, index) => {
      const ambiguity = record(raw, `requirement.payload.ambiguities[${index}]`)
      return {
        id: requireString(ambiguity.id, `requirement.payload.ambiguities[${index}].id`),
        statement: requireString(ambiguity.statement, `requirement.payload.ambiguities[${index}].statement`),
        blocking: requireBoolean(ambiguity.blocking, `requirement.payload.ambiguities[${index}].blocking`),
      }
    }),
    clarification_questions: requireArray(item.clarification_questions, 'requirement.payload.clarification_questions').map((raw, index) => {
      const question = record(raw, `requirement.payload.clarification_questions[${index}]`)
      return {
        key: requireString(question.key, `requirement.payload.clarification_questions[${index}].key`),
        question: requireString(question.question, `requirement.payload.clarification_questions[${index}].question`),
        rationale: requireString(question.rationale, `requirement.payload.clarification_questions[${index}].rationale`),
      }
    }),
    blocking_issues: requireArray(item.blocking_issues, 'requirement.payload.blocking_issues').map((raw, index) => {
      const issue = record(raw, `requirement.payload.blocking_issues[${index}]`)
      return {
        key: requireString(issue.key, `requirement.payload.blocking_issues[${index}].key`),
        reason: requireString(issue.reason, `requirement.payload.blocking_issues[${index}].reason`),
        kind: requireString(issue.kind, `requirement.payload.blocking_issues[${index}].kind`),
      }
    }),
    sensitivity: requireOneOf(item.sensitivity, ['public', 'internal', 'confidential'] as const, 'requirement.payload.sensitivity'),
    pii_detected: requireBoolean(item.pii_detected, 'requirement.payload.pii_detected'),
  }
}

function parseRequirement(value: unknown): RequirementVersionV3 {
  const item = record(value, 'requirement')
  requireCanonicalHash(item.payload, item.content_hash, 'requirement.content_hash')
  return {
    id: requireString(item.id, 'requirement.id'),
    run_id: requireString(item.run_id, 'requirement.run_id'),
    version: requireInteger(item.version, 'requirement.version', 1),
    schema_version: requireLiteral(item.schema_version, 'research-task-v3', 'requirement.schema_version'),
    task_type: requireLiteral(item.task_type, 'competitive_research', 'requirement.task_type'),
    payload: parseTask(item.payload),
    content_hash: requireString(item.content_hash, 'requirement.content_hash'),
    created_at: parseDateTime(item.created_at, 'requirement.created_at'),
  }
}

function parseExpectedOutputs(value: unknown, label: string): ExpectedOutputV3[] {
  return requireArray(value, label).map((raw, index) => {
    const item = record(raw, `${label}[${index}]`)
    return {
      pointer: requireString(item.pointer, `${label}[${index}].pointer`),
      description: requireString(item.description, `${label}[${index}].description`),
    }
  })
}

function parseStepProposal(value: unknown, label: string): PlanStepProposalV3 {
  const item = record(value, label)
  return {
    proposed_step_number: requireInteger(item.proposed_step_number, `${label}.proposed_step_number`, 1),
    name: requireString(item.name, `${label}.name`),
    actor_type: parseActorType(item.actor_type, `${label}.actor_type`),
    actor_id: requireString(item.actor_id, `${label}.actor_id`),
    question_ids: strings(item.question_ids, `${label}.question_ids`),
    depends_on: integers(item.depends_on, `${label}.depends_on`),
    input: { ...record(item.input, `${label}.input`) },
    input_bindings: requireArray(item.input_bindings, `${label}.input_bindings`).map((raw, index) => {
      const binding = record(raw, `${label}.input_bindings[${index}]`)
      return {
        source_step_number: requireInteger(binding.source_step_number, `${label}.input_bindings[${index}].source_step_number`, 1),
        source_pointer: requireString(binding.source_pointer, `${label}.input_bindings[${index}].source_pointer`),
        target_pointer: requireString(binding.target_pointer, `${label}.input_bindings[${index}].target_pointer`),
      }
    }),
    expected_outputs: parseExpectedOutputs(item.expected_outputs, `${label}.expected_outputs`),
    acceptance_criteria: strings(item.acceptance_criteria, `${label}.acceptance_criteria`),
    requires_approval: requireBoolean(item.requires_approval, `${label}.requires_approval`),
    approval_role: item.approval_role === null ? null : parseApprovalRole(item.approval_role, `${label}.approval_role`),
  }
}

function parseCandidate(value: unknown, expectedId: 'depth', label: string): DepthPlanCandidateV3
function parseCandidate(value: unknown, expectedId: 'speed', label: string): SpeedPlanCandidateV3
function parseCandidate(value: unknown, expectedId: 'depth' | 'speed', label: string): PlanCandidateV3 {
  const item = record(value, label)
  const common = {
    title: requireString(item.title, `${label}.title`),
    rationale: requireString(item.rationale, `${label}.rationale`),
    tradeoffs: requireString(item.tradeoffs, `${label}.tradeoffs`),
    assumptions: parseAssumptions(item.assumptions, `${label}.assumptions`),
    proposed_steps: requireArray(item.proposed_steps, `${label}.proposed_steps`).map((step, index) => (
      parseStepProposal(step, `${label}.proposed_steps[${index}]`)
    )),
  }
  requireLiteral(item.candidate_id, expectedId, `${label}.candidate_id`)
  return expectedId === 'depth'
    ? { ...common, candidate_id: 'depth' }
    : { ...common, candidate_id: 'speed' }
}

function parseCandidates(value: unknown): PlanCandidateSetV3 {
  const item = record(value, 'candidates')
  requireLiteral(item.schema_version, 'plan-candidates-v3', 'candidates.schema_version')
  const candidates = requireArray(item.candidates, 'candidates.candidates')
  if (candidates.length !== 2) throw new TypeError('The frozen candidate set must contain depth and speed')
  return {
    schema_version: 'plan-candidates-v3',
    candidates: [
      parseCandidate(candidates[0], 'depth', 'candidates.candidates[0]'),
      parseCandidate(candidates[1], 'speed', 'candidates.candidates[1]'),
    ],
  }
}

function parsePlan(value: unknown): ExecutionPlanVersionV3 {
  const item = record(value, 'selected_plan')
  requireLiteral(item.schema_version, 'execution-plan-v3', 'selected_plan.schema_version')
  const payload = record(item.payload, 'selected_plan.payload')
  parseArtifact(
    payload.problem_graph_artifact,
    'selected_plan.payload.problem_graph_artifact',
    ARTIFACT_IDENTITIES.problemGraph,
  )
  parseArtifact(
    payload.control_snapshot_artifact,
    'selected_plan.payload.control_snapshot_artifact',
    ARTIFACT_IDENTITIES.controlSnapshot,
  )
  requireCanonicalHash(item.payload, item.plan_hash, 'selected_plan.plan_hash')
  return {
    id: requireString(item.id, 'selected_plan.id'),
    run_id: requireString(item.run_id, 'selected_plan.run_id'),
    requirement_version_id: requireString(item.requirement_version_id, 'selected_plan.requirement_version_id'),
    version: requireInteger(item.version, 'selected_plan.version', 1),
    schema_version: 'execution-plan-v3',
    plan_hash: requireString(item.plan_hash, 'selected_plan.plan_hash'),
    created_at: parseDateTime(item.created_at, 'selected_plan.created_at'),
    payload: {
      schema_version: requireLiteral(payload.schema_version, 'execution-plan-v3', 'selected_plan.payload.schema_version'),
      task_type: requireLiteral(payload.task_type, 'competitive_research', 'selected_plan.payload.task_type'),
      requirement_version_id: requireString(payload.requirement_version_id, 'selected_plan.payload.requirement_version_id'),
      requirement_content_hash: requireString(payload.requirement_content_hash, 'selected_plan.payload.requirement_content_hash'),
      candidate_id: requireOneOf(payload.candidate_id, ['depth', 'speed'] as const, 'selected_plan.payload.candidate_id'),
      candidate_title: requireString(payload.candidate_title, 'selected_plan.payload.candidate_title'),
      candidate_rationale: requireString(payload.candidate_rationale, 'selected_plan.payload.candidate_rationale'),
      candidate_tradeoffs: requireString(payload.candidate_tradeoffs, 'selected_plan.payload.candidate_tradeoffs'),
      deliverable_type: requireLiteral(payload.deliverable_type, 'competitive_analysis_report', 'selected_plan.payload.deliverable_type'),
      payload_schema_version: requireLiteral(payload.payload_schema_version, 'competitive-analysis-text-v1', 'selected_plan.payload.payload_schema_version'),
      activated_nodes: strings(payload.activated_nodes, 'selected_plan.payload.activated_nodes'),
      capability_gaps: requireArray(payload.capability_gaps, 'selected_plan.payload.capability_gaps').map((raw, index) => {
        const gap = record(raw, `selected_plan.payload.capability_gaps[${index}]`)
        return {
          capability_type: parseActorType(gap.capability_type, `selected_plan.payload.capability_gaps[${index}].capability_type`),
          capability_id: requireString(gap.capability_id, `selected_plan.payload.capability_gaps[${index}].capability_id`),
          code: requireString(gap.code, `selected_plan.payload.capability_gaps[${index}].code`),
          message: requireString(gap.message, `selected_plan.payload.capability_gaps[${index}].message`),
          required: requireBoolean(gap.required, `selected_plan.payload.capability_gaps[${index}].required`),
        }
      }),
      steps: requireArray(payload.steps, 'selected_plan.payload.steps').map((raw, index) => {
        const step = record(raw, `selected_plan.payload.steps[${index}]`)
        const contract = Object.fromEntries(Object.entries(step).filter(([key]) => key !== 'contract_hash'))
        requireCanonicalHash(contract, step.contract_hash, `selected_plan.payload.steps[${index}].contract_hash`)
        return {
          step_number: requireInteger(step.step_number, `selected_plan.payload.steps[${index}].step_number`, 1),
          name: requireString(step.name, `selected_plan.payload.steps[${index}].name`),
          actor_type: parseActorType(step.actor_type, `selected_plan.payload.steps[${index}].actor_type`),
          actor_id: requireString(step.actor_id, `selected_plan.payload.steps[${index}].actor_id`),
          contract_hash: requireString(step.contract_hash, `selected_plan.payload.steps[${index}].contract_hash`),
          question_ids: strings(step.question_ids, `selected_plan.payload.steps[${index}].question_ids`),
          depends_on: integers(step.depends_on, `selected_plan.payload.steps[${index}].depends_on`),
          expected_outputs: parseExpectedOutputs(step.expected_outputs, `selected_plan.payload.steps[${index}].expected_outputs`),
          acceptance_criteria: strings(step.acceptance_criteria, `selected_plan.payload.steps[${index}].acceptance_criteria`),
          required: requireBoolean(step.required, `selected_plan.payload.steps[${index}].required`),
          requires_approval: requireBoolean(step.requires_approval, `selected_plan.payload.steps[${index}].requires_approval`),
          approval_role: step.approval_role === null ? null : parseApprovalRole(step.approval_role, `selected_plan.payload.steps[${index}].approval_role`),
          timeout_seconds: requireInteger(step.timeout_seconds, `selected_plan.payload.steps[${index}].timeout_seconds`, 1),
        }
      }),
    },
  }
}

function parseApprovals(value: unknown): WorkbenchApprovalV1[] {
  return requireArray(value, 'approvals').map((raw, index) => {
    const item = record(raw, `approvals[${index}]`)
    const decision = requireOneOf(item.decision, ['pending', 'approved', 'rejected'] as const, `approvals[${index}].decision`)
    const receiptId = nullableString(item.receipt_id, `approvals[${index}].receipt_id`)
    if ((decision === 'pending') !== (receiptId === null)) {
      throw new TypeError('Approval receipts are present exactly for settled decisions')
    }
    return {
      gate_key: requireString(item.gate_key, `approvals[${index}].gate_key`),
      plan_version_id: requireString(item.plan_version_id, `approvals[${index}].plan_version_id`),
      role: parseApprovalRole(item.role, `approvals[${index}].role`),
      decision,
      receipt_id: receiptId,
    }
  })
}

function parseExecutionResult(value: unknown, label: string): ActorExecutionResultV3 {
  const item = record(value, label)
  return {
    result_artifact: parseArtifact(item.result_artifact, `${label}.result_artifact`),
    run_id: requireString(item.run_id, `${label}.run_id`),
    plan_version_id: requireString(item.plan_version_id, `${label}.plan_version_id`),
    attempt_id: requireString(item.attempt_id, `${label}.attempt_id`),
    step_number: requireInteger(item.step_number, `${label}.step_number`, 1),
    actor_type: parseActorType(item.actor_type, `${label}.actor_type`),
    actor_id: requireString(item.actor_id, `${label}.actor_id`),
    step_contract_hash: requireString(item.step_contract_hash, `${label}.step_contract_hash`),
    receipt_id: requireString(item.receipt_id, `${label}.receipt_id`),
  }
}

function parseAttempt(value: unknown): WorkbenchAttemptV1 {
  const item = record(value, 'attempt')
  const attempt = {
    attempt_id: requireString(item.attempt_id, 'attempt.attempt_id'),
    run_id: requireString(item.run_id, 'attempt.run_id'),
    plan_version_id: requireString(item.plan_version_id, 'attempt.plan_version_id'),
    status: requireOneOf(item.status, ['running', 'paused', 'completed'] as const, 'attempt.status'),
    steps: requireArray(item.steps, 'attempt.steps').map((raw, index) => {
      const step = record(raw, `attempt.steps[${index}]`)
      const status = requireOneOf(
        step.status,
        ['pending', 'running', 'succeeded', 'failed', 'skipped'] as const,
        `attempt.steps[${index}].status`,
      )
      const result = step.result === null ? null : parseExecutionResult(step.result, `attempt.steps[${index}].result`)
      const failureCode = nullableString(step.failure_code, `attempt.steps[${index}].failure_code`)
      if ((status === 'succeeded') !== (result !== null)) {
        throw new TypeError('A succeeded Workbench step requires exactly one bound result')
      }
      if ((status === 'failed') !== (failureCode !== null)) {
        throw new TypeError('A failed Workbench step requires exactly one failure code')
      }
      const parsed = {
        step_number: requireInteger(step.step_number, `attempt.steps[${index}].step_number`, 1),
        actor_type: parseActorType(step.actor_type, `attempt.steps[${index}].actor_type`),
        actor_id: requireString(step.actor_id, `attempt.steps[${index}].actor_id`),
        step_contract_hash: requireString(step.step_contract_hash, `attempt.steps[${index}].step_contract_hash`),
        expected_outputs: parseExpectedOutputs(step.expected_outputs, `attempt.steps[${index}].expected_outputs`),
        status,
        failure_code: failureCode,
        result,
      }
      if (result && (
        result.step_number !== parsed.step_number
        || result.actor_type !== parsed.actor_type
        || result.actor_id !== parsed.actor_id
        || result.step_contract_hash !== parsed.step_contract_hash
      )) throw new TypeError('Workbench step result does not match its plan-step identity')
      return parsed
    }),
  }
  for (const step of attempt.steps) {
    if (step.result && (
      step.result.run_id !== attempt.run_id
      || step.result.plan_version_id !== attempt.plan_version_id
      || step.result.attempt_id !== attempt.attempt_id
    )) throw new TypeError('Workbench step result does not belong to its attempt')
  }
  return attempt
}

function parseRecovery(value: unknown): WorkbenchRecoveryV1 {
  const item = record(value, 'recovery')
  return {
    failed_step_number: requireInteger(item.failed_step_number, 'recovery.failed_step_number', 1),
    reason_code: requireString(item.reason_code, 'recovery.reason_code'),
    allowed_actions: requireArray(item.allowed_actions, 'recovery.allowed_actions').map((action, index) => (
      requireOneOf(action, ['retry', 'skip', 'abort'] as const, `recovery.allowed_actions[${index}]`)
    )),
    decision_required: requireLiteral(item.decision_required, true, 'recovery.decision_required'),
  }
}

function parseEvidence(value: unknown): WorkbenchEvidenceV1 {
  const item = record(value, 'evidence')
  return {
    artifact: parseArtifact(item.artifact, 'evidence.artifact', ARTIFACT_IDENTITIES.evidenceManifest),
    presentation_mode: requireLiteral(item.presentation_mode, 'text', 'evidence.presentation_mode'),
    run_id: requireString(item.run_id, 'evidence.run_id'),
    plan_version_id: requireString(item.plan_version_id, 'evidence.plan_version_id'),
    attempt_id: requireString(item.attempt_id, 'evidence.attempt_id'),
    evidence: requireArray(item.evidence, 'evidence.evidence').map((raw, index) => {
      const evidenceItem = record(raw, `evidence.evidence[${index}]`)
      const gap = record(evidenceItem.gap_metadata, `evidence.evidence[${index}].gap_metadata`)
      const provenance = record(evidenceItem.provenance, `evidence.evidence[${index}].provenance`)
      const url = requireString(evidenceItem.url, `evidence.evidence[${index}].url`)
      if (!url.startsWith('https://')) throw new TypeError('Workbench evidence URLs must use HTTPS')
      return {
        evidence_id: requireString(evidenceItem.evidence_id, `evidence.evidence[${index}].evidence_id`),
        source_id: requireString(evidenceItem.source_id, `evidence.evidence[${index}].source_id`),
        title: requireString(evidenceItem.title, `evidence.evidence[${index}].title`),
        url,
        quote: requireString(evidenceItem.quote, `evidence.evidence[${index}].quote`),
        gap_metadata: {
          redaction: requireOneOf(gap.redaction, ['none', 'masked'] as const, `evidence.evidence[${index}].gap_metadata.redaction`),
          truncated: requireBoolean(gap.truncated, `evidence.evidence[${index}].gap_metadata.truncated`),
          conflict_status: requireOneOf(gap.conflict_status, ['none', 'corroborated', 'conflicting'] as const, `evidence.evidence[${index}].gap_metadata.conflict_status`),
          risk_flags: strings(gap.risk_flags, `evidence.evidence[${index}].gap_metadata.risk_flags`),
        },
        provenance: {
          source_kind: requireLiteral(provenance.source_kind, 'public_web', `evidence.evidence[${index}].provenance.source_kind`),
          retrieved_at: parseDateTime(provenance.retrieved_at, `evidence.evidence[${index}].provenance.retrieved_at`),
          registrable_domain: requireString(provenance.registrable_domain, `evidence.evidence[${index}].provenance.registrable_domain`),
          independence_group: requireString(provenance.independence_group, `evidence.evidence[${index}].provenance.independence_group`),
          artifact: parseArtifact(provenance.artifact, `evidence.evidence[${index}].provenance.artifact`),
          run_id: requireString(provenance.run_id, `evidence.evidence[${index}].provenance.run_id`),
          plan_version_id: requireString(provenance.plan_version_id, `evidence.evidence[${index}].provenance.plan_version_id`),
          attempt_id: requireString(provenance.attempt_id, `evidence.evidence[${index}].provenance.attempt_id`),
          actor_type: requireLiteral(provenance.actor_type, 'tool', `evidence.evidence[${index}].provenance.actor_type`),
          actor_id: requireString(provenance.actor_id, `evidence.evidence[${index}].provenance.actor_id`),
          step_number: requireInteger(provenance.step_number, `evidence.evidence[${index}].provenance.step_number`, 1),
          step_contract_hash: requireString(provenance.step_contract_hash, `evidence.evidence[${index}].provenance.step_contract_hash`),
          receipt_id: requireString(provenance.receipt_id, `evidence.evidence[${index}].provenance.receipt_id`),
        },
      }
    }),
  }
}

function parseDeliverable(value: unknown): { content: ResearchDeliverableV3; artifact: SealedArtifactRefV3 } {
  const item = record(value, 'deliverable')
  const artifact = parseArtifact(item.artifact, 'deliverable.artifact', ARTIFACT_IDENTITIES.deliverable)
  const content = record(item.content, 'deliverable.content')
  const parsedContent = {
    run_id: requireString(content.run_id, 'deliverable.content.run_id'),
    requirement_version_id: requireString(content.requirement_version_id, 'deliverable.content.requirement_version_id'),
    plan_version_id: requireString(content.plan_version_id, 'deliverable.content.plan_version_id'),
    attempt_id: requireString(content.attempt_id, 'deliverable.content.attempt_id'),
    evidence_manifest_artifact: parseArtifact(
      content.evidence_manifest_artifact,
      'deliverable.content.evidence_manifest_artifact',
      ARTIFACT_IDENTITIES.evidenceManifest,
    ),
    capability_provenance: requireArray(content.capability_provenance, 'deliverable.content.capability_provenance').map((raw, index) => {
      const capability = record(raw, `deliverable.content.capability_provenance[${index}]`)
      return {
        actor_type: parseActorType(capability.actor_type, `deliverable.content.capability_provenance[${index}].actor_type`),
        actor_id: requireString(capability.actor_id, `deliverable.content.capability_provenance[${index}].actor_id`),
        result_artifact: parseArtifact(capability.result_artifact, `deliverable.content.capability_provenance[${index}].result_artifact`),
      }
    }),
    method_summary: requireString(content.method_summary, 'deliverable.content.method_summary'),
    risks_and_open_issues: strings(content.risks_and_open_issues, 'deliverable.content.risks_and_open_issues'),
    recommendations: requireArray(content.recommendations, 'deliverable.content.recommendations').map((raw, index) => {
      const recommendation = record(raw, `deliverable.content.recommendations[${index}]`)
      return {
        id: requireString(recommendation.id, `deliverable.content.recommendations[${index}].id`),
        statement: requireString(recommendation.statement, `deliverable.content.recommendations[${index}].statement`),
        priority: requireOneOf(recommendation.priority, ['P0', 'P1', 'P2', 'P3'] as const, `deliverable.content.recommendations[${index}].priority`),
        finding_ids: strings(recommendation.finding_ids, `deliverable.content.recommendations[${index}].finding_ids`),
      }
    }),
  }
  requireCanonicalHash(item.content, artifact.content_hash, 'deliverable artifact hash')
  return { artifact, content: parsedContent }
}

function parseReview(value: unknown): { content: ReportReviewV3; artifact: SealedArtifactRefV3 } {
  const item = record(value, 'review')
  const artifact = parseArtifact(item.artifact, 'review.artifact', ARTIFACT_IDENTITIES.review)
  const content = record(item.content, 'review.content')
  const parsedContent = {
    run_id: requireString(content.run_id, 'review.content.run_id'),
    requirement_version_id: requireString(content.requirement_version_id, 'review.content.requirement_version_id'),
    plan_version_id: requireString(content.plan_version_id, 'review.content.plan_version_id'),
    attempt_id: requireString(content.attempt_id, 'review.content.attempt_id'),
    verdict: requireOneOf(content.verdict, ['pass', 'revise', 'block'] as const, 'review.content.verdict'),
    deliverable_artifact: parseArtifact(
      content.deliverable_artifact,
      'review.content.deliverable_artifact',
      ARTIFACT_IDENTITIES.deliverable,
    ),
  }
  requireCanonicalHash(item.content, artifact.content_hash, 'review artifact hash')
  return { artifact, content: parsedContent }
}

function parseReportBlock(value: unknown, label: string): ReportBlockV3 {
  const item = record(value, label)
  const id = requireString(item.id, `${label}.id`)
  const type = requireOneOf(item.type, ['paragraph', 'fact', 'metric', 'list'] as const, `${label}.type`)
  if (type === 'paragraph') return { id, type, text: requireString(item.text, `${label}.text`) }
  if (type === 'fact') return { id, type, text: requireString(item.text, `${label}.text`), evidence_ids: strings(item.evidence_ids, `${label}.evidence_ids`) }
  if (type === 'metric') return {
    id,
    type,
    label: requireString(item.label, `${label}.label`),
    value: requireNumber(item.value, `${label}.value`),
    evidence_ids: strings(item.evidence_ids, `${label}.evidence_ids`),
  }
  return { id, type, items: strings(item.items, `${label}.items`) }
}

function parseReport(value: unknown): { content: ReportDocumentV3; artifact: SealedArtifactRefV3 } {
  const item = record(value, 'report')
  const artifact = parseArtifact(item.artifact, 'report.artifact', ARTIFACT_IDENTITIES.report)
  const content = record(item.content, 'report.content')
  const parsedContent = {
    schema_version: requireLiteral(content.schema_version, 'report-document-v3', 'report.content.schema_version'),
    presentation_mode: requireLiteral(content.presentation_mode, 'text', 'report.content.presentation_mode'),
    review_verdict: requireLiteral(content.review_verdict, 'pass', 'report.content.review_verdict'),
    run_id: requireString(content.run_id, 'report.content.run_id'),
    requirement_version_id: requireString(content.requirement_version_id, 'report.content.requirement_version_id'),
    plan_version_id: requireString(content.plan_version_id, 'report.content.plan_version_id'),
    attempt_id: requireString(content.attempt_id, 'report.content.attempt_id'),
    deliverable_artifact: parseArtifact(
      content.deliverable_artifact,
      'report.content.deliverable_artifact',
      ARTIFACT_IDENTITIES.deliverable,
    ),
    review_artifact: parseArtifact(
      content.review_artifact,
      'report.content.review_artifact',
      ARTIFACT_IDENTITIES.review,
    ),
    title: requireString(content.title, 'report.content.title'),
    subtitle: requireString(content.subtitle, 'report.content.subtitle'),
    executive_summary: requireString(content.executive_summary, 'report.content.executive_summary'),
    sections: requireArray(content.sections, 'report.content.sections').map((raw, index) => {
      const section = record(raw, `report.content.sections[${index}]`)
      return {
        id: requireString(section.id, `report.content.sections[${index}].id`),
        title: requireString(section.title, `report.content.sections[${index}].title`),
        question_ids: strings(section.question_ids, `report.content.sections[${index}].question_ids`),
        blocks: requireArray(section.blocks, `report.content.sections[${index}].blocks`).map((block, blockIndex) => (
          parseReportBlock(block, `report.content.sections[${index}].blocks[${blockIndex}]`)
        )),
      }
    }),
  }
  requireCanonicalHash(item.content, artifact.content_hash, 'report artifact hash')
  return { artifact, content: parsedContent }
}

function validateFieldMatrix(root: Record<string, unknown>, state: WorkbenchState): void {
  const expected = FIELD_MATRIX[state]
  for (const field of PROJECTED_FIELDS) {
    if ((root[field] !== null) !== expected.has(field)) {
      throw new TypeError('Workbench aggregate fields do not match the frozen state projection')
    }
  }
}

function validatePlanLineage(
  runId: string,
  requirement: RequirementVersionV3,
  plan: ExecutionPlanVersionV3 | null,
): void {
  if (requirement.run_id !== runId) throw new TypeError('Workbench requirement does not belong to the projected run')
  if (plan && (
    plan.run_id !== runId
    || plan.requirement_version_id !== requirement.id
    || plan.payload.requirement_version_id !== requirement.id
    || plan.payload.requirement_content_hash !== requirement.content_hash
  )) throw new TypeError('Workbench selected plan requirement lineage is invalid')
}

function validateAttemptPlanBinding(attempt: WorkbenchAttemptV1, plan: ExecutionPlanVersionV3): void {
  if (attempt.steps.length !== plan.payload.steps.length) {
    throw new TypeError('Workbench steps do not exactly match the selected Plan contracts')
  }
  attempt.steps.forEach((step, index) => {
    const planned = plan.payload.steps[index]
    if (!planned
      || step.step_number !== planned.step_number
      || step.actor_type !== planned.actor_type
      || step.actor_id !== planned.actor_id
      || step.step_contract_hash !== planned.contract_hash
      || JSON.stringify(step.expected_outputs) !== JSON.stringify(planned.expected_outputs)
    ) throw new TypeError('Workbench steps do not exactly match the selected Plan contracts')
  })
}

function validateReportLineage(
  runId: string,
  requirement: RequirementVersionV3,
  plan: ExecutionPlanVersionV3,
  attempt: WorkbenchAttemptV1,
  evidence: WorkbenchEvidenceV1,
  deliverable: { content: ResearchDeliverableV3; artifact: SealedArtifactRefV3 },
  review: { content: ReportReviewV3; artifact: SealedArtifactRefV3 },
  report: { content: ReportDocumentV3; artifact: SealedArtifactRefV3 },
): void {
  if (attempt.status !== 'completed') throw new TypeError('text report projection requires a completed attempt')
  const expectedThree = [runId, plan.id, attempt.attempt_id]
  if (JSON.stringify([evidence.run_id, evidence.plan_version_id, evidence.attempt_id]) !== JSON.stringify(expectedThree)) {
    throw new TypeError('Workbench Evidence Manifest lineage is invalid')
  }
  const expectedFour = [runId, requirement.id, plan.id, attempt.attempt_id]
  if (JSON.stringify([
    deliverable.content.run_id,
    deliverable.content.requirement_version_id,
    deliverable.content.plan_version_id,
    deliverable.content.attempt_id,
  ]) !== JSON.stringify(expectedFour)) throw new TypeError('Workbench deliverable requirement lineage is invalid')
  if (!sameArtifact(deliverable.content.evidence_manifest_artifact, evidence.artifact)) {
    throw new TypeError('Workbench deliverable references a different Evidence Manifest')
  }
  if (JSON.stringify([
    review.content.run_id,
    review.content.requirement_version_id,
    review.content.plan_version_id,
    review.content.attempt_id,
  ]) !== JSON.stringify(expectedFour)) throw new TypeError('Workbench review requirement lineage is invalid')
  if (review.content.verdict !== 'pass') throw new TypeError('Workbench report projection requires a pass review')
  if (!sameArtifact(review.content.deliverable_artifact, deliverable.artifact)) {
    throw new TypeError('Workbench review references a different deliverable')
  }
  if (JSON.stringify([
    report.content.run_id,
    report.content.requirement_version_id,
    report.content.plan_version_id,
    report.content.attempt_id,
  ]) !== JSON.stringify(expectedFour)) throw new TypeError('Workbench report requirement lineage is invalid')
  if (!sameArtifact(report.content.deliverable_artifact, deliverable.artifact)
    || !sameArtifact(report.content.review_artifact, review.artifact)) {
    throw new TypeError('Workbench report references different reviewed Artifacts')
  }

  const evidenceIds = new Set(evidence.evidence.map((item) => item.evidence_id))
  for (const section of report.content.sections) {
    for (const block of section.blocks) {
      if ((block.type === 'fact' || block.type === 'metric')
        && block.evidence_ids.some((evidenceId) => !evidenceIds.has(evidenceId))) {
        throw new TypeError('Workbench report block references unknown Evidence')
      }
    }
  }

  const successfulResults = attempt.steps.flatMap((step) => step.status === 'succeeded' && step.result ? [step.result] : [])
  for (const item of evidence.evidence) {
    const source = item.provenance
    if (source.run_id !== evidence.run_id
      || source.plan_version_id !== evidence.plan_version_id
      || source.attempt_id !== evidence.attempt_id) {
      throw new TypeError('Workbench evidence provenance does not match its projection lineage')
    }
    const bound = successfulResults.some((result) => (
      sameArtifact(result.result_artifact, source.artifact)
      && result.run_id === source.run_id
      && result.plan_version_id === source.plan_version_id
      && result.attempt_id === source.attempt_id
      && result.step_number === source.step_number
      && result.actor_type === source.actor_type
      && result.actor_id === source.actor_id
      && result.step_contract_hash === source.step_contract_hash
      && result.receipt_id === source.receipt_id
    ))
    if (!bound) throw new TypeError('Workbench Evidence Artifact is not bound to a successful attempt result')
  }
  for (const capability of deliverable.content.capability_provenance) {
    if (!successfulResults.some((result) => (
      sameArtifact(result.result_artifact, capability.result_artifact)
      && result.actor_type === capability.actor_type
      && result.actor_id === capability.actor_id
    ))) throw new TypeError('Workbench capability Artifact is not bound to a successful attempt result')
  }
}

function currentProvenance(
  provenance: WorkbenchProjectionProvenance,
  workflow: WorkbenchWorkflow,
): CurrentWorkbenchProjectionProvenance {
  if (provenance.source_kind === 'v2_history_adapter') {
    throw new TypeError('research-v3 current projections cannot use v2 history provenance')
  }
  if (provenance.source_state_version !== workflow.state_version) {
    throw new TypeError('Workbench provenance and workflow state versions do not agree')
  }
  if (provenance.source_kind === 'isolated_fixture' && provenance.baseline_state_id !== workflow.state) {
    throw new TypeError('Workbench fixture provenance names a different baseline state')
  }
  return provenance
}

function validateCurrent(root: Record<string, unknown>): ResearchV3WorkbenchAggregateV1 {
  exactKeys(root, TOP_LEVEL_CURRENT_FIELDS, 'research-v3 workbench aggregate')
  requireLiteral(root.orchestration_version, 'research-v3', 'orchestration_version')
  const runId = requireString(root.run_id, 'run_id')
  const workflow = parseWorkflow(root.workflow)
  validateFieldMatrix(root, workflow.state)
  const provenance = currentProvenance(parseProvenance(root.provenance, 'provenance'), workflow)
  const approvals = parseApprovals(root.approvals)

  if (workflow.state === 'idle') {
    if (approvals.length) throw new TypeError('idle Workbench projection cannot contain approvals')
    return {
      schema_version: 'research-workbench-aggregate-v1', projection_kind: 'research-v3-current', orchestration_version: 'research-v3',
      run_id: runId, workflow, approvals, provenance,
      requirement: null, candidates: null, selected_plan: null, attempt: null, recovery: null,
      evidence: null, deliverable: null, review: null, report: null,
    }
  }

  const requirement = parseRequirement(root.requirement)
  if (workflow.state === 'clarify') {
    if (approvals.length) throw new TypeError('pre-approval Workbench states cannot contain approvals')
    validatePlanLineage(runId, requirement, null)
    return {
      schema_version: 'research-workbench-aggregate-v1', projection_kind: 'research-v3-current', orchestration_version: 'research-v3',
      run_id: runId, workflow, approvals, provenance, requirement,
      candidates: null, selected_plan: null, attempt: null, recovery: null, evidence: null, deliverable: null, review: null, report: null,
    }
  }

  const candidates = parseCandidates(root.candidates)
  if (workflow.state === 'candidates') {
    if (approvals.length) throw new TypeError('pre-approval Workbench states cannot contain approvals')
    validatePlanLineage(runId, requirement, null)
    return {
      schema_version: 'research-workbench-aggregate-v1', projection_kind: 'research-v3-current', orchestration_version: 'research-v3',
      run_id: runId, workflow, approvals, provenance, requirement, candidates,
      selected_plan: null, attempt: null, recovery: null, evidence: null, deliverable: null, review: null, report: null,
    }
  }

  const selectedPlan = parsePlan(root.selected_plan)
  validatePlanLineage(runId, requirement, selectedPlan)
  if (workflow.state === 'plan' || workflow.state === 'approval') {
    if (workflow.state === 'plan' && approvals.length) {
      throw new TypeError('pre-approval Workbench states cannot contain approvals')
    }
    if (workflow.state === 'approval' && (!approvals.length || !approvals.some((item) => item.decision === 'pending'))) {
      throw new TypeError('approval state requires a pending approval')
    }
    if (approvals.some((item) => item.plan_version_id !== selectedPlan.id)) {
      throw new TypeError('Workbench approval references a different selected plan')
    }
    return {
      schema_version: 'research-workbench-aggregate-v1', projection_kind: 'research-v3-current', orchestration_version: 'research-v3',
      run_id: runId, workflow, approvals, provenance, requirement, candidates, selected_plan: selectedPlan,
      attempt: null, recovery: null, evidence: null, deliverable: null, review: null, report: null,
    }
  }

  if (!approvals.length || approvals.some((item) => item.decision !== 'approved')) {
    throw new TypeError('execution and report states require settled approvals')
  }
  if (approvals.some((item) => item.plan_version_id !== selectedPlan.id)) {
    throw new TypeError('Workbench approval references a different selected plan')
  }
  const attempt = parseAttempt(root.attempt)
  if (attempt.run_id !== runId || attempt.plan_version_id !== selectedPlan.id) {
    throw new TypeError('Workbench attempt does not belong to the selected plan')
  }
  validateAttemptPlanBinding(attempt, selectedPlan)

  if (workflow.state === 'dag_or_executing') {
    if (attempt.status !== 'running') throw new TypeError('executing Workbench state requires a running attempt')
    return {
      schema_version: 'research-workbench-aggregate-v1', projection_kind: 'research-v3-current', orchestration_version: 'research-v3',
      run_id: runId, workflow, approvals, provenance, requirement, candidates, selected_plan: selectedPlan, attempt,
      recovery: null, evidence: null, deliverable: null, review: null, report: null,
    }
  }

  if (workflow.state === 'paused') {
    if (attempt.status !== 'paused') throw new TypeError('paused Workbench state requires a paused attempt and recovery')
    const recovery = parseRecovery(root.recovery)
    if (!attempt.steps.some((step) => step.step_number === recovery.failed_step_number && step.status === 'failed')) {
      throw new TypeError('Workbench recovery must identify a failed step')
    }
    return {
      schema_version: 'research-workbench-aggregate-v1', projection_kind: 'research-v3-current', orchestration_version: 'research-v3',
      run_id: runId, workflow, approvals, provenance, requirement, candidates, selected_plan: selectedPlan, attempt, recovery,
      evidence: null, deliverable: null, review: null, report: null,
    }
  }

  const evidence = parseEvidence(root.evidence)
  const deliverable = parseDeliverable(root.deliverable)
  const review = parseReview(root.review)
  const report = parseReport(root.report)
  validateReportLineage(runId, requirement, selectedPlan, attempt, evidence, deliverable, review, report)
  return {
    schema_version: 'research-workbench-aggregate-v1', projection_kind: 'research-v3-current', orchestration_version: 'research-v3',
    run_id: runId, workflow, approvals, provenance, requirement, candidates, selected_plan: selectedPlan, attempt,
    recovery: null, evidence, deliverable, review, report,
  }
}

function validateHistory(root: Record<string, unknown>): ResearchV2HistoryWorkbenchAggregateV1 {
  exactKeys(
    root,
    ['schema_version', 'projection_kind', 'orchestration_version', 'read_only', 'run_id', 'history_payload', 'provenance'],
    'research-v2 history workbench aggregate',
  )
  requireLiteral(root.orchestration_version, 'research-v2', 'orchestration_version')
  requireLiteral(root.read_only, true, 'read_only')
  const provenance = parseProvenance(root.provenance, 'provenance')
  if (provenance.source_kind !== 'v2_history_adapter') {
    throw new TypeError('research-v2 history requires v2_history_adapter provenance')
  }
  return {
    schema_version: 'research-workbench-aggregate-v1',
    projection_kind: 'research-v2-history',
    orchestration_version: 'research-v2',
    read_only: true,
    run_id: requireString(root.run_id, 'run_id'),
    history_payload: { ...record(root.history_payload, 'history_payload') },
    provenance,
  }
}

declare const trustedValidatedAggregate: unique symbol
type TrustedValidatedWorkbenchAggregate = WorkbenchAggregateV1 & {
  readonly [trustedValidatedAggregate]: true
}

function validateTrustedAggregate(root: Record<string, unknown>): TrustedValidatedWorkbenchAggregate {
  if (root.projection_kind === 'research-v3-current') {
    return validateCurrent(root) as TrustedValidatedWorkbenchAggregate
  }
  if (root.projection_kind === 'research-v2-history') {
    return validateHistory(root) as TrustedValidatedWorkbenchAggregate
  }
  throw new TypeError('Unsupported workbench projection kind')
}

const CANONICAL_IDENTITY_KEYS = new Set([
  'schema_version', 'projection_kind', 'orchestration_version', 'content_hash', 'plan_hash', 'contract_hash',
  'step_contract_hash', 'artifact', 'result_artifact', 'deliverable_artifact', 'review_artifact',
  'evidence_manifest_artifact',
])

function stripCanonicalIdentities(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stripCanonicalIdentities)
  if (value === null || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !CANONICAL_IDENTITY_KEYS.has(key))
      .map(([key, item]) => [key, stripCanonicalIdentities(item)]),
  )
}

function projectForRender(aggregate: TrustedValidatedWorkbenchAggregate): ResearchWorkbenchRenderV1 {
  const projected = stripCanonicalIdentities(aggregate) as Record<string, unknown>
  return {
    ...projected,
    render_schema_version: 'research-workbench-render-v1',
    source_schema_version: 'research-workbench-aggregate-v1',
    render_kind: aggregate.projection_kind === 'research-v3-current' ? 'current' : 'history',
  } as ResearchWorkbenchRenderV1
}

/**
 * Validates unknown JSON at the frozen canonical boundary, applies semantic integrity checks, then
 * returns a distinct render-only model with every sealed/canonical identity removed.
 */
export function adaptWorkbenchAggregate(input: unknown): ResearchWorkbenchRenderV1 {
  validateCanonicalWorkbenchSchema(input)
  const root = record(input, 'workbench aggregate')
  requireLiteral(root.schema_version, 'research-workbench-aggregate-v1', 'schema_version')
  return projectForRender(validateTrustedAggregate(root))
}
