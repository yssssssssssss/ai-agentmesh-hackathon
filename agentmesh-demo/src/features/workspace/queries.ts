import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryRoots } from '../../app/queryKeys'
import { useAuth } from '../auth/AuthProvider'
import { workspaceApi } from './api'
import { workspaceKeys } from './keys'
import type {
  ChatResponse,
  DocumentJobsResponse,
  ThreadDetailResponse,
  UploadResponse,
  WorkspaceScope,
} from './types'

const ACTIVE_JOB_STATUS: Record<string, true> = { queued: true, running: true }
export type ChatSendState = 'retryable' | 'processing' | 'failed' | 'unknown'

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

export function useSkillsQuery(scope: WorkspaceScope) {
  return useQuery({
    queryKey: workspaceKeys.skills(scope),
    queryFn: workspaceApi.skills,
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
