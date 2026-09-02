import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ChevronRight,
  Clock3,
  Columns3,
  List,
  ListChecks,
  LockKeyhole,
  MessageSquareText,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
} from 'lucide-react'

import { TaskDetailDrawer } from '../components/tasks/TaskDetailDrawer'
import { TaskFormDialog, type TaskFormValues } from '../components/tasks/TaskFormDialog'
import { ApiError } from '../api/client'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { PageHeader } from '../components/ui/PageHeader'
import { useAuth } from '../features/auth/AuthProvider'
import { collaborationErrorMessage, useTaskCards } from '../features/collaboration/queries'
import { taskManagementApi } from '../features/tasks/api'
import { TASK_PRIORITY_LABELS, taskDeliveryStageLabel } from '../features/tasks/managementPresentation'
import {
  taskManagementErrorMessage,
  useManagedTaskDetail,
  useManagedTasks,
  useTaskManagementMutations,
} from '../features/tasks/queries'
import type { ManagedTask, TaskManagementAction, TaskTransitionPayload } from '../features/tasks/types'
import { workspaceApi } from '../features/workspace/api'
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

function commandId(operation: string): string {
  return `task-${operation}-${crypto.randomUUID()}`
}

export function Tasks() {
  const { user, bootstrap } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [taskFormOpen, setTaskFormOpen] = useState(false)
  const [editingTask, setEditingTask] = useState<ManagedTask | null>(null)
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [mutationNotice, setMutationNotice] = useState<string | null>(null)
  const [runStarting, setRunStarting] = useState(false)
  const [formDetailReadyTaskId, setFormDetailReadyTaskId] = useState<string | null>(null)
  const saveCommandId = useRef<string | null>(null)
  const actionCommand = useRef<{ action: TaskManagementAction; id: string } | null>(null)
  const reviewCommand = useRef<{ key: string; id: string } | null>(null)
  const captureCommands = useRef<Record<string, string>>({})
  const context = {
    userId: user?.id ?? '',
    workspaceId: user?.workspace_id ?? '',
    projectId: user?.default_project_id ?? '',
  }
  const cardsQuery = useTaskCards(context)
  const managedQuery = useManagedTasks(context)
  const managedDetailQuery = useManagedTaskDetail(
    context,
    taskFormOpen && editingTask ? editingTask.task.id : null,
  )
  const mutations = useTaskManagementMutations(context)
  const managedByTaskId = useMemo(
    () => new Map((managedQuery.data?.items ?? []).map((item) => [item.task.id, item])),
    [managedQuery.data?.items],
  )
  const writeEnabled = bootstrap?.task_management_mode === 'write'
  const canManageProjectTasks = (bootstrap?.capabilities ?? []).includes('manage_project_tasks')
  const projectMemberIds = new Set(bootstrap?.project.member_ids ?? [])
  const projectUsers = (bootstrap?.users ?? []).filter((candidate) => (
    candidate.workspace_id === user?.workspace_id
    && candidate.status === 'active'
    && (projectMemberIds.size === 0 || projectMemberIds.has(candidate.id as string))
  ))
  const assignableUsers = canManageProjectTasks
    ? projectUsers
    : projectUsers.filter((candidate) => candidate.id === user?.id)
  const assignableAgents = (bootstrap?.agents ?? []).filter((candidate) => (
    candidate.workspace_id === user?.workspace_id
    && candidate.status === 'online'
    && (
      candidate.owner_user_id === user?.id
      || (canManageProjectTasks && candidate.owner_user_id == null && candidate.agent_type !== 'personal')
    )
  ))
  const managementAssigneeByTaskId = useMemo(() => {
    const labels = new Map<string, string>()
    for (const managed of managedQuery.data?.items ?? []) {
      const assigneeId = managed.management.assignee_id
      if (!assigneeId) continue
      const label = managed.management.assignee_kind === 'user'
        ? bootstrap?.users.find((candidate) => candidate.id === assigneeId)?.name
        : bootstrap?.agents.find((candidate) => candidate.id === assigneeId)?.name
      if (label) labels.set(managed.task.id, label)
    }
    return labels
  }, [bootstrap?.agents, bootstrap?.users, managedQuery.data?.items])
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
  const openCreate = () => {
    setEditingTask(null)
    setMutationError(null)
    setMutationNotice(null)
    saveCommandId.current = null
    actionCommand.current = null
    reviewCommand.current = null
    setFormDetailReadyTaskId(null)
    setTaskFormOpen(true)
  }
  const openEdit = (task: ManagedTask) => {
    setEditingTask(task)
    setMutationError(null)
    setMutationNotice(null)
    saveCommandId.current = null
    actionCommand.current = null
    reviewCommand.current = null
    setFormDetailReadyTaskId(null)
    setTaskFormOpen(true)
  }
  const closeForm = () => {
    setTaskFormOpen(false)
    setMutationError(null)
    setMutationNotice(null)
    saveCommandId.current = null
    actionCommand.current = null
    reviewCommand.current = null
    setFormDetailReadyTaskId(null)
  }

  useEffect(() => {
    if (!taskFormOpen || !editingTask) return
    const taskId = editingTask.task.id
    let cancelled = false
    setFormDetailReadyTaskId(null)
    void managedDetailQuery.refetch().then((result) => {
      if (
        !cancelled
        && result.error == null
        && result.data?.item.task.id === taskId
      ) {
        setFormDetailReadyTaskId(taskId)
      }
    })
    return () => {
      cancelled = true
    }
  }, [editingTask?.task.id, taskFormOpen])

  useEffect(() => {
    const managedTaskId = searchParams.get('manage')?.trim()
    if (!managedTaskId || taskFormOpen || managedQuery.isLoading) return
    let cancelled = false
    const openRequestedTask = async () => {
      let target = managedByTaskId.get(managedTaskId) ?? null
      if (!target) {
        try {
          target = (await taskManagementApi.get(managedTaskId)).item
        } catch {
          target = null
        }
      }
      if (cancelled) return
      if (target) openEdit(target)
      const next = new URLSearchParams(searchParams)
      next.delete('manage')
      setSearchParams(next, { replace: true })
    }
    void openRequestedTask()
    return () => {
      cancelled = true
    }
  }, [managedByTaskId, managedQuery.isLoading, searchParams, setSearchParams, taskFormOpen])

  const retryFormDetail = async () => {
    if (!editingTask) return
    const taskId = editingTask.task.id
    setFormDetailReadyTaskId(null)
    const result = await managedDetailQuery.refetch()
    if (result.error == null && result.data?.item.task.id === taskId) {
      setFormDetailReadyTaskId(taskId)
    }
  }
  const refreshEditingTaskAfterConflict = async (error: unknown) => {
    if (!(error instanceof ApiError) || error.status !== 409 || !editingTask) return
    const refreshed = await managedQuery.refetch()
    const latest = refreshed.data?.items.find((item) => item.task.id === editingTask.task.id)
    if (latest) {
      setEditingTask(latest)
      return
    }
    try {
      const detail = await taskManagementApi.get(editingTask.task.id)
      setEditingTask(detail.item)
    } catch (refreshError) {
      if (refreshError instanceof ApiError && refreshError.status === 404) closeForm()
    }
  }
  const saveTask = async (values: TaskFormValues) => {
    setMutationError(null)
    setMutationNotice(null)
    const stableCommandId = saveCommandId.current ?? commandId(editingTask ? 'update' : 'create')
    saveCommandId.current = stableCommandId
    try {
      if (editingTask) {
        await mutations.update.mutateAsync({
          taskId: editingTask.task.id,
          payload: {
            command_id: stableCommandId,
            expected_version: editingTask.management.version,
            title: values.title,
            description: values.description,
            task_type: values.taskType,
            priority: values.priority,
            due_at: values.dueAt,
            assignee_kind: values.assigneeKind,
            assignee_id: values.assigneeId,
            tags: values.tags,
          },
        })
      } else {
        await mutations.create.mutateAsync({
          command_id: stableCommandId,
          title: values.title,
          description: values.description,
          task_type: values.taskType,
          priority: values.priority,
          due_at: values.dueAt,
          assignee_kind: values.assigneeKind,
          assignee_id: values.assigneeId,
          tags: values.tags,
        })
      }
      await Promise.all([cardsQuery.refetch(), managedQuery.refetch()])
      closeForm()
    } catch (error) {
      await refreshEditingTaskAfterConflict(error)
      setMutationError(taskManagementErrorMessage(error))
    }
  }
  const applyTaskAction = async (action: TaskManagementAction, reason?: string) => {
    if (!editingTask) return
    setMutationError(null)
    setMutationNotice(null)
    const stableCommand = actionCommand.current?.action === action
      ? actionCommand.current
      : { action, id: commandId(action) }
    actionCommand.current = stableCommand
    try {
      if (action === 'start_agent_run') {
        setRunStarting(true)
        const response = await workspaceApi.startAgentRun({
          threadId: null,
          taskId: editingTask.task.id,
          content: editingTask.management.description || editingTask.task.title,
          clientTurnId: stableCommand.id,
          orchestrationMode: 'single',
          planningMode: 'standard',
        })
        await managedDetailQuery.refetch()
        setMutationNotice(`AgentRun 已启动：${response.item.id}`)
        actionCommand.current = null
        return
      }
      if (action === 'archive') {
        await mutations.archive.mutateAsync({
          taskId: editingTask.task.id,
          payload: {
            command_id: stableCommand.id,
            expected_version: editingTask.management.version,
          },
        })
      } else {
        await mutations.transition.mutateAsync({
          taskId: editingTask.task.id,
          payload: {
            command_id: stableCommand.id,
            expected_version: editingTask.management.version,
            action: action as TaskTransitionPayload['action'],
            reason: reason ?? null,
          },
        })
      }
      await Promise.all([cardsQuery.refetch(), managedQuery.refetch()])
      closeForm()
    } catch (error) {
      await refreshEditingTaskAfterConflict(error)
      setMutationError(taskManagementErrorMessage(error))
    } finally {
      setRunStarting(false)
    }
  }
  const refreshOpenTask = async () => {
    const [detail] = await Promise.all([
      managedDetailQuery.refetch(),
      cardsQuery.refetch(),
      managedQuery.refetch(),
    ])
    if (detail.data) setEditingTask(detail.data.item)
  }
  const submitArtifactReview = async (runId: string, artifactIds: string[]) => {
    const current = managedDetailQuery.data?.item ?? editingTask
    if (!current) return
    setMutationError(null)
    setMutationNotice(null)
    const key = `submit:${current.management.version}:${runId}:${artifactIds.join(',')}`
    const stableCommand = reviewCommand.current?.key === key
      ? reviewCommand.current
      : { key, id: commandId('submit-review') }
    reviewCommand.current = stableCommand
    try {
      const response = await mutations.submitReview.mutateAsync({
        taskId: current.task.id,
        payload: {
          command_id: stableCommand.id,
          expected_task_version: current.management.version,
          run_id: runId,
          artifact_ids: artifactIds,
        },
      })
      await refreshOpenTask()
      setMutationNotice(`第 ${response.item.review.round} 轮审核已提交。`)
      reviewCommand.current = null
    } catch (error) {
      await refreshEditingTaskAfterConflict(error)
      setMutationError(taskManagementErrorMessage(error))
    }
  }
  const decideArtifactReview = async (
    reviewId: string,
    expectedVersion: number,
    decision: 'accepted' | 'changes_requested' | 'rejected',
    decisionNote: string | null,
  ) => {
    setMutationError(null)
    setMutationNotice(null)
    const key = `decide:${reviewId}:${expectedVersion}:${decision}:${decisionNote ?? ''}`
    const stableCommand = reviewCommand.current?.key === key
      ? reviewCommand.current
      : { key, id: commandId('decide-review') }
    reviewCommand.current = stableCommand
    try {
      await mutations.decideReview.mutateAsync({
        reviewId,
        payload: {
          command_id: stableCommand.id,
          expected_version: expectedVersion,
          decision,
          decision_note: decisionNote,
        },
      })
      await refreshOpenTask()
      setMutationNotice(
        decision === 'accepted' ? '交付已接受，任务已完成。'
          : decision === 'changes_requested' ? '已要求修改，任务返回进行中。'
            : '交付已拒绝，任务返回进行中。',
      )
      reviewCommand.current = null
    } catch (error) {
      await refreshEditingTaskAfterConflict(error)
      setMutationError(taskManagementErrorMessage(error))
    }
  }
  const captureReviewMemory = async (
    reviewId: string,
    target: 'personal' | 'team_candidate',
    title: string,
    summary: string,
  ) => {
    setMutationError(null)
    setMutationNotice(null)
    const key = JSON.stringify([reviewId, target, title, summary])
    const captureCommandId = captureCommands.current[key] ?? commandId('capture-memory')
    captureCommands.current[key] = captureCommandId
    try {
      await mutations.captureMemory.mutateAsync({
        reviewId,
        payload: {
          command_id: captureCommandId,
          target,
          title,
          summary,
          memory_type: 'project_experience',
          layer: 'mid_term',
        },
      })
      await refreshOpenTask()
      setMutationNotice(
        target === 'personal'
          ? '已保存为个人记忆。'
          : '已提交团队候选，等待独立 Memory Review。',
      )
      delete captureCommands.current[key]
    } catch (error) {
      setMutationError(taskManagementErrorMessage(error))
    }
  }
  const mutationPending = runStarting
    || mutations.create.isPending
    || mutations.update.isPending
    || mutations.transition.isPending
    || mutations.archive.isPending
    || mutations.submitReview.isPending
    || mutations.decideReview.isPending
    || mutations.captureMemory.isPending
  const currentDetailTask = (
    editingTask
    && managedDetailQuery.data?.item.task.id === editingTask.task.id
    && managedDetailQuery.data.item.management.version >= editingTask.management.version
  )
    ? managedDetailQuery.data.item
    : editingTask
  const formDetailUsable = (
    editingTask !== null
    && formDetailReadyTaskId === editingTask.task.id
    && managedDetailQuery.error == null
    && !managedDetailQuery.isFetching
  )
  const taskForForm = currentDetailTask && editingTask && !formDetailUsable
    ? { ...currentDetailTask, allowed_actions: [] }
    : currentDetailTask

  return (
    <div className="space-y-6" lang="zh-CN">
      <PageHeader
        title="任务中心"
        subtitle={writeEnabled
          ? '管理当前项目任务；Agent 执行与项目交付状态保持独立。'
          : '查看现有 Agent 与协作流程产生、且当前账号可见的任务。任务写入当前未开放。'}
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            {writeEnabled ? <Button icon={<Plus className="h-4 w-4" />} onClick={openCreate}>新建任务</Button> : null}
            <ViewSwitcher value={viewMode} onChange={(mode) => setParameter('view', mode, 'board')} />
          </div>
        )}
      />

      {cardsQuery.error || managedQuery.error ? (
        <section role="alert" className="flex flex-wrap items-center justify-between gap-4 rounded-[12px] border border-rose/25 bg-rose/10 p-4 text-sm text-rose">
          <div>
            <p className="font-medium">任务列表读取失败</p>
            <p className="mt-1 text-xs leading-5 text-rose/80">
              {collaborationErrorMessage(cardsQuery.error ?? managedQuery.error)}
            </p>
          </div>
          <Button
            size="sm"
            variant="subtle"
            icon={<RefreshCw className="h-4 w-4" />}
            loading={cardsQuery.isFetching || managedQuery.isFetching}
            onClick={() => void Promise.all([cardsQuery.refetch(), managedQuery.refetch()])}
          >
            重试
          </Button>
        </section>
      ) : cardsQuery.isLoading || managedQuery.isLoading ? (
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
            <TaskBoard
              groups={view.groups}
              managedByTaskId={managedByTaskId}
              managementAssigneeByTaskId={managementAssigneeByTaskId}
              onOpenTask={openTask}
              onManageTask={openEdit}
            />
          ) : (
            <TaskList
              items={view.items}
              managedByTaskId={managedByTaskId}
              managementAssigneeByTaskId={managementAssigneeByTaskId}
              onOpenTask={openTask}
              onManageTask={openEdit}
            />
          )}
        </>
      )}

      <TaskFormDialog
        open={taskFormOpen}
        task={taskForForm}
        users={assignableUsers}
        agents={assignableAgents}
        submitting={
          mutationPending
          || (editingTask !== null && !formDetailUsable)
          || managedDetailQuery.isFetching
        }
        runtimeReady={bootstrap?.agent_runtime_ready === true && !managedDetailQuery.isLoading && !managedDetailQuery.error}
        runs={managedDetailQuery.data?.runs ?? []}
        artifacts={managedDetailQuery.data?.artifacts ?? []}
        reviews={managedDetailQuery.data?.reviews ?? []}
        memoryLinks={managedDetailQuery.data?.memory_links ?? []}
        historyTruncated={
          managedDetailQuery.data?.runs_truncated === true
          || managedDetailQuery.data?.artifacts_truncated === true
        }
        reviewsTruncated={managedDetailQuery.data?.reviews_truncated === true}
        detailError={
          editingTask && !formDetailUsable && managedDetailQuery.error
            ? taskManagementErrorMessage(managedDetailQuery.error)
            : null
        }
        detailRetrying={managedDetailQuery.isFetching}
        error={mutationError}
        notice={mutationNotice}
        onClose={closeForm}
        onRetryDetail={() => void retryFormDetail()}
        onSubmit={(values) => void saveTask(values)}
        onAction={(action, reason) => void applyTaskAction(action, reason)}
        onSubmitReview={(runId, artifactIds) => void submitArtifactReview(runId, artifactIds)}
        onDecideReview={(reviewId, version, decision, note) => (
          void decideArtifactReview(reviewId, version, decision, note)
        )}
        onCaptureMemory={(reviewId, target, title, summary) => (
          void captureReviewMemory(reviewId, target, title, summary)
        )}
      />

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

