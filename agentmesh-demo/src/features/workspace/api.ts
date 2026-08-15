import { apiRequest } from '../../api/client'
import type {
  ChatResponse,
  ChatTurnReceipt,
  DocumentJobResponse,
  DocumentJobsResponse,
  DocumentResponse,
  SearchResponse,
  SkillsResponse,
  ThreadDetailResponse,
  ThreadListResponse,
  UploadResponse,
  WorkspaceScope,
} from './types'

const pathId = (value: string) => encodeURIComponent(value)

export const workspaceApi = {
  threads: () => apiRequest<ThreadListResponse>('/api/chat/threads'),
  thread: (threadId: string) => apiRequest<ThreadDetailResponse>(`/api/chat/threads/${pathId(threadId)}`),
  sendMessage: (threadId: string | null, content: string, clientTurnId: string) =>
    apiRequest<ChatResponse>('/api/chat/messages', {
      method: 'POST',
      body: JSON.stringify({ thread_id: threadId, content, client_turn_id: clientTurnId }),
    }),
  turnReceipt: (clientTurnId: string) =>
    apiRequest<ChatTurnReceipt>(`/api/chat/messages/receipts/${pathId(clientTurnId)}`),
  skills: () => apiRequest<SkillsResponse>('/api/chat/skills'),
  upload: (file: File) => {
    const body = new FormData()
    body.set('file', file)
    return apiRequest<UploadResponse>('/api/documents/upload', { method: 'POST', body })
  },
  jobs: () => apiRequest<DocumentJobsResponse>('/api/documents/jobs'),
  job: (jobId: string) => apiRequest<DocumentJobResponse>(`/api/documents/jobs/${pathId(jobId)}`),
  document: (documentId: string) => apiRequest<DocumentResponse>(`/api/documents/${pathId(documentId)}`),
  search: (scope: WorkspaceScope, query: string) => {
    const params = new URLSearchParams({
      q: query,
      workspace_id: scope.workspaceId,
      project_id: scope.projectId,
      visibility: 'personal',
    })
    return apiRequest<SearchResponse>(`/api/search?${params.toString()}`)
  },
}
