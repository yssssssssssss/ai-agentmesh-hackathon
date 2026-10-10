import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../../api/client'
import { Button } from '../../../components/ui/Button'
import { marketApi, type QueryView } from '../api/marketApi'

interface Peer { id: string; name: string }
interface Props { userId: string; projectId: string; peers: Peer[]; selectedQueryId?: string | null }

export const QUERY_STATUS: Record<QueryView['status'], string> = {
  pending: '处理中', awaiting_confirm: '待本人确认', answered: '已回答', insufficient_evidence: '资料不足',
  blocked: '暂不可用', denied: '已拒绝', failed: '已中断',
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) return '状态或依据已变化，请刷新后重新操作。'
  if (error instanceof ApiError && [403, 404].includes(error.status)) return '当前无权访问这次代答或同事。'
  return '操作失败，请稍后重试。'
}

export function DelegatedQueryPanel({ userId, projectId, peers, selectedQueryId }: Props) {
  const cache = useQueryClient()
  const key = ['delegated-queries', userId, projectId]
  const consentKey = ['delegated-consents', userId, projectId]
  const queries = useQuery({ queryKey: key, queryFn: () => marketApi.queries(projectId), enabled: !!userId && !!projectId })
  const consents = useQuery({ queryKey: consentKey, queryFn: () => marketApi.consents(projectId), enabled: !!userId && !!projectId })
  const selected = useQuery({ queryKey: [...key, selectedQueryId], queryFn: () => marketApi.query(selectedQueryId!),
    enabled: !!userId && !!projectId && !!selectedQueryId })
  const [peerId, setPeerId] = useState('')
  const [question, setQuestion] = useState('')
  const [message, setMessage] = useState('')
  const command = useRef({ signature: '', id: '' })
  const consentCommand = useRef({ signature: '', id: '' })
  const adoptionCommands = useRef(new Map<string, string>())
  const peer = peers.find((item) => item.id === peerId) ?? peers[0]
  const consent = consents.data?.items.find((item) => item.grantee_id === peer?.id)

  const refresh = () => Promise.all([
    cache.invalidateQueries({ queryKey: key }), cache.invalidateQueries({ queryKey: consentKey }),
    cache.invalidateQueries({ queryKey: ['knowledge'] }),
  ])
  const create = useMutation({
    mutationFn: marketApi.createQuery,
    onSuccess: async (result) => {
      command.current = { signature: '', id: '' }
      setMessage(`代答请求：${QUERY_STATUS[result.status]}。`)
      await refresh()
    },
    onError: (error) => setMessage(errorMessage(error)),
  })
  const resolve = useMutation({
    mutationFn: ({ query, action }: { query: QueryView; action: 'approve' | 'deny' }) =>
      marketApi.resolveQuery(query.id, action, query.version),
    onSuccess: async (result) => { setMessage(`处理结果：${QUERY_STATUS[result.status]}。`); await refresh() },
    onError: (error) => setMessage(errorMessage(error)),
  })
  const adopt = useMutation({
    mutationFn: (query: QueryView) => {
      if (!query.artifact_hash || !query.current_available) throw new Error('Answer unavailable')
      const id = adoptionCommands.current.get(query.id) ?? crypto.randomUUID()
      adoptionCommands.current.set(query.id, id)
      return marketApi.adoptQuery(query.id, { command_id: id, expected_version: query.version, artifact_hash: query.artifact_hash })
    },
    onSuccess: async () => { setMessage('已采纳到我的私有知识，并记录来源与一次贡献。'); await refresh() },
    onError: (error) => setMessage(errorMessage(error)),
  })
  const updateConsent = useMutation({
    mutationFn: marketApi.setConsent,
    onSuccess: async (result) => { setMessage(result.enabled ? '已允许该同事在本项目自动提问，高敏资料仍需确认。' : '已撤销该同事的自动提问授权。'); await refresh() },
    onError: (error) => setMessage(errorMessage(error)),
  })
  const resume = useMutation({
    mutationFn: marketApi.resumeQuery,
    onSuccess: async (result) => { setMessage(`请求状态：${QUERY_STATUS[result.status]}。`); await refresh() },
    onError: (error) => setMessage(errorMessage(error)),
  })
  const busy = create.isPending || resolve.isPending || adopt.isPending || updateConsent.isPending || resume.isPending
  const selectedQuery = selected.data?.project_id === projectId ? selected.data : undefined
  const items = selectedQuery ? [selectedQuery, ...(queries.data?.items ?? []).filter((query) => query.id !== selectedQuery.id)]
    : queries.data?.items ?? []

  const submit = () => {
    if (!peer || !question.trim()) return
    const signature = JSON.stringify([projectId, peer.id, question.trim()])
    if (command.current.signature !== signature) command.current = { signature, id: crypto.randomUUID() }
    create.mutate({ project_id: projectId, target_id: peer.id, question: question.trim(), command_id: command.current.id })
  }
  const toggleConsent = () => {
    if (!peer || !consents.data) return
    const version = consent?.version ?? 0
    const enabled = !(consent?.enabled ?? false)
    const signature = JSON.stringify([projectId, peer.id, version, enabled])
    if (consentCommand.current.signature !== signature) consentCommand.current = { signature, id: crypto.randomUUID() }
    updateConsent.mutate({ project_id: projectId, grantee_id: peer.id, expected_version: version,
      enabled, command_id: consentCommand.current.id })
  }

  return <section className="card-base space-y-5 p-6" aria-labelledby="delegated-query-title">
    <div>
      <h2 id="delegated-query-title" className="text-base font-semibold text-slate-100">项目代答</h2>
      <p className="mt-1 text-sm text-slate-400">仅请求方和回答方可查看。默认由本人确认；采纳保存在我的私有知识中。</p>
    </div>
    <div className="grid gap-3 md:grid-cols-[1fr_2fr_auto]">
      <label className="space-y-1 text-sm text-slate-300">向同事提问
        <select aria-label="代答同事" className="w-full rounded-control border border-white/10 bg-slate-900 px-3 py-2 text-slate-100" value={peer?.id ?? ''} onChange={(event) => setPeerId(event.target.value)}>
          {!peer ? <option value="">暂无可选同事</option> : null}
          {peers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <label className="space-y-1 text-sm text-slate-300">问题
        <textarea aria-label="代答问题" className="w-full rounded-control border border-white/10 bg-slate-900 px-3 py-2 text-slate-100" rows={2} maxLength={2000} value={question}
          onChange={(event) => setQuestion(event.target.value)} />
      </label>
      <Button className="self-end" disabled={busy || !peer || !question.trim()} loading={create.isPending} onClick={submit}>发起代答</Button>
    </div>
    {peer ? <div className="flex flex-wrap items-center gap-3 text-sm text-slate-400">
      <span>允许 {peer.name} 的分身自动向我提问：{consent?.enabled ? '已授权' : '每次确认'}。双方加入市场后生效，高敏资料始终确认。</span>
      <Button size="sm" variant="secondary" disabled={busy || !consents.data} onClick={toggleConsent}>
        {consent?.enabled ? '撤销自动授权' : '允许自动提问'}
      </Button>
    </div> : null}
    {message ? <p role="status" className="text-sm text-slate-300">{message}</p> : null}
    {queries.error || consents.error || selected.error ? <p role="alert" className="text-sm text-rose">{errorMessage(queries.error ?? consents.error ?? selected.error)}</p> : null}
    <div className="flex items-center justify-between text-sm text-slate-400">
      <span>最近的本人代答请求</span><Button size="sm" variant="subtle" onClick={() => void refresh()}>刷新代答</Button>
    </div>
    {queries.isLoading ? <p className="text-sm text-slate-400">正在读取代答…</p> : null}
    {queries.data?.items.length === 0 ? <p className="text-sm text-slate-400">暂无代答请求。</p> : null}
    {items.map((query) => <article key={query.id} data-query-id={query.id} className="space-y-3 rounded-soft border border-white/10 p-4">
      <div className="flex items-start justify-between gap-3"><p className="text-sm text-slate-200">{query.question}</p>
        <span className="shrink-0 text-xs text-slate-400">{QUERY_STATUS[query.status]}</span></div>
      {query.answer ? <p className="whitespace-pre-wrap text-sm text-slate-300">{query.answer}</p> : null}
      {query.status === 'answered' && !query.current_available ? <p className="text-sm text-remind">当前授权、依据或产物已失效，答案不可读取或采纳。</p> : null}
      {query.citations?.map((citation) => <p key={citation.id} className="text-xs text-slate-400">来源：{citation.title}</p>)}
      {query.status === 'awaiting_confirm' && query.target_id === userId ? <div className="flex gap-2">
        <Button size="sm" disabled={busy} onClick={() => resolve.mutate({ query, action: 'approve' })}>同意本次代答</Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => resolve.mutate({ query, action: 'deny' })}>拒绝本次代答</Button>
      </div> : null}
      {query.status === 'pending' ? <Button size="sm" variant="secondary" disabled={busy} onClick={() => resume.mutate(query.id)}>
        检查并继续
      </Button> : null}
      {query.status === 'answered' && query.requester_id === userId && query.current_available ?
        <Button size="sm" variant="secondary" disabled={busy || !!query.adoption} onClick={() => adopt.mutate(query)}>
          {query.adoption ? '已采纳到我的私有知识' : '采纳到我的私有知识'}
        </Button> : null}
    </article>)}
  </section>
}