function TaskBoard({
  groups,
  managedByTaskId,
  managementAssigneeByTaskId,
  onOpenTask,
  onManageTask,
}: {
  groups: ReturnType<typeof buildTaskCenterViewModel>['groups']
  managedByTaskId: Map<string, ManagedTask>
  managementAssigneeByTaskId: Map<string, string>
  onOpenTask: (taskId: string) => void
  onManageTask: (task: ManagedTask) => void
}) {
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
              {group.items.map((item) => (
                <TaskBoardCard
                  key={item.id}
                  item={item}
                  managedTask={managedByTaskId.get(item.id) ?? null}
                  managementAssignee={managementAssigneeByTaskId.get(item.id) ?? null}
                  onOpen={() => onOpenTask(item.id)}
                  onManage={onManageTask}
                />
              ))}
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

function TaskBoardCard({
  item,
  managedTask,
  managementAssignee,
  onOpen,
  onManage,
}: {
  item: TaskCenterItem
  managedTask: ManagedTask | null
  managementAssignee: string | null
  onOpen: () => void
  onManage: (task: ManagedTask) => void
}) {
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
      {managedTask ? (
        <div className="mt-3 flex items-center justify-between gap-2 border-t border-white/[0.05] pt-3">
          <div className="flex flex-col items-start gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="neutral">{taskDeliveryStageLabel(managedTask.management.delivery_stage)}</Badge>
              {managedTask.management.priority ? (
                <Badge tone={managedTask.management.priority === 'p0' ? 'rose' : 'remind'}>
                  {TASK_PRIORITY_LABELS[managedTask.management.priority]}
                </Badge>
              ) : null}
            </div>
            {managementAssignee ? <span className="text-[11px] text-slate-500">交付负责人：{managementAssignee}</span> : null}
          </div>
          {managedTask.allowed_actions.length > 0 ? (
            <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => onManage(managedTask)}>
              管理
            </Button>
          ) : null}
        </div>
      ) : null}
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-white/[0.05] pt-3 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1.5"><MessageSquareText className="h-3.5 w-3.5" aria-hidden="true" />{item.postCount} 条可见动态</span>
        <span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />{formatDate(item.lastActivityAt)}</span>
      </div>
    </article>
  )
}

