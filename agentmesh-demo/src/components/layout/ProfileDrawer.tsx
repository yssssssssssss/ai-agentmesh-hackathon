import { Bot, BriefcaseBusiness, CircleUserRound, ShieldCheck } from 'lucide-react'

import { useAuth } from '../../features/auth/AuthProvider'
import { Badge } from '../ui/Badge'
import { Drawer } from '../ui/Drawer'

interface ProfileDrawerProps {
  open: boolean
  onClose: () => void
}

export function ProfileDrawer({ open, onClose }: ProfileDrawerProps) {
  const { user, bootstrap } = useAuth()
  const agent = bootstrap?.agents.find((item) => item.id === user?.personal_agent_id)
  const capabilities = bootstrap?.capabilities ?? []
  return (
    <Drawer
      open={open}
      onClose={onClose}
      icon={<CircleUserRound className="h-5 w-5" />}
      title={user?.name ?? '个人资料'}
      subtitle={bootstrap ? `${bootstrap.workspace.name} · ${bootstrap.project.name}` : '账号信息'}
      width={480}
    >
      {!user || !bootstrap ? <p className="text-sm text-slate-500">账号信息暂时不可用。</p> : (
        <div className="space-y-6">
          <section className="rounded-[12px] border border-white/[0.06] bg-surface-1 p-4">
            <div className="flex items-center gap-3"><CircleUserRound className="h-5 w-5 text-mint-300" /><div><h3 className="font-semibold text-white">{user.name}</h3><p className="mt-1 text-xs text-slate-500">账号 ID：{user.id}</p></div></div>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-xs text-slate-500">角色</dt><dd className="mt-1 text-slate-200">{user.role}</dd></div><div><dt className="text-xs text-slate-500">状态</dt><dd className="mt-1 text-slate-200">{user.status}</dd></div></dl>
          </section>
          <section>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-200"><BriefcaseBusiness className="h-4 w-4 text-mint-300" />当前上下文</h3>
            <dl className="mt-3 space-y-2 rounded-[12px] border border-white/[0.06] bg-surface-1 p-4 text-sm"><div className="flex justify-between gap-4"><dt className="text-slate-500">工作空间</dt><dd className="text-right text-slate-200">{bootstrap.workspace.name}</dd></div><div className="flex justify-between gap-4"><dt className="text-slate-500">项目</dt><dd className="text-right text-slate-200">{bootstrap.project.name}</dd></div></dl>
          </section>
          <section>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-200"><Bot className="h-4 w-4 text-mint-300" />个人 Agent</h3>
            {agent ? <div className="mt-3 rounded-[12px] border border-white/[0.06] bg-surface-1 p-4"><div className="flex flex-wrap items-center gap-2"><span className="font-medium text-white">{agent.name}</span><Badge>{agent.status}</Badge><Badge>{agent.runtime_status}</Badge></div><p className="mt-2 text-sm leading-6 text-slate-400">{agent.description}</p></div> : <p className="mt-3 text-sm text-slate-500">当前账号尚未绑定可见 Agent。</p>}
          </section>
          <section>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-200"><ShieldCheck className="h-4 w-4 text-mint-300" />管理能力</h3>
            {capabilities.length > 0 ? <div className="mt-3 flex flex-wrap gap-2">{capabilities.map((capability) => <Badge key={capability}>{capability}</Badge>)}</div> : <p className="mt-3 text-sm text-slate-500">当前账号没有管理能力。</p>}
          </section>
        </div>
      )}
    </Drawer>
  )
}
