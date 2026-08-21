import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { useEffect } from 'react'

import { ApiError } from '../../api/client'
import { queryRoots } from '../../app/queryKeys'
import { useAuth } from '../auth/AuthProvider'
import { subscribeAgentRunEvents, workspaceApi, type StartAgentRunInput } from './api'
import { workspaceKeys } from './keys'
import type {
  AgentRun,
  ChatResponse,
  ChatThread,
  DocumentJobsResponse,
  ThreadDetailResponse,
  ThreadListResponse,
  ThreadUpdateRequest,
  UploadResponse,
  WorkspaceScope,
} from './types'

const ACTIVE_JOB_STATUS: Record<string, true> = { queued: true, running: true }
export type ChatSendState = 'retryable' | 'processing' | 'approval' | 'failed' | 'unknown'

export class ChatSendError extends Error {
  readonly name = 'ChatSendError'

  constructor(
    message: string,
    public readonly state: ChatSendState,
    public readonly threadId: string | null = null,
  ) {
    super(message)
  }
}


export function workspaceErrorMessage(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  if (error instanceof Error) return error.message
  return '请求失败，请稍后重试'
}

export function useWorkspaceScope(): WorkspaceScope {
  const { user, bootstrap } = useAuth()
  if (!user || !bootstrap) throw new Error('Workspace queries require an authenticated bootstrap')
  return {
    userId: user.id ?? '',
    workspaceId: bootstrap.workspace.id ?? user.workspace_id,
    projectId: bootstrap.project.id ?? user.default_project_id,
  }
}

export function useThreadsQuery(scope: WorkspaceScope) {
  return useQuery({
    queryKey: workspaceKeys.threads(scope),
    queryFn: workspaceApi.threads,
  })
}

export function useThreadDetailQuery(scope: WorkspaceScope, threadId: string | null) {
  return useQuery({
    queryKey: workspaceKeys.thread(scope, threadId ?? 'none'),
    queryFn: () => workspaceApi.thread(threadId ?? ''),
    enabled: Boolean(threadId),
  })
}

function sortThreads(items: ChatThread[]): ChatThread[] {
  return [...items].sort((left, right) => {
    const pinOrder = Number(Boolean(right.pinned)) - Number(Boolean(left.pinned))
    if (pinOrder !== 0) return pinOrder
    const timeOrder = String(right.updated_at ?? '').localeCompare(String(left.updated_at ?? ''))
    if (timeOrder !== 0) return timeOrder
    return String(right.id ?? '').localeCompare(String(left.id ?? ''))
  })
}

export function useUpdateThreadMutation(scope: WorkspaceScope) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ threadId, update }: { threadId: string; update: ThreadUpdateRequest }) =>
      workspaceApi.updateThread(threadId, update),
    onSuccess: (response, { threadId }) => {
      queryClient.setQueryData<ThreadListResponse>(workspaceKeys.threads(scope), (current) => {
        if (!current) return current
        return {
          items: sortThreads(current.items.map((thread) => (
            thread.id === threadId ? response.thread : thread
          ))),
        }
      })
      queryClient.setQueryData<ThreadDetailResponse>(workspaceKeys.thread(scope, threadId), (current) => (
        current ? { ...current, thread: response.thread } : current
      ))
    },
  })
}

export function useDeleteThreadMutation(scope: WorkspaceScope) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (threadId: string) => workspaceApi.deleteThread(threadId),
    onSuccess: (_response, threadId) => {
      queryClient.setQueryData<ThreadListResponse>(workspaceKeys.threads(scope), (current) => (
        current ? { items: current.items.filter((thread) => thread.id !== threadId) } : current
      ))
      queryClient.removeQueries({ queryKey: workspaceKeys.thread(scope, threadId), exact: true })
    },
  })
}

export function useSkillsQuery(scope: WorkspaceScope) {
  return useQuery({
    queryKey: workspaceKeys.skills(scope),
    queryFn: workspaceApi.skills,
  })
}

export function useSkillCatalogQuery(scope: WorkspaceScope) {
  return useQuery({
    queryKey: workspaceKeys.skillCatalog(scope),
    queryFn: workspaceApi.skillCatalog,
  })
}

export function useAgentRunQuery(scope: WorkspaceScope, runId: string | null) {
  return useQuery({
    queryKey: workspaceKeys.run(scope, runId ?? 'none'),
    queryFn: () => workspaceApi.agentRun(runId ?? ''),
    enabled: Boolean(runId),
  })
}

