import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { queryKeys } from '../../app/queryKeys'

import { ApiError } from '../../api/client'
import { useAuth } from '../auth/AuthProvider'
import type { HandoffPayload, ReplyPayload } from './api'
import { collaborationApi } from './api'

export interface CollaborationContext {
  userId: string
  workspaceId: string
  projectId: string
}

export const collaborationKeys = {
  marketRoot: ['market'] as const,
  cards: queryKeys.tasks.cards,
  task: queryKeys.tasks.detail,
  marketStatus: (context: CollaborationContext) =>
    ['market', 'status', context.userId, context.workspaceId] as const,
  marketBoard: (context: CollaborationContext) =>
    ['market', 'board', context.userId, context.workspaceId] as const,
  participation: (context: CollaborationContext) =>
    ['market', 'participation', context.userId, context.workspaceId] as const,
}

export function collaborationErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (error.status === 400) return `请求内容不完整：${String(error.detail)}`
  if (error.status === 403) return `没有执行此操作的权限：${String(error.detail)}`
  if (error.status === 404) return `任务已不存在或当前账号不可见：${String(error.detail)}`
  if (error.status === 409) return `任务状态已变化，已刷新服务端最新状态：${String(error.detail)}`
  return String(error.detail || `请求失败（${error.status}）`)
}

function useDocumentVisible() {
  const [visible, setVisible] = useState(() => document.visibilityState === 'visible')
  useEffect(() => {
    const update = () => setVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  return visible
}

async function invalidateTaskResources(queryClient: QueryClient, refreshBootstrap: () => Promise<void>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.tasks.root }),
    queryClient.invalidateQueries({ queryKey: queryKeys.audit.root }),
    refreshBootstrap(),
  ])
}

async function invalidateMarketResources(queryClient: QueryClient, refreshBootstrap: () => Promise<void>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: collaborationKeys.marketRoot }),
    queryClient.invalidateQueries({ queryKey: queryKeys.audit.root }),
    refreshBootstrap(),
  ])
}

export function useTaskCards(context: CollaborationContext) {
  return useQuery({
    queryKey: collaborationKeys.cards(context),
    queryFn: () => collaborationApi.taskCards(context.projectId),
  })
}

export function useTaskDetail(context: CollaborationContext, taskId: string | null) {
  return useQuery({
    queryKey: collaborationKeys.task(context, taskId ?? 'none'),
    queryFn: () => collaborationApi.taskDetail(taskId as string),
    enabled: taskId !== null,
  })
}

export function useMarketQueries(context: CollaborationContext, marketVisible: boolean) {
  const documentVisible = useDocumentVisible()
  const enabled = marketVisible && documentVisible
  const status = useQuery({
    queryKey: collaborationKeys.marketStatus(context),
    queryFn: collaborationApi.marketStatus,
    enabled,
    refetchInterval: enabled ? 30_000 : false,
  })
  const board = useQuery({
    queryKey: collaborationKeys.marketBoard(context),
    queryFn: collaborationApi.marketBoard,
    enabled,
    refetchInterval: enabled ? 30_000 : false,
  })
  const participation = useQuery({
    queryKey: collaborationKeys.participation(context),
    queryFn: collaborationApi.participation,
    enabled,
  })
  return { status, board, participation, polling: enabled }
}

export function useCollaborationMutations() {
  const queryClient = useQueryClient()
  const { refreshBootstrap } = useAuth()
  const taskOptions = { onSettled: () => invalidateTaskResources(queryClient, refreshBootstrap) }
  const reply = useMutation({
    mutationFn: ({ postId, payload }: { postId: string; payload: ReplyPayload }) =>
      collaborationApi.reply(postId, payload),
    ...taskOptions,
  })
  const lock = useMutation({
    mutationFn: ({ postId, ownerAgentId }: { postId: string; ownerAgentId: string }) =>
      collaborationApi.lock(postId, ownerAgentId),
    ...taskOptions,
  })
  const unlock = useMutation({
    mutationFn: collaborationApi.unlock,
    ...taskOptions,
  })
  const handoff = useMutation({
    mutationFn: ({ postId, payload }: { postId: string; payload: HandoffPayload }) =>
      collaborationApi.handoff(postId, payload),
    ...taskOptions,
  })
  const markRead = useMutation({
    mutationFn: collaborationApi.markRead,
    ...taskOptions,
  })
  const participation = useMutation({
    mutationFn: collaborationApi.setParticipation,
    onSettled: () => invalidateMarketResources(queryClient, refreshBootstrap),
  })
  return { reply, lock, unlock, handoff, markRead, participation }
}
