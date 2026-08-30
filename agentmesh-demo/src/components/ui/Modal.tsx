import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { cn } from '../../lib/cn'
import { useDialogFocus } from './useDialogFocus'

interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
  subtitle?: string
  children: ReactNode
  footer?: ReactNode
  size?: 'md' | 'lg' | 'workspace'
}

export function Modal({ open, onClose, title, subtitle, children, footer, size = 'md' }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useDialogFocus(open, dialogRef, onClose)
  useEffect(() => {
    if (!open) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : '对话框'}
        tabIndex={-1}
        className={cn(
          'relative z-10 flex max-h-[calc(100dvh-1rem)] w-full flex-col overflow-hidden rounded-overlay border border-white/[0.08] bg-surface-2 shadow-pop animate-scale-in',
          size === 'workspace'
            ? 'h-[calc(100dvh-1rem)] max-w-[calc(100vw-1rem)] sm:h-[86vh] sm:max-w-[94vw]'
            : size === 'lg' ? 'max-w-2xl' : 'max-w-lg',
        )}
      >
        {(title || subtitle) && (
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-white/[0.06] px-6 py-5">
            <div>
              {title && <h2 id={titleId} className="text-lg font-semibold text-white">{title}</h2>}
              {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
            </div>
            <button
              type="button"
              data-autofocus
              onClick={onClose}
              className="inline-flex h-10 w-10 shrink-0 touch-manipulation items-center justify-center rounded-lg text-slate-400 transition-[transform,background-color,color] duration-150 active:scale-[0.96] [@media(hover:hover)]:hover:bg-white/[0.06] [@media(hover:hover)]:hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
              aria-label="关闭"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </header>
        )}
        <div className={cn('min-h-0 overscroll-contain overflow-x-hidden overflow-y-auto px-4 py-4 sm:px-6 sm:py-5', size === 'workspace' ? 'flex-1' : 'max-h-[70vh]')}>{children}</div>
        {footer && (
          <footer className="flex shrink-0 items-center justify-end gap-3 border-t border-white/[0.06] bg-surface-1/60 px-6 py-4">
            {footer}
          </footer>
        )}
      </div>
    </div>
  )
}