export function useResearchRunQuery(scope: WorkspaceScope, run: AgentRun | null | undefined) {
  const runId = run?.orchestration_version === 'research-v2' ? run.id : null
  return useQuery({
    queryKey: workspaceKeys.research(scope, runId ?? 'none'),
    queryFn: () => workspaceApi.researchRun(runId ?? ''),
    enabled: Boolean(runId),
  })
}

export function useSkillPlanQuery(scope: WorkspaceScope, runId: string | null, planId: string | null | undefined) {
  return useQuery({
    queryKey: workspaceKeys.plan(scope, runId ?? 'none'),
    queryFn: () => workspaceApi.skillPlan(runId ?? ''),
    enabled: Boolean(runId && planId),
  })
}

export function useSkillRecommendationsMutation() {
  return useMutation({
    mutationFn: ({ content, threadId }: { content: string; threadId?: string | null }) =>
      workspaceApi.recommendSkills(content, threadId),
  })
}

export function useUpdateSkillBindingMutation(scope: WorkspaceScope) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ skillId, enabled }: { skillId: string; enabled: boolean }) =>
      workspaceApi.updateSkillBinding(skillId, enabled),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: workspaceKeys.skillCatalog(scope) }),
        queryClient.invalidateQueries({ queryKey: workspaceKeys.skills(scope) }),
      ])
    },
  })
}

export function useDocumentQuery(scope: WorkspaceScope, documentId: string | null) {
  return useQuery({
    queryKey: workspaceKeys.document(scope, documentId ?? 'none'),
    queryFn: () => workspaceApi.document(documentId ?? ''),
    enabled: Boolean(documentId),
  })
}

export function useDocumentJobsQuery(scope: WorkspaceScope) {
  return useQuery({
    queryKey: workspaceKeys.jobs(scope),
    queryFn: async (): Promise<DocumentJobsResponse> => {
      const response = await workspaceApi.jobs()
      return {
        items: response.items.filter(
          (job) =>
            job.uploaded_by === scope.userId &&
            job.workspace_id === scope.workspaceId &&
            job.project_id === scope.projectId,
        ),
      }
    },
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => ACTIVE_JOB_STATUS[job.status]) ? 1_000 : false,
  })
}

export function useDocumentJobQuery(scope: WorkspaceScope, jobId: string | null) {
  return useQuery({
    queryKey: workspaceKeys.job(scope, jobId ?? 'none'),
    queryFn: () => workspaceApi.job(jobId ?? ''),
    enabled: Boolean(jobId),
    refetchInterval: (query) =>
      query.state.data && ACTIVE_JOB_STATUS[query.state.data.item.status] ? 1_000 : false,
  })
}

export function useSearchQuery(scope: WorkspaceScope, query: string) {
  const normalized = query.trim()
  return useQuery({
    queryKey: workspaceKeys.search(scope, normalized),
    queryFn: () => workspaceApi.search(scope, normalized),
    enabled: normalized.length > 0,
  })
}

async function invalidateChatSideEffects(queryClient: QueryClient, refreshBootstrap: () => Promise<void>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryRoots.inbox }),
    queryClient.invalidateQueries({ queryKey: queryRoots.memory }),
    queryClient.invalidateQueries({ queryKey: queryRoots.documents }),
    queryClient.invalidateQueries({ queryKey: queryRoots.tasks }),
    queryClient.invalidateQueries({ queryKey: queryRoots.audit }),
    refreshBootstrap(),
  ])
}

async function invalidateCanonicalThread(queryClient: QueryClient, scope: WorkspaceScope, threadId: string) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: workspaceKeys.thread(scope, threadId), exact: true }),
    queryClient.invalidateQueries({ queryKey: workspaceKeys.threads(scope), exact: true }),
  ])
}

function appendServerTurn(current: ThreadDetailResponse | undefined, response: ChatResponse) {
  if (!current) return current
  const returnedIds = new Set([response.user_message.id, response.assistant_message.id])
  const messages = current.messages.filter((message) => !returnedIds.has(message.id))
  messages.push(response.user_message, response.assistant_message)
  messages.sort((left, right) => (left.created_at ?? '').localeCompare(right.created_at ?? ''))
  const turnTraces = response.turn_trace
    ? [
        ...current.turn_traces.filter(
          (trace) => trace.assistant_message_id !== response.turn_trace?.assistant_message_id,
        ),
        response.turn_trace,
      ].sort((left, right) => left.created_at.localeCompare(right.created_at))
    : current.turn_traces
  return {
    thread: {
      ...current.thread,
      updated_at: response.assistant_message.created_at ?? current.thread.updated_at,
    },
    messages,
    turn_traces: turnTraces,
  }
}

