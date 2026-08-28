import { ArrowRight, CheckCircle2, LockKeyhole, Network, ShieldCheck } from 'lucide-react'

import type { CollaborationRecordView } from '../../features/collaboration/presenter'
import { Avatar } from '../ui/Avatar'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'

const STATUS_LABELS: Record<string, string> = {
  pending: '等待协作',
  running: '协作中',
  blocked: '等待补充',
  completed: '已完成',
  failed: '协作失败',
}

const RELATIONSHIP_LABELS = {
  owner: '当前负责人',
  upstream: '上游协作方',
  downstream: '下游协作方',
  actor: '内容贡献者',
  handoff: '交接负责人',
} as const

const RELATIONSHIP_TONES = {
  owner: 'mint',
  upstream: 'knowledge',
  downstream: 'collab',
  actor: 'knowledge',
  handoff: 'remind',
} as const

interface MyCollabCardProps {
  record: CollaborationRecordView
  onDetail: () => void
}

export function MyCollabCard({ record, onDetail }: MyCollabCardProps) {
  const participants = record.participants.value.filter(
    (participant, index, items) => items.findIndex((item) => item.name === participant.name) === index,
  )
  const status = record.status.value
  const completed = status === 'completed'

  return (
    <article data-task-id={record.id.value} className="card-base flex min-h-[290px] flex-col p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-slate-400">
            <Network className="h-3.5 w-3.5" />
            协作任务
            <DataSourceBadge source={record.title.source} />
          </div>
          <h3 className="mt-2 text-[17px] font-semibold leading-snug text-white">{record.title.value}</h3>
        </div>
        <Badge tone={completed ? 'mint' : status === 'failed' ? 'rose' : 'knowledge'} dot>
          {STATUS_LABELS[status] ?? status}
        </Badge>
      </div>

      <div className="mt-4 grid gap-3 rounded-soft bg-surface-2 p-4 text-xs sm:grid-cols-2">
        <div>
          <div className="text-slate-400">当前负责人</div>
          <div className="mt-1 font-medium text-slate-200">{record.owner.value ?? '尚未分配'}</div>
        </div>
        <div>
          <div className="text-slate-400">完成条件</div>
          <div className="mt-1 text-slate-300">{record.doneWhen.value ?? '服务端暂未设置'}</div>
        </div>
        {record.lock.value ? (
          <div className="sm:col-span-2">
            <div className="flex items-center gap-1.5 text-remind">
              <LockKeyhole className="h-3.5 w-3.5" />
              执行锁由 {record.lock.value.owner_label} 持有
            </div>
          </div>
        ) : null}
      </div>

      <div className="mt-4">
        <div className="text-[10.5px] font-medium uppercase tracking-wide text-slate-400">本次获得</div>
        {record.contributions.value.length > 0 ? (
          <ul className="mt-2 space-y-2">
            {record.contributions.value.slice(0, 3).map((contribution, index) => (
              <li key={`${contribution.actor}-${contribution.kind}-${index}`} className="flex items-start gap-2 text-[12px] leading-relaxed text-slate-300">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mint-300" />
                <span><span className="text-slate-400">{contribution.actor}：</span>{contribution.detail}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[12px] text-slate-400">任务已建立，等待协作方补充内容。</p>
        )}
      </div>

      <div className="mt-auto pt-5">
        <div className="flex flex-wrap items-end justify-between gap-3 border-t border-white/[0.06] pt-4">
          <details className="group/people relative">
            <summary className="flex min-h-10 cursor-pointer list-none items-center gap-3 rounded-lg pr-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">
              <span className="flex -space-x-2">
                {participants.slice(0, 4).map((participant) => (
                  <Avatar
                    key={participant.name}
                    name={participant.name}
                    size="sm"
                    tone={RELATIONSHIP_TONES[participant.relationship]}
                    className="border-2 border-surface-1 text-[11px]"
                  />
                ))}
              </span>
              <span className="text-[11px] text-slate-400">{participants.length} 位参与者</span>
            </summary>
            <div className="absolute bottom-full left-0 z-20 mb-2 w-[min(320px,80vw)] rounded-soft border border-white/[0.08] bg-surface-2 p-4 shadow-pop">
              <div className="mb-3 text-xs font-medium text-slate-200">本次协作参与者</div>
              <div className="space-y-3">
                {participants.map((participant) => {
                  const contribution = record.contributions.value.find((item) => item.actor === participant.name)
                  return (
                    <div key={participant.name} className="flex gap-3 border-t border-white/[0.05] pt-3 first:border-0 first:pt-0">
                      <Avatar name={participant.name} size="sm" tone={RELATIONSHIP_TONES[participant.relationship]} />
                      <div className="min-w-0">
                        <div className="text-[12.5px] font-medium text-slate-100">{participant.name}</div>
                        <div className="mt-0.5 text-[10.5px] text-slate-400">{RELATIONSHIP_LABELS[participant.relationship]}</div>
                        {contribution ? <p className="mt-1 text-[11.5px] leading-relaxed text-slate-400">{contribution.detail}</p> : null}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </details>
          <Button size="sm" variant="ghost" iconRight={<ArrowRight className="h-4 w-4" />} onClick={onDetail}>
            查看协作详情
          </Button>
        </div>

        <div className="mt-3 flex items-start gap-2 text-[11px] leading-relaxed text-slate-400">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          页面只提供服务端允许的回复、交接和执行锁操作。
        </div>

        <details className="mt-3 rounded-soft border border-white/[0.06] bg-surface-2/70 px-3 py-2 text-xs">
          <summary className="min-h-8 cursor-pointer py-1.5 text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">技术详情</summary>
          <div className="mt-2 border-t border-white/[0.06] pt-3">
            <DataSourceBadge source={record.technical.source} />
            <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-5 text-slate-400">{JSON.stringify({
              taskId: record.id.value,
              task: record.technical.value.task,
              stage: record.technical.value.stage,
              targetPostId: record.technical.value.targetPostId,
              upstreamAgents: record.technical.value.upstreamAgents,
              downstreamAgents: record.technical.value.downstreamAgents,
              allowedActions: record.actions.value,
              sources: record.sources.value,
            }, null, 2)}</pre>
          </div>
        </details>
      </div>
    </article>
  )
}
