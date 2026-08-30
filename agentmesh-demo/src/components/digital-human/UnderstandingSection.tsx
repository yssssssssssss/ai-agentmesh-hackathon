import { useMemo, useState } from 'react'
import { Sparkles, Check, Pencil, X, ChevronDown, BookOpen } from 'lucide-react'
import { SegmentedControl } from '../ui/SegmentedControl'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { UNDERSTANDINGS } from '../../data/mockData'
import { useDemo, type UnderstandingStatus } from '../../store/DemoContext'
import { cn } from '../../lib/cn'

type Bucket = 'pending' | 'confirmed' | 'ignored'

/** 'modified' 归入「已确认」桶,避免被修改的理解在三个筛选里都消失。 */
function bucketOf(status: UnderstandingStatus): Bucket {
  if (status === 'ignored') return 'ignored'
  if (status === 'confirmed' || status === 'modified') return 'confirmed'
  return 'pending'
}

const STATUS_BADGE: Record<UnderstandingStatus, { label: string; tone: 'mint' | 'knowledge' | 'remind' | 'neutral' }> = {
  pending: { label: '待确认', tone: 'remind' },
  confirmed: { label: '已确认', tone: 'mint' },
  modified: { label: '已修改', tone: 'knowledge' },
  ignored: { label: '已忽略', tone: 'neutral' },
}

/**
 * 对我的理解 —— 数字人从工作中形成的对用户的理解。
 * 按 待确认 / 已确认 / 已忽略 过滤;每条可展开「形成依据」查看 basis / source。
 * 首页只放待确认摘要,完整列表在此。
 */
export function UnderstandingSection() {
  const { understandings, setUnderstanding, showToast } = useDemo()
  const [filter, setFilter] = useState<Bucket>('pending')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const counts = useMemo(() => {
    const c: Record<Bucket, number> = { pending: 0, confirmed: 0, ignored: 0 }
    for (const u of UNDERSTANDINGS) c[bucketOf(understandings[u.id] ?? 'pending')] += 1
    return c
  }, [understandings])

  const visible = UNDERSTANDINGS.filter((u) => bucketOf(understandings[u.id] ?? 'pending') === filter)

  const toggleExpand = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const handleModify = (id: string) => {
    setUnderstanding(id, 'modified')
    showToast('已记录你的修改,数字人会据此调整这条理解', 'info')
  }

  return (
    <div className="animate-fade-in space-y-6">
      <header>
        <h1 className="flex items-center gap-2.5 text-xl font-semibold text-white">
          <Sparkles className="h-5 w-5 text-mint-300" />
          对我的理解
        </h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">
          数字人从你的工作与对话中形成的理解。确认后会更准确地代表你,你可以随时修改或忽略。
          <span className="text-slate-300">这些理解只来自你的工作,不涉及私人对话。</span>
        </p>
      </header>

      <SegmentedControl
        options={[
          { key: 'pending', label: `待确认 ${counts.pending}` },
          { key: 'confirmed', label: `已确认 ${counts.confirmed}` },
          { key: 'ignored', label: `已忽略 ${counts.ignored}` },
        ]}
        value={filter}
        onChange={(k) => setFilter(k as Bucket)}
        size="sm"
      />

      {visible.length > 0 ? (
        <ul className="space-y-3">
          {visible.map((u) => {
            const status = understandings[u.id] ?? 'pending'
            const badge = STATUS_BADGE[status]
            const isOpen = expanded.has(u.id)
            return (
              <li key={u.id} className="card-base p-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-[14px] leading-relaxed text-slate-200">{u.text}</p>
                  <Badge tone={badge.tone}>{badge.label}</Badge>
                </div>

                <button
                  type="button"
                  onClick={() => toggleExpand(u.id)}
                  className="mt-2.5 inline-flex items-center gap-1 text-[12px] text-slate-400 transition-colors hover:text-slate-300"
                >
                  <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', isOpen ? '' : '-rotate-90')} />
                  查看形成依据
                </button>

                {isOpen && (
                  <div className="mt-2 space-y-2 rounded-soft bg-surface-1 px-3.5 py-3 text-[12.5px] leading-relaxed animate-fade-in">
                    <p className="text-slate-400">{u.basis}</p>
                    <p className="flex items-center gap-1.5 text-slate-400">
                      <BookOpen className="h-3.5 w-3.5" />
                      来源:{u.source}
                    </p>
                  </div>
                )}

                {status === 'pending' && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button
                      variant="primary"
                      size="sm"
                      icon={<Check className="h-3.5 w-3.5" />}
                      onClick={() => setUnderstanding(u.id, 'confirmed')}
                    >
                      准确
                    </Button>
                    <Button
                      variant="subtle"
                      size="sm"
                      icon={<Pencil className="h-3.5 w-3.5" />}
                      onClick={() => handleModify(u.id)}
                    >
                      需要修改
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<X className="h-3.5 w-3.5" />}
                      onClick={() => setUnderstanding(u.id, 'ignored')}
                    >
                      忽略
                    </Button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      ) : (
        <div className="card-base flex flex-col items-center py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/[0.04] text-slate-400">
            <Sparkles className="h-5 w-5" />
          </span>
          <h3 className="mt-3 text-sm font-semibold text-slate-100">
            {filter === 'pending' ? '没有待确认的理解' : filter === 'confirmed' ? '还没有已确认的理解' : '没有被忽略的理解'}
          </h3>
          <p className="mt-1 max-w-sm text-xs text-slate-400">
            数字人会持续从你的工作中形成新的理解,出现后会在这里等待你确认。
          </p>
        </div>
      )}
    </div>
  )
}