export function useSendMessageMutation(scope: WorkspaceScope) {
  const queryClient = useQueryClient()
  const { refreshBootstrap } = useAuth()
  return useMutation({
    mutationFn: async ({
      threadId,
      content,
      clientTurnId,
    }: {
      threadId: string | null
      content: string
      clientTurnId: string
    }) => {
      try {
        return await workspaceApi.sendMessage(threadId, content, clientTurnId)
      } catch {
        try {
          const receipt = await workspaceApi.turnReceipt(clientTurnId)
          await invalidateCanonicalThread(queryClient, scope, receipt.thread_id)
          if (receipt.status === 'completed' && receipt.response) return receipt.response
          if (receipt.status === 'processing') {
            throw new ChatSendError('服务端已受理，正在处理。请重新核对状态。', 'processing', receipt.thread_id)
          }
          throw new ChatSendError('服务端已受理但未完成；草稿已保留，不会自动重复执行。', 'failed', receipt.thread_id)
        } catch (receiptError) {
          if (receiptError instanceof ChatSendError) throw receiptError
          if (receiptError instanceof ApiError && receiptError.status === 404) {
            throw new ChatSendError('服务端未收到本次请求，草稿已保留，可安全重试。', 'retryable')
          }
          throw new ChatSendError('暂时无法核对服务端状态；草稿已保留，请勿重复发送。', 'unknown')
        }
      }
    },
    onSuccess: async (response) => {
      queryClient.setQueryData<ThreadDetailResponse>(
        workspaceKeys.thread(scope, response.thread_id),
        (current) => appendServerTurn(current, response),
      )
      await Promise.all([
        invalidateCanonicalThread(queryClient, scope, response.thread_id),
        invalidateChatSideEffects(queryClient, refreshBootstrap),
      ])
    },
  })
}

export function useSendAgentRunMutation(scope: WorkspaceScope) {
  const queryClient = useQueryClient()
  const { refreshBootstrap } = useAuth()
  return useMutation({
    mutationFn: (input: StartAgentRunInput) => workspaceApi.startAgentRun(input),
    onSuccess: async (response) => {
      const run = response.item
      queryClient.setQueryData(workspaceKeys.run(scope, run.id), response)
      await Promise.all([
        invalidateCanonicalThread(queryClient, scope, run.thread_id),
        invalidateChatSideEffects(queryClient, refreshBootstrap),
      ])
    },
  })
}

export function useSkillPlanMutations(scope: WorkspaceScope, runId: string | null) {
  const queryClient = useQueryClient()
  const refresh = async () => {
    if (!runId) return
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: workspaceKeys.run(scope, runId), exact: true }),
      queryClient.invalidateQueries({ queryKey: workspaceKeys.plan(scope, runId), exact: true }),
    ])
  }
  const refreshOnConflict = async (error: unknown) => {
    if (error instanceof ApiError && error.status === 409) await refresh()
  }
  const update = useMutation({
    mutationFn: (request: Parameters<typeof workspaceApi.updateSkillPlan>[1]) => {
      if (!runId) throw new Error('缺少 Agent Run')
      return workspaceApi.updateSkillPlan(runId, request)
    },
    onSuccess: (detail) => {
      if (runId) queryClient.setQueryData(workspaceKeys.plan(scope, runId), detail)
    },
    onError: refreshOnConflict,
  })
  const approve = useMutation({
    mutationFn: (request: Parameters<typeof workspaceApi.approveSkillPlan>[1]) => {
      if (!runId) throw new Error('缺少 Agent Run')
      return workspaceApi.approveSkillPlan(runId, request)
    },
    onSuccess: async (response) => {
      if (runId) queryClient.setQueryData(workspaceKeys.run(scope, runId), { item: response.run })
      await refresh()
    },
    onError: refreshOnConflict,
  })
  const reject = useMutation({
    mutationFn: (request: Parameters<typeof workspaceApi.rejectSkillPlan>[1]) => {
      if (!runId) throw new Error('缺少 Agent Run')
      return workspaceApi.rejectSkillPlan(runId, request)
    },
    onSuccess: async (response) => {
      if (runId) queryClient.setQueryData(workspaceKeys.run(scope, runId), { item: response.run })
      await refresh()
    },
    onError: refreshOnConflict,
  })
  return { update, approve, reject }
}

