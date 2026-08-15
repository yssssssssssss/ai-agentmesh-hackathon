import { useNavigate } from 'react-router-dom'
import { ArrowRight, Share2 } from 'lucide-react'

const ITEMS = [
  {
    label: '活动标签信息层级规范',
    value: '本周被 4 位同事的数字员工用于相关项目',
    meta: '本周',
  },
  {
    label: '会场楼层优先级模型',
    value: '被用于「2024 家电超级品类日」项目复盘',
    meta: '上周',
  },
  {
    label: '本周影响',
    value: '帮助 4 位同事 · 被调用 6 次',
    meta: '',
  },
]

/** 首页展示经用户授权后，个人经验被其他数字员工复用的轻量摘要。 */
export function MyImpact() {
  const navigate = useNavigate()

  return (
    <section className="card-base grid h-[320px] grid-rows-[56px_1fr_40px] p-5">
      <header className="flex h-[56px] items-start gap-3">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[12px] bg-collab/10 text-collab">
          <Share2 className="h-[22px] w-[22px]" />
        </span>
        <div className="min-w-0 pt-0.5 text-left">
          <h2 className="text-[15px] font-semibold text-slate-100">我的经验正在被复用</h2>
          <p className="mt-1 text-[12px] leading-snug text-slate-500">经你授权共享的工作经验，被其他数字员工调用</p>
        </div>
      </header>

      <div className="divide-y divide-white/[0.06]">
        {ITEMS.map((item) => (
          <div key={item.label} className="flex h-[60px] flex-col justify-center">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-[13px] font-medium text-slate-300">{item.label}</span>
              {item.meta && <span className="shrink-0 text-[10.5px] text-slate-600">{item.meta}</span>}
            </div>
            <p className="mt-1 truncate text-[12px] text-slate-500">
              {item.label === '本周影响' ? (
                <>帮助 <span className="font-semibold text-mint-300">4</span> 位同事 · 被调用 <span className="font-semibold text-mint-300">6</span> 次</>
              ) : item.value}
            </p>
          </div>
        ))}
      </div>

      <footer className="flex h-10 items-end justify-end">
        <button
          type="button"
          onClick={() => navigate('/digital-human?section=activity')}
          className="inline-flex items-center gap-1 text-[12px] font-medium text-slate-400 transition-colors hover:text-mint-300"
        >
          查看全部动态
          <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </footer>
    </section>
  )
}
