import type { ReactNode } from 'react'
import {
  BookOpen,
  ClipboardList,
  FileText,
  History,
  Info,
  Quote,
  ShieldCheck,
  Target,
  Users,
} from 'lucide-react'

import type { MemoryLifecycleAction, MemoryLineage } from '../../features/knowledge/api'
import type {
  KnowledgeAssetView,
  KnowledgeUsageView,
  PendingKnowledgeView,
} from '../../features/knowledge/presenter'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'
import { Drawer } from '../ui/Drawer'

export type DrawerTarget =
  | { kind: 'asset'; asset: KnowledgeAssetView }
  | { kind: 'pending'; item: PendingKnowledgeView }
  | { kind: 'event'; event: KnowledgeUsageView; asset?: KnowledgeAssetView }

type PendingAction = 'confirm' | 'snooze' | 'resolve' | 'release' | 'discard' | 'accept'

interface Props {
  open: boolean
  onClose: () => void
  target: DrawerTarget | null
  busy?: boolean
  readOnly?: boolean
  onPendingAction?: (item: PendingKnowledgeView, action: PendingAction) => void
  lineage?: MemoryLineage | null
  lineageLoading?: boolean
  lineageError?: string | null
  onRevise?: (asset: KnowledgeAssetView) => void
  onTransition?: (asset: KnowledgeAssetView, action: MemoryLifecycleAction) => void
}

