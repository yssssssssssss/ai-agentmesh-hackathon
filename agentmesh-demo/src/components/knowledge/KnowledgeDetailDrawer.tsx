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
}

export function KnowledgeDetailDrawer({ open, onClose, target, busy = false, readOnly = false, onPendingAction }: Props) {
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
    <Drawer open onClose={onClose} width={520} icon={<BookOpen className="h-5 w-5" />} title={title} subtitle={sourceProject ? `来源:${sourceProject}` : undefined}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1"><Badge tone="mint" dot>{event ? event.statusLabel.value : '已沉淀'}</Badge>{event ? <DataSourceBadge source={event.statusLabel.source} /> : null}</span>
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
                {asset.version.value !== null ? <MetaRow label="文档版本" value={`v${asset.version.value}`} source={asset.version.source} /> : null}
              </dl>
            </SectionBlock>
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


function formatTime(value: string) {
  const timestamp = Date.parse(value)
  return Number.isNaN(timestamp) ? value : new Date(timestamp).toLocaleString('zh-CN')
}
