import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, MessageSquareText, ShieldCheck, ThumbsUp, X } from 'lucide-react'
import type { MarketMeTimelineItem, TimelineCategory, TimelineStatus } from '../types'
import { Drawer } from '../../../components/ui/Drawer'
import { Button } from '../../../components/ui/Button'
import { marketApi } from '../api/marketApi'

interface ExchangeTabsProps {
  timeline: MarketMeTimelineItem[]
}

type Filter = 'all' | TimelineCategory

const CATEGORY_TAG: Record<TimelineCategory, { en: string; zh: string; dot: string; text: string; ring: string }> = {
  request: {
    en: 'request',
    zh: '我发起',
    dot: 'bg-collab',
    text: 'text-collab',
    ring: 'ring-collab/25',
  },
  incoming: {
    en: 'incoming',
    zh: '收到帮助',
    dot: 'bg-remind',
    text: 'text-remind',
    ring: 'ring-remind/25',
  },
  outgoing: {
    en: 'outgoing',
    zh: '给出帮助',
    dot: 'bg-knowledge',
    text: 'text-knowledge',
    ring: 'ring-knowledge/25',
  },
}

const STATUS_STYLE: Record<
  TimelineStatus,
  { en: string; text: string; ring: string; bg: string }
> = {
  answered: {
    en: 'ANSWERED',
    text: 'text-mint-300',
    ring: 'ring-mint-400/40',
    bg: 'bg-mint-400/[0.08]',
  },
  awaiting_confirm: {
    en: 'AWAITING_CONFIRM',
    text: 'text-remind',
    ring: 'ring-remind/40',
    bg: 'bg-remind/[0.08]',
  },
  denied: {
    en: 'DENIED',
    text: 'text-rose',
    ring: 'ring-rose/40',
    bg: 'bg-rose/[0.08]',
  },
  open: {
    en: 'OPEN',
    text: 'text-slate-300',
    ring: 'ring-white/[0.14]',
    bg: 'bg-white/[0.04]',
  },
}

function formatTime(iso: string): { time: string; day?: string } {
  try {
    const date = new Date(iso)
    const now = new Date()
    const sameDay =
      date.getFullYear() === now.getFullYear() &&
      date.getMonth() === now.getMonth() &&
      date.getDate() === now.getDate()
    const yesterday = new Date(now)
    yesterday.setDate(now.getDate() - 1)
    const isYesterday =
      date.getFullYear() === yesterday.getFullYear() &&
      date.getMonth() === yesterday.getMonth() &&
      date.getDate() === yesterday.getDate()
    const hhmm = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
    if (sameDay) return { time: `${hhmm}:${String(date.getSeconds()).padStart(2, '0')}` }
    if (isYesterday) return { time: hhmm, day: '昨天' }
    const md = date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
    return { time: hhmm, day: md }
  } catch {
    return { time: iso.slice(11, 19) }
  }
}

function counts(list: MarketMeTimelineItem[]) {
  let open = 0
  let closed = 0
  for (const item of list) {
    if (item.status === 'answered' || item.status === 'denied') closed++
    else open++
  }
  return { open, closed }
}

function actionLabel(status: TimelineStatus, category: TimelineCategory): string {
  if (status === 'awaiting_confirm') return '审核并发送'
  if (category === 'request') return '查看信号'
  return '查看'
}

