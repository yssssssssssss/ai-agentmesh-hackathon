import type { ReactNode } from 'react'
import { BarChart3, FileText, History, Lightbulb, Sparkles, TrendingDown, TrendingUp, X } from 'lucide-react'

import {
  BRIEF,
  CORE_EXPERIENCE_REF,
  WORKSPACE_REFERENCES,
  type WorkspaceRef,
} from '../../data/mockData'
import { cn } from '../../lib/cn'
import { DataSourceBadge } from '../ui/DataSourceBadge'

export type DemoDetailSelection =
  | { kind: 'ref'; ref: WorkspaceRef }
  | { kind: 'sources' }
  | { kind: 'brief' }

export function DemoConversationDetailPanel({
  selection,
  onClose,
}: {
  selection: DemoDetailSelection | null
  onClose: () => void
}) {
  if (!selection) return null

  const title = selection.kind === 'ref'
    ? selection.ref.title
    : selection.kind === 'brief'
      ? BRIEF.title
      : '本次演示资料'
  const subtitle = selection.kind === 'ref'
    ? selection.ref.chip
    : selection.kind === 'brief'
      ? '数字员工生成 · 项目启动 Brief'
      : '历史项目、团队经验与业务数据'

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-label="演示资料详情"
      className="absolute inset-y-0 right-0 z-20 flex w-full max-w-[440px] flex-col border-l border-white/[0.08] bg-base shadow-panel"
    >
      <header className="flex items-start gap-3 border-b border-white/[0.06] px-5 py-4">
        <span className="rounded-soft bg-white/[0.05] p-2 text-mint-300">
          {selection.kind === 'brief' ? <FileText className="h-4 w-4" /> : <History className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <DataSourceBadge source="M" />
            <span className="text-[11px] text-slate-400">{subtitle}</span>
          </div>
          <h2 className="mt-1 text-sm font-semibold text-slate-100">{title}</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="关闭演示资料详情" className="rounded-lg p-2 text-slate-400 hover:bg-white/[0.06] hover:text-slate-200">
          <X className="h-4 w-4" />
        </button>
      </header>
      <div className="flex-1 overflow-y-auto px-5 py-5">
        {selection.kind === 'ref' ? <ReferenceBody reference={selection.ref} /> : null}
        {selection.kind === 'sources' ? <SourcesBody /> : null}
        {selection.kind === 'brief' ? <BriefBody /> : null}
      </div>
    </aside>
  )
}

