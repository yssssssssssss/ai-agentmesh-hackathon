import type { BlackboardPost, TaskCard, TaskDetail } from '../collaboration/api'

export type TaskPresentationTone = 'mint' | 'knowledge' | 'collab' | 'remind' | 'neutral' | 'rose'
export type KnownTaskStage = NonNullable<TaskCard['stage']>
export type KnownTaskStatus = TaskCard['task']['status']
export type TaskStageKey = KnownTaskStage | 'unknown'
export type TaskStatusKey = KnownTaskStatus | 'unknown'

export interface TaskFacetOption<T extends string> {
  value: T
  label: string
  tone: TaskPresentationTone
}

export const TASK_STAGE_OPTIONS = [
  { value: 'discussion', label: '讨论', tone: 'knowledge' },
  { value: 'execution', label: '执行', tone: 'collab' },
  { value: 'review', label: '评审', tone: 'remind' },
  { value: 'blocked', label: '阻塞', tone: 'rose' },
  { value: 'completed', label: '协作完成', tone: 'mint' },
  { value: 'unknown', label: '未知阶段', tone: 'neutral' },
] as const satisfies readonly TaskFacetOption<TaskStageKey>[]

export const TASK_STATUS_OPTIONS = [
  { value: 'created', label: '已创建', tone: 'neutral' },
  { value: 'running', label: '运行中', tone: 'collab' },
  { value: 'waiting_external_agent', label: '等待外部 Agent', tone: 'remind' },
  { value: 'synthesizing', label: '汇总中', tone: 'knowledge' },
  { value: 'completed', label: '执行完成', tone: 'mint' },
  { value: 'failed', label: '执行失败', tone: 'rose' },
  { value: 'unknown', label: '未知状态', tone: 'neutral' },
] as const satisfies readonly TaskFacetOption<TaskStatusKey>[]

export interface PresentedTaskFacet<T extends string> extends TaskFacetOption<T> {
  rawValue: string | null
}

type ActiveLock = NonNullable<TaskCard['active_lock']>

export interface TaskCenterItem {
  id: string
  title: string
  executionStatus: PresentedTaskFacet<TaskStatusKey>
  collaborationStage: PresentedTaskFacet<TaskStageKey>
  owner: string | null
  doneWhen: string | null
  activeLock: ActiveLock | null
  steps: string[]
  createdAt: string | null
  updatedAt: string | null
  lastActivityAt: string | null
  postCount: number
  initiatedByCurrentUser: boolean
  claimedByPersonalAgent: boolean
  card: TaskCard
}

export interface TaskCenterFilters {
  query: string
  collaborationStage: TaskStageKey | 'all'
  executionStatus: TaskStatusKey | 'all'
}

export const DEFAULT_TASK_CENTER_FILTERS: Readonly<TaskCenterFilters> = {
  query: '',
  collaborationStage: 'all',
  executionStatus: 'all',
}

export interface TaskCenterGroup {
  stage: TaskFacetOption<TaskStageKey>
  items: TaskCenterItem[]
}

export interface TaskCenterStats {
  totalVisible: number
  filteredVisible: number
  locked: number
  activeVisible: number
  blockedVisible: number
  completedVisible: number
  byStage: Record<TaskStageKey, number>
  byExecutionStatus: Record<TaskStatusKey, number>
}

export type TaskCenterEmptyReason = 'no-visible-tasks' | 'no-filter-matches' | null

export interface TaskCenterViewModel {
  items: TaskCenterItem[]
  groups: TaskCenterGroup[]
  filters: TaskCenterFilters
  stats: TaskCenterStats
  hasActiveFilters: boolean
  emptyReason: TaskCenterEmptyReason
}

type KnownPostType = BlackboardPost['post_type']
type PostTypeKey = KnownPostType | 'unknown'

export interface TaskTimelineItem {
  id: string
  actor: string
  title: string
  content: string
  postType: PresentedTaskFacet<PostTypeKey>
  collaborationStage: PresentedTaskFacet<TaskStageKey>
  publicationStatus: string
  owner: string | null
  doneWhen: string | null
  executionLock: BlackboardPost['execution_lock']
  createdAt: string | null
  sources: NonNullable<BlackboardPost['sources']>
  post: BlackboardPost
}

