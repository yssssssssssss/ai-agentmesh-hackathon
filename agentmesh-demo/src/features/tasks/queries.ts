import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys, type QueryScope } from '../../app/queryKeys'
import { useAuth } from '../auth/AuthProvider'
import { taskManagementApi } from './api'
import type {
  TaskArchivePayload,
  TaskCreatePayload,
  TaskTransitionPayload,
  TaskUpdatePayload,
} from './types'

export function taskManagementErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  const detail = typeof error.detail === 'string' ? error.detail : `请求失败（${error.status}）`
  const messages: Record<string, string> = {
    task_management_read_only: '任务中心当前为只读模式。',
    task_command_conflict: '该操作标识已经用于不同请求，请重新操作。',
    task_version_conflict: '任务已被其他操作更新，请刷新后重试。',
    task_transition_invalid: '当前交付阶段不允许此操作。',
    task_blocked: '任务仍处于阻塞状态，请先解除阻塞。',
    task_not_blocked: '任务当前没有阻塞状态。',
    task_archive_requires_terminal_stage: '只有已完成或已取消的任务可以归档。',
    task_already_archived: '任务已经归档。',
    task_archived: '任务已在其他会话归档，当前表单已切换为只读。',
    task_block_reason_required: '阻塞任务时必须填写原因。',
    task_assignment_forbidden: '没有权限执行该分派。',
    task_action_forbidden: '没有权限修改该任务。',
    task_assignee_not_found: '负责人不存在或不在当前项目。',
  }
  return messages[detail] ?? detail
}

async function invalidateTaskData(
  queryClient: ReturnType<typeof useQueryClient>,
  context: QueryScope,
  refreshBootstrap: () => Promise<void>,
) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.tasks.management(context), exact: true }),
    queryClient.invalidateQueries({ queryKey: queryKeys.tasks.root }),
    queryClient.invalidateQueries({ queryKey: queryKeys.audit.root }),
    refreshBootstrap(),
  ])
}

export function useManagedTasks(context: QueryScope) {
  return useQuery({
    queryKey: queryKeys.tasks.management(context),
    queryFn: () => taskManagementApi.list(context.projectId),
  })
}

export function useTaskManagementMutations(context: QueryScope) {
  const queryClient = useQueryClient()
  const { refreshBootstrap } = useAuth()
  const settled = () => invalidateTaskData(queryClient, context, refreshBootstrap)
  const create = useMutation({
    mutationFn: (payload: TaskCreatePayload) => taskManagementApi.create(payload),
    onSettled: settled,
  })
  const update = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: TaskUpdatePayload }) =>
      taskManagementApi.update(taskId, payload),
    onSettled: settled,
  })
  const transition = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: TaskTransitionPayload }) =>
      taskManagementApi.transition(taskId, payload),
    onSettled: settled,
  })
  const archive = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: TaskArchivePayload }) =>
      taskManagementApi.archive(taskId, payload),
    onSettled: settled,
  })
  return { create, update, transition, archive }
}
