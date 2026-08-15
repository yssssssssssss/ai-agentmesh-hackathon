import { useState, type FormEvent } from 'react'
import { ArrowRight, Loader2, LockKeyhole, Network, ShieldCheck, UserRound, UsersRound } from 'lucide-react'

import { ApiError } from '../../api/client'
import { Button } from '../../components/ui/Button'
import { useAuth } from './AuthProvider'

const DEMO_ROLES = [
  {
    id: 'designer',
    label: '当前设计师',
    detail: '个人工作',
    userId: 'usr_current_designer',
    password: 'designer123',
    icon: UserRound,
  },
  {
    id: 'team-lead',
    label: '设计组长',
    detail: '团队协作',
    userId: 'usr_team_lead',
    password: 'lead123',
    icon: UsersRound,
  },
  {
    id: 'admin',
    label: '平台管理员',
    detail: '平台管理',
    userId: 'usr_admin',
    password: 'admin123',
    icon: ShieldCheck,
  },
] as const

type DemoRole = (typeof DEMO_ROLES)[number]

function loginErrorMessage(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  return '无法完成登录，请检查网络后重试'
}

export function LoginPage() {
  const { status, user, message, logoutError, login, logout } = useAuth()
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [activePresetId, setActivePresetId] = useState<DemoRole['id'] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const runLogin = async (account: string, credential: string, presetId: DemoRole['id'] | null) => {
    setSubmitting(true)
    setActivePresetId(presetId)
    setError(null)
    try {
      await login(account, credential)
    } catch (caught) {
      setError(loginErrorMessage(caught))
    } finally {
      setSubmitting(false)
      setActivePresetId(null)
    }
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runLogin(userId.trim(), password, null)
  }

  const handlePresetLogin = async (role: DemoRole) => {
    await runLogin(role.userId, role.password, role.id)
  }

  if (status === 'revocation-required') {
    return (
      <main className="flex min-h-full items-center justify-center bg-canvas px-5 py-10">
        <section className="w-full max-w-md text-center" aria-live="polite">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-[12px] bg-white/[0.05] text-slate-300">
            <LockKeyhole className="h-5 w-5" aria-hidden="true" />
          </span>
          <h1 className="mt-6 text-2xl font-semibold text-slate-100">会话需要撤销</h1>
          <p className="mt-3 text-sm leading-6 text-slate-400">
            {message ?? '登录后的工作空间初始化失败，必须先撤销服务端会话。'}
          </p>
          <p className="mt-4 text-sm text-slate-300">
            候选会话：{user ? `${user.name}${user.id ? `（${user.id}）` : ''}` : '当前账号'}
          </p>
          {logoutError ? (
            <p role="alert" className="mt-4 rounded-[10px] bg-rose/10 px-4 py-3 text-sm leading-6 text-rose">
              {logoutError}
            </p>
          ) : null}
          <Button className="mt-7" onClick={() => void logout().catch(() => undefined)}>
            重试退出
          </Button>
        </section>
      </main>
    )
  }

  return (
    <main className="grid min-h-full bg-canvas lg:grid-cols-[minmax(0,1.15fr)_minmax(420px,0.85fr)]">
      <section className="relative hidden overflow-hidden border-r border-white/[0.06] bg-base px-12 py-14 lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-[12px] bg-mint-400/12 text-mint-300">
            <Network className="h-6 w-6" aria-hidden="true" />
          </span>
          <div>
            <p className="text-base font-semibold text-slate-100">AgentMesh</p>
            <p className="text-xs text-slate-500">团队智能协作空间</p>
          </div>
        </div>
        <div className="max-w-xl pb-10">
          <p className="mb-5 text-xs font-semibold uppercase tracking-[0.18em] text-mint-300">Internal pilot</p>
          <h1 className="text-balance text-5xl font-semibold leading-[1.08] text-slate-100">
            让团队经验进入每一次工作决策。
          </h1>
          <p className="mt-6 max-w-lg text-pretty text-base leading-8 text-slate-400">
            登录后进入你的数字人、工作台和共享知识空间。权限与数据范围由服务端统一控制。
          </p>
        </div>
        <p className="text-xs text-slate-600">同源会话，不在浏览器存储访问令牌</p>
      </section>

      <section className="flex min-h-full items-center justify-center px-5 py-10 sm:px-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-[12px] bg-mint-400/12 text-mint-300">
              <Network className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <p className="font-semibold text-slate-100">AgentMesh</p>
              <p className="text-xs text-slate-500">团队智能协作空间</p>
            </div>
          </div>

          <div className="mb-8">
            <span className="mb-5 flex h-10 w-10 items-center justify-center rounded-[10px] bg-white/[0.04] text-slate-300">
              <LockKeyhole className="h-5 w-5" aria-hidden="true" />
            </span>
            <h2 className="text-3xl font-semibold tracking-[-0.012em] text-slate-100">登录工作空间</h2>
            <p className="mt-3 text-sm leading-6 text-slate-400">使用内部试点账号继续。</p>
          </div>

          <section aria-labelledby="demo-roles-title">
            <div className="flex items-baseline justify-between gap-4">
              <h3 id="demo-roles-title" className="text-sm font-semibold text-slate-200">快速演示</h3>
              <p className="text-xs text-slate-500">一键进入预设角色</p>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2">
              {DEMO_ROLES.map((role) => {
                const RoleIcon = role.icon
                const active = activePresetId === role.id
                return (
                  <button
                    key={role.id}
                    type="button"
                    aria-label={`以${role.label}身份进入`}
                    aria-busy={active}
                    disabled={submitting}
                    onClick={() => void handlePresetLogin(role)}
                    className={`min-h-[88px] touch-manipulation rounded-[10px] border px-2.5 py-3 text-center transition-[border-color,background-color,transform] duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50 disabled:cursor-not-allowed disabled:opacity-45 ${
                      active
                        ? 'border-mint-400/50 bg-mint-400/[0.08] text-mint-300'
                        : 'border-white/[0.08] bg-white/[0.025] text-slate-300 [@media(hover:hover)]:hover:border-mint-400/35 [@media(hover:hover)]:hover:bg-mint-400/[0.05]'
                    }`}
                  >
                    {active ? (
                      <Loader2 className="mx-auto h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <RoleIcon className="mx-auto h-4 w-4" aria-hidden="true" />
                    )}
                    <span className="mt-2 block text-xs font-semibold leading-4">{role.label}</span>
                    <span className="mt-1 block text-[11px] leading-4 text-slate-500">{role.detail}</span>
                  </button>
                )
              })}
            </div>
          </section>

          <div className="my-6 flex items-center gap-3 text-[11px] text-slate-600">
            <span className="h-px flex-1 bg-white/[0.06]" aria-hidden="true" />
            <span>或使用账号密码</span>
            <span className="h-px flex-1 bg-white/[0.06]" aria-hidden="true" />
          </div>

          <form className="space-y-5" onSubmit={handleSubmit} noValidate>
            <div>
              <label htmlFor="user-id" className="mb-2 block text-sm font-medium text-slate-300">
                账号
              </label>
              <input
                id="user-id"
                name="userId"
                autoComplete="username"
                required
                disabled={submitting}
                value={userId}
                onChange={(event) => setUserId(event.target.value)}
                className="h-12 w-full rounded-[10px] border border-white/[0.1] bg-surface-1 px-4 text-[15px] text-slate-100 outline-none transition-[border-color,box-shadow] placeholder:text-slate-600 focus:border-mint-400/70 focus:ring-2 focus:ring-mint-400/15"
                placeholder="输入账号"
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-2 block text-sm font-medium text-slate-300">
                密码
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                disabled={submitting}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="h-12 w-full rounded-[10px] border border-white/[0.1] bg-surface-1 px-4 text-[15px] text-slate-100 outline-none transition-[border-color,box-shadow] placeholder:text-slate-600 focus:border-mint-400/70 focus:ring-2 focus:ring-mint-400/15"
                placeholder="输入密码"
              />
            </div>

            {error ? (
              <p role="alert" className="rounded-[10px] bg-rose/10 px-4 py-3 text-sm leading-6 text-rose">
                {error}
              </p>
            ) : null}

            <Button
              type="submit"
              size="lg"
              block
              loading={submitting && activePresetId === null}
              disabled={submitting || !userId.trim() || !password}
              iconRight={<ArrowRight className="h-4 w-4" aria-hidden="true" />}
              className="active:scale-[0.98]"
            >
              登录
            </Button>
          </form>
        </div>
      </section>
    </main>
  )
}
