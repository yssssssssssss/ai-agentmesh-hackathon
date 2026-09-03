import type { components } from '../../api/generated/schema'
import { apiRequest } from '../../api/client'

type GeneratedLegacyMemoryItem = components['schemas']['MemoryItemView']
type GeneratedMemoryEntry = components['schemas']['MemoryEntryViewV1']
type GeneratedUserMemoryItem = components['schemas']['UserMemoryItem']

export type InboxItem = components['schemas']['InboxItem'] & { allowed_actions: string[] }
export type LegacyMemoryItem = Omit<GeneratedLegacyMemoryItem, 'allowed_actions' | 'version'> & {
  allowed_actions: string[]
  version?: number
}
export type MemoryItem = Omit<GeneratedMemoryEntry, 'allowed_actions'> & { allowed_actions: string[] }
export type MemoryPage = Omit<components['schemas']['MemoryPageV1'], 'items'> & { items: MemoryItem[] }
export type MemoryLineage = components['schemas']['MemoryLineageViewV1']
export type MemoryLifecycleAction = components['schemas']['MemoryLifecycleAction']
export interface MemoryGovernanceFilters {
  page: number
  pageSize: number
  status: 'all' | 'disputed' | 'deprecated' | 'expired' | 'archived'
  scope: 'all' | components['schemas']['Scope']
  kind: 'all' | components['schemas']['MemoryEntryKind']
  layer: 'all' | components['schemas']['MemoryLayer']
}
export type UserMemoryItem = Omit<GeneratedUserMemoryItem, 'version'> & { version?: number }
export type MemoryReviewDecision = components['schemas']['MemoryReviewDecisionRequest']['decision']
export type MemoryReviewDecisionResponse = components['schemas']['MemoryReviewDecisionResponseV1']
export interface DocumentRecord {
  id: string
  title: string
  text: string
  file_name: string
  version: number
}

export interface MemoryOverview {
  project_id: string
  sections: {
    short: UserMemoryItem[]
    project: UserMemoryItem[]
    archive: UserMemoryItem[]
    team: LegacyMemoryItem[]
  }
  counts: Record<'short' | 'project' | 'archive' | 'team', number>
}

export type ToolApprovalAction = 'approve' | 'reject'

export interface ToolApprovalResolution {
  item: InboxItem
  run_id: string
  waiting_approval?: boolean
  answer?: string
}

interface ItemResponse<T> {
  item: T
}

export const knowledgeApi = {
  inbox: (includeSnoozed = true) =>
    apiRequest<{ items: InboxItem[] }>(`/api/inbox?include_snoozed=${includeSnoozed}`),
  memory: (projectId: string) => apiRequest<MemoryPage>(
    `/api/memory/entries?project_id=${encodeURIComponent(projectId)}&page_size=100`,
  ),
  governance: (projectId: string, filters: MemoryGovernanceFilters) => {
    const params = new URLSearchParams({
      project_id: projectId,
      include_archived: 'true',
      page: String(filters.page),
      page_size: String(filters.pageSize),
    })
    if (filters.status === 'all') params.set('lifecycle', 'inactive')
    else params.set('status', filters.status)
    if (filters.scope !== 'all') params.set('scope', filters.scope)
    if (filters.kind !== 'all') params.set('kind', filters.kind)
    if (filters.layer !== 'all') params.set('layer', filters.layer)
    return apiRequest<MemoryPage>(`/api/memory/entries?${params.toString()}`)
  },
  memoryLineage: (memoryId: string) => apiRequest<MemoryLineage>(
    `/api/memory/entries/${encodeURIComponent(memoryId)}/lineage`,
  ),
  overview: (projectId: string) =>
    apiRequest<MemoryOverview>(`/api/memory/overview?project_id=${encodeURIComponent(projectId)}`),
  documents: () => apiRequest<{ items: DocumentRecord[] }>('/api/documents'),
  document: (documentId: string) =>
    apiRequest<ItemResponse<DocumentRecord>>(`/api/documents/${encodeURIComponent(documentId)}`),
  updateInbox: (itemId: string, payload: components['schemas']['InboxUpdateRequest']) =>
    apiRequest<ItemResponse<InboxItem>>(`/api/inbox/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  confirmBrief: ({
    itemId,
    text,
    expectedDocumentVersion,
  }: {
    itemId: string
    text: string
    expectedDocumentVersion: number
  }) =>
    apiRequest<{ item: InboxItem; document: DocumentRecord; memory_item: LegacyMemoryItem }>(
      `/api/inbox/${encodeURIComponent(itemId)}/confirm-brief`,
      {
        method: 'POST',
        body: JSON.stringify({ text, expected_document_version: expectedDocumentVersion }),
      },
    ),
  resolveInjection: (itemId: string, action: 'release' | 'discard') =>
    apiRequest<{ item: InboxItem }>(
      `/api/inbox/${encodeURIComponent(itemId)}/resolve-injection-review?action=${action}`,
      { method: 'POST' },
    ),
  resolveToolApproval: (itemId: string, callId: string, action: ToolApprovalAction) =>
    apiRequest<ToolApprovalResolution>(
      `/api/inbox/${encodeURIComponent(itemId)}/resolve-tool-approval?action=${action}&call_id=${encodeURIComponent(callId)}`,
      { method: 'POST' },
    ),
  acceptMemory: (itemId: string) =>
    apiRequest<ItemResponse<LegacyMemoryItem>>(`/api/memory/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'accepted' }),
    }),
  createMemoryRevision: ({
    memoryId,
    payload,
  }: {
    memoryId: string
    payload: components['schemas']['MemoryRevisionRequest']
  }) => apiRequest<components['schemas']['MemoryRevisionResponseV1']>(
    `/api/memory/${encodeURIComponent(memoryId)}/revisions`,
    { method: 'POST', body: JSON.stringify(payload) },
  ),
  transitionMemory: ({
    memoryId,
    payload,
  }: {
    memoryId: string
    payload: components['schemas']['MemoryTransitionRequest']
  }) => apiRequest<components['schemas']['MemoryTransitionResponseV1']>(
    `/api/memory/${encodeURIComponent(memoryId)}/transitions`,
    { method: 'POST', body: JSON.stringify(payload) },
  ),
  decideMemoryReview: ({
    reviewId,
    commandId,
    expectedMemoryVersion,
    expectedReviewVersion,
    decision,
    decisionNote,
  }: {
    reviewId: string
    commandId: string
    expectedMemoryVersion: number
    expectedReviewVersion: number
    decision: MemoryReviewDecision
    decisionNote: string | null
  }) => apiRequest<MemoryReviewDecisionResponse>(
    `/api/memory-reviews/${encodeURIComponent(reviewId)}/decisions`,
    {
      method: 'POST',
      body: JSON.stringify({
        command_id: commandId,
        expected_memory_version: expectedMemoryVersion,
        expected_review_version: expectedReviewVersion,
        decision,
        decision_note: decisionNote,
      }),
    },
  ),
}
