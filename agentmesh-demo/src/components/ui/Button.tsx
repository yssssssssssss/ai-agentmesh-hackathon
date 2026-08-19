import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '../../lib/cn'

type Variant = 'primary' | 'secondary' | 'ghost' | 'subtle' | 'danger'
type Size = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
  iconRight?: ReactNode
  block?: boolean
}

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-mint-400 text-[#04241c] font-semibold hover:bg-mint-300 active:bg-mint-500 shadow-[0_6px_20px_-8px_rgba(45,212,168,0.6)]',
  secondary:
    'bg-surface-3 text-slate-100 hover:bg-surface-4 border border-white/[0.08] active:bg-surface-3',
  ghost:
    'bg-transparent text-slate-300 hover:bg-white/[0.06] hover:text-white active:bg-white/[0.04]',
  subtle:
    'bg-white/[0.04] text-slate-300 hover:bg-white/[0.08] border border-white/[0.06] active:bg-white/[0.05]',
  danger:
    'bg-rose/15 text-rose hover:bg-rose/25 border border-rose/25 active:bg-rose/20',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px] gap-1.5 rounded-lg',
  md: 'h-10 px-4 text-sm gap-2 rounded-[10px]',
  lg: 'h-12 px-6 text-[15px] gap-2 rounded-[12px]',
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  iconRight,
  block,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap transition-[transform,background-color,color,border-color,box-shadow] duration-150 active:scale-[0.96] select-none',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50',
        'disabled:opacity-45 disabled:cursor-not-allowed disabled:hover:bg-inherit',
        VARIANTS[variant],
        SIZES[size],
        block && 'w-full',
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        icon && <span className="shrink-0">{icon}</span>
      )}
      {children}
      {iconRight && !loading && <span className="shrink-0">{iconRight}</span>}
    </button>
  )
}
