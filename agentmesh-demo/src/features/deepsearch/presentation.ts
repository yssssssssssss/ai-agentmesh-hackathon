import type {
  DeepSearchAvailability,
  DeepSearchFinalizationStage,
  DeepSearchState,
} from './types'

const AVAILABILITY_COPY: Record<NonNullable<DeepSearchAvailability['reason_code']>, string> = {
  disabled: 'DeepSearch 尚未开放',
  execution_unavailable: 'DeepSearch 需要执行模式，当前环境仅支持预览',
  runtime_unavailable: 'Agent Runtime 暂不可用',
  model_unavailable: '当前账号没有可用的规划模型',
  planner_unavailable: 'DeepSearch 规划器暂不可用',
}

export function deepSearchAvailabilityMessage(availability: DeepSearchAvailability): string | null {
  if (availability.available) return null
  return availability.reason_code
    ? AVAILABILITY_COPY[availability.reason_code]
    : 'DeepSearch 当前不可用'
}

export const DEEPSEARCH_STAGES = [
  '需求理解',
  '澄清',
  '计划确认',
  '执行',
  'Evidence / Review',
  '报告',
] as const

const FINALIZATION_STAGES = new Set<DeepSearchFinalizationStage>([
  'nodes_terminal',
  'evidence_manifest_sealed',
  'synthesis_v0_saved',
  'coverage_v0_checked',
  'review_v0_checked',
  'synthesis_v1_saved',
  'coverage_v1_checked',
  'review_v1_checked',
  'terminal_committed',
])

export function activeDeepSearchStage(state: DeepSearchState): number {
  if (state.plan?.report_artifact_id) return 5
  if (state.run.status === 'waiting_clarification') return 1
  if (state.run.status === 'waiting_plan_approval') return 2
  if (
    state.plan?.finalization_stage
    && FINALIZATION_STAGES.has(state.plan.finalization_stage)
  ) return 4
  if (state.plan || ['running', 'waiting_approval'].includes(state.run.status)) return 3
  return 0
}

export function deepSearchFinalizationLabel(stage?: DeepSearchFinalizationStage): string {
  if (!stage || stage === 'none') return '等待节点完成'
  if (stage === 'nodes_terminal') return '正在封存 Evidence'
  if (stage === 'evidence_manifest_sealed') return 'Evidence 已封存，正在综合'
  if (stage.startsWith('synthesis_')) return '综合结果已保存，正在检查覆盖'
  if (stage.startsWith('coverage_')) return 'Evidence 覆盖已检查，正在审核'
  if (stage.startsWith('review_')) return '报告审核完成，正在封存'
  return '报告已封存'
}
