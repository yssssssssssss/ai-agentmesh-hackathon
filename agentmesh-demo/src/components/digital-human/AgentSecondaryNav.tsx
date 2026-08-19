import { IdCard, Sparkles, Wrench, ShieldCheck, History, type LucideIcon } from 'lucide-react'
import { DigitalHumanMark } from '../ui/DigitalHumanMark'
import { cn } from '../../lib/cn'

export type SectionKey = 'profile' | 'understanding' | 'skills' | 'knowledge' | 'activity'

export const SECTIONS: { key: SectionKey; label: string; mobileLabel: string; icon: LucideIcon }[] = [
  { key: 'profile', label: '数字员工档案', mobileLabel: '档案', icon: IdCard },
  { key: 'understanding', label: '对我的理解', mobileLabel: '理解', icon: Sparkles },
  { key: 'skills', label: '能力与 Skill', mobileLabel: 'Skill', icon: Wrench },
  { key: 'knowledge', label: '知识与权限', mobileLabel: '权限', icon: ShieldCheck },
  { key: 'activity', label: '活动记录', mobileLabel: '活动', icon: History },
]

interface Props {
  section: SectionKey
  onSelect: (key: SectionKey) => void
}

/**
 * 数字人管理页的二级导航。
 * 复用左侧栏一级导航的高亮范式(bg-surface-3 + mint 左条 + mint 图标),
 * 但不进入主导航(BASE_NAV),仅通过侧栏「数字人入口卡」到达。
 */
export function AgentSecondaryNav({ section, onSelect }: Props) {
  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-white/[0.06] bg-base md:h-full md:w-[240px] md:border-b-0 md:border-r">
      {/* 品牌块 */}
      <div className="hidden items-center gap-3 border-b border-white/[0.06] px-5 py-5 md:flex">
        <DigitalHumanMark size={40} online={false} />
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[15px] font-semibold text-white">数字员工管理</div>
        </div>
      </div>

      {/* 分区导航 */}
      <nav aria-label="数字员工管理分区" className="flex justify-between gap-1 overflow-x-auto px-3 py-2 md:flex-1 md:flex-col md:justify-start md:overflow-y-auto md:py-3">
        {SECTIONS.map((s) => {
          const Icon = s.icon
          const active = s.key === section
          return (
            <button
              key={s.key}
              type="button"
              aria-current={active ? 'page' : undefined}
              aria-label={s.label}
              onClick={() => onSelect(s.key)}
              className={cn(
                'group relative flex min-h-10 shrink-0 items-center gap-2 rounded-[10px] px-3 py-2 text-left text-sm font-medium transition-[transform,background-color,color] duration-150 active:scale-[0.98] md:w-full md:gap-3 md:py-2.5',
                active
                  ? 'bg-surface-3 text-white'
                  : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200',
              )}
            >
              {active && (
                <>
                  <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-t-full bg-mint-400 md:hidden" />
                  <span className="absolute left-0 top-1/2 hidden h-5 w-1 -translate-y-1/2 rounded-r-full bg-mint-400 md:block" />
                </>
              )}
              <Icon className={cn('hidden h-[18px] w-[18px] shrink-0 md:block', active ? 'text-mint-300' : '')} />
              <span className="whitespace-nowrap md:hidden">{s.mobileLabel}</span>
              <span className="hidden whitespace-nowrap md:flex-1 md:block">{s.label}</span>
            </button>
          )
        })}
      </nav>
    </aside>
  )
}
