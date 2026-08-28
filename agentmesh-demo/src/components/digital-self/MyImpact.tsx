import { ArrowRight, Share2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { DigitalSelfViewModel } from '../../features/digital-self/presenter'
import { ModuleSourceBadges, ValueSourceBadge } from './SourceBadges'

interface MyImpactProps {
  model: DigitalSelfViewModel['impact']
}

export function MyImpact({ model }: MyImpactProps) {
  const navigate = useNavigate()

  return (
    <section className="card-base grid min-h-[320px] min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[56px_1fr_40px] p-5" aria-labelledby="impact-heading">
      <header className="flex h-[56px] items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-soft bg-collab/10 text-collab">
            <Share2 className="h-[22px] w-[22px]" aria-hidden="true" />
          </span>
          <div className="min-w-0 pt-0.5 text-left">
            <h2 id="impact-heading" className="text-[15px] font-semibold text-slate-100">我的经验正在被复用</h2>
            <p className="mt-1 text-[12px] leading-snug text-slate-400">授权共享经验的参考影响摘要</p>
          </div>
        </div>
        <ModuleSourceBadges sources={model.sources} />
      </header>

      <div className="divide-y divide-white/[0.06]">
        {model.data.items.slice(0, 3).map((item) => (
          <div key={`${item.label.value}-${item.meta.value}`} className="flex min-h-[60px] flex-col justify-center py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate text-[13px] font-medium text-slate-300">{item.label.value}</span>
              <span className="flex shrink-0 items-center gap-1.5">
                {item.meta.value ? <span className="text-[10.5px] text-slate-400">{item.meta.value}</span> : null}
                <ValueSourceBadge value={item.label} />
              </span>
            </div>
            <p className="mt-1 truncate text-[12px] text-slate-400" title={item.value.value}>{item.value.value}</p>
          </div>
        ))}
      </div>

      <footer className="flex h-10 items-end justify-end">
        <button
          type="button"
          onClick={() => navigate('/digital-human?section=activity')}
          className="inline-flex min-h-10 items-center gap-1 text-[12px] font-medium text-slate-400 transition-[color,transform] duration-150 hover:text-mint-300 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
        >
          查看全部动态
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </footer>
    </section>
  )
}
