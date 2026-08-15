import { RadioTower } from 'lucide-react'

import type { MarketSignal } from '../../features/collaboration/api'
import { Avatar } from '../ui/Avatar'
import { Badge } from '../ui/Badge'

export function PeerCard({ signal }: { signal: MarketSignal }) {
  return (
    <article className="card-base p-4">
      <div className="flex items-start gap-3">
        <Avatar name={signal.owner_name} tone="collab" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-100">{signal.owner_name}</h3>
            <Badge tone={signal.participating ? 'mint' : 'neutral'}>{signal.participating ? '已参与' : '未参与'}</Badge>
          </div>
          <p className="mt-1 text-xs text-slate-500">{signal.capability || '未声明能力'}</p>
        </div>
        <RadioTower className="h-4 w-4 text-collab" />
      </div>
      <dl className="mt-4 space-y-2 text-sm">
        <div><dt className="text-xs text-slate-500">可提供</dt><dd className="mt-0.5 text-slate-300">{signal.offer || '暂无'}</dd></div>
        <div><dt className="text-xs text-slate-500">需要</dt><dd className="mt-0.5 text-slate-300">{signal.need || '暂无'}</dd></div>
      </dl>
    </article>
  )
}