export function KnowledgeDetailDrawer({
  open,
  onClose,
  target,
  busy = false,
  readOnly = false,
  onPendingAction,
  lineage = null,
  lineageLoading = false,
  lineageError = null,
  onRevise,
  onTransition,
}: Props) {
  if (!open || !target) return <Drawer open={false} onClose={onClose}>{null}</Drawer>
  if (target.kind === 'pending') {
    const item = target.item
    return (
      <Drawer
        open
        onClose={onClose}
        width={520}
        icon={<BookOpen className="h-5 w-5" />}
        title={item.title.value}
        subtitle={`来源:${item.sourceProject.value}`}
        footer={<PendingFooter item={item} busy={busy} readOnly={readOnly} onAction={onPendingAction} />}
      >
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="remind" dot>待确认</Badge>
            <Badge tone="knowledge">{item.memoryType.value}</Badge>
            <DataSourceBadge source={item.title.source} />
          </div>
          <SectionBlock icon={<Quote className="h-4 w-4" />} label="候选结论">
            <p className="text-[14.5px] font-medium leading-relaxed text-slate-100">{item.summary.value}</p>
          </SectionBlock>
          <SectionBlock icon={<Info className="h-4 w-4" />} label="治理状态">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
              <MetaRow label="候选类型" value={item.itemType.value} source={item.itemType.source} />
              <MetaRow label="当前状态" value={item.status.value} source={item.status.source} />
              <MetaRow label="形成时间" value={formatTime(item.createdAt.value)} source={item.createdAt.source} />
              <MetaRow label="文档版本" value={item.documentVersion.value === null ? '不适用' : `v${item.documentVersion.value}`} source={item.documentVersion.source} />
            </dl>
            {item.taskId.value ? (
              <a
                className="mt-3 inline-block text-xs text-mint-300 hover:underline"
                href={`/tasks?task=${encodeURIComponent(item.taskId.value)}`}
              >
                打开来源任务
              </a>
            ) : null}
          </SectionBlock>
          <SectionBlock icon={<ShieldCheck className="h-4 w-4" />} label="服务端可用操作">
            <p className="text-sm text-slate-300">{item.allowedActions.value.length > 0 ? item.allowedActions.value.join('、') : '当前没有可执行操作'}</p>
          </SectionBlock>
        </div>
      </Drawer>
    )
  }

  const asset = target.asset
  const event = target.kind === 'event' ? target.event : null
  const title = asset?.title.value ?? event?.knowledgeTitle.value ?? '知识详情'
  const sourceProject = asset?.sourceProject.value ?? event?.project.value ?? ''
  return (
    <Drawer
      open
      onClose={onClose}
      width={520}
      icon={<BookOpen className="h-5 w-5" />}
      title={title}
      subtitle={sourceProject ? `来源:${sourceProject}` : undefined}
      footer={asset ? (
        <AssetFooter
          asset={asset}
          busy={busy}
          readOnly={readOnly}
          onRevise={onRevise}
          onTransition={onTransition}
        />
      ) : undefined}
    >
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1"><Badge tone={event ? 'mint' : statusTone(asset?.status.value ?? '')} dot>{event ? event.statusLabel.value : STATUS_LABELS[asset?.status.value ?? ''] ?? asset?.status.value ?? '已沉淀'}</Badge>{event ? <DataSourceBadge source={event.statusLabel.source} /> : null}</span>
          {asset ? <span className="inline-flex items-center gap-1"><Badge tone="knowledge">{TYPE_LABELS[asset.type.value] ?? asset.type.value}</Badge><DataSourceBadge source={asset.type.source} /></span> : null}
          {asset ? <span className="inline-flex items-center gap-1"><Badge tone={asset.visibility.value === 'private' ? 'neutral' : 'collab'}>{VISIBILITY_LABELS[asset.visibility.value] ?? asset.visibility.value}</Badge><DataSourceBadge source={asset.visibility.source} /></span> : null}
          <DataSourceBadge source={(asset?.title ?? event?.knowledgeTitle)?.source ?? 'T'} />
        </div>

        {event ? (
          <SectionBlock icon={<History className="h-4 w-4" />} label="本次动态">
            <p className="text-sm leading-relaxed text-slate-300">{event.description.value}</p>
            {event.detail.value ? <p className="mt-2 text-[12.5px] leading-relaxed text-slate-400">{event.detail.value}</p> : null}
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3">
              <MetaRow label="使用者" value={event.actor.value} source={event.actor.source} />
              <MetaRow label="项目" value={event.project.value} source={event.project.source} />
              <MetaRow label="用途" value={event.purpose.value || '未提供'} source={event.purpose.source} />
              <MetaRow label="时间" value={formatTime(event.time.value)} source={event.time.source} />
            </dl>
          </SectionBlock>
        ) : null}

        {asset ? (
          <>
            <SectionBlock icon={<Quote className="h-4 w-4" />} label="核心结论">
              <PresentedParagraph value={asset.conclusion.value} source={asset.conclusion.source} />
            </SectionBlock>
            {asset.problem.value ? (
              <SectionBlock icon={<FileText className="h-4 w-4" />} label="解决的问题">
                <PresentedParagraph value={asset.problem.value} source={asset.problem.source} />
              </SectionBlock>
            ) : null}
            {asset.evidence.value.length > 0 ? (
              <SectionBlock icon={<ClipboardList className="h-4 w-4" />} label="形成依据">
                <div className="mb-2"><DataSourceBadge source={asset.evidence.source} /></div>
                <ul className="space-y-2">
                  {asset.evidence.value.map((evidence) => (
                    <li key={evidence} className="flex gap-2 text-sm text-slate-300"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-500" />{evidence}</li>
                  ))}
                </ul>
              </SectionBlock>
            ) : null}
            <SectionBlock icon={<Target className="h-4 w-4" />} label="适用范围与限制条件">
              <PresentedParagraph value={asset.scope.value} source={asset.scope.source} />
              {asset.limitation.value ? <div className="mt-3"><PresentedParagraph value={asset.limitation.value} source={asset.limitation.source} /></div> : null}
            </SectionBlock>
            <SectionBlock icon={<Users className="h-4 w-4" />} label="来源与贡献者">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                <MetaRow label="原始项目" value={asset.sourceProject.value} source={asset.sourceProject.source} />
                <MetaRow label="原始贡献者" value={asset.contributor.value} source={asset.contributor.source} />
                <MetaRow label="验证状态" value={asset.verified.value} source={asset.verified.source} />
                <MetaRow label="最近更新" value={formatTime(asset.updated.value)} source={asset.updated.source} />
                {asset.version.value !== null ? <MetaRow label="记录版本" value={`v${asset.version.value}`} source={asset.version.source} /> : null}
                {asset.archivedFromStatus.value ? <MetaRow label="归档前状态" value={STATUS_LABELS[asset.archivedFromStatus.value] ?? asset.archivedFromStatus.value} source={asset.archivedFromStatus.source} /> : null}
                {asset.contentHash.value ? <MetaRow label="内容哈希" value={asset.contentHash.value.slice(0, 12)} source={asset.contentHash.source} /> : null}
                {asset.sourceRunId.value ? <MetaRow label="来源 Run" value={asset.sourceRunId.value} source={asset.sourceRunId.source} /> : null}
                {asset.sourceReviewId.value ? <MetaRow label="来源审核" value={asset.sourceReviewId.value} source={asset.sourceReviewId.source} /> : null}
              </dl>
              {asset.sourceTaskId.value ? (
                <a
                  className="mt-3 inline-block text-xs text-mint-300 hover:underline"
                  href={`/tasks?task=${encodeURIComponent(asset.sourceTaskId.value)}`}
                >
                  打开来源任务
                </a>
              ) : null}
            </SectionBlock>
            {asset.memoryKind.value ? (
              <SectionBlock icon={<History className="h-4 w-4" />} label="版本与治理历史">
                {lineageLoading ? <p className="text-sm text-slate-400">正在读取版本链…</p> : null}
                {lineageError ? <p role="alert" className="text-sm text-rose">{lineageError}</p> : null}
                {lineage ? (
                  <div className="space-y-4">
                    <RevisionLinks label="前一版" items={lineage.source_memories ?? []} />
                    <RevisionLinks label="后一版" items={lineage.superseded_by_memories ?? []} />
                    {(lineage.governance_events ?? []).length > 0 ? (
                      <ol className="space-y-2">
                        {(lineage.governance_events ?? []).map((governanceEvent) => (
                          <li key={governanceEvent.id} className="rounded-soft bg-surface-1 px-3 py-2 text-xs text-slate-300">
                            <span className="font-medium text-slate-100">{EVENT_LABELS[governanceEvent.action] ?? governanceEvent.action}</span>
                            <span className="mt-1 block text-slate-400">{formatTime(governanceEvent.created_at)} · {governanceEvent.actor}</span>
                          </li>
                        ))}
                      </ol>
                    ) : <p className="text-sm text-slate-400">暂无治理事件。</p>}
                  </div>
                ) : null}
              </SectionBlock>
            ) : null}
            {lineage && (lineage.usage ?? []).length > 0 ? (
              <SectionBlock icon={<Quote className="h-4 w-4" />} label="后续复用">
                <ol className="space-y-2">
                  {(lineage.usage ?? []).map((usage) => (
                    <li key={usage.receipt_id} className="rounded-soft bg-surface-1 px-3 py-2 text-xs text-slate-300">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-mono font-semibold text-mint-300">[{usage.citation_label}]</span>
                        <span className="text-slate-400">v{usage.memory_version} · {formatTime(usage.created_at)}</span>
                      </div>
                      <p className="mt-1 text-slate-400">{REUSE_REASON_LABELS[usage.retrieval_reason] ?? usage.retrieval_reason}</p>
                      <div className="mt-2 flex flex-wrap gap-3">
                        {usage.task_navigation_href ? <a className="text-mint-300 hover:underline" href={usage.task_navigation_href}>打开使用任务</a> : null}
                        {usage.run_navigation_href ? <a className="text-mint-300 hover:underline" href={usage.run_navigation_href}>打开使用 Run</a> : null}
                      </div>
                    </li>
                  ))}
                </ol>
              </SectionBlock>
            ) : null}
            <SectionBlock icon={<History className="h-4 w-4" />} label="共享和引用记录">
              <div className="mb-2"><DataSourceBadge source={asset.citations.source} /></div>
              {asset.citations.value.length === 0 ? (
                <p className="text-sm text-slate-400">尚无可展示的引用记录。</p>
              ) : (
                <ol className="space-y-2.5">
                  {asset.citations.value.map((citation, index) => (
                    <li key={`${citation.who}-${citation.project}-${index}`} className="rounded-soft bg-surface-1 p-3 text-sm text-slate-300">
                      <span className="font-medium text-slate-100">{citation.who}</span> · {citation.project}
                      {citation.purpose ? <p className="mt-1 text-xs text-slate-400">用途:{citation.purpose}</p> : null}
                    </li>
                  ))}
                </ol>
              )}
            </SectionBlock>
          </>
        ) : null}

        {event && !asset ? (
          <p className="rounded-soft bg-surface-1 px-3 py-2 text-xs leading-relaxed text-slate-400">当前仅有时间线展示数据，没有对应的真实知识资产详情。</p>
        ) : null}
      </div>
    </Drawer>
  )
}

