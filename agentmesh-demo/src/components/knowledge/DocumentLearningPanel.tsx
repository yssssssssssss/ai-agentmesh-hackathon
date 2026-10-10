import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { knowledgeApi } from '../../features/knowledge/api'
import { knowledgeKeys } from '../../features/knowledge/queries'
import { learningApi, learningError, type LearningJob } from '../../features/knowledge/learningApi'
import { Button } from '../ui/Button'
import { StructuredMemoryPanel } from './StructuredMemoryPanel'
import { LearningHealthSummary } from './LearningHealthSummary'

export function DocumentLearningPanel({ userId, projectId }: { userId: string; projectId: string }) {
  const [documentId, setDocumentId] = useState('')
  const [selectedJob, setSelectedJob] = useState<string | null>(null)
  const client = useQueryClient()
  const key = ['memory-learning', userId]
  const documents = useQuery({ queryKey: [...key, 'documents', projectId], queryFn: knowledgeApi.documents })
  const status = useQuery({ queryKey: [...key, 'status'], queryFn: learningApi.status,
    refetchInterval: (query) => query.state.data && (query.state.data.cleanup_pending > 0
      || (query.state.data.mode === 'execute' && query.state.data.learning_enabled)) ? 5000 : false,
  })
  const jobs = useQuery({ queryKey: [...key, 'jobs'], queryFn: learningApi.jobs,
    refetchInterval: (query) => query.state.data?.some((job) => ['queued', 'running', 'retry_wait'].includes(job.status)) ? 5000 : false,
  })
  const refresh = () => client.invalidateQueries({ queryKey: key })
  const learn = useMutation({ mutationFn: async () => {
    const source = await learningApi.sourceIdentity(documentId)
    return learningApi.learn({ source_document_id: source.record_id, source_version: source.version, source_hash: source.content_hash })
  }, onSettled: refresh })
  const retry = useMutation({ mutationFn: learningApi.retry, onSettled: refresh })
  const sourceDocuments = (documents.data?.items ?? []).filter((doc) => doc.uploaded_by === userId && doc.project_id === projectId)
  const visibleJobs = (jobs.data ?? []).filter((job) => job.project_id === projectId)
  return <details className="card-base p-4">
    <summary className="cursor-pointer text-sm font-semibold text-slate-100">资料学习与待确认记忆</summary>
    <div className="mt-4 space-y-3">
      <p className="text-xs text-slate-400">引用必须能在当前原文中核对。学习结果仅为本人候选，确认时可以选择需要保留的事实。</p>
      {status.data ? <LearningHealthSummary status={status.data} /> : null}
      {status.data?.mode !== 'execute' ? <p className="text-xs text-amber-300">后台资料学习尚未启用。</p>
        : !status.data.learning_enabled ? <a className="text-xs text-mint-300" href="/digital-self">在数字员工页面开启资料学习</a> : null}
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-0 flex-1 text-xs text-slate-300">本项目的本人资料
          <select className="mt-1 block w-full rounded-control border border-white/10 bg-surface-1 p-2 text-sm"
            value={documentId} onChange={(event) => setDocumentId(event.target.value)}>
            <option value="">选择已上传资料</option>
            {sourceDocuments.map((doc) => <option key={doc.id} value={doc.id}>{doc.title} · v{doc.version}</option>)}
          </select>
        </label>
        <Button size="sm" loading={learn.isPending} disabled={!documentId || status.data?.mode !== 'execute' || !status.data.learning_enabled}
          onClick={() => learn.mutate()}>生成候选记忆</Button>
        <Button variant="subtle" size="sm" onClick={() => void refresh()}>刷新学习状态</Button>
      </div>
      {learn.error || retry.error ? <p role="alert" className="text-sm text-rose">{learningError(learn.error ?? retry.error)}</p> : null}
      {jobs.error ? <p role="alert" className="text-sm text-rose">无法读取学习记录。</p> : null}
      {visibleJobs.length === 0 && !jobs.isLoading ? <p className="text-xs text-slate-400">尚无本项目的资料学习记录。</p> : null}
      <ul className="space-y-2">
        {visibleJobs.map((job) => <li key={job.id} className="rounded-control bg-surface-1 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span>{sourceDocuments.find((doc) => doc.id === job.source_document_id)?.title ?? '已授权资料'} · v{job.source_version}</span>
            <span className="text-xs text-slate-400">{jobLabel(job)}</span>
          </div>
          {job.error_code ? <p className="mt-1 text-xs text-amber-300">{learningError(job.error_code)}</p> : null}
          <p className="mt-1 text-xs text-slate-500">已尝试 {job.attempt}/3 次 · 已报告 {job.actual_tokens} Token{job.usage_status === 'unknown' ? '（部分尝试用量未知）' : ''} · 预算预留 {job.reserved_tokens}/{job.token_cap}</p>
          {job.candidate_memory_id ? <Button variant="ghost" size="sm" onClick={() => setSelectedJob(selectedJob === job.id ? null : job.id)}>检查候选及原文</Button> : null}
          {['blocked', 'failed', 'cancelled'].includes(job.status) && job.attempt < 3 ? <Button variant="ghost" size="sm"
            loading={retry.isPending} disabled={status.data?.mode !== 'execute' || !status.data.learning_enabled}
            onClick={() => retry.mutate(job)}>重新尝试</Button> : null}
          {selectedJob === job.id ? <LearningCandidateReview key={job.id} userId={userId} job={job} /> : null}
        </li>)}
      </ul>
    </div>
  </details>
}

