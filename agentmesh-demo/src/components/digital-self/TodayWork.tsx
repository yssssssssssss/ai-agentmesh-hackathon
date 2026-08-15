import { Activity } from 'lucide-react'

import type { ActivityTodayResponse } from '../../features/digital-self/api'
import { Badge } from '../ui/Badge'
import { SectionCard } from '../ui/Card'

interface TodayWorkProps {
  data?: ActivityTodayResponse
  loading: boolean
  error: boolean
}

export function TodayWork({ data, loading, error }: TodayWorkProps) {
  const items = data ? [...data.personal, ...data.external] : []
  return (
    <SectionCard title="今日活动" icon={<Activity className="h-4 w-4" />} desc="个人与外部 Agent 的服务端活动记录。">
      {loading ? <p className="text-sm text-slate-500">正在加载活动…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose">活动资源暂时不可用。</p> : null}
      {!loading && !error && items.length === 0 ? <p className="text-sm text-slate-500">今日尚无活动记录。</p> : null}
      {items.length > 0 ? (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.id} className="rounded-[10px] border border-white/[0.06] bg-surface-2 px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium text-slate-100">{item.title}</span>
                <Badge>{item.category}</Badge>
              </div>
              <p className="mt-1 text-xs leading-5 text-slate-500">{item.summary}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </SectionCard>
  )
}
