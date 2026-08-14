import { Sparkles, UserPlus } from 'lucide-react'
import { Avatar } from '../ui/Avatar'
import { Button } from '../ui/Button'
import type { RecommendedPeer } from '../../data/mockData'

interface PeerCardProps {
  peer: RecommendedPeer
  onCollab: () => void
}

export function PeerCard({ peer, onCollab }: PeerCardProps) {
  return (
    <div className="card-base flex flex-col p-5">
      <div className="flex items-center gap-3">
        <Avatar name={peer.name} tone={peer.tone} size="lg" />
        <div>
          <h3 className="text-base font-semibold text-white">{peer.name}</h3>
          <p className="text-xs text-slate-500">擅长 · {peer.domain}</p>
        </div>
      </div>

      {/* 推荐理由 */}
      <div className="mt-4 flex items-start gap-2 rounded-[10px] bg-surface-2 px-3.5 py-2.5">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-mint-300" />
        <p className="text-xs leading-relaxed text-slate-300">
          <span className="text-slate-500">推荐理由：</span>
          {peer.reason}
        </p>
      </div>

      {/* 可提供 */}
      <div className="mt-3">
        <p className="mb-1.5 text-xs text-slate-500">可提供</p>
        <div className="flex flex-wrap gap-1.5">
          {peer.offers.map((o) => (
            <span
              key={o}
              className="rounded-pill border border-white/[0.06] bg-surface-2 px-2.5 py-1 text-xs text-slate-300"
            >
              {o}
            </span>
          ))}
        </div>
      </div>

      <div className="flex-1" />

      <Button variant="secondary" block className="mt-4" icon={<UserPlus className="h-4 w-4" />} onClick={onCollab}>
        邀请协作
      </Button>
    </div>
  )
}
