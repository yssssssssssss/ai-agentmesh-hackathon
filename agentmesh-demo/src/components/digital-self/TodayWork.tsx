import { ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { DigitalSelfViewModel } from '../../features/digital-self/presenter'
import { ModuleSourceBadges, ValueSourceBadge } from './SourceBadges'

interface TodayWorkProps {
  model: DigitalSelfViewModel['pending']
}

export function TodayWork({ model }: TodayWorkProps) {
  const navigate = useNavigate()
  const items = model.data.items.slice(0, 2)
  const showsActivityHistory = items.some((item) => item.actor !== undefined)

  return (
    <section className="pt-6" aria-labelledby="pending-work-heading">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="pending-work-heading" className="text-[16px] font-semibold text-slate-100">
            {showsActivityHistory ? '今日工作记录' : '需要你处理'}
          </h2>
          <p className="mt-0.5 text-[12px] text-slate-400">
            {showsActivityHistory
              ? `服务端记录了 ${model.data.items.length} 项活动，仅供查看`
              : `数字员工推进工作后，有 ${model.data.items.length} 项参考内容等待处理`}
          </p>
        </div>
        <ModuleSourceBadges sources={model.sources} />
      </div>

      {model.loading ? <p role="status" className="rounded-soft bg-surface-1 p-4 text-sm text-slate-400">正在读取工作记录…</p> : null}
      {model.error ? <p role="alert" className="rounded-soft border border-rose/25 bg-rose/10 p-4 text-sm text-rose">{model.error}</p> : null}
      {!model.loading && !model.error && items.length === 0 ? (
        <p className="rounded-soft bg-surface-1 p-4 text-sm text-slate-400">当前没有可展示的活动记录。</p>
      ) : null}

      {items.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {items.map((item, index) => {
            const key = item.id.value ?? `${item.title.value}-${index}`
            if (item.actor) {
              return (
                <article key={key} className="flex min-h-[132px] flex-col rounded-soft border border-white/[0.07] bg-surface-1 p-4 text-left">
                  <span className="flex w-full flex-wrap items-center justify-between gap-2">
                    <span className="w-fit rounded-pill bg-white/[0.05] px-2 py-0.5 text-[10.5px] font-medium text-slate-400">{item.tag.value}</span>
                    <ValueSourceBadge value={item.title} />
                  </span>
                  <h3 className="mt-2.5 text-[14px] font-semibold text-slate-100">{item.title.value}</h3>
                  <p className="mt-1 text-[12px] leading-relaxed text-slate-400">{item.context.value}</p>
                  <span className="mt-auto pt-3 text-[11px] text-slate-400">记录者：{item.actor.value} · 只读活动</span>
                </article>
              )
            }

            const actionable = item.to?.source === 'T'
            return (
              <button
                key={key}
                type="button"
                disabled={!actionable}
                title={actionable ? undefined : '参考展示事项，当前不可操作'}
                onClick={() => actionable && item.to && navigate(item.to.value)}
                className="flex min-h-[132px] flex-col rounded-soft border border-white/[0.07] bg-surface-1 p-4 text-left transition-[background-color,border-color,transform] duration-150 enabled:hover:border-white/[0.14] enabled:hover:bg-surface-2 enabled:active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-70"
              >
                <span className="flex w-full flex-wrap items-center justify-between gap-2">
                  <span className="w-fit rounded-pill bg-white/[0.05] px-2 py-0.5 text-[10.5px] font-medium text-slate-400">{item.tag.value}</span>
                  <ValueSourceBadge value={item.title} />
                </span>
                <h3 className="mt-2.5 text-[14px] font-semibold text-slate-100">{item.title.value}</h3>
                <p className="mt-1 text-[12px] leading-relaxed text-slate-400">{item.context.value}</p>
                <span className="mt-auto inline-flex items-center gap-1 pt-3 text-[12px] font-medium text-slate-400">
                  {item.cta?.value ?? '查看详情'}
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
              </button>
            )
          })}
        </div>
      ) : null}
    </section>
  )
}
