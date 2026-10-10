import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { terminologyApi, terminologyError, type ProjectTerminology } from '../../features/knowledge/terminologyApi'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'

export function ProjectTerminologyPanel({ userId, projectId, canManage }: {
  userId: string; projectId: string; canManage: boolean
}) {
  const client = useQueryClient()
  const key = ['project-terminology', userId, projectId]
  const query = useQuery({ queryKey: key, queryFn: () => terminologyApi.get(projectId) })
  const [editing, setEditing] = useState(false)
  return <details className="card-base p-4">
    <summary className="cursor-pointer text-sm font-semibold text-slate-100">项目术语库</summary>
    <div className="mt-4 space-y-3" role="region" aria-label="项目术语库">
      <p className="text-xs text-slate-400">确认本项目中名称相同的术语。查询会保留原始证据，并提示合并后出现的事实冲突。</p>
      {query.error ? <p role="alert" className="text-sm text-rose">{terminologyError(query.error)}</p>
        : query.isLoading ? <p className="text-sm text-slate-400">正在读取项目术语…</p>
          : query.data ? <>
            <p className="text-xs text-slate-400">版本 {query.data.version} <DataSourceBadge source="T" />
              {query.data.confirmed_by ? ` · 确认人 ${query.data.confirmed_by}` : ''}</p>
            {editing && canManage ? <TerminologyEditor initial={query.data} projectId={projectId}
              onCancel={() => setEditing(false)} onReload={() => { setEditing(false); void query.refetch() }}
              onSaved={(value) => { client.setQueryData(key, value); setEditing(false) }} />
              : <>
                <TermAliasList aliases={query.data.aliases} />
                {canManage ? <Button size="sm" onClick={() => setEditing(true)}>编辑项目术语</Button>
                  : <p className="text-xs text-slate-400">由有团队记忆管理权限的成员确认修改。</p>}
              </>}
          </> : null}
      <Button variant="subtle" size="sm" disabled={editing || query.isFetching} onClick={() => void query.refetch()}>刷新术语库</Button>
    </div>
  </details>
}

export function TermAliasList({ aliases }: { aliases: Record<string, string> }) {
  const entries = Object.entries(aliases)
  if (!entries.length) return <p className="text-sm text-slate-400">尚未确认术语别名。</p>
  return <ul className="space-y-2 text-sm text-slate-300" aria-label="已确认术语别名">
    {entries.map(([alias, canonical]) => <li className="break-words" key={alias}>{alias} → {canonical}</li>)}
  </ul>
}

function TerminologyEditor({ initial, projectId, onSaved, onCancel, onReload }: {
  initial: ProjectTerminology; projectId: string; onSaved: (value: ProjectTerminology) => void
  onCancel: () => void; onReload: () => void
}) {
  // The edit version stays fixed while a background refresh updates the read view.
  const [base] = useState(initial)
  const [aliases, setAliases] = useState(initial.aliases)
  const [alias, setAlias] = useState('')
  const [canonical, setCanonical] = useState('')
  const command = useRef<string | null>(null)
  const save = useMutation({ mutationFn: () => {
    command.current ??= crypto.randomUUID()
    return terminologyApi.update(projectId, { command_id: command.current, expected_version: base.version, aliases })
  }, onSuccess: onSaved })
  const conflict = save.error instanceof ApiError && save.error.status === 409
  const blocked = save.isPending || conflict
  const change = (next: Record<string, string>) => {
    command.current = null
    save.reset()
    setAliases(next)
  }
  return <div className="space-y-3" aria-label="编辑项目术语">
    <p className="text-xs text-slate-400">请核对全部映射后确认保存。每个别名只能指向一个规范名称，最多 200 项。</p>
    <ul className="space-y-2 text-sm text-slate-300">
      {Object.entries(aliases).map(([name, target]) => <li key={name} className="flex items-center justify-between gap-3">
        <span className="break-words">{name} → {target}</span>
        <Button size="sm" variant="ghost" disabled={blocked} aria-label={`移除别名 ${name}`} onClick={() => {
          const next = { ...aliases }; delete next[name]; change(next)
        }}>移除</Button>
      </li>)}
    </ul>
    <div className="flex flex-wrap items-end gap-3">
      <label className="text-xs text-slate-300">别名
        <input className="mt-1 block rounded-control border border-white/10 bg-surface-1 p-2 text-sm"
          maxLength={100} value={alias} disabled={blocked} onChange={(event) => setAlias(event.target.value)} />
      </label>
      <label className="text-xs text-slate-300">规范名称
        <input className="mt-1 block rounded-control border border-white/10 bg-surface-1 p-2 text-sm"
          maxLength={100} value={canonical} disabled={blocked} onChange={(event) => setCanonical(event.target.value)} />
      </label>
      <Button size="sm" variant="subtle" disabled={blocked || !alias.trim() || !canonical.trim() || Object.keys(aliases).length >= 200}
        onClick={() => { change({ ...aliases, [alias.trim()]: canonical.trim() }); setAlias(''); setCanonical('') }}>加入映射</Button>
    </div>
    {save.error ? <p role="alert" className="text-sm text-rose">{terminologyError(save.error)}</p> : null}
    <div className="flex flex-wrap gap-2">
      <Button size="sm" loading={save.isPending} disabled={conflict || Boolean(alias.trim() || canonical.trim())}
        onClick={() => save.mutate()}>确认保存术语</Button>
      {conflict ? <Button size="sm" variant="subtle" onClick={onReload}>重新加载术语</Button> : null}
      <Button size="sm" variant="ghost" disabled={save.isPending} onClick={onCancel}>取消</Button>
    </div>
  </div>
}
