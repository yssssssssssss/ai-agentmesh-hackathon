import { useMemo, useState } from 'react'
import { ArrowUpDown, BookMarked, ChevronDown } from 'lucide-react'
import { AssetCard } from './AssetCard'
import { cn } from '../../lib/cn'
import {
  KNOWLEDGE_TYPE_LABELS,
  type KnowledgeAsset,
  type KnowledgeType,
  type Visibility,
} from '../../data/mockData'

type UsageFilter = 'all' | 'unused' | 'cited' | 'feedback'
type VisibilityFilter = 'all' | Visibility
type TypeFilter = 'all' | KnowledgeType
type SortKey = 'default' | 'updated' | 'cited'

const TYPE_CHIPS: { key: TypeFilter; label: string }[] = [
  { key: 'all', label: '全部类型' },
  { key: 'design_rule', label: KNOWLEDGE_TYPE_LABELS.design_rule },
  { key: 'decision_method', label: KNOWLEDGE_TYPE_LABELS.decision_method },
  { key: 'project_experience', label: KNOWLEDGE_TYPE_LABELS.project_experience },
  { key: 'data_insight', label: '数据经验' },
  { key: 'workflow_method', label: KNOWLEDGE_TYPE_LABELS.workflow_method },
]

const VISIBILITY_CHIPS: { key: VisibilityFilter; label: string }[] = [
  { key: 'all', label: '全部权限' },
  { key: 'private', label: '仅自己' },
  { key: 'project', label: '当前项目' },
  { key: 'team', label: '已共享给团队' },
]

const USAGE_CHIPS: { key: UsageFilter; label: string }[] = [
  { key: 'all', label: '全部状态' },
  { key: 'unused', label: '尚未引用' },
  { key: 'cited', label: '已被引用' },
  { key: 'feedback', label: '有新反馈' },
]

interface Props {
  assets: KnowledgeAsset[]
  /** 顶部 tab 显示的总数(24 → 25)。用作空态时的对比数据。 */
  totalCount: number
  onOpenAsset: (asset: KnowledgeAsset) => void
}

/**
 * Tab 1 · 知识资产:
 *   搜索 + 类型 / 来源 / 权限 / 使用状态筛选 + 排序 + 卡片网格。
 * 只包含真实展示的资产;顶部计数与 assets 数量的差异由"其他历史资产"隐性承担。
 */
