import { Network, ShieldCheck } from 'lucide-react'
import { Drawer } from '../ui/Drawer'
import { cn } from '../../lib/cn'
import type { TaskCard } from '../../features/collaboration/api'

interface CollabTimelineDrawerProps {
  open: boolean
  onClose: () => void
  card?: TaskCard | null
}

const DEFAULT_STEPS = [
  { title: '识别信息缺口', detail: '当前项目缺少 2025 年 618 一线设计经验和近期入口数据。' },
  { title: '匹配李明的数字员工', detail: '匹配原因：参与过 2025 年 618 家电会场项目。' },
  { title: '获得历史项目经验', detail: '补充沉浸式头图对首屏入口可见性的影响判断。' },
  { title: '匹配王晨的数字员工', detail: '匹配原因：近期负责首页入口数据分析相关工作。' },
  { title: '获得近期数据', detail: '补充近 90 天入口点击数据与统计口径提醒。' },
  { title: '协作结果进入当前项目', detail: '用于 2026 年 618 家电会场首页设计 Brief，并记录全部来源。' },
]

export function CollabTimelineDrawer({ open, onClose, card }: CollabTimelineDrawerProps) {
  const steps = card
    ? [
        { title: '任务创建', detail: card.task.title },
        { title: '最新进展', detail: card.latest_post.content },
        { title: '当前状态', detail: card.task.collaboration_stage === 'completed' ? '已完成' : card.task.collaboration_stage === 'blocked' ? '需关注' : '进行中' },
      ]
    : DEFAULT_STEPS

  const title = card ? card.task.title : '查找 618 家电会场历史经验'
  const subtitle = card ? `最新更新：${card.latest_post.title}` : '这次协作是如何发生的'

  return (
    <Drawer
      open={open}
      onClose={onClose}
      icon={<Network className="h-5 w-5" />}
      title={title}
      subtitle={subtitle}
      width={520}
    >
      <div className="space-y-5">
        <ol className="relative space-y-5">
          {steps.map((step, index) => {
            const last = index === steps.length - 1
            return (
              <li key={step.title} className="relative flex gap-3.5">
                {!last && <span className="absolute left-[5px] top-4 h-[calc(100%+24px)] w-px bg-white/[0.09]" />}
                <span className={cn('relative z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full ring-4 ring-surface-2', last ? 'bg-mint-400' : 'bg-slate-500')} />
                <div className="min-w-0 flex-1 pb-1">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">0{index + 1}</div>
                  <h3 className="text-[13.5px] font-semibold text-slate-100">{step.title}</h3>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-slate-400">{step.detail}</p>
                </div>
              </li>
            )
          })}
        </ol>
        <div className="flex items-start gap-2 border-t border-white/[0.06] pt-4 text-[11.5px] leading-relaxed text-slate-500">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          全部协作仅使用已授权共享的工作知识，经验、数据和贡献来源均已记录在项目 Brief 中。
        </div>
      </div>
    </Drawer>
  )
}
