import { apiRequest } from '../../api/client'
import type {
  AgentRunEvent,
  AgentRunEventsResponse,
  AgentRunResponse,
  ChatResponse,
  ChatTurnReceipt,
  DocumentJobResponse,
  DocumentJobsResponse,
  DocumentResponse,
  ResearchCommandResponse,
  ResearchConfirmPlanRequest,
  ResearchExecuteRequest,
  ResearchRecoverRequest,
  ResearchRunProjection,
  SearchResponse,
  SkillPlanDetailResponse,
  SkillPlanTransitionResponse,
  SkillPlanUpdateRequest,
  SkillPlanVersionRequest,
  SkillRecommendationResponse,
  SkillsResponse,
  TaskRoutingPreviewRequest,
  TaskRoutingPreviewResponse,
  ThreadDetailResponse,
  ThreadListResponse,
  ThreadResponse,
  ThreadUpdateRequest,
  UploadResponse,
  WorkspaceScope,
} from './types'

const pathId = (value: string) => encodeURIComponent(value)

const RUN_EVENT_TYPES = [
  'intent_normalized',
  'run_started',
  'research_updated',
  'research_attempt_claimed',
  'research_attempt_completed',
  'research_attempt_failed',
  'research_attempt_cancelled',
  'research_step_claimed',
  'research_step_ready',
  'research_step_running',
  'research_step_completed',
  'research_step_failed',
  'research_step_skipped',
  'research_step_cancelled',
  'research_tool_invocation_prepared',
  'research_tool_invocation_sent',
  'research_tool_invocation_unknown',
  'research_tool_invocation_retry_authorized',
  'research_recovery_required',
  'research_artifacts_sealed',
  'research_model_call_settled',
  'artifact_staged',
  'artifact_invalidated',
  'artifact_purged',
  'skill_candidates_ranked',
  'plan_created',
  'plan_waiting_approval',
  'plan_updated',
  'plan_approved',
  'plan_rejected',
  'plan_execution_started',
  'plan_execution_resumed',
  'node_ready',
  'node_started',
  'node_retry_scheduled',
  'node_rescheduled_after_parallel_approval',
  'node_waiting_tool_approval',
  'node_completed',
  'node_failed',
  'node_skipped',
  'node_cancelled',
  'approval_requested',
  'approval_resolved',
  'synthesis_started',
  'synthesis_completed',
  'run_completed',
  'run_partial',
  'run_failed',
  'run_rejected',
  'run_cancelled',
] as const

const TERMINAL_RUN_EVENTS = new Set(['run_completed', 'run_partial', 'run_failed', 'run_rejected', 'run_cancelled'])

export function parseAgentRunEvent(data: string): AgentRunEvent | null {
  try {
    const value: unknown = JSON.parse(data)
    if (!value || typeof value !== 'object') return null
    const event = value as Partial<AgentRunEvent>
    if (
      typeof event.run_id !== 'string'
      || typeof event.sequence !== 'number'
      || !Number.isSafeInteger(event.sequence)
      || event.sequence < 1
      || typeof event.event_type !== 'string'
      || !event.payload
      || typeof event.payload !== 'object'
      || Array.isArray(event.payload)
    ) return null
    return event as AgentRunEvent
  } catch {
    return null
  }
}

export function subscribeAgentRunEvents(
  runId: string,
  handlers: { onEvent: (event: AgentRunEvent) => void; onError: () => void },
  afterSequence = 0,
): () => void {
  let lastSequence = Math.max(0, afterSequence)
  const params = new URLSearchParams({ after_sequence: String(lastSequence) })
  const stream = new EventSource(`/api/agent/runs/${pathId(runId)}/events/stream?${params.toString()}`)
  const handle = (rawEvent: Event) => {
    if (!(rawEvent instanceof MessageEvent)) return
    const event = parseAgentRunEvent(String(rawEvent.data))
    if (!event || event.run_id !== runId || event.sequence <= lastSequence) return
    lastSequence = event.sequence
    handlers.onEvent(event)
    if (TERMINAL_RUN_EVENTS.has(event.event_type)) stream.close()
  }
  for (const eventType of RUN_EVENT_TYPES) stream.addEventListener(eventType, handle)
  stream.onerror = handlers.onError
  return () => {
    for (const eventType of RUN_EVENT_TYPES) stream.removeEventListener(eventType, handle)
    stream.close()
  }
}

export interface StartAgentRunInput {
  threadId: string | null
  content: string
  clientTurnId: string
  explicitSkillName?: string
  orchestrationMode: 'auto' | 'single'
}

