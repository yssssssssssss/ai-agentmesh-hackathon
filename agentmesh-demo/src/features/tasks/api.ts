import { apiRequest } from '../../api/client'
import type {
  ManagedTask,
  ManagedTaskDetail,
  ManagedTaskPage,
  MemoryCaptureResponse,
  TaskOperationsSnapshot,
  TaskOptionPage,
  TaskArchivePayload,
  TaskCreatePayload,
  TaskReviewDecisionPayload,
  TaskReviewMutationResponse,
  TaskReviewSubmitPayload,
  TaskReviewMemoryCapturePayload,
  TaskTransitionPayload,
  TaskUpdatePayload,
} from './types'

export interface ManagedTaskResponse {
  item: ManagedTask
}

export const taskManagementApi = {
  list: (projectId: string, page = 1, pageSize = 100) =>
    apiRequest<ManagedTaskPage>(
      `/api/tasks?project_id=${encodeURIComponent(projectId)}&page=${page}&page_size=${pageSize}`,
    ),
  get: (taskId: string) =>
    apiRequest<ManagedTaskDetail>(`/api/tasks/${encodeURIComponent(taskId)}`),
  create: (payload: TaskCreatePayload) =>
    apiRequest<ManagedTaskResponse>('/api/tasks', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  update: (taskId: string, payload: TaskUpdatePayload) =>
    apiRequest<ManagedTaskResponse>(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  transition: (taskId: string, payload: TaskTransitionPayload) =>
    apiRequest<ManagedTaskResponse>(`/api/tasks/${encodeURIComponent(taskId)}/transitions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  archive: (taskId: string, payload: TaskArchivePayload) =>
    apiRequest<ManagedTaskResponse>(`/api/tasks/${encodeURIComponent(taskId)}/archive`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  submitReview: (taskId: string, payload: TaskReviewSubmitPayload) =>
    apiRequest<TaskReviewMutationResponse>(`/api/tasks/${encodeURIComponent(taskId)}/reviews`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  decideReview: (reviewId: string, payload: TaskReviewDecisionPayload) =>
    apiRequest<TaskReviewMutationResponse>(`/api/task-reviews/${encodeURIComponent(reviewId)}/decisions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  captureMemory: (reviewId: string, payload: TaskReviewMemoryCapturePayload) =>
    apiRequest<MemoryCaptureResponse>(`/api/task-reviews/${encodeURIComponent(reviewId)}/memory-candidates`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  operations: (
    projectId: string,
    options: {
      calendarStart: string
      calendarEnd: string
      calendarPage: number
      calendarPageSize?: number
      queuePage: number
      queuePageSize?: number
      queueAgentId?: string | null
    },
  ) => {
    const params = new URLSearchParams({
      calendar_start: options.calendarStart,
      calendar_end: options.calendarEnd,
      calendar_page: String(options.calendarPage),
      calendar_page_size: String(options.calendarPageSize ?? 20),
      queue_page: String(options.queuePage),
      queue_page_size: String(options.queuePageSize ?? 20),
    })
    if (options.queueAgentId) params.set('queue_agent_id', options.queueAgentId)
    return apiRequest<TaskOperationsSnapshot>(
      `/api/task-operations/${encodeURIComponent(projectId)}?${params.toString()}`,
    )
  },
  taskOptions: (
    projectId: string,
    options: { query?: string; excludeTaskId?: string | null; page?: number; pageSize?: number } = {},
  ) => {
    const params = new URLSearchParams({
      page: String(options.page ?? 1),
      page_size: String(options.pageSize ?? 50),
    })
    if (options.query) params.set('query', options.query)
    if (options.excludeTaskId) params.set('exclude_task_id', options.excludeTaskId)
    return apiRequest<TaskOptionPage>(
      `/api/task-operations/${encodeURIComponent(projectId)}/task-options?${params.toString()}`,
    )
  },
}
