import { createContext, useContext, useMemo, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { SettingsDrawer } from './SettingsDrawer'
import { ToastViewport } from '../ui/ToastViewport'
import { useSession } from '../../store/SessionContext'

interface LayoutUIValue {
  openSettings: () => void
}
const LayoutUIContext = createContext<LayoutUIValue | null>(null)

// eslint-disable-next-line react-refresh/only-export-components
export function useLayoutUI() {
  const ctx = useContext(LayoutUIContext)
  if (!ctx) throw new Error('useLayoutUI 必须在 AppLayout 内使用')
  return ctx
}

export function AppLayout() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { pathname } = useLocation()
  const { status } = useSession()
  // 工作台与「数字人管理」都走 full-bleed(自管理二级导航 + 独立滚动)
  const fullBleed = pathname.startsWith('/workspace') || pathname.startsWith('/digital-human')

  const ui = useMemo<LayoutUIValue>(
    () => ({
      openSettings: () => setSettingsOpen(true),
    }),
    [],
  )

  // 会话确认中 —— 不渲染任何布局,避免闪烁
  if (status === 'loading') return null
  // 未登录 —— 直接把用户推到 ERP 统一登录示意页,不渲染任何后台布局
  if (status !== 'authenticated') return <Navigate to="/login" replace />

  return (
    <LayoutUIContext.Provider value={ui}>
      <div className="flex h-screen overflow-hidden bg-canvas">
        <Sidebar onOpenSettings={ui.openSettings} />
        {fullBleed ? (
          // 工作台自管理布局与滚动(子导航 / 对话区 / 右侧面板)
          <main className="min-w-0 flex-1 overflow-hidden">
            <Outlet />
          </main>
        ) : (
          <main className="flex-1 overflow-y-auto">
            <div className="mx-auto min-h-full w-full max-w-[1240px] px-8 py-8">
              <Outlet />
            </div>
          </main>
        )}
      </div>

      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <ToastViewport />
    </LayoutUIContext.Provider>
  )
}
