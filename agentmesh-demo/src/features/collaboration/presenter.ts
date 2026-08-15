import {
  COLLAB_OVERVIEW,
  MY_COLLAB,
  MY_COLLABORATIONS,
  RECOMMENDED_PEERS,
} from '../../data/mockData'
import {
  canUseMockFallback,
  presentedModule,
  presentedValue,
  type PresentedModule,
  type PresentedValue,
  type PresentationState,
} from '../../lib/presentation'
import type { InboxItem } from '../knowledge/api'
import type {
  BlackboardPost,
  MarketBoard,
  MarketMatch,
  MarketSignal,
  MarketWorkerState,
  TaskCard,
  TaskDetail,
} from './api'

export interface CollaborationResource<T> {
  state: PresentationState
  data?: T
  error?: string
}

export type CollaborationRelationship = 'owner' | 'upstream' | 'downstream' | 'actor' | 'handoff'

export interface CollaborationParticipant {
  name: string
  relationship: CollaborationRelationship
}

export interface CollaborationContribution {
  actor: string
  detail: string
  kind: string
}

export interface CollaborationRecordTechnical {
  task: TaskCard['task']
  stage: TaskCard['stage']
  targetPostId: string | null
  upstreamAgents: string[]
  downstreamAgents: string[]
  claimedByPersonalAgent: boolean
}

type CollaborationSource = NonNullable<BlackboardPost['sources']>[number]

export interface CollaborationRecordView {
  id: PresentedValue<string>
  title: PresentedValue<string>
  status: PresentedValue<string>
  owner: PresentedValue<string | null>
  lock: PresentedValue<TaskCard['active_lock']>
  doneWhen: PresentedValue<string | null>
  postCount: PresentedValue<number>
  initiatedByCurrentUser: PresentedValue<boolean>
  participants: PresentedValue<CollaborationParticipant[]>
  contributions: PresentedValue<CollaborationContribution[]>
  sources: PresentedValue<CollaborationSource[]>
  actions: PresentedValue<string[]>
  technical: PresentedValue<CollaborationRecordTechnical>
}

export interface CollaborationTimelineTechnical {
  postType: BlackboardPost['post_type']
  title: string
  status: string
  scope: BlackboardPost['scope']
  permission: string
  collaborationStage: BlackboardPost['collaboration_stage']
  sources: BlackboardPost['sources']
  handoff: BlackboardPost['handoff']
  allowedActions: string[]
  currentOwnerAgentId: BlackboardPost['current_owner_agent_id']
  currentOwnerLabel: BlackboardPost['current_owner_label']
  executionLock: BlackboardPost['execution_lock']
  doneWhen: BlackboardPost['done_when']
  relatedPostId: BlackboardPost['related_post_id']
  readByAgents: BlackboardPost['read_by_agents']
  metadata: BlackboardPost['metadata']
}

export interface CollaborationTimelineItem {
  id: PresentedValue<string>
  taskId: PresentedValue<string>
  actor: PresentedValue<string>
  action: PresentedValue<string>
  narrative: PresentedValue<string>
  createdAt: PresentedValue<string | null>
  technical: PresentedValue<CollaborationTimelineTechnical>
}

export interface CollaborationMarketMatch extends MarketMatch {
  reason: PresentedValue<string>
}

export interface CollaborationMarketView {
  enabled: PresentedValue<boolean>
  counts: PresentedValue<MarketBoard['counts']>
  signals: PresentedValue<MarketSignal[]>
  matches: PresentedValue<CollaborationMarketMatch[]>
  publishWorker: PresentedValue<MarketWorkerState>
  scoutWorker: PresentedValue<MarketWorkerState>
}

export interface CollaborationAuthorizationView {
  id: PresentedValue<string>
  title: PresentedValue<string>
  summary: PresentedValue<string>
  status: PresentedValue<string>
  scope: PresentedValue<InboxItem['scope']>
  projectId: PresentedValue<string | null>
  applicant: PresentedValue<string>
  taskId: PresentedValue<string | null>
  metadata: PresentedValue<Record<string, string>>
  actions: PresentedValue<Array<'approve' | 'deny'>>
}

export interface CollaborationOverviewView {
  visibleTasks: PresentedValue<number>
  activeTasks: PresentedValue<number>
  marketParticipants: PresentedValue<number>
  receivedSupport: PresentedValue<number>
  periodAggregates: PresentedValue<{ all: number; ongoing: number; completed: number }>
  capabilityPercentages: PresentedValue<Array<{ label: string; percentage: number }>>
}

