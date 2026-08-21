import type {
  ResearchV2HistoryWorkbenchRenderV1,
  ResearchV3WorkbenchRenderV1,
  ResearchWorkbenchRenderV1,
  WorkbenchState,
} from './types'

export interface CurrentWorkbenchPresentation {
  kind: 'current'
  state: WorkbenchState
  stateLabel: string
  aggregate: ResearchV3WorkbenchRenderV1
  showWelcome: boolean
  showRequirement: boolean
  showClarification: boolean
  showCandidates: boolean
  showPlan: boolean
  showApproval: boolean
  showDag: boolean
  showRecovery: boolean
  showReport: boolean
}

export interface HistoryWorkbenchPresentation {
  kind: 'history'
  aggregate: ResearchV2HistoryWorkbenchRenderV1
  title: string
  status: string | null
  request: string | null
  summary: string | null
}

export type WorkbenchPresentation = CurrentWorkbenchPresentation | HistoryWorkbenchPresentation

const STATE_LABELS: Record<WorkbenchState, string> = {
  idle: '等待研究任务',
  clarify: '澄清需求',
  candidates: '选择方案',
  plan: '确认计划',
  approval: '等待授权',
  dag_or_executing: '执行研究',
  paused: '执行已暂停',
  text_report: '研究报告',
}

function firstString(payload: Record<string, unknown>, keys: readonly string[]): string | null {
  for (const key of keys) {
    const value = payload[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return null
}

function presentHistory(aggregate: ResearchV2HistoryWorkbenchRenderV1): HistoryWorkbenchPresentation {
  const payload = aggregate.history_payload
  return {
    kind: 'history',
    aggregate,
    title: firstString(payload, ['title', 'research_goal']) ?? '历史研究任务',
    status: firstString(payload, ['status', 'phase']),
    request: firstString(payload, ['original_input', 'input_text', 'research_goal']),
    // Only report-level fields are eligible for compatibility display. Tool output/artifact fields are never inspected.
    summary: firstString(payload, ['report_summary', 'executive_summary', 'answer']),
  }
}

export function presentWorkbench(aggregate: ResearchWorkbenchRenderV1): WorkbenchPresentation {
  if (aggregate.render_kind === 'history') return presentHistory(aggregate)

  const state = aggregate.workflow.state
  return {
    kind: 'current',
    state,
    stateLabel: STATE_LABELS[state],
    aggregate,
    showWelcome: state === 'idle',
    showRequirement: state !== 'idle' && state !== 'clarify',
    showClarification: state === 'clarify',
    showCandidates: state === 'candidates',
    showPlan: state === 'plan' || state === 'approval',
    showApproval: state === 'approval',
    showDag: state === 'dag_or_executing' || state === 'paused' || state === 'text_report',
    showRecovery: state === 'paused',
    showReport: state === 'text_report',
  }
}
