import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { cn } from '../../lib/cn'

interface DrawerProps {
  open: boolean
  onClose: () => void
  title?: string
  subtitle?: string
  icon?: ReactNode
  children: ReactNode
  footer?: ReactNode
  headerAction?: ReactNode
  width?: number
}

/** 右侧滑出抽屉，用于协作详情、数字人档案等 */
export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  icon,
  children,
  footer,
  headerAction,
  width = 460,
}: DrawerProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/55 backdrop-blur-sm animate-fade-in" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        className={cn(
          'absolute inset-y-0 right-0 flex flex-col border-l border-white/[0.08] bg-surface-2 shadow-pop animate-slide-in',
        )}
        style={{ width, maxWidth: '92vw' }}
      >
        <header className="flex items-start justify-between gap-4 border-b border-white/[0.06] px-6 py-5">
          <div className="flex items-start gap-3">
            {icon && (
              <span className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-[10px] bg-mint-400/12 text-mint-300">
                {icon}
              </span>
            )}
            <div>
              {title && <h2 className="text-[17px] font-semibold text-white">{title}</h2>}
              {subtitle && <p className="mt-0.5 text-sm text-slate-400">{subtitle}</p>}
            </div>
          </div>
          <div className="flex items-center gap-1">
            {headerAction}
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
            aria-label="关闭"
          >
            <X className="h-5 w-5" />
          </button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && (
          <footer className="border-t border-white/[0.06] bg-surface-1/60 px-6 py-4">{footer}</footer>
        )}
      </aside>
    </div>
  )
}