function jobLabel(job: LearningJob): string {
  if (job.status === 'completed') return job.candidate_memory_id ? '候选已生成' : '未发现可记录的事实'
  return { queued: '排队中', running: '正在学习', retry_wait: '等待重试', blocked: '暂不可执行', cancelled: '已停止', failed: '学习失败' }[job.status]
}

function LearningCandidateReview({ userId, job }: { userId: string; job: LearningJob }) {
  const [selected, setSelected] = useState<number[]>([])
  const client = useQueryClient()
  const key = ['memory-learning', userId]
  const candidate = useQuery({ queryKey: [...key, 'candidate', job.id], queryFn: () => learningApi.candidate(job.id) })
  const spans = useQuery({ queryKey: [...key, 'quotes', job.id], enabled: Boolean(candidate.data), queryFn: async () => {
    const refs = candidate.data?.facts?.flatMap((fact) => fact.evidence_refs).filter((ref) => ref.record_type === 'source_span') ?? []
    return Promise.all([...new Set(refs.map((ref) => ref.record_id))].map(learningApi.span))
  } })
  const confirm = useMutation({ mutationFn: () => learningApi.confirm(job.id, { command_id: crypto.randomUUID(),
    expected_memory_version: candidate.data!.version, selected_fact_indexes: selected }),
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: key }),
      client.invalidateQueries({ queryKey: knowledgeKeys.memoryRoot }), client.invalidateQueries({ queryKey: knowledgeKeys.inboxRoot })]),
  })
  if (candidate.isLoading) return <p className="mt-2 text-xs text-slate-400">正在读取候选…</p>
  if (!candidate.data || candidate.error) return <p role="alert" className="mt-2 text-xs text-rose">候选或来源已不可用，请刷新状态。</p>
  const memory = candidate.data
  return <div className="mt-3 space-y-3 border-t border-white/10 pt-3" aria-label="学习候选审核">
    <StructuredMemoryPanel memory={memory} />
    {spans.error ? <p role="alert" className="text-xs text-rose">引用原文已不可读取，无法确认。</p> : null}
    {(memory.facts ?? []).map((fact, index) => <div key={index} className="rounded-control border border-white/10 p-3">
      <label className="flex items-start gap-2 text-sm text-slate-200">
        <input type="checkbox" checked={selected.includes(index)} disabled={memory.status !== 'proposed' || confirm.isPending}
          onChange={(event) => setSelected((items) => event.target.checked ? [...items, index] : items.filter((item) => item !== index))} />
        <span>{fact.predicate}：{fact.value}</span>
      </label>
      {fact.evidence_refs.map((ref) => {
        const span = spans.data?.find((item) => item.id === ref.record_id)
        return span ? <blockquote key={ref.record_id} className="mt-2 whitespace-pre-wrap border-l-2 border-mint-400/30 pl-3 text-xs text-slate-400">{span.quote}</blockquote> : null
      })}
    </div>)}
    <p className="text-xs text-slate-400">有效时间未给出的事实仍会标记为资料不足，不会被当作当前事实自动使用。团队共享仍需独立审核。</p>
    {memory.status === 'proposed' ? <Button size="sm" loading={confirm.isPending} disabled={selected.length === 0 || !spans.data || Boolean(spans.error)}
      onClick={() => confirm.mutate()}>确认选中的事实</Button> : <p className="text-xs text-mint-300">本人已确认。</p>}
    {confirm.error ? <p role="alert" className="text-xs text-rose">{learningError(confirm.error)}</p> : null}
  </div>
}
