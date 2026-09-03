import {
  KNOWLEDGE_ASSETS,
  SHARE_EVENTS,
  type KnowledgeCitation,
  type ShareEvent,
  type UsageEventType,
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
  DocumentRecord,
  InboxItem,
  MemoryItem,
  MemoryOverview,
  MemoryPage,
  UserMemoryItem,
} from './api'

export interface KnowledgeResource<T> {
  state: PresentationState
  data?: T
  error?: string
}

export interface KnowledgeUsageRecord {
  id: string
  type: UsageEventType
  knowledgeId: string
  knowledgeTitle: string
  actor: string
  actorRole?: string
  project: string
  purpose?: string
  time: string
  statusLabel: string
  tone: ShareEvent['tone']
  description: string
  detail?: string
  primaryAction: string
  needsAction?: boolean
  allowed_actions: string[]
}

export interface KnowledgeAssetView {
  kind: 'user_memory' | 'accepted_memory' | 'document'
  id: PresentedValue<string>
  title: PresentedValue<string>
  conclusion: PresentedValue<string>
  type: PresentedValue<string>
  scope: PresentedValue<string>
  sourceProject: PresentedValue<string>
  contributor: PresentedValue<string>
  verified: PresentedValue<string>
  visibility: PresentedValue<string>
  citedBy: PresentedValue<number>
  updated: PresentedValue<string>
  hasNewFeedback: PresentedValue<boolean>
  problem: PresentedValue<string>
  evidence: PresentedValue<string[]>
  limitation: PresentedValue<string>
  citations: PresentedValue<KnowledgeCitation[]>
  allowedActions: PresentedValue<string[]>
  version: PresentedValue<number | null>
  status: PresentedValue<string>
  memoryKind: PresentedValue<string | null>
  supersedesMemoryId: PresentedValue<string | null>
  contentHash: PresentedValue<string | null>
  archivedFromStatus: PresentedValue<string | null>
  sourceTaskId: PresentedValue<string | null>
  sourceRunId: PresentedValue<string | null>
  sourceReviewId: PresentedValue<string | null>
}

export interface PendingKnowledgeView {
  kind: 'inbox' | 'team_candidate'
  id: PresentedValue<string>
  title: PresentedValue<string>
  summary: PresentedValue<string>
  itemType: PresentedValue<string>
  memoryType: PresentedValue<string>
  scope: PresentedValue<string>
  status: PresentedValue<string>
  sourceProject: PresentedValue<string>
  projectId: PresentedValue<string | null>
  createdAt: PresentedValue<string>
  updatedAt: PresentedValue<string>
  documentId: PresentedValue<string | null>
  documentVersion: PresentedValue<number | null>
  taskId: PresentedValue<string | null>
  memoryId: PresentedValue<string | null>
  memoryVersion: PresentedValue<number | null>
  memoryReview: PresentedValue<MemoryItem['memory_review'] | null>
  toolCalls: PresentedValue<ToolApprovalCall[]>
  allowedActions: PresentedValue<string[]>
}

export interface ToolApprovalCall {
  callId: string
  name: string
  argumentKeys: string[]
}

export interface KnowledgeUsageView {
  kind: 'accepted_memory' | 'reuse_event'
  id: PresentedValue<string>
  type: PresentedValue<UsageEventType>
  knowledgeId: PresentedValue<string>
  knowledgeTitle: PresentedValue<string>
  actor: PresentedValue<string>
  actorRole: PresentedValue<string>
  project: PresentedValue<string>
  purpose: PresentedValue<string>
  time: PresentedValue<string>
  statusLabel: PresentedValue<string>
  tone: PresentedValue<ShareEvent['tone']>
  description: PresentedValue<string>
  detail: PresentedValue<string>
  primaryAction: PresentedValue<string>
  needsAction: PresentedValue<boolean>
  allowedActions: PresentedValue<string[]>
}

interface KnowledgeViewModelInput {
  projectId: string
  projectName: string
  inbox: KnowledgeResource<{ items: InboxItem[] }>
  memory: KnowledgeResource<{ items: MemoryItem[] }>
  governance: KnowledgeResource<MemoryPage>
  overview: KnowledgeResource<MemoryOverview>
  documents: KnowledgeResource<{ items: DocumentRecord[] }>
  usage: KnowledgeResource<{ items: KnowledgeUsageRecord[] }>
}

