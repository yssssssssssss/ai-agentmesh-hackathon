import { useEffect, useMemo, useState } from 'react'
import { Check, LockKeyhole, MessageSquareReply, Network, Send, UnlockKeyhole } from 'lucide-react'
import type { components } from '../../api/generated/schema'

import type { CollaborationContext } from '../../features/collaboration/queries'
import {
  collaborationErrorMessage,
  useCollaborationMutations,
  useTaskDetail,
} from '../../features/collaboration/queries'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Drawer } from '../ui/Drawer'
import { SourceList } from '../ui/SourceList'

type Agent = components['schemas']['Agent']

interface CollabTimelineDrawerProps {
  open: boolean
  taskId: string | null
  context: CollaborationContext
  currentAgentId: string
  agents: Agent[]
  onClose: () => void
}

export function CollabTimelineDrawer({
  open,
  taskId,
  context,
  currentAgentId,
  agents,
  onClose,
}: CollabTimelineDrawerProps) {
  const detail = useTaskDetail(context, open ? taskId : null)
  const mutations = useCollaborationMutations()
  const [reply, setReply] = useState('')
  const [nextOwner, setNextOwner] = useState('')
  const [handoffResult, setHandoffResult] = useState('')
  const [doneWhen, setDoneWhen] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const eligibleAgents = useMemo(
    () => agents.filter((agent) => agent.workspace_id === context.workspaceId && agent.status === 'online'),
    [agents, context.workspaceId],
  )

  useEffect(() => {
    if (!open) return
    setReply('')
    setHandoffResult('')
    setDoneWhen('')
    setError(null)
    setMessage(null)
    setNextOwner('')
  }, [open, taskId])

  useEffect(() => {
    if (!open || nextOwner) return
    setNextOwner(eligibleAgents.find((agent) => agent.id !== currentAgentId)?.id ?? '')
  }, [currentAgentId, eligibleAgents, nextOwner, open])

  const card = detail.data?.task_card
  const targetPostId = card?.target_post_id ?? null
  const actions = card?.allowed_actions ?? []
  const busy = Object.values(mutations).some((mutation) => mutation.isPending)

  const run = async (action: () => Promise<unknown>, success: string) => {
    setError(null)
    setMessage(null)
    try {
      await action()
      setMessage(success)
      return true
    } catch (actionError) {
      setError(collaborationErrorMessage(actionError))
      return false
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      icon={<Network className="h-5 w-5" />}
      title={card?.task.title ?? '协作任务详情'}
      subtitle="服务端过滤的任务卡、时间线和允许操作"
      width={600}
    >
      {detail.isLoading ? <p className="text-sm text-slate-400">正在读取任务详情…</p> : null}
      {detail.error ? <p role="alert" className="text-sm text-rose">{collaborationErrorMessage(detail.error)}</p> : null}
      {error ? <p role="alert" className="mb-4 rounded-[10px] border border-rose/25 bg-rose/10 p-3 text-sm text-rose">{error}</p> : null}
      {message ? <p role="status" className="mb-4 rounded-[10px] border border-mint-400/20 bg-mint-400/[0.06] p-3 text-sm text-mint-300">{message}</p> : null}

      {card ? (
        <div className="space-y-6">
          <section className="rounded-[12px] border border-white/[0.06] bg-surface-1 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="collab">任务阶段：{card.stage ?? card.task.collaboration_stage}</Badge>
              <Badge tone={card.task.status === 'completed' ? 'mint' : 'knowledge'}>{card.task.status}</Badge>
              {card.active_lock ? <Badge tone="remind">执行锁：{card.active_lock.owner_label}</Badge> : null}
            </div>
            <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
              <div><dt className="text-xs text-slate-500">当前 owner</dt><dd className="mt-1 text-slate-200">{card.owner ?? '未分配'}</dd></div>
              <div><dt className="text-xs text-slate-500">完成条件</dt><dd className="mt-1 text-slate-200">{card.done_when ?? '未设置'}</dd></div>
            </dl>
          </section>

          <section>
            <h3 className="mb-3 text-sm font-semibold text-slate-200">协作时间线</h3>
            <ol className="space-y-3">
              {detail.data?.posts.map((post) => (
                <li key={post.id} className="rounded-[12px] border border-white/[0.06] bg-surface-1 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-slate-100">{post.title}</span>
                    <Badge tone="neutral">{post.post_type}</Badge>
                    <span className="text-xs text-slate-600">{post.actor}</span>
                  </div>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-400">{post.content}</p>
                  <SourceList sources={post.sources} />
                </li>
              ))}
            </ol>
          </section>

          {targetPostId && actions.includes('reply') ? (
            <section className="rounded-[12px] border border-white/[0.06] p-4">
              <label htmlFor="collaboration-reply" className="text-sm font-semibold text-slate-200">回复任务</label>
              <textarea
                id="collaboration-reply"
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                rows={3}
                className="mt-2 w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-200 outline-none focus:border-collab/50"
                placeholder="补充证据、决策或进度"
              />
              <Button
                className="mt-2"
                size="sm"
                loading={mutations.reply.isPending}
                disabled={!reply.trim()}
                icon={<Send className="h-4 w-4" />}
                onClick={() => void run(
                  () => mutations.reply.mutateAsync({ postId: targetPostId, payload: { post_type: 'evidence', title: '协作回复', content: reply.trim() } }),
                  '回复已保存到任务时间线。',
                ).then((succeeded) => {
                  if (succeeded) setReply('')
                })}
              >
                发送回复
              </Button>
            </section>
          ) : null}

          {targetPostId && actions.includes('handoff') ? (
            <section className="rounded-[12px] border border-white/[0.06] p-4">
              <h3 className="text-sm font-semibold text-slate-200">任务交接</h3>
              <div className="mt-3 grid gap-3">
                <label className="text-xs text-slate-400">下一位 owner
                  <select value={nextOwner} onChange={(event) => setNextOwner(event.target.value)} className="mt-1 block w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-200">
                    <option value="">请选择 Agent</option>
                    {eligibleAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
                  </select>
                </label>
                <label className="text-xs text-slate-400">当前结果
                  <input value={handoffResult} onChange={(event) => setHandoffResult(event.target.value)} className="mt-1 block w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-200" />
                </label>
                <label className="text-xs text-slate-400">完成条件
                  <input value={doneWhen} onChange={(event) => setDoneWhen(event.target.value)} className="mt-1 block w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-200" />
                </label>
              </div>
              <Button
                className="mt-3"
                size="sm"
                variant="secondary"
                disabled={busy || !nextOwner || !handoffResult.trim() || !doneWhen.trim()}
                onClick={() => void run(
                  () => mutations.handoff.mutateAsync({
                    postId: targetPostId,
                    payload: {
                      goal: card.task.title,
                      current_result: handoffResult.trim(),
                      done_when: doneWhen.trim(),
                      next_owner_agent_id: nextOwner,
                    },
                  }),
                  '任务已交接，owner 和时间线已刷新。',
                )}
              >
                确认交接
              </Button>
            </section>
          ) : null}

          {targetPostId ? (
            <div className="flex flex-wrap gap-2">
              {actions.includes('lock') ? <Button size="sm" loading={mutations.lock.isPending} icon={<LockKeyhole className="h-4 w-4" />} onClick={() => void run(() => mutations.lock.mutateAsync({ postId: targetPostId, ownerAgentId: currentAgentId }), '个人数字分身已取得执行锁。')}>锁定给我的数字分身</Button> : null}
              {actions.includes('unlock') ? <Button size="sm" variant="secondary" loading={mutations.unlock.isPending} icon={<UnlockKeyhole className="h-4 w-4" />} onClick={() => void run(() => mutations.unlock.mutateAsync(targetPostId), '执行锁已释放。')}>释放执行锁</Button> : null}
              {actions.includes('read') ? <Button size="sm" variant="ghost" loading={mutations.markRead.isPending} icon={<Check className="h-4 w-4" />} onClick={() => void run(() => mutations.markRead.mutateAsync(targetPostId), '已标记为已读。')}>标记已读</Button> : null}
              {actions.includes('reply') ? <span className="inline-flex items-center gap-1 text-xs text-slate-600"><MessageSquareReply className="h-3.5 w-3.5" />可回复</span> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </Drawer>
  )
}
