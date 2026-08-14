/**
 * Collaboration API —— blackboard task-cards, market board, inbox items
 */
import { api, get, type ItemsResponse } from '../../lib/api'

export interface Task {
  id: string
  thread_id: string
  intent: string
  status: string
  collaboration_stage: string
  current_owner_agent_id: string
  current_owner_label: string | null
  execution_lock: string | null
  done_when: string | null
  title: string
  steps: string[]
  created_at: string
  updated_at: string
}

export interface BlackboardPost {
  id: string
  task_id: string
  post_type: string
  actor: string
  title: string
  content: string
  scope: string
  permission: string
  status: string
  sources: unknown[]
  read_by_agents: string[]
  related_post_id: string | null
  created_at: string
  updated_at: string
}

export interface TaskCard {
  task: Task
  latest_post: BlackboardPost
}

export interface InboxItem {
  id: string
  title: string
  summary: string
  item_type: string
  scope: string
  user_id: string
  status: string
  workspace_id: string
  project_id: string
  metadata: Record<string, unknown>
  acknowledged_at: string | null
  snooze_until: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export interface MarketBoard {
  enabled: boolean
  publish_worker: { enabled: boolean; interval_seconds: number; running: boolean; last_run_at: string | null; last_published: number; last_error: string | null }
  scout_worker: { enabled: boolean; interval_seconds: number; running: boolean; last_run_at: string | null; last_triggered: number; last_error: string | null }
  counts: { signals: number; matches: number; consent_grants: number; participants: number }
  signals: unknown[]
  matches: unknown[]
}

export const collaborationApi = {
  taskCards: () => get<ItemsResponse<TaskCard>>('/blackboard/task-cards').then((r) => r.items),
  marketBoard: () => get<MarketBoard>('/market/board'),
  inboxList: () => api.inbox.list() as Promise<InboxItem[]>,
  resolveInboxItem: (itemId: string) =>
    api.inbox.resolve(itemId) as Promise<InboxItem>,
} as const
