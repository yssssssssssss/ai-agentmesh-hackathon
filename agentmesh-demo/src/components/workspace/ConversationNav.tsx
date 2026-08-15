import { Plus } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'

import { useThreadsQuery, useWorkspaceScope, workspaceErrorMessage } from '../../features/workspace/queries'
import { cn } from '../../lib/cn'

export function ConversationNav() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const scope = useWorkspaceScope()
  const threads = useThreadsQuery(scope)
  const activeId = pathname.match(/^\/workspace\/thread\/([^/]+)$/)?.[1]

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => navigate('/workspace')}
        className="flex w-full items-center gap-2 rounded-[8px] px-2.5 py-1.5 text-left text-[13px] font-medium text-mint-300 transition-colors hover:bg-white/[0.04] hover:text-mint-200"
      >
        <Plus className="h-4 w-4 shrink-0" aria-hidden="true" />
        开始新对话
      </button>

      {threads.isLoading ? <p className="px-2.5 py-2 text-xs text-slate-500">正在加载对话…</p> : null}
      {threads.isError ? (
        <p role="alert" className="px-2.5 py-2 text-xs leading-5 text-rose">
          {workspaceErrorMessage(threads.error)}
        </p>
      ) : null}
      {threads.data?.items.map((thread) => {
        const id = thread.id
        if (!id) return null
        return (
          <button
            key={id}
            type="button"
            aria-label={thread.title}
            aria-current={id === activeId ? 'page' : undefined}
            onClick={() => navigate(`/workspace/thread/${encodeURIComponent(id)}`)}
            className={cn(
              'block w-full truncate rounded-[8px] px-2.5 py-1.5 text-left text-[13px] leading-snug transition-colors',
              id === activeId
                ? 'bg-surface-3 font-medium text-slate-100'
                : 'text-slate-300 hover:bg-white/[0.04]',
            )}
          >
            {thread.title}
          </button>
        )
      })}
    </div>
  )
}
