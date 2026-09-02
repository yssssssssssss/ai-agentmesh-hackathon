import type { components } from '../../api/generated/schema'
import { apiRequest } from '../../api/client'

type GeneratedMemoryItem = components['schemas']['MemoryItemView']
type GeneratedUserMemoryItem = components['schemas']['UserMemoryItem']

export type InboxItem = components['schemas']['InboxItem'] & { allowed_actions: string[] }
export type MemoryItem = Omit<GeneratedMemoryItem, 'allowed_actions' | 'version'> & {
  allowed_actions: string[]
  version?: number
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
    team: MemoryItem[]
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
  memory: (projectId: string) => apiRequest<{ items: MemoryItem[] }>(`/api/memory?project_id=${encodeURIComponent(projectId)}`),
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
    apiRequest<{ item: InboxItem; document: DocumentRecord; memory_item: MemoryItem }>(
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
    apiRequest<ItemResponse<MemoryItem>>(`/api/memory/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'accepted' }),
    }),
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
