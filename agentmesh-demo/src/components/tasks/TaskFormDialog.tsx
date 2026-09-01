import { useEffect, useState, type FormEvent, type ReactNode } from 'react'

import type { components } from '../../api/generated/schema'
import { taskDeliveryStageLabel } from '../../features/tasks/managementPresentation'
import type {
  ManagedTask,
  TaskAssigneeKind,
  TaskManagementAction,
  TaskPriority,
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
  error: string | null
  onClose: () => void
  onSubmit: (values: TaskFormValues) => void
  onAction: (action: TaskManagementAction, reason?: string) => void
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
  error,
  onClose,
  onSubmit,
  onAction,
}: TaskFormDialogProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [taskType, setTaskType] = useState<TaskType>('project_action')
  const [priority, setPriority] = useState<TaskPriority | ''>('')
  const [dueAt, setDueAt] = useState('')
  const [assignee, setAssignee] = useState('')
  const [tags, setTags] = useState('')
  const [blockReason, setBlockReason] = useState('')
  const editable = task === null || task.allowed_actions.includes('edit')

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
  }, [open, task?.task.id])

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
                .filter((action) => action !== 'edit' && action !== 'assign')
                .map((action) => (
                  <Button
                    key={action}
                    type="button"
                    size="sm"
                    variant={action === 'cancel' || action === 'archive' ? 'ghost' : 'secondary'}
                    disabled={submitting || (action === 'block' && !blockReason.trim())}
                    onClick={() => onAction(action, action === 'block' ? blockReason.trim() : undefined)}
                  >
                    {ACTION_LABELS[action] ?? action}
                  </Button>
                ))}
            </div>
          </section>
        ) : null}
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

const inputClassName = 'min-h-10 w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50'
