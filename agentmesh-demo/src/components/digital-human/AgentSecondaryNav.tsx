import { IdCard, Sparkles, Wrench, ShieldCheck, History, type LucideIcon } from 'lucide-react'
import { DigitalHumanMark } from '../ui/DigitalHumanMark'
import { cn } from '../../lib/cn'

export type SectionKey = 'profile' | 'understanding' | 'skills' | 'knowledge' | 'activity'

export const SECTIONS: { key: SectionKey; label: string; icon: LucideIcon }[] = [
  { key: 'profile', label: '数字员工档案', icon: IdCard },
  { key: 'understanding', label: '对我的理解', icon: Sparkles },
  { key: 'skills', label: '能力与 Skill', icon: Wrench },
  { key: 'knowledge', label: '知识与权限', icon: ShieldCheck },
  { key: 'activity', label: '活动记录', icon: History },
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
    <aside className="flex h-full w-[240px] shrink-0 flex-col border-r border-white/[0.06] bg-base">
      {/* 品牌块 */}
      <div className="flex items-center gap-3 border-b border-white/[0.06] px-5 py-5">
        <DigitalHumanMark size={40} online={false} />
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[15px] font-semibold text-white">Digital Human demo</div>
        </div>
      </div>

      {/* 分区导航 */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-3">
        {SECTIONS.map((s) => {
          const Icon = s.icon
          const active = s.key === section
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => onSelect(s.key)}
              className={cn(
                'group relative flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left text-sm font-medium transition-all duration-150',
                active
                  ? 'bg-surface-3 text-white'
                  : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200',
              )}
            >
              {active && (
                <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-mint-400" />
              )}
              <Icon className={cn('h-[18px] w-[18px] shrink-0', active ? 'text-mint-300' : '')} />
              <span className="flex-1">{s.label}</span>
            </button>
          )
        })}
      </nav>

      {/* 底部说明 —— 明确本页与首页的分工 */}
      <div className="border-t border-white/[0.06] px-5 py-4">
        <p className="text-[11px] leading-relaxed text-slate-500">
          本页为本地视觉演示，人物、数据与状态均为示意，不代表当前登录用户的真实信息。
        </p>
      </div>
    </aside>
  )
}
