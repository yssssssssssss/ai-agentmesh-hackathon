import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ChevronRight,
  Clock3,
  Columns3,
  List,
  ListChecks,
  LockKeyhole,
  MessageSquareText,
  RefreshCw,
  RotateCcw,
  Search,
} from 'lucide-react'

import { TaskDetailDrawer } from '../components/tasks/TaskDetailDrawer'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { PageHeader } from '../components/ui/PageHeader'
import { useAuth } from '../features/auth/AuthProvider'
import { collaborationErrorMessage, useTaskCards } from '../features/collaboration/queries'
import {
  buildTaskCenterViewModel,
  TASK_STAGE_OPTIONS,
  TASK_STATUS_OPTIONS,
  type TaskCenterFilters,
  type TaskCenterItem,
  type TaskStageKey,
  type TaskStatusKey,
} from '../features/tasks/presenter'
import { cn } from '../lib/cn'

type ViewMode = 'board' | 'list'

const DATE_TIME_FORMAT = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

function formatDate(value: string | null): string {
  return value ? DATE_TIME_FORMAT.format(new Date(value)) : '暂无时间'
}

export function Tasks() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const context = {
    userId: user?.id ?? '',
    workspaceId: user?.workspace_id ?? '',
    projectId: user?.default_project_id ?? '',
  }
  const cardsQuery = useTaskCards(context)
  const query = searchParams.get('q') ?? ''
  const viewMode: ViewMode = searchParams.get('view') === 'list' ? 'list' : 'board'
  const requestedFilters: Partial<TaskCenterFilters> = {
    query,
    collaborationStage: (searchParams.get('stage') ?? 'all') as TaskStageKey | 'all',
    executionStatus: (searchParams.get('status') ?? 'all') as TaskStatusKey | 'all',
  }
  const view = useMemo(
    () => buildTaskCenterViewModel(cardsQuery.data?.items ?? [], requestedFilters),
    [cardsQuery.data?.items, query, requestedFilters.collaborationStage, requestedFilters.executionStatus],
  )
  const selectedTaskId = searchParams.get('task')?.trim() || null

  const setParameter = (key: string, value: string, defaultValue = '') => {
    const next = new URLSearchParams(searchParams)
    if (!value || value === defaultValue) next.delete(key)
    else next.set(key, value)
    setSearchParams(next, { replace: true })
  }

  const clearFilters = () => {
    const next = new URLSearchParams(searchParams)
    next.delete('q')
    next.delete('stage')
    next.delete('status')
    setSearchParams(next, { replace: true })
  }

  const openTask = (taskId: string) => setParameter('task', taskId)
  const closeTask = () => setParameter('task', '')

  return (
    <div className="space-y-6" lang="zh-CN">
      <PageHeader
        title="任务中心"
        subtitle="查看现有 Agent 与协作流程产生、且当前账号可见的任务。本页只提供观察，不提供创建、编辑或分派。"
        actions={<ViewSwitcher value={viewMode} onChange={(mode) => setParameter('view', mode, 'board')} />}
      />

      {cardsQuery.error ? (
        <section role="alert" className="flex flex-wrap items-center justify-between gap-4 rounded-[12px] border border-rose/25 bg-rose/10 p-4 text-sm text-rose">
          <div>
            <p className="font-medium">任务列表读取失败</p>
            <p className="mt-1 text-xs leading-5 text-rose/80">{collaborationErrorMessage(cardsQuery.error)}</p>
          </div>
          <Button
            size="sm"
            variant="subtle"
            icon={<RefreshCw className="h-4 w-4" />}
            loading={cardsQuery.isFetching}
            onClick={() => void cardsQuery.refetch()}
          >
            重试
          </Button>
        </section>
      ) : cardsQuery.isLoading ? (
        <TaskCenterLoading />
      ) : (
        <>
          <TaskMetrics
            total={view.stats.totalVisible}
            filtered={view.stats.filteredVisible}
            active={view.stats.activeVisible}
            blocked={view.stats.blockedVisible}
            filtersActive={view.hasActiveFilters}
          />

          <TaskFilters
            query={query}
            filters={view.filters}
            resultCount={view.stats.filteredVisible}
            filtersActive={view.hasActiveFilters}
            onQueryChange={(value) => setParameter('q', value)}
            onStageChange={(value) => setParameter('stage', value, 'all')}
            onStatusChange={(value) => setParameter('status', value, 'all')}
            onClear={clearFilters}
          />

          {view.emptyReason ? (
            <TaskCenterEmpty filtered={view.emptyReason === 'no-filter-matches'} onClear={clearFilters} />
          ) : viewMode === 'board' ? (
            <TaskBoard groups={view.groups} onOpenTask={openTask} />
          ) : (
            <TaskList items={view.items} onOpenTask={openTask} />
          )}
        </>
      )}

      <TaskDetailDrawer
        open={selectedTaskId !== null}
        taskId={selectedTaskId}
        context={context}
        onClose={closeTask}
      />
    </div>
  )
}