export function AssetsPanel({ assets, totalCount, onOpenAsset }: Props) {
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [visibilityFilter, setVisibilityFilter] = useState<VisibilityFilter>('all')
  const [usageFilter, setUsageFilter] = useState<UsageFilter>('all')
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [visibilityOpen, setVisibilityOpen] = useState(false)
  const [usageOpen, setUsageOpen] = useState(false)
  const [sortOpen, setSortOpen] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('default')

  const sourceOptions = useMemo(() => {
    const set = new Set<string>()
    assets.forEach((a) => set.add(a.sourceProject))
    return ['all', ...Array.from(set)]
  }, [assets])

  const filtered = useMemo(() => {
    return assets
      .filter((a) => {
        if (typeFilter !== 'all' && a.type !== typeFilter) return false
        if (visibilityFilter !== 'all' && a.visibility !== visibilityFilter) return false
        if (usageFilter === 'unused' && a.citedBy > 0) return false
        if (usageFilter === 'cited' && a.citedBy === 0) return false
        if (usageFilter === 'feedback' && !a.hasNewFeedback) return false
        if (sourceFilter !== 'all' && a.sourceProject !== sourceFilter) return false
        return true
      })
      .sort((a, b) => {
        // 刚沉淀的永远排最前(即使按其他排序)
        if (a.justConfirmed && !b.justConfirmed) return -1
        if (!a.justConfirmed && b.justConfirmed) return 1
        if (sortKey === 'cited') return b.citedBy - a.citedBy
        if (sortKey === 'updated') return updatedWeight(a.updated) - updatedWeight(b.updated)
        // 默认排序：刚沉淀优先，其余按最近更新时间。
        return updatedWeight(a.updated) - updatedWeight(b.updated)
      })
  }, [assets, typeFilter, visibilityFilter, usageFilter, sourceFilter, sortKey])

  const activeFilters =
    (typeFilter !== 'all' ? 1 : 0) +
    (visibilityFilter !== 'all' ? 1 : 0) +
    (usageFilter !== 'all' ? 1 : 0) +
    (sourceFilter !== 'all' ? 1 : 0)

  return (
    <div className="animate-fade-in space-y-5">
      {/* ── 类型 / 权限 / 使用状态 / 来源 ── */}
      <div className="space-y-2.5">
        <FilterRow label="类型">
          <ChipGroup
            options={TYPE_CHIPS}
            value={typeFilter}
            onChange={(k) => setTypeFilter(k as TypeFilter)}
          />
        </FilterRow>
        <FilterRow label="来源项目">
          <ChipGroup
            options={sourceOptions.map((source) => ({ key: source, label: source === 'all' ? '全部来源' : source }))}
            value={sourceFilter}
            onChange={setSourceFilter}
          />
        </FilterRow>

      </div>

      {/* ── 内容工具栏：结果数量 / 权限下拉 / 排序逻辑 ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4 text-xs text-slate-500">
        <span>
          共 <span className="tabular-nums text-slate-300">{totalCount}</span> 条已沉淀知识
          {activeFilters > 0 && (
            <>
              {' · 当前筛选出'}
              <span className="ml-1 tabular-nums text-slate-300">{filtered.length}</span>
              {' 条 · '}
              <button
                onClick={() => {
                  setTypeFilter('all')
                  setVisibilityFilter('all')
                  setUsageFilter('all')
                  setSourceFilter('all')
                }}
                className="text-mint-300 hover:text-mint-200"
              >
                清空筛选
              </button>
            </>
          )}
        </span>
        <div className="flex items-center gap-2">
          <div className="relative">
            <button
              type="button"
              onClick={() => setUsageOpen((value) => !value)}
              className="inline-flex items-center gap-1.5 rounded-[8px] px-2.5 py-1.5 text-slate-400 transition-colors hover:bg-white/[0.04] hover:text-slate-200"
            >
              {USAGE_CHIPS.find((item) => item.key === usageFilter)?.label ?? '全部状态'}
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', usageOpen && 'rotate-180')} />
            </button>
            {usageOpen && (
              <div className="absolute right-0 top-full z-20 mt-1 min-w-[140px] rounded-[10px] border border-white/[0.08] bg-surface-2 p-1 shadow-pop">
                {USAGE_CHIPS.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      setUsageFilter(item.key)
                      setUsageOpen(false)
                    }}
                    className={cn(
                      'block w-full rounded-[7px] px-3 py-2 text-left text-[12px] transition-colors',
                      usageFilter === item.key ? 'bg-mint-400/[0.12] text-mint-300' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200',
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="relative">
            <button
              type="button"
              onClick={() => setVisibilityOpen((value) => !value)}
              className="inline-flex items-center gap-1.5 rounded-[8px] px-2.5 py-1.5 text-slate-400 transition-colors hover:bg-white/[0.04] hover:text-slate-200"
            >
              {VISIBILITY_CHIPS.find((item) => item.key === visibilityFilter)?.label ?? '全部权限'}
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', visibilityOpen && 'rotate-180')} />
            </button>
            {visibilityOpen && (
              <div className="absolute right-0 top-full z-20 mt-1 min-w-[150px] rounded-[10px] border border-white/[0.08] bg-surface-2 p-1 shadow-pop">
                {VISIBILITY_CHIPS.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      setVisibilityFilter(item.key)
                      setVisibilityOpen(false)
                    }}
                    className={cn(
                      'block w-full rounded-[7px] px-3 py-2 text-left text-[12px] transition-colors',
                      visibilityFilter === item.key ? 'bg-mint-400/[0.12] text-mint-300' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200',
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="relative">
            <button
              type="button"
              onClick={() => setSortOpen((value) => !value)}
              className="inline-flex items-center gap-1.5 rounded-[8px] px-2.5 py-1.5 text-slate-400 transition-colors hover:bg-white/[0.04] hover:text-slate-200"
            >
              <ArrowUpDown className="h-3.5 w-3.5" />
              {sortKey === 'updated' ? '时间排序' : sortKey === 'cited' ? '引用数排序' : '默认排序'}
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', sortOpen && 'rotate-180')} />
            </button>
            {sortOpen && (
              <div className="absolute right-0 top-full z-20 mt-1 min-w-[140px] rounded-[10px] border border-white/[0.08] bg-surface-2 p-1 shadow-pop">
                {([
                  { key: 'default', label: '默认排序' },
                  { key: 'updated', label: '时间排序' },
                  { key: 'cited', label: '引用数排序' },
                ] as { key: SortKey; label: string }[]).map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      setSortKey(item.key)
                      setSortOpen(false)
                    }}
                    className={cn(
                      'block w-full rounded-[7px] px-3 py-2 text-left text-[12px] transition-colors',
                      sortKey === item.key ? 'bg-mint-400/[0.12] text-mint-300' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200',
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── 卡片网格 ── */}
      {filtered.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((a) => (
            <AssetCard key={a.id} data={a} onClick={() => onOpenAsset(a)} />
          ))}
        </div>
      ) : (
        <div className="card-base flex flex-col items-center py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/[0.04] text-slate-500">
            <BookMarked className="h-5 w-5" />
          </span>
          <h3 className="mt-3 text-sm font-semibold text-slate-100">没有匹配的知识</h3>
          <p className="mt-1 max-w-sm text-xs text-slate-500">
            调整搜索关键词或筛选条件试试。知识来源于真实工作或项目复盘,AI 生成的方案建议不能直接称为知识。
          </p>
        </div>
      )}
    </div>
  )
}

