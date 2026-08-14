import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ConversationThread } from '../components/workspace/ConversationThread'
import { Composer } from '../components/workspace/Composer'
import { DemoConversationThread } from '../components/workspace/DemoConversationThread'
import { DetailPanel, type DetailContent } from '../components/workspace/DetailPanel'
import type { WorkspaceRef } from '../data/mockData'
import { cn } from '../lib/cn'
import { useChat } from '../store/ChatContext'

export function Workspace() {
  const { messages, threadId, sending, loadThread, reset } = useChat()
  const [content, setContent] = useState<DetailContent | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedThreadId = searchParams.get('thread')
  const isDemoThread = requestedThreadId === 'thread_graph_demo'

  useEffect(() => {
    if (!isDemoThread) return
    reset()
  }, [isDemoThread, reset])

  useEffect(() => {
    if (isDemoThread) return
    setContent(null)
  }, [isDemoThread])

  useEffect(() => {
    if (isDemoThread || !requestedThreadId || requestedThreadId === threadId) return
    void loadThread(requestedThreadId).catch(() => {
      setSearchParams((current) => {
        if (current.get('thread') !== requestedThreadId) return current
        const next = new URLSearchParams(current)
        next.delete('thread')
        return next
      }, { replace: true })
    })
  }, [isDemoThread, loadThread, requestedThreadId, setSearchParams, threadId])

  useEffect(() => {
    if (!threadId || requestedThreadId) return
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set('thread', threadId)
      return next
    }, { replace: true })
  }, [requestedThreadId, setSearchParams, threadId])

  useLayoutEffect(() => {
    if (messages.length === 0 && !sending) return
    const scrollContainer = scrollRef.current
    if (!scrollContainer) return
    scrollContainer.scrollTop = scrollContainer.scrollHeight
  }, [messages, sending])

  const activeRefId = content?.kind === 'ref' ? content.ref.id : undefined
  const openRef = (ref: WorkspaceRef) => setContent({ kind: 'ref', ref })

  return (
    <div className="relative h-full overflow-hidden">
      <div
        ref={scrollRef}
        className={cn(
          'h-full overflow-y-auto transition-[padding] duration-300 ease-out',
          content && '2xl:pr-[456px]',
        )}
      >
        <div className="mx-auto max-w-[800px] px-6 pb-44 pt-8">
          {isDemoThread ? (
            <DemoConversationThread
              activeRefId={activeRefId}
              onOpenRef={openRef}
              onOpenSources={() => setContent({ kind: 'sources' })}
              onOpenBrief={() => setContent({ kind: 'brief' })}
            />
          ) : (
            <ConversationThread />
          )}
        </div>
      </div>
      <Composer
        beforeSend={isDemoThread
          ? () => {
              reset()
              setSearchParams({}, { replace: true })
            }
          : undefined}
      />
      <DetailPanel
        content={content}
        onClose={() => setContent(null)}
        onOpenSources={() => setContent({ kind: 'sources' })}
        onOpenTools={() => setContent({ kind: 'tools' })}
        onOpenCollaboration={() => setContent({ kind: 'collaboration' })}
      />
    </div>
  )
}
