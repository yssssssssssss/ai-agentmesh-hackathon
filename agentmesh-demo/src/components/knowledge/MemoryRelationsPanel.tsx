import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryScope } from '../../app/queryKeys'
import {
  createRelation, queryRelations, relationError, relationHref, relationKey, relationReference,
  type RelationCreate, type RelationGraph, type RelationRoot,
} from '../../features/knowledge/relationsApi'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'

const RELATIONS: Record<string, string> = {
  relates_to: '相关', supports: '支持', contradicts: '矛盾', supersedes: '替代', caused_by: '由此引起',
  depends_on: '依赖', child_of: '子任务', derived_from_task_review: '来自已通过的任务审核',
  derived_from_artifact: '来自交付依据', derived_from_memory: '来自记忆', shared_from_personal: '来自个人记忆', cites: '引用',
}
const ASSERTIONS = { native: '已核对来源', candidate: '候选关联', confirmed: '人工确认' }
const NODE_KINDS = { task: '任务', user_memory_item: '个人记忆', memory_item: '团队记忆', document: '文档', artifact: '交付依据' }
const TYPES = ['relates_to', 'supports', 'contradicts', 'supersedes', 'caused_by'] as const

export function MemoryRelationsPanel({ context, root, canCreate = false }: {
  context: QueryScope; root: RelationRoot; canCreate?: boolean
}) {
  const query = useQuery({
    queryKey: relationKey(context, root),
    queryFn: ({ signal }) => queryRelations(context, root, signal),
    enabled: Boolean(context.userId && context.workspaceId && context.projectId),
    staleTime: 0, retry: false,
  })
  return <section className="mt-6 space-y-3 rounded-xl border border-slate-700 bg-slate-900/40 p-4" aria-label="关联记录">
    <div className="flex items-center justify-between gap-3">
      <h3 className="text-sm font-semibold text-slate-100">关联记录</h3>
      <Button size="sm" variant="ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>刷新关联</Button>
    </div>
    <p className="text-xs leading-relaxed text-slate-400">查看当前可访问、依据仍有效的两层关联。候选关联需要人工判断。</p>
    {query.isLoading ? <p className="text-sm text-slate-400">正在查询关联…</p> : null}
    {query.error ? <p role="alert" className="text-sm text-remind">{relationError(query.error)}</p>
      : query.data ? <>
        <MemoryRelationsView graph={query.data} />
        {canCreate && ['user_memory_item', 'memory_item'].includes(root.record_type)
          ? <RelationComposer key={`${context.userId}:${context.workspaceId}:${context.projectId}:${root.record_type}:${root.record_id}`}
              context={context} graph={query.data} /> : null}
      </> : null}
  </section>
}

export function MemoryRelationsView({ graph }: { graph: RelationGraph }) {
  const nodes = new Map(graph.nodes.map((node) => [`${node.record_type}:${node.record_id}`, node]))
  return <div className="space-y-3">
    {graph.edges.length === 0 ? <p className="text-sm text-slate-400">暂无可展示的关联。</p> : <ul className="space-y-3">
      {graph.edges.map((edge) => {
        const source = nodes.get(edge.from_key)
        const target = nodes.get(edge.to_key)
        if (!source || !target) return null
        return <li key={edge.id} className="space-y-2 border-b border-slate-800 pb-3 text-sm last:border-0">
          <p className="break-words"><a className="text-mint-300 hover:underline" href={relationHref(source.navigation_href)}>{source.title} · v{source.version}</a>
            <span className="mx-2 text-slate-400">{RELATIONS[edge.relation_type] ?? '关联'}</span>
            <a className="text-mint-300 hover:underline" href={relationHref(target.navigation_href)}>{target.title} · v{target.version}</a></p>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={edge.assertion === 'candidate' ? 'remind' : 'neutral'}>{ASSERTIONS[edge.assertion]}</Badge>
            <span className="text-xs text-slate-500">{NODE_KINDS[source.record_type]} → {NODE_KINDS[target.record_type]}</span>
            {edge.evidence ? <span className="text-xs text-slate-500">{NODE_KINDS[edge.evidence.record_type]}依据 · v{edge.evidence.version}</span> : null}
          </div>
        </li>
      })}
    </ul>}
    {graph.truncated ? <p className="text-xs text-remind">已达到查询范围或数量限制，仅展示部分关联。</p> : null}
  </div>
}

