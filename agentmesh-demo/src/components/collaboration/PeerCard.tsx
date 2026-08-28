import { RadioTower, Sparkles, UserPlus } from 'lucide-react'

import type { DataSourceKind } from '../../lib/presentation'
import type { CollaborationMarketMatch } from '../../features/collaboration/presenter'
import type { MarketSignal } from '../../features/collaboration/api'
import { Avatar } from '../ui/Avatar'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'

interface PeerCardProps {
  signal: MarketSignal
  source: DataSourceKind
  match?: CollaborationMarketMatch
}

export function PeerCard({ signal, source, match }: PeerCardProps) {
  return (
    <article className="card-base flex min-h-[280px] flex-col p-5">
      <div className="flex items-start gap-3">
        <Avatar name={signal.owner_name} tone="collab" size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-100">{signal.owner_name}</h3>
            <Badge tone={signal.participating ? 'mint' : 'neutral'}>{signal.participating ? '已参与' : '未参与'}</Badge>
            <DataSourceBadge source={source} />
          </div>
          <p className="mt-1 text-xs text-slate-400">擅长 · {signal.capability || '服务端未声明能力'}</p>
        </div>
        <RadioTower className="h-4 w-4 shrink-0 text-collab" />
      </div>

      {match ? (
        <div className="mt-4 flex items-start gap-2 rounded-soft bg-surface-2 px-3.5 py-2.5">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-mint-300" />
          <div className="text-xs leading-relaxed text-slate-300">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-slate-400">匹配原因</span>
              <DataSourceBadge source={match.reason.source} />
            </div>
            <p className="mt-1">{match.reason.value}</p>
          </div>
        </div>
      ) : null}

      <dl className="mt-4 space-y-3 text-sm">
        <div>
          <dt className="text-xs text-slate-400">可提供</dt>
          <dd className="mt-1 leading-relaxed text-slate-300">{signal.offer || '服务端暂无供给描述'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-400">正在寻找</dt>
          <dd className="mt-1 leading-relaxed text-slate-300">{signal.need || '服务端暂无需求描述'}</dd>
        </div>
      </dl>

      <div className="mt-auto pt-4">
        <Button block variant="secondary" disabled icon={<UserPlus className="h-4 w-4" />} title="当前后端没有邀请协作命令">
          邀请协作暂不可用
        </Button>
        <details className="mt-3 rounded-soft border border-white/[0.06] bg-surface-2/70 px-3 py-2 text-xs">
          <summary className="min-h-8 cursor-pointer py-1.5 text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">技术详情</summary>
          <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all border-t border-white/[0.06] pt-3 font-mono text-[11px] leading-5 text-slate-400">{JSON.stringify({ signal, match }, null, 2)}</pre>
        </details>
      </div>
    </article>
  )
}
