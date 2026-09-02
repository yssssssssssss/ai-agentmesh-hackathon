import type { components } from '../../api/generated/schema'

type GeneratedManagedTask = components['schemas']['TaskManagementViewV1']
type GeneratedTask = components['schemas']['Task']
type GeneratedManagement = components['schemas']['TaskManagementMetadataV1']

export type TaskManagementAction = components['schemas']['TaskManagementAction']
export type ManagedTask = Omit<GeneratedManagedTask, 'task' | 'management' | 'allowed_actions'> & {
  task: GeneratedTask & { id: string }
  management: Omit<GeneratedManagement, 'tags'> & { tags: string[] }
  allowed_actions: TaskManagementAction[]
}
export type ManagedTaskPage = Omit<components['schemas']['TaskManagementPageV1'], 'items'> & {
  items: ManagedTask[]
}
export type ManagedTaskDetail = Omit<components['schemas']['TaskManagementDetailV1'], 'item' | 'reviews'> & {
  item: ManagedTask
  reviews: TaskReviewView[]
}
export type TaskRunSummary = Omit<components['schemas']['TaskRunSummaryV1'], 'can_submit_review'> & {
  can_submit_review: boolean
}
export type TaskArtifactSummary = components['schemas']['TaskArtifactSummaryV1']
export type TaskReviewAllowedAction = components['schemas']['TaskReviewAllowedAction']
export type TaskReview = Omit<components['schemas']['TaskReviewV1'], 'id'> & { id: string }
export type TaskReviewView = Omit<components['schemas']['TaskReviewViewV1'], 'allowed_actions' | 'review'> & {
  review: TaskReview
  allowed_actions: TaskReviewAllowedAction[]
}
export type TaskReviewSubmitPayload = components['schemas']['TaskReviewSubmitRequest']
export type TaskReviewDecisionPayload = components['schemas']['TaskReviewDecisionRequest']
export type TaskReviewMutationResponse = Omit<components['schemas']['TaskReviewMutationResponseV1'], 'item'> & {
  item: TaskReviewView
}
export type TaskCreatePayload = components['schemas']['TaskCreateRequest']
export type TaskUpdatePayload = components['schemas']['TaskUpdateRequest']
export type TaskTransitionPayload = components['schemas']['TaskTransitionRequest']
export type TaskArchivePayload = components['schemas']['TaskArchiveRequest']
export type TaskManagementMetadata = components['schemas']['TaskManagementMetadataV1']
export type TaskDeliveryStage = components['schemas']['TaskDeliveryStage']
export type TaskPriority = components['schemas']['TaskPriority']
export type TaskType = components['schemas']['TaskType']
export type TaskAssigneeKind = components['schemas']['TaskAssigneeKind']
