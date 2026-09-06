import type { components } from '../../api/generated/schema'

type GeneratedManagedTask = components['schemas']['TaskManagementViewV1']
type GeneratedTask = components['schemas']['Task']
type GeneratedManagement = components['schemas']['TaskManagementMetadataV1']

export type TaskManagementAction = components['schemas']['TaskManagementAction']
export type ManagedTask = Omit<GeneratedManagedTask, 'task' | 'management' | 'readiness' | 'allowed_actions'> & {
  task: GeneratedTask & { id: string }
  management: Omit<GeneratedManagement, 'tags' | 'dependency_task_ids'> & {
    tags: string[]
    dependency_task_ids: string[]
  }
  readiness: Omit<components['schemas']['TaskReadinessV1'], 'blocking_task_ids'> & {
    blocking_task_ids: string[]
  }
  allowed_actions: TaskManagementAction[]
}
export type ManagedTaskPage = Omit<components['schemas']['TaskManagementPageV1'], 'items'> & {
  items: ManagedTask[]
}
export type ManagedTaskDetail = Omit<
  components['schemas']['TaskManagementDetailV1'],
  'item' | 'reviews' | 'dependency_tasks' | 'child_tasks'
> & {
  item: ManagedTask
  reviews: TaskReviewView[]
  dependency_tasks: TaskRelationshipSummary[]
  child_tasks: TaskRelationshipSummary[]
}
export type TaskRelationshipSummary = components['schemas']['TaskRelationshipSummaryV1']
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
export type TaskReviewMemoryCapturePayload = components['schemas']['TaskReviewMemoryCaptureRequest']
export type MemoryCaptureResponse = components['schemas']['MemoryCaptureResponseV1']
export type TaskMemoryLink = components['schemas']['TaskMemoryLinkV1']
export type TaskCreatePayload = components['schemas']['TaskCreateRequest']
export type TaskUpdatePayload = components['schemas']['TaskUpdateRequest']
export type TaskTransitionPayload = components['schemas']['TaskTransitionRequest']
export type TaskArchivePayload = components['schemas']['TaskArchiveRequest']
export type TaskManagementMetadata = components['schemas']['TaskManagementMetadataV1']
export type TaskDeliveryStage = components['schemas']['TaskDeliveryStage']
export type TaskPriority = components['schemas']['TaskPriority']
export type TaskType = components['schemas']['TaskType']
export type TaskAssigneeKind = components['schemas']['TaskAssigneeKind']
export type TaskReadiness = Omit<components['schemas']['TaskReadinessV1'], 'blocking_task_ids'> & {
  blocking_task_ids: string[]
}
export type TaskReadinessState = components['schemas']['TaskReadinessState']
type GeneratedOperationsTask = components['schemas']['TaskOperationsTaskV1']
export type TaskOperationsTask = Omit<GeneratedOperationsTask, 'dependency_task_ids' | 'readiness'> & {
  dependency_task_ids: string[]
  readiness: TaskReadiness
}
type OperationsMilestone = Omit<components['schemas']['TaskMilestoneV1'], 'task'> & { task: TaskOperationsTask }
type OperationsCalendarItem = Omit<components['schemas']['TaskCalendarItemV1'], 'task'> & { task: TaskOperationsTask }
type OperationsQueueItem = Omit<components['schemas']['AgentQueueItemV1'], 'task'> & { task: TaskOperationsTask }
type OperationsMetrics = Omit<
  components['schemas']['TaskOperationsMetricsV1'],
  'tasks_by_stage' | 'tasks_by_readiness' | 'runs_by_status' | 'reviews_by_status'
> & {
  tasks_by_stage: Record<string, number>
  tasks_by_readiness: Record<string, number>
  runs_by_status: Record<string, number>
  reviews_by_status: Record<string, number>
}
export type TaskOperationsSnapshot = Omit<
  components['schemas']['TaskOperationsSnapshotV1'],
  'metrics' | 'critical_dependency_chain' | 'milestones' | 'calendar' | 'agent_queue'
> & {
  metrics: OperationsMetrics
  critical_dependency_chain: TaskOperationsTask[]
  milestones: OperationsMilestone[]
  calendar: Omit<components['schemas']['TaskCalendarPageV1'], 'items'> & { items: OperationsCalendarItem[] }
  agent_queue: Omit<components['schemas']['AgentQueuePageV1'], 'items'> & { items: OperationsQueueItem[] }
}
export type TaskOption = components['schemas']['TaskOptionV1']
export type TaskOptionPage = components['schemas']['TaskOptionPageV1']
export type AgentQueueState = components['schemas']['AgentQueueState']