export interface CollaborationTabView {
  key: 'all' | 'mine' | 'authorization'
  label: string
  count: PresentedValue<number>
}

export interface CollaborationViewModel {
  overview: PresentedModule<CollaborationOverviewView>
  tabs: PresentedModule<CollaborationTabView[]>
  records: PresentedModule<CollaborationRecordView[]>
  timeline: PresentedModule<CollaborationTimelineItem[]>
  market: PresentedModule<CollaborationMarketView>
  authorizations: PresentedModule<CollaborationAuthorizationView[]>
}

interface CollaborationPresenterInput {
  projectId: string
  taskCards: CollaborationResource<TaskCard[]>
  taskDetails: CollaborationResource<TaskDetail[]>
  marketBoard: CollaborationResource<MarketBoard>
  inbox: CollaborationResource<InboxItem[]>
}

const EMPTY_COUNTS: MarketBoard['counts'] = {
  signals: 0,
  matches: 0,
  consent_grants: 0,
  participants: 0,
}

const EMPTY_WORKER: MarketWorkerState = {
  enabled: false,
  running: false,
  last_run_at: null,
  last_error: null,
}

const ACTIVE_TASK_STATUSES: Partial<Record<string, true>> = {
  created: true,
  running: true,
  waiting_external_agent: true,
  synthesizing: true,
  pending: true,
  active: true,
  blocked: true,
}

const AUTHORIZATION_ITEM_TYPES: Partial<Record<string, true>> = {
  collaboration_authorization: true,
  delegated_answer_confirmation: true,
}

function resourceData<T>(resource: CollaborationResource<T>, empty: T): T {
  if (resource.state === 'forbidden' || resource.state === 'error') return empty
  return resource.data ?? empty
}

function resourceError(...resources: CollaborationResource<unknown>[]): string | null {
  return resources.find((resource) => resource.state === 'forbidden' || resource.state === 'error')?.error ?? null
}

function resourceLoading(...resources: CollaborationResource<unknown>[]): boolean {
  return resources.some((resource) => resource.state === 'loading')
}

function canFillDisplayGap(...resources: CollaborationResource<unknown>[]): boolean {
  return resources.every((resource) => resource.state === 'available' || canUseMockFallback(resource.state))
}

function addParticipant(
  participants: CollaborationParticipant[],
  name: string | null | undefined,
  relationship: CollaborationRelationship,
) {
  const normalizedName = name?.trim()
  if (!normalizedName) return
  if (participants.some((participant) => participant.name === normalizedName && participant.relationship === relationship)) return
  participants.push({ name: normalizedName, relationship })
}


function buildRecord(card: TaskCard, detail: TaskDetail | undefined): CollaborationRecordView {
  const posts = detail?.posts ?? (card.latest_post ? [card.latest_post] : [])
  const participants: CollaborationParticipant[] = []
  const contributions: CollaborationContribution[] = []

  addParticipant(participants, card.owner ?? card.task.current_owner_label, 'owner')
  for (const agent of card.upstream_agents ?? []) addParticipant(participants, agent, 'upstream')
  for (const agent of card.downstream_agents ?? []) addParticipant(participants, agent, 'downstream')

  for (const post of posts) {
    addParticipant(participants, post.actor, 'actor')
    contributions.push({ actor: post.actor, detail: post.content, kind: post.post_type })
    if (post.handoff) {
      addParticipant(participants, post.handoff.next_owner_agent_id, 'handoff')
      if (post.handoff.current_result) {
        contributions.push({
          actor: post.actor,
          detail: post.handoff.current_result,
          kind: 'handoff',
        })
      }
    }
  }

  const sources = posts.flatMap((post) => post.sources ?? [])
  const id = card.task.id ?? ''

  return {
    id: presentedValue(id, 'T'),
    title: presentedValue(card.task.title, 'T'),
    status: presentedValue(card.task.status, 'T'),
    owner: presentedValue(card.owner ?? card.task.current_owner_label ?? null, 'T'),
    lock: presentedValue(card.active_lock ?? card.task.execution_lock ?? null, 'T'),
    doneWhen: presentedValue(card.done_when ?? card.task.done_when ?? null, 'T'),
    postCount: presentedValue(card.post_count, 'T'),
    initiatedByCurrentUser: presentedValue(card.initiated_by_current_user, 'T'),
    participants: presentedValue(participants, 'T'),
    contributions: presentedValue(contributions, 'T'),
    sources: presentedValue(sources, 'T'),
    actions: presentedValue(card.allowed_actions, 'T'),
    technical: presentedValue({
      task: card.task,
      stage: card.stage,
      targetPostId: card.target_post_id ?? null,
      upstreamAgents: card.upstream_agents ?? [],
      downstreamAgents: card.downstream_agents ?? [],
      claimedByPersonalAgent: card.claimed_by_personal_agent,
    }, 'T'),
  }
}