function ViewSwitcher({ value, onChange }: { value: ViewMode; onChange: (value: ViewMode) => void }) {
  return (
    <div className="inline-flex items-center rounded-[10px] border border-white/[0.08] bg-surface-1 p-1" aria-label="任务视图">
      {([
        { value: 'board', label: '看板', icon: Columns3 },
        { value: 'list', label: '列表', icon: List },
      ] as const).map((item) => {
        const Icon = item.icon
        const active = item.value === value
        return (
          <button
            key={item.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(item.value)}
            className={cn(
              'flex min-h-10 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-[transform,background-color,color] duration-150 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50',
              active ? 'bg-surface-3 text-white' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200',
            )}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

function TaskMetrics({
  total,
  filtered,
  active,
  blocked,
  filtersActive,
}: {
  total: number
  filtered: number
  active: number
  blocked: number
  filtersActive: boolean
}) {
  const metrics = [
    { label: '当前可见', value: total, detail: '服务端权限过滤后' },
    { label: '当前结果', value: filtered, detail: filtersActive ? '符合当前筛选' : '未应用筛选' },
    { label: '执行进行中', value: active, detail: '按执行状态统计' },
    { label: '协作阻塞', value: blocked, detail: '按协作阶段统计' },
  ]
  return (
    <section aria-label="任务概览" className="card-base grid grid-cols-2 overflow-hidden lg:grid-cols-4">
      {metrics.map((metric, index) => (
        <div
          key={metric.label}
          className={cn(
            'px-4 py-4 md:px-5',
            index % 2 === 1 ? 'border-l border-white/[0.06]' : '',
            index >= 2 ? 'border-t border-white/[0.06] lg:border-t-0' : '',
            index === 2 ? 'lg:border-l' : '',
          )}
        >
          <div className="text-2xl font-semibold tabular-nums text-white">{metric.value}</div>
          <div className="mt-1 text-xs font-medium text-slate-300">{metric.label}</div>
          <div className="mt-0.5 text-[11px] text-slate-600">{metric.detail}</div>
        </div>
      ))}
    </section>
  )
}

function TaskFilters({
  query,
  filters,
  resultCount,
  filtersActive,
  onQueryChange,
  onStageChange,
  onStatusChange,
  onClear,
}: {
  query: string
  filters: TaskCenterFilters
  resultCount: number
  filtersActive: boolean
  onQueryChange: (value: string) => void
  onStageChange: (value: TaskStageKey | 'all') => void
  onStatusChange: (value: TaskStatusKey | 'all') => void
  onClear: () => void
}) {
  return (
    <section aria-label="筛选可见任务" className="flex flex-col gap-3 border-y border-white/[0.06] py-4 lg:flex-row lg:items-end">
      <label className="min-w-0 flex-1 text-xs font-medium text-slate-400">
        搜索任务
        <span className="relative mt-1.5 block">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="标题、负责人、完成条件或步骤"
            className="h-10 w-full rounded-[10px] border border-white/[0.08] bg-surface-1 pl-9 pr-3 text-sm text-slate-100 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
          />
        </span>
      </label>
      <label className="text-xs font-medium text-slate-400 lg:w-44">
        执行状态
        <select
          value={filters.executionStatus}
          onChange={(event) => onStatusChange(event.target.value as TaskStatusKey | 'all')}
          className="mt-1.5 h-10 w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 text-sm text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
        >
          <option value="all">全部执行状态</option>
          {TASK_STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <label className="text-xs font-medium text-slate-400 lg:w-40">
        协作阶段
        <select
          value={filters.collaborationStage}
          onChange={(event) => onStageChange(event.target.value as TaskStageKey | 'all')}
          className="mt-1.5 h-10 w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 text-sm text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
        >
          <option value="all">全部协作阶段</option>
          {TASK_STAGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <div className="flex min-h-10 items-center justify-between gap-3 lg:justify-end">
        <span className="text-xs tabular-nums text-slate-500" aria-live="polite">{resultCount} 项结果</span>
        {filtersActive ? (
          <Button size="sm" variant="ghost" icon={<RotateCcw className="h-4 w-4" />} onClick={onClear}>
            清除筛选
          </Button>
        ) : null}
      </div>
    </section>
  )
}

function TaskBoard({ groups, onOpenTask }: { groups: ReturnType<typeof buildTaskCenterViewModel>['groups']; onOpenTask: (taskId: string) => void }) {
  return (
    <section aria-label="任务看板" className="-mx-4 overflow-x-auto px-4 pb-3 md:-mx-8 md:px-8">
      <div className="flex min-w-max items-start gap-4">
        {groups.map((group) => (
          <section key={group.stage.value} aria-labelledby={`task-stage-${group.stage.value}`} className="w-[min(82vw,292px)] shrink-0 rounded-[12px] bg-surface-1/70 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.035)] md:w-[220px] xl:w-[178px]">
            <header className="mb-3 flex items-center justify-between gap-3 px-1">
              <div className="flex items-center gap-2">
                <span className={cn('h-2 w-2 rounded-full', stageDot(group.stage.tone))} aria-hidden="true" />
                <h2 id={`task-stage-${group.stage.value}`} className="text-sm font-semibold text-slate-200">{group.stage.label}</h2>
              </div>
              <span className="rounded-pill bg-white/[0.05] px-2 py-0.5 text-[11px] tabular-nums text-slate-500">{group.items.length}</span>
            </header>
            <div className="space-y-2.5">
              {group.items.map((item) => <TaskBoardCard key={item.id} item={item} onOpen={() => onOpenTask(item.id)} />)}
              {group.items.length === 0 ? (
                <div className="flex min-h-24 items-center justify-center rounded-[10px] border border-dashed border-white/[0.07] px-4 text-center text-xs text-slate-600">当前阶段无任务</div>
              ) : null}
            </div>
          </section>
        ))}
      </div>
    </section>
  )
}

function TaskBoardCard({ item, onOpen }: { item: TaskCenterItem; onOpen: () => void }) {
  return (
    <article
      data-task-id={item.id}
      className="w-full rounded-[10px] bg-surface-2 p-4 text-left shadow-[0_1px_0_rgba(255,255,255,0.05),0_8px_18px_-14px_rgba(0,0,0,0.9)]"
    >
      <div className="flex items-start justify-between gap-3">
        <Badge tone={item.executionStatus.tone} dot>{item.executionStatus.label}</Badge>
        {item.activeLock ? <LockKeyhole className="h-4 w-4 shrink-0 text-remind" aria-label="任务已加执行锁" /> : null}
      </div>
      <div className="mt-2 flex items-start gap-2">
        <h3 className="min-w-0 flex-1 pt-1 text-[14px] font-semibold leading-6 text-slate-100">{item.title}</h3>
        <button
          type="button"
          onClick={onOpen}
          aria-label={`查看任务：${item.title}`}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-slate-500 transition-[transform,background-color,color] duration-150 hover:bg-white/[0.06] hover:text-slate-200 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
        >
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <dl className="mt-3 space-y-2 text-xs">
        <div className="flex items-start justify-between gap-3">
          <dt className="shrink-0 text-slate-600">协作负责人</dt>
          <dd className="text-right text-slate-300">{item.owner ?? '未指定'}</dd>
        </div>
        <div>
          <dt className="text-slate-600">完成条件</dt>
          <dd className="mt-1 leading-5 text-slate-400">{item.doneWhen ?? '服务端暂未设置'}</dd>
        </div>
      </dl>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-white/[0.05] pt-3 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1.5"><MessageSquareText className="h-3.5 w-3.5" aria-hidden="true" />{item.postCount} 条可见动态</span>
        <span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />{formatDate(item.lastActivityAt)}</span>
      </div>
    </article>
  )
}

function TaskList({ items, onOpenTask }: { items: TaskCenterItem[]; onOpenTask: (taskId: string) => void }) {
  return (
    <section aria-label="任务列表">
      <div className="space-y-3 md:hidden">
        {items.map((item) => <TaskListMobileCard key={item.id} item={item} onOpen={() => onOpenTask(item.id)} />)}
      </div>
      <div className="card-base hidden overflow-x-auto md:block">
        <table className="w-full min-w-[860px] border-collapse text-left text-sm">
          <thead className="bg-surface-2/80 text-xs font-medium text-slate-500">
            <tr>
              <th scope="col" className="px-5 py-3">任务</th>
              <th scope="col" className="px-4 py-3">执行状态</th>
              <th scope="col" className="px-4 py-3">协作阶段</th>
              <th scope="col" className="px-4 py-3">协作负责人</th>
              <th scope="col" className="px-4 py-3">最近活动</th>
              <th scope="col" className="px-4 py-3 text-right">可见动态</th>
              <th scope="col" className="w-14 px-4 py-3"><span className="sr-only">详情</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.06]">
            {items.map((item) => (
              <tr key={item.id} data-task-id={item.id} className="bg-surface-1 transition-colors hover:bg-surface-2/80">
                <td className="max-w-sm px-5 py-4 align-top">
                  <button type="button" className="min-h-10 text-left font-medium leading-5 text-slate-100 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50" onClick={() => onOpenTask(item.id)}>
                    {item.title}
                  </button>
                  {item.doneWhen ? <p className="mt-1 text-xs leading-5 text-slate-500">完成条件：{item.doneWhen}</p> : null}
                </td>
                <td className="px-4 py-4 align-top"><Badge tone={item.executionStatus.tone} dot>{item.executionStatus.label}</Badge></td>
                <td className="px-4 py-4 align-top"><Badge tone={item.collaborationStage.tone}>{item.collaborationStage.label}</Badge></td>
                <td className="px-4 py-4 align-top text-slate-300">{item.owner ?? '未指定'}</td>
                <td className="whitespace-nowrap px-4 py-4 align-top text-xs tabular-nums text-slate-500">{formatDate(item.lastActivityAt)}</td>
                <td className="px-4 py-4 text-right align-top tabular-nums text-slate-400">{item.postCount}</td>
                <td className="px-4 py-4 align-top">
                  <button type="button" aria-label={`查看任务：${item.title}`} onClick={() => onOpenTask(item.id)} className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 transition-[transform,background-color,color] duration-150 hover:bg-white/[0.06] hover:text-slate-200 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">
                    <ChevronRight className="h-4 w-4" aria-hidden="true" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function TaskListMobileCard({ item, onOpen }: { item: TaskCenterItem; onOpen: () => void }) {
  return (
    <article data-task-id={item.id} className="card-base w-full p-4 text-left">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-sm font-semibold leading-6 text-slate-100">{item.title}</h2>
        <button type="button" onClick={onOpen} aria-label={`查看任务：${item.title}`} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-slate-500 transition-[transform,background-color,color] duration-150 hover:bg-white/[0.06] hover:text-slate-200 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Badge tone={item.executionStatus.tone} dot>{item.executionStatus.label}</Badge>
        <Badge tone={item.collaborationStage.tone}>{item.collaborationStage.label}</Badge>
        {item.activeLock ? <Badge tone="remind" icon={<LockKeyhole className="h-3 w-3" />}>执行锁</Badge> : null}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>{item.owner ?? '未指定负责人'}</span>
        <span className="tabular-nums">{formatDate(item.lastActivityAt)}</span>
      </div>
    </article>
  )
}

function TaskCenterLoading() {
  return (
    <section aria-live="polite" aria-busy="true" className="space-y-4">
      <div className="card-base h-24 animate-pulse bg-surface-1" />
      <div className="grid gap-4 md:grid-cols-3">
        {[0, 1, 2].map((item) => <div key={item} className="h-56 animate-pulse rounded-[12px] bg-surface-1" />)}
      </div>
      <span className="sr-only">正在读取可见任务</span>
    </section>
  )
}

function TaskCenterEmpty({ filtered, onClear }: { filtered: boolean; onClear: () => void }) {
  return (
    <section className="flex min-h-64 flex-col items-center justify-center rounded-[12px] border border-dashed border-white/[0.08] px-6 py-12 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-[10px] bg-white/[0.04] text-slate-500">
        <ListChecks className="h-5 w-5" aria-hidden="true" />
      </span>
      <h2 className="mt-4 text-base font-semibold text-slate-200">{filtered ? '没有符合筛选的任务' : '当前没有可见任务'}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">
        {filtered
          ? '调整标题、执行状态或协作阶段后再试。'
          : '只有现有 Agent 或协作流程产生，并且当前账号有权查看的任务才会出现在这里。'}
      </p>
      {filtered ? <Button className="mt-5" size="sm" variant="secondary" onClick={onClear}>清除筛选</Button> : null}
    </section>
  )
}

function stageDot(tone: string): string {
  const tones: Record<string, string> = {
    mint: 'bg-mint-300',
    knowledge: 'bg-knowledge',
    collab: 'bg-collab',
    remind: 'bg-remind',
    rose: 'bg-rose',
    neutral: 'bg-slate-500',
  }
  return tones[tone] ?? tones.neutral
}
