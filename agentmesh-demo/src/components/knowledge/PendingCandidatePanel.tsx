import type { ReactNode } from 'react'
import {
  ArrowUpRight,
  Check,
  Clock,
  FileCheck2,
  FolderClock,
  Info,
  Lightbulb,
  ShieldAlert,
  Wrench,
  X,
} from 'lucide-react'

import type { PendingKnowledgeView } from '../../features/knowledge/presenter'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'

interface Props {
  items: PendingKnowledgeView[]
  busy: boolean
  pendingToolApproval: { itemId: string; callId: string; action: 'approve' | 'reject' } | null
  readOnly: boolean
  onConfirm: (item: PendingKnowledgeView) => void
  onSnooze: (item: PendingKnowledgeView) => void
  onResolve: (item: PendingKnowledgeView) => void
  onInjection: (item: PendingKnowledgeView, action: 'release' | 'discard') => void
  onToolApproval: (item: PendingKnowledgeView, callId: string, action: 'approve' | 'reject') => void
  onAccept: (item: PendingKnowledgeView) => void
  onOpenDetail: (item: PendingKnowledgeView) => void
}

export function PendingCandidatePanel({
  items,
  busy,
  pendingToolApproval,
  readOnly,
  onConfirm,
  onSnooze,
  onResolve,
  onInjection,
  onToolApproval,
  onAccept,
  onOpenDetail,
}: Props) {
  return (
    <div className="animate-fade-in space-y-5">
      {items.map((item) => {
        const actions = item.allowedActions.value
        const injectionReview = item.itemType.value === 'prompt_injection_review'
        const toolApproval = item.itemType.value === 'sdk_tool_approval'
        return (
          <article
            key={`${item.kind}-${item.id.value}`}
            data-inbox-item-id={item.id.value}
            className="card-base overflow-hidden"
          >
            <section className="p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex min-w-0 items-start gap-3.5">
                  <span className={toolApproval
                    ? 'flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-remind/12 text-remind'
                    : 'flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-mint-400/12 text-mint-300'}>
                    {toolApproval ? <Wrench className="h-5 w-5" /> : injectionReview ? <ShieldAlert className="h-5 w-5" /> : item.kind === 'team_candidate' ? <Lightbulb className="h-5 w-5" /> : <FileCheck2 className="h-5 w-5" />}
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={item.status.value === 'snoozed' ? 'neutral' : 'remind'} dot>
                        {item.status.value === 'snoozed' ? '已稍后处理' : toolApproval ? '待工具审批' : '待确认'}
                      </Badge>
                      <Badge tone="knowledge">{toolApproval ? 'SDK 工具调用' : item.memoryType.value}</Badge>
                      {toolApproval ? <Badge tone="neutral">非 Plan Approval</Badge> : null}
                      <Badge tone="neutral">{item.sourceProject.value}</Badge>
                      <DataSourceBadge source={item.title.source} />
                    </div>
                    <h2 className="mt-2 text-[18px] font-semibold leading-snug text-white">{item.title.value}</h2>
                    <p className="mt-2 text-[14px] leading-relaxed text-slate-300">{item.summary.value}</p>
                  </div>
                </div>
                {!toolApproval ? (
                  <button
                    type="button"
                    onClick={() => onOpenDetail(item)}
                    className="inline-flex min-h-10 shrink-0 items-center gap-1 rounded-lg px-2 text-xs text-slate-500 transition-colors active:scale-[0.98] hover:bg-white/[0.04] hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
                  >
                    查看详情 <ArrowUpRight className="h-3 w-3" />
                  </button>
                ) : null}
              </div>
            </section>

            <section className="border-t border-white/[0.06] bg-surface-1/45 px-6 py-4">
              <div className="grid gap-3 text-xs text-slate-400 sm:grid-cols-2 lg:grid-cols-4">
                <Meta icon={<FolderClock className="h-3.5 w-3.5" />} label="来源项目" value={item.sourceProject.value} source={item.sourceProject.source} />
                <Meta icon={<Info className="h-3.5 w-3.5" />} label="候选类型" value={toolApproval ? 'SDK 工具调用' : item.itemType.value} source={item.itemType.source} />
                <Meta icon={<Clock className="h-3.5 w-3.5" />} label="形成时间" value={formatTime(item.createdAt.value)} source={item.createdAt.source} />
                <Meta icon={<FileCheck2 className="h-3.5 w-3.5" />} label="文档版本" value={item.documentVersion.value === null ? '不适用' : `v${item.documentVersion.value}`} source={item.documentVersion.source} />
              </div>
            </section>

            <section className="border-t border-white/[0.06] px-6 py-5">
              {toolApproval ? (
                <ToolApprovalActions
                  item={item}
                  busy={busy}
                  pending={pendingToolApproval}
                  readOnly={readOnly}
                  onResolve={onToolApproval}
                />
              ) : (
                <div className="flex flex-wrap items-center gap-2.5">
                {actions.includes('confirm_brief') ? (
                  <Button loading={busy} disabled={readOnly} icon={<Check className="h-4 w-4" />} onClick={() => onConfirm(item)}>确认并沉淀</Button>
                ) : null}
                {actions.includes('accept') ? (
                  <Button loading={busy} disabled={readOnly} icon={<Check className="h-4 w-4" />} onClick={() => onAccept(item)}>接受候选</Button>
                ) : null}
                {actions.includes('snooze') ? (
                  <Button variant="subtle" disabled={busy || readOnly} icon={<Clock className="h-4 w-4" />} onClick={() => onSnooze(item)}>稍后处理</Button>
                ) : null}
                {actions.includes('release') ? (
                  <Button variant="secondary" disabled={busy || readOnly} onClick={() => onInjection(item, 'release')}>释放内容</Button>
                ) : null}
                {actions.includes('discard') ? (
                  <Button variant="danger" disabled={busy || readOnly} icon={<X className="h-4 w-4" />} onClick={() => onInjection(item, 'discard')}>丢弃内容</Button>
                ) : null}
                {actions.includes('resolve') ? (
                  <Button variant="ghost" disabled={busy || readOnly} onClick={() => onResolve(item)}>标记已解决</Button>
                ) : null}
                {actions.length === 0 ? <span className="text-xs text-slate-500">服务端未开放可执行操作。</span> : null}
                </div>
              )}
            </section>
          </article>
        )
      })}

      <div className="flex items-start gap-2 text-[12px] leading-relaxed text-slate-500">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Inbox 项只有在服务端返回对应 allowed_actions 后才可处理。工具审批按 call_id 生效；确认 Brief 会携带当前文档版本，避免覆盖并发更新。
      </div>
    </div>
  )
}

