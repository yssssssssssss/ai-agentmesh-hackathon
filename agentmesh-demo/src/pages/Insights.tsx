import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  BarChart3,
  Blocks,
  BookMarked,
  CheckCircle2,
  FileText,
  LockKeyhole,
  PlayCircle,
  Sparkles,
} from 'lucide-react'

import { ProjectReviewDrawer } from '../components/insights/ProjectReviewDrawer'
import {
  ActivityPanel,
  AuditPanel,
  MemoryPanel,
  TaskCardsPanel,
} from '../components/insights/ReadModelPanels'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { DataSourceBadge } from '../components/ui/DataSourceBadge'
import { PageHeader } from '../components/ui/PageHeader'
import { ApiError } from '../api/client'
import { useAuth } from '../features/auth/AuthProvider'
import { useInsightsReadModel } from '../features/insights/api'
import {
  buildInsightsViewModel,
  gateInsightsAggregates,
  type InsightsResource,
  type InsightsViewModel,
  type MockInsightAction,
} from '../features/insights/presenter'
import type { PresentedModule, PresentedValue } from '../lib/presentation'
import { cn } from '../lib/cn'

interface QuerySnapshot<T> {
  data?: T
  isLoading: boolean
  isError: boolean
  error: unknown
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  if (error instanceof Error) return error.message
  return '请求失败，请稍后重试'
}

function queryResource<T>(query: QuerySnapshot<T>): InsightsResource<T> {
  if (query.isLoading) return { state: 'loading' }
  if (query.isError) {
    return {
      state: query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error',
      error: errorMessage(query.error),
    }
  }
  if (query.data === undefined) return { state: 'empty' }
  return { state: 'available', data: query.data }
}

function actionById(model: InsightsViewModel, id: MockInsightAction['id']) {
  return model.mockActions.find((action) => action.value.id === id)
}

function InsightsContent({ userId, workspaceId, projectId }: {
  userId: string
  workspaceId: string
  projectId: string
}) {
  const navigate = useNavigate()
  const { bootstrap } = useAuth()
  const readModel = useInsightsReadModel({ userId, workspaceId, projectId })
  const [reviewDrawerOpen, setReviewDrawerOpen] = useState(false)
  if (!bootstrap) return null

  const tasks = queryResource(readModel.tasks)
  const activity = queryResource(readModel.activity)
  const memory = queryResource(readModel.memory)
  const audit = queryResource(readModel.audit)
  const aggregates = gateInsightsAggregates([tasks, activity, memory, audit])
  const model = buildInsightsViewModel({
    project: bootstrap.project,
    tasks,
    activity,
    memory,
    audit,
    aggregates,
  })

  return (
    <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-7">
      <PageHeader
        title="工作洞察"
        subtitle="基于当前项目的任务、活动、记忆与审计记录回看工作，串联复盘机会与知识形成路径。"
      />

      <WorkOverviewSection model={model} onContinue={() => navigate('/workspace')} />
      <InsightSection model={model} />
      <ReviewSection model={model} onOpenDetails={() => setReviewDrawerOpen(true)} />
      <EvidenceSection model={model} />
      <KnowledgeFormationSection model={model} />

      <details className="card-base group p-5">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">
          <div>
            <h2 className="text-[14px] font-semibold text-slate-200">当前项目原始读模型</h2>
            <p className="mt-1 text-[12px] text-slate-400">次级诊断信息，展示服务端任务、活动、记忆和审计原始字段。</p>
          </div>
          <Badge tone="neutral">展开详情</Badge>
        </summary>
        <div className="mt-5 grid gap-5 border-t border-white/[0.06] pt-5 xl:grid-cols-2">
          <TaskCardsPanel data={tasks.data} loading={tasks.state === 'loading'} error={tasks.error} />
          <ActivityPanel data={activity.data} loading={activity.state === 'loading'} error={activity.error} />
          <MemoryPanel data={memory.data} loading={memory.state === 'loading'} error={memory.error} />
          <AuditPanel data={audit.data} loading={audit.state === 'loading'} error={audit.error} />
        </div>
      </details>

      <div className="flex items-start gap-2 text-[12px] leading-5 text-slate-400">
        <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <p>服务端数据与参考线索都会保留来源标记，复盘写入和知识候选生成需由后端能力确认。</p>
      </div>

      <ProjectReviewDrawer
        open={reviewDrawerOpen}
        onClose={() => setReviewDrawerOpen(false)}
        opportunity={model.review.data.opportunity}
        evidence={model.evidence.data.items}
        flow={model.knowledgeFormation.data.flow}
      />
    </div>
  )
}

