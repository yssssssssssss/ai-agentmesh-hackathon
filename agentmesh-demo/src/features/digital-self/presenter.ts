import {
  KNOWLEDGE_ASSETS,
  PRIORITY_ITEMS,
  SHARE_EVENTS,
  UNDERSTANDINGS,
} from '../../data/mockData'
import {
  canUseMockFallback,
  presentedModule,
  presentedValue,
  type PresentedModule,
  type PresentedValue,
  type PresentationState,
} from '../../lib/presentation'
import type { BootstrapState } from '../auth/api'
import type { ActivityTodayResponse, Agent, MemoryOverviewResponse } from './api'

const CATEGORY_REASON = '后端暂无经验、方法与协作分类聚合'
const IMPACT_REASON = '后端暂无经验复用记录'
const EMPTY_FALLBACK_REASON = '真实列表为空，使用参考展示数据'
const NARRATIVE_REASON = '后端暂无推进叙事'
const PARTICIPANT_REASON = '后端暂无参与人数聚合'

export interface DigitalSelfResource<T> {
  state: PresentationState
  data?: T
  error?: string
}

export interface DigitalSelfPresenterInput {
  bootstrap: DigitalSelfResource<BootstrapState>
  agent: DigitalSelfResource<Agent>
  activity: DigitalSelfResource<ActivityTodayResponse>
  memory: DigitalSelfResource<MemoryOverviewResponse>
}

export interface DigitalSelfHeroData {
  greeting: PresentedValue<string>
  workspaceName: PresentedValue<string>
  projectName: PresentedValue<string>
  projectGoal: PresentedValue<string>
  agentName: PresentedValue<string> | null
  agentStatus: PresentedValue<string> | null
  currentTask: PresentedValue<string | null> | null
  progressNarrative: PresentedValue<string>
  participantCount: PresentedValue<number>
}

export interface DigitalSelfPendingItem {
  id: PresentedValue<string | null>
  title: PresentedValue<string>
  context: PresentedValue<string>
  tag: PresentedValue<string>
  actor?: PresentedValue<string>
  cta?: PresentedValue<string>
  to?: PresentedValue<string>
}

export interface DigitalSelfUnderstandingItem {
  id: PresentedValue<string | null>
  text: PresentedValue<string>
  basis: PresentedValue<string>
  source: PresentedValue<string>
}

export interface DigitalSelfGrowthCategory {
  metric: PresentedValue<string>
  label: PresentedValue<string>
  value: PresentedValue<string>
}

export interface DigitalSelfMemoryCounts {
  short: PresentedValue<number>
  project: PresentedValue<number>
  archive: PresentedValue<number>
  team: PresentedValue<number>
}

export interface DigitalSelfImpactItem {
  label: PresentedValue<string>
  value: PresentedValue<string>
  meta: PresentedValue<string>
}

export interface DigitalSelfViewModel {
  hero: PresentedModule<DigitalSelfHeroData | null>
  pending: PresentedModule<{ items: DigitalSelfPendingItem[] }>
  understanding: PresentedModule<{ items: DigitalSelfUnderstandingItem[] }>
  growth: PresentedModule<{
    memoryCounts: DigitalSelfMemoryCounts | null
    categories: DigitalSelfGrowthCategory[]
  }>
  impact: PresentedModule<{
    items: DigitalSelfImpactItem[]
    mutation: null
  }>
}

function resourceOptions(resource: DigitalSelfResource<unknown>) {
  return {
    loading: resource.state === 'loading',
    error: resource.error ?? null,
  }
}

