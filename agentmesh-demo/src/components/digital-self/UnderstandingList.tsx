import { useNavigate } from 'react-router-dom'
import { ArrowRight, Sparkles } from 'lucide-react'
import { useUserMemory } from '../../lib/useUserMemory'
import type { UserMemoryItem } from '../../lib/api'

/** memory_type → 中文语义桶标签(与演示文案对齐)。 */
const TYPE_LABELS: Record<string, string> = {
  decision: '决策习惯',
  method: '正在沉淀',
  note: '近期工作重点',
  fact: '工作上下文',
}

function labelOf(item: UserMemoryItem): string {
  return TYPE_LABELS[item.memory_type] ?? '工作理解'
}

/** 首页只展示数字员工对工作的已确认理解摘要，完整内容进入管理页查看。 */
export function UnderstandingList() {
  const navigate = useNavigate()
  const { items, loading, error } = useUserMemory()
  // 取最近 3 条作为「已确认理解」摘要;真实数据不足时保持留白而非编造
  const understandings = items.slice(0, 3)

  return (
    <section className="card-base grid h-[320px] grid-rows-[56px_1fr_40px] p-5">
      <header className="flex h-[56px] items-start gap-3">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[12px] bg-mint-400/10 text-mint-300">
          <Sparkles className="h-[22px] w-[22px]" />
        </span>
        <div className="min-w-0 pt-0.5 text-left">
          <h2 className="text-[15px] font-semibold text-slate-100">对你的工作理解</h2>
          <p className="mt-1 text-[12px] leading-snug text-slate-500">基于近期工作形成，并经过你的确认</p>
        </div>
      </header>

      <div className="divide-y divide-white/[0.06]">
        {loading ? (
          <div className="flex h-full items-center justify-center text-[12px] text-slate-600">加载中…</div>
        ) : error ? (
          <div className="flex h-full items-center justify-center text-[12px] text-slate-600">暂时无法加载</div>
        ) : understandings.length === 0 ? (
          <div className="flex h-full items-center justify-center text-[12px] text-slate-600">
            还没有已确认的工作理解
          </div>
        ) : (
          understandings.map((item) => (
            <div key={item.id} className="flex h-[60px] flex-col justify-center">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-medium text-slate-300">{labelOf(item)}</span>
                <span className="rounded-pill bg-mint-400/10 px-2 py-0.5 text-[10.5px] text-mint-300">已确认</span>
              </div>
              <p className="mt-1 truncate text-[12px] text-slate-500">{item.title}</p>
            </div>
          ))
        )}
      </div>

      <footer className="flex h-10 items-end justify-end">
        <button
          type="button"
          onClick={() => navigate('/digital-human?section=understanding')}
          className="inline-flex items-center gap-1 text-[12px] font-medium text-slate-400 transition-colors hover:text-mint-300"
        >
          查看全部理解
          <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </footer>
    </section>
  )
}
