import { Plus } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { ChatThread } from '../../lib/api'
import { useChat } from '../../store/ChatContext'
import { cn } from '../../lib/cn'

/** 当前用户的真实对话记录。排序由服务端保证。 */
export function ConversationNav() {
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const { threads, threadId, loadingThreads, reset } = useChat()
  const requestedThreadId = new URLSearchParams(search).get('thread')
  const activeThreadId = requestedThreadId ?? threadId

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => {
          reset()
          navigate('/workspace')
        }}
        className="flex w-full items-center gap-2 rounded-[8px] px-2.5 py-1.5 text-left text-[13px] font-medium text-mint-300 transition-colors hover:bg-white/[0.04] hover:text-mint-200"
      >
        <Plus className="h-4 w-4 shrink-0" />
        开始新对话
      </button>

      {loadingThreads && threads.length === 0 ? (
        <div className="px-2.5 py-2 text-[12px] text-slate-600" role="status">
          正在加载对话…
        </div>
      ) : (
        threads.map((thread) => (
          <ConversationItem
            key={thread.id}
            thread={thread}
            active={pathname.startsWith('/workspace') && thread.id === activeThreadId}
            onSelect={() => navigate(`/workspace?thread=${encodeURIComponent(thread.id)}`)}
          />
        ))
      )}
    </div>
  )
}

function ConversationItem({
  thread,
  active,
  onSelect,
}: {
  thread: ChatThread
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'flex w-full items-center rounded-[8px] px-2.5 py-1.5 text-left transition-colors',
        active ? 'bg-surface-3' : 'hover:bg-white/[0.04]',
      )}
    >
      <span
        className={cn(
          'min-w-0 flex-1 truncate text-[13px] leading-snug',
          active ? 'font-medium text-slate-100' : 'text-slate-300',
        )}
      >
        {thread.title}
      </span>
    </button>
  )
}
