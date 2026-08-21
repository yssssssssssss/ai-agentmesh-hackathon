import type {
  ResearchV2HistoryWorkbenchAggregateV1,
  ResearchV3WorkbenchAggregateV1,
  WorkbenchAggregateV1,
  WorkbenchState,
} from './types'

const CURRENT_STATES = new Set<WorkbenchState>([
  'idle',
  'clarify',
  'candidates',
  'plan',
  'approval',
  'dag_or_executing',
  'paused',
  'text_report',
])

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`)
  }
  return value as Record<string, unknown>
}

function requireString(value: unknown, label: string): asserts value is string {
  if (typeof value !== 'string' || value.length === 0) throw new TypeError(`${label} must be a non-empty string`)
}

function requireArray(value: unknown, label: string): asserts value is unknown[] {
  if (!Array.isArray(value)) throw new TypeError(`${label} must be an array`)
}

function validateCommon(root: Record<string, unknown>): void {
  if (root.schema_version !== 'research-workbench-aggregate-v1') {
    throw new TypeError('Unsupported workbench schema version')
  }
  requireString(root.run_id, 'run_id')
  const provenance = record(root.provenance, 'provenance')
  if (provenance.projection_schema_version !== 'research-workbench-aggregate-v1') {
    throw new TypeError('Projection provenance does not match the aggregate schema')
  }
}

function validateCurrent(root: Record<string, unknown>): ResearchV3WorkbenchAggregateV1 {
  if (root.orchestration_version !== 'research-v3') {
    throw new TypeError('research-v3-current requires research-v3 orchestration')
  }
  const workflow = record(root.workflow, 'workflow')
  if (typeof workflow.state !== 'string' || !CURRENT_STATES.has(workflow.state as WorkbenchState)) {
    throw new TypeError('Unsupported research workbench state')
  }
  if (!Number.isInteger(workflow.state_version)) throw new TypeError('workflow.state_version must be an integer')
  record(workflow.gate, 'workflow.gate')
  requireArray(root.approvals, 'approvals')

  if (root.requirement !== null) {
    const requirement = record(root.requirement, 'requirement')
    if (requirement.schema_version !== 'research-task-v3') throw new TypeError('Unsupported requirement schema')
    const task = record(requirement.payload, 'requirement.payload')
    if (task.schema_version !== 'research-task-v3' || task.task_type !== 'competitive_research') {
      throw new TypeError('Only the frozen Competitive Text requirement is supported')
    }
  }
  if (root.candidates !== null) {
    const candidates = record(root.candidates, 'candidates')
    if (candidates.schema_version !== 'plan-candidates-v3') throw new TypeError('Unsupported candidate schema')
    requireArray(candidates.candidates, 'candidates.candidates')
    if (candidates.candidates.length !== 2) throw new TypeError('The frozen candidate set must contain depth and speed')
  }
  if (root.selected_plan !== null) {
    const plan = record(root.selected_plan, 'selected_plan')
    if (plan.schema_version !== 'execution-plan-v3') throw new TypeError('Unsupported execution plan schema')
  }

  return root as unknown as ResearchV3WorkbenchAggregateV1
}

function validateHistory(root: Record<string, unknown>): ResearchV2HistoryWorkbenchAggregateV1 {
  if (root.orchestration_version !== 'research-v2' || root.read_only !== true) {
    throw new TypeError('research-v2 history must be explicitly read-only')
  }
  record(root.history_payload, 'history_payload')
  const provenance = record(root.provenance, 'provenance')
  if (provenance.source_kind !== 'v2_history_adapter') {
    throw new TypeError('research-v2 history requires v2_history_adapter provenance')
  }
  return root as unknown as ResearchV2HistoryWorkbenchAggregateV1
}

/**
 * Narrows fixture/API-shaped JSON by its frozen discriminator before it can reach the renderer.
 * This is intentionally local and is not a production API decoder or a shape-based version fallback.
 */
export function adaptWorkbenchAggregate(input: unknown): WorkbenchAggregateV1 {
  const root = record(input, 'workbench aggregate')
  validateCommon(root)
  if (root.projection_kind === 'research-v3-current') return validateCurrent(root)
  if (root.projection_kind === 'research-v2-history') return validateHistory(root)
  throw new TypeError('Unsupported workbench projection kind')
}
