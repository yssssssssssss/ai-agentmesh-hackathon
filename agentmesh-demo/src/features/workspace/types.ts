import type { components } from '../../api/generated/schema'

export type WorkspaceScope = {
  userId: string
  workspaceId: string
  projectId: string
}

export type ChatThread = components['schemas']['ChatThread']
export type Source = components['schemas']['Source']
export type SearchResult = components['schemas']['SearchResult']
export type ChatWorkflowTrace = Omit<components['schemas']['ChatWorkflowTrace'], 'provider'> & {
  requested_provider?: string | null
  actual_provider?: string | null
  requested_model?: string | null
  actual_model?: string | null
  provider_mode?: 'real' | 'fallback' | null
  latency_ms?: number | null
  model_fallback_reason?: string | null
}
export type ChatMessage = Omit<components['schemas']['ChatMessage'], 'id' | 'workflow_trace'> & {
  id: string
  workflow_trace?: ChatWorkflowTrace | null
}
export type MemorySearchScope = 'auto' | 'personal' | 'project' | 'team'
export type MemoryKind = 'personal' | 'project' | 'team'
export type RetrievedMemoryEvidence = {
  result_id: string
  result_type: string
  memory_kind: MemoryKind
  citation_label: string
  title: string
  summary: string
  rank: number
  scope: components['schemas']['Scope']
  project_id?: string | null
  team_id?: string | null
  sources: Source[]
}
export type MemorySearchTrace = {
  requested_scope: MemorySearchScope
  personal_count: number
  project_count: number
  team_count: number
  results: RetrievedMemoryEvidence[]
}
export type ChatTurnTrace = {
  id: string
  thread_id: string
  user_message_id: string
  assistant_message_id: string
  task_id?: string | null
  intent: components['schemas']['Intent']
  source: string
  selected_workflow: string
  persisted: boolean
  llm_used: boolean
  fallback_reason?: string | null
  steps: string[]
  sources: Source[]
  memory_search?: MemorySearchTrace | null
  created_at: string
}
export type ChatResponse = Omit<components['schemas']['ChatResponse'], 'user_message' | 'assistant_message'> & {
  user_message: ChatMessage
  assistant_message: ChatMessage
  workflow_trace?: ChatWorkflowTrace | null
  turn_trace?: ChatTurnTrace | null
}

export type AgentRunStatus = components['schemas']['AgentRunStatus']
export type AgentRun = Omit<components['schemas']['AgentRun'], 'id'> & { id: string }
export type AgentRunEvent = components['schemas']['AgentRunEvent']
export type AgentRunResponse = { item: AgentRun }
export type AgentRunEventsResponse = components['schemas']['AgentRunEventsResponse']
export type ResearchRunProjection = components['schemas']['ResearchRunProjection']
export type ResearchCommandResponse = components['schemas']['ResearchCommandResponse']
export type ResearchConfirmPlanRequest = components['schemas']['ResearchConfirmPlanRequest']
export type ResearchExecuteRequest = components['schemas']['ResearchExecuteRequest']
export type ResearchRecoverRequest = components['schemas']['ResearchRecoverRequest']
export type SkillCandidate = components['schemas']['SkillCandidate']
export type SkillRecommendationRequest = components['schemas']['SkillRecommendationRequest']
export type SkillRecommendationResponse = components['schemas']['SkillRecommendationResponse']
export type SkillPlan = components['schemas']['SkillPlan']
export type SkillPlanNode = components['schemas']['SkillPlanNode']
export type SkillPlanDetailResponse = components['schemas']['SkillPlanDetailResponse']
export type SkillPlanUpdateRequest = components['schemas']['SkillPlanUpdateRequest']
export type SkillPlanVersionRequest = components['schemas']['SkillPlanVersionRequest']
export type SkillPlanTransitionResponse = components['schemas']['SkillPlanTransitionResponse']
export type SkillNodeResult = components['schemas']['SkillNodeResult']
export type SkillResultSource = components['schemas']['SkillResultSource']
export type SkillSynthesisResult = components['schemas']['SkillSynthesisResult']

export type ChatTurnReceipt = {
  client_turn_id: string
  status: 'processing' | 'completed' | 'failed'
  thread_id: string
  response?: ChatResponse | null
}

export type ThreadListResponse = { items: ChatThread[] }
export type ThreadDetailResponse = {
  thread: ChatThread
  messages: ChatMessage[]
  turn_traces: ChatTurnTrace[]
}
export type Skill = components['schemas']['SkillCatalogItem']
export type SkillsResponse = components['schemas']['SkillCatalogResponse']

export type DocumentRecord = {
  id: string
  title: string
  file_name: string
  content_type: string
  text: string
  source: Source
  workspace_id: string
  project_id: string
  uploaded_by: string
  metadata: Record<string, string>
  version: number
  expected_chunks: number
  completed_chunks: number
  created_at: string
  updated_at: string
}

export type DocumentJobStatus = 'queued' | 'running' | 'completed' | 'failed'
export type DocumentJob = {
  id: string
  file_name: string
  content_type: string
  workspace_id: string
  project_id: string
  uploaded_by: string
  status: DocumentJobStatus
  document_id?: string | null
  version: number
  expected_chunks: number
  completed_chunks: number
  error?: string | null
  error_type?: string | null
  created_at: string
  updated_at: string
}

export type UploadResponse = { item: DocumentRecord; job?: never } | { item?: never; job: DocumentJob }
export type DocumentJobsResponse = { items: DocumentJob[] }
export type DocumentJobResponse = { item: DocumentJob }
export type DocumentResponse = { item: DocumentRecord }
export type SearchResponse = { items: SearchResult[] }

export type ResourceSelection =
  | { kind: 'document'; id: string }
  | { kind: 'source'; source: Source }
