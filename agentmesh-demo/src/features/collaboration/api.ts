import type { components } from '../../api/generated/schema'
import { apiRequest } from '../../api/client'

type GeneratedTaskCard = components['schemas']['BlackboardTaskCard']
type GeneratedPost = components['schemas']['BlackboardPost']

export type BlackboardPost = GeneratedPost & { allowed_actions: string[] }
export type TaskCard = Omit<GeneratedTaskCard, 'latest_post'> & {
  latest_post?: BlackboardPost | null
  target_post_id?: string | null
  allowed_actions: string[]
}

export type ReplyPayload = {
  post_type: components['schemas']['BlackboardPostType']
  title: string
  content: string
}

export type HandoffPayload = components['schemas']['BlackboardHandoffRequest']

export interface TaskDetail {
  task_card: TaskCard
  posts: BlackboardPost[]
}

export interface MarketWorkerState {
  enabled: boolean
  running: boolean
  last_run_at: string | null
  last_error: string | null
}

export interface MarketStatus {
  enabled: boolean
  publish_worker: MarketWorkerState
  scout_worker: MarketWorkerState
  counts: {
    signals: number
    matches: number
    consent_grants: number
    participants: number
  }
}

export interface MarketSignal {
  owner_id: string
  owner_name: string
  participating: boolean
  capability: string
  offer: string
  need: string
  created_at: string
}

export interface MarketMatch {
  helper_id: string | null
  helper_name: string | null
  needer_id: string | null
  needer_name: string | null
  status: string | null
  at: string
}

export interface MarketBoard extends MarketStatus {
  signals: MarketSignal[]
  matches: MarketMatch[]
}

interface ItemResponse<T> {
  item: T
}

export const collaborationApi = {
  taskCards: (projectId: string) =>
    apiRequest<{ items: TaskCard[] }>(`/api/blackboard/task-cards?project_id=${encodeURIComponent(projectId)}`),
  taskDetail: (taskId: string) =>
    apiRequest<TaskDetail>(`/api/blackboard/tasks/${encodeURIComponent(taskId)}`),
  marketStatus: () => apiRequest<MarketStatus>('/api/market/status'),
  marketBoard: () => apiRequest<MarketBoard>('/api/market/board'),
  participation: () => apiRequest<components['schemas']['MarketParticipation']>('/api/market/participation'),
  setParticipation: (enabled: boolean) =>
    apiRequest<components['schemas']['MarketParticipation']>('/api/market/participation', {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),
  reply: (postId: string, payload: ReplyPayload) =>
    apiRequest<ItemResponse<BlackboardPost>>(`/api/blackboard/posts/${encodeURIComponent(postId)}/reply`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  lock: (postId: string, ownerAgentId: string) =>
    apiRequest<ItemResponse<BlackboardPost>>(`/api/blackboard/posts/${encodeURIComponent(postId)}/lock`, {
      method: 'POST',
      body: JSON.stringify({ owner_agent_id: ownerAgentId }),
    }),
  unlock: (postId: string) =>
    apiRequest<ItemResponse<BlackboardPost>>(`/api/blackboard/posts/${encodeURIComponent(postId)}/unlock`, {
      method: 'POST',
      body: JSON.stringify({ reason: 'user_requested' }),
    }),
  handoff: (postId: string, payload: HandoffPayload) =>
    apiRequest<ItemResponse<BlackboardPost>>(`/api/blackboard/posts/${encodeURIComponent(postId)}/handoff`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  markRead: (postId: string) =>
    apiRequest<ItemResponse<BlackboardPost>>(`/api/blackboard/posts/${encodeURIComponent(postId)}/read`, {
      method: 'PATCH',
    }),
}