function actionLabel(postType: BlackboardPost['post_type']): string {
  const labels: Record<BlackboardPost['post_type'], string> = {
    request: '发起求助',
    evidence: '补充经验',
    risk: '提醒风险',
    digest: '汇总结论',
    decision: '记录决策',
    handoff: '交接任务',
    archive: '归档结果',
    correction: '修正信息',
    memory_candidate: '沉淀知识候选',
    marketplace_signal: '发布协作信号',
    marketplace_match: '完成协作匹配',
  }
  return labels[postType]
}

function buildTimeline(details: TaskDetail[]): CollaborationTimelineItem[] {
  return details.flatMap((detail) => detail.posts.map((post, index) => ({
    id: presentedValue(post.id ?? `${post.task_id}-post-${index + 1}`, 'T'),
    taskId: presentedValue(post.task_id, 'T'),
    actor: presentedValue(post.actor, 'T'),
    action: presentedValue(actionLabel(post.post_type), 'T'),
    narrative: presentedValue(post.content, 'T'),
    createdAt: presentedValue(post.created_at ?? null, 'T'),
    technical: presentedValue({
      postType: post.post_type,
      title: post.title,
      status: post.status,
      scope: post.scope,
      permission: post.permission,
      collaborationStage: post.collaboration_stage,
      sources: post.sources,
      handoff: post.handoff,
      allowedActions: post.allowed_actions,
      currentOwnerAgentId: post.current_owner_agent_id,
      currentOwnerLabel: post.current_owner_label,
      executionLock: post.execution_lock,
      doneWhen: post.done_when,
      relatedPostId: post.related_post_id,
      readByAgents: post.read_by_agents,
      metadata: post.metadata,
    }, 'T'),
  })))
}

function isCurrentProjectAuthorization(item: InboxItem, projectId: string): boolean {
  return item.status === 'open'
    && item.project_id === projectId
    && AUTHORIZATION_ITEM_TYPES[item.item_type] === true
}

function buildAuthorizations(items: InboxItem[], projectId: string): CollaborationAuthorizationView[] {
  return items
    .filter((item) => isCurrentProjectAuthorization(item, projectId))
    .map((item) => {
      const metadata = item.metadata ?? {}
      const actions = item.allowed_actions.filter(
        (action): action is 'approve' | 'deny' => action === 'approve' || action === 'deny',
      )
      return {
        id: presentedValue(item.id ?? '', 'T'),
        title: presentedValue(item.title, 'T'),
        summary: presentedValue(item.summary, 'T'),
        status: presentedValue(item.status, 'T'),
        scope: presentedValue(item.scope, 'T'),
        projectId: presentedValue(item.project_id ?? null, 'T'),
        applicant: presentedValue(metadata.applicant ?? item.title, 'T'),
        taskId: presentedValue(metadata.task_id ?? null, 'T'),
        metadata: presentedValue(metadata, 'T'),
        actions: presentedValue(actions, 'T'),
      }
    })
}

export function collaborationDetailTaskIds(
  taskCards: TaskCard[],
  inbox: InboxItem[],
  projectId: string,
): string[] {
  const taskIds = new Set<string>()
  for (const card of taskCards) {
    if (card.task.id) taskIds.add(card.task.id)
  }
  for (const item of inbox) {
    if (!isCurrentProjectAuthorization(item, projectId)) continue
    const taskId = item.metadata?.task_id
    if (taskId) taskIds.add(taskId)
  }
  return [...taskIds]
}

