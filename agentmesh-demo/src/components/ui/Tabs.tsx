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
  function selectByKeyboard(event: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    const keyTarget = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? items.length - 1
        : event.key === 'ArrowRight'
          ? (index + 1) % items.length
          : event.key === 'ArrowLeft'
            ? (index - 1 + items.length) % items.length
            : null
    if (keyTarget === null) return
    event.preventDefault()
    onChange(items[keyTarget].key)
    const tabs = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
    tabs?.[keyTarget]?.focus()
  }

  return (
    <div
      role="tablist"
      aria-label="标签页"
      className={cn(
        'inline-flex items-center gap-1 rounded-[12px] border border-white/[0.06] bg-surface-1 p-1',
        className,
      )}
    >
      {items.map((item, index) => {
        const active = item.key === value
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(item.key)}
            onKeyDown={(event) => selectByKeyboard(event, index)}
            className={cn(
              'group relative inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-all duration-150',
              active
                ? 'bg-surface-3 text-white shadow-sm'
                : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200',
            )}
          >
            {item.label}
            {item.count !== undefined ? (
              <span
                className={cn(
                  'inline-flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[11px] font-semibold tabular-nums transition-colors',
                  active
                    ? item.count > 0
                      ? 'bg-mint-400/20 text-mint-300'
                      : 'bg-white/10 text-slate-400'
                    : 'bg-white/[0.06] text-slate-500',
                )}
              >
                {item.count}
              </span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}
