import type { components } from '../../api/generated/schema'
import {
  CURRENT_PROJECT_INSIGHT,
  INSIGHT_OVERVIEW,
  RECURRING_PROBLEM,
  REVIEW_FLOW,
  REVIEW_PROJECT,
} from '../../data/mockData'
import {
  canUseMockFallback,
  presentedModule,
  presentedValue,
  type PresentationState,
  type PresentedModule,
  type PresentedValue,
} from '../../lib/presentation'
import type {
  ActivityTodayResponse,
  AuditListResponse,
  BlackboardTaskCardsResponse,
  MemoryOverviewResponse,
} from './api'

type Project = components['schemas']['Project']

export interface InsightsResource<T> {
  state: PresentationState
  data?: T
  error?: string
}

export interface InsightsAggregateResource {
  state: PresentationState
  error?: string
}
export interface InsightsAggregateSet {
  crossProjectInsight: InsightsAggregateResource
  kpis: InsightsAggregateResource
  review: InsightsAggregateResource
  workflowRecommendation: InsightsAggregateResource
}


export interface InsightsPresenterInput {
  project: Project
  tasks: InsightsResource<BlackboardTaskCardsResponse>
  activity: InsightsResource<ActivityTodayResponse>
  memory: InsightsResource<MemoryOverviewResponse>
  audit: InsightsResource<AuditListResponse>
  aggregates: InsightsAggregateSet
}

export interface MockInsightAction {
  id: 'start-review' | 'apply-workflow-recommendation' | 'form-knowledge-candidate'
  label: string
  available: false
  unavailableReason: string
}

type WorkOverviewData = {
  project: PresentedValue<Project>
  tasks?: PresentedValue<BlackboardTaskCardsResponse>
  activity?: PresentedValue<ActivityTodayResponse>
  overview?: PresentedValue<typeof INSIGHT_OVERVIEW>
}

type InsightData = {
  memory?: PresentedValue<MemoryOverviewResponse>
  audit?: PresentedValue<AuditListResponse>
  currentProject?: PresentedValue<typeof CURRENT_PROJECT_INSIGHT>
  crossProject?: PresentedValue<typeof RECURRING_PROBLEM>
}

type ReviewData = {
  opportunity?: PresentedValue<typeof REVIEW_PROJECT>
  kpis?: PresentedValue<typeof REVIEW_PROJECT.materials>
}

type EvidenceData = {
  items?: PresentedValue<typeof REVIEW_FLOW.evidence>
}

type KnowledgeFormationData = {
  flow?: PresentedValue<{
    missingHint: string
    resultPlaceholder: string
    candidateReadyHint: string
    candidateTitle: string
  }>
  workflowRecommendation?: PresentedValue<typeof CURRENT_PROJECT_INSIGHT.skill>
}

export interface InsightsViewModel {
  workOverview: PresentedModule<WorkOverviewData>
  insight: PresentedModule<InsightData>
  review: PresentedModule<ReviewData>
  evidence: PresentedModule<EvidenceData>
  knowledgeFormation: PresentedModule<KnowledgeFormationData>
  mockActions: PresentedValue<MockInsightAction>[]
}

const REASONS = {
  overview: '阶段性概览聚合能力尚未接入，当前叙事来自页面参考结构。',
  currentProject: '当前项目洞察聚合能力尚未接入，当前卡片用于展示洞察结构。',
  crossProject: '跨项目洞察聚合能力尚未接入，当前卡片用于展示复用路径。',
  review: '历史项目复盘机会聚合能力尚未接入，当前卡片用于展示复盘入口。',
  kpis: '复盘 KPI 聚合能力尚未接入，当前指标用于展示材料结构。',
  evidence: '复盘证据聚合能力尚未接入，当前清单用于展示证据结构。',
  flow: '知识形成流程能力尚未接入，当前流程用于展示候选生成路径。',
  workflow: 'Workflow 推荐聚合能力尚未接入，当前建议用于展示应用入口。',
} as const
export function gateInsightsAggregates(
  dependencies: readonly InsightsAggregateResource[],
  requested: InsightsAggregateSet = {
    crossProjectInsight: { state: 'unsupported' },
    kpis: { state: 'unsupported' },
    review: { state: 'unsupported' },
    workflowRecommendation: { state: 'unsupported' },
  },
): InsightsAggregateSet {
  const blocker = dependencies.find((resource) => resource.state === 'forbidden')
    ?? dependencies.find((resource) => resource.state === 'error')
    ?? dependencies.find((resource) => resource.state === 'loading')
    ?? dependencies.find((resource) => resource.state !== 'available')

  if (!blocker) return requested

  const blockedState: InsightsAggregateResource = blocker.state === 'forbidden'
    || blocker.state === 'error'
    || blocker.state === 'loading'
    ? { state: blocker.state, error: blocker.error }
    : { state: 'available' }

  return {
    crossProjectInsight: { ...blockedState },
    kpis: { ...blockedState },
    review: { ...blockedState },
    workflowRecommendation: { ...blockedState },
  }
}


function realValue<T>(resource: InsightsResource<T>): PresentedValue<T> | undefined {
  if (resource.state !== 'available' || resource.data === undefined) return undefined
  return presentedValue(resource.data, 'T')
}

function mockValue<T>(
  resource: InsightsAggregateResource,
  value: T,
  reason: string,
): PresentedValue<T> | undefined {
  if (!canUseMockFallback(resource.state)) return undefined
  return presentedValue(value, 'M', reason)
}

function compact(values: Array<PresentedValue<unknown> | undefined>): PresentedValue<unknown>[] {
  return values.filter((value): value is PresentedValue<unknown> => value !== undefined)
}

