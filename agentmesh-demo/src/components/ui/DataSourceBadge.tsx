import type { DataSourceKind } from '../../lib/presentation'
import { Badge } from './Badge'

interface DataSourceBadgeProps {
  source: DataSourceKind
}

const PRESENTATION: Record<DataSourceKind, { label: string; tone: 'mint' | 'remind' }> = {
  T: { label: 'T数据', tone: 'mint' },
  M: { label: 'M数据', tone: 'remind' },
}

export function DataSourceBadge({ source }: DataSourceBadgeProps) {
  const { label, tone } = PRESENTATION[source]
  return (
    <span role="note" aria-label={label} data-tone={tone} className="inline-flex">
      <Badge tone={tone}>{label}</Badge>
    </span>
  )
}
