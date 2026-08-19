import { GitBranch, ShieldAlert, Square } from 'lucide-react'

import type { AgentRun, Skill, SkillPlanDetailResponse } from '../../features/workspace/types'
import { Button } from '../ui/Button'
import { SkillPlanNodeCard } from './SkillPlanNodeCard'

interface SkillPlanProgressProps {
  run: AgentRun
  detail: SkillPlanDetailResponse
  skillsById: ReadonlyMap<string, Skill>
  cancelling: boolean
  onCancel: () => void
  onOpenToolApproval: () => void
}

const RUN_STATUS_LABEL = {
  created: '准备中',
  planning: '规划中',
  waiting_plan_approval: '等待计划确认',
  running: '执行中',
  waiting_approval: '等待工具审批',
  completed: '已完成',
  partial: '部分完成',
  failed: '失败',
  rejected: '已拒绝',
  cancelled: '已取消',
} as const

export function SkillPlanProgress({
  run,
  detail,
  skillsById,
  cancelling,
  onCancel,
  onOpenToolApproval,
}: SkillPlanProgressProps) {
  const resultsByNode = new Map((detail.results ?? []).map((result) => [result.node_id, result]))
  const active = ['created', 'planning', 'running', 'waiting_approval'].includes(run.status)
  const previewOnly = run.status === 'completed' && detail.plan.status === 'approved'
  const statusLabel = previewOnly ? '计划已确认，预览模式未执行' : RUN_STATUS_LABEL[run.status]

  return (
    <section aria-labelledby="skill-plan-progress-title" className="mt-6 rounded-[14px] bg-surface-1 p-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-mint-300">
            <GitBranch className="h-4 w-4" aria-hidden="true" />
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em]">Skill plan progress</p>
          </div>
          <h2 id="skill-plan-progress-title" className="mt-2 text-lg font-semibold text-slate-100">
            {statusLabel}
          </h2>
          <p className="mt-1 text-sm leading-6 text-slate-400">{detail.plan.intent.goal}</p>
        </div>
        <div className="flex gap-2">
          {run.status === 'waiting_approval' ? (
            <Button variant="secondary" size="sm" icon={<ShieldAlert className="h-4 w-4" />} onClick={onOpenToolApproval}>
              处理工具审批
            </Button>
          ) : null}
          {active ? (
            <Button
              variant="danger"
              size="sm"
              loading={cancelling}
              icon={<Square className="h-3.5 w-3.5" />}
              onClick={onCancel}
            >
              取消运行
            </Button>
          ) : null}
        </div>
      </div>

      <ol className="mt-5 space-y-2.5" aria-label="Skill 节点执行状态">
        {(detail.plan.nodes ?? []).map((node) => (
          <li key={node.id ?? node.skill_id}>
            <SkillPlanNodeCard
              node={node}
              skill={skillsById.get(node.skill_id)}
              result={node.id ? resultsByNode.get(node.id) : undefined}
              mode="progress"
            />
          </li>
        ))}
      </ol>

      {run.error_code ? (
        <p role="alert" className="mt-4 rounded-[10px] bg-rose/10 px-3.5 py-3 text-xs text-rose">
          运行终止：{run.error_code}
        </p>
      ) : null}
      {detail.plan.degradation ? (
        <p className="mt-4 rounded-[10px] bg-amber-300/[0.07] px-3.5 py-3 text-xs text-amber-200">
          降级：{detail.plan.degradation}
        </p>
      ) : null}
    </section>
  )
}
