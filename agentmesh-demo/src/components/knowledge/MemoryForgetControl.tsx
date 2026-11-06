import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../features/auth/AuthProvider'
import { learningApi, learningError } from '../../features/knowledge/learningApi'
import { knowledgeKeys } from '../../features/knowledge/queries'
import { Button } from '../ui/Button'

export interface MemoryLifecycleTarget {
  kind: 'memory' | 'document'
  id: string
  version: number
  ownerUserId: string
}

export function MemoryForgetControl({ target, onForgotten }: { target: MemoryLifecycleTarget; onForgotten?: () => void }) {
  const { user } = useAuth()
  const [confirming, setConfirming] = useState(false)
  const client = useQueryClient()
  const forget = useMutation({ mutationFn: () => learningApi.forget(target.kind, target.id, target.version),
    onSuccess: () => onForgotten?.(),
    onSettled: () => Promise.all([client.invalidateQueries({ queryKey: knowledgeKeys.memoryRoot }),
      client.invalidateQueries({ queryKey: knowledgeKeys.documentsRoot }), client.invalidateQueries({ queryKey: knowledgeKeys.inboxRoot }),
      client.invalidateQueries({ queryKey: ['memory-learning'] }), client.invalidateQueries({ queryKey: ['market'] })]),
  })
  if (user?.id !== target.ownerUserId) return null
  const label = target.kind === 'document' ? '撤回此资料' : '遗忘此私有记忆'
  return <section className="rounded-control border border-rose/20 p-3" aria-label="记忆撤回">
    {!confirming ? <Button variant="danger" size="sm" onClick={() => setConfirming(true)}>{label}</Button>
      : <div className="space-y-2">
        <p className="text-xs text-slate-300">{target.kind === 'document' ? '资料原文及可证明依赖它的私有记忆将停止使用。团队知识保留审核记录并标记来源失效。'
          : '此私有记忆及可证明依赖它的私有摘要将停止使用。'}同时撤回本人的自动协作摘要。已交付内容、审计和备份不在本次删除范围内。</p>
        <div className="flex gap-2">
          <Button variant="danger" size="sm" loading={forget.isPending} disabled={forget.isSuccess} onClick={() => forget.mutate()}>确认{target.kind === 'document' ? '撤回' : '遗忘'}</Button>
          <Button variant="ghost" size="sm" disabled={forget.isPending} onClick={() => setConfirming(false)}>取消</Button>
        </div>
      </div>}
    {forget.error ? <p role="alert" className="mt-2 text-xs text-rose">{learningError(forget.error)}</p> : null}
    {forget.data ? <p role="status" className="mt-2 text-xs text-slate-300">已停止使用，共影响 {forget.data.invalidated_count} 条记录。检索内容已移除，后台继续清理派生索引。</p> : null}
  </section>
}
