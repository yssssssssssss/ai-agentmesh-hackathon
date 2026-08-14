import { useEffect, useState } from 'react'
import { api, ApiError, type UserMemoryItem } from '../lib/api'

interface UserMemoryState {
  items: UserMemoryItem[]
  loading: boolean
  error: string | null
}

/**
 * 拉取当前用户的真实记忆条目(GET /api/memory/user)。
 * 用于 DigitalSelf 首页的「工作理解」「本周新掌握」等聚合视图。
 * 失败时返回空列表并保留 error,由调用方决定降级为演示数据或提示。
 */
export function useUserMemory(): UserMemoryState {
  const [items, setItems] = useState<UserMemoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.memory
      .user()
      .then((list) => {
        if (cancelled) return
        setItems(list)
        setLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : '加载失败')
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { items, loading, error }
}
