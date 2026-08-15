import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  api,
  type ChatMessage,
  type ChatThread,
  type ChatTurnTrace,
} from '../lib/api'

export interface ChatViewMessage extends ChatMessage {
  delivery: 'pending' | 'sent' | 'failed'
}

interface ChatState {
  messages: ChatViewMessage[]
  threads: ChatThread[]
  tracesByAssistantMessageId: Record<string, ChatTurnTrace>
  threadId: string | null
  sending: boolean
  loadingHistory: boolean
  loadingThreads: boolean
  lastError: string | null
}

interface ChatActions {
  send: (content: string) => Promise<void>
  loadThread: (threadId: string) => Promise<void>
  reset: () => void
}

type ChatContextValue = ChatState & ChatActions

const ChatContext = createContext<ChatContextValue | null>(null)

export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<ChatViewMessage[]>([])
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [tracesByAssistantMessageId, setTracesByAssistantMessageId] = useState<Record<string, ChatTurnTrace>>({})
  const [threadId, setThreadId] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [loadingThreads, setLoadingThreads] = useState(false)
  const [lastError, setLastError] = useState<string | null>(null)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const conversationGeneration = useRef(0)
  const loadedThreadId = useRef<string | null>(null)
  const loadingThreadId = useRef<string | null>(null)
  const threadsRequestId = useRef(0)
  const activeThreadId = useRef<string | null>(null)

  const refreshThreads = useCallback(async () => {
    const requestId = ++threadsRequestId.current
    setLoadingThreads(true)
    try {
      const nextThreads = await api.chat.listThreads()
      if (requestId === threadsRequestId.current) setThreads(nextThreads)
    } finally {
      if (requestId === threadsRequestId.current) setLoadingThreads(false)
    }
  }, [])

  useEffect(() => {
    void refreshThreads().catch(() => {})
  }, [refreshThreads])

  const send = useCallback(
    async (content: string) => {
      const text = content.trim()
      if (!text) return

      const generation = conversationGeneration.current
      const optimisticId = `pending-${crypto.randomUUID()}`
      const optimisticMessage: ChatViewMessage = {
        id: optimisticId,
        thread_id: activeThreadId.current ?? '',
        role: 'user',
        content: text,
        scope: 'private',
        sources: [],
        created_at: new Date().toISOString(),
        delivery: 'pending',
      }
      setMessages((previous) => [...previous, optimisticMessage])

      const run = queue.current.then(async () => {
        if (generation !== conversationGeneration.current) return
        setSending(true)
        setLastError(null)
        try {
          const response = await api.chat.sendMessage(text, activeThreadId.current ?? undefined)
          if (generation !== conversationGeneration.current) return

          const userMessage: ChatViewMessage = { ...response.user_message, delivery: 'sent' }
          const assistantMessage: ChatViewMessage = { ...response.assistant_message, delivery: 'sent' }
          setThreadId(response.thread_id)
          activeThreadId.current = response.thread_id
          loadedThreadId.current = response.thread_id
          setMessages((previous) => {
            const index = previous.findIndex((message) => message.id === optimisticId)
            if (index === -1) return previous
            return [
              ...previous.slice(0, index),
              userMessage,
              assistantMessage,
              ...previous.slice(index + 1),
            ]
          })
          const turnTrace = response.turn_trace
          if (turnTrace) {
            setTracesByAssistantMessageId((previous) => ({
              ...previous,
              [turnTrace.assistant_message_id]: turnTrace,
            }))
          }
          void refreshThreads().catch(() => {})
        } catch (error) {
          if (generation === conversationGeneration.current) {
            const message = error instanceof Error ? error.message : '发送失败'
            setLastError(message)
            setMessages((previous) =>
              previous.map((item) =>
                item.id === optimisticId ? { ...item, delivery: 'failed' } : item,
              ),
            )
          }
          throw error
        } finally {
          if (generation === conversationGeneration.current) setSending(false)
        }
      })
      queue.current = run.catch(() => {})
      await run
    },
    [refreshThreads],
  )

  const loadThread = useCallback(async (requestedThreadId: string) => {
    const requestedId = requestedThreadId.trim()
    if (!requestedId || loadedThreadId.current === requestedId || loadingThreadId.current === requestedId) return

    conversationGeneration.current += 1
    const generation = conversationGeneration.current
    loadingThreadId.current = requestedId
    setLoadingHistory(true)
    setSending(false)
    setLastError(null)
    try {
      const [history, traces] = await Promise.all([
        api.chat.threadMessages(requestedId),
        api.chat.threadTraces(requestedId),
      ])
      if (generation !== conversationGeneration.current) return

      const nextTraces: Record<string, ChatTurnTrace> = {}
      for (const trace of traces) nextTraces[trace.assistant_message_id] = trace
      setMessages(history.map((message) => ({ ...message, delivery: 'sent' })))
      setTracesByAssistantMessageId(nextTraces)
      setThreadId(requestedId)
      activeThreadId.current = requestedId
      loadedThreadId.current = requestedId
    } catch (error) {
      if (generation === conversationGeneration.current) {
        const message = error instanceof Error ? error.message : '无法恢复对话'
        setMessages([])
        setTracesByAssistantMessageId({})
        setThreadId(null)
        activeThreadId.current = null
        setLastError(message)
      }
      throw error
    } finally {
      if (loadingThreadId.current === requestedId) loadingThreadId.current = null
      if (generation === conversationGeneration.current) setLoadingHistory(false)
    }
  }, [])

  const reset = useCallback(() => {
    conversationGeneration.current += 1
    loadedThreadId.current = null
    activeThreadId.current = null
    loadingThreadId.current = null
    setMessages([])
    setTracesByAssistantMessageId({})
    setThreadId(null)
    setSending(false)
    setLoadingHistory(false)
    setLastError(null)
  }, [])

  const value = useMemo<ChatContextValue>(
    () => ({
      messages,
      threads,
      tracesByAssistantMessageId,
      threadId,
      sending,
      loadingHistory,
      loadingThreads,
      lastError,
      loadThread,
      send,
      reset,
    }),
    [
      messages,
      threads,
      tracesByAssistantMessageId,
      threadId,
      sending,
      loadingHistory,
      loadingThreads,
      lastError,
      loadThread,
      send,
      reset,
    ],
  )

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useChat() {
  const context = useContext(ChatContext)
  if (!context) throw new Error('useChat must be used within ChatProvider')
  return context
}
