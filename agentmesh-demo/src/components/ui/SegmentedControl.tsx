import { cn } from '../../lib/cn'

export interface SegmentOption {
  key: string
  label: string
}

interface SegmentedControlProps {
  options: SegmentOption[]
  value: string
  onChange: (key: string) => void
  size?: 'sm' | 'md'
}

/** 分段切换控件，用于时间范围（今日/本周/本月）等 */
export function SegmentedControl({ options, value, onChange, size = 'md' }: SegmentedControlProps) {
  return (
    <div className="inline-flex rounded-[10px] border border-white/[0.06] bg-surface-1 p-0.5">
      {options.map((opt) => {
        const active = opt.key === value
        return (
          <button
            key={opt.key}
            onClick={() => onChange(opt.key)}
            className={cn(
              'rounded-lg font-medium transition-all duration-150',
              size === 'sm' ? 'px-3 py-1.5 text-[13px]' : 'px-4 py-2 text-sm',
              active
                ? 'bg-surface-3 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200',
            )}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