function resourceError(resources: readonly InsightsAggregateResource[]): string | null {
  for (const resource of resources) {
    if (resource.state !== 'forbidden' && resource.state !== 'error') continue
    if (resource.error) return resource.error
    return resource.state === 'forbidden' ? '当前账号无权访问该数据' : '数据加载失败，请稍后重试'
  }
  return null
}

function resourceLoading(resources: readonly InsightsAggregateResource[]): boolean {
  return resources.some((resource) => resource.state === 'loading')
}

function missingFields(data: Record<string, unknown>): string[] {
  return Object.entries(data)
    .filter(([, value]) => value === undefined)
    .map(([field]) => field)
}

function unavailableAction(
  id: MockInsightAction['id'],
  label: string,
  unavailableReason: string,
): PresentedValue<MockInsightAction> {
  return presentedValue(
    { id, label, available: false, unavailableReason },
    'M',
    unavailableReason,
  )
}

export function buildInsightsViewModel(input: InsightsPresenterInput): InsightsViewModel {
  const aggregates = gateInsightsAggregates(
    [input.tasks, input.activity, input.memory, input.audit],
    input.aggregates,
  )
  const project = presentedValue(input.project, 'T')
  const tasks = realValue(input.tasks)
  const activity = realValue(input.activity)
  const overview = mockValue(
    aggregates.crossProjectInsight,
    INSIGHT_OVERVIEW,
    REASONS.overview,
  )
  const workOverviewData: WorkOverviewData = { project, tasks, activity, overview }
  const workOverviewResources = [input.tasks, input.activity, aggregates.crossProjectInsight]
  const workOverview = presentedModule(
    workOverviewData,
    compact([project, tasks, activity, overview]),
    {
      missingFields: missingFields(workOverviewData),
      loading: resourceLoading(workOverviewResources),
      error: resourceError(workOverviewResources),
    },
  )

  const memory = realValue(input.memory)
  const audit = realValue(input.audit)
  const currentProject = mockValue(
    aggregates.crossProjectInsight,
    CURRENT_PROJECT_INSIGHT,
    REASONS.currentProject,
  )
  const crossProject = mockValue(
    aggregates.crossProjectInsight,
    RECURRING_PROBLEM,
    REASONS.crossProject,
  )
  const insightData: InsightData = { memory, audit, currentProject, crossProject }
  const insightResources = [input.memory, input.audit, aggregates.crossProjectInsight]
  const insight = presentedModule(
    insightData,
    compact([memory, audit, currentProject, crossProject]),
    {
      missingFields: missingFields(insightData),
      loading: resourceLoading(insightResources),
      error: resourceError(insightResources),
    },
  )

  const opportunity = mockValue(aggregates.review, REVIEW_PROJECT, REASONS.review)
  const kpis = mockValue(aggregates.kpis, REVIEW_PROJECT.materials, REASONS.kpis)
  const reviewData: ReviewData = { opportunity, kpis }
  const reviewResources = [aggregates.review, aggregates.kpis]
  const review = presentedModule(
    reviewData,
    compact([opportunity, kpis]),
    {
      missingFields: missingFields(reviewData),
      loading: resourceLoading(reviewResources),
      error: resourceError(reviewResources),
    },
  )

  const evidenceItems = mockValue(aggregates.review, REVIEW_FLOW.evidence, REASONS.evidence)
  const evidenceData: EvidenceData = { items: evidenceItems }
  const evidence = presentedModule(
    evidenceData,
    compact([evidenceItems]),
    {
      missingFields: missingFields(evidenceData),
      loading: resourceLoading([aggregates.review]),
      error: resourceError([aggregates.review]),
    },
  )

  const flowReference = {
    missingHint: REVIEW_FLOW.missingHint,
    resultPlaceholder: REVIEW_FLOW.resultPlaceholder,
    candidateReadyHint: REVIEW_FLOW.candidateReadyHint,
    candidateTitle: REVIEW_FLOW.candidateTitle,
  }
  const flow = mockValue(aggregates.review, flowReference, REASONS.flow)
  const workflowRecommendation = mockValue(
    aggregates.workflowRecommendation,
    CURRENT_PROJECT_INSIGHT.skill,
    REASONS.workflow,
  )
  const knowledgeFormationData: KnowledgeFormationData = { flow, workflowRecommendation }
  const knowledgeFormationResources = [
    aggregates.review,
    aggregates.workflowRecommendation,
  ]
  const knowledgeFormation = presentedModule(
    knowledgeFormationData,
    compact([flow, workflowRecommendation]),
    {
      missingFields: missingFields(knowledgeFormationData),
      loading: resourceLoading(knowledgeFormationResources),
      error: resourceError(knowledgeFormationResources),
    },
  )

  const mockActions: PresentedValue<MockInsightAction>[] = []
  if (canUseMockFallback(aggregates.review.state)) {
    mockActions.push(
      unavailableAction('start-review', '开始项目复盘', '复盘写入接口尚未提供，当前参考内容不可执行'),
      unavailableAction(
        'form-knowledge-candidate',
        '形成知识候选',
        '知识候选接口尚未提供，当前参考流程不可执行',
      ),
    )
  }
  if (canUseMockFallback(aggregates.workflowRecommendation.state)) {
    mockActions.push(
      unavailableAction(
        'apply-workflow-recommendation',
        '应用 Workflow 建议',
        'Workflow 创建接口尚未提供，当前参考建议不可执行',
      ),
    )
  }

  return {
    workOverview,
    insight,
    review,
    evidence,
    knowledgeFormation,
    mockActions,
  }
}
