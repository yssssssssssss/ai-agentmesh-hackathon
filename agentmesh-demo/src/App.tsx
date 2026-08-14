import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { Login } from './pages/Login'
import { DigitalSelf } from './pages/DigitalSelf'
import { Workspace } from './pages/Workspace'
import { Insights } from './pages/Insights'
import { Knowledge } from './pages/Knowledge'
import { Collaboration } from './pages/Collaboration'
import { DigitalHuman } from './pages/DigitalHuman'

export default function App() {
  return (
    <Routes>
      {/* 独立路由 —— ERP 统一登录示意页,不进 AppLayout */}
      <Route path="/login" element={<Login />} />

      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/digital-self" replace />} />
        <Route path="/digital-self" element={<DigitalSelf />} />
        <Route path="/workspace" element={<Workspace />} />
        <Route path="/insights" element={<Insights />} />
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/collaboration" element={<Collaboration />} />
        {/* 数字人管理 —— 仅经侧栏「数字人入口卡」进入,不进主导航 */}
        <Route path="/digital-human" element={<DigitalHuman />} />
        <Route path="*" element={<Navigate to="/digital-self" replace />} />
      </Route>
    </Routes>
  )
}
