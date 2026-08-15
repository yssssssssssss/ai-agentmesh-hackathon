import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

type Tone = 'mint' | 'knowledge' | 'collab' | 'remind'

const TONE_TEXT: Record<Tone, string> = {
  mint: 'text-mint-300',
  knowledge: 'text-knowledge',
  collab: 'text-collab',
  remind: 'text-remind',
}
const TONE_BG: Record<Tone, string> = {
  mint: 'bg-mint-400/10',
  knowledge: 'bg-knowledge/10',
  collab: 'bg-collab/10',
  remind: 'bg-remind/10',
}

interface StatTileProps {
  label: string
  value: ReactNode
  icon?: ReactNode
  tone?: Tone
  hint?: string
  className?: string
}

/** 关键指标数字卡 */
export function StatTile({ label, value, icon, tone = 'mint', hint, className }: StatTileProps) {
  return (
    <div
      className={cn(
        'rounded-[12px] border border-white/[0.06] bg-surface-2 p-4 transition-colors hover:border-white/[0.1]',
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">{label}</span>
        {icon && (
          <span className={cn('flex h-7 w-7 items-center justify-center rounded-lg', TONE_BG[tone], TONE_TEXT[tone])}>
            {icon}
          </span>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-[26px] font-semibold leading-none text-white tabular-nums">{value}</span>
      </div>
      {hint && <p className="mt-1.5 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}
