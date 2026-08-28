import { CheckCircle2, Info, X } from 'lucide-react'
import { useDemo } from '../../store/DemoContext'

/** 全局 Toast 展示层，固定右下角 */
export function ToastViewport() {
  const { toasts, dismissToast } = useDemo()
  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-[60] flex w-[360px] max-w-[90vw] flex-col gap-3">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="pointer-events-auto flex items-start gap-3 rounded-soft border border-white/[0.08] bg-surface-3 px-4 py-3.5 shadow-pop animate-slide-in"
        >
          <span className={t.tone === 'success' ? 'text-mint-300' : 'text-knowledge'}>
            {t.tone === 'success' ? (
              <CheckCircle2 className="h-5 w-5" />
            ) : (
              <Info className="h-5 w-5" />
            )}
          </span>
          <p className="flex-1 text-sm leading-relaxed text-slate-100">{t.message}</p>
          <button
            onClick={() => dismissToast(t.id)}
            className="rounded p-0.5 text-slate-400 transition-colors hover:text-slate-200"
            aria-label="关闭提示"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  )
}
