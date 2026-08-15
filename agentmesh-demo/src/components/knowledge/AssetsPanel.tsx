import { useMemo, useState } from 'react'
import { ArrowUpDown, BookMarked } from 'lucide-react'

import type { KnowledgeAssetView } from '../../features/knowledge/presenter'
import type { PresentedValue } from '../../lib/presentation'
import { cn } from '../../lib/cn'
import { DataSourceBadge } from '../ui/DataSourceBadge'
import { AssetCard } from './AssetCard'

type UsageFilter = 'all' | 'unused' | 'cited' | 'feedback'
type SortKey = 'updated' | 'cited'

interface Props {
  assets: KnowledgeAssetView[]
  totalCount: PresentedValue<number>
  onOpenAsset: (asset: KnowledgeAssetView) => void
}

export function AssetsPanel({ assets, totalCount, onOpenAsset }: Props) {
  const [typeFilter, setTypeFilter] = useState('all')
  const [visibilityFilter, setVisibilityFilter] = useState('all')
  const [usageFilter, setUsageFilter] = useState<UsageFilter>('all')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [sortKey, setSortKey] = useState<SortKey>('updated')

  const typeOptions = useMemo(
    () => ['all', ...new Set(assets.map((asset) => asset.type.value))],
    [assets],
  )
  const sourceOptions = useMemo(
    () => ['all', ...new Set(assets.map((asset) => asset.sourceProject.value))],
    [assets],
  )
  const visibilityOptions = useMemo(
    () => ['all', ...new Set(assets.map((asset) => asset.visibility.value))],
    [assets],
  )

  const filtered = useMemo(() => {
    const matches = assets.filter((asset) => {
      if (typeFilter !== 'all' && asset.type.value !== typeFilter) return false
      if (visibilityFilter !== 'all' && asset.visibility.value !== visibilityFilter) return false
      if (sourceFilter !== 'all' && asset.sourceProject.value !== sourceFilter) return false
      if (usageFilter === 'unused' && asset.citedBy.value > 0) return false
      if (usageFilter === 'cited' && asset.citedBy.value === 0) return false
      if (usageFilter === 'feedback' && !asset.hasNewFeedback.value) return false
      return true
    })
    return [...matches].sort((left, right) => {
      if (sortKey === 'cited') return right.citedBy.value - left.citedBy.value
      return timeWeight(right.updated.value) - timeWeight(left.updated.value)
    })
  }, [assets, sourceFilter, sortKey, typeFilter, usageFilter, visibilityFilter])

  const activeFilters = [typeFilter, visibilityFilter, sourceFilter].filter((value) => value !== 'all').length
    + (usageFilter === 'all' ? 0 : 1)
  const clearFilters = () => {
    setTypeFilter('all')
    setVisibilityFilter('all')
    setUsageFilter('all')
    setSourceFilter('all')
  }

  return (
    <div className="animate-fade-in space-y-5">
      <div className="space-y-3" aria-label="知识筛选">
        <FilterRow label="类型">
          <ChipGroup options={typeOptions} value={typeFilter} onChange={setTypeFilter} label={(value) => TYPE_LABELS[value] ?? value} />
        </FilterRow>
        <FilterRow label="来源项目">
          <ChipGroup options={sourceOptions} value={sourceFilter} onChange={setSourceFilter} label={(value) => value === 'all' ? '全部来源' : value} />
        </FilterRow>
        <FilterRow label="可见范围">
          <ChipGroup options={visibilityOptions} value={visibilityFilter} onChange={setVisibilityFilter} label={(value) => VISIBILITY_LABELS[value] ?? value} />
        </FilterRow>
        <FilterRow label="使用状态">
          <ChipGroup options={['all', 'unused', 'cited', 'feedback']} value={usageFilter} onChange={(value) => setUsageFilter(value as UsageFilter)} label={(value) => USAGE_LABELS[value] ?? value} />
        </FilterRow>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4 text-xs text-slate-500">
        <div className="flex flex-wrap items-center gap-2">
          <span>共 <span className="tabular-nums text-slate-300">{totalCount.value}</span> 条已沉淀知识</span>
          <DataSourceBadge source={totalCount.source} />
          {activeFilters > 0 ? (
            <>
              <span>当前筛选出 <span className="tabular-nums text-slate-300">{filtered.length}</span> 条</span>
              <button type="button" onClick={clearFilters} className="rounded px-1 py-1 text-mint-300 hover:text-mint-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">清空筛选</button>
            </>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => setSortKey((value) => value === 'updated' ? 'cited' : 'updated')}
          className="inline-flex min-h-10 items-center gap-1.5 rounded-[8px] px-3 text-slate-400 transition-colors active:scale-[0.98] hover:bg-white/[0.04] hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
        >
          <ArrowUpDown className="h-3.5 w-3.5" />
          {sortKey === 'cited' ? '按引用数排序' : '按更新时间排序'}
        </button>
      </div>

      {filtered.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((asset) => (
            <AssetCard key={`${asset.kind}-${asset.id.value}`} data={asset} onClick={() => onOpenAsset(asset)} />
          ))}
        </div>
      ) : (
        <div className="card-base flex flex-col items-center py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/[0.04] text-slate-500"><BookMarked className="h-5 w-5" /></span>
          <h3 className="mt-3 text-sm font-semibold text-slate-100">没有匹配的知识</h3>
          <p className="mt-1 max-w-sm text-xs text-slate-500">调整筛选条件，或等待真实工作与项目复盘形成新的知识资产。</p>
        </div>
      )}
    </div>
  )
}

function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="min-w-[64px] text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

function ChipGroup({ options, value, onChange, label }: {
  options: string[]
  value: string
  onChange: (value: string) => void
  label: (value: string) => string
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const active = option === value
        return (
          <button
            key={option}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option)}
            className={cn(
              'min-h-10 rounded-full border px-3 py-1.5 text-xs transition-[transform,background-color,border-color,color] active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50',
              active
                ? 'border-mint-400/40 bg-mint-400/[0.12] text-mint-200'
                : 'border-white/[0.06] bg-surface-1 text-slate-400 hover:border-white/[0.12] hover:text-slate-200',
            )}
          >
            {label(option)}
          </button>
        )
      })}
    </div>
  )
}

const TYPE_LABELS: Record<string, string> = {
  all: '全部类型',
  design_rule: '设计规范',
  decision_method: '决策方法',
  project_experience: '项目经验',
  data_insight: '数据经验',
  workflow_method: '流程方法',
  risk_boundary: '风险与边界',
}

const VISIBILITY_LABELS: Record<string, string> = {
  all: '全部范围',
  private: '仅自己',
  project: '当前项目',
  team: '团队共享',
}

const USAGE_LABELS: Record<string, string> = {
  all: '全部状态',
  unused: '尚未引用',
  cited: '已被引用',
  feedback: '有新反馈',
}


function timeWeight(value: string) {
  const parsed = Date.parse(value)
  if (!Number.isNaN(parsed)) return parsed
  const dayMatch = /(\d+)\s*天前/.exec(value)
  if (dayMatch) return Date.now() - Number(dayMatch[1]) * 86_400_000
  const weekMatch = /(\d+)\s*周前/.exec(value)
  if (weekMatch) return Date.now() - Number(weekMatch[1]) * 604_800_000
  const monthMatch = /(\d+)\s*月前/.exec(value)
  if (monthMatch) return Date.now() - Number(monthMatch[1]) * 2_592_000_000
  return 0
}
