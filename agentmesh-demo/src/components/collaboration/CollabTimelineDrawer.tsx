import { useEffect, useMemo, useState } from 'react'
import { Check, LockKeyhole, MessageSquareReply, Network, Send, ShieldCheck, UnlockKeyhole } from 'lucide-react'
import type { components } from '../../api/generated/schema'

import type {
  CollaborationRecordView,
  CollaborationTimelineItem,
} from '../../features/collaboration/presenter'
import type { CollaborationContext } from '../../features/collaboration/queries'
import {
  collaborationErrorMessage,
  useCollaborationMutations,
  useTaskDetail,
} from '../../features/collaboration/queries'
import { Avatar } from '../ui/Avatar'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'
import { Drawer } from '../ui/Drawer'
import { SourceList } from '../ui/SourceList'

type Agent = components['schemas']['Agent']

interface CollabTimelineDrawerProps {
  open: boolean
  taskId: string | null
  context: CollaborationContext
  currentAgentId: string
  agents: Agent[]
  record?: CollaborationRecordView
  timeline: CollaborationTimelineItem[]
  onClose: () => void
}

const TIMELINE_TONES = ['mint', 'knowledge', 'collab', 'remind'] as const

export function CollabTimelineDrawer({
  open,
  taskId,
  context,
  currentAgentId,
  agents,
  record,
  timeline,
  onClose,
}: CollabTimelineDrawerProps) {
  const detail = useTaskDetail(context, open ? taskId : null)
  const mutations = useCollaborationMutations(context)
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
      title={record?.title.value ?? card?.task.title ?? '协作任务详情'}
      subtitle="这次协作是如何发生的"
      width={620}
    >
      {detail.isLoading ? <p className="text-sm text-slate-400">正在读取协作详情…</p> : null}
      {detail.error ? <p role="alert" className="text-sm text-rose">{collaborationErrorMessage(detail.error)}</p> : null}
      {error ? <p role="alert" className="mb-4 rounded-soft border border-rose/25 bg-rose/10 p-3 text-sm text-rose">{error}</p> : null}
      {message ? <p role="status" className="mb-4 rounded-soft border border-mint-400/20 bg-mint-400/[0.06] p-3 text-sm text-mint-300">{message}</p> : null}

      {card || record ? (
        <div className="space-y-6">
          <section className="rounded-soft border border-white/[0.06] bg-surface-1 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={card?.task.status === 'completed' ? 'mint' : 'knowledge'}>
                {card?.task.status === 'completed' ? '已完成' : '协作中'}
              </Badge>
              {card?.active_lock ? <Badge tone="remind">执行锁：{card.active_lock.owner_label}</Badge> : null}
              <DataSourceBadge source="T" />
            </div>
            <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
              <div><dt className="text-xs text-slate-400">当前负责人</dt><dd className="mt-1 text-slate-200">{card?.owner ?? record?.owner.value ?? '尚未分配'}</dd></div>
              <div><dt className="text-xs text-slate-400">完成条件</dt><dd className="mt-1 text-slate-200">{card?.done_when ?? record?.doneWhen.value ?? '服务端暂未设置'}</dd></div>
            </dl>
            <details className="mt-4 border-t border-white/[0.06] pt-3 text-xs">
              <summary className="min-h-8 cursor-pointer py-1.5 text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">任务技术详情</summary>
              <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-5 text-slate-400">{JSON.stringify({
                task: card?.task ?? record?.technical.value.task,
                stage: card?.stage ?? record?.technical.value.stage,
                targetPostId,
                allowedActions: actions,
                activeLock: card?.active_lock ?? record?.lock.value,
              }, null, 2)}</pre>
            </details>
          </section>

          <section>
            <h3 className="mb-4 text-sm font-semibold text-slate-200">协作时间线</h3>
            {timeline.length > 0 ? (
              <ol className="relative space-y-5">
                {timeline.map((item, index) => {
                  const last = index === timeline.length - 1
                  const tone = TIMELINE_TONES[index % TIMELINE_TONES.length]
                  return (
                    <li key={item.id.value} className="relative flex gap-3.5">
                      {!last ? <span className="absolute left-[15px] top-9 h-[calc(100%+4px)] w-px bg-white/[0.09]" /> : null}
                      <Avatar name={item.actor.value} size="sm" tone={tone} className="relative z-10 h-8 w-8 shrink-0 text-[11px]" />
                      <div className="min-w-0 flex-1 pb-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-[13.5px] font-semibold text-slate-100">{item.action.value}</h4>
                          <DataSourceBadge source={item.narrative.source} />
                          <span className="text-[11px] text-slate-400">{item.actor.value}</span>
                        </div>
                        <p className="mt-1 text-[12.5px] leading-relaxed text-slate-400">{item.narrative.value}</p>
                        {item.technical.value.sources?.length ? <SourceList sources={item.technical.value.sources} /> : null}
                        <details className="mt-2 text-xs">
                          <summary className="min-h-8 cursor-pointer py-1.5 text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">技术详情</summary>
                          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-soft bg-surface-1 p-3 font-mono text-[11px] leading-5 text-slate-400">{JSON.stringify(item.technical.value, null, 2)}</pre>
                        </details>
                      </div>
                    </li>
                  )
                })}
              </ol>
            ) : (
              <div className="rounded-soft border border-white/[0.06] bg-surface-1 p-5 text-sm text-slate-400">当前任务尚无可见协作记录。</div>
            )}
          </section>

          <div className="flex items-start gap-2 border-t border-white/[0.06] pt-4 text-[11.5px] leading-relaxed text-slate-400">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            协作内容仅来自当前账号可见的 Task 与 Blackboard Post，来源和操作权限由服务端返回。
          </div>

          {targetPostId && actions.includes('reply') ? (
            <section className="rounded-soft border border-white/[0.06] p-4">
              <label htmlFor="collaboration-reply" className="text-sm font-semibold text-slate-200">回复任务</label>
              <textarea
                id="collaboration-reply"
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                rows={3}
                className="mt-2 w-full rounded-soft border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-200 outline-none focus:border-collab/50 focus-visible:ring-2 focus-visible:ring-mint-400/50"
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
            <section className="rounded-soft border border-white/[0.06] p-4">
              <h3 className="text-sm font-semibold text-slate-200">任务交接</h3>
              <div className="mt-3 grid gap-3">
                <label className="text-xs text-slate-400">下一位负责人
                  <select value={nextOwner} onChange={(event) => setNextOwner(event.target.value)} className="mt-1 block w-full rounded-soft border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">
                    <option value="">请选择 Agent</option>
                    {eligibleAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
                  </select>
                </label>
                <label className="text-xs text-slate-400">当前结果
                  <input value={handoffResult} onChange={(event) => setHandoffResult(event.target.value)} className="mt-1 block w-full rounded-soft border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50" />
                </label>
                <label className="text-xs text-slate-400">完成条件
                  <input value={doneWhen} onChange={(event) => setDoneWhen(event.target.value)} className="mt-1 block w-full rounded-soft border border-white/[0.08] bg-surface-1 px-3 py-2 text-sm text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50" />
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
                      goal: card?.task.title ?? record?.title.value ?? '',
                      current_result: handoffResult.trim(),
                      done_when: doneWhen.trim(),
                      next_owner_agent_id: nextOwner,
                    },
                  }),
                  '任务已交接，负责人和时间线已刷新。',
                )}
              >
                确认交接
              </Button>
            </section>
          ) : null}

          {targetPostId ? (
            <div className="flex flex-wrap items-center gap-2">
              {actions.includes('lock') ? <Button size="sm" disabled={!currentAgentId} loading={mutations.lock.isPending} icon={<LockKeyhole className="h-4 w-4" />} onClick={() => void run(() => mutations.lock.mutateAsync({ postId: targetPostId, ownerAgentId: currentAgentId }), '个人数字分身已取得执行锁。')}>锁定给我的数字分身</Button> : null}
              {actions.includes('unlock') ? <Button size="sm" variant="secondary" loading={mutations.unlock.isPending} icon={<UnlockKeyhole className="h-4 w-4" />} onClick={() => void run(() => mutations.unlock.mutateAsync(targetPostId), '执行锁已释放。')}>释放执行锁</Button> : null}
              {actions.includes('read') ? <Button size="sm" variant="ghost" loading={mutations.markRead.isPending} icon={<Check className="h-4 w-4" />} onClick={() => void run(() => mutations.markRead.mutateAsync(targetPostId), '已标记为已读。')}>标记已读</Button> : null}
              {actions.includes('reply') ? <span className="inline-flex items-center gap-1 text-xs text-slate-400"><MessageSquareReply className="h-3.5 w-3.5" />可回复</span> : null}
              {actions.length === 0 ? <Badge tone="neutral">当前任务只读</Badge> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </Drawer>
  )
}
