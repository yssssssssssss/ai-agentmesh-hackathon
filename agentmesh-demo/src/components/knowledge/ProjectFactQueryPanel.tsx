import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { components } from '../../api/generated/schema'
import { buildFactQuery, factQueryError, queryFacts, type FactQuery, type FactQueryForm,
  type FactQueryResult } from '../../features/knowledge/factsApi'
import { Button } from '../ui/Button'

const PREDICATES = { owner: '负责人', participant: '参与人', decision: '决策', constraint: '约束', status: '记录的状态' }
const OUTCOMES = { known: '找到有来源的事实', unknown: '尚无可用事实', conflict: '发现冲突，需要核对',
  insufficient_evidence: '证据不足，需要补充或确认' }
const MISSING: Record<string, string> = {
  fact_valid_time_unknown: '部分记录没有明确的有效时间。',
  fact_evidence_unavailable: '部分事实的来源已经更新、撤回或不可访问。',
  fact_content_requires_review: '部分内容需要审核后才能引用。',
  fact_requires_confirmation: '部分推断尚未经过确认。',
  fact_memory_limit_exceeded: '候选记忆较多，结果未覆盖全部记录。',
  fact_result_limit_exceeded: '结果较多，已展示部分事实。',
}
const SOURCE_NAMES = { document: '来源资料', artifact: '交付依据', source: '原始来源', source_span: '来源片段',
  task_review: '验收记录' }
const inputClass = 'mt-1 block w-full rounded-control border border-white/10 bg-surface-1 p-2 text-sm text-slate-200'
const dateLabel = (value: string) => new Date(value).toLocaleString('zh-CN')

function evidenceHref(projectId: string, ref: components['schemas']['MemoryEvidenceRefV1']): string | undefined {
  if (ref.record_type === 'document') return `/knowledge?${new URLSearchParams({ project: projectId, document: ref.record_id })}`
  if (ref.record_type === 'artifact') return `/api/artifacts/${encodeURIComponent(ref.record_id)}`
  return undefined
}

export function ProjectFactResults({ result }: { result: FactQueryResult }) {
  const facts = result.facts ?? []
  const conflicting = new Set(result.conflicts?.flatMap((conflict) => conflict.fact_indexes) ?? [])
  return <div className="space-y-3" aria-label="事实查询结果">
    <p role="status" className={result.outcome === 'known' ? 'text-sm text-mint-300' : 'text-sm text-amber-300'}>
      {OUTCOMES[result.outcome]}
    </p>
    <p className="text-xs text-slate-400">查询时间：{dateLabel(result.snapshot_at)}。结果按查询时的权限和来源核对。</p>
    {result.outcome === 'unknown' ? <p className="text-xs text-slate-400">可以同步或导入项目资料，再确认事实。未找到记录不代表事实不存在。</p> : null}
    {result.outcome === 'conflict' ? <p className="text-xs text-slate-400">以下记录存在不一致，请核对来源后纠正记忆。</p> : null}
    {result.term_resolution ? <p className="text-xs text-slate-400">已按项目确认的术语别名查询 · 词典 v{result.term_resolution.alias_version}</p> : null}
    {(result.missing_data ?? []).length ? <ul className="space-y-1 text-xs text-amber-300">
      {result.missing_data?.map((code) => <li key={code}>{MISSING[code] ?? '部分证据暂不满足引用条件。'}</li>)}
    </ul> : null}
    <ul className="space-y-3">
      {facts.map((hit, index) => <li key={`${hit.memory_record_type}:${hit.memory_id}:${index}`}
        className="space-y-2 rounded-control border border-white/10 p-3">
        <p className="break-words text-sm text-slate-100">{hit.fact.value}</p>
        {conflicting.has(index) || hit.status === 'disputed' ? <p className="text-xs text-amber-300">冲突记录</p> : null}
        <p className="text-xs text-slate-400">有效时间：{hit.fact.valid_from ? dateLabel(hit.fact.valid_from) : '未知'} 至{' '}
          {hit.fact.valid_to ? `${dateLabel(hit.fact.valid_to)}（不含结束时刻）` : '未指定结束时间'}</p>
        <p className="text-xs text-slate-400">记录时间：{dateLabel(hit.fact.observed_at)} ·{' '}
          {hit.memory_record_type === 'user_memory_item' ? '本人私有记忆' : '团队记忆'}</p>
        <a className="text-xs text-mint-300 hover:underline" href={`/knowledge?${new URLSearchParams({
          project: result.project_id, memory: hit.memory_id,
        })}`}>查看来源记忆 · 查询时 v{hit.memory_version}</a>
        <ul className="space-y-1 text-xs text-slate-400" aria-label="事实依据">
          {hit.fact.evidence_refs.map((ref, refIndex) => <li key={refIndex}>
            {evidenceHref(result.project_id, ref) ? <a className="text-mint-300 hover:underline"
              href={evidenceHref(result.project_id, ref)}>{SOURCE_NAMES[ref.record_type]} · v{ref.version}</a>
              : <span>{SOURCE_NAMES[ref.record_type]} · v{ref.version}</span>}
          </li>)}
        </ul>
      </li>)}
    </ul>
  </div>
}