export const workspaceApi = {
  threads: () => apiRequest<ThreadListResponse>('/api/chat/threads'),
  thread: (threadId: string) => apiRequest<ThreadDetailResponse>(`/api/chat/threads/${pathId(threadId)}`),
  updateThread: (threadId: string, request: ThreadUpdateRequest) =>
    apiRequest<ThreadResponse>(`/api/chat/threads/${pathId(threadId)}`, {
      method: 'PATCH',
      body: JSON.stringify(request),
    }),
  deleteThread: (threadId: string) =>
    apiRequest<null>(`/api/chat/threads/${pathId(threadId)}`, { method: 'DELETE' }),
  sendMessage: (threadId: string | null, content: string, clientTurnId: string) =>
    apiRequest<ChatResponse>('/api/chat/messages', {
      method: 'POST',
      body: JSON.stringify({ thread_id: threadId, content, client_turn_id: clientTurnId }),
    }),
  turnReceipt: (clientTurnId: string) =>
    apiRequest<ChatTurnReceipt>(`/api/chat/messages/receipts/${pathId(clientTurnId)}`),
  startAgentRun: ({
    threadId,
    content,
    clientTurnId,
    explicitSkillName,
    orchestrationMode,
  }: StartAgentRunInput) =>
    apiRequest<AgentRunResponse>('/api/agent/runs', {
      method: 'POST',
      body: JSON.stringify({
        thread_id: threadId,
        content,
        client_turn_id: clientTurnId,
        explicit_skill_name: explicitSkillName,
        orchestration_mode: orchestrationMode,
      }),
    }),
  agentRun: (runId: string) => apiRequest<AgentRunResponse>(`/api/agent/runs/${pathId(runId)}`),
  researchRun: (runId: string) =>
    apiRequest<ResearchRunProjection>(`/api/agent/runs/${pathId(runId)}/research`),
  confirmResearchPlan: (
    runId: string,
    planVersionId: string,
    request: ResearchConfirmPlanRequest,
    idempotencyKey: string,
  ) => apiRequest<ResearchCommandResponse>(
    `/api/agent/runs/${pathId(runId)}/research/plans/${pathId(planVersionId)}/confirm`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(request),
    },
  ),
  executeResearch: (
    runId: string,
    request: ResearchExecuteRequest,
    idempotencyKey: string,
  ) => apiRequest<ResearchCommandResponse>(`/api/agent/runs/${pathId(runId)}/research/execute`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(request),
  }),
  recoverResearch: (
    runId: string,
    request: ResearchRecoverRequest,
    idempotencyKey: string,
  ) => apiRequest<ResearchCommandResponse>(`/api/agent/runs/${pathId(runId)}/research/recover`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(request),
  }),
  resolveResearchToolApproval: (
    itemId: string,
    callId: string,
    action: 'approve' | 'reject',
  ) => apiRequest<{
    run_id: string
    attempt_id?: string | null
    scheduled: boolean
  }>(
    `/api/inbox/${pathId(itemId)}/resolve-tool-approval?action=${action}&call_id=${pathId(callId)}`,
    { method: 'POST' },
  ),
  agentRunEvents: (runId: string, afterSequence = 0) =>
    apiRequest<AgentRunEventsResponse>(
      `/api/agent/runs/${pathId(runId)}/events?after_sequence=${Math.max(0, afterSequence)}`,
    ),
  skillPlan: (runId: string) =>
    apiRequest<SkillPlanDetailResponse>(`/api/agent/runs/${pathId(runId)}/plan`),
  updateSkillPlan: (runId: string, request: SkillPlanUpdateRequest) =>
    apiRequest<SkillPlanDetailResponse>(`/api/agent/runs/${pathId(runId)}/plan`, {
      method: 'PATCH',
      body: JSON.stringify(request),
    }),
  approveSkillPlan: (runId: string, request: SkillPlanVersionRequest) =>
    apiRequest<SkillPlanTransitionResponse>(`/api/agent/runs/${pathId(runId)}/plan/approve`, {
      method: 'POST',
      body: JSON.stringify(request),
    }),
  rejectSkillPlan: (runId: string, request: SkillPlanVersionRequest) =>
    apiRequest<SkillPlanTransitionResponse>(`/api/agent/runs/${pathId(runId)}/plan/reject`, {
      method: 'POST',
      body: JSON.stringify(request),
    }),
  retryAgentRun: (runId: string, clientTurnId: string) =>
    apiRequest<AgentRunResponse>(`/api/agent/runs/${pathId(runId)}/retry`, {
      method: 'POST',
      body: JSON.stringify({ client_turn_id: clientTurnId }),
    }),
  cancelAgentRun: (runId: string) =>
    apiRequest<AgentRunResponse>(`/api/agent/runs/${pathId(runId)}/cancel`, { method: 'POST' }),
  recommendSkills: (content: string, threadId?: string | null) =>
    apiRequest<SkillRecommendationResponse>('/api/skills/recommendations', {
      method: 'POST',
      body: JSON.stringify({ content, thread_id: threadId || undefined }),
    }),
  previewTaskRouting: (request: TaskRoutingPreviewRequest) =>
    apiRequest<TaskRoutingPreviewResponse>('/api/skills/routing-preview', {
      method: 'POST',
      body: JSON.stringify(request),
    }),
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
