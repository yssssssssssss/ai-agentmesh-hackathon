import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  BookMarked,
  Bot,
  ChevronDown,
  ChevronRight,
  LineChart,
  ListTodo,
  LogOut,
  Network,
  RadioTower,
  Settings,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { useAuth } from '../../features/auth/AuthProvider'
import { cn } from '../../lib/cn'
import { Avatar } from '../ui/Avatar'
import { DigitalHumanMark } from '../ui/DigitalHumanMark'
import { ConversationNav } from '../workspace/ConversationNav'

interface NavigationItem {
  to: string
  label: string
  icon: LucideIcon
  badgeKey?: 'memory' | 'inbox'
}

const NAV: NavigationItem[] = [
  { to: '/digital-self', label: '我的数字员工', icon: Bot },
  { to: '/workspace', label: 'AI 工作台', icon: Sparkles },
  { to: '/insights', label: '工作洞察', icon: LineChart },
  { to: '/knowledge', label: '我的知识', icon: BookMarked, badgeKey: 'memory' as const },
  { to: '/collaboration', label: '协作网络', icon: Network, badgeKey: 'inbox' as const },
  { to: '/tasks', label: '任务中心', icon: ListTodo },
  { to: '/market', label: '协作市场', icon: RadioTower },
]

interface SidebarProps {
  onOpenSettings: () => void
  onOpenProfile: () => void
}

export function Sidebar({ onOpenSettings, onOpenProfile }: SidebarProps) {
  const { user, bootstrap, logout, logoutError } = useAuth()
  const { pathname } = useLocation()
  const isWorkspace = pathname.startsWith('/workspace')
  const isDigitalHuman = pathname.startsWith('/digital-human')
  const [historyOpen, setHistoryOpen] = useState(isWorkspace)
  const capabilities = bootstrap?.capabilities ?? []
  useEffect(() => {
    if (isWorkspace) setHistoryOpen(true)
  }, [isWorkspace])

  const nav: NavigationItem[] = capabilities.length > 0
    ? [...NAV, { to: '/admin', label: '管理控制台', icon: ShieldCheck }]
    : NAV

  return (
    <aside className="flex h-full w-[260px] shrink-0 flex-col border-r border-white/[0.06] bg-base">
      <div className="flex h-[80px] items-center px-5">
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[21px] font-bold tracking-wide text-white">AgentMesh</div>
          <div className="mt-1 truncate text-[11px] tracking-[0.12em] text-slate-400">我的数字员工</div>
        </div>
      </div>
      <nav aria-label="主导航" className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {nav.map((item) => {
          const Icon = item.icon
          const badge = item.badgeKey === 'memory'
            ? bootstrap?.metrics.memory_candidate_count ?? 0
            : item.badgeKey === 'inbox'
              ? bootstrap?.metrics.inbox_open_count ?? 0
              : 0
          const isWorkspaceItem = item.to === '/workspace'
          return (
            <div key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) => cn('group relative flex items-center gap-3 rounded-soft px-3 py-2.5 text-sm font-medium transition-[background-color,color] duration-150', isActive ? 'bg-surface-3 text-white' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200')}
              >
                {({ isActive }) => <>{isActive ? <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-mint-400" /> : null}<Icon className={cn('h-[18px] w-[18px] shrink-0', isActive ? 'text-mint-300' : '')} /><span className="flex-1">{item.label}</span>{badge > 0 ? <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-mint-400/20 px-1.5 text-[11px] font-semibold text-mint-300 tabular-nums">{badge}</span> : null}{isWorkspaceItem ? <button type="button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); setHistoryOpen((current) => !current) }} className="-mr-1 rounded p-0.5 text-slate-400 transition-colors hover:text-slate-200" aria-label={historyOpen ? '收起历史对话' : '展开历史对话'}><ChevronDown className={cn('h-4 w-4 transition-transform', historyOpen ? '' : '-rotate-90')} /></button> : null}</>}
              </NavLink>
              {isWorkspaceItem && historyOpen ? <><div className="mt-1.5 border-l border-white/[0.06] pl-2"><ConversationNav /></div><div className="mt-2 border-t border-white/[0.08]" /></> : null}
            </div>
          )
        })}
      </nav>
      <div className="border-t border-white/[0.06] p-3">
        <NavLink
          to="/digital-human"
          aria-label="打开数字人管理"
          className={cn(
            'group mb-2 flex min-h-12 w-full items-center gap-3 rounded-soft border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50',
            isDigitalHuman
              ? 'border-mint-400/40 bg-mint-400/[0.10]'
              : 'border-white/[0.06] bg-surface-1 hover:border-white/[0.14] hover:bg-white/[0.04]',
          )}
        >
          <DigitalHumanMark size={36} online={false} />
          <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-slate-100">
            {user?.name ?? '我'}的数字员工
          </span>
          <ChevronRight className={cn('h-4 w-4 shrink-0', isDigitalHuman ? 'text-mint-300' : 'text-slate-400 group-hover:text-slate-300')} />
        </NavLink>
        <button type="button" onClick={onOpenProfile} aria-label="打开个人资料" className="flex min-h-10 w-full items-center gap-3 rounded-soft px-2 py-2 text-left transition-colors hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"><Avatar name={user?.name ?? ''} size="md" tone="mint" /><span className="min-w-0 flex-1 leading-tight"><span className="block truncate text-sm font-medium text-slate-100">{user?.name}</span><span className="block truncate text-xs text-slate-400">{user?.role}</span></span><ChevronRight className="h-4 w-4 text-slate-400" /></button>
        <button type="button" onClick={onOpenSettings} aria-label="打开账号与设置" className="mt-1 flex min-h-10 w-full items-center gap-3 rounded-soft px-3 py-2 text-sm text-slate-400 transition-colors hover:bg-white/[0.04] hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"><Settings className="h-[18px] w-[18px]" />账号与设置</button>
        <button type="button" onClick={() => void logout().catch(() => undefined)} className="mt-1 flex min-h-10 w-full items-center gap-3 rounded-soft px-3 py-2 text-sm text-slate-400 transition-colors hover:bg-white/[0.04] hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"><LogOut className="h-[18px] w-[18px]" />{logoutError ? '重试退出' : '退出登录'}</button>
        {logoutError ? <p role="alert" className="mt-2 rounded-lg bg-rose/10 px-3 py-2 text-xs leading-5 text-rose">{logoutError}</p> : null}
      </div>
    </aside>
  )
}