export function ProjectFactQueryPanel({ userId, workspaceId, projectId }: {
  userId: string; workspaceId: string; projectId: string
}) {
  const [form, setForm] = useState<FactQueryForm>({ subjectType: 'project', subject: '', predicate: 'owner',
    timeMode: 'current', at: '', until: '', observedBefore: '' })
  const [request, setRequest] = useState<FactQuery | null>(null)
  const [error, setError] = useState('')
  const query = useQuery({ queryKey: ['project-facts', userId, workspaceId, projectId, request],
    queryFn: ({ signal }) => {
      if (!request) throw new Error('fact_query_required')
      return queryFacts(request, signal)
    }, enabled: Boolean(request && userId && workspaceId && projectId), retry: false, staleTime: 0 })
  const change = (next: Partial<FactQueryForm>) => {
    setForm((current) => ({ ...current, ...next }))
    setRequest(null)
    setError('')
  }
  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    try {
      const next = buildFactQuery(projectId, form)
      setError('')
      if (request && JSON.stringify(request) === JSON.stringify(next)) void query.refetch()
      else setRequest(next)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '请检查查询条件。')
    }
  }
  return <section aria-label="项目事实查询" className="space-y-4 rounded-soft border border-white/10 p-4">
    <h2 className="text-sm font-semibold text-slate-100">项目事实查询</h2>
    <p className="text-xs text-slate-400">查询已确认记忆中的负责人、决策和约束，并核对历史变化。{' '}
      <a className="text-mint-300 hover:underline" href={`/tasks?${new URLSearchParams({ project: projectId })}`}>实时任务进度与阻塞查看任务页</a>。
    </p>
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-xs text-slate-300">查询对象<select className={inputClass} value={form.subjectType}
          onChange={(event) => change({ subjectType: event.target.value as FactQueryForm['subjectType'] })}>
          <option value="project">当前项目</option><option value="term">概念或模块</option>
        </select></label>
        {form.subjectType === 'term' ? <label className="text-xs text-slate-300">概念或模块名称
          <input className={inputClass} required maxLength={100} value={form.subject}
            placeholder="例如：登录网关" onChange={(event) => change({ subject: event.target.value })} />
        </label> : null}
        <label className="text-xs text-slate-300">查询内容<select className={inputClass} value={form.predicate}
          onChange={(event) => change({ predicate: event.target.value })}>
          {Object.entries(PREDICATES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label className="text-xs text-slate-300">有效时间<select className={inputClass} value={form.timeMode}
          onChange={(event) => change({ timeMode: event.target.value as FactQueryForm['timeMode'] })}>
          <option value="current">当前</option><option value="point">历史时刻</option><option value="interval">时间区间</option>
        </select></label>
      </div>
      {form.timeMode !== 'current' ? <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs text-slate-300">{form.timeMode === 'point' ? '历史时刻' : '开始时间'}
          <input type="datetime-local" required className={inputClass} value={form.at}
            onChange={(event) => change({ at: event.target.value })} />
        </label>
        {form.timeMode === 'interval' ? <label className="text-xs text-slate-300">结束时间（不含）
          <input type="datetime-local" required className={inputClass} value={form.until}
            onChange={(event) => change({ until: event.target.value })} />
        </label> : null}
        <p className="text-xs text-slate-400">时间采用当前设备的时区。</p>
      </div> : null}
      <details className="text-xs text-slate-400">
        <summary className="cursor-pointer">按当时已记录的信息回查</summary>
        <label className="mt-2 block">只查询此时间之前已记录的事实（可选）
          <input type="datetime-local" className={inputClass} value={form.observedBefore}
            onChange={(event) => change({ observedBefore: event.target.value })} />
        </label>
      </details>
      <Button size="sm" type="submit" disabled={query.isFetching}>查询事实</Button>
    </form>
    {error ? <p role="alert" className="text-xs text-rose">{error}</p> : null}
    {request && query.isFetching ? <p role="status" className="text-xs text-slate-400">正在核对事实与来源…</p> : null}
    {request && !query.isFetching && query.error ? <p role="alert" className="text-xs text-rose">{factQueryError(query.error)}</p> : null}
    {request && !query.isFetching && !query.error && query.data ? <ProjectFactResults result={query.data} /> : null}
  </section>
}
