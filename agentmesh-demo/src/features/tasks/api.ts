import { apiRequest } from '../../api/client'
import type {
  ManagedTask,
  ManagedTaskDetail,
  ManagedTaskPage,
  MemoryCaptureResponse,
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
  list: async (projectId: string) => {
    const pageSize = 100
    const items: ManagedTask[] = []
    let page = 1
    let response: ManagedTaskPage
    do {
      response = await apiRequest<ManagedTaskPage>(
        `/api/tasks?project_id=${encodeURIComponent(projectId)}&page=${page}&page_size=${pageSize}`,
      )
      items.push(...response.items)
      page += 1
    } while (response.has_next && page <= 100)
    if (response.has_next) throw new Error('task_page_limit_exceeded')
    return { ...response, items, page: 1, page_size: pageSize, has_next: false }
  },
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
}
