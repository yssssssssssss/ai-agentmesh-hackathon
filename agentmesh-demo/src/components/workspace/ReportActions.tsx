import { Download, ExternalLink } from 'lucide-react'

interface ReportActionsProps {
  runId: string
}

export function ReportActions({ runId }: ReportActionsProps) {
  const reportHref = `/api/agent/runs/${encodeURIComponent(runId)}/report.html`
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="报告操作">
      <a
        href={reportHref}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex min-h-10 items-center gap-1.5 rounded-soft bg-white/[0.05] px-3 text-xs font-medium text-slate-200 transition-[transform,background-color,color] duration-150 active:scale-[0.96] hover:bg-white/[0.09] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
      >
        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
        独立查看
      </a>
      <a
        href={`${reportHref}?download=true`}
        download
        className="inline-flex min-h-10 items-center gap-1.5 rounded-soft bg-mint-400 px-3 text-xs font-semibold text-[#08271f] transition-[transform,background-color] duration-150 active:scale-[0.96] hover:bg-mint-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        下载 HTML
      </a>
    </div>
  )
}
