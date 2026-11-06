import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiRequest } from '../../api/client'
import type { components } from '../../api/generated/schema'
import { knowledgeKeys } from '../../features/knowledge/queries'
import { Button } from '../ui/Button'

type DocumentJob = components['schemas']['DocumentParseJob']
type JobPage = components['schemas']['DocumentJobsResponse']
const STATUS: Record<DocumentJob['status'], string> = {
  queued: '等待解析', running: '正在解析', completed: '导入完成', failed: '导入失败',
}
const ERRORS: Record<string, string> = {
  document_input_expired: '原始上传已到期清理，请重新上传。',
  document_input_unavailable: '原始上传已不可用，请重新上传。',
  document_input_integrity_failed: '原始上传校验失败，请重新上传。',
  document_input_reference_invalid: '原始上传不可读取，请重新上传。',
  document_authority_unavailable: '当前已无该项目的访问权限。',
  document_type_unsupported: '无法解析此文件类型，请转换为文本、PDF、Word 或幻灯片后重试。',
  document_text_encoding_invalid: '文本编码不可读取，请使用 UTF-8 文本。',
  document_parsed_text_too_large: '解析正文超过 1 MiB，请拆分资料。',
  document_parser_metadata_too_large: '资料标题或元数据过长，请简化后重新上传。',
  document_ingestion_queue_full: '解析队列已满，可以稍后重试。',
  document_ingestion_shutdown: '解析因服务停止而中断，可以重试。',
  document_job_version_conflict: '记录已更新，请根据最新状态操作。',
  document_attempt_limit_reached: '已达到尝试次数上限，请重新上传。',
  document_legacy_partial_import_requires_review: '旧导入留下不完整记录，请检查资料后重新上传。',
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === 'string' && ERRORS[error.detail]) return ERRORS[error.detail]
    if (error.status === 404) return '该项目或导入记录已不可访问。'
    if (error.status === 409) return '导入记录已变化或不可重试，请查看最新状态。'
  }
  return '操作未完成，请查看导入记录后再尝试。'
}

export function DocumentImportRow({ job, userId, busy, onRetry }: {
  job: DocumentJob; userId: string; busy: boolean; onRetry: () => void
}) {
  const retryable = job.status === 'failed' && job.uploaded_by === userId
    && Boolean(job.id) && Boolean(job.state_version)
    && job.input_contract === 'document-input-v1' && !job.input_purged
    && (job.attempt_count ?? 0) < 3 && !['document_input_expired', 'document_input_integrity_failed',
      'document_input_reference_invalid', 'document_input_unavailable',
      'document_legacy_partial_import_requires_review'].includes(job.error ?? '')
  return <li className="space-y-1 rounded-control border border-white/10 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="break-all text-sm text-slate-200">{job.file_name}</span>
      <span className="text-xs text-slate-400">{STATUS[job.status]} · 已尝试 {job.attempt_count ?? 0}/3</span>
    </div>
    {job.status === 'completed' ? <p className="text-xs text-mint-300">本次上传{job.version ? ` v${job.version}` : ''} 已导入 {job.completed_chunks ?? 0} 个检索片段。</p> : null}
    {job.error ? <p className="text-xs text-rose">{ERRORS[job.error] ?? ((job.attempt_count ?? 0) >= 3
      ? '已达到三次尝试上限，请重新上传。' : '解析或写入失败，可以重试。')}</p> : null}
    {job.input_cleanup_pending ? <p className="text-xs text-slate-400">{job.status === 'completed'
      ? '原始上传缓存等待清理，导入结果仍有效。' : '原始上传缓存等待清理。'}</p> : null}
    {retryable ? <Button size="sm" variant="secondary" loading={busy} onClick={onRetry}>重试解析</Button> : null}
  </li>
}

