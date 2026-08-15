import { Clock, FolderClock } from 'lucide-react'

import { Badge } from '../ui/Badge'
import { SourceList, type Source } from '../ui/SourceList'
export interface KnowledgeCardData {
  id: string
  title: string
  summary: string
  memoryType: string
  scope: string
  project: string
  updated?: string
  sources?: Source[]
}

interface KnowledgeCardProps {
  data: KnowledgeCardData
  accent?: 'mint' | 'knowledge' | 'default'
  actions?: React.ReactNode
}

const ACCENT: Record<NonNullable<KnowledgeCardProps['accent']>, string> = {
  mint: 'border-mint-400/20',
  knowledge: 'border-knowledge/20',
  default: 'border-white/[0.06]',
}

export function KnowledgeCard({ data, accent = 'default', actions }: KnowledgeCardProps) {
  return (
    <article className={`flex h-full flex-col rounded-[12px] border bg-surface-2 p-4 ${ACCENT[accent]}`}>
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold leading-snug text-slate-100">{data.title}</h3>
        <Badge tone={accent === 'mint' ? 'mint' : accent === 'knowledge' ? 'knowledge' : 'neutral'}>
          {data.scope}
        </Badge>
      </div>
      <p className="mt-2 flex-1 text-[13px] leading-relaxed text-slate-400">{data.summary}</p>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <Badge tone="neutral">{data.memoryType}</Badge>
      </div>
      <SourceList sources={data.sources} />
      <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-white/[0.05] pt-2.5 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1">
          <FolderClock className="h-3 w-3" />
          {data.project}
        </span>
        {data.updated ? (
          <span className="inline-flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {new Date(data.updated).toLocaleString('zh-CN')}
          </span>
        ) : null}
      </div>
      {actions ? <div className="mt-3 flex flex-wrap gap-2">{actions}</div> : null}
    </article>
  )
}