function PendingFooter({ item, busy, readOnly, onAction }: { item: PendingKnowledgeView; busy: boolean; readOnly: boolean; onAction?: Props['onPendingAction'] }) {
  const actions = item.allowedActions.value
  if (!onAction || actions.length === 0) return <p className="text-xs text-slate-400">当前没有服务端可用操作。</p>
  return (
    <div className="flex flex-wrap justify-end gap-2">
      {actions.includes('confirm_brief') ? <Button size="sm" loading={busy} disabled={readOnly} onClick={() => onAction(item, 'confirm')}>确认 Brief</Button> : null}
      {actions.includes('accept') ? <Button size="sm" loading={busy} disabled={readOnly} onClick={() => onAction(item, 'accept')}>接受候选</Button> : null}
      {actions.includes('snooze') ? <Button size="sm" variant="subtle" disabled={busy || readOnly} onClick={() => onAction(item, 'snooze')}>稍后处理</Button> : null}
      {actions.includes('release') ? <Button size="sm" variant="secondary" disabled={busy || readOnly} onClick={() => onAction(item, 'release')}>释放内容</Button> : null}
      {actions.includes('discard') ? <Button size="sm" variant="danger" disabled={busy || readOnly} onClick={() => onAction(item, 'discard')}>丢弃内容</Button> : null}
      {actions.includes('resolve') ? <Button size="sm" variant="ghost" disabled={busy || readOnly} onClick={() => onAction(item, 'resolve')}>标记已解决</Button> : null}
    </div>
  )
}