export function buildCollaborationViewModel(input: CollaborationPresenterInput): CollaborationViewModel {
  const taskCards = resourceData(input.taskCards, [])
  const taskDetails = resourceData(input.taskDetails, [])
  const marketBoard = resourceData<MarketBoard | null>(input.marketBoard, null)
  const inbox = resourceData(input.inbox, [])
  const authorizations = buildAuthorizations(inbox, input.projectId)
  const records = taskCards.map((card) => buildRecord(
    card,
    taskDetails.find((detail) => detail.task_card.task.id === card.task.id),
  ))
  const timeline = buildTimeline(taskDetails)
  const canUseOverviewFallback = canFillDisplayGap(input.taskCards, input.marketBoard)
  const canUseMarketReasonFallback = canFillDisplayGap(input.marketBoard)

  const visibleTasks = presentedValue(taskCards.length, 'T')
  const activeTasks = presentedValue(
    taskCards.filter((card) => ACTIVE_TASK_STATUSES[card.task.status] === true).length,
    'T',
  )
  const marketParticipants = presentedValue(marketBoard?.counts.participants ?? 0, 'T')
  const receivedSupport = canUseOverviewFallback
    ? presentedValue(COLLAB_OVERVIEW.receivedSupport, 'M', '后端暂无周期聚合')
    : presentedValue(0, 'T')
  const periodAggregates = canUseOverviewFallback
    ? presentedValue({
      all: MY_COLLABORATIONS.length,
      ongoing: MY_COLLABORATIONS.filter((item) => item.status === 'ongoing').length,
      completed: MY_COLLABORATIONS.filter((item) => item.status === 'done').length,
    }, 'M', '后端暂无周期聚合')
    : presentedValue({ all: 0, ongoing: 0, completed: 0 }, 'T')
  const capabilityPercentages = canUseOverviewFallback
    ? presentedValue(MY_COLLAB.capabilities.map((capability) => ({
      label: capability.name,
      percentage: 100 / MY_COLLAB.capabilities.length,
    })), 'M', '后端暂无能力占比')
    : presentedValue<Array<{ label: string; percentage: number }>>([], 'T')
  const overview = {
    visibleTasks,
    activeTasks,
    marketParticipants,
    receivedSupport,
    periodAggregates,
    capabilityPercentages,
  }
  const overviewValues = Object.values(overview)
  const overviewMissing = canUseOverviewFallback
    ? ['receivedSupport', 'periodAggregates', 'capabilityPercentages']
    : []

  const tabs: CollaborationTabView[] = [
    { key: 'all', label: '全部协作', count: presentedValue(taskCards.length, 'T') },
    {
      key: 'mine',
      label: '我的申请',
      count: presentedValue(taskCards.filter((card) => card.initiated_by_current_user).length, 'T'),
    },
    { key: 'authorization', label: '待我授权', count: presentedValue(authorizations.length, 'T') },
  ]

  const marketMatches: CollaborationMarketMatch[] = (marketBoard?.matches ?? []).map((match, index) => ({
    ...match,
    reason: canUseMarketReasonFallback
      ? presentedValue(
        RECOMMENDED_PEERS[index % RECOMMENDED_PEERS.length]?.reason ?? '基于当前供需信号匹配。',
        'M',
        '后端暂无匹配原因',
      )
      : presentedValue('', 'T'),
  }))
  const market: CollaborationMarketView = {
    enabled: presentedValue(marketBoard?.enabled ?? false, 'T'),
    counts: presentedValue(marketBoard?.counts ?? EMPTY_COUNTS, 'T'),
    signals: presentedValue(marketBoard?.signals ?? [], 'T'),
    matches: presentedValue(marketMatches, 'T'),
    publishWorker: presentedValue(marketBoard?.publish_worker ?? EMPTY_WORKER, 'T'),
    scoutWorker: presentedValue(marketBoard?.scout_worker ?? EMPTY_WORKER, 'T'),
  }

  const recordValues = records.flatMap((record) => Object.values(record))
  const timelineValues = timeline.flatMap((item) => Object.values(item))
  const authorizationValues = authorizations.flatMap((item) => Object.values(item))
  const marketValues = [
    ...Object.values(market),
    ...marketMatches.map((match) => match.reason),
  ]

  return {
    overview: presentedModule(overview, overviewValues, {
      missingFields: overviewMissing,
      loading: resourceLoading(input.taskCards, input.marketBoard),
      error: resourceError(input.taskCards, input.marketBoard),
    }),
    tabs: presentedModule(tabs, tabs.map((tab) => tab.count), {
      loading: resourceLoading(input.taskCards, input.inbox),
      error: resourceError(input.taskCards, input.inbox),
    }),
    records: presentedModule(records, recordValues, {
      loading: resourceLoading(input.taskCards, input.taskDetails),
      error: resourceError(input.taskCards, input.taskDetails),
    }),
    timeline: presentedModule(timeline, timelineValues, {
      loading: resourceLoading(input.taskDetails),
      error: resourceError(input.taskDetails),
    }),
    market: presentedModule(market, marketValues, {
      missingFields: canUseMarketReasonFallback && marketMatches.length > 0 ? ['matches.reason'] : [],
      loading: resourceLoading(input.marketBoard),
      error: resourceError(input.marketBoard),
    }),
    authorizations: presentedModule(authorizations, authorizationValues, {
      loading: resourceLoading(input.inbox),
      error: resourceError(input.inbox),
    }),
  }
}
