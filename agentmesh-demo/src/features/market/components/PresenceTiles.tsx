import type { ReactNode } from 'react'
import { Brain, RadioTower, Send, Sparkles } from 'lucide-react'
import type { MarketMePresence, MarketMeWorkerState } from '../types'

interface PresenceTilesProps {
  presence: MarketMePresence
  enabled: boolean
  workers?: { [key: string]: MarketMeWorkerState }
}

type Tone = 'me' | 'request' | 'incoming' | 'outgoing'

const TONE_TEXT: Record<Tone, string> = {
  me: 'text-mint-300',
  request: 'text-collab',
  incoming: 'text-remind',
  outgoing: 'text-knowledge',
}
const TONE_BG: Record<Tone, string> = {
  me: 'bg-mint-400/10',
  request: 'bg-collab/10',
  incoming: 'bg-remind/10',
  outgoing: 'bg-knowledge/10',
}
const TONE_STRIPE: Record<Tone, string> = {
  me: 'from-mint-400/60',
  request: 'from-collab/60',
  incoming: 'from-remind/60',
  outgoing: 'from-knowledge/60',
}

function formatRefreshed(iso: string | null | undefined): string {
  if (!iso) return '尚未发布'
  try {
    const date = new Date(iso)
    const now = Date.now()
    const diff = Math.max(0, now - date.getTime())
    if (diff < 60_000) return '刚刚'
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
    return date.toLocaleDateString('zh-CN')
  } catch {
    return '—'
  }
}

interface TileProps {
  tone: Tone
  label: string
  value: ReactNode
  hint?: string
  icon: ReactNode
}

function Tile({ tone, label, value, hint, icon }: TileProps) {
  return (
    <div className="group relative overflow-hidden rounded-soft border border-white/[0.06] bg-surface-2 p-4 transition-colors hover:border-white/[0.14]">
      <span
        aria-hidden
        className={`absolute inset-y-0 left-0 w-[3px] bg-gradient-to-b ${TONE_STRIPE[tone]} to-transparent opacity-80`}
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">{label}</span>
        <span className={`flex h-7 w-7 items-center justify-center rounded-lg ${TONE_BG[tone]} ${TONE_TEXT[tone]}`}>
          {icon}
        </span>
      </div>
      <div className="mt-2 text-2xl font-semibold leading-none text-white tabular-nums">{value}</div>
      {hint ? <p className="mt-2 text-xs text-slate-400">{hint}</p> : null}
    </div>
  )
}

export function PresenceTiles({ presence, enabled, workers }: PresenceTilesProps) {
  void workers

  return (
    <div className="space-y-3">
      {!enabled ? (
        <div
          role="status"
          className="flex items-center gap-2 rounded-soft border border-remind/25 bg-remind/10 px-3 py-2 text-xs text-remind"
        >
          <RadioTower className="h-4 w-4" />
          自主协作市场未启用（设置 AGENTMESH_MARKET_ENABLED=1 以启动 agent-1 / agent-2）。
        </div>
      ) : null}
      <section aria-label="我的市场状态" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile
          tone="me"
          label="我的记忆"
          value={presence.memory_count}
          hint="分身用来生成信号的私有素材"
          icon={<Brain className="h-4 w-4" />}
        />
        <Tile
          tone="request"
          label="我发出的信号"
          value={presence.signal_on ? '在线' : '未发布'}
          hint={presence.signal_on ? formatRefreshed(presence.signal_refreshed_at) + '刷新' : '未参与市场或无素材'}
          icon={<Sparkles className="h-4 w-4" />}
        />
        <Tile
          tone="incoming"
          label="收到的回应"
          value={presence.received_count}
          hint="他人分身为我代答的次数"
          icon={<RadioTower className="h-4 w-4" />}
        />
        <Tile
          tone="outgoing"
          label="我提供的帮助"
          value={presence.given_count}
          hint="我的分身帮别人解答的次数"
          icon={<Send className="h-4 w-4" />}
        />
      </section>
    </div>
  )
}