function AssetFooter({ asset, busy, readOnly, onRevise, onTransition }: {
  asset: KnowledgeAssetView
  busy: boolean
  readOnly: boolean
  onRevise?: (asset: KnowledgeAssetView) => void
  onTransition?: (asset: KnowledgeAssetView, action: MemoryLifecycleAction) => void
}) {
  const actions = asset.allowedActions.value
  const lifecycleActions = actions.filter((action): action is MemoryLifecycleAction => (
    ['dispute', 'deprecate', 'expire', 'archive', 'restore'].includes(action)
  ))
  if (!actions.includes('revise') && lifecycleActions.length === 0) {
    return <p className="text-xs text-slate-400">当前没有服务端可用操作。</p>
  }
  return (
    <div className="flex flex-wrap justify-end gap-2">
      {actions.includes('revise') && onRevise ? (
        <Button size="sm" disabled={busy || readOnly} onClick={() => onRevise(asset)}>创建修订</Button>
      ) : null}
      {lifecycleActions.map((action) => (
        <Button
          key={action}
          size="sm"
          variant={['dispute', 'deprecate', 'expire'].includes(action) ? 'danger' : 'secondary'}
          disabled={busy || readOnly || !onTransition}
          onClick={() => onTransition?.(asset, action)}
        >
          {ACTION_LABELS[action]}
        </Button>
      ))}
    </div>
  )
}

type RevisionLink = NonNullable<MemoryLineage['source_memories']>[number]

function RevisionLinks({ label, items }: { label: string; items: RevisionLink[] }) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] uppercase tracking-wide text-slate-400">{label}</p>
      {items.length > 0 ? (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li key={item.id}>
              <a
                href={item.navigation_href}
                className="flex min-h-10 items-center justify-between gap-3 rounded-soft bg-surface-1 px-3 py-2 text-xs text-slate-300 transition-colors active:scale-[0.98] hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
              >
                <span className="min-w-0 truncate">{item.title}</span>
                <span className="shrink-0 tabular-nums text-slate-400">{STATUS_LABELS[item.status] ?? item.status} · v{item.version}</span>
              </a>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-slate-400">无</p>}
    </div>
  )
}

function PresentedParagraph({ value, source }: { value: string; source: 'M' | 'T' }) {
  return (
    <div className="flex items-start gap-2">
      <p className="min-w-0 flex-1 text-sm leading-relaxed text-slate-300">{value}</p>
      <DataSourceBadge source={source} />
    </div>
  )
}

function SectionBlock({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400"><span>{icon}</span>{label}</div>
      {children}
    </section>
  )
}

function MetaRow({ label, value, source }: { label: string; value: string; source: 'M' | 'T' }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 flex items-center gap-1.5 text-sm text-slate-200"><span>{value}</span><DataSourceBadge source={source} /></dd>
    </div>
  )
}

const REUSE_REASON_LABELS: Record<string, string> = {
  automatic_run_context: '任务执行自动上下文',
  tool_memory_search: '运行中显式记忆检索',
}

const STATUS_LABELS: Record<string, string> = {
  proposed: '待审核',
  accepted: '已接受',
  disputed: '存在争议',
  deprecated: '已废弃',
  expired: '已失效',
  archived: '已归档',
  active: '生效中',
}

const ACTION_LABELS: Record<MemoryLifecycleAction, string> = {
  dispute: '标记争议',
  deprecate: '废弃版本',
  expire: '标记失效',
  archive: '归档',
  restore: '恢复',
}

const EVENT_LABELS: Record<string, string> = {
  capture_memory_from_task_review: '从任务审核沉淀',
  create_memory_revision: '提交修订候选',
  decide_memory_review: '完成记忆审核',
  transition_memory_dispute: '标记争议',
  transition_memory_deprecate: '废弃版本',
  transition_memory_expire: '标记失效',
  transition_memory_archive: '归档版本',
  transition_memory_restore: '恢复版本',
}

const TYPE_LABELS: Record<string, string> = {
  design_rule: '设计规范',
  decision_method: '决策方法',
  project_experience: '项目经验',
  data_insight: '数据经验',
  workflow_method: '流程方法',
  risk_boundary: '风险与边界',
}

const VISIBILITY_LABELS: Record<string, string> = {
  private: '仅自己',
  project: '当前项目',
  team: '团队共享',
}


function statusTone(status: string): 'mint' | 'remind' | 'neutral' | 'rose' {
  if (status === 'accepted' || status === 'active') return 'mint'
  if (status === 'proposed') return 'remind'
  if (status === 'disputed') return 'rose'
  return 'neutral'
}

function formatTime(value: string) {
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString('zh-CN')
}
