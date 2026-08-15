import { BrainCircuit, Palette, Sparkles } from 'lucide-react'

import { cn } from '../../lib/cn'
import type { WorkspaceToolId } from './types'

interface ToolLauncherBarProps {
  activeTool: WorkspaceToolId | null
  onOpen: (tool: WorkspaceToolId) => void
}

const TOOLS = [
  { id: 'aesthetic-quant' as const, label: '美学量化', icon: Palette, tone: 'mint' as const },
  { id: 'experience-model' as const, label: '体验模型', icon: BrainCircuit, tone: 'amber' as const },
]

export function ToolLauncherBar({ activeTool, onOpen }: ToolLauncherBarProps) {
  return (
    <section aria-label="Tool 演示入口" className="flex items-center gap-2 overflow-x-auto pb-0.5">
      <span className="hidden shrink-0 items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500 sm:inline-flex">
        <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
        Tool 演示
      </span>
      {TOOLS.map((tool) => {
        const Icon = tool.icon
        const selected = activeTool === tool.id
        return (
          <button
            key={tool.id}
            type="button"
            aria-label={`${tool.label} Mock`}
            aria-expanded={selected}
            onClick={() => onOpen(tool.id)}
            className={cn(
              'inline-flex h-8 shrink-0 items-center gap-2 rounded-full border px-3 text-xs font-semibold transition-colors active:translate-y-px',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50',
              tool.tone === 'mint'
                ? 'border-mint-400/20 bg-mint-400/[0.08] text-mint-300 hover:bg-mint-400/[0.14]'
                : 'border-amber-300/20 bg-amber-300/[0.08] text-amber-200 hover:bg-amber-300/[0.14]',
              selected && 'border-white/20 bg-white/[0.1] text-white',
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            {tool.label}
            <span className="rounded-full bg-white/[0.07] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-slate-400">
              Mock
            </span>
          </button>
        )
      })}
    </section>
  )
}
