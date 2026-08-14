import { useMemo, useState } from 'react'
import {
  Quote,
  MessageSquareText,
  ShieldQuestion,
  Share2,
  Clock,
  ArrowUpRight,
  Check,
  X,
  History,
  Sparkles,
} from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { cn } from '../../lib/cn'
import type { ShareEvent, UsageEventType } from '../../data/mockData'
import { resolveShareEventStatus, useDemo } from '../../store/DemoContext'

type Filter = 'all' | 'shared' | 'reused' | 'pending' | 'feedback'

const FILTER_CHIPS: { key: Filter; label: string }[] = [
  { key: 'all', label: '全部动态' },
  { key: 'shared', label: '我共享的' },
  { key: 'reused', label: '被数字人引用' },
  { key: 'pending', label: '等待授权' },
  { key: 'feedback', label: '有新反馈' },
]

interface Props {
  events: ShareEvent[]
  totalCount: number
  onOpenEvent: (event: ShareEvent) => void
  /** 内嵌到其他页面(如数字人管理·知识与权限)时隐藏自带头部,避免标题重复。 */
  showHeader?: boolean
}

/**
 * Tab 3 · 共享与引用(修改文档 §10):
 *   动态时间线,3 类语义:被引用 / 新反馈 / 等待授权。
 *   头部横向 chip 筛选;时间轴上的点用 event.tone 表示分类。
 *   "等待授权" / "新反馈" 显示行内操作;已授权 / 已拒绝 / 已查看反馈会在 statusLabel 上体现。
 */