export interface KnowledgeViewModel {
  tabs: Array<{
    key: 'assets' | 'pending' | 'governance' | 'shared'
    label: string
    count: PresentedValue<number>
  }>
  assets: PresentedModule<{ items: KnowledgeAssetView[] }>
  pending: PresentedModule<{ items: PendingKnowledgeView[] }>
  governance: PresentedModule<{ items: KnowledgeAssetView[] }>
  usage: PresentedModule<{ items: KnowledgeUsageView[] }>
}

const referenceAssets = new Map(KNOWLEDGE_ASSETS.map((asset) => [asset.id, asset]))

function referenceValue<T>(value: T, field: string): PresentedValue<T> {
  return presentedValue(value, 'M', `${field} 暂无服务端字段，使用参考展示数据。`)
}

function timeValue(value: string | undefined, field: string): PresentedValue<string> {
  if (value) return presentedValue(value, 'T')
  return referenceValue('时间未提供', field)
}

function projectLabel(
  projectId: string | null | undefined,
  input: Pick<KnowledgeViewModelInput, 'projectId' | 'projectName'>,
) {
  if (projectId === input.projectId) return input.projectName
  return projectId || '未关联项目'
}

function toolApprovalCalls(item: InboxItem): ToolApprovalCall[] {
  if (item.item_type !== 'sdk_tool_approval') return []
  const raw = item.metadata?.interruptions
  if (!raw) return []
  try {
    const interruptions: unknown = JSON.parse(raw)
    if (!Array.isArray(interruptions)) return []
    const seen = new Set<string>()
    return interruptions.flatMap((interruption) => {
      if (!interruption || typeof interruption !== 'object') return []
      const callId = 'call_id' in interruption && typeof interruption.call_id === 'string'
        ? interruption.call_id.trim()
        : ''
      if (!callId || seen.has(callId)) return []
      seen.add(callId)
      const name = 'name' in interruption && typeof interruption.name === 'string'
        ? interruption.name.trim() || 'unknown_tool'
        : 'unknown_tool'
      const argumentKeys = 'argument_keys' in interruption && typeof interruption.argument_keys === 'string'
        ? interruption.argument_keys.split(',').map((key: string) => key.trim()).filter(Boolean)
        : []
      return [{ callId, name, argumentKeys }]
    })
  } catch {
    return []
  }
}

function userMemoryAsset(item: UserMemoryItem, input: KnowledgeViewModelInput): KnowledgeAssetView {
  const reference = referenceAssets.get(item.id ?? '')
  const governed = item.provenance != null
  return {
    kind: 'user_memory',
    id: presentedValue(item.id ?? item.title, 'T'),
    title: presentedValue(item.title, 'T'),
    conclusion: presentedValue(item.summary, 'T'),
    type: presentedValue(item.memory_type, 'T'),
    scope: referenceValue(reference?.scope ?? '未提供适用范围', '适用范围'),
    sourceProject: presentedValue(projectLabel(item.project_id, input), 'T'),
    contributor: governed
      ? presentedValue(item.user_id, 'T')
      : referenceValue(reference?.contributor ?? '未提供贡献者', '贡献者'),
    verified: presentedValue(item.status, 'T'),
    visibility: presentedValue(item.scope === 'project' ? 'project' : 'private', 'T'),
    citedBy: referenceValue(reference?.citedBy ?? 0, '引用次数'),
    updated: timeValue(item.updated_at ?? item.created_at, '更新时间'),
    hasNewFeedback: referenceValue(reference?.hasNewFeedback ?? false, '反馈状态'),
    problem: referenceValue(reference?.problem ?? '', '问题背景'),
    evidence: governed
      ? presentedValue(item.provenance?.artifact_ids ?? [], 'T')
      : referenceValue([...(reference?.evidence ?? [])], '形成依据'),
    limitation: referenceValue(reference?.limitation ?? '', '限制条件'),
    citations: referenceValue((reference?.citations ?? []).map((citation) => ({ ...citation })), '引用记录'),
    allowedActions: presentedValue([], 'T'),
    version: governed ? presentedValue(item.version ?? 1, 'T') : referenceValue(null, '版本'),
    status: presentedValue(item.status, 'T'),
    memoryKind: presentedValue(governed ? 'personal' : null, 'T'),
    supersedesMemoryId: presentedValue(item.supersedes_memory_id ?? null, 'T'),
    contentHash: presentedValue(null, 'T'),
    archivedFromStatus: presentedValue(null, 'T'),
    sourceTaskId: presentedValue(item.provenance?.task_id ?? null, 'T'),
    sourceRunId: presentedValue(item.provenance?.run_id ?? null, 'T'),
    sourceReviewId: presentedValue(item.provenance?.review_id ?? null, 'T'),
  }
}

