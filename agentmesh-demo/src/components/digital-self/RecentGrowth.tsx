import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, BookMarked, TrendingUp, Users, Wrench } from 'lucide-react'
import { useUserMemory } from '../../lib/useUserMemory'

/** 首页展示数字员工本周在真实工作中新增的经验、方法和协作。 */
export function RecentGrowth() {
  const navigate = useNavigate()
  const { items, loading, error } = useUserMemory()

  // 近 7 天新增的记忆,按类型聚合为「经验 / 方法」两类指标
  const growth = useMemo(() => {
    const weekAgo = Date.now() - 7 * 24 * 3600 * 1000
    const recent = items.filter((i) => new Date(i.created_at).getTime() >= weekAgo)
    const experiences = recent.filter((i) => i.memory_type === 'decision' || i.memory_type === 'fact')
    const methods = recent.filter((i) => i.memory_type === 'method')
    return { recent, experiences, methods }
  }, [items])

  const rows = [
    {
      icon: BookMarked,
      metric: `+${growth.experiences.length}`,
      label: '已确认经验',
      value: growth.experiences[0]?.title ?? '本周暂无新增',
    },
    {
      icon: Wrench,
      metric: `+${growth.methods.length}`,
      label: '工作方法',
      value: growth.methods[0]?.title ?? '本周暂无新增',
    },
    {
      icon: Users,
      metric: `+${growth.recent.length}`,
      label: '条新记忆',
      value: growth.recent[0]?.title ?? '本周暂无新增',
    },
  ]

  return (
    <section className="card-base grid h-[320px] grid-rows-[56px_1fr_40px] p-5">
      <header className="flex h-[56px] items-start gap-3">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[12px] bg-knowledge/10 text-knowledge">
          <TrendingUp className="h-[22px] w-[22px]" />
        </span>
        <div className="min-w-0 pt-0.5 text-left">
          <h2 className="text-[15px] font-semibold text-slate-100">本周新掌握</h2>
          <p className="mt-1 text-[12px] leading-snug text-slate-500">实际工作中新增的知识、方法与协作经验</p>
        </div>
      </header>

      <div className="divide-y divide-white/[0.06]">
        {loading ? (
          <div className="flex h-full items-center justify-center text-[12px] text-slate-600">加载中…</div>
        ) : error ? (
          <div className="flex h-full items-center justify-center text-[12px] text-slate-600">暂时无法加载</div>
        ) : (
          rows.map((item) => (
            <div key={item.label} className="flex h-[60px] items-center gap-3">
              <item.icon className="h-4 w-4 shrink-0 text-slate-500" />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5">
                  <span className="text-[16px] font-semibold tabular-nums text-mint-300">{item.metric}</span>
                  <span className="text-[13px] font-medium text-slate-300">{item.label}</span>
                </div>
                <p className="mt-1 truncate text-[12px] text-slate-500">{item.value}</p>
              </div>
            </div>
          ))
        )}
      </div>

      <footer className="flex h-10 items-end justify-end">
        <button
          type="button"
          onClick={() => navigate('/digital-human?section=skills')}
          className="inline-flex items-center gap-1 text-[12px] font-medium text-slate-400 transition-colors hover:text-mint-300"
        >
          查看数字员工档案
          <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </footer>
    </section>
  )
}
