import { useState } from 'react'
import { ArrowLeft, Shield } from 'lucide-react'

import { Button } from '../../components/ui/Button'
import { PageHeader } from '../../components/ui/PageHeader'
import { useAuth } from '../auth/AuthProvider'
import { AgentModule } from './AgentModule'
import { AuditModule } from './AuditModule'
import { DiagnosticsModule } from './DiagnosticsModule'
import { PolicyModule } from './PolicyModule'
import { UsersModule } from './UsersModule'
import { ADMIN_CAPABILITIES, hasCapability } from './api'

const SECTIONS = [
  { id: 'users', label: '用户管理' },
  { id: 'agents', label: 'Agent 配置' },
  { id: 'providers', label: 'Provider 与 O2' },
  { id: 'policies', label: '策略只读' },
  { id: 'audit', label: '审计日志' },
] as const

type SectionId = (typeof SECTIONS)[number]['id']

export function AdminPage() {
  const { user, bootstrap } = useAuth()
  const capabilities = bootstrap?.capabilities ?? []
  const allowed: SectionId[] = []
  if (hasCapability(capabilities, ADMIN_CAPABILITIES.users)) allowed.push('users')
  if (hasCapability(capabilities, ADMIN_CAPABILITIES.agents)) allowed.push('agents')
  if (
    hasCapability(capabilities, ADMIN_CAPABILITIES.providers) ||
    hasCapability(capabilities, ADMIN_CAPABILITIES.o2)
  ) allowed.push('providers')
  if (
    hasCapability(capabilities, ADMIN_CAPABILITIES.permissionPolicies) ||
    hasCapability(capabilities, ADMIN_CAPABILITIES.riskPolicies)
  ) allowed.push('policies')
  if (hasCapability(capabilities, ADMIN_CAPABILITIES.audit)) allowed.push('audit')

  const requestedSection = new URLSearchParams(window.location.search).get('section') as SectionId | null
  const initialSection = requestedSection && allowed.includes(requestedSection) ? requestedSection : allowed[0]
  const [section, setSection] = useState<SectionId | undefined>(initialSection)

  if (!user?.id || !bootstrap?.workspace.id) return null
  if (!section || allowed.length === 0) {
    return (
      <section className="mx-auto max-w-lg py-16 text-center">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-[12px] bg-white/[0.05] text-slate-300"><Shield className="h-5 w-5" /></span>
        <h1 className="mt-6 text-2xl font-semibold text-white">无权访问</h1>
        <p className="mt-3 text-sm text-slate-400">当前账号没有可用的管理能力。</p>
        <Button className="mt-6" variant="secondary" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => window.history.back()}>返回</Button>
      </section>
    )
  }

  const context = { userId: user.id, workspaceId: bootstrap.workspace.id }
  return (
    <div className="space-y-6">
      <PageHeader title="管理控制台" subtitle="模块按服务端 capability 独立开放；未支持能力不在界面中展示。" />
      <div role="tablist" aria-label="管理模块" className="flex gap-2 overflow-x-auto border-b border-white/[0.06] pb-3">
        {SECTIONS.filter((item) => allowed.includes(item.id)).map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={section === item.id}
            onClick={() => setSection(item.id)}
            className={`shrink-0 rounded-[10px] px-4 py-2 text-sm font-medium transition-colors ${section === item.id ? 'bg-mint-400/15 text-mint-300' : 'text-slate-400 hover:bg-white/[0.05] hover:text-slate-200'}`}
          >{item.label}</button>
        ))}
      </div>
      <div role="tabpanel">
        {section === 'users' ? <UsersModule context={context} /> : null}
        {section === 'agents' ? <AgentModule context={context} /> : null}
        {section === 'providers' ? (
          <DiagnosticsModule
            context={context}
            canViewProviders={hasCapability(capabilities, ADMIN_CAPABILITIES.providers)}
            canSyncO2={hasCapability(capabilities, ADMIN_CAPABILITIES.o2)}
          />
        ) : null}
        {section === 'policies' ? (
          <PolicyModule
            context={context}
            canViewPermissions={hasCapability(capabilities, ADMIN_CAPABILITIES.permissionPolicies)}
            canViewRisk={hasCapability(capabilities, ADMIN_CAPABILITIES.riskPolicies)}
          />
        ) : null}
        {section === 'audit' ? <AuditModule context={context} /> : null}
      </div>
    </div>
  )
}
