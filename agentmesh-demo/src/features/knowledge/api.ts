import type { components } from '../../api/generated/schema'
import { apiRequest } from '../../api/client'

export type InboxItem = components['schemas']['InboxItem'] & { allowed_actions: string[] }
export type MemoryItem = components['schemas']['MemoryItemView'] & { allowed_actions: string[] }
export type UserMemoryItem = components['schemas']['UserMemoryItem']
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
  acceptMemory: (itemId: string) =>
    apiRequest<ItemResponse<MemoryItem>>(`/api/memory/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'accepted' }),
    }),
}
