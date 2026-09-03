import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys, type QueryScope } from '../../app/queryKeys'
import { useAuth } from '../auth/AuthProvider'
import { knowledgeApi, type MemoryGovernanceFilters } from './api'

export type KnowledgeContext = QueryScope

export const knowledgeKeys = {
  inboxRoot: queryKeys.inbox.root,
  memoryRoot: queryKeys.memory.root,
  documentsRoot: queryKeys.documents.root,
  auditRoot: queryKeys.audit.root,
  tasksRoot: queryKeys.tasks.root,
  workspaceRoot: queryKeys.workspace.root,
  inbox: queryKeys.inbox.list,
  memory: queryKeys.memory.list,
  memoryLineage: queryKeys.memory.detail,
  governance: queryKeys.memory.governance,
  overview: queryKeys.memory.overview,
  documents: queryKeys.documents.list,
  document: queryKeys.documents.detail,
}

export function governanceErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (error.status === 400) return `请求内容不完整：${String(error.detail)}`
  if (error.status === 403) return `没有执行此操作的权限：${String(error.detail)}`
  if (error.status === 404) return `资源已不存在或不可见：${String(error.detail)}`
  if (error.status === 409) return `状态已被其他操作更新，已刷新最新结果：${String(error.detail)}`
  return String(error.detail || `请求失败（${error.status}）`)
}

async function invalidateGovernance(queryClient: QueryClient, refreshBootstrap: () => Promise<void>) {
  await Promise.allSettled([
    queryClient.invalidateQueries({ queryKey: knowledgeKeys.inboxRoot }),
    queryClient.invalidateQueries({ queryKey: knowledgeKeys.memoryRoot }),
    queryClient.invalidateQueries({ queryKey: knowledgeKeys.documentsRoot }),
    queryClient.invalidateQueries({ queryKey: knowledgeKeys.auditRoot }),
    queryClient.invalidateQueries({ queryKey: knowledgeKeys.tasksRoot }),
    queryClient.invalidateQueries({ queryKey: knowledgeKeys.workspaceRoot }),
    refreshBootstrap(),
  ])
}

export function useKnowledgeQueries(context: KnowledgeContext) {
  const inbox = useQuery({
    queryKey: knowledgeKeys.inbox(context, true),
    queryFn: () => knowledgeApi.inbox(true),
  })
  const memory = useQuery({
    queryKey: knowledgeKeys.memory(context),
    queryFn: () => knowledgeApi.memory(context.projectId),
  })
  const overview = useQuery({
    queryKey: knowledgeKeys.overview(context),
    queryFn: () => knowledgeApi.overview(context.projectId),
  })
  const documents = useQuery({
    queryKey: knowledgeKeys.documents(context),
    queryFn: knowledgeApi.documents,
  })
  return { inbox, memory, overview, documents }
}

export function useGovernanceHistoryQuery(
  context: KnowledgeContext,
  filters: MemoryGovernanceFilters,
) {
  return useQuery({
    queryKey: knowledgeKeys.governance(
      context,
      filters.status,
      filters.scope,
      filters.kind,
      filters.layer,
      filters.page,
      filters.pageSize,
    ),
    queryFn: () => knowledgeApi.governance(context.projectId, filters),
  })
}

export function useMemoryLineageQuery(context: KnowledgeContext, memoryId: string | null) {
  return useQuery({
    queryKey: knowledgeKeys.memoryLineage(context, memoryId ?? 'none'),
    queryFn: () => knowledgeApi.memoryLineage(memoryId as string),
    enabled: memoryId !== null,
  })
}

export function useDocumentQuery(context: KnowledgeContext, documentId: string | null) {
  return useQuery({
    queryKey: knowledgeKeys.document(context, documentId ?? 'none'),
    queryFn: () => knowledgeApi.document(documentId as string),
    enabled: documentId !== null,
  })
}

export function useKnowledgeMutations() {
  const queryClient = useQueryClient()
  const { refreshBootstrap } = useAuth()
  const options = { onSettled: () => invalidateGovernance(queryClient, refreshBootstrap) }
  const updateInbox = useMutation({
    mutationFn: ({ itemId, status }: { itemId: string; status: 'snoozed' | 'resolved' }) =>
      knowledgeApi.updateInbox(itemId, status === 'snoozed' ? { status, ttl_minutes: 60 } : { status }),
    ...options,
  })
  const confirmBrief = useMutation({
    mutationFn: knowledgeApi.confirmBrief,
    ...options,
  })
  const resolveInjection = useMutation({
    mutationFn: ({ itemId, action }: { itemId: string; action: 'release' | 'discard' }) =>
      knowledgeApi.resolveInjection(itemId, action),
    ...options,
  })
  const resolveToolApproval = useMutation({
    mutationFn: ({ itemId, callId, action }: { itemId: string; callId: string; action: 'approve' | 'reject' }) =>
      knowledgeApi.resolveToolApproval(itemId, callId, action),
    ...options,
  })
  const acceptMemory = useMutation({
    mutationFn: knowledgeApi.acceptMemory,
    ...options,
  })
  const createMemoryRevision = useMutation({
    mutationFn: knowledgeApi.createMemoryRevision,
    ...options,
  })
  const transitionMemory = useMutation({
    mutationFn: knowledgeApi.transitionMemory,
    ...options,
  })
  const decideMemoryReview = useMutation({
    mutationFn: knowledgeApi.decideMemoryReview,
    ...options,
  })
  return {
    updateInbox,
    confirmBrief,
    resolveInjection,
    resolveToolApproval,
    acceptMemory,
    createMemoryRevision,
    transitionMemory,
    decideMemoryReview,
  }
}
