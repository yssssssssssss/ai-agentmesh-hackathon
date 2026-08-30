import { useMemo, useState } from 'react'
import { History, Clock } from 'lucide-react'
import { Badge } from '../ui/Badge'
import {
  ACTIVITY_LOG,
  ACTIVITY_CATEGORY_LABELS,
  type ActivityCategory,
  type ActivityEntry,
} from '../../data/mockData'
import { cn } from '../../lib/cn'

type Filter = 'all' | ActivityCategory

const CHIPS: { key: Filter; label: string }[] = [
  { key: 'all', label: '全部' },
  ...(Object.keys(ACTIVITY_CATEGORY_LABELS) as ActivityCategory[]).map((k) => ({
    key: k,
    label: ACTIVITY_CATEGORY_LABELS[k],
  })),
]

const DOT_TONE: Record<ActivityEntry['tone'], string> = {
  mint: 'bg-mint-400/20 text-mint-300',
  knowledge: 'bg-knowledge/20 text-knowledge',
  collab: 'bg-collab/20 text-collab',
  remind: 'bg-remind/20 text-remind',
  rose: 'bg-rose/20 text-rose',
}

const BADGE_TONE: Record<ActivityEntry['tone'], 'mint' | 'knowledge' | 'collab' | 'remind' | 'rose'> = {
  mint: 'mint',
  knowledge: 'knowledge',
  collab: 'collab',
  remind: 'remind',
  rose: 'rose',
}

/**
 * 活动记录 —— 数字人近期做过的事,按 5 类分类过滤后以时间流展示。
 * 只呈现工作相关活动(Skill 调用 / 协作 / Brief 生成 / 知识提交 / 用户确认),
 * 不展示成员私人对话或行为轨迹。
 */
export function ActivitySection() {
  const [filter, setFilter] = useState<Filter>('all')

  const visible = useMemo(
    () => (filter === 'all' ? ACTIVITY_LOG : ACTIVITY_LOG.filter((a) => a.category === filter)),
    [filter],
  )

  return (
    <div className="animate-fade-in space-y-6">
      <header>
        <h1 className="flex items-center gap-2.5 text-xl font-semibold text-white">
          <History className="h-5 w-5 text-mint-300" />
          活动记录
        </h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">
          数字人近期的工作活动。这里只记录工作相关行为,不涉及成员的私人对话与个人轨迹。
        </p>
      </header>

      {/* 分类 chip */}
      <div className="flex flex-wrap items-center gap-1.5">
        {CHIPS.map((c) => {
          const active = c.key === filter
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
            </button>
          )
        })}
      </div>

      {/* 时间流 */}
      {visible.length > 0 ? (
        <ol className="relative space-y-3">
          <span
            aria-hidden
            className="pointer-events-none absolute left-[19px] top-2 bottom-2 w-px bg-white/[0.06]"
          />
          {visible.map((a) => (
            <li key={a.id} className="relative pl-11">
              <span
                aria-hidden
                className={cn(
                  'absolute left-[12px] top-4 flex h-4 w-4 items-center justify-center rounded-full ring-4 ring-canvas',
                  DOT_TONE[a.tone],
                )}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
              </span>
              <div className="card-base p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={BADGE_TONE[a.tone]}>{ACTIVITY_CATEGORY_LABELS[a.category]}</Badge>
                  <span className="inline-flex items-center gap-1 text-[11.5px] text-slate-400">
                    <Clock className="h-3 w-3" />
                    {a.time}
                  </span>
                </div>
                <h3 className="mt-2 text-[14px] font-medium leading-relaxed text-slate-100">{a.title}</h3>
                {a.detail && <p className="mt-1 text-[12.5px] leading-relaxed text-slate-400">{a.detail}</p>}
                <p className="mt-2 text-[11.5px] text-slate-400">{a.actor}</p>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <div className="card-base flex flex-col items-center py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/[0.04] text-slate-400">
            <History className="h-5 w-5" />
          </span>
          <h3 className="mt-3 text-sm font-semibold text-slate-100">该分类下暂无活动</h3>
          <p className="mt-1 max-w-sm text-xs text-slate-400">切换到其他分类查看数字人的近期活动。</p>
        </div>
      )}
    </div>
  )
}
