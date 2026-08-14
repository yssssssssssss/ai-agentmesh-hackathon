import { Quote, Clock, Sparkles, Target, FolderClock, BadgeCheck } from 'lucide-react'
import { Badge } from '../ui/Badge'
import type { KnowledgeAsset } from '../../data/mockData'
import { cn } from '../../lib/cn'

interface AssetCardProps {
  data: KnowledgeAsset
  onClick?: () => void
}

/**
 * 知识资产卡片(修改文档 §8.3、§13):
 *   标题 / 一句话结论 → 第一视觉层级
 *   类型 · 适用范围 · 来源项目 · 验证状态 · 权限 · 引用次数 · 更新时间 → 辅助信息
 * 卡片 hover 出现轻微边框增强,整卡可点击进入右侧详情抽屉。
 * 语义色仅用于:仅自己 / 已共享 / 有新反馈 / 刚沉淀。
 */
export function AssetCard({ data, onClick }: AssetCardProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'group relative flex h-full w-full flex-col rounded-[12px] border p-5 text-left transition-all duration-150',
        'border-white/[0.06] bg-surface-2 hover:-translate-y-0.5 hover:border-white/[0.16] hover:bg-surface-3',
        data.justConfirmed && 'border-mint-400/25 bg-mint-400/[0.04]',
      )}
    >
      {/* 主标题 + 状态 */}
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 text-[15px] font-semibold leading-snug text-white">{data.title}</h3>
        <div className="flex shrink-0 items-center gap-1.5">
          {data.justConfirmed && <Badge tone="mint" dot>刚沉淀</Badge>}
          {data.hasNewFeedback && !data.justConfirmed && <Badge tone="remind" dot>有新反馈</Badge>}
        </div>
      </div>

      {/* 经验结论 */}
      <p className="mt-1.5 h-10 line-clamp-2 text-[13px] leading-5 text-slate-400">
        {data.conclusion}
      </p>

      {/* 元信息:适用范围 / 来源 / 验证 */}
      <dl className="mt-3.5 space-y-1.5 text-[12px] text-slate-500">
        <MetaLine icon={<Target className="h-3 w-3" />} label="适用范围" value={data.scope} />
        <MetaLine icon={<FolderClock className="h-3 w-3" />} label="来源项目" value={data.sourceProject} />
        <MetaLine icon={<BadgeCheck className="h-3 w-3" />} label="验证依据" value={verificationBasis(data.verified)} className="pb-3" />
      </dl>

      {/* 底部:引用次数 + 更新时间 */}
       <div className="mt-auto flex items-center justify-between gap-3 border-t border-white/[0.05] pt-3">
         <span className="inline-flex items-center gap-1.5 text-[11.5px] text-slate-500">
          <Quote className="h-3 w-3" />
          被引用
          <span
            className={cn(
              'tabular-nums font-medium',
               data.citedBy > 0 ? 'text-white' : 'text-slate-500',
            )}
          >
            {data.citedBy}
          </span>
          次
        </span>
        <span className="inline-flex items-center gap-1 text-[11.5px] text-slate-500">
          <Clock className="h-3 w-3" />
          {data.updated}
        </span>
      </div>

      {/* hover 时右上角小箭头(用于强化可点击感,不必单独一个按钮) */}
      <span
        aria-hidden
        className="pointer-events-none absolute right-4 top-4 hidden text-slate-500 opacity-0 transition-opacity duration-150 group-hover:opacity-100 md:inline"
      >
        <Sparkles className="h-3.5 w-3.5" />
      </span>
    </button>
  )
}

function verificationBasis(verified: string) {
  if (verified.includes('测试')) return '实际测试'
  if (verified.includes('数据')) return '业务数据'
  return '项目复盘'
}

function MetaLine({ icon, label, value, className }: { icon: React.ReactNode; label: string; value: string; className?: string }) {
  return (
    <div className={cn('flex items-start gap-1.5', className)}>
      <span className="mt-[2px] shrink-0 text-slate-500">{icon}</span>
      <span className="shrink-0 text-slate-500">{label}:</span>
      <span className="truncate text-slate-400">{value}</span>
    </div>
  )
}
