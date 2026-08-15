import { Brain } from 'lucide-react'

import type { MemoryOverviewResponse } from '../../features/digital-self/api'
import { SectionCard } from '../ui/Card'

interface RecentGrowthProps {
  data?: MemoryOverviewResponse
  loading: boolean
  error: boolean
}

const LABELS: Record<keyof MemoryOverviewResponse['counts'], string> = {
  short: '短期',
  project: '项目',
  archive: '归档',
  team: '团队',
}

export function RecentGrowth({ data, loading, error }: RecentGrowthProps) {
  const total = data ? Object.values(data.counts).reduce((sum, count) => sum + count, 0) : 0
  return (
    <SectionCard title="记忆概览" icon={<Brain className="h-4 w-4" />} desc="当前项目的分层记忆数量。">
      {loading ? <p className="text-sm text-slate-500">正在加载记忆…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose">记忆资源暂时不可用。</p> : null}
      {!loading && !error && total === 0 ? <p className="text-sm text-slate-500">尚无记忆记录。</p> : null}
      {data && total > 0 ? (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(data.counts).map(([key, count]) => (
            <div key={key} className="rounded-[10px] border border-white/[0.06] bg-surface-2 p-3 text-center">
              <dd className="text-xl font-semibold tabular-nums text-white">{count}</dd>
              <dt className="mt-1 text-xs text-slate-500">{LABELS[key as keyof typeof LABELS]}记忆</dt>
            </div>
          ))}
        </dl>
      ) : null}
    </SectionCard>
  )
}
