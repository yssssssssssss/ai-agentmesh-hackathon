import { ArrowRight, Clock3, LockKeyhole, MessagesSquare } from 'lucide-react'

import type { TaskCard } from '../../features/collaboration/api'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'

export function MyCollabCard({ card, onDetail }: { card: TaskCard; onDetail: () => void }) {
  const task = card.task
  return (
    <article data-task-id={task.id} className="card-base p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Clock3 className="h-3.5 w-3.5" />
            {task.updated_at ? new Date(task.updated_at).toLocaleString('zh-CN') : '服务端任务'}
          </div>
          <h2 className="mt-2 text-base font-semibold text-white">{task.title}</h2>
          <p className="mt-1 text-sm text-slate-400">{card.latest_post?.content ?? '暂无可见协作消息。'}</p>
        </div>
        <Badge tone={task.status === 'completed' ? 'mint' : 'collab'} dot>
          {task.status}
        </Badge>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1 rounded-pill bg-white/[0.04] px-2.5 py-1">
          <MessagesSquare className="h-3.5 w-3.5" /> {card.post_count} 条消息
        </span>
        <span className="rounded-pill bg-white/[0.04] px-2.5 py-1">阶段：{card.stage ?? task.collaboration_stage}</span>
        {card.active_lock ? (
          <span className="inline-flex items-center gap-1 rounded-pill bg-remind/10 px-2.5 py-1 text-remind">
            <LockKeyhole className="h-3.5 w-3.5" /> {card.active_lock.owner_label}
          </span>
        ) : null}
      </div>
      <Button className="mt-4" variant="secondary" iconRight={<ArrowRight className="h-4 w-4" />} onClick={onDetail}>
        查看协作详情
      </Button>
    </article>
  )
}