export function memoryEntryAsset(
  item: MemoryItem,
  input: Pick<KnowledgeViewModelInput, 'projectId' | 'projectName'>,
): KnowledgeAssetView {
  const reference = referenceAssets.get(item.id ?? '')
  const governed = item.provenance != null
  return {
    kind: 'accepted_memory',
    id: presentedValue(item.id ?? item.title, 'T'),
    title: presentedValue(item.title, 'T'),
    conclusion: presentedValue(item.summary, 'T'),
    type: presentedValue(item.memory_type, 'T'),
    scope: referenceValue(reference?.scope ?? '未提供适用范围', '适用范围'),
    sourceProject: presentedValue(projectLabel(item.project_id, input), 'T'),
    contributor: governed
      ? presentedValue(item.owner_user_id ?? '未记录贡献者', 'T')
      : referenceValue(reference?.contributor ?? '未提供贡献者', '贡献者'),
    verified: presentedValue(item.status, 'T'),
    visibility: presentedValue(
      item.scope === 'team_accepted' ? 'team' : item.scope === 'team_candidate' ? 'team_candidate' : item.scope,
      'T',
    ),
    citedBy: referenceValue(reference?.citedBy ?? 0, '引用次数'),
    updated: timeValue(item.updated_at ?? item.created_at, '更新时间'),
    hasNewFeedback: referenceValue(reference?.hasNewFeedback ?? false, '反馈状态'),
    problem: referenceValue(reference?.problem ?? '', '问题背景'),
    evidence: governed
      ? presentedValue(item.provenance?.artifact_ids ?? [], 'T')
      : referenceValue([...(reference?.evidence ?? [])], '形成依据'),
    limitation: referenceValue(reference?.limitation ?? '', '限制条件'),
    citations: referenceValue((reference?.citations ?? []).map((citation) => ({ ...citation })), '引用记录'),
    allowedActions: presentedValue([...item.allowed_actions], 'T'),
    version: presentedValue(item.version, 'T'),
    status: presentedValue(item.status, 'T'),
    memoryKind: presentedValue(item.kind, 'T'),
    supersedesMemoryId: presentedValue(item.supersedes_memory_id ?? null, 'T'),
    contentHash: presentedValue(item.content_hash ?? null, 'T'),
    archivedFromStatus: presentedValue(item.archived_from_status ?? null, 'T'),
    sourceTaskId: presentedValue(item.provenance?.task_id ?? null, 'T'),
    sourceRunId: presentedValue(item.provenance?.run_id ?? null, 'T'),
    sourceReviewId: presentedValue(item.provenance?.review_id ?? null, 'T'),
  }
}

function documentAsset(document: DocumentRecord): KnowledgeAssetView {
  return {
    kind: 'document',
    id: presentedValue(document.id, 'T'),
    title: presentedValue(document.title, 'T'),
    conclusion: presentedValue(document.text, 'T'),
    type: referenceValue('project_experience', '知识类型'),
    scope: referenceValue('文档正文', '适用范围'),
    sourceProject: presentedValue(document.file_name, 'T'),
    contributor: referenceValue('未提供贡献者', '贡献者'),
    verified: presentedValue(`文档 v${document.version}`, 'T'),
    visibility: referenceValue('project', '可见范围'),
    citedBy: referenceValue(0, '引用次数'),
    updated: referenceValue('时间未提供', '更新时间'),
    hasNewFeedback: referenceValue(false, '反馈状态'),
    problem: referenceValue('', '问题背景'),
    evidence: referenceValue([], '形成依据'),
    limitation: referenceValue('', '限制条件'),
    citations: referenceValue([], '引用记录'),
    allowedActions: presentedValue([], 'T'),
    version: presentedValue(document.version, 'T'),
    status: presentedValue('document', 'T'),
    memoryKind: presentedValue(null, 'T'),
    supersedesMemoryId: presentedValue(null, 'T'),
    contentHash: presentedValue(null, 'T'),
    archivedFromStatus: presentedValue(null, 'T'),
    sourceTaskId: presentedValue(null, 'T'),
    sourceRunId: presentedValue(null, 'T'),
    sourceReviewId: presentedValue(null, 'T'),
  }
}

