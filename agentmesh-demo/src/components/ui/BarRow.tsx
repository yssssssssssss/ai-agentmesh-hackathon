import { cn } from '../../lib/cn'

type Tone = 'mint' | 'knowledge' | 'collab' | 'remind'

const BAR: Record<Tone, string> = {
  mint: 'bg-mint-400',
  knowledge: 'bg-knowledge',
  collab: 'bg-collab',
  remind: 'bg-remind',
}

interface BarRowProps {
  label: string
  value: number // 0-100
  tone?: Tone
  valueLabel?: string
}

/** 轻量横向条形，用于工作主题分布 */
export function BarRow({ label, value, tone = 'mint', valueLabel }: BarRowProps) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-sm">
        <span className="text-slate-300">{label}</span>
        <span className="font-medium tabular-nums text-slate-400">{valueLabel ?? `${value}%`}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/[0.05]">
        <div
          className={cn('h-full origin-left rounded-full animate-grow-x', BAR[tone])}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  )
}
