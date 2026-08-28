import { Check, Circle, Loader2, X } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { cn } from '../../lib/cn'
import { DEEPSEARCH_STAGES } from './presentation'

interface DeepSearchStageRailProps {
  activeStage: number
  terminal: boolean
  reportPublished: boolean
}

export function DeepSearchStageRail({ activeStage, terminal, reportPublished }: DeepSearchStageRailProps) {
  const activeHeading = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    activeHeading.current?.focus({ preventScroll: true })
  }, [activeStage])

  const progress = activeStage === 0 ? 0 : (activeStage / (DEEPSEARCH_STAGES.length - 1)) * 100

  return (
    <section aria-label="DeepSearch 阶段" className="mt-6 overflow-hidden rounded-soft border border-mint-400/15 bg-surface-1 shadow-card">
      <div className="flex items-center justify-between gap-4 px-5 py-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mint-300">DeepSearch · v1</p>
          <p
            ref={activeHeading}
            tabIndex={-1}
            className="mt-1 text-sm font-semibold text-slate-100 outline-none"
          >
            当前阶段：{DEEPSEARCH_STAGES[activeStage]}
          </p>
        </div>
        <span className="text-[11px] text-slate-400">{activeStage + 1} / {DEEPSEARCH_STAGES.length}</span>
      </div>
      <div className="relative border-t border-white/[0.06] px-4 py-4 sm:px-5">
        <div className="absolute left-9 right-9 top-[27px] h-px bg-white/[0.08] sm:left-10 sm:right-10" aria-hidden="true">
          <span
            className="block h-full origin-left bg-mint-400 transition-[width] duration-500 motion-reduce:transition-none"
            style={{ width: `${progress}%` }}
          />
        </div>
        <ol className="relative grid grid-cols-3 gap-y-4 sm:grid-cols-6">
          {DEEPSEARCH_STAGES.map((label, index) => {
            const complete = index < activeStage || (reportPublished && index === activeStage)
            const active = index === activeStage && !terminal
            const stopped = index === activeStage && terminal && !reportPublished
            const Icon = complete ? Check : active ? Loader2 : stopped ? X : Circle
            return (
              <li key={label} className="flex min-w-0 flex-col items-center gap-2 text-center">
                <span className={cn(
                  'flex h-7 w-7 items-center justify-center rounded-full border bg-surface-1',
                  complete && 'border-mint-400/45 text-mint-300',
                  active && 'border-mint-400/45 text-mint-300',
                  stopped && 'border-rose/35 text-rose',
                  !complete && !active && !stopped && 'border-white/[0.09] text-slate-400',
                )}>
                  <Icon className={cn('h-3.5 w-3.5', active && 'animate-spin motion-reduce:animate-none')} aria-hidden="true" />
                </span>
                <span className={cn(
                  'max-w-[8rem] text-[11px] leading-4',
                  index <= activeStage ? 'text-slate-300' : 'text-slate-400',
                )}>
                  {label}
                </span>
              </li>
            )
          })}
        </ol>
      </div>
    </section>
  )
}