function RelationComposer({ context, graph }: { context: QueryScope; graph: RelationGraph }) {
  const client = useQueryClient()
  const source = graph.nodes.find((node) => `${node.record_type}:${node.record_id}` === graph.root_key)
  const targets = graph.nodes.filter((node) => `${node.record_type}:${node.record_id}` !== graph.root_key)
  const evidenceNodes = graph.nodes.filter((node) => ['task', 'document'].includes(node.record_type))
  const [targetKey, setTargetKey] = useState('')
  const [evidenceKey, setEvidenceKey] = useState('')
  const [type, setType] = useState<RelationCreate['relation_type']>('relates_to')
  const [confirmed, setConfirmed] = useState(false)
  const command = useRef<{ body: string; id: string } | null>(null)
  const mutation = useMutation({
    mutationFn: createRelation,
    onSuccess: () => client.invalidateQueries({ queryKey: ['memory', 'relations', context.userId, context.workspaceId, context.projectId] }),
    onError: () => client.invalidateQueries({ queryKey: ['memory', 'relations', context.userId, context.workspaceId, context.projectId] }),
  })
  if (!source || !targets.length || !evidenceNodes.length) return null
  const selectClass = 'mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 p-2 text-sm text-slate-200'
  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const target = targets.find((node) => `${node.record_type}:${node.record_id}` === targetKey)
    const evidence = evidenceNodes.find((node) => `${node.record_type}:${node.record_id}` === evidenceKey)
    if (!target || !evidence) return
    const request = { project_id: context.projectId, source: relationReference(source),
      target: relationReference(target), evidence: relationReference(evidence), relation_type: type,
      assertion: confirmed ? 'confirmed' as const : 'candidate' as const }
    const body = JSON.stringify(request)
    if (command.current?.body !== body) command.current = { body, id: crypto.randomUUID() }
    mutation.mutate({ ...request, command_id: command.current.id })
  }
  return <form onSubmit={submit} className="space-y-3 border-t border-slate-700 pt-3">
    <p className="text-xs text-slate-400">为已展示的记录补充判断，保存时会重新核对权限与依据。</p>
    <label className="block text-xs text-slate-300">关联记录<select className={selectClass} value={targetKey} onChange={(e) => setTargetKey(e.target.value)} required>
      <option value="">选择关联记录</option>{targets.map((node) => <option key={`${node.record_type}:${node.record_id}`} value={`${node.record_type}:${node.record_id}`}>{node.title} · v{node.version}</option>)}
    </select></label>
    <label className="block text-xs text-slate-300">关系<select className={selectClass} value={type} onChange={(e) => setType(e.target.value as RelationCreate['relation_type'])}>
      {TYPES.map((value) => <option key={value} value={value}>{RELATIONS[value]}</option>)}
    </select></label>
    <label className="block text-xs text-slate-300">判断依据<select className={selectClass} value={evidenceKey} onChange={(e) => setEvidenceKey(e.target.value)} required>
      <option value="">选择当前任务或文档</option>{evidenceNodes.map((node) => <option key={`${node.record_type}:${node.record_id}`} value={`${node.record_type}:${node.record_id}`}>{node.title} · v{node.version}</option>)}
    </select></label>
    <label className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />我已核对依据，确认此关联</label>
    <Button size="sm" type="submit" disabled={mutation.isPending || !targetKey || !evidenceKey}>保存关联</Button>
    {mutation.error ? <p role="alert" className="text-xs text-remind">{relationError(mutation.error)}</p> : null}
    {mutation.isSuccess ? <p role="status" className="text-xs text-mint-300">关联已保存。</p> : null}
  </form>
}