export function useResearchMutations(scope: WorkspaceScope, run: AgentRun | null | undefined) {
  const queryClient = useQueryClient()
  const runId = run?.id ?? null
  const refresh = async () => {
    if (!runId) return
    const work = [
      queryClient.invalidateQueries({ queryKey: workspaceKeys.run(scope, runId), exact: true }),
      queryClient.invalidateQueries({ queryKey: workspaceKeys.research(scope, runId), exact: true }),
      queryClient.invalidateQueries({ queryKey: queryRoots.inbox }),
    ]
    if (run?.thread_id) work.push(invalidateCanonicalThread(queryClient, scope, run.thread_id))
    await Promise.all(work)
  }
  const refreshOnConflict = async (error: unknown) => {
    if (error instanceof ApiError && error.status === 409) await refresh()
  }
  const confirm = useMutation({
    mutationFn: ({ planVersionId, stateVersion }: { planVersionId: string; stateVersion: number }) => {
      if (!runId) throw new Error('缺少 Research Run')
      return workspaceApi.confirmResearchPlan(
        runId,
        planVersionId,
        { expected_state_version: stateVersion },
        `web-confirm-plan-v${stateVersion}`,
      )
    },
    onSuccess: refresh,
    onError: refreshOnConflict,
  })
  const execute = useMutation({
    mutationFn: ({ stateVersion }: { stateVersion: number }) => {
      if (!runId) throw new Error('缺少 Research Run')
      return workspaceApi.executeResearch(
        runId,
        { expected_state_version: stateVersion },
        `web-execute-v${stateVersion}`,
      )
    },
    onSuccess: refresh,
    onError: refreshOnConflict,
  })
  const resolveTool = useMutation({
    mutationFn: ({
      itemId,
      callId,
      action,
    }: {
      itemId: string
      callId: string
      action: 'approve' | 'reject'
    }) => workspaceApi.resolveResearchToolApproval(itemId, callId, action),
    onSuccess: refresh,
    onError: refreshOnConflict,
  })
  const recover = useMutation({
    mutationFn: ({
      stateVersion,
      invocationId,
      action,
    }: {
      stateVersion: number
      invocationId: string
      action: 'retry' | 'abort'
    }) => {
      if (!runId) throw new Error('缺少 Research Run')
      return workspaceApi.recoverResearch(
        runId,
        {
          expected_state_version: stateVersion,
          invocation_id: invocationId,
          action,
        },
        `web-recover-${action}-v${stateVersion}`,
      )
    },
    onSuccess: refresh,
    onError: refreshOnConflict,
  })
  return { confirm, execute, resolveTool, recover }
}

export function useCancelAgentRunMutation(scope: WorkspaceScope) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (run: AgentRun) => workspaceApi.cancelAgentRun(run.id),
    onSuccess: async (response) => {
      const run = response.item
      queryClient.setQueryData(workspaceKeys.run(scope, run.id), response)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: workspaceKeys.plan(scope, run.id), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryRoots.inbox }),
        invalidateCanonicalThread(queryClient, scope, run.thread_id),
      ])
    },
  })
}

export function useRetryAgentRunMutation(scope: WorkspaceScope) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, clientTurnId }: { runId: string; clientTurnId: string }) => (
      workspaceApi.retryAgentRun(runId, clientTurnId)
    ),
    onSuccess: async (response) => {
      queryClient.setQueryData(workspaceKeys.run(scope, response.item.id), response)
      await invalidateCanonicalThread(queryClient, scope, response.item.thread_id)
    },
  })
}

const TERMINAL_RUN_STATUSES = new Set(['completed', 'partial', 'failed', 'rejected', 'cancelled'])
const PLAN_EVENT_PREFIXES = ['plan_', 'node_', 'synthesis_']

type AgentRunEventTarget = Pick<AgentRun, 'id' | 'thread_id' | 'orchestration_version'>

