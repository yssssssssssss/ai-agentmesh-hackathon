import { useRef, useState, type ChangeEvent } from 'react'
import { Target, Users, Building2, Palette, Sparkles, Upload } from 'lucide-react'
import { SectionCard } from '../ui/Card'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DigitalHumanMark } from '../ui/DigitalHumanMark'
import { AGENT_PROFILE } from '../../data/mockData'
import { cn } from '../../lib/cn'

/**
 * 数字人档案 —— 数字人自身的身份信息(独立于用户 ERP 身份)。
 * 从旧首页 WelcomeHero 右侧身份块移下来的长期档案,不再占据首页空间。
 */
export function ProfileSection() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)

  const handleAvatarUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setAvatarUrl((current) => {
      if (current) URL.revokeObjectURL(current)
      return URL.createObjectURL(file)
    })
  }

  return (
    <div className="animate-fade-in space-y-6">
      <header>
        <h1 className="flex items-center gap-2.5 text-xl font-semibold text-white">
          <Target className="h-5 w-5 text-mint-300" />
          数字员工档案
        </h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">
          管理数字员工的基础定位、服务范围与界面形象。
        </p>
      </header>

      {/* 基础信息 */}
      <SectionCard title="基础信息" icon={<Target className="h-4 w-4" />}>
        <div className="divide-y divide-white/[0.05]">
          <InfoRow icon={<Target className="h-4 w-4" />} label="角色定位">
            <span className="text-slate-200">{AGENT_PROFILE.rolePositioning}</span>
          </InfoRow>
          <InfoRow icon={<Users className="h-4 w-4" />} label="服务对象">
            <div className="flex flex-wrap justify-end gap-1.5">
              {AGENT_PROFILE.serviceTargets.map((t) => (
                <Badge key={t} tone="collab">
                  {t}
                </Badge>
              ))}
            </div>
          </InfoRow>
          <InfoRow icon={<Building2 className="h-4 w-4" />} label="所属空间">
            <span className="text-slate-200">{AGENT_PROFILE.space}</span>
          </InfoRow>
          <InfoRow icon={<Palette className="h-4 w-4" />} label="主要领域">
            <div className="flex flex-wrap justify-end gap-1.5">
              {AGENT_PROFILE.domains.map((d) => (
                <Badge key={d} tone="knowledge">
                  {d}
                </Badge>
              ))}
            </div>
          </InfoRow>
        </div>
      </SectionCard>

      {/* 形象与微动画 */}
      <SectionCard
        title="形象与微动画"
        icon={<Sparkles className="h-4 w-4" />}
        desc="管理数字人的头像与界面动效,不改变其能力与权限。"
      >
        <div className="mb-3 flex items-center gap-4 rounded-soft border border-white/[0.06] bg-surface-2 p-4">
          <div className="flex h-[76px] w-[76px] shrink-0 items-center justify-center overflow-hidden rounded-overlay border border-white/[0.08] bg-surface-1">
            {avatarUrl ? (
              <img
                src={avatarUrl}
                alt="数字人头像预览"
                width={76}
                height={76}
                className="h-full w-full object-cover"
              />
            ) : (
              <DigitalHumanMark size={60} />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium text-slate-200">数字人头像</div>
            <p className="mt-1 text-[11.5px] leading-relaxed text-slate-400">
              支持 JPG、PNG 图片,建议使用 1:1 比例的清晰图片。
            </p>
            <Button
              variant="subtle"
              size="sm"
              icon={<Upload className="h-3.5 w-3.5" />}
              className="mt-3"
              onClick={() => fileInputRef.current?.click()}
            >
              上传图片
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg"
              className="hidden"
              onChange={handleAvatarUpload}
            />
          </div>
        </div>
        <div className="space-y-1">
          <ToggleRow label="数字人光效标识" hint="同心环 + 核心光点的抽象身份标识" defaultOn />
          <ToggleRow label="待命微动画" hint="空闲时核心光点的轻微呼吸感" defaultOn />
          <ToggleRow label="消息提示动效" hint="有新协作或待确认时的入口高亮" />
        </div>
      </SectionCard>
    </div>
  )
}

/* ─────────── 内部辅助 ─────────── */

function InfoRow({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
      <span className="flex shrink-0 items-center gap-2 text-[13px] text-slate-400">
        <span className="text-slate-400">{icon}</span>
        {label}
      </span>
      <div className="min-w-0 text-right text-[13px]">{children}</div>
    </div>
  )
}

function ToggleRow({
  label,
  hint,
  defaultOn = false,
}: {
  label: string
  hint?: string
  defaultOn?: boolean
}) {
  const [on, setOn] = useState(defaultOn)
  return (
    <button
      type="button"
      onClick={() => setOn((v) => !v)}
      className="flex w-full items-center justify-between gap-4 rounded-soft px-2 py-2.5 text-left transition-colors hover:bg-white/[0.03]"
    >
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-slate-200">{label}</span>
        {hint && <span className="mt-0.5 block text-[11.5px] text-slate-400">{hint}</span>}
      </span>
      <span
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
          on ? 'bg-mint-400' : 'bg-white/[0.12]',
        )}
      >
        <span
          className={cn(
            'h-4 w-4 rounded-full bg-white shadow transition-[margin] duration-150',
            on ? 'ml-auto mr-0.5' : 'ml-0.5',
          )}
        />
      </span>
    </button>
  )
}
