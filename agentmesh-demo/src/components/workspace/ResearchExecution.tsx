import {
  Check,
  Circle,
  Clock3,
  X,
} from 'lucide-react'

import type { ResearchRunProjection } from '../../features/workspace/types'
import { ResearchResults } from './ResearchResults'

interface ResearchExecutionProps {
  projection: ResearchRunProjection
}

const STEP_STATUS: Record<string, string> = {
  pending: '等待上游步骤',
  ready: '等待执行',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  skipped: '已跳过',
  cancelled: '已取消',
}

const STEP_TITLE: Record<number, string> = {
  1: '检索并封存外部证据',
  2: '生成、校验并交付竞品分析',
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <Check className="h-4 w-4 text-mint-300" aria-hidden="true" />
  if (status === 'running') return <Clock3 className="h-4 w-4 text-amber-200" aria-hidden="true" />
  if (status === 'failed' || status === 'cancelled') {
    return <X className="h-4 w-4 text-rose" aria-hidden="true" />
  }
  return <Circle className="h-4 w-4 text-slate-400" aria-hidden="true" />
}

export function ResearchExecution({ projection }: ResearchExecutionProps) {
  const attempt = projection.attempt

  return (
    <section aria-label="研究执行与结果" className="mt-4 space-y-4">
      <p role="status" className="rounded-soft border border-white/[0.06] bg-base px-4 py-3 text-sm text-slate-400">
        Research v2 已退役；以下内容是只读历史记录，不提供继续执行或状态变更操作。
      </p>

      {attempt ? (
        <section aria-labelledby="research-progress-title" className="rounded-soft border border-white/[0.07] bg-surface-1 p-5 shadow-card">
          <div>
            <h3 id="research-progress-title" className="text-sm font-semibold text-slate-100">执行进度</h3>
            <p className="mt-1 text-xs text-slate-400">
              第 {attempt.attempt_number} 次 Attempt · {STEP_STATUS[attempt.status] ?? attempt.status}
            </p>
          </div>
          <ol aria-live="polite" className="mt-4 space-y-2">
            {(attempt.steps ?? []).map((step) => (
              <li key={step.step_number} className="flex items-start gap-3 rounded-soft bg-base/70 px-4 py-3">
                <StatusIcon status={step.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-200">{STEP_TITLE[step.step_number] ?? `步骤 ${step.step_number}`}</p>
                    <span className="text-xs text-slate-400">{STEP_STATUS[step.status] ?? step.status}</span>
                  </div>
                  {step.error_code ? <p className="mt-1 break-all text-xs text-rose">{step.error_code}</p> : null}
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <ResearchResults projection={projection} />
    </section>
  )
}
