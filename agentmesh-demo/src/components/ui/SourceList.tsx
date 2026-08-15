import { FileText } from 'lucide-react'
import type { components } from '../../api/generated/schema'

export type Source = components['schemas']['Source']

export function SourceList({ sources }: { sources?: Source[] }) {
  if (!sources || sources.length === 0) return null
  return (
    <div className="mt-3 border-t border-white/[0.05] pt-2.5" aria-label="来源">
      <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">来源</div>
      <ul className="space-y-1.5">
        {sources.map((source) => (
          <li key={source.id ?? `${source.source_type}:${source.reference}`} className="flex min-w-0 items-start gap-1.5 text-[11px] leading-5 text-slate-400">
            <FileText className="mt-1 h-3 w-3 shrink-0 text-slate-500" aria-hidden="true" />
            <span className="min-w-0">
              <span className="font-medium text-slate-300">{source.title}</span>
              <span className="ml-1.5 text-slate-600">{source.source_type}</span>
              <span className="block break-all text-slate-500">{source.reference}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
