/**
 * AgentMesh 后端 API 客户端。
 *
 * 会话机制:httponly cookie(`agentmesh_session`),`samesite=lax`。
 * 因此前端必须经 vite proxy 以「同源」方式访问后端(见 vite.config.ts),
 * 不能跨端口直连,否则 lax 下不会携带 cookie。
 *
 * 所有响应解包 FastAPI 的包装模型:
 *  - UserResponse    { user }
 *  - ItemsResponse   { items }
 *  - PaginatedResponse { items, total, ... }
 *  - StatusResponse  { status }
 */

const API_PREFIX = '/api'

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    /** FastAPI 的 detail 字段,可能是 string 或校验错误数组 */
    public detail: unknown,
  ) {
    super(`API ${status} ${statusText}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`)
    this.name = 'ApiError'
  }
}

export class UnauthorizedError extends ApiError {
  constructor(detail: unknown) {
    super(401, 'Unauthorized', detail)
    this.name = 'UnauthorizedError'
  }
}

// ---------------------------------------------------------------------------
// 与后端 Pydantic 模型逐字段对应的类型(agentmesh/models.py)
// ---------------------------------------------------------------------------

export type UserRole = 'user' | 'team_lead' | 'admin'
export type Scope = 'private' | 'project' | 'team_candidate' | 'team_accepted'

export type MemorySearchScope = 'auto' | 'personal' | 'project' | 'team'

export type MemoryKind = 'personal' | 'project' | 'team'

export interface User {
  id: string
  workspace_id: string
  default_project_id: string
  name: string
  role: UserRole | string
  status: string
  personal_agent_id: string
  created_at: string
  updated_at: string
}

export interface ChatThread {
  id: string
  workspace_id: string
  project_id: string
  user_id: string
  title: string
  status: string
  created_at: string
  updated_at: string
}

export interface ChatSkill {
  command: string
  title: string
  description: string
  usage: string
  placeholder: string
  aliases: string[]
  requires_input: boolean
  memory_search_scope?: MemorySearchScope | null
}

export type ChatRole = 'user' | 'assistant' | 'system'

export interface Source {
  id: string
  title: string
  source_type: string
  reference: string
  created_at: string
}

export interface RetrievedMemoryEvidence {
  result_id: string
  result_type: string
  memory_kind: MemoryKind
  citation_label: string
  title: string
  summary: string
  rank: number
  scope: Scope
  project_id: string | null
  team_id: string | null
  sources: Source[]
}

export interface MemorySearchTrace {
  requested_scope: MemorySearchScope
  personal_count: number
  project_count: number
  team_count: number
  results: RetrievedMemoryEvidence[]
}

export interface ChatMessage {
  id: string
  thread_id: string
  role: ChatRole
  content: string
  scope: string
  sources: Source[]
  created_at: string
}

export interface ChatTurnTrace {
  id: string
  thread_id: string
  user_message_id: string
  assistant_message_id: string
  task_id: string | null
  intent: string
  source: string
  selected_workflow: string
  persisted: boolean
  llm_used: boolean
  fallback_reason: string | null
  steps: string[]
  sources: Source[]
  memory_search?: MemorySearchTrace | null
  created_at: string
}

export interface ChatResponse {
  thread_id: string
  user_message: ChatMessage
  assistant_message: ChatMessage
  task: unknown | null
  request_post: unknown | null
  evidence_post: unknown | null
  risk_post: unknown | null
  activity_logs: unknown[]
  inbox_items: unknown[]
  memory_items: unknown[]
  user_memory_items: unknown[]
  workflow_trace: unknown | null
  turn_trace: ChatTurnTrace | null
}

export type MemoryLayer = 'short_term' | 'mid_term' | 'long_term'

/** 用户记忆条目(agentmesh/models.py UserMemoryItem)。 */
export interface UserMemoryItem {
  id: string
  user_id: string
  layer: MemoryLayer
  title: string
  summary: string
  source_kind: string
  memory_type: string
  memory_date: string
  sensitivity: string
  scope: string
  workspace_id: string
  project_id: string | null
  source_thread_id: string | null
  source_task_id: string | null
  sources: Source[]
  status: string
  created_at: string
  updated_at: string
}

