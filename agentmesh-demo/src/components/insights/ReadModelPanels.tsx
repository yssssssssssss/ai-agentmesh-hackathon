import { Activity, Brain, ClipboardList, ScrollText } from 'lucide-react'

import type {
  ActivityTodayResponse,
  AuditListResponse,
  BlackboardTaskCardsResponse,
  MemoryOverviewResponse,
} from '../../features/insights/api'
import { Badge } from '../ui/Badge'
import { SectionCard } from '../ui/Card'

interface QueryState<T> {
  data?: T
  loading: boolean
  error: boolean
}

export function TaskCardsPanel({ data, loading, error }: QueryState<BlackboardTaskCardsResponse>) {
  return (
    <SectionCard title="当前任务卡片" icon={<ClipboardList className="h-4 w-4" />} desc="当前项目可见的服务端任务。">
      {loading ? <p className="text-sm text-slate-500">正在加载任务…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose">任务资源暂时不可用。</p> : null}
      {!loading && !error && (!data || data.items.length === 0) ? <p className="text-sm text-slate-500">当前没有任务卡片。</p> : null}
      {data && data.items.length > 0 ? (
        <ul className="space-y-3">
          {data.items.map((card) => (
            <li key={card.task.id} className="rounded-[10px] border border-white/[0.06] bg-surface-2 px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-slate-100">{card.task.title}</span>
                <Badge tone={card.task.status === 'completed' ? 'mint' : 'neutral'}>{card.task.status}</Badge>
              </div>
              <p className="mt-1 text-xs text-slate-500">{card.done_when ?? '未提供完成标准'}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </SectionCard>
  )
}

export function ActivityPanel({ data, loading, error }: QueryState<ActivityTodayResponse>) {
  const items = data ? [...data.personal, ...data.external] : []
  return (
    <SectionCard title="活动记录" icon={<Activity className="h-4 w-4" />} desc="当前账号今日可见活动。">
      {loading ? <p className="text-sm text-slate-500">正在加载活动…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose">活动资源暂时不可用。</p> : null}
      {!loading && !error && items.length === 0 ? <p className="text-sm text-slate-500">当前没有活动记录。</p> : null}
      {items.length > 0 ? (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.id} className="border-l-2 border-mint-400/30 pl-3">
              <div className="text-sm font-medium text-slate-200">{item.title}</div>
              <div className="mt-1 text-xs leading-5 text-slate-500">{item.summary}</div>
            </li>
          ))}
        </ul>
      ) : null}
    </SectionCard>
  )
}

export function MemoryPanel({ data, loading, error }: QueryState<MemoryOverviewResponse>) {
  const total = data ? Object.values(data.counts).reduce((sum, count) => sum + count, 0) : 0
  return (
    <SectionCard title="项目记忆" icon={<Brain className="h-4 w-4" />} desc="服务端分层记忆概览。">
      {loading ? <p className="text-sm text-slate-500">正在加载记忆…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose">记忆资源暂时不可用。</p> : null}
      {!loading && !error && total === 0 ? <p className="text-sm text-slate-500">本项目尚无记忆。</p> : null}
      {data && total > 0 ? (
        <dl className="grid grid-cols-2 gap-3">
          {Object.entries(data.counts).map(([layer, count]) => (
            <div key={layer} className="rounded-[10px] bg-surface-2 p-3">
              <dt className="text-xs text-slate-500">{layer}</dt>
              <dd className="mt-1 text-lg font-semibold text-white tabular-nums">{count}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </SectionCard>
  )
}

export function AuditPanel({ data, loading, error }: QueryState<AuditListResponse>) {
  return (
    <SectionCard title="最近审计" icon={<ScrollText className="h-4 w-4" />} desc="只读审计事件，不生成本地结论。">
      {loading ? <p className="text-sm text-slate-500">正在加载审计…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose">审计资源暂时不可用。</p> : null}
      {!loading && !error && (!data || data.items.length === 0) ? <p className="text-sm text-slate-500">当前没有审计事件。</p> : null}
      {data && data.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-slate-500"><tr><th className="pb-2 font-medium">动作</th><th className="pb-2 font-medium">对象</th><th className="pb-2 font-medium">操作者</th></tr></thead>
            <tbody className="divide-y divide-white/[0.05]">
              {data.items.map((event) => (
                <tr key={event.id}>
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
