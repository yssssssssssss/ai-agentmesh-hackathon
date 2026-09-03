import { useEffect, useState, type FormEvent } from 'react'

import type { MemoryLifecycleAction } from '../../features/knowledge/api'
import type { KnowledgeAssetView } from '../../features/knowledge/presenter'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'

interface RevisionProps {
  open: boolean
  asset: KnowledgeAssetView | null
  busy: boolean
  error: string | null
  onClose: () => void
  onSubmit: (values: { title: string; summary: string; memoryType: string }) => void
}

export function MemoryRevisionDialog({ open, asset, busy, error, onClose, onSubmit }: RevisionProps) {
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [memoryType, setMemoryType] = useState('')

  useEffect(() => {
    if (!open || !asset) return
    setTitle(asset.title.value)
    setSummary(asset.conclusion.value)
    setMemoryType(asset.type.value)
  }, [open, asset?.id.value])

  const changed = asset !== null && (
    title.trim() !== asset.title.value
    || summary.trim() !== asset.conclusion.value
    || memoryType.trim() !== asset.type.value
  )
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!asset || !title.trim() || !summary.trim() || !memoryType.trim() || !changed) return
    onSubmit({
      title: title.trim(),
      summary: summary.trim(),
      memoryType: memoryType.trim(),
    })
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="提交团队知识修订"
      subtitle="新内容先成为候选，独立审核通过后才替代当前版本。"
      footer={(
        <>
          <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
          <Button type="submit" form="memory-revision-form" loading={busy} disabled={!title.trim() || !summary.trim() || !memoryType.trim() || !changed}>
            提交修订候选
          </Button>
        </>
      )}
    >
      <form id="memory-revision-form" className="space-y-4" onSubmit={submit}>
        {error ? <p role="alert" className="rounded-soft border border-rose/25 bg-rose/10 px-3 py-2 text-sm text-rose">{error}</p> : null}
        <p className="rounded-soft bg-base px-3 py-2 text-xs leading-5 text-slate-400">
          来源版本 v{asset?.version.value ?? 1} 保持不可变。修订被接受时，来源版本会原子标记为已废弃。
        </p>
        <Field label="标题">
          <input
            data-autofocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={200}
            className="h-11 w-full rounded-soft border border-white/[0.08] bg-base px-3 text-sm text-slate-100 outline-none focus:border-mint-400/60 focus:ring-2 focus:ring-mint-400/15"
          />
        </Field>
        <Field label="摘要">
          <textarea
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            maxLength={2000}
            rows={7}
            className="w-full resize-y rounded-soft border border-white/[0.08] bg-base px-3 py-2 text-sm leading-6 text-slate-100 outline-none focus:border-mint-400/60 focus:ring-2 focus:ring-mint-400/15"
          />
        </Field>
        <Field label="记忆类型">
          <input
            value={memoryType}
            onChange={(event) => setMemoryType(event.target.value)}
            maxLength={80}
            className="h-11 w-full rounded-soft border border-white/[0.08] bg-base px-3 text-sm text-slate-100 outline-none focus:border-mint-400/60 focus:ring-2 focus:ring-mint-400/15"
          />
        </Field>
      </form>
    </Modal>
  )
}

interface TransitionTarget {
  id: string
  title: string
  version: number
  action: MemoryLifecycleAction
}

interface TransitionProps {
  target: TransitionTarget | null
  busy: boolean
  error: string | null
  onClose: () => void
  onConfirm: () => void
}

export function MemoryTransitionDialog({ target, busy, error, onClose, onConfirm }: TransitionProps) {
  if (!target) return null
  const copy = TRANSITION_COPY[target.action]
  return (
    <Modal
      open
      onClose={onClose}
      title={copy.title}
      subtitle={target.title}
      footer={(
        <>
          <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
          <Button
            type="button"
            variant={copy.danger ? 'danger' : 'secondary'}
            loading={busy}
            onClick={onConfirm}
          >
            {copy.confirm}
          </Button>
        </>
      )}
    >
      <div className="space-y-3 text-sm leading-6 text-slate-300">
        {error ? <p role="alert" className="rounded-soft border border-rose/25 bg-rose/10 px-3 py-2 text-rose">{error}</p> : null}
        <p>{copy.description}</p>
        <p className="text-xs text-slate-400">将以服务端版本 v{target.version} 执行；版本变化时操作会被拒绝并刷新。</p>
      </div>
    </Modal>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs font-medium text-slate-300">
      <span className="mb-1.5 block">{label}</span>
      {children}
    </label>
  )
}

const TRANSITION_COPY: Record<MemoryLifecycleAction, {
  title: string
  confirm: string
  description: string
  danger: boolean
}> = {
  dispute: {
    title: '标记团队知识存在争议',
    confirm: '标记争议',
    description: '该版本会立即退出 Agent 自动上下文，但历史记录和血缘保持可见。',
    danger: true,
  },
  deprecate: {
    title: '废弃团队知识版本',
    confirm: '确认废弃',
    description: '该版本会退出自动检索。需要替代内容时，请先创建修订候选。',
    danger: true,
  },
  expire: {
    title: '将记忆标记为失效',
    confirm: '确认失效',
    description: '失效版本不会进入 Agent 自动上下文。待审核候选的审核任务也会同步关闭。',
    danger: true,
  },
  archive: {
    title: '归档记忆版本',
    confirm: '确认归档',
    description: '归档会保留当前生命周期状态，之后可由有权限的维护者恢复。',
    danger: false,
  },
  restore: {
    title: '恢复归档记忆',
    confirm: '确认恢复',
    description: '记忆会恢复到归档前的状态；只有原状态为 accepted 时才重新进入自动检索。',
    danger: false,
  },
}

export type { TransitionTarget as MemoryTransitionTarget }
