import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys, type QueryScope } from '../../app/queryKeys'
import { useAuth } from '../auth/AuthProvider'
import { taskManagementApi } from './api'
import type {
  TaskArchivePayload,
  TaskCreatePayload,
  TaskReviewDecisionPayload,
  TaskReviewSubmitPayload,
  TaskTransitionPayload,
  TaskUpdatePayload,
} from './types'

export function taskManagementErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  const rawDetail = error.detail
  const detail = typeof rawDetail === 'string'
    ? rawDetail
    : rawDetail && typeof rawDetail === 'object' && 'code' in rawDetail
      ? String((rawDetail as { code: unknown }).code)
      : `请求失败（${error.status}）`
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
    task_agent_run_requires_in_progress: '任务进入“进行中”后才能启动 AgentRun。',
    task_agent_assignment_not_executable: '当前负责人不能通过个人 Agent 执行该任务。',
    task_thread_identity_conflict: '任务上下文已变化，请刷新后重试。',
    task_action_forbidden: '没有权限修改该任务。',
    task_assignee_not_found: '负责人不存在或不在当前项目。',
    task_artifact_review_required: '已有 Agent 执行记录，必须选择已封存产物发起审核。',
    task_review_pending: '该任务已有待处理审核，请先完成当前审核。',
    task_review_command_conflict: '该审核操作标识已经用于不同请求，请重新操作。',
    task_review_requires_in_progress: '任务进入“进行中”后才能发起产物审核。',
    task_review_run_not_found: '所选 Run 不属于该任务或当前不可见。',
    task_review_run_not_complete: '只有已完成或部分完成的 Run 可以提交审核。',
    task_review_submitter_not_run_owner: '只有该 Run 的所有者可以提交其产物进行跨用户审核。',
    task_review_artifact_not_found: '所选产物不存在或不属于该 Run。',
    task_review_artifact_not_reviewable: '只有通过完整性校验的已封存产物可以审核。',
    task_review_reviewer_unavailable: '当前项目没有可用的交付审核人。',
    task_review_reviewer_changed: '审核人资格已变化，请重新提交审核。',
    task_review_version_conflict: '审核已被其他操作更新，请刷新后重试。',
    task_review_already_decided: '该审核已经完成。',
    task_review_task_changed: '任务在审核期间发生变化，请重新发起审核。',
    task_review_artifact_integrity_failed: '已冻结产物未通过完整性复核，审核已停止。',
    task_review_inbox_invalid: '审核待办状态异常，决策已安全停止。',
    task_review_integrity_failed: '审核记录未通过完整性校验。',
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
    queryClient.invalidateQueries({ queryKey: queryKeys.inbox.root }),
    refreshBootstrap(),
  ])
}

export function useManagedTasks(context: QueryScope) {
  return useQuery({
    queryKey: queryKeys.tasks.management(context),
    queryFn: () => taskManagementApi.list(context.projectId),
  })
}

export function useManagedTaskDetail(context: QueryScope, taskId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.managedDetail(context, taskId ?? 'none'),
    queryFn: () => taskManagementApi.get(taskId as string),
    enabled: taskId !== null,
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
  const submitReview = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: TaskReviewSubmitPayload }) =>
      taskManagementApi.submitReview(taskId, payload),
    onSettled: settled,
  })
  const decideReview = useMutation({
    mutationFn: ({ reviewId, payload }: { reviewId: string; payload: TaskReviewDecisionPayload }) =>
      taskManagementApi.decideReview(reviewId, payload),
    onSettled: settled,
  })
  return { create, update, transition, archive, submitReview, decideReview }
}
