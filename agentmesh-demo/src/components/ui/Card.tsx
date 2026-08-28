import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'

interface CardProps {
  children: ReactNode
  className?: string
  hover?: boolean
  onClick?: () => void
  padding?: 'none' | 'sm' | 'md' | 'lg'
}

const PAD: Record<NonNullable<CardProps['padding']>, string> = {
  none: '',
  sm: 'p-4',
  md: 'p-5',
  lg: 'p-6',
}

export function Card({ children, className, hover, onClick, padding = 'md' }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'card-base',
        PAD[padding],
        hover &&
          'transition-[transform,background-color,border-color] duration-200 [@media(hover:hover)]:hover:border-white/[0.12] [@media(hover:hover)]:hover:bg-surface-2 [@media(hover:hover)]:hover:-translate-y-0.5',
        onClick && 'cursor-pointer',
        className,
      )}
    >
      {children}
    </div>
  )
}

interface SectionCardProps {
  title: string
  icon?: ReactNode
  action?: ReactNode
  desc?: string
  children: ReactNode
  className?: string
  bodyClassName?: string
}

/** 带标题栏的区块卡片，用于建立清晰的标题层级 */
export function SectionCard({
  title,
  icon,
  action,
  desc,
  children,
  className,
  bodyClassName,
}: SectionCardProps) {
  return (
    <section className={cn('card-base p-5', className)}>
      <header className="mb-4 flex items-start justify-between gap-4">
        <div className="flex items-center gap-2.5">
          {icon && <span className="text-mint-300">{icon}</span>}
          <div>
            <h2 className="text-[15px] font-semibold text-slate-100">{title}</h2>
            {desc && <p className="mt-0.5 text-xs text-slate-400">{desc}</p>}
          </div>
        </div>
        {action}
      </header>
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}
