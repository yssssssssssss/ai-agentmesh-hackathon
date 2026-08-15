import { Info } from 'lucide-react'

export function UnderstandingList() {
  return (
    <section className="rounded-[12px] border border-white/[0.06] bg-surface-1 p-4 text-sm text-slate-400">
      <div className="flex items-start gap-3">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-mint-300" aria-hidden="true" />
        <p>数字人理解在 MVP 中仅由服务端工作记录形成，不提供本地编辑或偏好保存。</p>
      </div>
    </section>
  )
}
