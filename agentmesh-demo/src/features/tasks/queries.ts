import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys, type QueryScope } from '../../app/queryKeys'
import { useAuth } from '../auth/AuthProvider'
import { taskManagementApi } from './api'
import type {
  TaskArchivePayload,
  TaskCreatePayload,
  TaskReviewDecisionPayload,
  TaskReviewMemoryCapturePayload,
  TaskReviewSubmitPayload,
  TaskTransitionPayload,
  TaskUpdatePayload,
} from './types'

export function taskManagementErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) return '请求失败，请稍后重试。'
  const rawDetail = error instanceof ApiError ? error.detail : error.message
  const detail = typeof rawDetail === 'string'
    ? rawDetail
    : rawDetail && typeof rawDetail === 'object' && 'code' in rawDetail
      ? String((rawDetail as { code: unknown }).code)
      : error instanceof ApiError ? `请求失败（${error.status}）` : error.message
  const messages: Record<string, string> = {
    task_management_read_only: '任务中心当前为只读模式。',
    schedule_cron_invalid: '请填写有效的五段 cron，例如 30 9 * * *。',
    schedule_cron_unreachable: '该日历计划没有可用的运行时间，请调整日期。',
    schedule_timezone_invalid: '请填写有效的 IANA 时区，例如 Asia/Shanghai。',
    schedule_frequency_too_high: '自动巡检的最短间隔为 5 分钟。',
    schedule_version_conflict: '巡检配置已更新，请刷新后重试。',
    schedule_command_conflict: '该操作标识已用于不同请求，请重新操作。',
    schedule_permission_denied: '没有管理当前项目巡检的权限。',
    schedule_actor_not_authorized: '执行账号已停用或权限已变化。',
    schedule_owner_not_authorized: '配置 owner 的项目权限已撤销，巡检已停止。',
    schedule_agent_not_authorized: '配置 owner 的个人 Agent 当前不可用。',
    schedule_project_inactive: '项目已停用，请先恢复项目后再运行。',
    automation_execution_disabled: '自动执行当前关闭或处于观察模式。',
    automation_runtime_unavailable: '执行服务尚未启用，请由管理员检查配置。',
    schedule_overlap: '上一轮仍在执行，本次已跳过。',
    schedule_utc_frequency_limit: '距离上一轮不足 5 分钟，本次已跳过。',
    inspection_deadline_exceeded: '巡检已达到 10 分钟执行时限。',
    inspection_tool_budget_exceeded: '巡检已达到工具调用预算。',
    inspection_read_retry_exhausted: '读取重试已用尽，请检查数据源后手动重跑。',
    inspection_report_not_found: '报告不可访问；完整报告仅配置 owner 可见。',
    inspection_report_not_ready: '报告尚未就绪，请稍后刷新运行记录。',
    inspection_execution_failed: '巡检失败，请查看运行记录并核对来源。',
    legacy_schedule_unvalidated: '历史配置需要重新绑定项目与模板后才能执行。',
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
    task_agent_run_already_active: '该任务已有活动中的 AgentRun。',
    task_agent_assignment_not_executable: '当前负责人不能通过个人 Agent 执行该任务。',
    task_dependencies_incomplete: '前置依赖尚未完成，当前任务不能开始。',
    task_dependency_cycle: '依赖关系会形成环，未保存更改。',
    task_parent_cycle: '父子关系会形成环，未保存更改。',
    task_relationship_target_not_found: '关联任务不存在或不在当前项目。',
    task_relationship_target_archived: '不能关联已归档任务。',
    task_relationship_overlap: '父任务不能同时作为前置依赖。',
    task_dependency_graph_invalid: '项目任务关系异常，操作已安全停止。',
    task_calendar_timezone_required: '日历时间范围必须包含时区。',
    task_calendar_range_invalid: '日历时间范围无效。',
    task_calendar_range_too_large: '单次日历范围不能超过 366 天。',
    task_operations_page_invalid: '项目运营分页参数无效。',
    task_options_page_invalid: '关联任务分页参数无效。',
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
    memory_source_review_not_found: '只有当前账号拥有的已接受 Task Review 可以沉淀记忆。',
    memory_capture_forbidden: '不能从其他人的交付审核创建记忆。',
    memory_reviewer_unavailable: '当前项目没有可用的团队记忆审核人。',
    memory_governance_command_conflict: '该记忆操作标识已经用于不同请求。',
  }
  return messages[detail] ?? detail
}

export async function refreshTaskData(
  queryClient: ReturnType<typeof useQueryClient>,
  refreshBootstrap: () => Promise<void>,
) {
  // An initial fetch without cached data is otherwise reused by refetchQueries.
  // Cancel that older snapshot before asking for post-mutation projections.
  await queryClient.cancelQueries({ queryKey: queryKeys.tasks.root })
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.tasks.root, refetchType: 'none' }),
    queryClient.invalidateQueries({ queryKey: queryKeys.audit.root }),
    queryClient.invalidateQueries({ queryKey: queryKeys.inbox.root }),
    refreshBootstrap(),
  ])
  await queryClient.refetchQueries({ queryKey: queryKeys.tasks.root, type: 'active' })
}

export function useManagedTasks(context: QueryScope, enabled = true, page = 1, pageSize = 100) {
  return useQuery({
    queryKey: [...queryKeys.tasks.management(context), page, pageSize],
    queryFn: () => taskManagementApi.list(context.projectId, page, pageSize),
    enabled,
  })
}

export function useProjectOperations(
  context: QueryScope,
  options: {
    calendarStart: string
    calendarEnd: string
    calendarPage: number
    queuePage: number
    queueAgentId: string
  },
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.tasks.operations(
      context,
      options.calendarStart,
      options.calendarEnd,
      options.calendarPage,
      options.queuePage,
      options.queueAgentId,
    ),
    queryFn: () => taskManagementApi.operations(context.projectId, {
      ...options,
      queueAgentId: options.queueAgentId || null,
    }),
    enabled,
  })
}

export function useTaskOptions(
  context: QueryScope,
  query: string,
  excludeTaskId: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.tasks.options(context, query, excludeTaskId ?? ''),
    queryFn: () => taskManagementApi.taskOptions(context.projectId, {
      query,
      excludeTaskId,
      pageSize: 50,
    }),
    enabled,
  })
}

export function useManagedTaskDetail(
  context: QueryScope,
  taskId: string | null,
  autoFetch = true,
) {
  return useQuery({
    queryKey: queryKeys.tasks.managedDetail(context, taskId ?? 'none'),
    queryFn: () => taskManagementApi.get(taskId as string),
    enabled: autoFetch && taskId !== null,
  })
}

export function useTaskManagementMutations() {
  const queryClient = useQueryClient()
  const { refreshBootstrap } = useAuth()
  const settled = () => refreshTaskData(queryClient, refreshBootstrap)
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
  const captureMemory = useMutation({
    mutationFn: ({ reviewId, payload }: { reviewId: string; payload: TaskReviewMemoryCapturePayload }) =>
      taskManagementApi.captureMemory(reviewId, payload),
    onSettled: async () => {
      await Promise.all([
        settled(),
        queryClient.invalidateQueries({ queryKey: queryKeys.memory.root }),
      ])
    },
  })
  return { create, update, transition, archive, submitReview, decideReview, captureMemory }
}
