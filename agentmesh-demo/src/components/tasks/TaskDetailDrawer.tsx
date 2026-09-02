import {
  AlertTriangle,
  CalendarClock,
  ListChecks,
  ListTodo,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  UserRound,
} from 'lucide-react'

import { ApiError } from '../../api/client'
import type { TaskDetail } from '../../features/collaboration/api'
import type { CollaborationContext } from '../../features/collaboration/queries'
import {
  collaborationErrorMessage,
  useTaskDetail,
} from '../../features/collaboration/queries'
import type { TaskArtifactSummary, TaskReviewView, TaskRunSummary } from '../../features/tasks/types'
import { useManagedTaskDetail } from '../../features/tasks/queries'
import { buildTaskDetailViewModel } from '../../features/tasks/presenter'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Drawer } from '../ui/Drawer'
import { SourceList } from '../ui/SourceList'

export interface TaskDetailDrawerProps {
  open: boolean
  taskId: string | null
  context: CollaborationContext
  onClose: () => void
}

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function TaskDetailDrawer({
  open,
  taskId,
  context,
  onClose,
}: TaskDetailDrawerProps) {
  const detail = useTaskDetail(context, open ? taskId : null)
  const managed = useManagedTaskDetail(context, open ? taskId : null)
  const accessError = isTaskAccessError(detail.error)
  const title = accessError ? '任务详情' : detail.data?.task_card.task.title?.trim() || '任务详情'

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={680}
      icon={<ListTodo className="h-5 w-5" aria-hidden="true" />}
      title={title}
      subtitle="只读视图，仅展示当前账号可见的任务事实"
    >
      {!taskId ? <MissingTaskState /> : null}
      {taskId && detail.isLoading ? <LoadingState /> : null}
      {taskId && detail.error && (!detail.data || accessError) ? (
        <ErrorState
          error={detail.error}
          retrying={detail.isFetching}
          onRetry={() => void detail.refetch()}
        />
      ) : null}
      {taskId && detail.data && !accessError ? (
        <>
          {detail.error ? (
            <RefreshNotice
              error={detail.error}
              retrying={detail.isFetching}
              onRetry={() => void detail.refetch()}
            />
          ) : null}
          <TaskDetailContent
            detail={detail.data}
            runs={managed.data?.runs ?? []}
            artifacts={managed.data?.artifacts ?? []}
            reviews={managed.data?.reviews ?? []}
            executionTruncated={
              managed.data?.runs_truncated === true
              || managed.data?.artifacts_truncated === true
            }
            reviewTruncated={managed.data?.reviews_truncated === true}
            executionLoading={managed.isLoading}
            executionError={managed.error}
            executionRetrying={managed.isFetching}
            onRetryExecution={() => void managed.refetch()}
          />
        </>
      ) : null}
    </Drawer>
  )
}

