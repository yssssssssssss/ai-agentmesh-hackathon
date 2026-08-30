import {
  Activity,
  Check,
  Circle,
  GitBranch,
  Loader2,
  Pause,
  ShieldAlert,
  Square,
  TriangleAlert,
  X,
} from 'lucide-react'

import type { AgentRun, Skill, SkillPlanDetailResponse, SkillPlanNode } from '../../features/workspace/types'
import { Button } from '../ui/Button'
import { SkillPlanNodeCard } from './SkillPlanNodeCard'
import { degradationCopy, failureReason } from './skillPlanPresentation'

interface SkillPlanProgressProps {
  run: AgentRun
  detail: SkillPlanDetailResponse
  skillsById: ReadonlyMap<string, Skill>
  cancelling: boolean
  onCancel: () => void
  onOpenToolApproval: () => void
}

const RUN_STATUS_LABEL = {
  created: '正在准备执行计划',
  planning: '正在准备执行计划',
  waiting_plan_approval: '等待你确认计划',
  running: '执行计划进行中',
  waiting_approval: '需要确认高风险操作',
  completed: '执行完成',
  partial: '部分结果已生成',
  failed: '执行未完成',
  rejected: '计划已拒绝',
  cancelled: '执行已取消',
} as const

function hasParallelPath(nodes: SkillPlanNode[], detail: SkillPlanDetailResponse): boolean {
  const relation = detail.plan.routing_result?.task.execution_relation
  if (relation === 'parallel' || relation === 'parallel_then_merge') return true
  const groupCounts = new Map<string, number>()
  for (const node of nodes) {
    if (!node.parallel_group) continue
    groupCounts.set(node.parallel_group, (groupCounts.get(node.parallel_group) ?? 0) + 1)
  }
  return [...groupCounts.values()].some((count) => count > 1)
}

