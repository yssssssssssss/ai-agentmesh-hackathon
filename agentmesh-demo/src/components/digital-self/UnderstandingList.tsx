import { ArrowRight, Sparkles } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { DigitalSelfViewModel } from '../../features/digital-self/presenter'
import { ModuleSourceBadges, ValueSourceBadge } from './SourceBadges'

interface UnderstandingListProps {
  model: DigitalSelfViewModel['understanding']
}

export function UnderstandingList({ model }: UnderstandingListProps) {
  const navigate = useNavigate()
  const items = model.data.items.slice(0, 3)

  return (
    <section id="understanding" className="card-base grid min-h-[320px] min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[56px_1fr_40px] p-5" aria-labelledby="understanding-heading">
      <header className="flex h-[56px] items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-soft bg-mint-400/10 text-mint-300">
            <Sparkles className="h-[22px] w-[22px]" aria-hidden="true" />
          </span>
          <div className="min-w-0 pt-0.5 text-left">
            <h2 id="understanding-heading" className="text-[15px] font-semibold text-slate-100">对你的工作理解</h2>
            <p className="mt-1 text-[12px] leading-snug text-slate-400">基于近期工作形成的理解摘要</p>
          </div>
        </div>
        <ModuleSourceBadges sources={model.sources} />
      </header>

      <div className="divide-y divide-white/[0.06]">
        {model.loading ? <p role="status" className="py-5 text-sm text-slate-400">正在读取工作理解…</p> : null}
        {model.error ? <p role="alert" className="py-5 text-sm text-rose">{model.error}</p> : null}
        {!model.loading && !model.error && items.length === 0 ? <p className="py-5 text-sm text-slate-400">尚未形成可展示的工作理解。</p> : null}
        {items.map((item, index) => (
          <div key={item.id.value ?? `${item.text.value}-${index}`} className="flex min-h-[60px] flex-col justify-center py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate text-[13px] font-medium text-slate-300">{item.text.value}</span>
              <ValueSourceBadge value={item.text} />
            </div>
            <p className="mt-1 truncate text-[12px] text-slate-400" title={item.basis.value}>{item.basis.value}</p>
          </div>
        ))}
      </div>

      <footer className="flex h-10 items-end justify-end">
        <button
          type="button"
          onClick={() => navigate('/digital-human?section=understanding')}
          className="inline-flex min-h-10 items-center gap-1 text-[12px] font-medium text-slate-400 transition-[color,transform] duration-150 hover:text-mint-300 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
        >
          查看全部理解
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </footer>
    </section>
  )
}
