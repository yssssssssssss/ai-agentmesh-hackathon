import { useEffect, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  Bot,
  Sparkles,
  LineChart,
  BookMarked,
  Network,
  Settings,
  ChevronDown,
  ChevronRight,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '../../lib/cn'
import { useDemo } from '../../store/DemoContext'
import { CURRENT_USER } from '../../data/mockData'
import { DigitalHumanMark } from '../ui/DigitalHumanMark'
import { ConversationNav } from '../workspace/ConversationNav'

type NavItem = {
  to: string
  label: string
  icon: LucideIcon
  badgeKey?: 'pending' | 'requests'
}

const BASE_NAV: NavItem[] = [
  { to: '/digital-self', label: '我的数字员工', icon: Bot },
  { to: '/workspace', label: 'AI 工作台', icon: Sparkles },
  { to: '/insights', label: '工作洞察', icon: LineChart },
  { to: '/knowledge', label: '我的知识', icon: BookMarked, badgeKey: 'pending' },
  { to: '/collaboration', label: '协作网络', icon: Network, badgeKey: 'requests' },
]

interface SidebarProps {
  onOpenSettings: () => void
}

export function Sidebar({ onOpenSettings }: SidebarProps) {
  const navigate = useNavigate()
  const { pendingCount } = useDemo()
  const { pathname } = useLocation()
  const isWorkspace = pathname.startsWith('/workspace')
  const isDigitalHuman = pathname.startsWith('/digital-human')

  // 「AI 工作台」下的历史对话子导航:进入工作台自动展开,可手动折叠
  const [historyOpen, setHistoryOpen] = useState(isWorkspace)
  useEffect(() => {
    if (isWorkspace) setHistoryOpen(true)
  }, [isWorkspace])

  const nav = BASE_NAV

  return (
    <aside className="flex h-full w-[260px] shrink-0 flex-col border-r border-white/[0.06] bg-base">
      {/* 平台品牌 */}
      <div className="flex h-[80px] items-center px-5">
        <div className="leading-tight">
          <div className="text-[21px] font-bold tracking-wide text-white">AgentMesh</div>
          <div className="mt-1 text-[11px] tracking-[0.12em] text-slate-500">我的数字员工</div>
        </div>
      </div>

      {/* 一级导航(AI 工作台 展开历史对话子导航) */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {nav.map((item) => {
          const Icon = item.icon
          const badge =
            item.badgeKey === 'pending' ? pendingCount : item.badgeKey === 'requests' ? 3 : 0
          const isWorkspaceItem = item.to === '/workspace'
          return (
            <div key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'group relative flex items-center gap-3 rounded-[10px] px-3 py-2.5 text-sm font-medium transition-all duration-150',
                    isActive
                      ? 'bg-surface-3 text-white'
                      : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {isActive && (
                      <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-mint-400" />
                    )}
                    <Icon
                      className={cn('h-[18px] w-[18px] shrink-0', isActive ? 'text-mint-300' : '')}
                    />
                    <span className="flex-1">{item.label}</span>
                    {badge > 0 && (
                      <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-mint-400/20 px-1.5 text-[11px] font-semibold text-mint-300 tabular-nums">
                        {badge}
                      </span>
                    )}
                    {isWorkspaceItem && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault()
                          e.stopPropagation()
                          setHistoryOpen((v) => !v)
                        }}
                        className="-mr-1 rounded p-0.5 text-slate-500 transition-colors hover:text-slate-200"
                        aria-label={historyOpen ? '收起历史对话' : '展开历史对话'}
                      >
                        <ChevronDown
                          className={cn(
                            'h-4 w-4 transition-transform',
                            historyOpen ? '' : '-rotate-90',
                          )}
                        />
                      </button>
                    )}
                  </>
                )}
              </NavLink>

              {/* 历史对话子导航 + 与其余导航的分割线 */}
              {isWorkspaceItem && historyOpen && (
                <>
                  <div className="mt-1.5 border-l border-white/[0.06] pl-2">
                    <ConversationNav />
                  </div>
                  {/* 分割线:区隔「AI 工作台」模块与后续导航 */}
                  <div className="mt-2 border-t border-white/[0.08]" />
                </>
              )}
            </div>
          )
        })}
      </nav>

        {/* 底部:空间 + 数字人入口 + 用户设置 */}
      <div className="relative border-t border-white/[0.06] p-3">
        {/* 数字人入口卡 —— 通往「数字人管理」独立页(不进主导航) */}
        <button
          type="button"
          onClick={() => navigate('/digital-human')}
          className={cn(
            'group relative mb-2 flex w-full items-center gap-3 rounded-[12px] border px-3 py-2.5 text-left transition-all',
            isDigitalHuman
              ? 'border-mint-400/40 bg-mint-400/[0.10]'
              : 'border-white/[0.06] bg-surface-1 hover:border-white/[0.14] hover:bg-white/[0.04]',
          )}
        >
          <DigitalHumanMark size={40} online={false} />
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[13px] font-semibold text-slate-100">
              {CURRENT_USER.name}的数字员工
            </div>
          </div>
          <ChevronRight
            className={cn(
              'h-4 w-4 shrink-0 transition-colors',
              isDigitalHuman ? 'text-mint-300' : 'text-slate-500 group-hover:text-slate-300',
            )}
          />
        </button>

        <button
          type="button"
          onClick={onOpenSettings}
          className="flex w-full items-center gap-3 rounded-[10px] px-2 py-2 text-left transition-colors hover:bg-white/[0.04]"
          aria-label="打开账号与设置"
        >
          <span className="min-w-0 flex-1 truncate px-1 text-sm font-medium text-slate-100">
            {CURRENT_USER.name}
          </span>
          <Settings className="h-[18px] w-[18px] shrink-0 text-slate-500" />
        </button>
      </div>
    </aside>
  )
}