export async function invalidateAgentRunEvent(
  queryClient: QueryClient,
  scope: WorkspaceScope,
  run: AgentRunEventTarget,
  eventType: string,
  refreshBootstrap: () => Promise<void>,
) {
  if (run.orchestration_version === 'research-v2' || run.orchestration_version === 'research-v3') {
    const work = [
      queryClient.invalidateQueries({ queryKey: workspaceKeys.research(scope, run.id), exact: true }),
      queryClient.invalidateQueries({ queryKey: workspaceKeys.run(scope, run.id), exact: true }),
    ]
    if (eventType === 'approval_requested' || eventType === 'approval_resolved') {
      work.push(queryClient.invalidateQueries({ queryKey: queryRoots.inbox }))
    }
    if (eventType.startsWith('run_') && TERMINAL_RUN_STATUSES.has(eventType.slice(4))) {
      work.push(invalidateCanonicalThread(queryClient, scope, run.thread_id), refreshBootstrap())
    }
    await Promise.all(work)
    return
  }

  const work = [
    queryClient.invalidateQueries({ queryKey: workspaceKeys.run(scope, run.id), exact: true }),
  ]
  if (PLAN_EVENT_PREFIXES.some((prefix) => eventType.startsWith(prefix))) {
    work.push(queryClient.invalidateQueries({ queryKey: workspaceKeys.plan(scope, run.id), exact: true }))
  }
  if (eventType === 'approval_requested' || eventType === 'approval_resolved') {
    work.push(queryClient.invalidateQueries({ queryKey: queryRoots.inbox }))
  }
  if (eventType.startsWith('run_') && TERMINAL_RUN_STATUSES.has(eventType.slice(4))) {
    work.push(
      queryClient.invalidateQueries({ queryKey: workspaceKeys.plan(scope, run.id), exact: true }),
      invalidateCanonicalThread(queryClient, scope, run.thread_id),
      refreshBootstrap(),
    )
  }
  await Promise.all(work)
}

export function useAgentRunEventSubscription(
  scope: WorkspaceScope,
  run: AgentRun | null | undefined,
) {
  const queryClient = useQueryClient()
  const { refreshBootstrap } = useAuth()
  const runId = run?.id
  const runStatus = run?.status
  const threadId = run?.thread_id
  const orchestrationVersion = run?.orchestration_version
  useEffect(() => {
    if (!runId || !threadId || !runStatus || !orchestrationVersion || TERMINAL_RUN_STATUSES.has(runStatus)) return
    const target: AgentRunEventTarget = {
      id: runId,
      thread_id: threadId,
      orchestration_version: orchestrationVersion,
    }
    return subscribeAgentRunEvents(runId, {
      onEvent: (event) => {
        void invalidateAgentRunEvent(queryClient, scope, target, event.event_type, refreshBootstrap)
      },
      onError: () => {
        const queryKey = orchestrationVersion === 'research-v2' || orchestrationVersion === 'research-v3'
          ? workspaceKeys.research(scope, runId)
          : workspaceKeys.run(scope, runId)
        void queryClient.invalidateQueries({ queryKey, exact: true })
      },
    })
  }, [
    queryClient,
    refreshBootstrap,
    orchestrationVersion,
    runId,
    runStatus,
    scope.projectId,
    scope.userId,
    scope.workspaceId,
    threadId,
  ])
}

export function useUploadDocumentMutation(scope: WorkspaceScope) {
  const queryClient = useQueryClient()
  const { refreshBootstrap } = useAuth()
  return useMutation({
    mutationFn: workspaceApi.upload,
    onSuccess: async (response: UploadResponse) => {
      const invalidations = [
        queryClient.invalidateQueries({ queryKey: workspaceKeys.documents(scope) }),
        queryClient.invalidateQueries({ queryKey: workspaceKeys.jobs(scope), exact: true }),
        queryClient.invalidateQueries({ queryKey: workspaceKeys.searchRoot(scope) }),
        queryClient.invalidateQueries({ queryKey: queryRoots.documents }),
        queryClient.invalidateQueries({ queryKey: queryRoots.memory }),
        queryClient.invalidateQueries({ queryKey: queryRoots.audit }),
        refreshBootstrap(),
      ]
      if (response.item) {
        invalidations.push(
          queryClient.invalidateQueries({ queryKey: workspaceKeys.document(scope, response.item.id), exact: true }),
        )
      }
      await Promise.all(invalidations)
    },
  })
}