function buildHero(
  bootstrapResource: DigitalSelfResource<BootstrapState>,
  agentResource: DigitalSelfResource<Agent>,
): DigitalSelfViewModel['hero'] {
  if (bootstrapResource.state !== 'available' || !bootstrapResource.data) {
    return presentedModule(null, [], resourceOptions(bootstrapResource))
  }

  const { project, user, workspace } = bootstrapResource.data
  const agent = agentResource.state === 'available' ? agentResource.data : undefined
  const greeting = presentedValue(`下午好，${user.name}`, 'T')
  const workspaceName = presentedValue(workspace.name, 'T')
  const projectName = presentedValue(project.name, 'T')
  const projectGoal = presentedValue(project.goal, 'T')
  const agentName = agent ? presentedValue(agent.name, 'T') : null
  const agentStatus = agent ? presentedValue(agent.status, 'T') : null
  const currentTask = agent ? presentedValue(agent.current_task_title ?? null, 'T') : null
  const participantCount = presentedValue(2, 'M', PARTICIPANT_REASON)
  const progressNarrative = presentedValue(
    `你的数字员工正在推进「${project.name}」，已完成历史项目与团队经验检索，并邀请 ${participantCount.value} 位同事的数字员工补充项目经验和近期数据。`,
    'M',
    NARRATIVE_REASON,
  )
  const values: PresentedValue<unknown>[] = [
    greeting,
    workspaceName,
    projectName,
    projectGoal,
  ]
  if (agentName) values.push(agentName)
  if (agentStatus) values.push(agentStatus)
  if (currentTask) values.push(currentTask)
  values.push(progressNarrative, participantCount)

  return presentedModule(
    {
      greeting,
      workspaceName,
      projectName,
      projectGoal,
      agentName,
      agentStatus,
      currentTask,
      progressNarrative,
      participantCount,
    },
    values,
    {
      missingFields: ['progressNarrative', 'participantCount'],
      loading: agentResource.state === 'loading',
      error: agentResource.error ?? null,
    },
  )
}

function buildPending(
  resource: DigitalSelfResource<ActivityTodayResponse>,
): DigitalSelfViewModel['pending'] {
  const activityItems = resource.data
    ? [...resource.data.personal, ...resource.data.external]
    : []

  if (activityItems.length > 0 && resource.state !== 'loading' && resource.state !== 'forbidden' && resource.state !== 'error') {
    const items = activityItems.map((item) => ({
      id: presentedValue(item.id ?? null, 'T'),
      title: presentedValue(item.title, 'T'),
      context: presentedValue(item.summary, 'T'),
      tag: presentedValue(item.category, 'T'),
      actor: presentedValue(item.actor, 'T'),
    }))
    return presentedModule(items.length ? { items } : { items: [] }, items.flatMap(Object.values), resourceOptions(resource))
  }

  if (canUseMockFallback(resource.state)) {
    const items = PRIORITY_ITEMS.map((item) => ({
      id: presentedValue(item.id, 'M', EMPTY_FALLBACK_REASON),
      title: presentedValue(item.title, 'M', EMPTY_FALLBACK_REASON),
      context: presentedValue(item.context, 'M', EMPTY_FALLBACK_REASON),
      tag: presentedValue(item.tag, 'M', EMPTY_FALLBACK_REASON),
      cta: presentedValue(item.cta, 'M', EMPTY_FALLBACK_REASON),
      to: presentedValue(item.to, 'M', EMPTY_FALLBACK_REASON),
    }))
    return presentedModule({ items }, items.flatMap(Object.values), {
      missingFields: ['activity'],
      ...resourceOptions(resource),
    })
  }

  return presentedModule({ items: [] }, [], resourceOptions(resource))
}

function buildUnderstanding(
  resource: DigitalSelfResource<MemoryOverviewResponse>,
): DigitalSelfViewModel['understanding'] {
  const records = resource.data
    ? [
        ...resource.data.sections.short,
        ...resource.data.sections.project,
        ...resource.data.sections.archive,
        ...resource.data.sections.team,
      ]
    : []

  if (records.length > 0 && resource.state !== 'loading' && resource.state !== 'forbidden' && resource.state !== 'error') {
    const items = records.map((item) => ({
      id: presentedValue(item.id ?? null, 'T'),
      text: presentedValue(item.summary, 'T'),
      basis: presentedValue(item.title, 'T'),
      source: presentedValue(
        'source_kind' in item ? item.source_kind : item.sources?.[0]?.source_type ?? 'team',
        'T',
      ),
    }))
    return presentedModule({ items }, items.flatMap(Object.values), resourceOptions(resource))
  }

  if (canUseMockFallback(resource.state)) {
    const items = UNDERSTANDINGS.map((item) => ({
      id: presentedValue(item.id, 'M', EMPTY_FALLBACK_REASON),
      text: presentedValue(item.text, 'M', EMPTY_FALLBACK_REASON),
      basis: presentedValue(item.basis, 'M', EMPTY_FALLBACK_REASON),
      source: presentedValue(item.source, 'M', EMPTY_FALLBACK_REASON),
    }))
    return presentedModule({ items }, items.flatMap(Object.values), {
      missingFields: ['memory'],
      ...resourceOptions(resource),
    })
  }

  return presentedModule({ items: [] }, [], resourceOptions(resource))
}