function pendingInbox(
  item: InboxItem,
  input: KnowledgeViewModelInput,
  documentsById: ReadonlyMap<string, DocumentRecord>,
): PendingKnowledgeView {
  const documentId = item.metadata?.document_id || null
  const documentVersion = documentId ? documentsById.get(documentId)?.version ?? null : null
  return {
    kind: 'inbox',
    id: presentedValue(item.id ?? item.title, 'T'),
    title: presentedValue(item.title, 'T'),
    summary: presentedValue(item.summary, 'T'),
    itemType: presentedValue(item.item_type, 'T'),
    memoryType: presentedValue(String(item.metadata?.memory_type ?? item.item_type), 'T'),
    scope: presentedValue(item.scope, 'T'),
    status: presentedValue(item.status, 'T'),
    sourceProject: presentedValue(projectLabel(item.project_id, input), 'T'),
    projectId: presentedValue(item.project_id ?? null, 'T'),
    createdAt: timeValue(item.created_at, '形成时间'),
    updatedAt: timeValue(item.updated_at ?? item.created_at, '更新时间'),
    documentId: presentedValue(documentId, 'T'),
    documentVersion: presentedValue(documentVersion, 'T'),
    taskId: presentedValue(item.metadata?.task_id || null, 'T'),
    memoryId: presentedValue(item.metadata?.memory_id || null, 'T'),
    memoryVersion: presentedValue(null, 'T'),
    memoryReview: presentedValue(null, 'T'),
    toolCalls: presentedValue(toolApprovalCalls(item), 'T'),
    allowedActions: presentedValue([...item.allowed_actions], 'T'),
  }
}

function pendingCandidate(item: MemoryItem, input: KnowledgeViewModelInput): PendingKnowledgeView {
  return {
    kind: 'team_candidate',
    id: presentedValue(item.id ?? item.title, 'T'),
    title: presentedValue(item.title, 'T'),
    summary: presentedValue(item.summary, 'T'),
    itemType: presentedValue('team_candidate', 'T'),
    memoryType: presentedValue(item.memory_type, 'T'),
    scope: presentedValue(item.scope, 'T'),
    status: presentedValue(item.status, 'T'),
    sourceProject: presentedValue(projectLabel(item.project_id, input), 'T'),
    projectId: presentedValue(item.project_id ?? null, 'T'),
    createdAt: timeValue(item.created_at, '形成时间'),
    updatedAt: timeValue(item.updated_at, '更新时间'),
    documentId: presentedValue(null, 'T'),
    documentVersion: presentedValue(null, 'T'),
    taskId: presentedValue(item.provenance?.task_id ?? null, 'T'),
    memoryId: presentedValue(item.id ?? null, 'T'),
    memoryVersion: presentedValue(item.version ?? 1, 'T'),
    memoryReview: presentedValue(item.memory_review ?? null, 'T'),
    toolCalls: presentedValue([], 'T'),
    allowedActions: presentedValue([...item.allowed_actions], 'T'),
  }
}

function acceptedMemoryUsage(item: MemoryItem, input: KnowledgeViewModelInput): KnowledgeUsageView {
  const id = item.id ?? item.title
  return {
    kind: 'accepted_memory',
    id: presentedValue(id, 'T'),
    type: presentedValue('shared', 'T'),
    knowledgeId: presentedValue(id, 'T'),
    knowledgeTitle: presentedValue(item.title, 'T'),
    actor: presentedValue('当前项目团队', 'T'),
    actorRole: presentedValue('知识维护者', 'T'),
    project: presentedValue(projectLabel(item.project_id, input), 'T'),
    purpose: presentedValue(item.memory_type, 'T'),
    time: timeValue(item.created_at, '共享时间'),
    statusLabel: presentedValue(item.status === 'accepted' ? '已接受' : item.status, 'T'),
    tone: presentedValue('collab', 'T'),
    description: presentedValue(item.summary, 'T'),
    detail: presentedValue('', 'T'),
    primaryAction: presentedValue(item.allowed_actions.includes('read') ? '查看知识详情' : '无可用操作', 'T'),
    needsAction: presentedValue(false, 'T'),
    allowedActions: presentedValue([...item.allowed_actions], 'T'),
  }
}

