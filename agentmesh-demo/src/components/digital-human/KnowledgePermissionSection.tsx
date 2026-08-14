import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ShieldCheck, BookMarked, Users, Quote, Layers } from 'lucide-react'
import { SectionCard } from '../ui/Card'
import { StatTile } from '../ui/StatTile'
import { SegmentedControl } from '../ui/SegmentedControl'
import { ShareTimeline } from '../knowledge/ShareTimeline'
import { DIGITAL_PROFILE, type ShareEvent } from '../../data/mockData'
import { SCOPE_LABELS, useDemo, type ShareScope } from '../../store/DemoContext'
import { cn } from '../../lib/cn'

const SCOPE_OPTIONS = (Object.keys(SCOPE_LABELS) as ShareScope[]).map((k) => ({
  key: k,
  label: SCOPE_LABELS[k],
}))

/**
 * 知识与权限 —— 数字人可用的知识范围、默认共享范围、以及授权与引用记录。
 * 累计成效指标从首页搬迁到此(帮助同事 / 知识被引用 / 支持项目)。
 * 复用 ShareTimeline(隐藏其自带头部,避免与本区标题重复)。
 */
export function KnowledgePermissionSection() {
  const navigate = useNavigate()
  const { shareScope, peopleHelped, monthlyCitations, shareEvents, shareEventCount } = useDemo()

  // 默认共享范围为装饰态(context 未暴露 setter),本地维护以便交互演示。
  const [scope, setScope] = useState<ShareScope>(shareScope)

  const openEvent = (_event: ShareEvent) => navigate('/knowledge?tab=shared')

  return (
    <div className="animate-fade-in space-y-6">
      <header>
        <h1 className="flex items-center gap-2.5 text-xl font-semibold text-white">
          <ShieldCheck className="h-5 w-5 text-mint-300" />
          知识与权限
        </h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">
          管理数字人可以使用的知识范围、默认共享范围,以及每一次授权与引用的记录。
          <span className="text-slate-300">引用都会保留来源与适用范围,不自动扩大共享。</span>
        </p>
      </header>

      {/* 可用知识范围 */}
      <SectionCard title="可用知识范围" icon={<BookMarked className="h-4 w-4" />}>
        <div className="space-y-2.5 text-[13px] leading-relaxed text-slate-400">
          <p className="flex items-baseline justify-between gap-4">
            <span>你确认沉淀的个人知识</span>
            <span className="text-slate-200">{DIGITAL_PROFILE.personalKnowledge} 条</span>
          </p>
          <p className="flex items-baseline justify-between gap-4">
            <span>家电设计组共享给你的团队知识</span>
            <span className="text-slate-200">按团队权限调用</span>
          </p>
          <p className="text-[12.5px] text-slate-500">
            数字人只能使用你确认的个人知识,以及你所在团队按权限共享的知识,不会读取成员的私人知识。
          </p>
        </div>
      </SectionCard>

      {/* 默认共享范围 + 装饰开关 */}
      <SectionCard
        title="默认共享范围"
        icon={<Users className="h-4 w-4" />}
        desc="新沉淀知识的默认可见范围,单条知识仍可单独调整。"
        action={
          <SegmentedControl
            options={SCOPE_OPTIONS}
            value={scope}
            onChange={(k) => setScope(k as ShareScope)}
            size="sm"
          />
        }
      >
        <div className="space-y-1">
          <ToggleRow label="新知识需我确认后再共享" hint="沉淀的知识候选先经你确认,不自动对外可见" defaultOn />
          <ToggleRow label="被引用时保留来源与适用范围" hint="其他数字人引用时始终标注来源,不改写原知识" defaultOn />
          <ToggleRow label="允许团队在授权后检索我的知识" hint="团队成员需经你授权才能在项目中引用" defaultOn />
        </div>
      </SectionCard>

      {/* 累计成效指标(从首页搬迁) */}
      <SectionCard title="累计协作成效" icon={<Quote className="h-4 w-4" />} desc="你的知识对团队的长期贡献。">
        <div className="grid grid-cols-3 gap-3">
          <StatTile label="帮助同事" value={peopleHelped} icon={<Users className="h-4 w-4" />} tone="collab" hint="位同事的数字人" />
          <StatTile label="知识被引用" value={monthlyCitations} icon={<Quote className="h-4 w-4" />} tone="knowledge" hint="次累计引用" />
          <StatTile label="支持项目" value={DIGITAL_PROFILE.projectsSupported} icon={<Layers className="h-4 w-4" />} tone="mint" hint="个项目复用" />
        </div>
      </SectionCard>

      {/* 授权与引用记录(复用 ShareTimeline,隐藏自带头部) */}
      <div>
        <h2 className="mb-3 text-[15px] font-semibold text-slate-100">授权与引用记录</h2>
        <ShareTimeline events={shareEvents} totalCount={shareEventCount} onOpenEvent={openEvent} showHeader={false} />
      </div>
    </div>
  )
}

/* ─────────── 内部辅助 ─────────── */

function ToggleRow({ label, hint, defaultOn = false }: { label: string; hint?: string; defaultOn?: boolean }) {
  const [on, setOn] = useState(defaultOn)
  return (
    <button
      type="button"
      onClick={() => setOn((v) => !v)}
      className="flex w-full items-center justify-between gap-4 rounded-[10px] px-2 py-2.5 text-left transition-colors hover:bg-white/[0.03]"
    >
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-slate-200">{label}</span>
        {hint && <span className="mt-0.5 block text-[11.5px] text-slate-500">{hint}</span>}
      </span>
      <span
        className={cn(
          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
          on ? 'bg-mint-400' : 'bg-white/[0.12]',
        )}
      >
        <span className={cn('h-4 w-4 rounded-full bg-white shadow transition-all', on ? 'ml-auto mr-0.5' : 'ml-0.5')} />
      </span>
    </button>
  )
}