function TaskDetailContent({
  detail,
  runs,
  artifacts,
  reviews,
  executionTruncated,
  reviewTruncated,
  executionLoading,
  executionError,
  executionRetrying,
  onRetryExecution,
}: {
  detail: TaskDetail
  runs: TaskRunSummary[]
  artifacts: TaskArtifactSummary[]
  reviews: TaskReviewView[]
  executionTruncated: boolean
  reviewTruncated: boolean
  executionLoading: boolean
  executionError: unknown
  executionRetrying: boolean
  onRetryExecution: () => void
}) {
  const view = buildTaskDetailViewModel(detail)
  const { task, timeline } = view

  return (
    <div className="space-y-6">
      <section aria-labelledby="task-status-heading" className="rounded-[12px] bg-surface-1 p-4 ring-1 ring-inset ring-white/[0.06]">
        <h3 id="task-status-heading" className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          当前状态
        </h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className="min-w-0 rounded-[10px] bg-white/[0.025] px-3.5 py-3">
            <p className="text-xs text-slate-500">执行状态</p>
            <div className="mt-2">
              <Badge tone={task.executionStatus.tone} dot>
                {facetLabel(task.executionStatus)}
              </Badge>
            </div>
          </div>
          <div className="min-w-0 rounded-[10px] bg-white/[0.025] px-3.5 py-3">
            <p className="text-xs text-slate-500">协作阶段</p>
            <div className="mt-2">
              <Badge tone={task.collaborationStage.tone} dot>
                {facetLabel(task.collaborationStage)}
              </Badge>
            </div>
          </div>
        </div>
      </section>

      <section aria-labelledby="task-responsibility-heading" className="border-t border-white/[0.06] pt-5">
        <h3 id="task-responsibility-heading" className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <UserRound className="h-4 w-4 text-slate-500" aria-hidden="true" />
          责任与完成条件
        </h3>
        <dl className="mt-4 grid gap-4 sm:grid-cols-2">
          <MetaItem label="协作负责人" value={task.owner ?? '尚未分配'} />
          <MetaItem label="完成条件" value={task.doneWhen ?? '服务端暂未设置'} />
        </dl>

        {task.activeLock ? (
          <div className="mt-4 rounded-[10px] bg-remind/[0.06] px-3.5 py-3 ring-1 ring-inset ring-remind/15">
            <div className="flex items-start gap-2.5">
              <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-remind" aria-hidden="true" />
              <div className="min-w-0">
                <p className="text-xs font-semibold text-remind">执行锁生效中</p>
                <p className="mt-1 break-words text-sm text-slate-200">{task.activeLock.owner_label}</p>
                <p className="mt-1 text-xs tabular-nums text-slate-500">
                  获取时间：{formatTime(task.activeLock.acquired_at ?? null)}
                </p>
              </div>
            </div>
          </div>
        ) : (
          <p className="mt-4 flex items-center gap-2 text-xs text-slate-500">
            <LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />
            当前没有生效中的执行锁
          </p>
        )}
      </section>

      <section aria-labelledby="task-steps-heading" className="border-t border-white/[0.06] pt-5">
        <h3 id="task-steps-heading" className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <ListChecks className="h-4 w-4 text-slate-500" aria-hidden="true" />
          任务步骤
        </h3>
        {task.steps.length > 0 ? (
          <ol className="mt-4 space-y-2.5">
            {task.steps.map((step, index) => (
              <li key={`${index}-${step}`} className="flex min-w-0 items-start gap-3 text-sm leading-6 text-slate-300">
                <span className="mt-0.5 flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-white/[0.06] px-1 text-[10px] tabular-nums text-slate-400">
                  {index + 1}
                </span>
                <span className="min-w-0 break-words">{step}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-3 text-sm text-slate-500">该任务未提供执行步骤。</p>
        )}
      </section>

      <section aria-labelledby="task-record-heading" className="border-t border-white/[0.06] pt-5">
        <h3 id="task-record-heading" className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <CalendarClock className="h-4 w-4 text-slate-500" aria-hidden="true" />
          任务记录
        </h3>
        <dl className="mt-4 grid gap-x-5 gap-y-4 sm:grid-cols-3">
          <MetaItem label="创建时间" value={formatTime(task.createdAt)} tabular />
          <MetaItem label="更新时间" value={formatTime(task.updatedAt)} tabular />
          <MetaItem label="可见动态" value={`${task.postCount} 条`} tabular />
        </dl>
      </section>

      <TaskExecutionHistory
        runs={runs}
        artifacts={artifacts}
        truncated={executionTruncated}
        loading={executionLoading}
        error={executionError}
        retrying={executionRetrying}
        onRetry={onRetryExecution}
      />

      <TaskReviewHistory reviews={reviews} truncated={reviewTruncated} />

      <section aria-labelledby="task-timeline-heading" className="border-t border-white/[0.06] pt-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 id="task-timeline-heading" className="text-sm font-semibold text-slate-200">黑板时间线</h3>
          <span className="text-xs tabular-nums text-slate-500">{timeline.length} 条可见</span>
        </div>
        <p className="mt-1.5 text-xs leading-5 text-slate-500">
          以下动态已由服务端按当前账号权限过滤。
        </p>

        {timeline.length > 0 ? (
          <ol className="relative mt-5 space-y-5" aria-label="任务黑板动态">
            {timeline.map((item, index) => (
              <li key={item.id} className="relative flex min-w-0 gap-3.5">
                {index < timeline.length - 1 ? (
                  <span className="absolute left-[15px] top-9 h-[calc(100%+4px)] w-px bg-white/[0.07]" aria-hidden="true" />
                ) : null}
                <span className="relative z-10 mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-3 text-[11px] font-semibold text-slate-300 ring-1 ring-inset ring-white/[0.08]">
                  {actorMark(item.actor)}
                </span>
                <article className="min-w-0 flex-1 pb-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="break-words text-xs font-medium text-slate-300">{item.actor}</span>
                    <Badge tone={item.postType.tone}>{facetLabel(item.postType)}</Badge>
                    <Badge tone={item.collaborationStage.tone}>{facetLabel(item.collaborationStage)}</Badge>
                  </div>
                  <h4 className="mt-2 break-words text-[13.5px] font-semibold leading-5 text-slate-100">
                    {item.title}
                  </h4>
                  {item.content ? (
                    <p className="mt-1 whitespace-pre-wrap break-words text-[13px] leading-6 text-slate-400">
                      {item.content}
                    </p>
                  ) : (
                    <p className="mt-1 text-xs text-slate-600">该动态没有正文。</p>
                  )}
                  <p className="mt-2 text-[11px] tabular-nums text-slate-600">
                    <time dateTime={item.createdAt ?? undefined}>{formatTime(item.createdAt)}</time>
                  </p>
                  <SourceList sources={item.sources} />
                </article>
              </li>
            ))}
          </ol>
        ) : (
          <div className="mt-4 rounded-[10px] bg-surface-1 px-4 py-5 text-sm leading-6 text-slate-500 ring-1 ring-inset ring-white/[0.05]">
            当前账号没有可见的黑板动态。
          </div>
        )}
      </section>
    </div>
  )
}

function TaskExecutionHistory({
  runs,
  artifacts,
  truncated,
  loading,
  error,
  retrying,
  onRetry,
}: {
  runs: TaskRunSummary[]
  artifacts: TaskArtifactSummary[]
  truncated: boolean
  loading: boolean
  error: unknown
  retrying: boolean
  onRetry: () => void
}) {
  if (loading && runs.length === 0 && artifacts.length === 0) {
    return (
      <section aria-label="Agent 执行与产物" className="border-t border-white/[0.06] pt-5 text-sm text-slate-500">
        正在读取执行记录…
      </section>
    )
  }
  if (error && runs.length === 0 && artifacts.length === 0) {
    return (
      <section role="alert" className="border-t border-white/[0.06] pt-5">
        <p className="text-sm font-medium text-rose">执行记录加载失败</p>
        <p className="mt-1 text-xs text-slate-500">{collaborationErrorMessage(error)}</p>
        <Button className="mt-3" size="sm" variant="subtle" loading={retrying} onClick={onRetry}>重试执行记录</Button>
      </section>
    )
  }
  if (runs.length === 0 && artifacts.length === 0) return null
  return (
    <section aria-labelledby="task-runs-heading" className="border-t border-white/[0.06] pt-5">
      <div className="flex items-baseline justify-between gap-2">
        <h3 id="task-runs-heading" className="text-sm font-semibold text-slate-200">Agent 执行与产物</h3>
        <span className="text-xs tabular-nums text-slate-500">{runs.length} 次执行</span>
      </div>
      <div className="mt-4 space-y-2">
        {error ? (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-2 text-xs text-remind">
            <span>执行记录刷新失败，以下为最近一次成功结果。</span>
            <Button size="sm" variant="ghost" loading={retrying} onClick={onRetry}>重试</Button>
          </div>
        ) : null}
        {truncated ? <p className="text-xs text-remind">仅显示最近的执行和已封存产物。</p> : null}
        {runs.map((run) => (
          <div key={run.id} className="rounded-[10px] bg-surface-1 px-3.5 py-3 ring-1 ring-inset ring-white/[0.05]">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="font-medium text-slate-200">{run.status}</span>
              <span className="text-slate-500">{run.artifact_count} 个已封存产物</span>
            </div>
            {run.navigation_href ? <a className="mt-2 inline-block text-xs text-mint-300 hover:underline" href={run.navigation_href}>打开本人的 Run</a> : null}
          </div>
        ))}
        {artifacts.map((artifact) => (
          <div key={artifact.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[10px] border border-white/[0.06] px-3.5 py-3 text-xs text-slate-500">
            <span>{artifact.artifact_type} · {artifact.verification_state}</span>
            {artifact.download_href ? <a className="text-mint-300 hover:underline" href={artifact.download_href}>打开产物</a> : null}
          </div>
        ))}
      </div>
    </section>
  )
}

function TaskReviewHistory({ reviews, truncated }: { reviews: TaskReviewView[]; truncated: boolean }) {
  if (reviews.length === 0) return null
  return (
    <section aria-labelledby="task-reviews-heading" className="border-t border-white/[0.06] pt-5">
      <div className="flex items-baseline justify-between gap-2">
        <h3 id="task-reviews-heading" className="text-sm font-semibold text-slate-200">交付审核</h3>
        <span className="text-xs tabular-nums text-slate-500">{reviews.length} 轮</span>
      </div>
      {truncated ? <p className="mt-2 text-xs text-remind">仅显示最近的审核记录。</p> : null}
      <ol className="mt-4 space-y-2.5">
        {reviews.map(({ review }) => (
          <li key={review.id} className="rounded-[10px] bg-surface-1 px-3.5 py-3 ring-1 ring-inset ring-white/[0.05]">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="font-medium text-slate-200">第 {review.round} 轮 · {reviewStatusLabel(review.status)}</span>
              <span className="text-slate-500">{review.artifact_ids.length} 个冻结产物</span>
            </div>
            <p className="mt-2 break-all text-[11px] text-slate-500">Run {review.run_id}</p>
            <p className="mt-1 text-[11px] text-slate-500">审核人：{review.reviewer_id}</p>
            {review.decision_note ? (
              <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-5 text-slate-300">{review.decision_note}</p>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  )
}

function reviewStatusLabel(status: TaskReviewView['review']['status']): string {
  return {
    pending: '待审核',
    accepted: '已接受',
    changes_requested: '要求修改',
    rejected: '已拒绝',
  }[status]
}

function MetaItem({ label, value, tabular = false }: { label: string; value: string; tabular?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className={`mt-1.5 break-words text-sm leading-6 text-slate-200${tabular ? ' tabular-nums' : ''}`}>
        {value}
      </dd>
    </div>
  )
}

function LoadingState() {
  return (
    <div role="status" aria-live="polite" className="flex min-h-48 flex-col items-center justify-center gap-3 text-center">
      <LoaderCircle className="h-5 w-5 animate-spin text-mint-300" aria-hidden="true" />
      <p className="text-sm text-slate-400">正在读取任务详情…</p>
    </div>
  )
}

function MissingTaskState() {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center gap-3 text-center">
      <ListTodo className="h-6 w-6 text-slate-600" aria-hidden="true" />
      <div>
        <h3 className="text-sm font-semibold text-slate-200">未选择任务</h3>
        <p className="mt-1 text-xs text-slate-500">关闭抽屉并从任务中心选择一项。</p>
      </div>
    </div>
  )
}

function ErrorState({
  error,
  retrying,
  onRetry,
}: {
  error: unknown
  retrying: boolean
  onRetry: () => void
}) {
  const inaccessible = isTaskAccessError(error)

  return (
    <div role="alert" className="flex min-h-48 flex-col items-center justify-center text-center">
      <span className="flex h-10 w-10 items-center justify-center rounded-[10px] bg-rose/10 text-rose">
        <AlertTriangle className="h-5 w-5" aria-hidden="true" />
      </span>
      <h3 className="mt-3 text-sm font-semibold text-slate-100">
        {inaccessible ? '无法查看该任务' : '任务详情加载失败'}
      </h3>
      <p className="mt-1.5 max-w-md text-xs leading-5 text-slate-500">
        {collaborationErrorMessage(error)}
      </p>
      <Button
        type="button"
        variant="secondary"
        className="mt-4"
        loading={retrying}
        icon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
        onClick={onRetry}
      >
        重试
      </Button>
    </div>
  )
}

function RefreshNotice({
  error,
  retrying,
  onRetry,
}: {
  error: unknown
  retrying: boolean
  onRetry: () => void
}) {
  return (
    <div role="alert" className="mb-5 flex flex-col gap-3 rounded-[10px] bg-remind/[0.06] px-3.5 py-3 ring-1 ring-inset ring-remind/15 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-xs leading-5 text-remind">
        刷新失败，以下仍是最近一次成功读取的内容。{collaborationErrorMessage(error)}
      </p>
      <Button
        type="button"
        size="sm"
        variant="subtle"
        className="min-h-10 self-start sm:self-auto"
        loading={retrying}
        icon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
        onClick={onRetry}
      >
        重试
      </Button>
    </div>
  )
}

function facetLabel(facet: { label: string; value: string; rawValue: string | null }): string {
  if (facet.value !== 'unknown' || !facet.rawValue) return facet.label
  return `${facet.label}（${facet.rawValue}）`
}

function actorMark(actor: string): string {
  return Array.from(actor.trim())[0]?.toLocaleUpperCase() ?? '·'
}

function isTaskAccessError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404)
}

function formatTime(value: string | null): string {
  if (!value) return '未记录'
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? DATE_TIME_FORMATTER.format(timestamp) : value
}
