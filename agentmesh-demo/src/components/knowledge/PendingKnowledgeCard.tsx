import { Check, Clock3, FileCheck2, ShieldAlert, X } from 'lucide-react'

import type { InboxItem } from '../../features/knowledge/api'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'

interface PendingKnowledgeCardProps {
  item: InboxItem
  busy: boolean
  onConfirm: () => void
  onSnooze: () => void
  onResolve: () => void
  onInjection: (action: 'release' | 'discard') => void
}

export function PendingKnowledgeCard({
  item,
  busy,
  onConfirm,
  onSnooze,
  onResolve,
  onInjection,
}: PendingKnowledgeCardProps) {
  return (
    <article data-inbox-item-id={item.id} className="rounded-card border border-mint-400/20 bg-mint-400/[0.05] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-mint-400/12 text-mint-300">
            {item.item_type === 'prompt_injection_review' ? (
              <ShieldAlert className="h-5 w-5" />
            ) : (
              <FileCheck2 className="h-5 w-5" />
            )}
          </span>
          <div>
            <h2 className="text-base font-semibold text-white">{item.title}</h2>
            <p className="mt-1 text-sm leading-relaxed text-slate-400">{item.summary}</p>
          </div>
        </div>
        <Badge tone={item.status === 'snoozed' ? 'neutral' : 'remind'} dot>
          {item.status === 'snoozed' ? '已稍后处理' : '待处理'}
        </Badge>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {item.allowed_actions.includes('confirm_brief') ? (
          <Button loading={busy} icon={<Check className="h-4 w-4" />} onClick={onConfirm}>
            确认并沉淀
          </Button>
        ) : null}
        {item.allowed_actions.includes('snooze') ? (
          <Button variant="subtle" disabled={busy} icon={<Clock3 className="h-4 w-4" />} onClick={onSnooze}>
            稍后处理
          </Button>
        ) : null}
        {item.allowed_actions.includes('release') ? (
          <Button variant="secondary" disabled={busy} onClick={() => onInjection('release')}>
            释放内容
          </Button>
        ) : null}
        {item.allowed_actions.includes('discard') ? (
          <Button variant="danger" disabled={busy} icon={<X className="h-4 w-4" />} onClick={() => onInjection('discard')}>
            丢弃内容
          </Button>
        ) : null}
        {item.allowed_actions.includes('resolve') ? (
          <Button variant="ghost" disabled={busy} onClick={onResolve}>
            标记已解决
          </Button>
        ) : null}
      </div>
    </article>
  )
}