export function SkillPlanProgress({
  run,
  detail,
  skillsById,
  cancelling,
  onCancel,
  onOpenToolApproval,
}: SkillPlanProgressProps) {
  const nodes = detail.plan.nodes ?? []
  const resultsByNode = new Map((detail.results ?? []).map((result) => [result.node_id, result]))
  const active = ['created', 'planning', 'running', 'waiting_approval'].includes(run.status)
  const previewOnly = run.status === 'completed' && detail.plan.status === 'approved'
  const statusLabel = previewOnly ? '计划已确认，预览模式未执行' : RUN_STATUS_LABEL[run.status]
  const runningNodes = nodes.filter((node) => node.status === 'running')
  const approvalNodes = nodes.filter((node) => node.status === 'waiting_tool_approval')
  const failedNodes = nodes.filter((node) => node.status === 'failed')
  const completedCount = nodes.filter((node) => node.status === 'completed').length
  const queuedCount = nodes.filter((node) => node.status === 'pending' || node.status === 'ready').length
  const parallel = hasParallelPath(nodes, detail)
  const planNotice = detail.plan.degradation ? degradationCopy(detail.plan.degradation) : null
  const activityTitle = runningNodes.length > 1
    ? `正在同时处理 ${runningNodes.length} 个分析步骤`
    : runningNodes.length === 1
      ? `正在处理：${skillsById.get(runningNodes[0].skill_id)?.title ?? runningNodes[0].skill_id}`
      : queuedCount > 0
        ? '正在准备下一批可执行步骤'
        : '等待当前状态更新'

  return (
    <section aria-labelledby="skill-plan-progress-title" className="mt-6 rounded-[14px] bg-surface-1 p-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-mint-300">
            <GitBranch className="h-4 w-4" aria-hidden="true" />
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em]">Skill 执行计划</p>
          </div>
          <h2 id="skill-plan-progress-title" className="mt-2 text-lg font-semibold text-slate-100">
            {statusLabel}
          </h2>
          <p className="mt-1 text-sm leading-6 text-slate-400">{detail.plan.intent.goal}</p>
        </div>
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

      <div className="mt-4 flex flex-wrap gap-2 text-[11px]" aria-label="步骤统计">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.05] px-2.5 py-1 text-slate-400">
          <Circle className="h-3 w-3" aria-hidden="true" />共 {nodes.length} 个步骤
        </span>
        {completedCount > 0 ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-mint-400/10 px-2.5 py-1 text-mint-300">
            <Check className="h-3 w-3" aria-hidden="true" />{completedCount} 个已完成
          </span>
        ) : null}
        {runningNodes.length > 0 ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-mint-400/10 px-2.5 py-1 text-mint-300">
            <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />{runningNodes.length} 个处理中
          </span>
        ) : null}
        {approvalNodes.length > 0 ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-300/10 px-2.5 py-1 text-amber-200">
            <Pause className="h-3 w-3" aria-hidden="true" />{approvalNodes.length} 个等待授权
          </span>
        ) : null}
        {failedNodes.length > 0 ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-rose/10 px-2.5 py-1 text-rose">
            <X className="h-3 w-3" aria-hidden="true" />{failedNodes.length} 个失败
          </span>
        ) : null}
      </div>

      {run.status === 'running' ? (
        <div role="status" aria-live="polite" className="mt-4 rounded-[11px] border border-mint-400/15 bg-mint-400/[0.04] px-4 py-3">
          <div className="flex items-start gap-2.5">
            <Activity className="mt-0.5 h-4 w-4 shrink-0 text-mint-300" aria-hidden="true" />
            <div>
              <p className="text-sm font-semibold text-slate-200">{activityTitle}</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">
                “处理中”表示步骤已开始读取已确认的输入并生成结果，不代表最终结论已经完成。
              </p>
              {parallel ? (
                <p className="mt-1 text-xs leading-5 text-slate-400">
                  这些是同一计划中的不同分析步骤，不是多套方案。它们彼此没有前后依赖，所以同时执行，完成后会合并为一份结果。
                </p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {run.status === 'waiting_approval' ? (
        <section aria-labelledby="tool-approval-explanation" className="mt-4 rounded-[11px] border border-amber-300/20 bg-amber-300/[0.06] px-4 py-3.5">
          <div className="flex items-start gap-2.5">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-200" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <h3 id="tool-approval-explanation" className="text-sm font-semibold text-amber-100">为什么这次仍需要确认？</h3>
              <p className="mt-1 text-xs leading-5 text-slate-300">
                常规只读工具会直接继承你为个人 Agent 配置的权限，不再逐次询问。当前操作涉及写入，或命中了高风险安全策略，因此执行才会暂停。确认只作用于页面中列出的本次操作。
              </p>
              <Button
                className="mt-3"
                variant="secondary"
                size="sm"
                icon={<ShieldAlert className="h-4 w-4" />}
                onClick={onOpenToolApproval}
              >
                查看高风险操作
              </Button>
            </div>
          </div>
        </section>
      ) : null}

      {parallel && run.status !== 'running' && !previewOnly ? (
        <p className="mt-4 rounded-[10px] border border-white/[0.06] bg-base/55 px-3.5 py-3 text-xs leading-5 text-slate-400">
          这是同一计划中的 {nodes.length} 个分析步骤，不是 {nodes.length} 套方案。无前后依赖的步骤可以同时执行，所有可用结果会在最后统一汇总。
        </p>
      ) : null}

      <ol className="mt-5 space-y-2.5" aria-label="Skill 节点执行状态">
        {nodes.map((node) => (
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
        <section role="alert" className="mt-4 rounded-[10px] border border-rose/20 bg-rose/10 px-3.5 py-3">
          <div className="flex items-start gap-2.5">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose" aria-hidden="true" />
            <div>
              <p className="text-xs font-semibold text-rose">为什么执行未完成？</p>
              <p className="mt-1 text-xs leading-5 text-slate-300">{failureReason(run.error_code)}</p>
              <p className="mt-1 text-[11px] leading-5 text-slate-500">
                “失败”只用于工具、Provider、权限、超时或输出校验未完成。需求信息不足应显示为“需要补充”或“部分完成”，不应归因于用户需求本身。
              </p>
              <details className="mt-1.5 text-[10px] text-slate-500">
                <summary className="cursor-pointer select-none hover:text-slate-300">查看技术原因</summary>
                <code className="mt-1 block break-all">{run.error_code}</code>
              </details>
            </div>
          </div>
        </section>
      ) : null}
      {planNotice && detail.plan.degradation ? (
        <section className="mt-4 rounded-[10px] border border-amber-300/15 bg-amber-300/[0.06] px-3.5 py-3">
          <p className="text-xs font-semibold text-amber-100">{planNotice.title}</p>
          <p className="mt-1 text-xs leading-5 text-slate-300">{planNotice.description}</p>
          <details className="mt-1.5 text-[10px] text-slate-500">
            <summary className="cursor-pointer select-none hover:text-slate-300">查看技术诊断</summary>
            <code className="mt-1 block break-all">{detail.plan.degradation}</code>
          </details>
        </section>
      ) : null}
    </section>
  )
}
