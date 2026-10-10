import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { connectorsApi, type ConnectorControlRequest, type ConnectorStatus } from '../../features/knowledge/connectorsApi'
import { knowledgeKeys } from '../../features/knowledge/queries'
import { Button } from '../ui/Button'

const NAMES: Record<ConnectorStatus['provider'], string> = {
  repo_docs: '项目资料目录', github_issues: 'GitHub 问题',
}

function failureMessage(code?: string | null): string {
  if (code === 'connector_access_unavailable' || code === 'connector_root_unavailable') {
    return '来源暂时无法访问，已停止引用旧资料。请联系项目管理员检查来源。'
  }
  if (code === 'connector_rate_limited') return '来源请求受到限流，请等待允许读取的时间。最近成功读取的资料已保留。'
  return '同步失败，保留最近成功读取的资料。可以重试。'
}

export function SourceSyncRow({ item, busy, onSync, controlBusy = false, reading = false, autoAvailable = false, onControl }: {
  item: ConnectorStatus; busy: boolean; onSync: (mode: 'incremental' | 'full') => void
  controlBusy?: boolean; reading?: boolean; autoAvailable?: boolean
  onControl?: (action: ConnectorControlRequest['action']) => void
}) {
  const cursor = item.cursor
  const inProgress = Boolean(cursor?.scan_started_at && cursor.status !== 'idle')
  const disabled = cursor?.enabled === false || cursor?.status === 'disabled'
  const activeRead = cursor?.status === 'reading'
  const waiting = Boolean(cursor?.next_allowed_at && new Date(cursor.next_allowed_at).getTime() > Date.now())
  const syncable = item.configured && !item.configuration_changed && !disabled
  const label = !cursor ? '尚未同步' : disabled ? '已禁用' : cursor.status === 'cancelled' ? '已取消'
    : activeRead ? '正在读取' : cursor.status === 'failed' ? '同步失败' : cursor.status === 'syncing' ? '等待继续'
      : cursor.completed_at ? '本轮已完成' : '等待同步'
  const action = cursor?.status === 'failed' ? '重试同步' : inProgress ? '继续同步' : '同步更新'
  return <li className="space-y-2 rounded-control border border-white/10 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-sm text-slate-200">{NAMES[item.provider]}</span>
      <span className="text-xs text-slate-400">{label}</span>
    </div>
    {item.provider === 'github_issues' ? <p className="break-all text-xs text-slate-400">{item.namespace}</p> : null}
    <p className="text-xs text-slate-400">{cursor?.last_successful_at
      ? `最近成功读取：${new Date(cursor.last_successful_at).toLocaleString('zh-CN')}` : '尚未成功读取资料。'}</p>
    {cursor?.watermark_at ? <p className="text-xs text-slate-400">最近一轮读取起点：{new Date(cursor.watermark_at).toLocaleString('zh-CN')}</p> : null}
    {cursor?.auto_sync_enabled ? <p className="text-xs text-slate-400">自动同步：{autoAvailable ? '已开启' : '等待服务恢复'}，每 {cursor.interval_seconds / 60} 分钟读取一轮。
      {cursor.next_sync_at ? ` 下次读取：${new Date(cursor.next_sync_at).toLocaleString('zh-CN')}` : ''}</p> : null}
    {waiting && cursor?.next_allowed_at ? <p className="text-xs text-slate-400">允许再次读取：{new Date(cursor.next_allowed_at).toLocaleString('zh-CN')}</p> : null}
    {cursor?.status === 'failed' && autoAvailable && !cursor.auto_sync_enabled && cursor.consecutive_failures > 0
      ? <p className="text-xs text-slate-400">请检查来源后重试或重新开启自动同步。</p> : null}
    {cursor?.status === 'failed' ? <p role="status" className="text-xs text-rose">{failureMessage(cursor.last_error_code)}</p> : null}
    {!item.configured ? <p className="text-xs text-slate-400">来源配置已移除，旧资料已停止引用。</p> : null}
    {item.configuration_changed ? <p className="text-xs text-slate-400">来源配置已变化，旧资料已停止引用。请重置进度后完整读取。</p> : null}
    {disabled ? <p className="text-xs text-slate-400">已停止同步和旧资料引用。恢复需重置进度并重新读取。</p> : null}
    <div className="flex flex-wrap gap-2">
      {syncable ? <Button size="sm" disabled={busy || controlBusy || activeRead || waiting}
        onClick={() => onSync('incremental')}>{action}</Button> : null}
      {syncable && !inProgress && cursor ? <Button size="sm" variant="secondary" disabled={busy || controlBusy || waiting}
        onClick={() => onSync('full')}>完整复核</Button> : null}
      {cursor && onControl ? <>
        {cursor.auto_sync_enabled ? <Button size="sm" variant="secondary" disabled={controlBusy}
          onClick={() => onControl('pause_auto')}>暂停自动同步</Button>
          : syncable && autoAvailable ? <Button size="sm" variant="secondary" disabled={busy || controlBusy || activeRead}
            onClick={() => onControl('enable_auto')}>开启自动同步（每15分钟）</Button> : null}
        {item.configured ? <Button size="sm" variant="secondary" disabled={busy || controlBusy || activeRead}
          onClick={() => onControl('reset')}>{disabled ? '恢复并重置' : '重置进度'}</Button> : null}
        {!disabled ? <Button size="sm" variant="ghost" disabled={controlBusy}
          onClick={() => onControl('disable')}>禁用同步</Button> : null}
        {!disabled && (inProgress || reading) ? <Button size="sm" variant="ghost" disabled={controlBusy}
          onClick={() => onControl('cancel')}>取消本轮</Button> : null}
      </> : null}
    </div>
  </li>
}