export function ExchangeTabs({ timeline }: ExchangeTabsProps) {
  const [filter, setFilter] = useState<Filter>('all')
  const [selected, setSelected] = useState<MarketMeTimelineItem | null>(null)
  const [actionResult, setActionResult] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const closeDrawer = () => {
    setSelected(null)
    setActionResult(null)
  }

  const invalidateMarket = () => queryClient.invalidateQueries({ queryKey: ['market'] })

  const resolveMutation = useMutation({
    mutationFn: ({ inboxItemId, action }: { inboxItemId: string; action: 'approve' | 'deny' }) =>
      marketApi.resolveDelegated(inboxItemId, action),
    onSuccess: (_data, variables) => {
      setActionResult(variables.action === 'approve' ? '已批准，答案已发送给对方。' : '已拒绝，未透露任何内容。')
      void invalidateMarket()
    },
    onError: () => setActionResult('操作失败，请稍后重试。'),
  })

  const adoptMutation = useMutation({
    mutationFn: ({ helperId, question }: { helperId: string; question: string }) =>
      marketApi.adopt(helperId, question),
    onSuccess: () => {
      setActionResult('已采纳，对方获得一条贡献记录，并建立了来源血缘。')
      void invalidateMarket()
    },
    onError: () => setActionResult('采纳失败，请稍后重试。'),
  })

  const actionBusy = resolveMutation.isPending || adoptMutation.isPending

  const groups = useMemo(() => {
    return {
      all: timeline,
      request: timeline.filter((item) => item.category === 'request'),
      incoming: timeline.filter((item) => item.category === 'incoming'),
      outgoing: timeline.filter((item) => item.category === 'outgoing'),
    }
  }, [timeline])

  const requestCounts = counts(groups.request)

  const columns: Array<{
    key: Filter
    en: string
    zh: string
    sub: string
  }> = [
    { key: 'all', en: 'ALL', zh: '全部往来', sub: `${groups.all.length} records` },
    {
      key: 'request',
      en: 'MY REQUESTS',
      zh: '我提出的求助',
      sub: `${requestCounts.open} open · ${requestCounts.closed} closed`,
    },
    { key: 'incoming', en: 'RECEIVED', zh: '谁帮了我', sub: `${groups.incoming.length} matches` },
    { key: 'outgoing', en: 'GIVEN', zh: '我帮了谁', sub: `${groups.outgoing.length} matches` },
  ]

  const list = groups[filter]

  return (
    <>
    <section aria-label="市场交流记录" className="rounded-soft border border-white/[0.06] bg-surface-1">
      <div role="tablist" aria-label="市场往来分类" className="grid grid-cols-4">
        {columns.map((col) => {
          const active = col.key === filter
          return (
            <button
              key={col.key}
              type="button"
              role="tab"
              aria-selected={active}
              tabIndex={active ? 0 : -1}
              onClick={() => setFilter(col.key)}
              className={`relative flex flex-col items-start gap-1 px-5 py-4 text-left transition-colors ${
                active ? 'bg-surface-2' : 'hover:bg-white/[0.02]'
              }`}
            >
              <span
                aria-hidden
                className={`pointer-events-none absolute inset-x-0 top-0 h-px ${
                  active ? 'bg-white/40' : 'bg-transparent'
                }`}
              />
              <span
                aria-hidden
                className={`pointer-events-none absolute inset-x-0 bottom-0 h-[2px] ${
                  active ? 'bg-white' : 'bg-transparent'
                }`}
              />
              <span
                className={`text-[11px] font-semibold uppercase tracking-[0.14em] ${
                  active ? 'text-slate-300' : 'text-slate-400'
                }`}
              >
                {col.en}
              </span>
              <span className={`text-base ${active ? 'text-white' : 'text-slate-200'}`}>{col.zh}</span>
              <span className="text-xs text-slate-400 tabular-nums">{col.sub}</span>
            </button>
          )
        })}
      </div>

      <div className="h-[clamp(480px,62vh,760px)] overflow-y-auto overscroll-contain border-t border-white/[0.06]">
        {list.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">当前分类没有记录。</div>
        ) : (
          <ol className="divide-y divide-white/[0.04]">
            {list.map((item) => {
              const tag = CATEGORY_TAG[item.category]
              const status = STATUS_STYLE[item.status]
              const { time, day } = formatTime(item.at)
              return (
                <li
                  key={item.id}
                  className="group grid grid-cols-[112px_1fr_auto] items-start gap-6 px-6 py-4 transition-colors hover:bg-white/[0.015]"
                >
                  <div className="pt-1 text-xs tabular-nums leading-tight text-slate-400">
                    {day ? <div>{day}</div> : null}
                    <div className={day ? 'text-slate-400' : ''}>{time}</div>
                  </div>

                  <div className="flex min-w-0 flex-col gap-1.5">
                    <span
                      className={`inline-flex w-fit items-center gap-1.5 rounded-full bg-white/[0.03] px-2.5 py-1 text-[11px] ring-1 ${tag.ring}`}
                    >
                      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${tag.dot}`} />
                      <span className={`font-medium ${tag.text}`}>{tag.en}</span>
                      <span className="text-slate-400">·</span>
                      <span className="text-slate-300">{tag.zh}</span>
                    </span>
                    <p className="truncate text-sm text-slate-100">{item.title}</p>
                    <p className="text-[11px] text-slate-400">
                      {item.meta ? item.meta : item.counterpart ? `对方 · ${item.counterpart.name}` : null}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 pt-0.5">
                    <span
                      className={`rounded-md px-2 py-1 text-[11px] font-semibold uppercase tracking-wider ring-1 ${status.text} ${status.ring} ${status.bg}`}
                    >
                      {status.en}
                    </span>
                    <button
                      type="button"
                      onClick={() => setSelected(item)}
                      className="rounded-md border border-white/[0.08] bg-white/[0.02] px-3 py-1 text-xs text-slate-300 transition-colors hover:border-white/[0.16] hover:bg-white/[0.05] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
                    >
                      {actionLabel(item.status, item.category)}
                    </button>
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </section>

    <Drawer
      open={selected !== null}
      onClose={closeDrawer}
      icon={<MessageSquareText className="h-5 w-5" />}
      title={selected?.title ?? '协作往来详情'}
      subtitle={selected ? CATEGORY_TAG[selected.category].zh : undefined}
      width={560}
    >
      {selected ? (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`inline-flex items-center gap-1.5 rounded-full bg-white/[0.03] px-2.5 py-1 ring-1 ${CATEGORY_TAG[selected.category].ring}`}>
              <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${CATEGORY_TAG[selected.category].dot}`} />
              <span className={`font-medium ${CATEGORY_TAG[selected.category].text}`}>{CATEGORY_TAG[selected.category].en}</span>
              <span className="text-slate-400">·</span>
              <span className="text-slate-300">{CATEGORY_TAG[selected.category].zh}</span>
            </span>
            <span className={`rounded-md px-2 py-1 font-semibold uppercase tracking-wider ring-1 ${STATUS_STYLE[selected.status].text} ${STATUS_STYLE[selected.status].ring} ${STATUS_STYLE[selected.status].bg}`}>
              {STATUS_STYLE[selected.status].en}
            </span>
          </div>

          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-slate-400">话题</dt>
              <dd className="mt-1 text-slate-200">{selected.topic || '—'}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-400">对方</dt>
              <dd className="mt-1 text-slate-200">{selected.counterpart?.name ?? '我的分身'}</dd>
            </div>
          </dl>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-slate-200">
              {selected.category === 'request' ? '我的分身发出的信号' : '分身给出的答案'}
            </h3>
            <div className="whitespace-pre-wrap rounded-soft border border-white/[0.06] bg-surface-1 p-4 text-[13.5px] leading-relaxed text-slate-200">
              {selected.detail || '暂无可展示的内容。'}
            </div>
          </section>

          <div className="flex items-start gap-2 border-t border-white/[0.06] pt-4 text-[11.5px] leading-relaxed text-slate-400">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            答案由对方分身依据其私有记忆生成，只回传结论，原始记忆不离境。
          </div>

          {actionResult ? (
            <p role="status" className="rounded-soft border border-mint-400/20 bg-mint-400/[0.06] px-3 py-2 text-xs text-mint-300">
              {actionResult}
            </p>
          ) : null}

          {selected.status === 'awaiting_confirm' && selected.action_ref ? (
            <div className="rounded-soft border border-remind/25 bg-remind/[0.06] p-4">
              <p className="text-sm text-slate-200">这条代答涉及较敏感的记忆，需要你确认后才会发送给对方。</p>
              <div className="mt-3 flex gap-2">
                <Button
                  size="sm"
                  icon={<Check className="h-4 w-4" />}
                  loading={resolveMutation.isPending}
                  disabled={actionBusy}
                  onClick={() => resolveMutation.mutate({ inboxItemId: selected.action_ref, action: 'approve' })}
                >
                  批准发送
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<X className="h-4 w-4" />}
                  disabled={actionBusy}
                  onClick={() => resolveMutation.mutate({ inboxItemId: selected.action_ref, action: 'deny' })}
                >
                  拒绝
                </Button>
              </div>
            </div>
          ) : null}

          {selected.category === 'incoming' && selected.status === 'answered' && selected.counterpart ? (
            <Button
              size="sm"
              variant="secondary"
              icon={<ThumbsUp className="h-4 w-4" />}
              loading={adoptMutation.isPending}
              disabled={actionBusy}
              onClick={() => adoptMutation.mutate({ helperId: selected.counterpart!.id, question: selected.topic })}
            >
              采纳此答案（给对方记一次贡献）
            </Button>
          ) : null}
        </div>
      ) : null}
    </Drawer>
    </>
  )
}
