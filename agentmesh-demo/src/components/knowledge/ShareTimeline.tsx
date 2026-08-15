import { useMemo, useState, type ReactNode } from 'react'
import {
  ArrowUpRight,
  Clock,
  History,
  MessageSquareText,
  Quote,
  Share2,
  ShieldQuestion,
  Sparkles,
} from 'lucide-react'

import type { KnowledgeUsageView } from '../../features/knowledge/presenter'
import type { DataSourceKind, PresentedValue } from '../../lib/presentation'
import { cn } from '../../lib/cn'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'

type Filter = 'all' | 'shared' | 'reused' | 'pending' | 'feedback'

const FILTER_CHIPS: Array<{ key: Filter; label: string }> = [
  { key: 'all', label: '全部动态' },
  { key: 'shared', label: '已共享知识' },
  { key: 'reused', label: '被数字人引用' },
  { key: 'pending', label: '等待授权' },
  { key: 'feedback', label: '有新反馈' },
]

interface Props {
  events: KnowledgeUsageView[]
  totalCount: PresentedValue<number>
  sources: DataSourceKind[]
  onOpenEvent: (event: KnowledgeUsageView) => void
}

export function ShareTimeline({ events, totalCount, sources, onOpenEvent }: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const filtered = useMemo(() => {
    if (filter === 'all') return events
    if (filter === 'shared') return events.filter((event) => event.type.value === 'shared')
    if (filter === 'reused') return events.filter((event) => event.type.value === 'reused')
    if (filter === 'pending') return events.filter((event) => event.type.value === 'reuse_requested')
    return events.filter((event) => event.type.value === 'feedback_received')
  }, [events, filter])
  const pendingCount = events.filter(
    (event) => event.type.value === 'reuse_requested' && event.allowedActions.value.length > 0,
  ).length
  const feedbackCount = events.filter(
    (event) => event.type.value === 'feedback_received' && event.allowedActions.value.length > 0,
  ).length

  return (
    <div className="animate-fade-in space-y-5">
      <section className="card-base p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-collab/12 text-collab"><Share2 className="h-4 w-4" /></span>
              <h2 className="text-[15px] font-semibold text-white">使用与反馈</h2>
              {sources.map((source) => <DataSourceBadge key={source} source={source} />)}
            </div>
            <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-slate-400">
              查看知识在后续项目中的引用记录与新反馈。参考时间线只补齐展示，所有操作均以服务端 allowed_actions 为准。
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <MetricBlock label="可处理授权" value={pendingCount} tone={pendingCount > 0 ? 'remind' : 'neutral'} />
            <MetricBlock label="可处理反馈" value={feedbackCount} tone={feedbackCount > 0 ? 'knowledge' : 'neutral'} />
            <div className="flex items-end gap-1.5">
              <MetricBlock label="累计动态" value={totalCount.value} tone="neutral" />
              <DataSourceBadge source={totalCount.source} />
            </div>
          </div>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-1.5" aria-label="动态筛选">
        {FILTER_CHIPS.map((chip) => {
          const active = chip.key === filter
          return (
            <button
              key={chip.key}
              type="button"
              aria-pressed={active}
              onClick={() => setFilter(chip.key)}
              className={cn(
                'min-h-10 rounded-full border px-3 py-1.5 text-xs transition-[transform,background-color,border-color,color] active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50',
                active
                  ? 'border-mint-400/40 bg-mint-400/[0.12] text-mint-200'
                  : 'border-white/[0.06] bg-surface-1 text-slate-400 hover:border-white/[0.12] hover:text-slate-200',
              )}
            >
              {chip.label}
            </button>
          )
        })}
      </div>

      {filtered.length > 0 ? (
        <ol className="relative space-y-3">
          <span aria-hidden className="pointer-events-none absolute bottom-2 left-[19px] top-2 w-px bg-white/[0.06]" />
          {filtered.map((event) => (
            <TimelineItem key={`${event.kind}-${event.id.value}`} event={event} onOpen={() => onOpenEvent(event)} />
          ))}
        </ol>
      ) : (
        <div className="card-base flex flex-col items-center py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/[0.04] text-slate-500"><History className="h-5 w-5" /></span>
          <h3 className="mt-3 text-sm font-semibold text-slate-100">没有相关动态</h3>
          <p className="mt-1 max-w-sm text-xs text-slate-500">切换分类查看其他真实记录或参考时间线。</p>
        </div>
      )}
    </div>
  )
}

