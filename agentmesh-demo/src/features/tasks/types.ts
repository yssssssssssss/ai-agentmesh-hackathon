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
export type ManagedTaskDetail = Omit<components['schemas']['TaskManagementDetailV1'], 'item'> & {
  item: ManagedTask
}
export type TaskRunSummary = components['schemas']['TaskRunSummaryV1']
export type TaskArtifactSummary = components['schemas']['TaskArtifactSummaryV1']
export type TaskCreatePayload = components['schemas']['TaskCreateRequest']
export type TaskUpdatePayload = components['schemas']['TaskUpdateRequest']
export type TaskTransitionPayload = components['schemas']['TaskTransitionRequest']
export type TaskArchivePayload = components['schemas']['TaskArchiveRequest']
export type TaskManagementMetadata = components['schemas']['TaskManagementMetadataV1']
export type TaskDeliveryStage = components['schemas']['TaskDeliveryStage']
export type TaskPriority = components['schemas']['TaskPriority']
export type TaskType = components['schemas']['TaskType']
export type TaskAssigneeKind = components['schemas']['TaskAssigneeKind']
