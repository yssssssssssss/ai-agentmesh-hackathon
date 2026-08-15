import { LockKeyhole, RefreshCw } from 'lucide-react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { Button } from './components/ui/Button'
import { useAuth } from './features/auth/AuthProvider'
import { DemoProvider } from './store/DemoContext'
import { LoginPage } from './features/auth/LoginPage'
import { AdminPage } from './features/admin/AdminPage'
import { DigitalSelf } from './pages/DigitalSelf'
import { Workspace } from './pages/Workspace'
import { Insights } from './pages/Insights'
import { Knowledge } from './pages/Knowledge'
import { Collaboration } from './pages/Collaboration'
import { Market } from './pages/Market'
import { DigitalHuman } from './pages/DigitalHuman'

function FullPageStatus({
  title,
  message,
  children,
}: {
  title: string
  message: string
  children?: React.ReactNode
}) {
  return (
    <main className="flex min-h-full items-center justify-center bg-canvas px-5 py-10">
      <section className="w-full max-w-md text-center" aria-live="polite">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-[12px] bg-white/[0.05] text-slate-300">
          <LockKeyhole className="h-5 w-5" aria-hidden="true" />
        </span>
        <h1 className="mt-6 text-2xl font-semibold text-slate-100">{title}</h1>
        <p className="mt-3 text-sm leading-6 text-slate-400">{message}</p>
        {children ? <div className="mt-7 flex justify-center gap-3">{children}</div> : null}
      </section>
    </main>
  )
}


function AuthenticatedRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/digital-self" replace />} />
        <Route path="/digital-self/*" element={<DigitalSelf />} />
        <Route path="/workspace/*" element={<Workspace />} />
        <Route path="/insights/*" element={<Insights />} />
        <Route path="/knowledge/*" element={<Knowledge />} />
        <Route path="/collaboration/*" element={<Collaboration />} />
        <Route path="/market/*" element={<Market />} />
        <Route path="/digital-human/*" element={<DigitalHuman />} />
        <Route path="/admin/*" element={<AdminPage />} />
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
