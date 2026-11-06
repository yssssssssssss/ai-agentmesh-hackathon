import { Laptop, RefreshCw, ShieldCheck } from 'lucide-react'

import { ApiError } from '../../api/client'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { useRunnerAdmin } from './api'

interface RunnerModuleProps {
  context: { userId: string; workspaceId: string }
  enrollmentCode: string | null
}

function message(error: unknown) {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : '请求失败'
}

function timestamp(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '尚未连接'
}

export function RunnerModule({ context, enrollmentCode }: RunnerModuleProps) {
  const resource = useRunnerAdmin(context, enrollmentCode)
  const enrollment = resource.enrollment.data
  const canApprove = enrollment?.status === 'pending'
  const revoke = (runnerId?: string) => {
    if (runnerId) resource.revoke.mutate(runnerId)
  }

  return (
    <div className="space-y-6">
      {enrollmentCode ? (
        <Card padding="lg">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-soft bg-mint-400/10 text-mint-300">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold text-white">确认本地 Runner</h2>
              <p className="mt-1 text-sm text-slate-400">仅确认你正在安装的设备。确认后，终端会收到独立的 Runner 凭据。</p>
            </div>
          </div>

          {resource.enrollment.isLoading ? <p className="mt-5 text-sm text-slate-400">正在读取设备申请…</p> : null}
          {resource.enrollment.isError ? <p role="alert" className="mt-5 text-sm text-rose">{message(resource.enrollment.error)}</p> : null}
          {enrollment ? (
            <div className="mt-5 rounded-soft border border-white/[0.06] bg-surface-2 p-4">
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <div><dt className="text-xs text-slate-400">设备</dt><dd className="mt-1 font-medium text-slate-100">{enrollment.device_name}</dd></div>
                <div><dt className="text-xs text-slate-400">确认码</dt><dd className="mt-1 font-mono font-medium text-slate-100">{enrollmentCode}</dd></div>
                <div><dt className="text-xs text-slate-400">系统</dt><dd className="mt-1 text-slate-200">{enrollment.capabilities.platform} / {enrollment.capabilities.architecture}</dd></div>
                <div><dt className="text-xs text-slate-400">Runner 版本</dt><dd className="mt-1 text-slate-200">{enrollment.capabilities.runner_version}</dd></div>
              </dl>
              <div className="mt-4 flex items-center justify-between gap-3">
                <Badge tone={enrollment.status === 'pending' ? 'remind' : 'mint'}>{enrollment.status}</Badge>
                {canApprove ? (
                  <Button loading={resource.approve.isPending} onClick={() => resource.approve.mutate()}>
                    确认连接此设备
                  </Button>
                ) : (
                  <p role="status" className="text-sm text-mint-300">设备已确认，可返回终端继续。</p>
                )}
              </div>
              {resource.approve.isError ? <p role="alert" className="mt-3 text-sm text-rose">{message(resource.approve.error)}</p> : null}
            </div>
          ) : null}
        </Card>
      ) : null}

      <Card padding="lg">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <Laptop className="mt-0.5 h-5 w-5 text-mint-300" />
            <div>
              <h2 className="text-lg font-semibold text-white">本地 Runner</h2>
              <p className="mt-1 text-sm text-slate-400">查看当前账号已注册的执行设备，并撤销不再使用的设备。</p>
            </div>
          </div>
          <Button
            size="sm"
            variant="secondary"
            icon={<RefreshCw className="h-4 w-4" />}
            loading={resource.runners.isFetching}
            onClick={() => void resource.runners.refetch()}
          >
            刷新
          </Button>
        </div>

        {resource.runners.isLoading ? <p className="mt-5 text-sm text-slate-400">正在加载 Runner…</p> : null}
        {resource.runners.isError ? <p role="alert" className="mt-5 text-sm text-rose">{message(resource.runners.error)}</p> : null}
        {resource.runners.data?.items.length === 0 ? (
          <p className="mt-5 text-sm text-slate-400">尚未注册 Runner。请在终端运行 `agentmesh setup --server &lt;地址&gt;`。</p>
        ) : null}
        {resource.runners.data && resource.runners.data.items.length > 0 ? (
          <div className="mt-5 space-y-3">
            {resource.runners.data.items.map((runner) => (
              <article key={runner.id ?? runner.name} className="rounded-soft border border-white/[0.06] bg-surface-2 p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-slate-100">{runner.name}</h3>
                      <Badge tone={runner.status === 'active' ? 'mint' : 'neutral'}>{runner.status}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-slate-400">
                      {runner.capabilities.platform} / {runner.capabilities.architecture} · {runner.capabilities.runner_version}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">最后连接：{timestamp(runner.last_seen_at)}</p>
                  </div>
                  {runner.status === 'active' && runner.id ? (
                    <Button
                      size="sm"
                      variant="danger"
                      loading={resource.revoke.isPending && resource.revoke.variables === runner.id}
                      onClick={() => revoke(runner.id)}
                    >
                      撤销
                    </Button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : null}
        {resource.revoke.isError ? <p role="alert" className="mt-3 text-sm text-rose">{message(resource.revoke.error)}</p> : null}
      </Card>
    </div>
  )
}
