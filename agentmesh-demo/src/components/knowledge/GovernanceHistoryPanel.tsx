import { Archive, History } from 'lucide-react'

import type { MemoryGovernanceFilters } from '../../features/knowledge/api'
import type { KnowledgeAssetView } from '../../features/knowledge/presenter'
import { Badge } from '../ui/Badge'
import { DataSourceBadge } from '../ui/DataSourceBadge'

interface Props {
  items: KnowledgeAssetView[]
  filters: MemoryGovernanceFilters
  total: number
  hasNext: boolean
  onFiltersChange: (filters: MemoryGovernanceFilters) => void
  onPageChange: (page: number) => void
  onOpen: (item: KnowledgeAssetView) => void
}

function FilterSelect({ label, value, onChange, options }: {
  label: string
  value: string
  onChange: (value: string) => void
  options: Record<string, string>
}) {
  return (
    <label className="block min-w-36 text-[11px] font-medium uppercase tracking-wide text-slate-400">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 h-10 w-full rounded-soft border border-white/[0.08] bg-surface-2 px-3 text-sm text-slate-200 outline-none transition-[border-color,box-shadow] focus:border-mint-400/60 focus:ring-2 focus:ring-mint-400/15"
      >
        {Object.entries(options).map(([option, optionLabel]) => (
          <option key={option} value={option}>{optionLabel}</option>
        ))}
      </select>
    </label>
  )
}

const SCOPE_LABELS: Record<string, string> = {
  all: '全部范围',
  team_accepted: '团队知识',
  team_candidate: '团队候选',
  project: '项目范围',
}

const KIND_LABELS: Record<string, string> = {
  all: '全部类型',
  team_knowledge: '团队知识',
  team_candidate: '团队候选',
  legacy_shared: 'Legacy 共享',
}

const LAYER_LABELS: Record<string, string> = {
  all: '全部层级',
  short_term: '短期',
  mid_term: '中期',
  long_term: '长期',
}

const STATUS_LABELS: Record<string, string> = {
  all: '全部状态',
  disputed: '存在争议',
  deprecated: '已废弃',
  expired: '已失效',
  archived: '已归档',
}

export function GovernanceHistoryPanel({
  items,
  filters,
  total,
  hasNext,
  onFiltersChange,
  onPageChange,
  onOpen,
}: Props) {
  const setFilter = <Key extends 'status' | 'scope' | 'kind' | 'layer'>(
    key: Key,
    value: MemoryGovernanceFilters[Key],
  ) => onFiltersChange({ ...filters, [key]: value, page: 1 })

  return (
    <section className="animate-fade-in space-y-4" aria-labelledby="memory-governance-history-heading">
      <div className="flex flex-wrap items-end justify-between gap-3 rounded-soft border border-white/[0.06] bg-surface-1 p-4">
        <div>
          <div className="flex items-center gap-2 text-slate-100">
            <History className="h-4 w-4 text-mint-300" aria-hidden="true" />
            <h2 id="memory-governance-history-heading" className="text-sm font-semibold">记忆治理历史</h2>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-400">查看争议、废弃、失效和归档版本；重新激活内容必须通过修订与独立审核。</p>
        </div>
        <div className="grid w-full gap-3 sm:grid-cols-2 xl:w-auto xl:grid-cols-4">
          <FilterSelect label="生命周期状态" value={filters.status} onChange={(value) => setFilter('status', value as MemoryGovernanceFilters['status'])} options={STATUS_LABELS} />
          <FilterSelect label="范围" value={filters.scope} onChange={(value) => setFilter('scope', value as MemoryGovernanceFilters['scope'])} options={SCOPE_LABELS} />
          <FilterSelect label="类型" value={filters.kind} onChange={(value) => setFilter('kind', value as MemoryGovernanceFilters['kind'])} options={KIND_LABELS} />
          <FilterSelect label="层级" value={filters.layer} onChange={(value) => setFilter('layer', value as MemoryGovernanceFilters['layer'])} options={LAYER_LABELS} />
        </div>
      </div>

      {items.length > 0 ? (
        <div className="divide-y divide-white/[0.06] overflow-hidden rounded-soft bg-surface-1">
          {items.map((item) => (
            <button
              key={item.id.value}
              type="button"
              onClick={() => onOpen(item)}
              className="flex min-h-20 w-full items-center gap-4 px-4 py-3 text-left transition-colors active:scale-[0.99] hover:bg-white/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-mint-400/50"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-soft bg-white/[0.04] text-slate-400">
                <Archive className="h-4 w-4" aria-hidden="true" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold text-slate-100">{item.title.value}</span>
                  <Badge tone="neutral">{STATUS_LABELS[item.status.value] ?? item.status.value}</Badge>
                  <DataSourceBadge source={item.status.source} />
                </span>
                <span className="mt-1 block line-clamp-2 text-xs leading-5 text-slate-400">{item.conclusion.value}</span>
              </span>
              <span className="shrink-0 text-right text-[11px] text-slate-400">
                <span className="block tabular-nums">v{item.version.value ?? 1}</span>
                <span className="mt-1 block">查看血缘</span>
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="card-base py-12 text-center text-sm text-slate-400">当前筛选下没有治理历史。</div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400">
        <span>共 <span className="tabular-nums text-slate-200">{total}</span> 条，当前第 {filters.page} 页</span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={filters.page <= 1}
            onClick={() => onPageChange(filters.page - 1)}
            className="min-h-10 rounded-control px-3 transition-colors active:scale-[0.98] hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-40"
          >
            上一页
          </button>
          <button
            type="button"
            disabled={!hasNext}
            onClick={() => onPageChange(filters.page + 1)}
            className="min-h-10 rounded-control px-3 transition-colors active:scale-[0.98] hover:bg-white/[0.04] disabled:cursor-not-allowed disabled:opacity-40"
          >
            下一页
          </button>
        </div>
      </div>
    </section>
  )
}
