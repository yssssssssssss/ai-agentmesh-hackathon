import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { Menu, X } from 'lucide-react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { ProfileDrawer } from './ProfileDrawer'
import { SettingsDrawer } from './SettingsDrawer'
import { ToastViewport } from '../ui/ToastViewport'

interface LayoutUIValue {
  openProfile: () => void
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
  const [profileOpen, setProfileOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [navigationOpen, setNavigationOpen] = useState(false)
  const { pathname } = useLocation()
  const fullBleed = pathname.startsWith('/workspace') || pathname.startsWith('/digital-human')

  useEffect(() => setNavigationOpen(false), [pathname])
  useEffect(() => {
    if (!navigationOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setNavigationOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [navigationOpen])

  const ui = useMemo<LayoutUIValue>(
    () => ({
      openProfile: () => setProfileOpen(true),
      openSettings: () => setSettingsOpen(true),
    }),
    [],
  )

  return (
    <LayoutUIContext.Provider value={ui}>
      <div data-testid="app-shell" className="flex h-screen overflow-hidden bg-canvas">
        {navigationOpen ? (
          <button
            type="button"
            aria-label="关闭导航遮罩"
            className="fixed inset-0 z-40 bg-black/60 lg:hidden"
            onClick={() => setNavigationOpen(false)}
          />
        ) : null}
        <div
          className={`fixed inset-y-0 left-0 z-50 transition-transform duration-200 lg:static lg:z-auto lg:translate-x-0 ${
            navigationOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          <Sidebar onOpenSettings={ui.openSettings} onOpenProfile={ui.openProfile} />
          <button
            type="button"
            aria-label="关闭导航"
            onClick={() => setNavigationOpen(false)}
            className="absolute right-2 top-2 flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50 lg:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center border-b border-white/[0.06] bg-base px-4 lg:hidden">
            <button
              type="button"
              aria-label="打开导航"
              onClick={() => setNavigationOpen(true)}
              className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
            >
              <Menu className="h-5 w-5" />
            </button>
            <span className="ml-3 text-sm font-semibold text-slate-100">AgentMesh</span>
          </header>

          {fullBleed ? (
            <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
              <Outlet />
            </main>
          ) : (
            <main className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
              <div className="mx-auto min-h-full w-full max-w-[1240px] px-4 py-4 md:px-8 md:py-8">
                <Outlet />
              </div>
            </main>
          )}
        </div>
      </div>

      <ProfileDrawer open={profileOpen} onClose={() => setProfileOpen(false)} />
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <ToastViewport />
    </LayoutUIContext.Provider>
  )
}
