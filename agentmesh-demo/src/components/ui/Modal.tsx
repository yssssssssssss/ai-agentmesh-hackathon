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
        autoFocus
        className={cn(
          'relative z-10 flex w-full flex-col overflow-hidden rounded-[16px] border border-white/[0.08] bg-surface-2 shadow-pop animate-scale-in',
          size === 'workspace'
            ? 'h-[calc(100dvh-1rem)] max-w-[calc(100vw-1rem)] sm:h-[86vh] sm:max-w-[94vw]'
            : size === 'lg' ? 'max-w-2xl' : 'max-w-lg',
        )}
      >
        {(title || subtitle) && (
          <header className="flex items-start justify-between gap-4 border-b border-white/[0.06] px-6 py-5">
            <div>
              {title && <h2 id={titleId} className="text-lg font-semibold text-white">{title}</h2>}
              {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
            </div>
            <button
              type="button"
              data-autofocus
              onClick={onClose}
              className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-white"
              aria-label="关闭"
            >
              <X className="h-5 w-5" />
            </button>
          </header>
        )}
        <div className={cn('overflow-x-hidden overflow-y-auto px-4 py-4 sm:px-6 sm:py-5', size === 'workspace' ? 'min-h-0 flex-1' : 'max-h-[70vh]')}>{children}</div>
        {footer && (
          <footer className="flex items-center justify-end gap-3 border-t border-white/[0.06] bg-surface-1/60 px-6 py-4">
            {footer}
          </footer>
        )}
      </div>
    </div>
  )
}
