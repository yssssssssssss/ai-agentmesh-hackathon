import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ShieldCheck, ArrowRight, LogIn } from 'lucide-react'
import { DigitalHumanMark } from '../components/ui/DigitalHumanMark'
import { Button } from '../components/ui/Button'
import { useSession } from '../store/SessionContext'
import { ApiError } from '../lib/api'

/**
 * ERP 统一登录示意页 —— 独立布局,不进入 AppLayout。
 *
 * 演示目的:说明数字人接入的是京东内部 ERP 统一身份认证 —
 *   · 只保留主入口:ERP 账号 + "使用 ERP 统一登录"
 *   · 不出现密码 / 短信验证码 / 第三方登录 / 注册,统一由 ERP 侧完成
 *   · 底部安全说明保持与其他系统一致的语气
 *
 * 接入说明:演示环境把 ERP 账号映射到后端种子用户,口令使用种子默认口令桥接;
 * 真实环境应由 ERP SSO 回跳携带票据,前端不接触口令。
 */

/** ERP 账号 → 后端种子用户(user_id, 演示口令)。 */
const ERP_ACCOUNTS: Record<string, { userId: string; password: string }> = {
  linzhixia: { userId: 'usr_current_designer', password: 'designer123' },
  designer: { userId: 'usr_current_designer', password: 'designer123' },
  lead: { userId: 'usr_team_lead', password: 'lead123' },
  admin: { userId: 'usr_admin', password: 'admin123' },
}

export function Login() {
  const navigate = useNavigate()
  const { login } = useSession()
  const [erp, setErp] = useState('linzhixia')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const disabled = erp.trim().length === 0 || submitting

  const handleLogin = async () => {
    if (disabled) return
    const account = ERP_ACCOUNTS[erp.trim().toLowerCase()]
    setSubmitting(true)
    setError(null)
    try {
      // 未配置的 ERP 账号按当前设计师演示登录
      const cred = account ?? ERP_ACCOUNTS.linzhixia
      await login(cred.userId, cred.password)
      navigate('/digital-self', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? '账号或口令校验失败' : '登录失败，请稍后重试')
      setSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-canvas">
      {/* 柔和光斑 —— 与首页 WelcomeHero 一致的克制未来感 */}
      <div className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full bg-mint-400/[0.07] blur-3xl" />
      <div className="pointer-events-none absolute -left-40 bottom-0 h-[480px] w-[480px] rounded-full bg-knowledge/[0.06] blur-3xl" />

      {/* 顶部品牌 */}
      <header className="relative px-8 py-6">
        <div className="text-[17px] font-semibold tracking-wide text-white">AgentMesh</div>
      </header>

      {/* 中央登录卡 */}
      <main className="relative flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-[440px]">
          <div className="mb-8 flex flex-col items-center gap-4">
            <DigitalHumanMark size={80} />
            <div className="text-center">
              <h1 className="text-[24px] font-bold tracking-tight text-white">
                登录我的数字员工
              </h1>
              <p className="mt-2 text-[13.5px] leading-relaxed text-slate-400">
                使用你的京东 ERP 账号登录后,数字人会根据 ERP 身份与组织权限
                <br />
                自动加载你可访问的知识与工作理解。
              </p>
            </div>
          </div>

          <div className="rounded-[16px] border border-white/[0.08] bg-surface-1/80 p-6 shadow-pop backdrop-blur">
            {/* ERP 账号 */}
            <label className="block">
              <span className="text-[12.5px] font-medium text-slate-300">ERP 账号</span>
              <input
                value={erp}
                onChange={(e) => setErp(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                placeholder="linzhixia"
                autoFocus
                className="mt-1.5 h-11 w-full rounded-[10px] border border-white/[0.08] bg-surface-2 px-3.5 text-[14px] text-slate-100 placeholder:text-slate-600 focus:border-mint-400/45 focus:outline-none focus:ring-2 focus:ring-mint-400/25"
              />
              <span className="mt-1.5 block text-[11.5px] leading-relaxed text-slate-500">
                示例账号 linzhixia,真实环境将直接沿用你在京东 SSO 的登录态
              </span>
            </label>

            {/* 主按钮 */}
            <Button
              block
              size="lg"
              icon={<LogIn className="h-[18px] w-[18px]" />}
              iconRight={<ArrowRight className="h-4 w-4" />}
              className="mt-5"
              onClick={handleLogin}
              disabled={disabled}
            >
              {submitting ? '登录中…' : '使用 ERP 统一登录'}
            </Button>

            {error && (
              <p className="mt-3 rounded-[8px] border border-red-400/20 bg-red-400/[0.08] px-3 py-2 text-[12px] text-red-300">
                {error}
              </p>
            )}

            {/* 协议 / 说明 */}
            <p className="mt-4 text-[11.5px] leading-relaxed text-slate-500">
              点击"使用 ERP 统一登录",即表示同意《京东员工内部工具使用协议》与《数字人隐私说明》。
              首次登录时,数字人会请求同步你的 HR 组织关系与授权范围。
            </p>
          </div>

          {/* 底部安全说明 */}
          <div className="mt-6 flex items-center justify-center gap-2 text-[11.5px] text-slate-500">
            <ShieldCheck className="h-3.5 w-3.5 text-mint-400/70" />
            由京东统一身份认证提供安全登录
          </div>
        </div>
      </main>
    </div>
  )
}
