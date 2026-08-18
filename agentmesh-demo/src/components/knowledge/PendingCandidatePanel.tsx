import type { ReactNode } from 'react'
import {
  ArrowUpRight,
  Check,
  Clock,
  FileCheck2,
  FolderClock,
  Info,
  Lightbulb,
  ShieldAlert,
  X,
} from 'lucide-react'

import type { PendingKnowledgeView } from '../../features/knowledge/presenter'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'

interface Props {
  items: PendingKnowledgeView[]
  busy: boolean
  readOnly: boolean
  onConfirm: (item: PendingKnowledgeView) => void
  onSnooze: (item: PendingKnowledgeView) => void
  onResolve: (item: PendingKnowledgeView) => void
  onInjection: (item: PendingKnowledgeView, action: 'release' | 'discard') => void
  onAccept: (item: PendingKnowledgeView) => void
  onOpenDetail: (item: PendingKnowledgeView) => void
}

export function PendingCandidatePanel({
  items,
  busy,
  readOnly,
  onConfirm,
  onSnooze,
  onResolve,
  onInjection,
  onAccept,
  onOpenDetail,
}: Props) {
  return (
    <div className="animate-fade-in space-y-5">
      {items.map((item) => {
        const actions = item.allowedActions.value
        const injectionReview = item.itemType.value === 'prompt_injection_review'
        return (
          <article
            key={`${item.kind}-${item.id.value}`}
            data-inbox-item-id={item.id.value}
            className="card-base overflow-hidden"
          >
            <section className="p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex min-w-0 items-start gap-3.5">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-mint-400/12 text-mint-300">
                    {injectionReview ? <ShieldAlert className="h-5 w-5" /> : item.kind === 'team_candidate' ? <Lightbulb className="h-5 w-5" /> : <FileCheck2 className="h-5 w-5" />}
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={item.status.value === 'snoozed' ? 'neutral' : 'remind'} dot>
                        {item.status.value === 'snoozed' ? '已稍后处理' : '待确认'}
                      </Badge>
                      <Badge tone="knowledge">{item.memoryType.value}</Badge>
                      <Badge tone="neutral">{item.sourceProject.value}</Badge>
                      <DataSourceBadge source={item.title.source} />
                    </div>
                    <h2 className="mt-2 text-[18px] font-semibold leading-snug text-white">{item.title.value}</h2>
                    <p className="mt-2 text-[14px] leading-relaxed text-slate-300">{item.summary.value}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onOpenDetail(item)}
                  className="inline-flex min-h-10 shrink-0 items-center gap-1 rounded-lg px-2 text-xs text-slate-500 transition-colors active:scale-[0.98] hover:bg-white/[0.04] hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
                >
                  查看详情 <ArrowUpRight className="h-3 w-3" />
                </button>
              </div>
            </section>

            <section className="border-t border-white/[0.06] bg-surface-1/45 px-6 py-4">
              <div className="grid gap-3 text-xs text-slate-400 sm:grid-cols-2 lg:grid-cols-4">
                <Meta icon={<FolderClock className="h-3.5 w-3.5" />} label="来源项目" value={item.sourceProject.value} source={item.sourceProject.source} />
                <Meta icon={<Info className="h-3.5 w-3.5" />} label="候选类型" value={item.itemType.value} source={item.itemType.source} />
                <Meta icon={<Clock className="h-3.5 w-3.5" />} label="形成时间" value={formatTime(item.createdAt.value)} source={item.createdAt.source} />
                <Meta icon={<FileCheck2 className="h-3.5 w-3.5" />} label="文档版本" value={item.documentVersion.value === null ? '不适用' : `v${item.documentVersion.value}`} source={item.documentVersion.source} />
              </div>
            </section>

            <section className="border-t border-white/[0.06] px-6 py-5">
              <div className="flex flex-wrap items-center gap-2.5">
                {actions.includes('confirm_brief') ? (
                  <Button loading={busy} disabled={readOnly} icon={<Check className="h-4 w-4" />} onClick={() => onConfirm(item)}>确认并沉淀</Button>
                ) : null}
                {actions.includes('accept') ? (
                  <Button loading={busy} disabled={readOnly} icon={<Check className="h-4 w-4" />} onClick={() => onAccept(item)}>接受候选</Button>
                ) : null}
                {actions.includes('snooze') ? (
                  <Button variant="subtle" disabled={busy || readOnly} icon={<Clock className="h-4 w-4" />} onClick={() => onSnooze(item)}>稍后处理</Button>
                ) : null}
                {actions.includes('release') ? (
                  <Button variant="secondary" disabled={busy || readOnly} onClick={() => onInjection(item, 'release')}>释放内容</Button>
                ) : null}
                {actions.includes('discard') ? (
                  <Button variant="danger" disabled={busy || readOnly} icon={<X className="h-4 w-4" />} onClick={() => onInjection(item, 'discard')}>丢弃内容</Button>
                ) : null}
                {actions.includes('resolve') ? (
                  <Button variant="ghost" disabled={busy || readOnly} onClick={() => onResolve(item)}>标记已解决</Button>
                ) : null}
                {actions.length === 0 ? <span className="text-xs text-slate-500">服务端未开放可执行操作。</span> : null}
              </div>
            </section>
          </article>
        )
      })}

      <div className="flex items-start gap-2 text-[12px] leading-relaxed text-slate-500">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        候选只有在服务端返回对应 allowed_actions 后才可处理。确认 Brief 会携带当前文档版本，避免覆盖并发更新。
      </div>
    </div>
  )
}

function Meta({ icon, label, value, source }: { icon: ReactNode; label: string; value: string; source: 'M' | 'T' }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <span className="shrink-0 text-slate-500">{icon}</span>
      <span className="shrink-0 text-slate-500">{label}:</span>
      <span className="truncate text-slate-300">{value}</span>
      <DataSourceBadge source={source} />
    </div>
  )
}

function formatTime(value: string) {
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString('zh-CN')
}