export interface TaskDetailViewModel {
  task: TaskCenterItem
  timeline: TaskTimelineItem[]
}

const STAGE_OPTION_BY_VALUE = new Map<TaskStageKey, TaskFacetOption<TaskStageKey>>(
  TASK_STAGE_OPTIONS.map((option) => [option.value, option]),
)
const STATUS_OPTION_BY_VALUE = new Map<TaskStatusKey, TaskFacetOption<TaskStatusKey>>(
  TASK_STATUS_OPTIONS.map((option) => [option.value, option]),
)
const KNOWN_STAGE_VALUES = new Set<string>(TASK_STAGE_OPTIONS.slice(0, -1).map((option) => option.value))
const KNOWN_STATUS_VALUES = new Set<string>(TASK_STATUS_OPTIONS.slice(0, -1).map((option) => option.value))
const ACTIVE_STATUS_VALUES = new Set<TaskStatusKey>([
  'running',
  'waiting_external_agent',
  'synthesizing',
])

const POST_TYPE_OPTIONS = [
  { value: 'request', label: '发起请求', tone: 'knowledge' },
  { value: 'evidence', label: '补充证据', tone: 'mint' },
  { value: 'risk', label: '提示风险', tone: 'rose' },
  { value: 'digest', label: '汇总结论', tone: 'collab' },
  { value: 'decision', label: '记录决策', tone: 'remind' },
  { value: 'handoff', label: '任务交接', tone: 'collab' },
  { value: 'archive', label: '归档结果', tone: 'neutral' },
  { value: 'correction', label: '修正信息', tone: 'remind' },
  { value: 'memory_candidate', label: '沉淀知识候选', tone: 'mint' },
  { value: 'marketplace_signal', label: '发布协作信号', tone: 'knowledge' },
  { value: 'marketplace_match', label: '完成协作匹配', tone: 'collab' },
  { value: 'unknown', label: '未知动态', tone: 'neutral' },
] as const satisfies readonly TaskFacetOption<PostTypeKey>[]

const POST_TYPE_OPTION_BY_VALUE = new Map<PostTypeKey, TaskFacetOption<PostTypeKey>>(
  POST_TYPE_OPTIONS.map((option) => [option.value, option]),
)
const KNOWN_POST_TYPE_VALUES = new Set<string>(POST_TYPE_OPTIONS.slice(0, -1).map((option) => option.value))

function nonEmptyString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  return normalized || null
}

function validTimestamp(value: unknown): string | null {
  const normalized = nonEmptyString(value)
  if (!normalized || !Number.isFinite(Date.parse(normalized))) return null
  return normalized
}

function latestTimestamp(...values: unknown[]): string | null {
  let latest: string | null = null
  let latestValue = Number.NEGATIVE_INFINITY
  for (const value of values) {
    const timestamp = validTimestamp(value)
    if (!timestamp) continue
    const parsed = Date.parse(timestamp)
    if (parsed <= latestValue) continue
    latest = timestamp
    latestValue = parsed
  }
  return latest
}

function presentedStage(value: unknown): PresentedTaskFacet<TaskStageKey> {
  const rawValue = nonEmptyString(value)
  const key: TaskStageKey = rawValue && KNOWN_STAGE_VALUES.has(rawValue)
    ? rawValue as KnownTaskStage
    : 'unknown'
  const option = STAGE_OPTION_BY_VALUE.get(key) as TaskFacetOption<TaskStageKey>
  return { ...option, rawValue }
}

function presentedStatus(value: unknown): PresentedTaskFacet<TaskStatusKey> {
  const rawValue = nonEmptyString(value)
  const key: TaskStatusKey = rawValue && KNOWN_STATUS_VALUES.has(rawValue)
    ? rawValue as KnownTaskStatus
    : 'unknown'
  const option = STATUS_OPTION_BY_VALUE.get(key) as TaskFacetOption<TaskStatusKey>
  return { ...option, rawValue }
}

function presentedPostType(value: unknown): PresentedTaskFacet<PostTypeKey> {
  const rawValue = nonEmptyString(value)
  const key: PostTypeKey = rawValue && KNOWN_POST_TYPE_VALUES.has(rawValue)
    ? rawValue as KnownPostType
    : 'unknown'
  const option = POST_TYPE_OPTION_BY_VALUE.get(key) as TaskFacetOption<PostTypeKey>
  return { ...option, rawValue }
}