function WorkOverviewSection({ model, onContinue }: { model: InsightsViewModel; onContinue: () => void }) {
  const { project, tasks, activity, overview } = model.workOverview.data
  const activityCount = activity ? activity.value.personal.length + activity.value.external.length : null

  return (
    <section aria-labelledby="insights-work-overview">
      <ModuleHeading
        id="insights-work-overview"
        title="近期工作概览"
        desc="先呈现当前项目真实状态，再补充有明确来源标记的参考叙事"
        icon={<BarChart3 className="h-5 w-5" />}
        tone="mint"
      />
      <div className="card-base p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <DataSourceBadge source={project.source} />
              <Badge tone="neutral">{project.value.status}</Badge>
            </div>
            <h3 className="mt-3 text-[18px] font-semibold text-slate-100">{project.value.name}</h3>
            <p className="mt-1.5 max-w-3xl text-[13px] leading-6 text-slate-400">{project.value.goal}</p>
          </div>
          <Button variant="secondary" icon={<PlayCircle className="h-4 w-4" />} onClick={onContinue}>
            继续当前项目
          </Button>
        </div>

        {(tasks || activity) ? (
          <dl className="mt-5 grid gap-3 border-t border-white/[0.06] pt-4 sm:grid-cols-2">
            {tasks ? (
              <div className="rounded-soft bg-surface-2 px-4 py-3">
                <dt className="flex items-center justify-between gap-2 text-[11px] text-slate-400">
                  当前任务 <DataSourceBadge source={tasks.source} />
                </dt>
                <dd className="mt-2 text-right text-[20px] font-semibold tabular-nums text-slate-100">{tasks.value.items.length}</dd>
              </div>
            ) : null}
            {activity ? (
              <div className="rounded-soft bg-surface-2 px-4 py-3">
                <dt className="flex items-center justify-between gap-2 text-[11px] text-slate-400">
                  今日活动 <DataSourceBadge source={activity.source} />
                </dt>
                <dd className="mt-2 text-right text-[20px] font-semibold tabular-nums text-slate-100">{activityCount}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}

        {overview ? (
          <ReferencePanel className="mt-5" value={overview} label="参考工作概览">
            <p className="text-[13px] leading-6 text-slate-300">{overview.value.lastWeek.summary}</p>
            <p className="mt-2 text-[11px] leading-5 text-slate-400">{overview.value.lastWeek.meta}</p>
          </ReferencePanel>
        ) : null}
        <ModuleStatus module={model.workOverview} emptyLabel="当前没有可展示的工作概览。" />
      </div>
    </section>
  )
}

function InsightSection({ model }: { model: InsightsViewModel }) {
  const { memory, audit, currentProject, crossProject } = model.insight.data
  const memoryTotal = memory
    ? Object.values(memory.value.counts).reduce((sum, count) => sum + count, 0)
    : null

  return (
    <section aria-labelledby="insights-feedback">
      <ModuleHeading
        id="insights-feedback"
        title="洞察反馈"
        desc="真实信号与尚未接入的聚合判断分层展示"
        icon={<Sparkles className="h-5 w-5" />}
        tone="remind"
        hero
      />
      <div className="card-base p-5 sm:p-6">
        {(memory || audit) ? (
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[14px] font-semibold text-slate-100">当前项目可确认信号</h3>
              <DataSourceBadge source="T" />
            </div>
            <dl className="mt-4 grid gap-3 sm:grid-cols-2">
              {memory ? (
                <div className="rounded-soft bg-surface-2 px-4 py-3">
                  <dt className="text-[11px] text-slate-400">服务端记忆总数</dt>
                  <dd className="mt-2 text-right text-[20px] font-semibold tabular-nums text-slate-100">{memoryTotal}</dd>
                </div>
              ) : null}
              {audit ? (
                <div className="rounded-soft bg-surface-2 px-4 py-3">
                  <dt className="text-[11px] text-slate-400">可见审计事件</dt>
                  <dd className="mt-2 text-right text-[20px] font-semibold tabular-nums text-slate-100">{audit.value.total}</dd>
                </div>
              ) : null}
            </dl>
            <p className="mt-3 text-[11px] leading-5 text-slate-400">数量是 T 数据事实，不自动推导为项目成效或复盘证据。</p>
          </div>
        ) : null}

        {currentProject ? (
          <ReferencePanel className="mt-5" value={currentProject} label="当前项目洞察参考">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[16px] font-semibold text-slate-100">{currentProject.value.name}</h3>
              <Badge tone="neutral">{currentProject.value.stage}</Badge>
            </div>
            <ul className="mt-4 grid gap-2 sm:grid-cols-2">
              {currentProject.value.progress.map((item) => (
                <li key={item} className="flex items-start gap-2 text-[12px] leading-5 text-slate-400">
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mint-300" />{item}
                </li>
              ))}
            </ul>
            <div className="mt-4 rounded-soft bg-remind/[0.06] px-4 py-3">
              <p className="text-[13px] font-medium text-slate-200">{currentProject.value.problem.title}</p>
              <p className="mt-1 text-[12px] leading-5 text-slate-400">{currentProject.value.problem.desc}</p>
            </div>
            <p className="mt-3 text-[11px] leading-5 text-slate-400">{currentProject.value.pendingValidation}</p>
          </ReferencePanel>
        ) : null}

        {crossProject ? (
          <ReferencePanel className="mt-5" value={crossProject} label="跨项目洞察参考">
            <h3 className="text-[16px] font-semibold text-slate-100">{crossProject.value.title}</h3>
            <p className="mt-2 text-[13px] leading-6 text-slate-400">{crossProject.value.desc}</p>
            <ol className="mt-4 space-y-2">
              {crossProject.value.basis.map((item, index) => (
                <li key={item} className="flex gap-3 text-[12px] leading-5 text-slate-400">
                  <span className="font-medium tabular-nums text-slate-400">0{index + 1}</span>{item}
                </li>
              ))}
            </ol>
            <p className="mt-4 border-t border-white/[0.06] pt-4 text-[12px] leading-5 text-slate-300">{crossProject.value.improve}</p>
          </ReferencePanel>
        ) : null}
        <ModuleStatus module={model.insight} emptyLabel="当前没有可展示的洞察信息。" />
      </div>
    </section>
  )
}

function ReviewSection({ model, onOpenDetails }: { model: InsightsViewModel; onOpenDetails: () => void }) {
  const { opportunity, kpis } = model.review.data
  const startReview = actionById(model, 'start-review')

  return (
    <section aria-labelledby="insights-review">
      <ModuleHeading
        id="insights-review"
        title="值得复盘的历史项目"
        desc="参考项目保留原有叙事，但不伪装成当前账号的真实历史项目"
        icon={<BookMarked className="h-5 w-5" />}
        tone="knowledge"
      />
      <div className="card-base p-5 sm:p-6">
        {opportunity ? (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <DataSourceBadge source={opportunity.source} />
                  <Badge tone="remind">{opportunity.value.status}</Badge>
                </div>
                <h3 className="mt-3 text-[18px] font-semibold text-slate-100">{opportunity.value.name}</h3>
                <p className="mt-2 max-w-4xl text-[13px] leading-6 text-slate-400">{opportunity.value.judgment}</p>
              </div>
            </div>

            {kpis ? (
              <div className="mt-5 border-t border-white/[0.06] pt-5">
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">参考项目材料与指标</h4>
                  <DataSourceBadge source={kpis.source} />
                </div>
                <dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
                  {kpis.value.map((item) => (
                    <div key={item.label}>
                      <dt className="text-[11px] text-slate-400">{item.label}</dt>
                      <dd className="mt-1 text-right text-[17px] font-semibold tabular-nums text-slate-100">{item.value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : null}

            <div className="mt-5 flex flex-wrap items-start gap-3 border-t border-white/[0.06] pt-5">
              <UnavailableAction action={startReview} icon={<LockKeyhole className="h-4 w-4" />} />
              <Button variant="subtle" onClick={onOpenDetails}>查看只读复盘结构</Button>
            </div>
          </>
        ) : null}
        <ModuleStatus module={model.review} emptyLabel="当前没有可安全展示的复盘机会。" />
      </div>
    </section>
  )
}

function EvidenceSection({ model }: { model: InsightsViewModel }) {
  const items = model.evidence.data.items
  return (
    <section aria-labelledby="insights-evidence">
      <ModuleHeading
        id="insights-evidence"
        title="复盘证据"
        desc="复盘材料与审计记录严格区分，缺失项不会被自动补成真实结果"
        icon={<FileText className="h-5 w-5" />}
        tone="knowledge"
      />
      <div className="card-base p-5 sm:p-6">
        {items ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <DataSourceBadge source={items.source} />
              <Badge tone="remind">参考材料清单</Badge>
            </div>
            <ul className="mt-4 grid gap-3 sm:grid-cols-2">
              {items.value.map((item) => (
                <li key={item.label} className="flex items-start gap-3 rounded-soft bg-surface-2 px-4 py-3">
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
            <p className="mt-4 text-[11px] leading-5 text-remind">{items.reason}</p>
          </>
        ) : null}
        <ModuleStatus module={model.evidence} emptyLabel="当前没有可安全展示的复盘证据。" />
      </div>
    </section>
  )
}

function KnowledgeFormationSection({ model }: { model: InsightsViewModel }) {
  const { flow, workflowRecommendation } = model.knowledgeFormation.data
  const formCandidate = actionById(model, 'form-knowledge-candidate')
  const applyWorkflow = actionById(model, 'apply-workflow-recommendation')

  return (
    <section aria-labelledby="insights-knowledge-formation">
      <ModuleHeading
        id="insights-knowledge-formation"
        title="知识形成"
        desc="结果补充、复盘确认与候选形成均需真实后端能力"
        icon={<Blocks className="h-5 w-5" />}
        tone="mint"
      />
      <div className="card-base p-5 sm:p-6">
        {flow ? (
          <ReferencePanel value={flow} label="知识形成流程参考">
            <div className="grid gap-4 lg:grid-cols-[1fr_auto_1fr] lg:items-center">
              <div>
                <p className="text-[11px] font-medium text-slate-400">材料条件</p>
                <p className="mt-1 text-[13px] leading-6 text-slate-300">{flow.value.missingHint}</p>
              </div>
              <span aria-hidden="true" className="hidden text-slate-400 lg:block">→</span>
              <div>
                <p className="text-[11px] font-medium text-slate-400">参考候选方向</p>
                <p className="mt-1 text-[13px] font-medium leading-6 text-slate-200">{flow.value.candidateTitle}</p>
              </div>
            </div>
          </ReferencePanel>
        ) : null}

        {workflowRecommendation ? (
          <ReferencePanel className="mt-5" value={workflowRecommendation} label="Workflow 建议参考">
            <h3 className="text-[15px] font-semibold text-slate-100">{workflowRecommendation.value.name}</h3>
            <p className="mt-2 text-[13px] leading-6 text-slate-400">{workflowRecommendation.value.desc}</p>
          </ReferencePanel>
        ) : null}

        {(formCandidate || applyWorkflow) ? (
          <div className="mt-5 flex flex-wrap items-start gap-3 border-t border-white/[0.06] pt-5">
            <UnavailableAction action={formCandidate} icon={<BookMarked className="h-4 w-4" />} />
            <UnavailableAction action={applyWorkflow} icon={<Blocks className="h-4 w-4" />} />
          </div>
        ) : null}
        <ModuleStatus module={model.knowledgeFormation} emptyLabel="当前没有可安全展示的知识形成信息。" />
      </div>
    </section>
  )
}

function ModuleHeading({ id, title, desc, icon, tone, hero }: {
  id: string
  title: string
  desc: string
  icon: ReactNode
  tone: 'mint' | 'remind' | 'knowledge'
  hero?: boolean
}) {
  const toneClass = tone === 'remind'
    ? 'bg-remind/[0.14] text-remind'
    : tone === 'knowledge'
      ? 'bg-knowledge/[0.14] text-knowledge'
      : 'bg-mint-400/[0.14] text-mint-300'
  return (
    <div className="mb-3 flex items-center gap-3">
      <span className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-soft', toneClass)}>{icon}</span>
      <div className="min-w-0">
        <h2 id={id} className={cn('font-semibold text-slate-100', hero ? 'text-[17px]' : 'text-[15px]')}>{title}</h2>
        <p className="mt-0.5 text-[12px] leading-5 text-slate-400">{desc}</p>
      </div>
    </div>
  )
}

function ReferencePanel<T>({ value, label, className, children }: {
  value: PresentedValue<T>
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <section className={cn('rounded-soft border border-remind/20 bg-remind/[0.035] p-4', className)}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <DataSourceBadge source={value.source} />
        <span className="text-[11px] font-medium text-remind">{label}</span>
      </div>
      {children}
      {value.reason ? <p className="mt-3 text-[11px] leading-5 text-remind/90">{value.reason}</p> : null}
    </section>
  )
}

function ModuleStatus<T>({ module, emptyLabel }: {
  module: PresentedModule<T>
  emptyLabel: string
}) {
  if (module.error) {
    return <p role="alert" className="mt-4 rounded-soft bg-rose/10 px-4 py-3 text-[12px] text-rose">{module.error}</p>
  }
  if (module.loading) {
    return <p role="status" className="mt-4 text-[12px] text-slate-400">正在读取当前项目数据…</p>
  }
  if (module.sources.length === 0) return <p className="mt-4 text-[12px] text-slate-400">{emptyLabel}</p>
  return null
}

function UnavailableAction({ action, icon }: {
  action?: PresentedValue<MockInsightAction>
  icon: ReactNode
}) {
  if (!action) return null
  return (
    <div className="max-w-xs">
      <Button disabled variant="subtle" icon={icon}>{action.value.label}（暂不可用）</Button>
      <p className="mt-1.5 text-[11px] leading-5 text-slate-400">{action.value.unavailableReason}</p>
    </div>
  )
}

export function Insights() {
  const { user, bootstrap } = useAuth()
  if (!user?.id || !bootstrap?.workspace.id || !bootstrap.project.id) return null
  return (
    <InsightsContent
      userId={user.id}
      workspaceId={bootstrap.workspace.id}
      projectId={bootstrap.project.id}
    />
  )
}
