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

import { advanceSessionGeneration, ApiError, onUnauthorized } from '../../api/client'
import { queryClient } from '../../app/queryClient'
import { authApi, type BootstrapState, type User } from './api'

type AuthStatus = 'loading' | 'signed-out' | 'ready' | 'denied' | 'unavailable' | 'revocation-required'

interface AuthState {
  status: AuthStatus
  user: User | null
  bootstrap: BootstrapState | null
  message: string | null
}

export interface AuthContextValue extends AuthState {
  logoutError: string | null
  login: (userId: string, password: string) => Promise<void>
  logout: () => Promise<void>
  restore: () => Promise<void>
  refreshBootstrap: () => Promise<void>
}

const LOADING_STATE: AuthState = {
  status: 'loading',
  user: null,
  bootstrap: null,
  message: null,
}

const SIGNED_OUT_STATE: AuthState = {
  status: 'signed-out',
  user: null,
  bootstrap: null,
  message: null,
}

const AuthContext = createContext<AuthContextValue | null>(null)

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  if (error instanceof Error) return error.message
  return '请求失败，请稍后重试'
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(LOADING_STATE)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const sessionGeneration = useRef(0)
  const initialRestoreStarted = useRef(false)

  const clearClientSession = useCallback((requestGeneration: number) => {
    if (requestGeneration !== sessionGeneration.current) return
    sessionGeneration.current = advanceSessionGeneration()
    queryClient.clear()
    setLogoutError(null)
    setState(SIGNED_OUT_STATE)
  }, [])

  const restore = useCallback(async () => {
    const generation = advanceSessionGeneration()
    sessionGeneration.current = generation
    setState(LOADING_STATE)
    setLogoutError(null)
    try {
      const user = await authApi.me()
      try {
        const bootstrap = await authApi.bootstrap()
        if (generation !== sessionGeneration.current) return
        setState({ status: 'ready', user: bootstrap.user, bootstrap, message: null })
      } catch (error) {
        if (generation !== sessionGeneration.current) return
        if (error instanceof ApiError && error.status === 403) {
          queryClient.clear()
          setState({ status: 'denied', user, bootstrap: null, message: errorMessage(error) })
          return
        }
        throw error
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearClientSession(generation)
        return
      }
      if (generation !== sessionGeneration.current) return
      queryClient.clear()
      setState({ status: 'unavailable', user: null, bootstrap: null, message: errorMessage(error) })
    }
  }, [clearClientSession])

  const refreshBootstrap = useCallback(async () => {
    const generation = sessionGeneration.current
    try {
      const bootstrap = await authApi.bootstrap()
      if (generation !== sessionGeneration.current) return
      setState((current) => current.status === 'ready'
        ? { status: 'ready', user: bootstrap.user, bootstrap, message: null }
        : current)
    } catch (error) {
      if (generation !== sessionGeneration.current) return
      if (error instanceof ApiError && error.status === 401) {
        clearClientSession(generation)
        return
      }
      if (error instanceof ApiError && error.status === 403) {
        queryClient.clear()
        setState((current) => ({
          status: 'denied',
          user: current.user,
          bootstrap: null,
          message: errorMessage(error),
        }))
        return
      }
      throw error
    }
  }, [clearClientSession])

  useEffect(() => onUnauthorized(clearClientSession), [clearClientSession])

  useEffect(() => {
    if (initialRestoreStarted.current) return
    initialRestoreStarted.current = true
    void restore()
  }, [restore])

  const login = useCallback(async (userId: string, password: string) => {
    const generation = advanceSessionGeneration()
    sessionGeneration.current = generation
    setLogoutError(null)
    const candidate = await authApi.login(userId, password)
    if (generation !== sessionGeneration.current) return
    try {
      const bootstrap = await authApi.bootstrap()
      if (generation !== sessionGeneration.current) return
      setState({ status: 'ready', user: bootstrap.user, bootstrap, message: null })
    } catch (error) {
      if (generation !== sessionGeneration.current) return
      if (error instanceof ApiError && error.status === 403) {
        queryClient.clear()
        setState({ status: 'denied', user: candidate, bootstrap: null, message: errorMessage(error) })
        return
      }

      try {
        await authApi.logout()
        clearClientSession(generation)
      } catch (rollbackError) {
        if (generation !== sessionGeneration.current) return
        setLogoutError(errorMessage(rollbackError))
        setState({
          status: 'revocation-required',
          user: candidate,
          bootstrap: null,
          message: errorMessage(error),
        })
        return
      }
      throw error
    }
  }, [clearClientSession])

  const logout = useCallback(async () => {
    const generation = advanceSessionGeneration()
    sessionGeneration.current = generation
    setLogoutError(null)
    try {
      await authApi.logout()
      clearClientSession(generation)
    } catch (error) {
      if (generation !== sessionGeneration.current) return
      setLogoutError(errorMessage(error))
      throw error
    }
  }, [clearClientSession])

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, logoutError, login, logout, restore, refreshBootstrap }),
    [login, logout, logoutError, refreshBootstrap, restore, state],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
