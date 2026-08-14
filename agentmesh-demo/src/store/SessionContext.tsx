import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, ApiError, UnauthorizedError, type User } from '../lib/api'

type SessionStatus = 'loading' | 'authenticated' | 'anonymous'

interface SessionState {
  status: SessionStatus
  user: User | null
}

interface SessionActions {
  login: (userId: string, password: string) => Promise<User>
  logout: () => Promise<void>
  /** 重新拉取 /auth/me 刷新当前用户。 */
  refresh: () => Promise<void>
}

type SessionContextValue = SessionState & SessionActions

const SessionContext = createContext<SessionContextValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<SessionStatus>('loading')

  const refresh = useCallback(async () => {
    try {
      const me = await api.auth.me()
      setUser(me)
      setStatus('authenticated')
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        setUser(null)
        setStatus('anonymous')
        return
      }
      // 非 401(网络/5xx)视为无法确认会话,按匿名处理但保留可重试
      setUser(null)
      setStatus('anonymous')
      throw err
    }
  }, [])

  useEffect(() => {
    void refresh().catch(() => {
      /* refresh 内部已归类状态;此处仅吞掉非授权异常,避免未处理拒绝 */
    })
  }, [refresh])

  const login = useCallback(async (userId: string, password: string) => {
    const me = await api.auth.login(userId, password)
    setUser(me)
    setStatus('authenticated')
    return me
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.auth.logout()
    } catch (err) {
      // 会话可能已过期,logout 失败也按登出处理
      if (!(err instanceof ApiError)) throw err
    }
    setUser(null)
    setStatus('anonymous')
  }, [])

  const value = useMemo<SessionContextValue>(
    () => ({ status, user, login, logout, refresh }),
    [status, user, login, logout, refresh],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSession() {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used within SessionProvider')
  return ctx
}