function TaskList({
  items,
  managedByTaskId,
  managementAssigneeByTaskId,
  onOpenTask,
  onManageTask,
}: {
  items: TaskCenterItem[]
  managedByTaskId: Map<string, ManagedTask>
  managementAssigneeByTaskId: Map<string, string>
  onOpenTask: (taskId: string) => void
  onManageTask: (task: ManagedTask) => void
}) {
  return (
    <section aria-label="任务列表">
      <div className="space-y-3 md:hidden">
        {items.map((item) => (
          <TaskListMobileCard
            key={item.id}
            item={item}
            managedTask={managedByTaskId.get(item.id) ?? null}
            managementAssignee={managementAssigneeByTaskId.get(item.id) ?? null}
            onOpen={() => onOpenTask(item.id)}
            onManage={onManageTask}
          />
        ))}
      </div>
      <div className="card-base hidden overflow-x-auto md:block">
        <table className="w-full min-w-[860px] border-collapse text-left text-sm">
          <thead className="bg-surface-2/80 text-xs font-medium text-slate-500">
            <tr>
              <th scope="col" className="px-5 py-3">任务</th>
              <th scope="col" className="px-4 py-3">执行状态</th>
              <th scope="col" className="px-4 py-3">协作阶段</th>
              <th scope="col" className="px-4 py-3">协作负责人</th>
              <th scope="col" className="px-4 py-3">交付负责人</th>
              <th scope="col" className="px-4 py-3">最近活动</th>
              <th scope="col" className="px-4 py-3">交付阶段</th>
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
                <td className="px-4 py-4 align-top text-slate-300">{managementAssigneeByTaskId.get(item.id) ?? '未指定'}</td>
                <td className="whitespace-nowrap px-4 py-4 align-top text-xs tabular-nums text-slate-500">{formatDate(item.lastActivityAt)}</td>
                <td className="px-4 py-4 align-top">
                  {managedByTaskId.get(item.id) ? (
                    <Badge tone="neutral">
                      {taskDeliveryStageLabel((managedByTaskId.get(item.id) as ManagedTask).management.delivery_stage)}
                    </Badge>
                  ) : '—'}
                </td>
                <td className="px-4 py-4 text-right align-top tabular-nums text-slate-400">{item.postCount}</td>
                <td className="px-4 py-4 align-top">
                  <div className="flex items-center justify-end gap-1">
                    {managedByTaskId.get(item.id)?.allowed_actions.length ? (
                      <button type="button" aria-label={`管理任务：${item.title}`} onClick={() => onManageTask(managedByTaskId.get(item.id) as ManagedTask)} className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 transition-[transform,background-color,color] duration-150 hover:bg-white/[0.06] hover:text-slate-200 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">
                        <Pencil className="h-4 w-4" aria-hidden="true" />
                      </button>
                    ) : null}
                    <button type="button" aria-label={`查看任务：${item.title}`} onClick={() => onOpenTask(item.id)} className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 transition-[transform,background-color,color] duration-150 hover:bg-white/[0.06] hover:text-slate-200 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">
                      <ChevronRight className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function TaskListMobileCard({
  item,
  managedTask,
  managementAssignee,
  onOpen,
  onManage,
}: {
  item: TaskCenterItem
  managedTask: ManagedTask | null
  managementAssignee: string | null
  onOpen: () => void
  onManage: (task: ManagedTask) => void
}) {
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
      {managedTask ? (
        <div className="mt-3 flex items-center justify-between gap-2 border-t border-white/[0.05] pt-3">
          <div className="flex flex-col items-start gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="neutral">{taskDeliveryStageLabel(managedTask.management.delivery_stage)}</Badge>
              {managedTask.management.priority ? (
                <Badge tone={managedTask.management.priority === 'p0' ? 'rose' : 'remind'}>
                  {TASK_PRIORITY_LABELS[managedTask.management.priority]}
                </Badge>
              ) : null}
            </div>
            {managementAssignee ? <span className="text-[11px] text-slate-500">交付负责人：{managementAssignee}</span> : null}
          </div>
          {managedTask.allowed_actions.length > 0 ? (
            <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => onManage(managedTask)}>
              管理
            </Button>
          ) : null}
        </div>
      ) : null}
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
          : '当前项目还没有可见任务。任务可以由用户创建，也可以由 Agent 或协作流程产生。'}
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
