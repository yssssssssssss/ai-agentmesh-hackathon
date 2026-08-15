import { useState, type FormEvent } from 'react'
import { ScrollText, Search, X } from 'lucide-react'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { useAuditAdmin } from './api'

interface AuditModuleProps {
  context: { userId: string; workspaceId: string }
}

function message(error: unknown) {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : '请求失败'
}

export function AuditModule({ context }: AuditModuleProps) {
  const [action, setAction] = useState('')
  const [targetType, setTargetType] = useState('')
  const [filters, setFilters] = useState<{ action?: string; targetType?: string }>({})
  const query = useAuditAdmin(context, filters, true)

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFilters({ action: action.trim() || undefined, targetType: targetType.trim() || undefined })
  }

  const clearFilters = () => {
    setAction('')
    setTargetType('')
    setFilters({})
  }

  return (
    <Card padding="lg">
      <div className="flex items-center gap-3"><ScrollText className="h-5 w-5 text-mint-300" /><div><h2 className="text-lg font-semibold text-white">审计日志</h2><p className="mt-1 text-sm text-slate-500">服务端返回的最近审计事件。</p></div></div>
      <form onSubmit={applyFilters} className="mt-5 flex flex-wrap items-end gap-3">
        <label className="min-w-48 flex-1 text-sm text-slate-300">
          动作
          <input aria-label="审计动作" value={action} onChange={(event) => setAction(event.target.value)} placeholder="例如 create_user" className="mt-2 h-10 w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 text-white outline-none focus:border-mint-400/50" />
        </label>
        <label className="min-w-48 flex-1 text-sm text-slate-300">
          对象类型
          <input aria-label="审计对象类型" value={targetType} onChange={(event) => setTargetType(event.target.value)} placeholder="例如 user" className="mt-2 h-10 w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 text-white outline-none focus:border-mint-400/50" />
        </label>
        <Button type="submit" variant="secondary" icon={<Search className="h-4 w-4" />}>筛选</Button>
        <Button type="button" variant="ghost" icon={<X className="h-4 w-4" />} disabled={!action && !targetType && !filters.action && !filters.targetType} onClick={clearFilters}>清除</Button>
      </form>
      {query.isLoading ? <p className="mt-5 text-sm text-slate-500">正在加载审计…</p> : null}
      {query.isError ? <p role="alert" className="mt-5 text-sm text-rose">{message(query.error)}</p> : null}
      {query.data && query.data.items.length === 0 ? <p className="mt-5 text-sm text-slate-500">当前没有审计事件。</p> : null}
      {query.data && query.data.items.length > 0 ? (
        <div className="mt-5 overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-slate-500"><tr><th className="pb-3 font-medium">动作</th><th className="pb-3 font-medium">对象</th><th className="pb-3 font-medium">操作者</th><th className="pb-3 font-medium">时间</th></tr></thead><tbody className="divide-y divide-white/[0.06]">{query.data.items.map((event) => <tr key={event.id}><td className="py-3 pr-4 font-medium text-slate-100">{event.action}</td><td className="py-3 pr-4 text-slate-400">{event.target_type} · {event.target_id}</td><td className="py-3 pr-4 text-slate-400">{event.actor}</td><td className="py-3 text-slate-500">{event.created_at ? new Date(event.created_at).toLocaleString() : '—'}</td></tr>)}</tbody></table></div>
      ) : null}
    </Card>
  )
}
