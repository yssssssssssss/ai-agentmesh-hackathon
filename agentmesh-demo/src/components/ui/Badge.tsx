import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

type Tone = 'mint' | 'knowledge' | 'collab' | 'remind' | 'neutral' | 'rose'

const TONES: Record<Tone, string> = {
  mint: 'bg-mint-400/12 text-mint-300 ring-1 ring-inset ring-mint-400/20',
  knowledge: 'bg-knowledge/12 text-knowledge ring-1 ring-inset ring-knowledge/25',
  collab: 'bg-collab/12 text-collab ring-1 ring-inset ring-collab/25',
  remind: 'bg-remind/12 text-remind ring-1 ring-inset ring-remind/25',
  rose: 'bg-rose/12 text-rose ring-1 ring-inset ring-rose/25',
  neutral: 'bg-white/[0.06] text-slate-300 ring-1 ring-inset ring-white/10',
}

interface BadgeProps {
  tone?: Tone
  icon?: ReactNode
  children: ReactNode
  className?: string
  dot?: boolean
}

export function Badge({ tone = 'neutral', icon, children, className, dot }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-xs font-medium leading-none',
        TONES[tone],
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {icon && <span className="shrink-0">{icon}</span>}
      {children}
    </span>
  )
}