function activeLock(card: TaskCard): ActiveLock | null {
  const lock = card.active_lock ?? card.task.execution_lock ?? null
  if (!lock || lock.released_at) return null
  return lock
}

function presentTaskCard(card: TaskCard, index: number): TaskCenterItem {
  const task = card.task
  const lock = activeLock(card)
  const createdAt = validTimestamp(task.created_at)
  const updatedAt = validTimestamp(task.updated_at)
  const latestPostAt = validTimestamp(card.latest_post?.created_at)

  return {
    id: nonEmptyString(task.id) ?? nonEmptyString(task.thread_id) ?? `visible-task-${index + 1}`,
    title: nonEmptyString(task.title) ?? '未命名任务',
    executionStatus: presentedStatus(task.status),
    collaborationStage: presentedStage(nonEmptyString(card.stage) ?? task.collaboration_stage),
    owner: nonEmptyString(card.owner)
      ?? nonEmptyString(task.current_owner_label),
    doneWhen: nonEmptyString(card.done_when) ?? nonEmptyString(task.done_when),
    activeLock: lock,
    steps: (task.steps ?? []).flatMap((step) => nonEmptyString(step) ?? []),
    createdAt,
    updatedAt,
    lastActivityAt: latestTimestamp(latestPostAt, updatedAt, createdAt),
    postCount: Number.isFinite(card.post_count) && card.post_count > 0 ? Math.floor(card.post_count) : 0,
    initiatedByCurrentUser: card.initiated_by_current_user === true,
    claimedByPersonalAgent: card.claimed_by_personal_agent === true,
    card,
  }
}

function textCompare(left: string, right: string): number {
  if (left === right) return 0
  return left < right ? -1 : 1
}

function timestampValue(value: string | null): number {
  return value ? Date.parse(value) : Number.NEGATIVE_INFINITY
}

function compareTimestamp(left: string | null, right: string | null, direction: 'asc' | 'desc'): number {
  const leftValue = timestampValue(left)
  const rightValue = timestampValue(right)
  if (leftValue === rightValue) return 0
  if (leftValue === Number.NEGATIVE_INFINITY) return 1
  if (rightValue === Number.NEGATIVE_INFINITY) return -1
  if (direction === 'asc') return leftValue < rightValue ? -1 : 1
  return leftValue > rightValue ? -1 : 1
}

function sortedTaskItems(cards: readonly TaskCard[]): TaskCenterItem[] {
  return cards
    .map((card, index) => ({ item: presentTaskCard(card, index), inputIndex: index }))
    .sort((left, right) => {
      const timeDifference = compareTimestamp(left.item.lastActivityAt, right.item.lastActivityAt, 'desc')
      if (timeDifference !== 0) return timeDifference
      const titleDifference = textCompare(left.item.title, right.item.title)
      if (titleDifference !== 0) return titleDifference
      const idDifference = textCompare(left.item.id, right.item.id)
      return idDifference || left.inputIndex - right.inputIndex
    })
    .map(({ item }) => item)
}

function normalizedSearchText(value: string): string {
  return value.normalize('NFKC').toLocaleLowerCase().trim().replace(/\s+/g, ' ')
}

function itemMatchesQuery(item: TaskCenterItem, query: string): boolean {
  if (!query) return true
  const searchable = [
    item.id,
    item.title,
    item.owner,
    item.doneWhen,
    item.executionStatus.label,
    item.executionStatus.rawValue,
    item.collaborationStage.label,
    item.collaborationStage.rawValue,
    ...item.steps,
  ]
    .flatMap((value) => value ?? [])
    .map(normalizedSearchText)
    .join('\n')
  return searchable.includes(query)
}

function normalizeFilters(filters: Partial<TaskCenterFilters>): TaskCenterFilters {
  const query = normalizedSearchText(typeof filters.query === 'string' ? filters.query : '')
  const collaborationStage = filters.collaborationStage === 'all'
    || STAGE_OPTION_BY_VALUE.has(filters.collaborationStage as TaskStageKey)
    ? filters.collaborationStage ?? 'all'
    : 'all'
  const executionStatus = filters.executionStatus === 'all'
    || STATUS_OPTION_BY_VALUE.has(filters.executionStatus as TaskStatusKey)
    ? filters.executionStatus ?? 'all'
    : 'all'
  return { query, collaborationStage, executionStatus }
}

