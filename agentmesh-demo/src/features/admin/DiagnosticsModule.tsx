import { RefreshCw, ServerCog } from 'lucide-react'

import { ApiError } from '../../api/client'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { useProviderAdmin } from './api'

interface DiagnosticsModuleProps {
  context: { userId: string; workspaceId: string }
  canViewProviders: boolean
  canSyncO2: boolean
}

function message(error: unknown) {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : '请求失败'
}

export function DiagnosticsModule({ context, canViewProviders, canSyncO2 }: DiagnosticsModuleProps) {
  const resource = useProviderAdmin(context, canViewProviders, canSyncO2)

  return (
    <div className="space-y-6">
      {canViewProviders ? (
        <Card padding="lg">
          <div className="flex items-center gap-3"><ServerCog className="h-5 w-5 text-mint-300" /><div><h2 className="text-lg font-semibold text-white">Provider diagnostics</h2><p className="mt-1 text-sm text-slate-500">配置、就绪、运行模式与最近错误。</p></div></div>
          {resource.providers.isLoading ? <p className="mt-5 text-sm text-slate-500">正在检查 Provider…</p> : null}
          {resource.providers.isError ? <p role="alert" className="mt-5 text-sm text-rose">{message(resource.providers.error)}</p> : null}
          {resource.providers.data && resource.providers.data.providers.length === 0 ? <p className="mt-5 text-sm text-slate-500">没有 Provider 状态。</p> : null}
          {resource.providers.data && resource.providers.data.providers.length > 0 ? (
            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-slate-500"><tr><th className="pb-3 font-medium">Provider</th><th className="pb-3 font-medium">配置</th><th className="pb-3 font-medium">就绪</th><th className="pb-3 font-medium">模式</th><th className="pb-3 font-medium">最近错误</th></tr></thead>
                <tbody className="divide-y divide-white/[0.06]">
                  {resource.providers.data.providers.map((provider) => (
                    <tr key={provider.name}>
                      <td className="py-3 pr-4 font-medium text-slate-100">{provider.name}</td>
                      <td className="py-3 pr-4"><Badge tone={provider.configured ? 'mint' : 'neutral'}>{provider.configured ? 'configured' : 'not configured'}</Badge></td>
                      <td className="py-3 pr-4"><Badge tone={provider.ready ? 'mint' : 'remind'}>{provider.ready ? 'ready' : 'unavailable'}</Badge></td>
                      <td className="py-3 pr-4 text-slate-300">{provider.mode}</td>
                      <td className="py-3 text-slate-400">{provider.last_error ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </Card>
      ) : null}
      {canSyncO2 ? (
        <Card padding="lg">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div><h2 className="text-lg font-semibold text-white">O2 registry</h2><p className="mt-1 text-sm text-slate-500">安装、登录与工具注册表同步状态。</p></div>
            <Button icon={<RefreshCw className="h-4 w-4" />} loading={resource.sync.isPending} onClick={() => resource.sync.mutate()}>同步 O2 工具</Button>
          </div>
          {resource.o2.isLoading ? <p className="mt-5 text-sm text-slate-500">正在检查 O2…</p> : null}
          {resource.o2.isError ? <p role="alert" className="mt-5 text-sm text-rose">{message(resource.o2.error)}</p> : null}
          {resource.o2.data ? (
            <dl className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="rounded-[10px] bg-surface-2 p-4"><dt className="text-xs text-slate-500">安装</dt><dd className="mt-1 text-sm font-medium text-slate-100">{resource.o2.data.installed ? '已安装' : '未安装'}</dd></div>
              <div className="rounded-[10px] bg-surface-2 p-4"><dt className="text-xs text-slate-500">版本</dt><dd className="mt-1 text-sm font-medium text-slate-100">{resource.o2.data.version ?? '未知'}</dd></div>
              <div className="rounded-[10px] bg-surface-2 p-4"><dt className="text-xs text-slate-500">登录</dt><dd className="mt-1 text-sm font-medium text-slate-100">{resource.o2.data.login.logged_in ? '已登录' : '未登录'}</dd></div>
            </dl>
          ) : null}
          {resource.sync.isSuccess ? <p role="status" className="mt-4 text-sm text-mint-300">同步完成，共 {resource.sync.data.count} 个工具。</p> : null}
          {resource.sync.isError ? <p role="alert" className="mt-4 text-sm text-rose">{message(resource.sync.error)}</p> : null}
        </Card>
      ) : null}
    </div>
  )
}
