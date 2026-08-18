import { CheckCircle2, Radio, ShieldAlert, ShieldCheck, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'
import type { MarketActivityItem } from '../types'

interface ActivityFeedProps {
  items: MarketActivityItem[]
  live?: boolean
}

type Accent = {
  dot: string
  icon: string
  ring: string
  label: string
}

function accentFor(item: MarketActivityItem): Accent {
  if (item.kind === 'signal') {
    return { dot: 'bg-collab', icon: 'text-collab', ring: 'ring-collab/25', label: '发出信号' }
  }
  switch (item.status) {
    case 'answered':
      return { dot: 'bg-mint-400', icon: 'text-mint-300', ring: 'ring-mint-400/25', label: '完成代答' }
    case 'awaiting_confirm':
      return { dot: 'bg-remind', icon: 'text-remind', ring: 'ring-remind/25', label: '等待确认' }
    case 'denied':
      return { dot: 'bg-rose', icon: 'text-rose', ring: 'ring-rose/25', label: '已婉拒' }
    default:
      return { dot: 'bg-slate-400', icon: 'text-slate-300', ring: 'ring-white/[0.14]', label: '进行中' }
  }
}

function iconFor(item: MarketActivityItem): ReactNode {
  if (item.kind === 'signal') return <Sparkles className="h-3.5 w-3.5" />
  if (item.status === 'answered') return <CheckCircle2 className="h-3.5 w-3.5" />
  if (item.status === 'awaiting_confirm') return <ShieldCheck className="h-3.5 w-3.5" />
  if (item.status === 'denied') return <ShieldAlert className="h-3.5 w-3.5" />
  return <Radio className="h-3.5 w-3.5" />
}

function relativeTime(iso: string): string {
  try {
    const diff = Math.max(0, Date.now() - new Date(iso).getTime())
    if (diff < 60_000) return '刚刚'
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
    return `${Math.floor(diff / 86_400_000)} 天前`
  } catch {
    return ''
  }
}

export function ActivityFeed({ items, live = true }: ActivityFeedProps) {
  return (
    <section
      aria-label="市场实时动态"
      className="flex h-[clamp(440px,66vh,720px)] flex-col rounded-[14px] border border-white/[0.06] bg-surface-1"
    >
      <header className="flex shrink-0 items-center justify-between border-b border-white/[0.06] px-5 py-3.5">
        <div className="flex flex-col">
          <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            LIVE ACTIVITY
          </span>
          <h2 className="text-base text-white">市场实时动态</h2>
        </div>
        {live ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-mint-400/[0.08] px-2.5 py-1 text-[11px] text-mint-300 ring-1 ring-mint-400/25">
            <span aria-hidden className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-mint-400/70" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-mint-400" />
            </span>
            实时
          </span>
        ) : null}
      </header>

      {items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center px-5 text-center text-sm text-slate-500">市场还没有动态，等分身们开始协作。</div>
      ) : (
        <ol className="relative flex-1 overflow-y-auto overscroll-contain px-5 py-4">
          <span
            aria-hidden
            className="absolute left-[26px] top-6 bottom-6 w-px bg-white/[0.06]"
          />
          {items.map((item) => {
            const accent = accentFor(item)
            return (
              <li key={item.id} className="relative flex gap-4 py-2.5">
                <span
                  className={`relative z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-2 ring-1 ${accent.ring} ${accent.icon}`}
                >
                  {iconFor(item)}
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className={`inline-flex items-center gap-1 text-[11px] ${accent.icon}`}>
                      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${accent.dot}`} />
                      {accent.label}
                    </span>
                    {item.involves_me ? (
                      <span className="rounded-full bg-mint-400/[0.08] px-1.5 py-0.5 text-[10px] text-mint-300 ring-1 ring-mint-400/25">
                        与我相关
                      </span>
                    ) : null}
                    <span className="ml-auto text-[11px] tabular-nums text-slate-500">
                      {relativeTime(item.at)}
                    </span>
                  </div>
                  <p className="text-[13.5px] leading-relaxed text-slate-200">{item.text}</p>
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
