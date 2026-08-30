import { Component, lazy, Suspense, type ErrorInfo, type ReactNode } from 'react'
import { LockKeyhole, RefreshCw } from 'lucide-react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { Button } from './components/ui/Button'
import { useAuth } from './features/auth/AuthProvider'
import { DemoProvider } from './store/DemoContext'
import { LoginPage } from './features/auth/LoginPage'

const AdminPage = lazy(() => import('./features/admin/AdminPage').then((module) => ({ default: module.AdminPage })))
const DigitalSelf = lazy(() => import('./pages/DigitalSelf').then((module) => ({ default: module.DigitalSelf })))
const Workspace = lazy(() => import('./pages/Workspace').then((module) => ({ default: module.Workspace })))
const Insights = lazy(() => import('./pages/Insights').then((module) => ({ default: module.Insights })))
const Knowledge = lazy(() => import('./pages/Knowledge').then((module) => ({ default: module.Knowledge })))
const Collaboration = lazy(() => import('./pages/Collaboration').then((module) => ({ default: module.Collaboration })))
const Market = lazy(() => import('./pages/Market').then((module) => ({ default: module.Market })))
const DigitalHuman = lazy(() => import('./pages/DigitalHuman').then((module) => ({ default: module.DigitalHuman })))

function FullPageStatus({
  title,
  message,
  children,
}: {
  title: string
  message: string
  children?: ReactNode
}) {
  return (
    <main className="flex min-h-full items-center justify-center bg-canvas px-5 py-10">
      <section className="w-full max-w-md text-center" aria-live="polite">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-soft bg-white/[0.05] text-slate-300">
          <LockKeyhole className="h-5 w-5" aria-hidden="true" />
        </span>
        <h1 className="mt-6 text-2xl font-semibold text-slate-100">{title}</h1>
        <p className="mt-3 text-sm leading-6 text-slate-400">{message}</p>
        {children ? <div className="mt-7 flex justify-center gap-3">{children}</div> : null}
      </section>
    </main>
  )
}


function RouteLoading() {
  return (
    <div role="status" className="card-base p-5 text-sm text-slate-400">
      正在加载页面…
    </div>
  )
}

class RouteErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // The user-facing recovery is a hard reload so stale deployment chunks can be replaced.
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div role="alert" className="card-base p-5 text-sm text-slate-300">
        <p>页面资源加载失败，可能是版本已更新或网络暂时中断。</p>
        <Button className="mt-3" size="sm" onClick={() => window.location.reload()}>
          重新加载
        </Button>
      </div>
    )
  }
}

function LazyPage({ children }: { children: ReactNode }) {
  const location = useLocation()
  return (
    <RouteErrorBoundary key={location.pathname}>
      <Suspense fallback={<RouteLoading />}>{children}</Suspense>
    </RouteErrorBoundary>
  )
}

function AuthenticatedRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/digital-self" replace />} />
        <Route path="/digital-self/*" element={<LazyPage><DigitalSelf /></LazyPage>} />
        <Route path="/workspace/*" element={<LazyPage><Workspace /></LazyPage>} />
        <Route path="/insights/*" element={<LazyPage><Insights /></LazyPage>} />
        <Route path="/knowledge/*" element={<LazyPage><Knowledge /></LazyPage>} />
        <Route path="/collaboration/*" element={<LazyPage><Collaboration /></LazyPage>} />
        <Route path="/market/*" element={<LazyPage><Market /></LazyPage>} />
        <Route path="/digital-human/*" element={<LazyPage><DigitalHuman /></LazyPage>} />
        <Route path="/admin/*" element={<LazyPage><AdminPage /></LazyPage>} />
        <Route path="*" element={<Navigate to="/digital-self" replace />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  const { status, user, message, logoutError, logout, restore } = useAuth()

  if (status === 'loading') {
    return <FullPageStatus title="正在恢复会话" message="正在确认账号和工作空间权限。" />
  }
  if (status === 'signed-out' || status === 'revocation-required') return <LoginPage />
  if (status === 'denied') {
    return (
      <FullPageStatus title="访问受限" message={message ?? '当前账号没有访问此工作空间的权限。'}>
        <Button variant="secondary" onClick={() => void restore()} icon={<RefreshCw className="h-4 w-4" />}>
          重新检查
        </Button>
        <Button onClick={() => void logout().catch(() => undefined)}>{logoutError ? '重试退出' : '退出登录'}</Button>
        {logoutError ? <p role="alert">{logoutError}</p> : null}
      </FullPageStatus>
    )
  }
  if (status === 'unavailable') {
    return (
      <FullPageStatus title="暂时无法连接" message={message ?? '无法恢复会话，请稍后重试。'}>
        <Button onClick={() => void restore()} icon={<RefreshCw className="h-4 w-4" />}>
          重试
        </Button>
      </FullPageStatus>
    )
  }
  return <DemoProvider key={user?.id ?? user?.personal_agent_id}><AuthenticatedRoutes /></DemoProvider>
}
