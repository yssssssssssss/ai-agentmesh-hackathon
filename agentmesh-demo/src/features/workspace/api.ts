import { apiRequest } from '../../api/client'
import type {
  AgentRunResponse,
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

export function streamAgentRun(runId: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const stream = new EventSource(`/api/agent/runs/${pathId(runId)}/events/stream`)
    const timeout = window.setTimeout(async () => {
      stream.close()
      try {
        const current = await workspaceApi.agentRun(runId)
        if (current.item.status !== 'created' && current.item.status !== 'running') {
          resolve()
          return
        }
      } catch {
        // Report the stable timeout below without exposing provider details.
      }
      reject(new Error(`Agent 运行连接超时，可通过运行记录 ${runId} 继续核对状态`))
    }, 300_000)
    const finish = () => {
      window.clearTimeout(timeout)
      stream.close()
      resolve()
    }
    stream.addEventListener('run_completed', finish)
    stream.addEventListener('run_failed', finish)
    stream.addEventListener('run_cancelled', finish)
    stream.addEventListener('approval_requested', finish)
    // EventSource reconnects automatically and sends Last-Event-ID. Do not turn a
    // transient disconnect into a second Agent run.
    stream.onerror = () => undefined
  })
}

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
  startAgentRun: (threadId: string | null, content: string, clientTurnId: string, skillName?: string) =>
    apiRequest<AgentRunResponse>('/api/agent/runs', {
      method: 'POST',
      body: JSON.stringify({
        thread_id: threadId,
        content,
        client_turn_id: clientTurnId,
        skill_name: skillName,
      }),
    }),
  agentRun: (runId: string) => apiRequest<AgentRunResponse>(`/api/agent/runs/${pathId(runId)}`),
  cancelAgentRun: (runId: string) =>
    apiRequest<AgentRunResponse>(`/api/agent/runs/${pathId(runId)}/cancel`, { method: 'POST' }),
  skills: () => apiRequest<SkillsResponse>('/api/chat/skills'),
  skillCatalog: () => apiRequest<SkillsResponse>('/api/skills'),
  updateSkillBinding: (skillId: string, enabled: boolean) =>
    apiRequest<{ item: SkillsResponse['items'][number] }>(`/api/skills/${pathId(skillId)}/binding`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
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
