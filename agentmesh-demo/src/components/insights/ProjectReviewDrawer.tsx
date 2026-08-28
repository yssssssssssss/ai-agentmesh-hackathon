import { AlertCircle, CheckCircle2, ClipboardList, LockKeyhole } from 'lucide-react'

import { REVIEW_FLOW, REVIEW_PROJECT } from '../../data/mockData'
import type { PresentedValue } from '../../lib/presentation'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'
import { Drawer } from '../ui/Drawer'

interface ProjectReviewDrawerProps {
  open: boolean
  onClose: () => void
  opportunity?: PresentedValue<typeof REVIEW_PROJECT>
  evidence?: PresentedValue<typeof REVIEW_FLOW.evidence>
  flow?: PresentedValue<{
    missingHint: string
    resultPlaceholder: string
    candidateReadyHint: string
    candidateTitle: string
  }>
}

export function ProjectReviewDrawer({
  open,
  onClose,
  opportunity,
  evidence,
  flow,
}: ProjectReviewDrawerProps) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={560}
      icon={<ClipboardList className="h-4 w-4" />}
      title="参考复盘结构"
      subtitle="以下内容来自 M 数据，仅用于恢复参考信息结构，不代表当前项目事实"
      footer={
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-xs text-[11px] leading-5 text-slate-400">
            后端尚未提供复盘写入与知识候选接口，当前不能保存、确认或形成候选。
          </p>
          <Button disabled icon={<LockKeyhole className="h-4 w-4" />}>
            开始复盘（暂不可用）
          </Button>
        </div>
      }
    >
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          <DataSourceBadge source="M" />
          <Badge tone="remind">只读参考</Badge>
        </div>

        {opportunity ? (
          <section>
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">复盘机会</h3>
            <h4 className="mt-2 text-[16px] font-semibold text-slate-100">{opportunity.value.name}</h4>
            <p className="mt-2 text-[13px] leading-6 text-slate-400">{opportunity.value.judgment}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {opportunity.value.directions.map((direction) => (
                <Badge key={direction} tone="neutral">{direction}</Badge>
              ))}
            </div>
            <p className="mt-3 text-[11px] leading-5 text-remind">{opportunity.reason}</p>
          </section>
        ) : null}

        {evidence ? (
          <section className="border-t border-white/[0.06] pt-5">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">参考证据检查</h3>
            <ul className="mt-3 space-y-2">
              {evidence.value.map((item) => (
                <li key={item.label} className="flex items-start gap-3 rounded-soft bg-surface-1 px-3.5 py-3">
                  {item.ready ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-mint-300" />
                  ) : (
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-remind" />
                  )}
                  <div>
                    <p className="text-[13px] font-medium text-slate-200">{item.label}</p>
                    <p className="mt-1 text-[12px] leading-5 text-slate-400">{item.note}</p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {flow ? (
          <section className="border-t border-white/[0.06] pt-5">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">知识形成条件</h3>
            <p className="mt-2 text-[13px] leading-6 text-slate-400">{flow.value.missingHint}</p>
            <div className="mt-3 rounded-soft bg-remind/[0.06] px-3.5 py-3">
              <p className="text-[11px] text-remind">参考候选标题</p>
              <p className="mt-1 text-[13px] font-medium text-slate-200">{flow.value.candidateTitle}</p>
            </div>
            <p className="mt-3 text-[11px] leading-5 text-remind">{flow.reason}</p>
          </section>
        ) : null}

        {!opportunity && !evidence && !flow ? (
          <p className="text-sm leading-6 text-slate-400">当前没有可安全展示的复盘参考内容。</p>
        ) : null}
      </div>
    </Drawer>
  )
}