function buildGrowthCategories(): DigitalSelfGrowthCategory[] {
  const experiences = KNOWLEDGE_ASSETS.filter((item) => item.type === 'project_experience')
  const methods = KNOWLEDGE_ASSETS.filter((item) => item.type === 'decision_method')
  const reused = SHARE_EVENTS.filter((event) => event.type === 'reused')
  const collaborators = new Set(reused.map((event) => event.actor)).size

  return [
    {
      metric: presentedValue(`+${experiences.length}`, 'M', CATEGORY_REASON),
      label: presentedValue('已确认经验', 'M', CATEGORY_REASON),
      value: presentedValue(experiences[0]?.title ?? '暂无参考经验', 'M', CATEGORY_REASON),
    },
    {
      metric: presentedValue(`+${methods.length}`, 'M', CATEGORY_REASON),
      label: presentedValue('工作方法', 'M', CATEGORY_REASON),
      value: presentedValue(methods[0]?.title ?? '暂无参考方法', 'M', CATEGORY_REASON),
    },
    {
      metric: presentedValue(`+${reused.length}`, 'M', CATEGORY_REASON),
      label: presentedValue('次协作', 'M', CATEGORY_REASON),
      value: presentedValue(`${collaborators} 位数字人复用经验`, 'M', CATEGORY_REASON),
    },
  ]
}

function buildGrowth(
  resource: DigitalSelfResource<MemoryOverviewResponse>,
): DigitalSelfViewModel['growth'] {
  if (resource.state === 'loading' || resource.state === 'forbidden' || resource.state === 'error') {
    return presentedModule(
      { memoryCounts: null, categories: [] },
      [],
      resourceOptions(resource),
    )
  }

  const memoryCounts = resource.data
    ? {
        short: presentedValue(resource.data.counts.short, 'T'),
        project: presentedValue(resource.data.counts.project, 'T'),
        archive: presentedValue(resource.data.counts.archive, 'T'),
        team: presentedValue(resource.data.counts.team, 'T'),
      }
    : null
  const categories = buildGrowthCategories()
  const values: PresentedValue<unknown>[] = memoryCounts
    ? [...Object.values(memoryCounts), ...categories.flatMap(Object.values)]
    : categories.flatMap(Object.values)

  return presentedModule(
    { memoryCounts, categories },
    values,
    {
      missingFields: memoryCounts
        ? ['categoryAggregation']
        : ['memoryOverview', 'categoryAggregation'],
      ...resourceOptions(resource),
    },
  )
}

function buildImpact(): DigitalSelfViewModel['impact'] {
  const reused = SHARE_EVENTS.filter((event) => event.type === 'reused')
  const collaborators = new Set(reused.map((event) => event.actor)).size
  const items: DigitalSelfImpactItem[] = [
    ...reused.slice(0, 2).map((event) => ({
      label: presentedValue(event.knowledgeTitle, 'M', IMPACT_REASON),
      value: presentedValue(event.description, 'M', IMPACT_REASON),
      meta: presentedValue(event.time, 'M', IMPACT_REASON),
    })),
    {
      label: presentedValue('本周影响', 'M', IMPACT_REASON),
      value: presentedValue(
        `帮助 ${collaborators} 位同事 · 被调用 ${reused.length} 次`,
        'M',
        IMPACT_REASON,
      ),
      meta: presentedValue('', 'M', IMPACT_REASON),
    },
  ]

  return presentedModule(
    { items, mutation: null },
    items.flatMap(Object.values),
    { missingFields: ['reuseRecords'] },
  )
}

export function buildDigitalSelfViewModel(
  input: DigitalSelfPresenterInput,
): DigitalSelfViewModel {
  return {
    hero: buildHero(input.bootstrap, input.agent),
    pending: buildPending(input.activity),
    understanding: buildUnderstanding(input.memory),
    growth: buildGrowth(input.memory),
    impact: buildImpact(),
  }
}