function realUsageEvent(event: KnowledgeUsageRecord): KnowledgeUsageView {
  return {
    kind: 'reuse_event',
    id: presentedValue(event.id, 'T'),
    type: presentedValue(event.type, 'T'),
    knowledgeId: presentedValue(event.knowledgeId, 'T'),
    knowledgeTitle: presentedValue(event.knowledgeTitle, 'T'),
    actor: presentedValue(event.actor, 'T'),
    actorRole: presentedValue(event.actorRole ?? '', 'T'),
    project: presentedValue(event.project, 'T'),
    purpose: presentedValue(event.purpose ?? '', 'T'),
    time: presentedValue(event.time, 'T'),
    statusLabel: presentedValue(event.statusLabel, 'T'),
    tone: presentedValue(event.tone, 'T'),
    description: presentedValue(event.description, 'T'),
    detail: presentedValue(event.detail ?? '', 'T'),
    primaryAction: presentedValue(event.primaryAction, 'T'),
    needsAction: presentedValue(event.needsAction ?? false, 'T'),
    allowedActions: presentedValue([...event.allowed_actions], 'T'),
  }
}

function mockUsageEvent(event: ShareEvent): KnowledgeUsageView {
  return {
    kind: 'reuse_event',
    id: referenceValue(event.id, '复用事件'),
    type: referenceValue(event.type, '事件类型'),
    knowledgeId: referenceValue(event.knowledgeId, '知识标识'),
    knowledgeTitle: referenceValue(event.knowledgeTitle, '知识标题'),
    actor: referenceValue(event.actor, '使用者'),
    actorRole: referenceValue(event.actorRole ?? '', '使用者角色'),
    project: referenceValue(event.project, '使用项目'),
    purpose: referenceValue(event.purpose ?? '', '使用目的'),
    time: referenceValue(event.time, '事件时间'),
    statusLabel: referenceValue(event.statusLabel, '事件状态'),
    tone: referenceValue(event.tone, '事件语义色'),
    description: referenceValue(event.description, '事件说明'),
    detail: referenceValue(event.detail ?? '', '事件详情'),
    primaryAction: referenceValue(event.primaryAction, '参考操作'),
    needsAction: referenceValue(event.needsAction ?? false, '待办状态'),
    allowedActions: referenceValue([], '参考事件不提供真实操作。'),
  }
}

function assetValues(asset: KnowledgeAssetView): PresentedValue<unknown>[] {
  return [
    asset.id,
    asset.title,
    asset.conclusion,
    asset.type,
    asset.scope,
    asset.sourceProject,
    asset.contributor,
    asset.verified,
    asset.visibility,
    asset.citedBy,
    asset.updated,
    asset.hasNewFeedback,
    asset.problem,
    asset.evidence,
    asset.limitation,
    asset.citations,
    asset.allowedActions,
    asset.version,
    asset.status,
    asset.memoryKind,
    asset.supersedesMemoryId,
    asset.contentHash,
    asset.archivedFromStatus,
    asset.sourceTaskId,
    asset.sourceRunId,
    asset.sourceReviewId,
  ]
}

function pendingValues(item: PendingKnowledgeView): PresentedValue<unknown>[] {
  return [
    item.id,
    item.title,
    item.summary,
    item.itemType,
    item.memoryType,
    item.scope,
    item.status,
    item.sourceProject,
    item.createdAt,
    item.updatedAt,
    item.documentId,
    item.documentVersion,
    item.toolCalls,
    item.allowedActions,
  ]
}

function usageValues(item: KnowledgeUsageView): PresentedValue<unknown>[] {
  return [
    item.id,
    item.type,
    item.knowledgeId,
    item.knowledgeTitle,
    item.actor,
    item.actorRole,
    item.project,
    item.purpose,
    item.time,
    item.statusLabel,
    item.tone,
    item.description,
    item.detail,
    item.primaryAction,
    item.needsAction,
    item.allowedActions,
  ]
}

function resourceError(resources: KnowledgeResource<unknown>[]): string | null {
  for (const resource of resources) {
    if (resource.state === 'forbidden') return resource.error ?? '没有查看权限'
    if (resource.state === 'error') return resource.error ?? '数据加载失败'
  }
  return null
}

function isLoading(resources: KnowledgeResource<unknown>[]) {
  return resources.some((resource) => resource.state === 'loading')
}

