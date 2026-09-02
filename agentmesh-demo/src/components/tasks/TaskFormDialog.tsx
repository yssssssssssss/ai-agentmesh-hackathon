import { useEffect, useState, type FormEvent, type ReactNode } from 'react'

import type { components } from '../../api/generated/schema'
import { taskDeliveryStageLabel } from '../../features/tasks/managementPresentation'
import type {
  ManagedTask,
  TaskArtifactSummary,
  TaskAssigneeKind,
  TaskManagementAction,
  TaskMemoryLink,
  TaskPriority,
  TaskReviewView,
  TaskRunSummary,
  TaskType,
} from '../../features/tasks/types'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'

export interface TaskFormValues {
  title: string
  description: string
  taskType: TaskType
  priority: TaskPriority | null
  dueAt: string | null
  assigneeKind: TaskAssigneeKind | null
  assigneeId: string | null
  tags: string[]
}

interface TaskFormDialogProps {
  open: boolean
  task: ManagedTask | null
  users: components['schemas']['User'][]
  agents: components['schemas']['Agent'][]
  submitting: boolean
  runtimeReady: boolean
  runs: TaskRunSummary[]
  artifacts: TaskArtifactSummary[]
  reviews: TaskReviewView[]
  memoryLinks: TaskMemoryLink[]
  historyTruncated: boolean
  reviewsTruncated: boolean
  detailError: string | null
  detailRetrying: boolean
  error: string | null
  notice: string | null
  onClose: () => void
  onRetryDetail: () => void
  onSubmit: (values: TaskFormValues) => void
  onAction: (action: TaskManagementAction, reason?: string) => void
  onSubmitReview: (runId: string, artifactIds: string[]) => void
  onDecideReview: (
    reviewId: string,
    expectedVersion: number,
    decision: 'accepted' | 'changes_requested' | 'rejected',
    decisionNote: string | null,
  ) => void
  onCaptureMemory: (
    reviewId: string,
    target: 'personal' | 'team_candidate',
    title: string,
    summary: string,
  ) => void
}

const TASK_TYPES: Array<{ value: TaskType; label: string }> = [
  { value: 'project_action', label: '项目行动' },
  { value: 'design', label: '设计' },
  { value: 'research', label: '研究' },
  { value: 'data', label: '数据' },
  { value: 'risk', label: '风险' },
  { value: 'review', label: '评审' },
  { value: 'milestone', label: '里程碑' },
]

const PRIORITIES: Array<{ value: TaskPriority; label: string }> = [
  { value: 'p0', label: 'P0 紧急' },
  { value: 'p1', label: 'P1 高' },
  { value: 'p2', label: 'P2 中' },
  { value: 'p3', label: 'P3 低' },
]

const ACTION_LABELS: Partial<Record<TaskManagementAction, string>> = {
  plan: '进入计划',
  start: '开始任务',
  submit_review: '进入审核',
  complete: '完成任务',
  reopen: '重新打开',
  block: '标记阻塞',
  unblock: '解除阻塞',
  cancel: '取消任务',
  archive: '归档任务',
  start_agent_run: '启动个人 Agent',
}