function emptyStageCounts(): Record<TaskStageKey, number> {
  return {
    discussion: 0,
    execution: 0,
    review: 0,
    blocked: 0,
    completed: 0,
    unknown: 0,
  }
}

function emptyStatusCounts(): Record<TaskStatusKey, number> {
  return {
    created: 0,
    running: 0,
    waiting_external_agent: 0,
    synthesizing: 0,
    completed: 0,
    failed: 0,
    unknown: 0,
  }
}

function buildGroups(items: TaskCenterItem[], stageFilter: TaskCenterFilters['collaborationStage']): TaskCenterGroup[] {
  const options = stageFilter === 'all'
    ? TASK_STAGE_OPTIONS.filter((option) => option.value !== 'unknown'
      || items.some((item) => item.collaborationStage.value === 'unknown'))
    : TASK_STAGE_OPTIONS.filter((option) => option.value === stageFilter)

  return options.map((stage) => ({
    stage,
    items: items.filter((item) => item.collaborationStage.value === stage.value),
  }))
}

export function buildTaskCenterViewModel(
  cards: readonly TaskCard[],
  inputFilters: Partial<TaskCenterFilters> = DEFAULT_TASK_CENTER_FILTERS,
): TaskCenterViewModel {
  const filters = normalizeFilters(inputFilters)
  const allItems = sortedTaskItems(cards)
  const byStage = emptyStageCounts()
  const byExecutionStatus = emptyStatusCounts()

  for (const item of allItems) {
    byStage[item.collaborationStage.value] += 1
    byExecutionStatus[item.executionStatus.value] += 1
  }

  const items = allItems.filter((item) => (
    itemMatchesQuery(item, filters.query)
    && (filters.collaborationStage === 'all' || item.collaborationStage.value === filters.collaborationStage)
    && (filters.executionStatus === 'all' || item.executionStatus.value === filters.executionStatus)
  ))
  const hasActiveFilters = filters.query !== ''
    || filters.collaborationStage !== 'all'
    || filters.executionStatus !== 'all'

  return {
    items,
    groups: buildGroups(items, filters.collaborationStage),
    filters,
    stats: {
      totalVisible: allItems.length,
      filteredVisible: items.length,
      locked: items.filter((item) => item.activeLock !== null).length,
      activeVisible: items.filter((item) => ACTIVE_STATUS_VALUES.has(item.executionStatus.value)).length,
      blockedVisible: items.filter((item) => item.collaborationStage.value === 'blocked').length,
      completedVisible: items.filter((item) => item.executionStatus.value === 'completed').length,
      byStage,
      byExecutionStatus,
    },
    hasActiveFilters,
    emptyReason: allItems.length === 0
      ? 'no-visible-tasks'
      : items.length === 0
        ? 'no-filter-matches'
        : null,
  }
}

export function buildTaskDetailViewModel(detail: TaskDetail): TaskDetailViewModel {
  const timeline = detail.posts
    .map((post, inputIndex) => ({
      item: {
        id: nonEmptyString(post.id) ?? `${post.task_id}-post-${inputIndex + 1}`,
        actor: nonEmptyString(post.actor) ?? '未知参与者',
        title: nonEmptyString(post.title) ?? '未命名动态',
        content: nonEmptyString(post.content) ?? '',
        postType: presentedPostType(post.post_type),
        collaborationStage: presentedStage(post.collaboration_stage),
        publicationStatus: nonEmptyString(post.status) ?? 'unknown',
        owner: nonEmptyString(post.current_owner_label) ?? nonEmptyString(post.current_owner_agent_id),
        doneWhen: nonEmptyString(post.done_when),
        executionLock: post.execution_lock ?? null,
        createdAt: validTimestamp(post.created_at),
        sources: post.sources ?? [],
        post,
      } satisfies TaskTimelineItem,
      inputIndex,
    }))
    .sort((left, right) => {
      const timeDifference = compareTimestamp(left.item.createdAt, right.item.createdAt, 'asc')
      if (timeDifference !== 0) return timeDifference
      return left.inputIndex - right.inputIndex
    })
    .map(({ item }) => item)

  return {
    task: presentTaskCard(detail.task_card, 0),
    timeline,
  }
}
