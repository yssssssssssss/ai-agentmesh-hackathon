import { ShieldCheck } from 'lucide-react'

import { ApiError } from '../../api/client'
import { Badge } from '../../components/ui/Badge'
import { Card } from '../../components/ui/Card'
import { usePolicyAdmin } from './api'

interface PolicyModuleProps {
  context: { userId: string; workspaceId: string }
  canViewPermissions: boolean
  canViewRisk: boolean
}

function message(error: unknown) {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : '请求失败'
}

export function PolicyModule({ context, canViewPermissions, canViewRisk }: PolicyModuleProps) {
  const resource = usePolicyAdmin(context, canViewPermissions, canViewRisk)
  return (
    <div className="space-y-6">
      {canViewPermissions ? (
        <Card padding="lg">
          <div className="flex items-center gap-3"><ShieldCheck className="h-5 w-5 text-mint-300" /><div><h2 className="text-lg font-semibold text-white">权限策略</h2><p className="mt-1 text-sm text-slate-400">只读显示当前角色规则。</p></div></div>
          {resource.permissionPolicies.isLoading ? <p className="mt-5 text-sm text-slate-400">正在加载权限策略…</p> : null}
          {resource.permissionPolicies.isError ? <p role="alert" className="mt-5 text-sm text-rose">{message(resource.permissionPolicies.error)}</p> : null}
          {resource.permissionPolicies.data && resource.permissionPolicies.data.items.length === 0 ? <p className="mt-5 text-sm text-slate-400">没有权限策略。</p> : null}
          {resource.permissionPolicies.data && resource.permissionPolicies.data.items.length > 0 ? (
            <ul className="mt-5 space-y-2">
              {resource.permissionPolicies.data.items.map((rule) => (
                <li key={rule.id} className="flex flex-wrap items-center gap-3 rounded-soft border border-white/[0.06] bg-surface-2 px-4 py-3 text-sm">
                  <span className="font-medium text-slate-100">{rule.action}</span><Badge>{rule.role}</Badge><Badge tone={rule.effect === 'allow' ? 'mint' : 'rose'}>{rule.effect}</Badge><span className="min-w-0 flex-1 text-slate-400">{rule.description || '无说明'}</span><span className="text-xs text-slate-400">{rule.enabled ? 'enabled' : 'disabled'}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </Card>
      ) : null}
      {canViewRisk ? (
        <Card padding="lg">
          <div><h2 className="text-lg font-semibold text-white">风险策略</h2><p className="mt-1 text-sm text-slate-400">只读显示判定信号和决策。</p></div>
          {resource.riskPolicies.isLoading ? <p className="mt-5 text-sm text-slate-400">正在加载风险策略…</p> : null}
          {resource.riskPolicies.isError ? <p role="alert" className="mt-5 text-sm text-rose">{message(resource.riskPolicies.error)}</p> : null}
          {resource.riskPolicies.data && resource.riskPolicies.data.items.length === 0 ? <p className="mt-5 text-sm text-slate-400">没有风险策略。</p> : null}
          {resource.riskPolicies.data && resource.riskPolicies.data.items.length > 0 ? (
            <div className="mt-5 overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-slate-400"><tr><th className="pb-3 font-medium">规则</th><th className="pb-3 font-medium">分类</th><th className="pb-3 font-medium">信号</th><th className="pb-3 font-medium">决策</th></tr></thead><tbody className="divide-y divide-white/[0.06]">{resource.riskPolicies.data.items.map((rule) => <tr key={rule.id}><td className="py-3 pr-4 font-medium text-slate-100">{rule.rule_id}</td><td className="py-3 pr-4 text-slate-400">{rule.category}</td><td className="py-3 pr-4 text-slate-400">{rule.signal}</td><td className="py-3 text-slate-300">{rule.decision}</td></tr>)}</tbody></table></div>
          ) : null}
        </Card>
      ) : null}
    </div>
  )
}
