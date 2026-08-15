import { useState, type ReactNode } from 'react'
import {
  Bell,
  Bot,
  ChevronRight,
  Cpu,
  LogOut,
  Moon,
  ScrollText,
  Settings,
  Shield,
  Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { ADMIN_CAPABILITIES, hasCapability, type AdminCapability } from '../../features/admin/api'
import { useAuth } from '../../features/auth/AuthProvider'
import { cn } from '../../lib/cn'
import { Avatar } from '../ui/Avatar'
import { DataSourceBadge } from '../ui/DataSourceBadge'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Drawer } from '../ui/Drawer'

interface SettingsDrawerProps {
  open: boolean
  onClose: () => void
}

interface SettingsEntry {
  section: string
  capability: AdminCapability
  alternate?: AdminCapability
  icon: LucideIcon
  label: string
  desc: string
}

const ENTRIES: SettingsEntry[] = [
  { section: 'users', capability: ADMIN_CAPABILITIES.users, icon: Users, label: '用户管理', desc: '创建、禁用账号与密码重置' },
  { section: 'agents', capability: ADMIN_CAPABILITIES.agents, icon: Bot, label: 'Agent 配置', desc: '公共 Agent 的模型与工具' },
  { section: 'providers', capability: ADMIN_CAPABILITIES.providers, alternate: ADMIN_CAPABILITIES.o2, icon: Cpu, label: 'Provider 与 O2', desc: '运行状态和工具同步' },
  { section: 'policies', capability: ADMIN_CAPABILITIES.permissionPolicies, alternate: ADMIN_CAPABILITIES.riskPolicies, icon: Shield, label: '策略只读', desc: '权限与风险规则' },
  { section: 'audit', capability: ADMIN_CAPABILITIES.audit, icon: ScrollText, label: '审计日志', desc: '查看服务端审计事件' },
]

export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const [darkTheme, setDarkTheme] = useState(true)
  const [notify, setNotify] = useState(true)
  const navigate = useNavigate()
  const { user, bootstrap, logout, logoutError } = useAuth()
  const capabilities = bootstrap?.capabilities ?? []
  const entries = ENTRIES.filter((entry) => hasCapability(capabilities, entry.capability) || (entry.alternate ? hasCapability(capabilities, entry.alternate) : false))

  return (
    <Drawer
      open={open}
      onClose={onClose}
      icon={<Settings className="h-5 w-5" />}
      title="账号与设置"
      subtitle={user && bootstrap ? `${user.name} · ${bootstrap.workspace.name}` : '当前账号'}
      width={460}
    >
      <div className="space-y-6">
        <section>
          <div className="mb-3 flex items-center gap-3">
            <Avatar name={user?.name ?? ''} size="md" tone="mint" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="truncate text-[15px] font-semibold text-white">{user?.name ?? '账号信息'}</span>
                {user ? <Badge tone="neutral">{user.role}</Badge> : null}
              </div>
              <div className="mt-0.5 truncate text-xs text-slate-500">{bootstrap?.project.name ?? '项目信息暂时不可用'}</div>
            </div>
            <DataSourceBadge source="T" />
          </div>
          <div className="space-y-1.5 rounded-[12px] border border-white/[0.06] bg-surface-1 px-4 py-3">
            <RowLine label="姓名" value={user?.name ?? '暂无'} />
            <RowLine label="账号 ID" value={<span className="font-mono text-[11.5px]">{user?.id ?? '暂无'}</span>} />
            <RowLine label="工作空间" value={bootstrap?.workspace.name ?? '暂无'} />
            <RowLine label="当前项目" value={bootstrap?.project.name ?? '暂无'} />
            <RowLine label="当前身份" value={user?.role ?? '暂无'} />
          </div>
        </section>

        <section>
          <div className="mb-2.5 flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-slate-200">显示与偏好</h3>
            <DataSourceBadge source="M" />
          </div>
          <div className="divide-y divide-white/[0.05] overflow-hidden rounded-[12px] border border-white/[0.06] bg-surface-1">
            <ToggleRow
              icon={<Moon className="h-4 w-4 text-slate-400" />}
              label="深色主题"
              hint="当前仅提供深色企业主题"
              on={darkTheme}
              onToggle={() => setDarkTheme((current) => !current)}
            />
            <ToggleRow
              icon={<Bell className="h-4 w-4 text-slate-400" />}
              label="消息通知"
              hint="协作请求、授权与反馈的桌面提醒"
              on={notify}
              onToggle={() => setNotify((current) => !current)}
            />
          </div>
        </section>

        {entries.length > 0 ? (
          <section>
            <div className="mb-3 flex items-center gap-2">
              <h3 className="text-sm font-semibold text-slate-200">管理入口</h3>
              <Badge tone="neutral">{entries.length}</Badge>
            </div>
            <div className="space-y-2">
              {entries.map((entry) => (
                <button
                  key={entry.section}
                  type="button"
                  onClick={() => {
                    navigate(`/admin?section=${entry.section}`)
                    onClose()
                  }}
                  className="flex w-full items-center gap-3 rounded-[10px] border border-white/[0.06] bg-surface-1 px-4 py-3 text-left transition-colors hover:border-white/[0.12] hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.05] text-slate-300">
                    <entry.icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-slate-100">{entry.label}</span>
                    <span className="block text-xs text-slate-500">{entry.desc}</span>
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-slate-600" />
                </button>
              ))}
            </div>
          </section>
        ) : null}

        <Button
          type="button"
          variant="danger"
          block
          icon={<LogOut className="h-4 w-4" />}
          onClick={() => void logout().catch(() => undefined)}
        >
          {logoutError ? '重试退出' : '退出登录'}
        </Button>
        {logoutError ? <p role="alert" className="rounded-lg bg-rose/10 px-3 py-2 text-xs leading-5 text-rose">{logoutError}</p> : null}
      </div>
    </Drawer>
  )
}

function RowLine({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 text-[12px]">
      <span className="text-slate-500">{label}</span>
      <span className="min-w-0 flex-1 truncate text-right text-slate-300">{value}</span>
    </div>
  )
}

function ToggleRow({
  icon,
  label,
  hint,
  on,
  onToggle,
}: {
  icon: ReactNode
  label: string
  hint?: string
  on: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-white/[0.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-mint-400/50"
      role="switch"
      aria-checked={on}
    >
      {icon}
      <span className="min-w-0 flex-1">
        <span className="block text-sm text-slate-200">{label}</span>
        {hint ? <span className="mt-0.5 block text-[11px] text-slate-500">{hint}</span> : null}
      </span>
      <span
        aria-hidden="true"
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
          on ? 'bg-mint-400' : 'bg-white/[0.12]',
        )}
      >
        <span
          className={cn(
            'absolute left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
            on ? 'translate-x-4' : 'translate-x-0',
          )}
        />
      </span>
    </button>
  )
}
