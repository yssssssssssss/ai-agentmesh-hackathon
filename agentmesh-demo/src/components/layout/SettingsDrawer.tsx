import { Bot, ChevronRight, Cpu, ScrollText, Shield, Users } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { ADMIN_CAPABILITIES, hasCapability, type AdminCapability } from '../../features/admin/api'
import { useAuth } from '../../features/auth/AuthProvider'
import { Badge } from '../ui/Badge'
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
  const navigate = useNavigate()
  const { bootstrap } = useAuth()
  const capabilities = bootstrap?.capabilities ?? []
  const entries = ENTRIES.filter((entry) => hasCapability(capabilities, entry.capability) || (entry.alternate ? hasCapability(capabilities, entry.alternate) : false))
  return (
    <Drawer open={open} onClose={onClose} icon={<Shield className="h-5 w-5" />} title="设置" subtitle="由账号 capability 开放的管理入口" width={460}>
      <section>
        <div className="mb-3 flex items-center gap-2"><h3 className="text-sm font-semibold text-slate-200">可用能力</h3><Badge tone="neutral">{entries.length}</Badge></div>
        {entries.length === 0 ? <p className="rounded-[12px] border border-white/[0.06] bg-surface-1 p-4 text-sm text-slate-500">当前账号没有管理入口。</p> : (
          <div className="space-y-2">
            {entries.map((entry) => (
              <button
                key={entry.section}
                type="button"
                onClick={() => { navigate(`/admin?section=${entry.section}`); onClose() }}
                className="flex w-full items-center gap-3 rounded-[10px] border border-white/[0.06] bg-surface-1 px-4 py-3 text-left transition-colors hover:border-white/[0.12] hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.05] text-slate-300"><entry.icon className="h-4 w-4" /></span>
                <span className="min-w-0 flex-1"><span className="block text-sm font-medium text-slate-100">{entry.label}</span><span className="block text-xs text-slate-500">{entry.desc}</span></span>
                <ChevronRight className="h-4 w-4 text-slate-600" />
              </button>
            ))}
          </div>
        )}
      </section>
    </Drawer>
  )
}
