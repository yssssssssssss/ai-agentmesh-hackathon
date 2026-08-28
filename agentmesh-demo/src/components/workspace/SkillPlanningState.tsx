import { BrainCircuit, Route, ShieldCheck, Sparkles, Square } from 'lucide-react'

import type { AgentRun } from '../../features/workspace/types'
import { Button } from '../ui/Button'

interface SkillPlanningStateProps {
  run: AgentRun
  cancelling: boolean
  onCancel: () => void
}

const PLANNING_STAGES = [
  { label: '理解目标', icon: BrainCircuit },
  { label: '匹配任务场景', icon: Route },
  { label: '检查能力与权限', icon: ShieldCheck },
  { label: '生成执行计划', icon: Sparkles },
] as const

export function SkillPlanningState({ run, cancelling, onCancel }: SkillPlanningStateProps) {
  const explicitSkill = Boolean(run.skill_name)
  const title = run.status === 'created'
    ? '正在启动规划器'
    : explicitSkill
      ? '正在验证 Skill 与运行条件'
      : '正在理解任务，并匹配可用能力'

  return (
    <section
      aria-labelledby="skill-planning-title"
      className="mt-6 overflow-hidden rounded-soft border border-mint-400/15 bg-surface-1 shadow-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-5">
        <div className="flex min-w-0 items-start gap-3.5">
          <span className="relative mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-soft bg-mint-400/10 text-mint-300">
            <span className="planning-orbit absolute inset-1 rounded-full border border-transparent border-t-mint-300/80" aria-hidden="true" />
            <BrainCircuit className="h-4 w-4" aria-hidden="true" />
          </span>
          <div role="status" aria-live="polite" className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-mint-300">正在构建执行计划</p>
            <h2 id="skill-planning-title" className="mt-1.5 text-base font-semibold text-slate-100">{title}</h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-400">
              {explicitSkill
                ? `系统正在检查 $${run.skill_name} 的输入、权限和可用工具。`
                : '系统正在把你的请求映射为 Task → Scenario → Skill，并检查资料和工具是否可用。'}
            </p>
          </div>
        </div>
        <Button
          variant="danger"
          size="sm"
          loading={cancelling}
          icon={<Square className="h-3.5 w-3.5" />}
          onClick={onCancel}
        >
          取消规划
        </Button>
      </div>

      <div className="border-t border-white/[0.06] bg-base/45 px-5 py-4">
        <ol className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="规划阶段">
          {PLANNING_STAGES.map(({ label, icon: StageIcon }) => (
            <li key={label} className="planning-stage flex items-center gap-2 text-[11px] text-slate-400">
              <span className="planning-stage-dot flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-white/[0.08] bg-surface-2 text-slate-400">
                <StageIcon className="h-3 w-3" aria-hidden="true" />
              </span>
              {label}
            </li>
          ))}
        </ol>
        <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/[0.05]" aria-hidden="true">
          <span className="planning-scan block h-full w-1/3 rounded-full bg-mint-400" />
        </div>
        <p className="mt-3 text-[11px] leading-5 text-slate-400">
          规划完成后会先展示可确认的步骤。此阶段不会调用外部工具，也不会把处理中内容当作最终结论。
        </p>
      </div>
    </section>
  )
}