/* ---------- 单行筛选(左侧 label + 右侧 chip 组) ---------- */
function FilterRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="min-w-[64px] text-[11px] font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

/* ---------- 可复用 chip 组 ---------- */
function ChipGroup<T extends string>({
  options,
  value,
  onChange,
  size = 'md',
}: {
  options: { key: T; label: string }[]
  value: T
  onChange: (k: T) => void
  size?: 'sm' | 'md'
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const active = o.key === value
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            className={cn(
              'rounded-full border transition-colors',
              size === 'sm' ? 'px-2.5 py-1 text-[11.5px]' : 'px-3 py-1.5 text-xs',
              active
                ? 'border-mint-400/40 bg-mint-400/[0.12] text-mint-200'
                : 'border-white/[0.06] bg-surface-1 text-slate-400 hover:border-white/[0.12] hover:text-slate-200',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/**
 * 极简"最近程度"权重:数字越小越"最近"。刚刚 < 今天 < X 天前 < 本周 < X 周前 < X 月前 < 更久
 * demo 场景够用;真实产品应使用时间戳。
 */
function updatedWeight(s: string): number {
  if (!s) return 999
  if (s.includes('刚刚')) return 0
  if (s.includes('今天')) return 1
  const dayMatch = /(\d+)\s*天前/.exec(s)
  if (dayMatch) return 10 + Number(dayMatch[1])
  if (s.includes('本周')) return 30
  const weekMatch = /(\d+)\s*周前/.exec(s)
  if (weekMatch) return 40 + Number(weekMatch[1])
  const monthMatch = /(\d+)\s*月前/.exec(s)
  if (monthMatch) return 100 + Number(monthMatch[1])
  return 200
}
