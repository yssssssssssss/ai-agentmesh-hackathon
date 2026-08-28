import { useState, type FormEvent } from 'react'
import { UserPlus } from 'lucide-react'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Modal } from '../../components/ui/Modal'
import type { User } from './api'
import { useUsersAdmin } from './api'

interface UsersModuleProps {
  context: { userId: string; workspaceId: string }
}

function message(error: unknown) {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return error instanceof Error ? error.message : '请求失败'
}

export function UsersModule({ context }: UsersModuleProps) {
  const resource = useUsersAdmin(context, true)
  const [createOpen, setCreateOpen] = useState(false)
  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [name, setName] = useState('')
  const [role, setRole] = useState<'user' | 'team_lead' | 'admin'>('user')
  const [password, setPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')

  const submitCreate = (event: FormEvent) => {
    event.preventDefault()
    resource.create.mutate(
      { name: name.trim(), role, password },
      {
        onSuccess: () => {
          setCreateOpen(false)
          setName('')
          setRole('user')
          setPassword('')
        },
      },
    )
  }
  const submitReset = (event: FormEvent) => {
    event.preventDefault()
    if (!resetTarget?.id) return
    resource.resetPassword.mutate(
      { userId: resetTarget.id, newPassword },
      {
        onSuccess: () => {
          setResetTarget(null)
          setNewPassword('')
        },
      },
    )
  }

  return (
    <Card padding="lg">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">用户管理</h2>
          <p className="mt-1 text-sm text-slate-400">创建、禁用账号或重置密码。</p>
        </div>
        <Button icon={<UserPlus className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>创建用户</Button>
      </div>
      {resource.query.isLoading ? <p className="mt-5 text-sm text-slate-400">正在加载用户…</p> : null}
      {resource.query.isError ? <p role="alert" className="mt-5 text-sm text-rose">{message(resource.query.error)}</p> : null}
      {resource.query.data && resource.query.data.items.length === 0 ? <p className="mt-5 text-sm text-slate-400">当前工作空间没有用户。</p> : null}
      {resource.query.data && resource.query.data.items.length > 0 ? (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-slate-400"><tr><th className="pb-3 font-medium">姓名</th><th className="pb-3 font-medium">角色</th><th className="pb-3 font-medium">状态</th><th className="pb-3 text-right font-medium">操作</th></tr></thead>
            <tbody className="divide-y divide-white/[0.06]">
              {resource.query.data.items.map((item) => (
                <tr key={item.id}>
                  <td className="py-3 pr-4 font-medium text-slate-100">{item.name}</td>
                  <td className="py-3 pr-4 text-slate-400">{item.role}</td>
                  <td className="py-3 pr-4 text-slate-400">{item.status}</td>
                  <td className="py-3">
                    <div className="flex justify-end gap-2">
                      {item.status !== 'disabled' && item.id !== context.userId ? (
                        <Button size="sm" variant="danger" loading={resource.disable.isPending && resource.disable.variables === item.id} onClick={() => item.id && resource.disable.mutate(item.id)}>禁用</Button>
                      ) : null}
                      <Button size="sm" variant="secondary" onClick={() => setResetTarget(item)}>重置密码</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {resource.disable.isError ? <p role="alert" className="mt-3 text-sm text-rose">{message(resource.disable.error)}</p> : null}

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="创建用户"
        footer={<><Button variant="ghost" onClick={() => setCreateOpen(false)}>取消</Button><Button type="submit" form="create-user-form" loading={resource.create.isPending}>确认创建</Button></>}
      >
        <form id="create-user-form" className="space-y-4" onSubmit={submitCreate}>
          <label className="block text-sm text-slate-300">姓名<input aria-label="姓名" required value={name} onChange={(event) => setName(event.target.value)} className="mt-2 h-10 w-full rounded-soft border border-white/[0.08] bg-surface-1 px-3 text-white outline-none focus:border-mint-400/50" /></label>
          <label className="block text-sm text-slate-300">角色<select aria-label="角色" value={role} onChange={(event) => setRole(event.target.value as typeof role)} className="mt-2 h-10 w-full rounded-soft border border-white/[0.08] bg-surface-1 px-3 text-white outline-none"><option value="user">user</option><option value="team_lead">team_lead</option><option value="admin">admin</option></select></label>
          <label className="block text-sm text-slate-300">初始密码<input aria-label="初始密码" type="password" minLength={8} required value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 h-10 w-full rounded-soft border border-white/[0.08] bg-surface-1 px-3 text-white outline-none focus:border-mint-400/50" /></label>
          {resource.create.isError ? <p role="alert" className="text-sm text-rose">{message(resource.create.error)}</p> : null}
        </form>
      </Modal>

      <Modal
        open={Boolean(resetTarget)}
        onClose={() => setResetTarget(null)}
        title="重置密码"
        subtitle={resetTarget ? `账号：${resetTarget.name}` : undefined}
        footer={<><Button variant="ghost" onClick={() => setResetTarget(null)}>取消</Button><Button type="submit" form="reset-password-form" loading={resource.resetPassword.isPending}>确认重置</Button></>}
      >
        <form id="reset-password-form" onSubmit={submitReset}>
          <label className="block text-sm text-slate-300">新密码<input aria-label="新密码" type="password" minLength={8} required value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="mt-2 h-10 w-full rounded-soft border border-white/[0.08] bg-surface-1 px-3 text-white outline-none focus:border-mint-400/50" /></label>
          {resource.resetPassword.isError ? <p role="alert" className="mt-3 text-sm text-rose">{message(resource.resetPassword.error)}</p> : null}
        </form>
      </Modal>
    </Card>
  )
}