function TimelineItem({ event, onOpen }: { event: KnowledgeUsageView; onOpen: () => void }) {
  const meta = TYPE_META[event.type.value] ?? TYPE_META.reused
  const canRead = event.allowedActions.value.includes('read')
  return (
    <li className="relative pl-11">
      <span aria-hidden className={cn('absolute left-[12px] top-3 flex h-4 w-4 items-center justify-center rounded-full ring-4 ring-canvas', meta.dot)}>
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
      </span>
      <article className="card-base p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={meta.tone}>{meta.icon}{meta.label}</Badge>
              <Badge tone={event.needsAction.value && canRead ? 'remind' : 'neutral'} dot={event.needsAction.value && canRead}>{event.statusLabel.value}</Badge>
              <DataSourceBadge source={event.id.source} />
            </div>
            <h3 className="mt-2 text-[14.5px] font-semibold text-slate-100">{event.knowledgeTitle.value}</h3>
            <p className="mt-1 text-[13px] leading-relaxed text-slate-400">{event.description.value}</p>
            {event.detail.value ? <p className="mt-2 rounded-[10px] bg-surface-1 px-3 py-2 text-[12px] leading-relaxed text-slate-400">{event.detail.value}</p> : null}
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-slate-500">
              <span className="inline-flex items-center gap-1"><Sparkles className="h-3 w-3" />{event.actor.value}</span>
              <span>· {event.project.value}</span>
              {event.purpose.value ? <span>· 用途:{event.purpose.value}</span> : null}
              <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" />{formatTime(event.time.value)}</span>
            </div>
          </div>
        </div>
        <div className="mt-3">
          <Button
            variant="subtle"
            size="sm"
            disabled={!canRead}
            icon={<ArrowUpRight className="h-3.5 w-3.5" />}
            onClick={canRead ? onOpen : undefined}
            title={canRead ? undefined : '该记录没有服务端可用操作'}
          >
            {canRead ? event.primaryAction.value : '参考记录，操作不可用'}
          </Button>
        </div>
      </article>
    </li>
  )
}

function MetricBlock({ label, value, tone }: { label: string; value: number; tone: 'remind' | 'knowledge' | 'neutral' }) {
  const color = tone === 'remind' ? 'text-remind' : tone === 'knowledge' ? 'text-knowledge' : 'text-slate-300'
  return (
    <div className="flex flex-col items-end">
      <span className={cn('text-lg font-semibold tabular-nums', color)}>{value}</span>
      <span className="text-[10.5px] uppercase tracking-wide text-slate-500">{label}</span>
    </div>
  )
}

interface TypeMeta {
  label: string
  tone: 'mint' | 'knowledge' | 'collab' | 'remind' | 'rose'
  dot: string
  icon: ReactNode
}

const TYPE_META: Record<string, TypeMeta> = {
  reused: { label: '被引用', tone: 'mint', dot: 'bg-mint-400/20 text-mint-300', icon: <Quote className="mr-1 h-3 w-3" /> },
  reuse_requested: { label: '等待授权', tone: 'remind', dot: 'bg-remind/20 text-remind', icon: <ShieldQuestion className="mr-1 h-3 w-3" /> },
  feedback_received: { label: '新反馈', tone: 'knowledge', dot: 'bg-knowledge/20 text-knowledge', icon: <MessageSquareText className="mr-1 h-3 w-3" /> },
  shared: { label: '已共享', tone: 'collab', dot: 'bg-collab/20 text-collab', icon: <Share2 className="mr-1 h-3 w-3" /> },
  update_requested: { label: '更新请求', tone: 'rose', dot: 'bg-rose/20 text-rose', icon: <Sparkles className="mr-1 h-3 w-3" /> },
}

function formatTime(value: string) {
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString('zh-CN')
}
