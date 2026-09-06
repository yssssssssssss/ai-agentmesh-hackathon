import {
  Activity,
  Bot,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  GitBranch,
  Milestone,
  RefreshCw,
} from 'lucide-react'

import type { components } from '../../api/generated/schema'
import type {
  AgentQueueState,
  TaskOperationsSnapshot,
  TaskOperationsTask,
  TaskReadinessState,
} from '../../features/tasks/types'
import { cn } from '../../lib/cn'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'

export type OperationsSection = 'overview' | 'calendar' | 'agents'

const READINESS_LABELS: Record<TaskReadinessState, string> = {
  backlog: '待规划',
  waiting_dependencies: '等待依赖',
  blocked: '已阻塞',
  planned: '已计划',
  ready: '可执行',
  running: '运行中',
  review: '审核中',
  done: '已完成',
  cancelled: '已取消',
  archived: '已归档',
}

const QUEUE_LABELS: Record<AgentQueueState, string> = {
  backlog: '待规划',
  planned: '已计划',
  waiting_dependencies: '等待依赖',
  blocked: '已阻塞',
  ready: '可执行',
  running: '运行中',
  review: '审核中',
}

const DATE_FORMAT = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  year: 'numeric',
})

function formatDate(value: string | null | undefined): string {
  return value ? DATE_FORMAT.format(new Date(value)) : '未设置'
}

function readinessTone(state: TaskReadinessState): 'mint' | 'rose' | 'remind' | 'neutral' | 'collab' {
  if (state === 'ready' || state === 'done') return 'mint'
  if (state === 'blocked' || state === 'cancelled') return 'rose'
  if (state === 'waiting_dependencies' || state === 'review') return 'remind'
  if (state === 'running') return 'collab'
  return 'neutral'
}

function TaskLink({ task, compact = false }: { task: TaskOperationsTask; compact?: boolean }) {
  return (
    <a
      href={task.navigation_href}
      className="group block min-h-10 rounded-lg px-2 py-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
    >
      <span className={cn('block font-medium text-slate-200 group-hover:text-white', compact ? 'text-xs' : 'text-sm')}>
        {task.title}
      </span>
      <span className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <Badge tone={readinessTone(task.readiness.state)}>{READINESS_LABELS[task.readiness.state]}</Badge>
        <span>{formatDate(task.due_at)}</span>
      </span>
    </a>
  )
}

function MetricStrip({ data }: { data: TaskOperationsSnapshot }) {
  const metrics = [
    { label: '开放任务', value: data.metrics.open_task_count, icon: Activity, tone: 'text-mint-300' },
    { label: '可执行', value: data.metrics.tasks_by_readiness.ready ?? 0, icon: CheckCircle2, tone: 'text-mint-300' },
    { label: '阻塞', value: data.metrics.blocked_task_count, icon: CircleAlert, tone: 'text-rose' },
    { label: '逾期', value: data.metrics.overdue_task_count, icon: Clock3, tone: 'text-remind' },
    { label: '活跃 Run', value: data.metrics.active_run_count, icon: Bot, tone: 'text-sky-300' },
    { label: '我的记忆引用', value: data.metrics.cited_memory_use_count, icon: GitBranch, tone: 'text-knowledge' },
  ]
  return (
    <section aria-label="项目运营指标" className="grid grid-cols-2 overflow-hidden rounded-[12px] bg-surface-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] md:grid-cols-3 xl:grid-cols-6">
      {metrics.map(({ label, value, icon: Icon, tone }, index) => (
        <div key={label} className={cn('min-w-0 px-4 py-4', index > 0 ? 'border-l border-white/[0.06]' : '', index >= 2 ? 'max-md:border-t' : '', index >= 3 ? 'md:max-xl:border-t' : '')}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-slate-500">{label}</span>
            <Icon className={cn('h-4 w-4', tone)} aria-hidden="true" />
          </div>
          <div className="mt-2 text-2xl font-semibold tabular-nums text-slate-100">{value}</div>
        </div>
      ))}
    </section>
  )
}