function ToolApprovalActions({
  item,
  busy,
  pending,
  readOnly,
  onResolve,
}: {
  item: PendingKnowledgeView
  busy: boolean
  pending: { itemId: string; callId: string; action: 'approve' | 'reject' } | null
  readOnly: boolean
  onResolve: (item: PendingKnowledgeView, callId: string, action: 'approve' | 'reject') => void
}) {
  const actions = item.allowedActions.value
  const canApprove = actions.includes('approve_tool')
  const canReject = actions.includes('reject_tool')
  const calls = item.toolCalls.value

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2.5 rounded-[10px] border border-remind/20 bg-remind/[0.06] p-3 text-xs leading-5 text-slate-300">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-remind" aria-hidden="true" />
        <p>
          这是运行中的工具调用审批，不是 Plan Approval。每次决定只作用于对应 call_id，处理后仍可能保留其他待审批调用。
        </p>
      </div>

      {calls.length > 0 ? (
        <ul className="space-y-2.5">
          {calls.map((call) => (
            <li
              key={call.callId}
              data-tool-call-id={call.callId}
              className="flex flex-col gap-3 rounded-[10px] bg-base p-3.5 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-100">{call.name}</p>
                <p className="mt-1 break-all font-mono text-[11px] text-slate-500">call_id: {call.callId}</p>
                <p className="mt-1 text-[11px] text-slate-500">
                  参数字段：{call.argumentKeys.length > 0 ? call.argumentKeys.join('、') : '无'}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                {canApprove ? (
                  <Button
                    size="sm"
                    loading={pending?.itemId === item.id.value && pending.callId === call.callId && pending.action === 'approve'}
                    disabled={busy || readOnly}
                    icon={<Check className="h-4 w-4" />}
                    onClick={() => onResolve(item, call.callId, 'approve')}
                  >
                    批准此调用
                  </Button>
                ) : null}
                {canReject ? (
                  <Button
                    variant="danger"
                    size="sm"
                    loading={pending?.itemId === item.id.value && pending.callId === call.callId && pending.action === 'reject'}
                    disabled={busy || readOnly}
                    icon={<X className="h-4 w-4" />}
                    onClick={() => onResolve(item, call.callId, 'reject')}
                  >
                    拒绝此调用
                  </Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p role="alert" className="text-xs text-remind">审批详情缺少可用的 call_id，无法安全处理。</p>
      )}

      {!canApprove && !canReject ? (
        <span className="text-xs text-slate-500">服务端未开放可执行操作。</span>
      ) : null}
    </div>
  )
}

function Meta({ icon, label, value, source }: { icon: ReactNode; label: string; value: string; source: 'M' | 'T' }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <span className="shrink-0 text-slate-500">{icon}</span>
      <span className="shrink-0 text-slate-500">{label}:</span>
      <span className="truncate text-slate-300">{value}</span>
      <DataSourceBadge source={source} />
    </div>
  )
}

function formatTime(value: string) {
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString('zh-CN')
}
