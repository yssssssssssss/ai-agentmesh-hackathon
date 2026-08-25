import type { Skill } from './types'

export const DESIGN_STAGE_META = {
  pre_design: { label: '设计前', description: '研究、定义与方向判断', dotClass: 'bg-knowledge' },
  during_design: { label: '设计中', description: '方案生成与验证', dotClass: 'bg-collab' },
  post_design: { label: '设计后', description: '评估、排序与持续度量', dotClass: 'bg-mint-400' },
  other: { label: '未分类 Skill', description: '尚未标注所属设计阶段', dotClass: 'bg-slate-400' },
  tools: { label: '工具', description: '记忆、资料、数据与系统操作', dotClass: 'bg-remind' },
} as const

export type DesignStageKey = keyof typeof DESIGN_STAGE_META

const DESIGN_STAGE_ORDER: DesignStageKey[] = ['pre_design', 'during_design', 'post_design', 'other', 'tools']

function designStageKey(skill: Skill): DesignStageKey {
  if (skill.primary_stage === 'pre_design') return 'pre_design'
  if (skill.primary_stage === 'during_design') return 'during_design'
  if (skill.primary_stage === 'post_design') return 'post_design'
  return skill.command.includes('.') ? 'tools' : 'other'
}

export function isCallableSkill(skill: Skill): boolean {
  const ready = skill.readiness === undefined || skill.readiness === null || skill.readiness === 'ready'
  const executionAvailable = skill.execution_readiness !== 'unavailable'
  return skill.enabled !== false && skill.binding_enabled !== false && ready && executionAvailable
}

export function skillAvailabilityLabel(skill: Skill): string {
  if (!isCallableSkill(skill)) return '未就绪'
  if (skill.execution_readiness === 'tool_limited') return '已接入 · 工具待接通'
  if (skill.command.includes('.')) return '可直接调用'
  return skill.planner_eligible ? '可自动编排' : '可显式调用'
}

export function missingToolsSummary(missingTools: string[] | undefined): string {
  if (!missingTools?.length) return ''
  const visible = missingTools.slice(0, 3).join('、')
  return missingTools.length > 3 ? `${visible} 等 ${missingTools.length} 项` : visible
}

export function groupSkillsByDesignStage(skills: Skill[]) {
  return DESIGN_STAGE_ORDER.flatMap((key) => {
    const items = skills
      .filter((skill) => designStageKey(skill) === key)
      .sort((left, right) => left.title.localeCompare(right.title, 'zh-CN'))
    return items.length > 0 ? [{ key, ...DESIGN_STAGE_META[key], items }] : []
  })
}