export function SourceSyncPanel({ userId, workspaceId, projectId }: {
  userId: string; workspaceId: string; projectId: string
}) {
  const client = useQueryClient()
  const [message, setMessage] = useState('')
  const [polling, setPolling] = useState(false)
  const previousSuccess = useRef<string>()
  const key = ['project-connectors', workspaceId, userId, projectId]
  const status = useQuery({ queryKey: key, queryFn: () => connectorsApi.status(projectId), retry: false,
    enabled: Boolean(userId && workspaceId && projectId), staleTime: 5000,
    refetchInterval: (query) => polling || query.state.data?.items.some((item) => item.cursor?.status === 'reading')
      ? 1000 : query.state.data?.items.some((item) => item.cursor?.auto_sync_enabled) ? 15000 : false })
  const success = status.data?.items.map((item) => `${item.namespace}:${item.cursor?.last_successful_at ?? ''}`).join('|')
  useEffect(() => {
    if (success !== undefined && previousSuccess.current !== undefined && previousSuccess.current !== success) {
      void client.invalidateQueries({ queryKey: knowledgeKeys.documentsRoot })
      void client.invalidateQueries({ queryKey: knowledgeKeys.memoryRoot })
    }
    previousSuccess.current = success
  }, [client, success])
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: key }),
    client.invalidateQueries({ queryKey: knowledgeKeys.documentsRoot }),
    client.invalidateQueries({ queryKey: knowledgeKeys.memoryRoot }),
    client.invalidateQueries({ queryKey: ['memory-learning', userId] }),
  ])
  const sync = useMutation({ mutationFn: ({ item, mode }: {
    item: ConnectorStatus; mode: 'incremental' | 'full'
  }) => connectorsApi.sync(projectId, item.provider, { expected_version: item.cursor?.version ?? 0, mode }),
  onMutate: () => { setPolling(true) },
  onSettled: () => { setPolling(false) },
  onSuccess: async (cursor) => {
    setMessage(cursor.next_position ? '本页已读取，请继续同步后续资料。' : '本轮同步已完成，资料可在下方列表查看。')
    await refresh()
  }, onError: async (error) => {
    setMessage(error instanceof ApiError && error.status === 409
      ? '读取结果未提交，请查看最新来源状态。' : '本次同步未完成，请查看来源状态后重试。')
    await refresh()
  } })
  const control = useMutation({ mutationFn: ({ item, action }: {
    item: ConnectorStatus; action: ConnectorControlRequest['action']
  }) => {
    if (!item.cursor) throw new Error('connector_required')
    return connectorsApi.control(projectId, item.cursor.id, { expected_version: item.cursor.version, action,
      interval_seconds: action === 'enable_auto' ? 900 : item.cursor.interval_seconds })
  }, onSuccess: async (_, variables) => {
    setMessage(variables.action === 'disable' ? '已禁用同步，旧来源资料已停止引用。'
      : variables.action === 'reset' ? '进度已重置，请同步以完整读取当前来源。'
        : variables.action === 'enable_auto' ? '已开启自动同步，后台将继续读取并定期更新。'
          : variables.action === 'pause_auto' ? '自动同步已暂停，最近成功读取的资料已保留。'
        : '本轮已取消，正在读取的旧结果将不再提交。')
    await refresh()
  }, onError: async () => {
    setMessage('操作未完成，进度或访问权限可能已变化，请查看最新状态后操作。')
    await refresh()
  } })
  return <section aria-label="项目来源同步" className="space-y-3 rounded-soft border border-white/10 p-4">
    <h2 className="text-sm font-semibold text-slate-100">项目来源同步</h2>
    <p className="text-xs text-slate-400">读取已配置的项目资料和问题状态，每次处理一页。同步资料进入本人资料列表，事实学习和团队共享需确认。</p>
    {status.data && !status.data.auto_sync_available
      ? <p className="text-xs text-slate-400">自动同步服务未启用，可继续手动同步。</p> : null}
    {message ? <p role="status" className="text-xs text-slate-300">{message}</p> : null}
    {status.isLoading ? <p className="text-xs text-slate-400">正在读取来源状态…</p> : null}
    {status.error ? <p className="text-xs text-slate-400">当前项目未配置或无法访问同步来源，请联系项目管理员。</p>
      : <ul className="space-y-2">{(status.data?.items ?? []).map((item) => <SourceSyncRow
        key={`${item.provider}:${item.namespace}`} item={item} busy={sync.isPending || status.isFetching}
        autoAvailable={status.data?.auto_sync_available}
        reading={sync.isPending && sync.variables?.item.cursor?.id === item.cursor?.id}
        controlBusy={control.isPending} onControl={(action) => { setMessage(''); control.mutate({ item, action }) }}
        onSync={(mode) => { setMessage(''); sync.mutate({ item, mode }) }} />)}</ul>}
    {!status.isLoading && !status.error && !status.data?.items.length
      ? <p className="text-xs text-slate-400">当前项目尚未配置同步来源。</p> : null}
  </section>
}
