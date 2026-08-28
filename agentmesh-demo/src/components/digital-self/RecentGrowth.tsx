import { ArrowRight, BookMarked, TrendingUp, Users, Wrench } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { DigitalSelfViewModel } from '../../features/digital-self/presenter'
import { ModuleSourceBadges, ValueSourceBadge } from './SourceBadges'

interface RecentGrowthProps {
  model: DigitalSelfViewModel['growth']
}

const CATEGORY_ICONS = [BookMarked, Wrench, Users]

export function RecentGrowth({ model }: RecentGrowthProps) {
  const navigate = useNavigate()
  const counts = model.data.memoryCounts

  return (
    <section className="card-base grid min-h-[320px] min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[56px_1fr_40px] p-5" aria-labelledby="growth-heading">
      <header className="flex h-[56px] items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-soft bg-knowledge/10 text-knowledge">
            <TrendingUp className="h-[22px] w-[22px]" aria-hidden="true" />
          </span>
          <div className="min-w-0 pt-0.5 text-left">
            <h2 id="growth-heading" className="text-[15px] font-semibold text-slate-100">本周新掌握</h2>
            {counts ? (
              <p className="mt-1 truncate text-[11px] leading-snug text-slate-400">
                短期 {counts.short.value} · 项目 {counts.project.value} · 归档 {counts.archive.value} · 团队 {counts.team.value}
              </p>
            ) : <p className="mt-1 text-[12px] leading-snug text-slate-400">知识、方法与协作经验</p>}
          </div>
        </div>
        <ModuleSourceBadges sources={model.sources} />
      </header>

      <div className="divide-y divide-white/[0.06]">
        {model.loading ? <p role="status" className="py-5 text-sm text-slate-400">正在读取成长记录…</p> : null}
        {model.error ? <p role="alert" className="py-5 text-sm text-rose">{model.error}</p> : null}
        {!model.loading && !model.error && model.data.categories.length === 0 ? <p className="py-5 text-sm text-slate-400">尚无可展示的成长记录。</p> : null}
        {model.data.categories.slice(0, 3).map((item, index) => {
          const Icon = CATEGORY_ICONS[index] ?? BookMarked
          return (
            <div key={item.label.value} className="flex min-h-[60px] items-center gap-3 py-2">
              <Icon className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[16px] font-semibold tabular-nums text-mint-300">{item.metric.value}</span>
                  <span className="text-[13px] font-medium text-slate-300">{item.label.value}</span>
                  <ValueSourceBadge value={item.metric} />
                </div>
                <p className="mt-1 truncate text-[12px] text-slate-400">{item.value.value}</p>
              </div>
            </div>
          )
        })}
      </div>

      <footer className="flex h-10 items-end justify-end">
        <button
          type="button"
          onClick={() => navigate('/digital-human?section=skills')}
          className="inline-flex min-h-10 items-center gap-1 text-[12px] font-medium text-slate-400 transition-[color,transform] duration-150 hover:text-mint-300 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
        >
          查看数字员工档案
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </footer>
    </section>
  )
}
