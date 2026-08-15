import type { DataSourceKind, PresentedValue } from '../../lib/presentation'
import { DataSourceBadge } from '../ui/DataSourceBadge'

export function ModuleSourceBadges({ sources }: { sources: DataSourceKind[] }) {
  if (sources.length === 0) return null
  return (
    <span className="flex shrink-0 flex-wrap items-center justify-end gap-1.5" aria-label="模块数据来源">
      {sources.map((source) => <DataSourceBadge key={source} source={source} />)}
    </span>
  )
}

export function ValueSourceBadge({ value }: { value: PresentedValue<unknown> }) {
  return (
    <span className="inline-flex shrink-0" title={value.reason}>
      <DataSourceBadge source={value.source} />
    </span>
  )
}
