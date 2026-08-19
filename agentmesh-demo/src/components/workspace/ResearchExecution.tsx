import {
  Check,
  Circle,
  Clock3,
  FileSearch,
  RefreshCcw,
  ShieldCheck,
  TriangleAlert,
  X,
} from 'lucide-react'

import type { ResearchRunProjection } from '../../features/workspace/types'
import { Button } from '../ui/Button'
import { ResearchResults } from './ResearchResults'

export type ResearchPendingAction =
  | 'confirm'
  | 'execute'
  | 'approve-tool'
  | 'reject-tool'
  | 'retry'
  | 'abort'
  | 'cancel'
  | null

interface ResearchExecutionProps {
  projection: ResearchRunProjection
  pendingAction: ResearchPendingAction
  executionEnabled?: boolean
  error?: string | null
  onConfirmPlan: (planVersionId: string, stateVersion: number) => void
  onExecute: (stateVersion: number) => void
  onResolveTool: (itemId: string, callId: string, action: 'approve' | 'reject') => void
  onRecover: (invocationId: string, stateVersion: number, action: 'retry' | 'abort') => void
  onCancel?: () => void
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
  return <Circle className="h-4 w-4 text-slate-600" aria-hidden="true" />
}

export function ResearchExecution({
  projection,
  pendingAction,
  executionEnabled = true,
  error,
  onConfirmPlan,
  onExecute,
  onResolveTool,
  onRecover,
  onCancel,
}: ResearchExecutionProps) {
  const { workflow } = projection
  const plan = projection.plans?.find((item) => item.recommended) ?? projection.plans?.[0]
  const approval = projection.tool_approval
  const recovery = projection.recovery
  const attempt = projection.attempt
  const terminal = workflow.phase === 'terminal'

  return (
    <section aria-label="研究执行与结果" className="mt-4 space-y-4">
      {error ? (
        <p role="alert" className="rounded-[10px] border border-rose/25 bg-rose/10 px-4 py-3 text-sm text-rose">
          {error}
        </p>
      ) : null}

      {workflow.active_gate === 'plan_confirmation' ? (
        <section aria-labelledby="research-plan-action" className="rounded-[14px] border border-mint-400/15 bg-surface-1 p-5 shadow-card">
          <h3 id="research-plan-action" className="text-sm font-semibold text-slate-100">确认研究计划</h3>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            这一步只确认 Tool → Skill 计划，不会批准工具调用，也不会访问 Provider。
          </p>
          <div className="mt-4">
            <Button
              size="sm"
              loading={pendingAction === 'confirm'}
              disabled={!plan}
              icon={<Check className="h-4 w-4" />}
              onClick={() => plan && onConfirmPlan(plan.plan_version_id, workflow.state_version)}
            >
              确认此计划
            </Button>
          </div>
        </section>
      ) : null}

      {workflow.phase === 'planning' && workflow.active_gate === 'none' && !attempt ? (
        <section aria-labelledby="research-execute-action" className="rounded-[14px] border border-white/[0.07] bg-surface-1 p-5 shadow-card">
          <h3 id="research-execute-action" className="text-sm font-semibold text-slate-100">计划已确认</h3>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            开始后系统会先判断 web_research 是否还需要独立审批，再进入实际执行。
          </p>
          {executionEnabled ? <div className="mt-4">
            <Button
              size="sm"
              loading={pendingAction === 'execute'}
              icon={<FileSearch className="h-4 w-4" />}
              onClick={() => onExecute(workflow.state_version)}
            >
              开始执行研究
            </Button>
          </div> : (
            <p role="status" className="mt-3 rounded-[9px] bg-base/70 px-3 py-2 text-sm text-slate-400">
              当前为预览或关闭模式；计划已保存，但不会调用 Tool 或 Provider。
            </p>
          )}
        </section>
      ) : null}

      {workflow.active_gate === 'tool_approval' ? (
        <section aria-labelledby="research-tool-approval" className="rounded-[14px] border border-amber-300/20 bg-amber-300/[0.06] p-5">
          <div className="flex items-center gap-2 text-amber-100">
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
            <h3 id="research-tool-approval" className="text-sm font-semibold">独立 Tool Approval</h3>
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            计划已经确认，但 Provider 尚未被调用。批准只作用于本次 {approval?.tool_name ?? 'web_research'} 调用。
          </p>
          {!executionEnabled ? <p role="status" className="mt-2 text-sm text-rose">执行已关闭，不能批准新的 Provider 调用。</p> : null}
          {approval ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                size="sm"
                loading={pendingAction === 'approve-tool'}
                disabled={pendingAction !== null || !executionEnabled}
                icon={<Check className="h-4 w-4" />}
                onClick={() => onResolveTool(approval.inbox_item_id, approval.call_id, 'approve')}
              >
                批准工具调用
              </Button>
              <Button
                variant="danger"
                size="sm"
                loading={pendingAction === 'reject-tool'}
                disabled={pendingAction !== null || !executionEnabled}
                icon={<X className="h-4 w-4" />}
                onClick={() => onResolveTool(approval.inbox_item_id, approval.call_id, 'reject')}
              >
                拒绝并终止
              </Button>
            </div>
          ) : (
            <p role="alert" className="mt-3 text-sm text-rose">审批身份校验失败，系统已停止执行。</p>
          )}
        </section>
      ) : null}

      {workflow.active_gate === 'recovery_decision' ? (
        <section aria-labelledby="research-recovery-action" className="rounded-[14px] border border-rose/25 bg-rose/[0.08] p-5">
          <div className="flex items-center gap-2 text-rose">
            <TriangleAlert className="h-5 w-5" aria-hidden="true" />
            <h3 id="research-recovery-action" className="text-sm font-semibold">外部结果未知</h3>
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            系统没有自动重试。再次发送可能产生第二次 Provider 请求，请先确认上一请求未完成。
          </p>
          {!executionEnabled ? <p role="status" className="mt-2 text-sm text-rose">执行已关闭；仍可安全终止，但不能再次发送。</p> : null}
          {recovery ? (
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="sm"
                loading={pendingAction === 'retry'}
                disabled={pendingAction !== null || !executionEnabled}
                icon={<RefreshCcw className="h-4 w-4" />}
                onClick={() => onRecover(recovery.invocation_id, workflow.state_version, 'retry')}
              >
                确认后再次发送
              </Button>
              <Button
                variant="danger"
                size="sm"
                loading={pendingAction === 'abort'}
                disabled={pendingAction !== null}
                onClick={() => onRecover(recovery.invocation_id, workflow.state_version, 'abort')}
              >
                安全终止
              </Button>
            </div>
          ) : (
            <p role="alert" className="mt-3 text-sm text-rose">恢复记录缺失，系统不会继续发送。</p>
          )}
        </section>
      ) : null}

      {attempt ? (
        <section aria-labelledby="research-progress-title" className="rounded-[14px] border border-white/[0.07] bg-surface-1 p-5 shadow-card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 id="research-progress-title" className="text-sm font-semibold text-slate-100">执行进度</h3>
              <p className="mt-1 text-xs text-slate-500">第 {attempt.attempt_number} 次 Attempt · {STEP_STATUS[attempt.status] ?? attempt.status}</p>
            </div>
            {!terminal && workflow.active_gate === 'none' && onCancel ? (
              <Button variant="danger" size="sm" loading={pendingAction === 'cancel'} onClick={onCancel}>取消运行</Button>
            ) : null}
          </div>
          <ol aria-live="polite" className="mt-4 space-y-2">
            {(attempt.steps ?? []).map((step) => (
              <li key={step.step_number} className="flex items-start gap-3 rounded-[10px] bg-base/70 px-4 py-3">
                <StatusIcon status={step.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-200">{STEP_TITLE[step.step_number] ?? `步骤 ${step.step_number}`}</p>
                    <span className="text-xs text-slate-500">{STEP_STATUS[step.status] ?? step.status}</span>
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
