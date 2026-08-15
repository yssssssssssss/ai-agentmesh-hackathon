import { BadgeCheck, Clock, FileText, FolderClock, Quote, Target } from 'lucide-react'

import type { KnowledgeAssetView } from '../../features/knowledge/presenter'
import { Badge } from '../ui/Badge'
import { DataSourceBadge } from '../ui/DataSourceBadge'

interface AssetCardProps {
  data: KnowledgeAssetView
  onClick: () => void
}

export function AssetCard({ data, onClick }: AssetCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex h-full w-full flex-col rounded-[12px] border border-white/[0.06] bg-surface-2 p-5 text-left transition-[transform,background-color,border-color] duration-150 active:scale-[0.98] hover:-translate-y-0.5 hover:border-white/[0.16] hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
    >
      <div className="flex w-full items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {data.kind === 'document' ? <FileText className="h-4 w-4 shrink-0 text-knowledge" /> : null}
            <h3 className="min-w-0 text-[15px] font-semibold leading-snug text-white">{data.title.value}</h3>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1"><Badge tone="knowledge">{TYPE_LABELS[data.type.value] ?? data.type.value}</Badge><DataSourceBadge source={data.type.source} /></span>
            {data.version.value !== null ? <span className="inline-flex items-center gap-1"><Badge tone="neutral">v{data.version.value}</Badge><DataSourceBadge source={data.version.source} /></span> : null}
            {data.hasNewFeedback.value ? <span className="inline-flex items-center gap-1"><Badge tone="remind" dot>有新反馈</Badge><DataSourceBadge source={data.hasNewFeedback.source} /></span> : null}
          </div>
        </div>
        <DataSourceBadge source={data.title.source} />
      </div>

      <div className="mt-2 flex items-start gap-2">
        <p className="line-clamp-3 min-w-0 flex-1 text-[13px] leading-5 text-slate-400">{data.conclusion.value}</p>
        {data.conclusion.source !== data.title.source ? <DataSourceBadge source={data.conclusion.source} /> : null}
      </div>

      <dl className="mt-4 w-full space-y-2 text-[12px] text-slate-500">
        <MetaLine icon={<Target className="h-3 w-3" />} label="适用范围" value={data.scope.value} source={data.scope.source} />
        <MetaLine icon={<FolderClock className="h-3 w-3" />} label="来源" value={data.sourceProject.value} source={data.sourceProject.source} />
        <MetaLine icon={<BadgeCheck className="h-3 w-3" />} label="验证" value={data.verified.value} source={data.verified.source} />
      </dl>

      <div className="mt-auto flex w-full flex-wrap items-center justify-between gap-3 border-t border-white/[0.05] pt-3 text-[11.5px] text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <Quote className="h-3 w-3" />
          被引用 <span className="font-medium tabular-nums text-slate-200">{data.citedBy.value}</span> 次
          <DataSourceBadge source={data.citedBy.source} />
        </span>
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatTime(data.updated.value)}
          <DataSourceBadge source={data.updated.source} />
        </span>
      </div>
    </button>
  )
}

function MetaLine({ icon, label, value, source }: {
  icon: React.ReactNode
  label: string
  value: string
  source: 'M' | 'T'
}) {
  return (
    <div className="flex items-start gap-1.5">
      <span className="mt-0.5 shrink-0 text-slate-500">{icon}</span>
      <dt className="shrink-0">{label}:</dt>
      <dd className="min-w-0 flex-1 truncate text-slate-400">{value}</dd>
      <DataSourceBadge source={source} />
    </div>
  )
}

const TYPE_LABELS: Record<string, string> = {
  design_rule: '设计规范',
  decision_method: '决策方法',
  project_experience: '项目经验',
  data_insight: '数据经验',
  workflow_method: '流程方法',
  risk_boundary: '风险与边界',
}


function formatTime(value: string) {
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString('zh-CN')
}