export function ShareTimeline({ events, totalCount, onOpenEvent, showHeader = true }: Props) {
  const { authorizedEventIds, declinedEventIds, feedbackHandledIds } = useDemo()
  const [filter, setFilter] = useState<Filter>('all')

  const filtered = useMemo(() => {
    if (filter === 'all') return events
    if (filter === 'shared') return events.filter((e) => e.type === 'shared')
    if (filter === 'reused') return events.filter((e) => e.type === 'reused')
    if (filter === 'pending') return events.filter((e) => e.type === 'reuse_requested')
    if (filter === 'feedback') return events.filter((e) => e.type === 'feedback_received')
    return events
  }, [events, filter])

  const pendingCount = events.filter(
    (e) => e.type === 'reuse_requested' && !authorizedEventIds.has(e.id) && !declinedEventIds.has(e.id),
  ).length
  const feedbackCount = events.filter(
    (e) => e.type === 'feedback_received' && !feedbackHandledIds.has(e.id),
  ).length

  return (
    <div className="animate-fade-in space-y-5">
      {/* ── 顶部说明 + 未处理条数(简短、无大面积语义色) ── */}
      {showHeader && (
      <div className="card-base p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-collab/12 text-collab">
                <Share2 className="h-4 w-4" />
              </span>
              <h2 className="text-[15px] font-semibold text-white">使用与反馈</h2>
            </div>
            <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-slate-400">
               查看知识在后续项目中的引用记录与新反馈，了解知识如何被调用、产生新结果并反馈原结论。
               <span className="text-slate-300">所有使用都会保留来源与适用范围</span>，不会自动修改原知识。
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <MetricBlock
              label="待处理授权"
              value={pendingCount}
              tone={pendingCount > 0 ? 'remind' : 'neutral'}
            />
            <MetricBlock
              label="新反馈"
              value={feedbackCount}
              tone={feedbackCount > 0 ? 'knowledge' : 'neutral'}
            />
            <MetricBlock label="累计动态" value={totalCount} tone="neutral" />
          </div>
        </div>
      </div>
      )}

      {/* ── 分类 chip ── */}
      <div className="flex flex-wrap items-center gap-1.5">
        {FILTER_CHIPS.map((c) => {
          const active = c.key === filter
          const badge =
            c.key === 'pending' && pendingCount > 0
              ? pendingCount
              : c.key === 'feedback' && feedbackCount > 0
                ? feedbackCount
                : undefined
          return (
            <button
              key={c.key}
              onClick={() => setFilter(c.key)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors',
                active
                  ? 'border-mint-400/40 bg-mint-400/[0.12] text-mint-200'
                  : 'border-white/[0.06] bg-surface-1 text-slate-400 hover:border-white/[0.12] hover:text-slate-200',
              )}
            >
              {c.label}
              {badge !== undefined && (
                <span
                  className={cn(
                    'inline-flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[10px] tabular-nums',
                    active ? 'bg-mint-400/20 text-mint-100' : 'bg-white/[0.06] text-slate-400',
                  )}
                >
                  {badge}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* ── 时间线 ── */}
      {filtered.length > 0 ? (
        <ol className="relative space-y-3">
          {/* 竖线 */}
          <span
            aria-hidden
            className="pointer-events-none absolute left-[19px] top-2 bottom-2 w-px bg-white/[0.06]"
          />
          {filtered.map((e) => (
            <TimelineItem key={e.id} event={e} onOpen={() => onOpenEvent(e)} />
          ))}
        </ol>
      ) : (
        <div className="card-base flex flex-col items-center py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/[0.04] text-slate-500">
            <History className="h-5 w-5" />
          </span>
          <h3 className="mt-3 text-sm font-semibold text-slate-100">没有相关的动态</h3>
          <p className="mt-1 max-w-sm text-xs text-slate-500">
            尝试切换到其他分类。等待授权和新反馈会在这里最先出现。
          </p>
        </div>
      )}
    </div>
  )
}

/* ---------- Timeline Item ---------- */
function TimelineItem({ event, onOpen }: { event: ShareEvent; onOpen: () => void }) {
  const {
    authorizedEventIds,
    declinedEventIds,
    feedbackHandledIds,
    authorizeShareEvent,
    declineShareEvent,
    markFeedbackHandled,
  } = useDemo()

  const status = resolveShareEventStatus(
    event,
    authorizedEventIds,
    declinedEventIds,
    feedbackHandledIds,
  )
  const closed = status.closed

  // 类型 → 颜色圆点 + 图标(收敛为 3 类语义)
  const typeMeta = TYPE_META[event.type] ?? DEFAULT_TYPE_META

  return (
    <li className="relative pl-11">
      {/* 圆点 */}
      <span
        aria-hidden
        className={cn(
          'absolute left-[12px] top-3 flex h-4 w-4 items-center justify-center rounded-full ring-4 ring-canvas',
          typeMeta.dot,
        )}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
      </span>

      <div
        className={cn(
          'card-base p-4 transition-colors',
          closed ? 'opacity-90' : 'hover:border-white/[0.14]',
        )}
      >
        {/* 顶部:类型 + 标题 + 状态 */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={typeMeta.tone}>
                <span className="mr-1 inline-flex h-3 w-3">{typeMeta.icon}</span>
                {typeMeta.label}
              </Badge>
              <Badge tone={status.tone === 'neutral' ? 'neutral' : status.tone} dot={!closed}>
                {status.label}
              </Badge>
            </div>
            <h3 className="mt-2 truncate text-[14.5px] font-semibold text-slate-100">
              {event.knowledgeTitle}
            </h3>
            <p className="mt-1 text-[13px] leading-relaxed text-slate-400">
              {event.description}
            </p>
            {event.detail && !closed && (
              <p className="mt-2 rounded-[10px] bg-surface-1 px-3 py-2 text-[12px] leading-relaxed text-slate-400">
                {event.detail}
              </p>
            )}
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-slate-500">
              <span className="inline-flex items-center gap-1">
                <Sparkles className="h-3 w-3" />
                {event.actor}
              </span>
              <span>· {event.project}</span>
              {event.purpose && <span className="truncate">· 用途:{event.purpose}</span>}
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {event.time}
              </span>
            </div>
          </div>
        </div>

        {/* 底部操作 */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {/* 等待授权 → 允许 / 拒绝 */}
          {event.type === 'reuse_requested' && !closed && (
            <>
              <Button
                variant="primary"
                size="sm"
                icon={<Check className="h-3.5 w-3.5" />}
                onClick={() => authorizeShareEvent(event.id)}
              >
                允许本次引用
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<X className="h-3.5 w-3.5" />}
                onClick={() => declineShareEvent(event.id)}
              >
                拒绝
              </Button>
            </>
          )}
          {/* 新反馈 → 查看反馈 */}
          {event.type === 'feedback_received' && !closed && (
            <Button
              variant="primary"
              size="sm"
              icon={<MessageSquareText className="h-3.5 w-3.5" />}
              onClick={() => markFeedbackHandled(event.id)}
            >
              查看反馈
            </Button>
          )}
          <Button
            variant="subtle"
            size="sm"
            icon={<ArrowUpRight className="h-3.5 w-3.5" />}
            onClick={onOpen}
          >
            {event.type === 'reuse_requested' && !closed
              ? '查看知识详情'
              : event.type === 'feedback_received' && !closed
                ? '查看知识详情'
                : event.primaryAction}
          </Button>
        </div>
      </div>
    </li>
  )
}

/* ---------- 顶部 metric ---------- */
function MetricBlock({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: 'remind' | 'knowledge' | 'neutral'
}) {
  const cls =
    tone === 'remind'
      ? 'text-remind'
      : tone === 'knowledge'
        ? 'text-knowledge'
        : 'text-slate-300'
  return (
    <div className="flex flex-col items-end">
      <span className={cn('text-lg font-semibold tabular-nums', cls)}>{value}</span>
      <span className="text-[10.5px] uppercase tracking-wide text-slate-500">{label}</span>
    </div>
  )
}

/* ---------- 类型 → 视觉 meta ---------- */
const TYPE_META: Record<
  UsageEventType,
  { label: string; tone: 'mint' | 'knowledge' | 'collab' | 'remind' | 'rose'; dot: string; icon: React.ReactNode }
> = {
  reused: {
    label: '被引用',
    tone: 'mint',
    dot: 'bg-mint-400/20 text-mint-300',
    icon: <Quote className="h-3 w-3" />,
  },
  reuse_requested: {
    label: '等待授权',
    tone: 'remind',
    dot: 'bg-remind/20 text-remind',
    icon: <ShieldQuestion className="h-3 w-3" />,
  },
  feedback_received: {
    label: '新反馈',
    tone: 'knowledge',
    dot: 'bg-knowledge/20 text-knowledge',
    icon: <MessageSquareText className="h-3 w-3" />,
  },
  shared: {
    label: '我共享',
    tone: 'collab',
    dot: 'bg-collab/20 text-collab',
    icon: <Share2 className="h-3 w-3" />,
  },
  update_requested: {
    label: '更新请求',
    tone: 'rose',
    dot: 'bg-rose/20 text-rose',
    icon: <Sparkles className="h-3 w-3" />,
  },
}

const DEFAULT_TYPE_META = TYPE_META.reused