export function DocumentImportPanel({ userId, projectId }: { userId: string; projectId: string }) {
  const client = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [message, setMessage] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const commands = useRef(new Map<string, string>())
  const key = ['document-imports', userId, projectId]
  const jobs = useQuery({ queryKey: key, queryFn: () => apiRequest<JobPage>(
    `/api/documents/jobs?project_id=${encodeURIComponent(projectId)}&limit=50`,
  ), refetchInterval: (query) => query.state.data?.items.some((job) => ['queued', 'running'].includes(job.status)
    || job.input_cleanup_pending) ? 5000 : false })
  const refreshContent = () => Promise.all([
    client.invalidateQueries({ queryKey: knowledgeKeys.documentsRoot }),
    client.invalidateQueries({ queryKey: knowledgeKeys.memoryRoot }),
    client.invalidateQueries({ queryKey: ['memory-learning', userId] }),
  ])
  const signature = jobs.data?.items.map((job) => `${job.id}:${job.status}`).join(',') ?? ''
  useEffect(() => {
    if (jobs.data?.items.some((job) => job.status === 'completed')) void refreshContent()
    // Only completion transitions refresh derived material; polling never creates imports.
  }, [signature, client, userId])
  const refresh = async () => { await Promise.all([client.invalidateQueries({ queryKey: key }), refreshContent()]) }
  const upload = useMutation({ mutationFn: async () => {
    if (!file) throw new Error('file_required')
    if (file.size > 20 * 1024 * 1024) throw new ApiError(400, 'file_too_large', null)
    const body = new FormData()
    body.set('file', file)
    return apiRequest<{ item?: { id: string }; job?: DocumentJob }>(
      `/api/documents/upload?project_id=${encodeURIComponent(projectId)}`, { method: 'POST', body },
    )
  }, onSuccess: async (result) => {
    setMessage(result.item || result.job?.status === 'completed' ? '资料已导入。' : '上传已保存，等待解析。')
    setFile(null)
    if (fileInput.current) fileInput.current.value = ''
    await refresh()
  }, onError: async (error) => {
    setMessage(error instanceof ApiError && error.detail === 'file_too_large' ? '文件不能超过 20 MiB。' : errorMessage(error))
    await refresh()
  } })
  const retry = useMutation({ mutationFn: (job: DocumentJob) => {
    if (!job.id || !job.state_version) throw new Error('document_job_identity_unavailable')
    const id = `${job.id}:${job.state_version}`
    if (!commands.current.has(id)) commands.current.set(id, crypto.randomUUID())
    return apiRequest<components['schemas']['DocumentJobItemResponse']>(
      `/api/documents/jobs/${encodeURIComponent(job.id)}/retry`, { method: 'POST', body: JSON.stringify({
        expected_version: job.state_version, command_id: commands.current.get(id),
      }) },
    )
  }, onSuccess: async () => { setMessage('重试已受理，运行状态以导入记录为准。'); await refresh() },
  onError: async (error) => { setMessage(errorMessage(error)); await refresh() } })
  return <section aria-label="资料导入" className="space-y-3 rounded-soft border border-white/10 p-4">
    <h2 className="text-sm font-semibold text-slate-100">资料导入</h2>
    <p className="text-xs text-slate-400">上传进入当前项目的本人资料与检索片段，事实学习和团队共享仍需确认。文件上限 20 MiB，解析正文上限 1 MiB；未完成上传保留七天用于恢复。</p>
    <form className="flex flex-wrap items-center gap-3" onSubmit={(event) => { event.preventDefault(); setMessage(''); upload.mutate() }}>
      <input ref={fileInput} aria-label="选择要导入的资料" type="file" accept=".txt,.md,.markdown,.pdf,.docx,.pptx,.png,.jpg,.jpeg,.webp"
        disabled={upload.isPending} className="max-w-full text-sm text-slate-300" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
      <Button type="submit" size="sm" disabled={!file} loading={upload.isPending}>上传资料</Button>
    </form>
    {message ? <p role="status" className="text-sm text-slate-300">{message}</p> : null}
    {jobs.error ? <p role="alert" className="text-xs text-rose">无法读取导入记录。</p> : null}
    <p className="text-xs text-slate-400">最近 50 条导入记录</p>
    <ul className="space-y-2">{(jobs.data?.items ?? []).map((job) => <DocumentImportRow key={job.id} job={job}
      userId={userId} busy={retry.isPending} onRetry={() => retry.mutate(job)} />)}</ul>
    {!jobs.isLoading && !jobs.error && !jobs.data?.items.length ? <p className="text-xs text-slate-400">尚无资料导入记录。</p> : null}
  </section>
}