// 包装模型 --------------------------------------------------------------

interface UserResponse {
  user: User
}

interface ItemsResponse<T = unknown> {
  items: T[]
}

interface PaginatedResponse<T = unknown> {
  items: T[]
  total: number
  page: number
  page_size: number
}

interface StatusResponse {
  status: string
}

// ---------------------------------------------------------------------------
// 底层请求
// ---------------------------------------------------------------------------

type Json = Record<string, unknown> | unknown[] | string | number | boolean | null

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`, {
    credentials: 'same-origin', // 同源 proxy 下携带会话 cookie
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })

  if (res.status === 401) {
    throw new UnauthorizedError(await safeDetail(res))
  }
  if (!res.ok) {
    throw new ApiError(res.status, res.statusText, await safeDetail(res))
  }
  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

async function safeDetail(res: Response): Promise<unknown> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    return body.detail ?? body
  } catch {
    return null
  }
}

function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET' })
}

function post<T>(path: string, body?: Json): Promise<T> {
  return request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
}

function patch<T>(path: string, body?: Json): Promise<T> {
  return request<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) })
}

// ---------------------------------------------------------------------------
// 领域 API —— 按后端路由模块分组,逐页接入时在此扩展
// ---------------------------------------------------------------------------

export const api = {
  auth: {
    me: () => get<UserResponse>('/auth/me').then((r) => r.user),
    login: (userId: string, password: string) =>
      post<UserResponse>('/auth/login', { user_id: userId, password }).then((r) => r.user),
    logout: () => post<StatusResponse>('/auth/logout'),
    oauthStatus: () => get<Record<string, unknown>>('/auth/oauth/status'),
  },
  chat: {
    skills: () => get<ItemsResponse<ChatSkill>>('/chat/skills').then((r) => r.items),
    createThread: (payload: { title: string; project_id?: string }) =>
      post<{ thread: ChatThread }>('/chat/threads', payload).then((r) => r.thread),
    listThreads: () => get<ItemsResponse<ChatThread>>('/chat/threads').then((r) => r.items),
    sendMessage: (content: string, threadId?: string) =>
      post<ChatResponse>('/chat/messages', { content, thread_id: threadId ?? null }),
    threadMessages: (threadId: string) =>
      get<ItemsResponse<ChatMessage>>(`/chat/threads/${encodeURIComponent(threadId)}/messages`).then((r) => r.items),
    threadTraces: (threadId: string) =>
      get<ItemsResponse<ChatTurnTrace>>(`/chat/threads/${encodeURIComponent(threadId)}/turn-traces`).then((r) => r.items),
  },
  agents: {
    bootstrap: () => get<Record<string, unknown>>('/agents/bootstrap'),
    list: () => get<ItemsResponse>('/agents').then((r) => r.items),
    me: () => get<Record<string, unknown>>('/agents/me'),
  },
  memory: {
    list: () => get<ItemsResponse>('/memory').then((r) => r.items),
    user: () => get<ItemsResponse<UserMemoryItem>>('/memory/user').then((r) => r.items),
    overview: () => get<Record<string, unknown>>('/memory/overview'),
    skills: () => get<Record<string, unknown>>('/memory/skills'),
  },
  workspace: {
    activityToday: () =>
      get<{ personal: unknown[]; external: unknown[] }>('/activity/today'),
    search: (q: string) => get<{ results: unknown[] }>(`/search?q=${encodeURIComponent(q)}`),
    projects: () => get<ItemsResponse>('/projects').then((r) => r.items),
  },
  market: {
    board: () => get<Record<string, unknown>>('/market/board'),
    status: () => get<Record<string, unknown>>('/market/status'),
  },
  inbox: {
    list: () => get<ItemsResponse>('/inbox').then((r) => r.items),
    resolve: (itemId: string) => patch<{ item: unknown }>(`/inbox/${itemId}`, { status: 'resolved' }).then((r) => r.item),
  },
  health: {
    status: () => get<{ status: string }>('/health'),
  },
} as const

export { get, post }
export type { ItemsResponse, PaginatedResponse, StatusResponse, UserResponse }