function Overview({ data }: { data: TaskOperationsSnapshot }) {
  return (
    <div className="space-y-5">
      <MetricStrip data={data} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
        <section aria-labelledby="critical-chain-title" className="rounded-[12px] bg-surface-1 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
          <div className="flex items-center gap-2">
            <GitBranch className="h-4 w-4 text-mint-300" aria-hidden="true" />
            <h2 id="critical-chain-title" className="text-sm font-semibold text-slate-200">关键依赖链</h2>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">按依赖层级计算最长未完成链路，不伪造工期预测。</p>
          {data.critical_dependency_chain_truncated ? (
            <p className="mt-2 text-[11px] text-remind">链路共 {data.critical_dependency_chain_total} 项，显示最接近交付端的 100 项。</p>
          ) : null}
          {data.critical_dependency_chain.length > 0 ? (
            <ol className="mt-4 space-y-1">
              {data.critical_dependency_chain.map((task, index) => (
                <li key={task.id} className="grid grid-cols-[28px_minmax(0,1fr)] items-start gap-2">
                  <span className="mt-2 flex h-6 w-6 items-center justify-center rounded-full bg-mint-400/10 text-[11px] font-semibold tabular-nums text-mint-300">{index + 1}</span>
                  <TaskLink task={task} />
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-4 rounded-lg bg-white/[0.03] px-3 py-4 text-sm text-slate-500">当前没有两级以上的未完成依赖链。</p>
          )}
        </section>

        <section aria-labelledby="milestone-title" className="rounded-[12px] bg-surface-1 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
          <div className="flex items-center gap-2">
            <Milestone className="h-4 w-4 text-remind" aria-hidden="true" />
            <h2 id="milestone-title" className="text-sm font-semibold text-slate-200">近期里程碑</h2>
          </div>
          <div className="mt-4 space-y-4">
            {data.milestones.slice(0, 6).map((item) => (
              <article key={item.task.id}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1"><TaskLink task={item.task} compact /></div>
                  <span className={cn('text-sm font-semibold tabular-nums', item.overdue ? 'text-rose' : 'text-slate-200')}>{item.progress_percent}%</span>
                </div>
                <div
                  className="mt-2 h-1.5 overflow-hidden rounded-pill bg-white/[0.06]"
                  role="progressbar"
                  aria-label={`${item.task.title} 完成进度`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={item.progress_percent}
                >
                  <div className="h-full rounded-pill bg-mint-400" style={{ width: `${item.progress_percent}%` }} />
                </div>
                <p className="mt-1.5 text-[11px] text-slate-600">{item.completed_descendant_count}/{item.descendant_count} 个下级任务完成</p>
              </article>
            ))}
            {data.milestones_truncated ? (
              <p className="text-[11px] text-remind">共 {data.milestone_total} 个里程碑，仅显示最近 50 个。</p>
            ) : null}
            {data.milestones.length === 0 ? <p className="text-sm text-slate-500">当前项目还没有里程碑。</p> : null}
          </div>
        </section>
      </div>

      <section aria-labelledby="flow-metrics-title" className="rounded-[12px] bg-surface-1 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
        <h2 id="flow-metrics-title" className="text-sm font-semibold text-slate-200">流程事实</h2>
        <dl className="mt-4 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2 xl:grid-cols-5">
          <Fact label="待审核" value={data.metrics.pending_review_count} />
          <Fact label="已完成 Task" value={data.metrics.tasks_by_stage.done ?? 0} />
          <Fact label="我的 Memory 使用" value={data.metrics.memory_use_count} />
          <Fact label="我的复用 Memory 数" value={data.metrics.unique_reused_memory_count} />
          <Fact label="已接受团队知识" value={data.metrics.accepted_team_knowledge_count} />
        </dl>
      </section>
    </div>
  )
}

function Fact({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-white/[0.05] pb-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium tabular-nums text-slate-200">{value}</dd>
    </div>
  )
}

function CalendarView({
  data,
  onPeriodPrevious,
  onPeriodNext,
  onPreviousPage,
  onNextPage,
}: {
  data: TaskOperationsSnapshot
  onPeriodPrevious: () => void
  onPeriodNext: () => void
  onPreviousPage: () => void
  onNextPage: () => void
}) {
  return (
    <section aria-labelledby="calendar-title" className="rounded-[12px] bg-surface-1 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2"><CalendarDays className="h-4 w-4 text-mint-300" aria-hidden="true" /><h2 id="calendar-title" className="text-sm font-semibold text-slate-200">项目日历</h2></div>
          <p className="mt-1 text-xs text-slate-500">{formatDate(data.calendar.range_start)} 至 {formatDate(data.calendar.range_end)}</p>
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" icon={<ChevronLeft className="h-4 w-4" />} onClick={onPeriodPrevious}>上一时间段</Button>
          <Button size="sm" variant="ghost" icon={<ChevronRight className="h-4 w-4" />} onClick={onPeriodNext}>下一时间段</Button>
        </div>
      </div>
      <p className="mt-3 text-right text-xs tabular-nums text-slate-500">{data.calendar.total} 项到期安排</p>
      <div className="mt-2 divide-y divide-white/[0.06]">
        {data.calendar.items.map((item) => (
          <article key={item.task.id} className="grid gap-2 py-3 sm:grid-cols-[110px_minmax(0,1fr)_auto] sm:items-center">
            <span className={cn('text-xs tabular-nums', item.overdue ? 'text-rose' : 'text-slate-400')}>{formatDate(item.task.due_at)}</span>
            <TaskLink task={item.task} compact />
            {item.task.task_type === 'milestone' ? <Badge tone="remind">里程碑</Badge> : null}
          </article>
        ))}
        {data.calendar.items.length === 0 ? <p className="py-10 text-center text-sm text-slate-500">当前时间范围内没有到期任务。</p> : null}
      </div>
      <Pagination page={data.calendar.page} hasNext={data.calendar.has_next} onPrevious={onPreviousPage} onNext={onNextPage} />
    </section>
  )
}

function AgentQueue({
  data,
  agents,
  selectedAgentId,
  onAgentChange,
  onPreviousPage,
  onNextPage,
}: {
  data: TaskOperationsSnapshot
  agents: components['schemas']['Agent'][]
  selectedAgentId: string
  onAgentChange: (value: string) => void
  onPreviousPage: () => void
  onNextPage: () => void
}) {
  return (
    <section aria-labelledby="agent-queue-title" className="rounded-[12px] bg-surface-1 p-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2"><Bot className="h-4 w-4 text-sky-300" aria-hidden="true" /><h2 id="agent-queue-title" className="text-sm font-semibold text-slate-200">Agent 队列</h2></div>
          <p className="mt-1 text-xs leading-5 text-slate-500">仅展示服务端判定的排队状态，不会自动启动任务。</p>
        </div>
        <label className="text-xs font-medium text-slate-400">
          Agent
          <select value={selectedAgentId} onChange={(event) => onAgentChange(event.target.value)} className="ml-2 h-10 rounded-lg border border-white/[0.08] bg-surface-2 px-3 text-sm text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">
            <option value="">全部 Agent</option>
            {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
          </select>
        </label>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[700px] border-collapse text-left text-sm">
          <thead className="text-xs text-slate-500"><tr><th scope="col" className="px-3 py-2">任务</th><th scope="col" className="px-3 py-2">队列状态</th><th scope="col" className="px-3 py-2">Agent</th><th scope="col" className="px-3 py-2">Run</th><th scope="col" className="px-3 py-2 text-right">依赖</th></tr></thead>
          <tbody className="divide-y divide-white/[0.06]">
            {data.agent_queue.items.map((item) => (
              <tr key={item.task.id}>
                <td className="px-1 py-1"><TaskLink task={item.task} compact /></td>
                <td className="px-3 py-3"><Badge tone={readinessTone(item.task.readiness.state)}>{QUEUE_LABELS[item.queue_state]}</Badge></td>
                <td className="px-3 py-3 text-xs text-slate-400">{agents.find((agent) => agent.id === item.task.assignee_id)?.name ?? item.task.assignee_id}</td>
                <td className="px-3 py-3 text-xs text-slate-500">{item.active_run_status ?? '—'}</td>
                <td className="px-3 py-3 text-right tabular-nums text-slate-400">{item.task.readiness.completed_dependency_count}/{item.task.readiness.dependency_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.agent_queue.items.length === 0 ? <p className="py-10 text-center text-sm text-slate-500">当前筛选下没有 Agent 任务。</p> : null}
      </div>
      <Pagination page={data.agent_queue.page} hasNext={data.agent_queue.has_next} onPrevious={onPreviousPage} onNext={onNextPage} />
    </section>
  )
}

function Pagination({ page, hasNext, onPrevious, onNext }: { page: number; hasNext: boolean; onPrevious: () => void; onNext: () => void }) {
  return (
    <div className="mt-4 flex items-center justify-end gap-2 border-t border-white/[0.06] pt-3">
      <Button size="sm" variant="ghost" icon={<ChevronLeft className="h-4 w-4" />} disabled={page <= 1} onClick={onPrevious}>上一页</Button>
      <span className="min-w-12 text-center text-xs tabular-nums text-slate-500">第 {page} 页</span>
      <Button size="sm" variant="ghost" icon={<ChevronRight className="h-4 w-4" />} disabled={!hasNext} onClick={onNext}>下一页</Button>
    </div>
  )
}

export function ProjectOperationsPanel({
  section,
  data,
  loading,
  error,
  agents,
  selectedAgentId,
  onAgentChange,
  onRetry,
  onCalendarPeriodPrevious,
  onCalendarPeriodNext,
  onCalendarPrevious,
  onCalendarNext,
  onQueuePrevious,
  onQueueNext,
}: {
  section: OperationsSection
  data: TaskOperationsSnapshot | undefined
  loading: boolean
  error: string | null
  agents: components['schemas']['Agent'][]
  selectedAgentId: string
  onAgentChange: (value: string) => void
  onRetry: () => void
  onCalendarPeriodPrevious: () => void
  onCalendarPeriodNext: () => void
  onCalendarPrevious: () => void
  onCalendarNext: () => void
  onQueuePrevious: () => void
  onQueueNext: () => void
}) {
  if (error) {
    return (
      <section role="alert" className="flex flex-wrap items-center justify-between gap-4 rounded-[12px] bg-rose/10 p-4 text-sm text-rose ring-1 ring-inset ring-rose/20">
        <div><p className="font-medium">项目运营数据读取失败</p><p className="mt-1 text-xs text-rose/80">{error}</p></div>
        <Button size="sm" variant="subtle" icon={<RefreshCw className="h-4 w-4" />} onClick={onRetry}>重试</Button>
      </section>
    )
  }
  if (loading || !data) {
    return <section aria-busy="true" aria-label="正在读取项目运营数据" className="h-72 animate-pulse rounded-[12px] bg-surface-1" />
  }
  if (section === 'calendar') {
    return (
      <CalendarView
        data={data}
        onPeriodPrevious={onCalendarPeriodPrevious}
        onPeriodNext={onCalendarPeriodNext}
        onPreviousPage={onCalendarPrevious}
        onNextPage={onCalendarNext}
      />
    )
  }
  if (section === 'agents') {
    return (
      <AgentQueue
        data={data}
        agents={agents}
        selectedAgentId={selectedAgentId}
        onAgentChange={onAgentChange}
        onPreviousPage={onQueuePrevious}
        onNextPage={onQueueNext}
      />
    )
  }
  return <Overview data={data} />
}
