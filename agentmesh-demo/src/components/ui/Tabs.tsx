import { cn } from '../../lib/cn'

export interface TabItem {
  key: string
  label: string
  count?: number
}

interface TabsProps {
  items: TabItem[]
  value: string
  onChange: (key: string) => void
  className?: string
}

/** 顶部分类 Tab，支持数量角标 */
export function Tabs({ items, value, onChange, className }: TabsProps) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1 rounded-[12px] border border-white/[0.06] bg-surface-1 p-1',
        className,
      )}
    >
      {items.map((item) => {
        const active = item.key === value
        return (
          <button
            key={item.key}
            onClick={() => onChange(item.key)}
            className={cn(
              'group relative inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-all duration-150',
               active
                 ? 'bg-mint-400/[0.12] text-mint-200'
                 : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]',
            )}
          >
            {item.label}
            {item.count !== undefined && (
              <span
                className={cn(
                  'inline-flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[11px] font-semibold tabular-nums transition-colors',
                   active
                     ? 'bg-mint-400/20 text-mint-300'
                     : 'bg-white/[0.06] text-slate-500',
                )}
              >
                {item.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
