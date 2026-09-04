import { BookOpenCheck, ExternalLink, Quote } from 'lucide-react'

import type { MemoryUseView } from '../../features/workspace/types'
import { Badge } from '../ui/Badge'

export function MemoryUsePanel({ items }: { items: MemoryUseView[] }) {
  if (items.length === 0) return null
  return (
    <section
      aria-labelledby="run-memory-context-heading"
      className="mt-6 rounded-soft border border-white/[0.06] bg-surface-1 px-5 py-4 shadow-card"
    >
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-soft bg-mint-400/10 text-mint-300">
          <BookOpenCheck className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 id="run-memory-context-heading" className="text-sm font-semibold text-slate-100">本次使用的记忆</h2>
          <p className="mt-1 text-xs leading-5 text-slate-400">仅展示实际进入本次 Run 上下文并写入不可变回执的版本。</p>
        </div>
      </div>
      <ol className="mt-4 divide-y divide-white/[0.06]">
        {items.map((item) => (
          <li key={item.receipt.id} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs font-semibold text-mint-300">[{item.receipt.citation_label}]</span>
                <span className="text-sm font-medium text-slate-100">{item.title ?? item.receipt.memory_id}</span>
                <Badge tone={item.cited_in_output ? 'mint' : 'neutral'}>
                  {item.cited_in_output ? '输出已引用' : '已进入上下文'}
                </Badge>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                v{item.receipt.memory_version} · {SCOPE_LABELS[item.scope ?? ''] ?? item.scope ?? '当前不可见'} · {LAYER_LABELS[item.layer ?? ''] ?? item.layer ?? '未标注层级'}
              </p>
              {item.sources.length > 0 ? (
                <p className="mt-1 flex items-center gap-1 text-[11px] text-slate-400">
                  <Quote className="h-3 w-3" aria-hidden="true" />
                  原始来源：{item.sources.map((source) => source.title).join('、')}
                </p>
              ) : null}
            </div>
            {item.memory_navigation_href ? (
              <a
                href={item.memory_navigation_href}
                className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-control px-3 text-xs text-mint-300 transition-colors active:scale-[0.98] hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
              >
                查看记忆 <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              </a>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  )
}

const SCOPE_LABELS: Record<string, string> = {
  private: '个人范围',
  project: '项目范围',
  team_accepted: '团队范围',
}

const LAYER_LABELS: Record<string, string> = {
  short_term: '短期',
  mid_term: '中期',
  long_term: '长期',
}
