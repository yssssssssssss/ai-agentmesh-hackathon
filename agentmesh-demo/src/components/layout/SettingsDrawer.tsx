import { useState } from 'react'
import { Settings, Moon, Bell, LogOut } from 'lucide-react'
import { Drawer } from '../ui/Drawer'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Avatar } from '../ui/Avatar'
import { LogoutConfirmModal } from './LogoutConfirmModal'
import { CURRENT_USER } from '../../data/mockData'
import { cn } from '../../lib/cn'

const ERP_ACCOUNT = 'linzhixia'

interface SettingsDrawerProps {
  open: boolean
  onClose: () => void
}

/**
 * 设置抽屉 —— 只承载与「显示 / 偏好」和「登录 / 安全」相关的用户自助项。
 * 管理员 / 平台后台入口已迁出(改由账号菜单在「管理员视角」下显隐),
 * 保持普通用户前台的克制。所有偏好项在 Demo 中均为装饰态,只保留深色主题。
 */
export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const [logoutOpen, setLogoutOpen] = useState(false)
  const [darkTheme, setDarkTheme] = useState(true)
  const [notify, setNotify] = useState(true)

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        icon={<Settings className="h-5 w-5" />}
        title="账号与设置"
        subtitle="林知夏 · ERP 统一身份"
        width={460}
      >
        <div className="space-y-6">
          {/* 账号与身份 */}
          <section>
            <div className="mb-3 flex items-center gap-3">
              <Avatar name={CURRENT_USER.name} size="md" tone="mint" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[15px] font-semibold text-white">{CURRENT_USER.name}</span>
                  <Badge tone="neutral">普通员工</Badge>
                </div>
                <div className="mt-0.5 text-xs text-slate-500">{CURRENT_USER.space}</div>
              </div>
            </div>
            <div className="space-y-1.5 rounded-[12px] border border-white/[0.06] bg-surface-1 px-4 py-3">
              <RowLine label="姓名" value={CURRENT_USER.name} />
              <RowLine label="ERP 账号" value={<span className="font-mono text-[11.5px]">{ERP_ACCOUNT}</span>} />
              <RowLine label="团队" value={CURRENT_USER.space} />
              <RowLine label="当前身份" value="普通员工" />
            </div>
          </section>

          {/* 显示与偏好 */}
          <section>
            <h3 className="mb-2.5 text-sm font-semibold text-slate-200">显示与偏好</h3>
            <div className="divide-y divide-white/[0.05] overflow-hidden rounded-[12px] border border-white/[0.06] bg-surface-1">
              <ToggleRow
                icon={<Moon className="h-4 w-4 text-slate-400" />}
                label="深色主题"
                hint="当前 Demo 仅提供深色企业主题"
                on={darkTheme}
                onToggle={() => setDarkTheme((v) => !v)}
              />
              <ToggleRow
                icon={<Bell className="h-4 w-4 text-slate-400" />}
                label="消息通知"
                hint="协作请求、授权与反馈的桌面提醒"
                on={notify}
                onToggle={() => setNotify((v) => !v)}
              />
            </div>
          </section>

          <Button
            variant="danger"
            block
            icon={<LogOut className="h-4 w-4" />}
            onClick={() => setLogoutOpen(true)}
          >
            退出登录
          </Button>
        </div>
      </Drawer>

      {/* 抽屉内自挂登出确认(与侧栏那个实例各自独立,任一时刻只会开一个) */}
      <LogoutConfirmModal open={logoutOpen} onClose={() => setLogoutOpen(false)} />
    </>
  )
}

/* ─────────── 内部辅助 ─────────── */

function RowLine({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 text-[12px]">
      <span className="text-slate-500">{label}</span>
      <span className="min-w-0 flex-1 truncate text-right text-slate-300">{value}</span>
    </div>
  )
}

function ToggleRow({
  icon,
  label,
  hint,
  on,
  onToggle,
}: {
  icon: React.ReactNode
  label: string
  hint?: string
  on: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-white/[0.02]"
      role="switch"
      aria-checked={on}
    >
      {icon}
      <span className="min-w-0 flex-1">
        <span className="block text-sm text-slate-200">{label}</span>
        {hint && <span className="mt-0.5 block text-[11px] text-slate-500">{hint}</span>}
      </span>
      <span
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
          on ? 'bg-mint-400' : 'bg-white/[0.12]',
        )}
      >
        <span
          className={cn(
            'h-4 w-4 rounded-full bg-white shadow transition-all',
            on ? 'ml-auto mr-0.5' : 'ml-0.5',
          )}
        />
      </span>
    </button>
  )
}

