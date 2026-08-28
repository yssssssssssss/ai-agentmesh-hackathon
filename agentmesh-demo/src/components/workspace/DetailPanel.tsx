import { FileText, Link2, X } from 'lucide-react'

import { useDocumentQuery, workspaceErrorMessage } from '../../features/workspace/queries'
import type { ResourceSelection, Source, WorkspaceScope } from '../../features/workspace/types'

function safeReference(reference: string): string {
  const assignmentRedacted = reference.replace(
    /\b(api[-_ ]?key|token|password|secret|credential)\s*[:=]\s*[^\s,;&]+/gi,
    '$1=[REDACTED]',
  )
  try {
    const url = new URL(assignmentRedacted)
    url.username = ''
    url.password = ''
    url.search = ''
    url.hash = ''
    return url.toString()
  } catch {
    return assignmentRedacted.replace(/bearer\s+[^\s,;&]+/gi, 'Bearer [REDACTED]')
  }
}

function SourceFields({ source }: { source: Source }) {
  return (
    <dl className="space-y-4 text-sm">
      <div><dt className="text-xs uppercase tracking-wide text-slate-400">来源类型</dt><dd className="mt-1 text-slate-200">{source.source_type}</dd></div>
      <div><dt className="text-xs uppercase tracking-wide text-slate-400">稳定引用</dt><dd className="mt-1 break-all font-mono text-xs leading-5 text-slate-300">{safeReference(source.reference)}</dd></div>
    </dl>
  )
}

export function DetailPanel({
  selection,
  scope,
  onClose,
}: {
  selection: ResourceSelection | null
  scope: WorkspaceScope
  onClose: () => void
}) {
  const documentId = selection?.kind === 'document' ? selection.id : null
  const document = useDocumentQuery(scope, documentId)
  if (!selection) return null

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-label="资源详情"
      className="absolute inset-y-0 right-0 z-20 flex w-full max-w-[440px] flex-col border-l border-white/[0.08] bg-base shadow-panel"
    >
      <header className="flex items-start gap-3 border-b border-white/[0.06] px-5 py-4">
        <span className="rounded-soft bg-white/[0.05] p-2 text-mint-300"><FileText className="h-4 w-4" aria-hidden="true" /></span>
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-wide text-slate-400">Owner-visible resource</p>
          <h2 className="mt-1 truncate text-sm font-semibold text-slate-100">
            {selection.kind === 'source' ? selection.source.title : document.data?.item.title ?? '正在加载文档'}
          </h2>
        </div>
        <button type="button" onClick={onClose} aria-label="关闭资源详情" className="rounded-lg p-2 text-slate-400 hover:bg-white/[0.06] hover:text-slate-200">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </header>
      <div className="flex-1 overflow-y-auto px-5 py-5">
        {selection.kind === 'source' ? <SourceFields source={selection.source} /> : null}
        {selection.kind === 'document' && document.isLoading ? <p className="text-sm text-slate-400">正在加载服务端文档…</p> : null}
        {selection.kind === 'document' && document.isError ? <p role="alert" className="text-sm text-rose">{workspaceErrorMessage(document.error)}</p> : null}
        {selection.kind === 'document' && document.data ? (
          <div className="space-y-5">
            <dl className="grid grid-cols-2 gap-3 text-xs">
              <div className="rounded-soft bg-white/[0.04] p-3"><dt className="text-slate-400">文件</dt><dd className="mt-1 break-all text-slate-200">{document.data.item.file_name}</dd></div>
              <div className="rounded-soft bg-white/[0.04] p-3"><dt className="text-slate-400">版本</dt><dd className="mt-1 text-slate-200">v{document.data.item.version}</dd></div>
            </dl>
            <div>
              <h3 className="text-xs uppercase tracking-wide text-slate-400">正文</h3>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-300">{document.data.item.text}</p>
            </div>
            <div className="border-t border-white/[0.06] pt-4">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-400"><Link2 className="h-3.5 w-3.5" aria-hidden="true" />来源</div>
              <SourceFields source={document.data.item.source} />
            </div>
          </div>
        ) : null}
      </div>
    </aside>
  )
}