function datetimeLocalValue(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

export function TaskFormDialog({
  open,
  task,
  users,
  agents,
  submitting,
  runtimeReady,
  runs,
  artifacts,
  reviews,
  memoryLinks,
  historyTruncated,
  reviewsTruncated,
  detailError,
  detailRetrying,
  error,
  notice,
  onClose,
  onRetryDetail,
  onSubmit,
  onAction,
  onSubmitReview,
  onDecideReview,
  onCaptureMemory,
}: TaskFormDialogProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [taskType, setTaskType] = useState<TaskType>('project_action')
  const [priority, setPriority] = useState<TaskPriority | ''>('')
  const [dueAt, setDueAt] = useState('')
  const [assignee, setAssignee] = useState('')
  const [tags, setTags] = useState('')
  const [blockReason, setBlockReason] = useState('')
  const [reviewRunId, setReviewRunId] = useState('')
  const [selectedArtifactIds, setSelectedArtifactIds] = useState<string[]>([])
  const [decisionNote, setDecisionNote] = useState('')
  const [memoryTitle, setMemoryTitle] = useState('')
  const [memorySummary, setMemorySummary] = useState('')
  const editable = task === null || task.allowed_actions.includes('edit')
  const completedRuns = runs.filter((run) => (
    run.can_submit_review
    && (run.status === 'completed' || run.status === 'partial')
    && artifacts.some((artifact) => artifact.run_id === run.id)
  ))
  const reviewArtifacts = artifacts.filter((artifact) => artifact.run_id === reviewRunId)
  const linkedExecution = runs.length > 0
  const canSubmitArtifactReview = task?.allowed_actions.includes('submit_review') === true && linkedExecution

  useEffect(() => {
    if (!open) return
    // A version refresh after a 409 must not erase the user's unsaved form fields.
    const management = task?.management
    setTitle(task?.task.title ?? '')
    setDescription(management?.description ?? '')
    setTaskType(management?.task_type ?? 'project_action')
    setPriority(management?.priority ?? '')
    setDueAt(datetimeLocalValue(management?.due_at))
    setAssignee(
      management?.assignee_kind && management.assignee_id
        ? `${management.assignee_kind}:${management.assignee_id}`
        : '',
    )
    setTags(management?.tags.join(', ') ?? '')
    setBlockReason(management?.blocked_reason ?? '')
    setReviewRunId('')
    setSelectedArtifactIds([])
    setDecisionNote('')
    setMemoryTitle(task?.task.title ?? '')
    setMemorySummary(management?.description ?? '')
  }, [open, task?.task.id])

  useEffect(() => {
    if (!open || !task || reviewRunId || completedRuns.length === 0) return
    const initialRunId = completedRuns[0].id
    setReviewRunId(initialRunId)
    setSelectedArtifactIds(
      artifacts.filter((artifact) => artifact.run_id === initialRunId).map((artifact) => artifact.id),
    )
  }, [artifacts, completedRuns, open, reviewRunId, task])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!editable) return
    const [assigneeKind, assigneeId] = assignee ? assignee.split(':', 2) : []
    onSubmit({
      title: title.trim(),
      description: description.trim(),
      taskType,
      priority: priority || null,
      dueAt: dueAt ? new Date(dueAt).toISOString() : null,
      assigneeKind: (assigneeKind as TaskAssigneeKind | undefined) ?? null,
      assigneeId: assigneeId ?? null,
      tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean),
    })
  }

  const chooseReviewRun = (runId: string) => {
    setReviewRunId(runId)
    setSelectedArtifactIds(
      artifacts.filter((artifact) => artifact.run_id === runId).map((artifact) => artifact.id),
    )
  }

  const toggleReviewArtifact = (artifactId: string) => {
    setSelectedArtifactIds((current) => (
      current.includes(artifactId)
        ? current.filter((candidate) => candidate !== artifactId)
        : [...current, artifactId]
    ))
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={task ? '编辑任务' : '新建任务'}
      subtitle="任务管理状态与 Agent 执行状态相互独立。"
      footer={(
        <>
          <Button type="button" variant="ghost" onClick={onClose}>{editable ? '取消' : '关闭'}</Button>
          {editable ? (
            <Button type="submit" form="task-management-form" loading={submitting} disabled={!title.trim()}>
              {task ? '保存任务' : '创建任务'}
            </Button>
          ) : null}
        </>
      )}
    >
      <form id="task-management-form" className="space-y-4" onSubmit={submit}>
        {task?.management.archived_at ? (
          <p role="status" className="rounded-lg bg-white/[0.04] px-3 py-2 text-sm text-slate-400">
            该任务已归档，当前内容仅供查看。
          </p>
        ) : null}
        <Field label="任务标题">
          <input
            data-autofocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={200}
            required
            disabled={!editable || submitting}
            className={inputClassName}
          />
        </Field>
        <Field label="任务描述">
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={4000}
            rows={4}
            disabled={!editable || submitting}
            className={inputClassName}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="任务类型">
            <select value={taskType} disabled={!editable || submitting} onChange={(event) => setTaskType(event.target.value as TaskType)} className={inputClassName}>
              {TASK_TYPES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </Field>
          <Field label="优先级">
            <select value={priority} disabled={!editable || submitting} onChange={(event) => setPriority(event.target.value as TaskPriority | '')} className={inputClassName}>
              <option value="">未设置</option>
              {PRIORITIES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="截止时间">
            <input type="datetime-local" value={dueAt} disabled={!editable || submitting} onChange={(event) => setDueAt(event.target.value)} className={inputClassName} />
          </Field>
          <Field label="负责人">
            <select value={assignee} disabled={!editable || submitting} onChange={(event) => setAssignee(event.target.value)} className={inputClassName}>
              <option value="">未分派</option>
              <optgroup label="项目成员">
                {users.map((user) => <option key={user.id} value={`user:${user.id}`}>{user.name}</option>)}
              </optgroup>
              <optgroup label="Agent">
                {agents.filter((agent) => agent.status === 'online').map((agent) => (
                  <option key={agent.id} value={`agent:${agent.id}`}>{agent.name}</option>
                ))}
              </optgroup>
            </select>
          </Field>
        </div>
        <Field label="标签" hint="使用英文逗号分隔，最多 12 个。">
          <input value={tags} disabled={!editable || submitting} onChange={(event) => setTags(event.target.value)} className={inputClassName} />
        </Field>
        {task ? (
          <section className="border-t border-white/[0.06] pt-4" aria-label="任务状态操作">
            <p className="text-xs font-medium text-slate-400">
              交付阶段：<span className="text-slate-200">{taskDeliveryStageLabel(task.management.delivery_stage)}</span>
            </p>
            {task.allowed_actions.includes('block') ? (
              <Field label="阻塞原因">
                <input
                  value={blockReason}
                  onChange={(event) => setBlockReason(event.target.value)}
                  maxLength={1000}
                  placeholder="说明当前阻塞条件"
                  className={inputClassName}
                />
              </Field>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-2">
              {task.allowed_actions
                .filter((action) => (
                  action !== 'edit'
                  && action !== 'assign'
                  && action !== 'review_deliverable'
                  && !(action === 'submit_review' && linkedExecution)
                ))
                .map((action) => (
                  <Button
                    key={action}
                    type="button"
                    size="sm"
                    variant={action === 'cancel' || action === 'archive' ? 'ghost' : 'secondary'}
                    disabled={
                      submitting
                      || (action === 'block' && !blockReason.trim())
                      || (action === 'start_agent_run' && !runtimeReady)
                    }
                    onClick={() => onAction(action, action === 'block' ? blockReason.trim() : undefined)}
                  >
                    {ACTION_LABELS[action] ?? action}
                  </Button>
                ))}
            </div>
          </section>
        ) : null}
        {task && canSubmitArtifactReview ? (
          <section className="border-t border-white/[0.06] pt-4" aria-label="提交产物审核">
            <h3 className="text-sm font-semibold text-slate-200">提交产物审核</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              选择一次已完成执行及其通过完整性校验的封存产物。提交后，产物 ID 与内容哈希会冻结。
            </p>
            {completedRuns.length > 0 ? (
              <div className="mt-3 space-y-3">
                <Field label="审核 Run">
                  <select
                    value={reviewRunId}
                    disabled={submitting}
                    onChange={(event) => chooseReviewRun(event.target.value)}
                    className={inputClassName}
                  >
                    {completedRuns.map((run) => (
                      <option key={run.id} value={run.id}>{run.id} · {run.status}</option>
                    ))}
                  </select>
                </Field>
                <fieldset>
                  <legend className="text-xs font-medium text-slate-400">封存产物</legend>
                  <div className="mt-2 space-y-2">
                    {reviewArtifacts.map((artifact) => (
                      <label key={artifact.id} className="flex min-h-10 items-start gap-2 rounded-lg border border-white/[0.06] px-3 py-2 text-xs text-slate-300">
                        <input
                          type="checkbox"
                          checked={selectedArtifactIds.includes(artifact.id)}
                          disabled={submitting}
                          onChange={() => toggleReviewArtifact(artifact.id)}
                          className="mt-0.5"
                        />
                        <span className="min-w-0">
                          <span className="block break-all font-medium text-slate-200">{artifact.id}</span>
                          <span className="mt-0.5 block text-slate-500">{artifact.artifact_type} · {artifact.verification_state}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <Button
                  type="button"
                  size="sm"
                  loading={submitting}
                  disabled={!reviewRunId || selectedArtifactIds.length === 0}
                  onClick={() => onSubmitReview(reviewRunId, selectedArtifactIds)}
                >
                  提交审核
                </Button>
              </div>
            ) : (
              <p role="note" className="mt-3 rounded-lg bg-white/[0.04] px-3 py-2 text-xs text-slate-500">
                当前没有同时满足“Run 已完成”和“产物已封存”的交付物。
              </p>
            )}
          </section>
        ) : null}
        {task && reviews.length > 0 ? (
          <section className="border-t border-white/[0.06] pt-4" aria-label="任务审核记录">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-200">审核记录</h3>
              <span className="text-xs text-slate-500">{reviews.length} 轮</span>
            </div>
            {reviewsTruncated ? <p className="mt-2 text-xs text-remind">仅显示最近的审核记录。</p> : null}
            <div className="mt-3 space-y-3">
              {reviews.map(({ review, allowed_actions: allowedActions }) => (
                <article key={review.id} className="rounded-lg bg-surface-1 px-3 py-3 ring-1 ring-inset ring-white/[0.05]">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="font-medium text-slate-200">第 {review.round} 轮 · {taskReviewStatusLabel(review.status)}</span>
                    <span className="text-slate-500">v{review.version}</span>
                  </div>
                  <p className="mt-2 break-all text-[11px] text-slate-500">
                    Run {review.run_id} · {review.artifact_ids.length} 个冻结产物
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500">审核人：{review.reviewer_id}</p>
                  <ul className="mt-2 space-y-1.5" aria-label={`第 ${review.round} 轮冻结产物`}>
                    {review.artifact_ids.map((artifactId, index) => (
                      <li key={artifactId} className="rounded-md border border-white/[0.05] px-2.5 py-2 text-[11px] text-slate-500">
                        <span className="block break-all text-slate-300">{artifactId}</span>
                        <span className="mt-1 block break-all font-mono">sha256:{review.artifact_hashes[index]}</span>
                        {allowedActions.length > 0 ? (
                          <a
                            className="mt-1.5 inline-block text-mint-300 hover:underline"
                            href={`/api/task-reviews/${encodeURIComponent(review.id)}/artifacts/${encodeURIComponent(artifactId)}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            检查冻结产物
                          </a>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                  {review.decision_note ? (
                    <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-5 text-slate-300">{review.decision_note}</p>
                  ) : null}
                  {allowedActions.length > 0 && allowedActions.some((action) => action !== 'capture_memory') ? (
                    <div className="mt-3 space-y-3">
                      <Field label="审核意见" hint="要求修改或拒绝时必填。">
                        <textarea
                          value={decisionNote}
                          onChange={(event) => setDecisionNote(event.target.value)}
                          maxLength={4000}
                          rows={3}
                          disabled={submitting}
                          className={inputClassName}
                        />
                      </Field>
                      <div className="flex flex-wrap gap-2">
                        {allowedActions.includes('accept') ? (
                          <Button
                            type="button"
                            size="sm"
                            loading={submitting}
                            onClick={() => onDecideReview(review.id, review.version, 'accepted', decisionNote.trim() || null)}
                          >
                            接受交付
                          </Button>
                        ) : null}
                        {allowedActions.includes('request_changes') ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            disabled={submitting || !decisionNote.trim()}
                            onClick={() => onDecideReview(review.id, review.version, 'changes_requested', decisionNote.trim())}
                          >
                            要求修改
                          </Button>
                        ) : null}
                        {allowedActions.includes('reject') ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="danger"
                            disabled={submitting || !decisionNote.trim()}
                            onClick={() => onDecideReview(review.id, review.version, 'rejected', decisionNote.trim())}
                          >
                            拒绝交付
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                  {allowedActions.includes('capture_memory') ? (
                    <div className="mt-3 space-y-3 border-t border-white/[0.06] pt-3">
                      <p className="text-xs font-medium text-slate-300">沉淀审核产物</p>
                      <Field label="记忆标题">
                        <input
                          value={memoryTitle}
                          onChange={(event) => setMemoryTitle(event.target.value)}
                          maxLength={200}
                          disabled={submitting}
                          className={inputClassName}
                        />
                      </Field>
                      <Field label="记忆摘要" hint="Task Review 通过不等于团队知识通过；团队候选仍需独立审核。">
                        <textarea
                          value={memorySummary}
                          onChange={(event) => setMemorySummary(event.target.value)}
                          maxLength={2000}
                          rows={3}
                          disabled={submitting}
                          className={inputClassName}
                        />
                      </Field>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={submitting || !memoryTitle.trim() || !memorySummary.trim()}
                          onClick={() => onCaptureMemory(
                            review.id,
                            'personal',
                            memoryTitle.trim(),
                            memorySummary.trim(),
                          )}
                        >
                          保存为个人记忆
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          disabled={submitting || !memoryTitle.trim() || !memorySummary.trim()}
                          onClick={() => onCaptureMemory(
                            review.id,
                            'team_candidate',
                            memoryTitle.trim(),
                            memorySummary.trim(),
                          )}
                        >
                          提交团队候选
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </section>
        ) : null}
        {task && memoryLinks.length > 0 ? (
          <section className="border-t border-white/[0.06] pt-4" aria-label="任务记忆资产">
            <div className="flex items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-200">记忆资产</h3>
              <span className="text-xs text-slate-500">{memoryLinks.length} 条</span>
            </div>
            <div className="mt-3 space-y-2">
              {memoryLinks.map((memory) => (
                <a
                  key={memory.id}
                  href={memory.navigation_href}
                  className="block rounded-lg border border-white/[0.06] px-3 py-2 text-xs hover:bg-white/[0.03]"
                >
                  <span className="font-medium text-slate-200">{memory.title}</span>
                  <span className="ml-2 text-slate-500">{memory.kind} · {memory.status} · v{memory.version}</span>
                </a>
              ))}
            </div>
          </section>
        ) : null}
        {task && (runs.length > 0 || artifacts.length > 0) ? (
          <section className="border-t border-white/[0.06] pt-4" aria-label="任务执行记录">
            <h3 className="text-sm font-semibold text-slate-200">执行记录</h3>
            <div className="mt-2 space-y-2">
              {historyTruncated ? <p className="text-xs text-remind">仅显示最近的执行和已封存产物。</p> : null}
              {runs.map((run) => (
                <div key={run.id} className="rounded-lg bg-surface-1 px-3 py-2 text-xs text-slate-400">
                  <span className="font-medium text-slate-200">{run.status}</span>
                  <span className="ml-2">{run.planning_mode}</span>
                  <span className="ml-2">{run.artifact_count} 个产物</span>
                  {run.navigation_href ? <a className="ml-2 text-mint-300 hover:underline" href={run.navigation_href}>打开 Run</a> : null}
                </div>
              ))}
              {artifacts.map((artifact) => (
                <div key={artifact.id} className="rounded-lg border border-white/[0.06] px-3 py-2 text-xs text-slate-500">
                  {artifact.artifact_type} · {artifact.verification_state ?? 'legacy_unverified'}
                  {artifact.download_href ? <a className="ml-2 text-mint-300 hover:underline" href={artifact.download_href}>打开产物</a> : null}
                </div>
              ))}
            </div>
          </section>
        ) : null}
        {detailError ? (
          <div role="alert" className="rounded-lg bg-remind/[0.08] px-3 py-3 text-sm text-remind">
            <p>任务权限与状态刷新失败，操作保持禁用。{detailError}</p>
            <Button
              type="button"
              className="mt-2"
              size="sm"
              variant="subtle"
              loading={detailRetrying}
              onClick={onRetryDetail}
            >
              重试任务详情
            </Button>
          </div>
        ) : null}
        {notice ? <p role="status" className="rounded-lg bg-mint-400/10 px-3 py-2 text-sm text-mint-300">{notice}</p> : null}
        {error ? <p role="alert" className="rounded-lg bg-rose/10 px-3 py-2 text-sm text-rose">{error}</p> : null}
      </form>
    </Modal>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-xs font-medium text-slate-400">
      {label}
      <span className="mt-1.5 block">{children}</span>
      {hint ? <span className="mt-1 block text-[11px] font-normal text-slate-600">{hint}</span> : null}
    </label>
  )
}

function taskReviewStatusLabel(status: TaskReviewView['review']['status']): string {
  return {
    pending: '待审核',
    accepted: '已接受',
    changes_requested: '要求修改',
    rejected: '已拒绝',
  }[status]
}

const inputClassName = 'min-h-10 w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50'