function ReferenceBody({ reference }: { reference: WorkspaceRef }) {
  if (reference.kind === 'project') {
    return (
      <div className="space-y-5">
        <Field label="项目背景">{reference.detail.background}</Field>
        <Field label="核心问题">{reference.detail.problem}</Field>
        <Field label="设计方案">{reference.detail.solution}</Field>
        <Field label="结果数据"><span className="text-slate-200">{reference.detail.result}</span></Field>
        <Highlight label="与当前任务的关联">{reference.detail.relation}</Highlight>
      </div>
    )
  }

  if (reference.kind === 'data') {
    return (
      <div className="space-y-5">
        <Field label="数据范围">{reference.detail.range}</Field>
        <div>
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-slate-400">核心指标</div>
          <div className="space-y-2">
            {reference.detail.metrics.map((metric) => (
              <div key={metric.label} className="flex items-center justify-between rounded-soft border border-white/[0.06] bg-surface-1 px-3 py-2.5">
                <div className="min-w-0">
                  <div className="text-[13px] text-slate-200">{metric.label}</div>
                  <div className="text-[11px] text-slate-400">{metric.value}</div>
                </div>
                {metric.delta ? (
                  <span className={cn(
                    'flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-[12px] font-semibold',
                    metric.delta.startsWith('-') ? 'bg-rose/10 text-rose' : 'bg-mint-400/10 text-mint-300',
                  )}>
                    {metric.delta.startsWith('-') ? <TrendingDown className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}
                    {metric.delta}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
        <Highlight label="关键结论">{reference.detail.conclusion}</Highlight>
        <Field label="数据时间">{reference.detail.time}</Field>
        <Field label="口径说明">{reference.detail.caliber}</Field>
      </div>
    )
  }

  if (reference.kind === 'experience') {
    return (
      <div className="space-y-5">
        <Highlight label="经验结论">{reference.detail.conclusion}</Highlight>
        <Field label="来源项目">
          <div className="flex flex-wrap gap-1.5">
            {reference.detail.sourceProjects.map((project) => <span key={project} className="rounded-full bg-white/[0.05] px-2.5 py-1 text-[12px] text-slate-300">{project}</span>)}
          </div>
        </Field>
        <Field label="适用范围">{reference.detail.scope}</Field>
        <Field label="最近验证时间">{reference.detail.lastVerified}</Field>
        <Field label="引用项目">
          <ul className="space-y-1.5">{reference.detail.citedBy.map((item) => <li key={item}>· {item}</li>)}</ul>
        </Field>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <Field label="角色和擅长领域">{reference.detail.field}</Field>
      <Field label="引用经验">{reference.detail.citedExperience}</Field>
      <Highlight label="具体贡献">{reference.detail.contribution}</Highlight>
      <Field label="知识来源">{reference.detail.knowledgeSource}</Field>
    </div>
  )
}

function SourcesBody() {
  const projects = WORKSPACE_REFERENCES.filter((reference) => reference.kind === 'project')
  const dataSources = WORKSPACE_REFERENCES.filter((reference) => reference.kind === 'data')
  return (
    <div className="space-y-6">
      <SourceSection icon={<History className="h-4 w-4 text-knowledge" />} title="相似历史项目">
        {projects.map((reference) => (
          <article key={reference.id} className="rounded-soft border border-white/[0.06] bg-surface-1 p-3">
            <h3 className="text-[13px] font-medium text-slate-200">{reference.title}</h3>
            <p className="mt-1 text-[11px] text-slate-400">{reference.chip}</p>
            <p className="mt-2 text-[12px] leading-relaxed text-slate-400">{reference.detail.relation}</p>
          </article>
        ))}
      </SourceSection>
      <SourceSection icon={<Lightbulb className="h-4 w-4 text-mint-300" />} title="已确认团队经验">
        <article className="rounded-soft border border-mint-400/15 bg-mint-400/[0.04] p-3">
          <h3 className="text-[13px] font-medium text-slate-200">{CORE_EXPERIENCE_REF.title}</h3>
          <p className="mt-2 text-[12px] leading-relaxed text-slate-400">{CORE_EXPERIENCE_REF.detail.conclusion}</p>
        </article>
      </SourceSection>
      <SourceSection icon={<BarChart3 className="h-4 w-4 text-remind" />} title="业务数据依据">
        {dataSources.map((reference) => (
          <article key={reference.id} className="rounded-soft border border-remind/15 bg-remind/[0.04] p-3">
            <h3 className="text-[13px] font-medium text-slate-200">{reference.title}</h3>
            <p className="mt-2 text-[12px] leading-relaxed text-slate-400">{reference.detail.range}</p>
            <p className="mt-2 text-[11px] text-slate-400">{reference.chip}</p>
          </article>
        ))}
      </SourceSection>
    </div>
  )
}

function BriefBody() {
  return (
    <div className="space-y-5">
      <Field label="项目目标">{BRIEF.goal}</Field>
      <ListField label="历史背景" items={BRIEF.history} />
      <Field label="核心问题">{BRIEF.problem}</Field>
      <ListField label="设计原则" items={BRIEF.principles} ordered />
      <ListField label="设计方向" items={BRIEF.direction} />
      <ListField label="数据支撑" items={BRIEF.data} />
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div><div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</div><div className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-300">{children}</div></div>
}

function Highlight({ label, children }: { label: string; children: ReactNode }) {
  return <div className="rounded-soft border border-mint-400/20 bg-mint-400/[0.06] px-4 py-3"><div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-mint-300"><Sparkles className="h-3 w-3" />{label}</div><div className="text-[13px] leading-relaxed text-slate-300">{children}</div></div>
}

function SourceSection({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <section><div className="mb-2 flex items-center gap-2"><span>{icon}</span><h3 className="text-[12px] font-semibold text-slate-200">{title}</h3></div><div className="space-y-2">{children}</div></section>
}

function ListField({ label, items, ordered = false }: { label: string; items: string[]; ordered?: boolean }) {
  const List = ordered ? 'ol' : 'ul'
  return <Field label={label}><List className="space-y-1.5">{items.map((item, index) => <li key={item} className="flex gap-2"><span className={ordered ? 'text-mint-300' : 'text-slate-400'}>{ordered ? `${index + 1}.` : '·'}</span><span>{item}</span></li>)}</List></Field>
}
