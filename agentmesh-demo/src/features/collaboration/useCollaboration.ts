import { useCallback, useEffect, useMemo, useState } from 'react'
import { collaborationApi, type TaskCard, type InboxItem, type MarketBoard } from './api'

export function useCollaboration() {
  const [taskCards, setTaskCards] = useState<TaskCard[]>([])
  const [marketBoard, setMarketBoard] = useState<MarketBoard | null>(null)
  const [inboxItems, setInboxItems] = useState<InboxItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [cards, board, inbox] = await Promise.all([
        collaborationApi.taskCards(),
        collaborationApi.marketBoard(),
        collaborationApi.inboxList(),
      ])
      setTaskCards(cards)
      setMarketBoard(board)
      setInboxItems(inbox)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const resolveInbox = useCallback(async (itemId: string) => {
    await collaborationApi.resolveInboxItem(itemId)
    setInboxItems((prev) => prev.filter((i) => i.id !== itemId))
  }, [])

  const stats = useMemo(() => {
    const completed = taskCards.filter((c) => c.task.collaboration_stage === 'completed').length
    const blocked = taskCards.filter((c) => c.task.collaboration_stage === 'blocked').length
    const running = taskCards.filter((c) => c.task.collaboration_stage === 'running').length
    const pendingAuths = inboxItems.filter((i) => i.status === 'open' && (i.item_type === 'decision_review' || i.item_type === 'risk_review')).length
    return { completed, blocked, running, pendingAuths, total: taskCards.length }
  }, [taskCards, inboxItems])

  return {
    taskCards,
    marketBoard,
    inboxItems,
    loading,
    error,
    stats,
    refresh,
    resolveInbox,
  }
}
