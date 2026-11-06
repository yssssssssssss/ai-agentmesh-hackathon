import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { knowledgeApi, type DocumentRecord } from '../../features/knowledge/api'
import { knowledgeKeys } from '../../features/knowledge/queries'
import { Button } from '../ui/Button'

function commandError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return '资料或项目已不可访问，请刷新资料列表。'
    if (error.status === 409) return error.detail === 'document_chunk_requires_review'
      ? '已有片段被遗忘、归档或与正文不一致，请检查资料；重新导入不会恢复它们。'
      : '资料已变化，请读取最新版本并检查草稿后再操作。'
    if (error.status === 422) return '正文为空或超过导入上限，请检查并拆分资料。'
  }
  return '未能确认操作结果，请查看最新版本和片段数后再重试。'
}

export function DocumentMaintenancePanel({ userId, projectId, documents, loading = false, error = false }: {
  userId: string; projectId: string; documents: DocumentRecord[]; loading?: boolean; error?: boolean
}) {
  const client = useQueryClient()
  const [editing, setEditing] = useState<DocumentRecord | null>(null)
  const [draft, setDraft] = useState('')
  const [message, setMessage] = useState('')
  const available = documents.filter((document) => document.uploaded_by === userId && document.project_id === projectId)
  const latest = available.find((document) => document.id === editing?.id)
  const managed = Boolean(latest?.source?.snapshot || latest?.source?.origin)
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: knowledgeKeys.documentsRoot }),
    client.invalidateQueries({ queryKey: knowledgeKeys.memoryRoot }),
    client.invalidateQueries({ queryKey: ['memory-learning', userId] }),
    client.invalidateQueries({ queryKey: ['market'] }),
  ])
  const select = (document: DocumentRecord | undefined) => {
    setEditing(document ?? null)
    setDraft(document?.text ?? '')
    setMessage('')
  }
  const save = useMutation({ mutationFn: () => {
    if (!editing) throw new Error('document_required')
    return knowledgeApi.updateDocument({ documentId: editing.id, expectedVersion: editing.version, text: draft })
  }, onSuccess: async (result) => {
    setEditing(result.item)
    setDraft(result.item.text)
    setMessage(`正文已保存为 v${result.item.version}，旧检索片段已失效。可重新导入当前版本。`)
    await refresh()
  }, onError: async (failure) => { setMessage(commandError(failure)); await refresh() } })
  const reimport = useMutation({ mutationFn: () => {
    const target = managed ? latest : editing
    if (!target) throw new Error('document_required')
    return knowledgeApi.importDocument({ documentId: target.id, expectedVersion: target.version })
  }, onSuccess: async (result) => {
    setMessage(result.status === 'already_imported' ? `当前版本已有 ${result.chunk_count} 个检索片段。`
      : `当前版本已导入 ${result.chunk_count} 个检索片段。事实学习和团队共享仍需确认。`)
    await refresh()
  }, onError: async (failure) => { setMessage(commandError(failure)); await refresh() } })
  const busy = save.isPending || reimport.isPending
  const visible = editing && latest && !error
  return <section aria-label="编辑与重新导入资料" className="space-y-3 rounded-soft border border-white/10 p-4">
    <h2 className="text-sm font-semibold text-slate-100">编辑与重新导入资料</h2>
    <p className="text-xs text-slate-400">仅显示当前项目的本人资料。保存正文会使旧片段失效，并撤回自动协作摘要；重新导入单独生成当前版本的私有检索片段。</p>
    {loading ? <p className="text-xs text-slate-400">正在读取资料…</p> : null}
    {error ? <p role="alert" className="text-xs text-rose">无法读取资料，请刷新后再操作。</p> : null}
    <label className="block space-y-1 text-xs text-slate-400">选择要维护的资料
      <select aria-label="选择要维护的资料" value={latest?.id ?? ''} disabled={loading || error || busy}
        className="w-full rounded-control border border-white/10 bg-surface-2 p-2 text-sm text-slate-200"
        onChange={(event) => select(available.find((document) => document.id === event.target.value))}>
        <option value="">请选择资料</option>
        {available.map((document) => <option key={document.id} value={document.id}>{document.title} · v{document.version}</option>)}
      </select>
    </label>
    {visible ? <div className="space-y-3">
      <p className="text-xs text-slate-400">当前 v{latest.version} · 已导入 {latest.completed_chunks ?? 0}/{latest.expected_chunks ?? 0} 个片段</p>
      {!managed && latest.version !== editing.version ? <p role="alert" className="text-xs text-rose">资料已更新，当前草稿基于 v{editing.version}；请读取最新版本后检查。</p> : null}
      <label className="block space-y-1 text-xs text-slate-400">资料正文
        <textarea aria-label="资料正文" value={managed ? latest.text : draft} readOnly={managed}
          maxLength={100000} rows={8} disabled={busy}
          className="w-full rounded-control border border-white/10 bg-surface-2 p-3 text-sm text-slate-200"
          onChange={(event) => { setDraft(event.target.value); setMessage('') }} />
      </label>
      <p className="text-xs text-slate-400">{managed ? '正文由来源同步维护，请在原系统修改后同步。可以显式导入当前版本。'
        : '编辑上限 100,000 字符；有未保存的改动时，请先保存正文。'}</p>
      <div className="flex flex-wrap gap-2">
        {!managed ? <Button size="sm" loading={save.isPending} disabled={busy || !draft.trim() || draft.length > 100000 || draft === editing.text}
          onClick={() => save.mutate()}>保存正文</Button> : null}
        <Button size="sm" variant="secondary" loading={reimport.isPending} disabled={busy || (!managed && draft !== editing.text)}
          onClick={() => reimport.mutate()}>重新导入当前版本</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => select(latest)}>读取最新版本</Button>
      </div>
    </div> : null}
    {message ? <p role="status" className="text-sm text-slate-300">{message}</p> : null}
    {!loading && !error && available.length === 0 ? <p className="text-xs text-slate-400">当前项目尚无本人资料。</p> : null}
  </section>
}
