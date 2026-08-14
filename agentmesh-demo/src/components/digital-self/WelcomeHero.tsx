import { useNavigate } from 'react-router-dom'
import { ArrowRight, PlayCircle } from 'lucide-react'
import { Button } from '../ui/Button'
import { PRIORITY_ITEMS } from '../../data/mockData'
import { useSession } from '../../store/SessionContext'

/** 按当前小时给出问候语。 */
function greeting(): string {
  const h = new Date().getHours()
  if (h < 6) return '凌晨好'
  if (h < 12) return '上午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

/** 首页上半区：当前进展与待处理事项，使用克制、统一的视觉层级。 */
export function WelcomeHero() {
  const navigate = useNavigate()
  const { user } = useSession()
  const name = user?.name ?? '设计师'

  return (
    <section>
      {/* 01 当前进展：页面唯一高视觉权重区域 */}
      <div className="border-b border-white/[0.08] pb-7">
        <div className="mb-3 text-[11px] font-medium uppercase tracking-[0.14em] text-mint-300">
          当前进展
        </div>
        <h1 className="text-[28px] font-bold tracking-tight text-white">
          {greeting()}，{name}
        </h1>
        <p className="mt-2.5 whitespace-nowrap text-[15px] leading-relaxed text-slate-300">
          你的数字员工正在推进{' '}
          <span className="font-semibold text-white">「2026 年 618 家电会场首页改版」</span>，
          已完成历史项目与团队经验检索，并邀请{' '}
          <span className="font-semibold text-mint-300">2 位同事的数字员工</span>
          补充项目经验和近期数据。
        </p>
        <div className="mt-5">
          <Button
            size="lg"
            icon={<PlayCircle className="h-[18px] w-[18px]" />}
            iconRight={<ArrowRight className="h-4 w-4" />}
            onClick={() => navigate('/workspace')}
          >
            继续 618 项目
          </Button>
        </div>
      </div>

      {/* 02 待处理：统一为低强调的任务列表卡 */}
      <div className="pt-6">
        <div className="mb-3">
          <h2 className="text-[16px] font-semibold text-slate-100">需要你处理</h2>
          <p className="mt-0.5 text-[12px] text-slate-500">数字员工推进工作后，有 2 项内容等待你继续处理</p>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {PRIORITY_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => navigate(item.to)}
              className="group flex min-h-[132px] flex-col rounded-[12px] border border-white/[0.07] bg-surface-1 p-4 text-left transition-colors hover:border-white/[0.14] hover:bg-surface-2"
            >
              <span className="w-fit rounded-pill bg-white/[0.05] px-2 py-0.5 text-[10.5px] font-medium text-slate-400">
                {item.tag}
              </span>
              <h3 className="mt-2.5 text-[14px] font-semibold text-slate-100">{item.title}</h3>
              <p className="mt-1 text-[12px] leading-relaxed text-slate-500">{item.context}</p>
              <span className="mt-auto inline-flex items-center gap-1 pt-3 text-[12px] font-medium text-slate-400 transition-colors group-hover:text-mint-300">
                {item.cta}
                <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </span>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}
