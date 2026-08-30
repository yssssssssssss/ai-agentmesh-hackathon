import { Activity, Brain, ClipboardList, ScrollText } from 'lucide-react'

import type {
  ActivityTodayResponse,
  AuditListResponse,
  BlackboardTaskCardsResponse,
  MemoryOverviewResponse,
} from '../../features/insights/api'
import { Badge } from '../ui/Badge'
import { SectionCard } from '../ui/Card'
import { DataSourceBadge } from '../ui/DataSourceBadge'

interface QueryState<T> {
  data?: T
  loading: boolean
  error?: string | null
}

function QueryFeedback({ loading, error, empty, emptyLabel }: {
  loading: boolean
  error?: string | null
  empty: boolean
  emptyLabel: string
}) {
  if (loading) return <p className="text-sm text-slate-400">正在读取服务端数据…</p>
  if (error) return <p role="alert" className="text-sm text-rose">{error}</p>
  if (empty) return <p className="text-sm text-slate-400">{emptyLabel}</p>
  return null
}

export function TaskCardsPanel({ data, loading, error }: QueryState<BlackboardTaskCardsResponse>) {
  return (
    <SectionCard
      title="当前任务卡片"
      icon={<ClipboardList className="h-4 w-4" />}
      desc="当前项目可见的服务端任务与允许操作。"
      action={data ? <DataSourceBadge source="T" /> : null}
    >
      <QueryFeedback loading={loading} error={error} empty={!data || data.items.length === 0} emptyLabel="当前没有任务卡片。" />
      {data && data.items.length > 0 ? (
        <ul className="space-y-3">
          {data.items.map((card) => {
            const allowedActions = card.allowed_actions ?? []
            return (
              <li key={card.task.id ?? card.task.thread_id} className="rounded-soft border border-white/[0.06] bg-surface-2 px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-100">{card.task.title}</span>
                  <Badge tone={card.task.status === 'completed' ? 'mint' : 'neutral'}>{card.task.status}</Badge>
                </div>
                <p className="mt-1 text-xs text-slate-400">{card.done_when ?? '服务端未提供完成标准'}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {allowedActions.length > 0 ? allowedActions.map((action) => (
                    <Badge key={action} tone="neutral">允许操作：{action}</Badge>
                  )) : <span className="text-[11px] text-slate-400">当前无可执行操作</span>}
                </div>
              </li>
            )
          })}
        </ul>
      ) : null}
    </SectionCard>
  )
}

export function ActivityPanel({ data, loading, error }: QueryState<ActivityTodayResponse>) {
  const items = data ? [...data.personal, ...data.external] : []
  return (
    <SectionCard
      title="活动记录"
      icon={<Activity className="h-4 w-4" />}
      desc="当前账号今日可见的服务端活动。"
      action={data ? <DataSourceBadge source="T" /> : null}
    >
      <QueryFeedback loading={loading} error={error} empty={items.length === 0} emptyLabel="当前没有活动记录。" />
      {items.length > 0 ? (
        <ul className="divide-y divide-white/[0.05]">
          {items.map((item, index) => (
            <li key={item.id ?? `${item.title}-${index}`} className="py-3 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-slate-200">{item.title}</span>
                <Badge tone="neutral">{item.scope}</Badge>
              </div>
              <p className="mt-1 text-xs leading-5 text-slate-400">{item.summary}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </SectionCard>
  )
}

const MEMORY_LABELS: Record<keyof MemoryOverviewResponse['counts'], string> = {
  short: '短期记忆',
  project: '项目记忆',
  archive: '归档记忆',
  team: '团队记忆',
}

export function MemoryPanel({ data, loading, error }: QueryState<MemoryOverviewResponse>) {
  const total = data ? Object.values(data.counts).reduce((sum, count) => sum + count, 0) : 0
  return (
    <SectionCard
      title="项目记忆"
      icon={<Brain className="h-4 w-4" />}
      desc="服务端分层记忆数量，仅作为当前项目事实。"
      action={data ? <DataSourceBadge source="T" /> : null}
    >
      <QueryFeedback loading={loading} error={error} empty={!data || total === 0} emptyLabel="本项目尚无记忆。" />
      {data && total > 0 ? (
        <dl className="grid grid-cols-2 gap-3">
          {Object.entries(data.counts).map(([layer, count]) => (
            <div key={layer} className="rounded-soft bg-surface-2 p-3">
              <dt className="text-xs text-slate-400">{MEMORY_LABELS[layer as keyof MemoryOverviewResponse['counts']]}</dt>
              <dd className="mt-1 text-right text-lg font-semibold tabular-nums text-slate-100">{count}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </SectionCard>
  )
}

export function AuditPanel({ data, loading, error }: QueryState<AuditListResponse>) {
  return (
    <SectionCard
      title="最近审计"
      icon={<ScrollText className="h-4 w-4" />}
      desc="只读审计事件，不将其命名为复盘证据。"
      action={data ? <DataSourceBadge source="T" /> : null}
    >
      <QueryFeedback loading={loading} error={error} empty={!data || data.items.length === 0} emptyLabel="当前没有审计事件。" />
      {data && data.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-slate-400">
              <tr><th className="pb-2 pr-4 font-medium">动作</th><th className="pb-2 pr-4 font-medium">对象</th><th className="pb-2 font-medium">操作者</th></tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {data.items.map((event, index) => (
                <tr key={event.id ?? `${event.action}-${event.target_id}-${index}`}>
                  <td className="py-3 pr-4 text-slate-200">{event.action}</td>
                  <td className="py-3 pr-4 text-slate-400">{event.target_type} · {event.target_id}</td>
                  <td className="py-3 text-slate-400">{event.actor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </SectionCard>
  )
}