function uniqueById<T extends { id?: string | null; title: string }>(items: T[]) {
  const seen = new Set<string>()
  return items.filter((item) => {
    const id = item.id ?? item.title
    if (seen.has(id)) return false
    seen.add(id)
    return true
  })
}

export function buildKnowledgeViewModel(input: KnowledgeViewModelInput): KnowledgeViewModel {
  const userMemories = input.overview.state === 'available'
    ? uniqueById([
        ...(input.overview.data?.sections.short ?? []),
        ...(input.overview.data?.sections.project ?? []),
        ...(input.overview.data?.sections.archive ?? []),
      ])
    : []
  const teamMemories = input.memory.state === 'available'
    ? input.memory.data?.items ?? []
    : []
  const projectTeamMemories = uniqueById(
    teamMemories.filter((item) => !item.project_id || item.project_id === input.projectId),
  )
  const acceptedMemories = projectTeamMemories.filter(
    (item) => item.scope === 'team_accepted' && item.status === 'accepted',
  )
  const candidates = projectTeamMemories.filter(
    (item) => item.scope === 'team_candidate' && item.status === 'proposed',
  )
  const governanceMemories = input.governance.state === 'available'
    ? input.governance.data?.items ?? []
    : []
  const documents = input.documents.state === 'available' ? input.documents.data?.items ?? [] : []
  const documentsById = new Map(documents.map((document) => [document.id, document]))
  const assets = [
    ...userMemories.map((item) => userMemoryAsset(item, input)),
    ...acceptedMemories.map((item) => memoryEntryAsset(item, input)),
    ...documents.map(documentAsset),
  ]
  const assetResources = [input.overview, input.memory, input.documents]
  const assetsModule = presentedModule(
    { items: assets },
    assets.flatMap(assetValues),
    {
      missingFields: assets.length > 0
        ? ['适用范围', '贡献者', '引用次数', '反馈状态', '问题背景', '形成依据', '限制条件', '引用记录']
        : [],
      loading: isLoading(assetResources),
      error: resourceError(assetResources),
    },
  )

  const inboxItems = input.inbox.state === 'available'
    ? (input.inbox.data?.items ?? []).filter((item) => item.status !== 'resolved')
    : []
  const pendingItems = [
    ...inboxItems.map((item) => pendingInbox(item, input, documentsById)),
    ...candidates.map((item) => pendingCandidate(item, input)),
  ]
  const pendingResources = [input.inbox, input.memory, input.documents]
  const pendingModule = presentedModule(
    { items: pendingItems },
    pendingItems.flatMap(pendingValues),
    {
      loading: isLoading(pendingResources),
      error: resourceError(pendingResources),
    },
  )

  const governanceItems = governanceMemories.map((item) => memoryEntryAsset(item, input))
  const governanceModule = presentedModule(
    { items: governanceItems },
    governanceItems.flatMap(assetValues),
    {
      loading: input.governance.state === 'loading',
      error: resourceError([input.governance]),
    },
  )

  const acceptedUsage = acceptedMemories.map((item) => acceptedMemoryUsage(item, input))
  const realEvents = input.usage.state === 'available'
    ? (input.usage.data?.items ?? []).map(realUsageEvent)
    : []
  const fallbackEvents = canUseMockFallback(input.usage.state)
    ? SHARE_EVENTS.map(mockUsageEvent)
    : []
  const usageItems = [...acceptedUsage, ...realEvents, ...fallbackEvents]
  const usageResources = [input.memory, input.usage]
  const usageModule = presentedModule(
    { items: usageItems },
    usageItems.flatMap(usageValues),
    {
      missingFields: fallbackEvents.length > 0 ? ['复用与反馈时间线'] : [],
      loading: isLoading(usageResources),
      error: resourceError(usageResources),
    },
  )

  const usageCountSource = usageItems.some((item) => item.id.source === 'M') ? 'M' : 'T'
  return {
    tabs: [
      { key: 'assets', label: '已沉淀知识', count: presentedValue(assets.length, 'T') },
      { key: 'pending', label: '待我确认', count: presentedValue(pendingItems.length, 'T') },
      {
        key: 'governance',
        label: '治理历史',
        count: presentedValue(input.governance.data?.total ?? governanceItems.length, 'T'),
      },
      { key: 'shared', label: '使用与反馈', count: presentedValue(usageItems.length, usageCountSource) },
    ],
    assets: assetsModule,
    pending: pendingModule,
    governance: governanceModule,
    usage: usageModule,
  }
}
