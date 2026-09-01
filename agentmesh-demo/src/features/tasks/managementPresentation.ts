import type { TaskDeliveryStage, TaskPriority } from './types'

export const TASK_DELIVERY_STAGE_LABELS: Record<TaskDeliveryStage, string> = {
  backlog: '待办',
  planned: '已计划',
  in_progress: '进行中',
  review: '待审核',
  done: '已完成',
  cancelled: '已取消',
}

export const TASK_PRIORITY_LABELS: Record<TaskPriority, string> = {
  p0: 'P0',
  p1: 'P1',
  p2: 'P2',
  p3: 'P3',
}

export function taskDeliveryStageLabel(stage: TaskDeliveryStage): string {
  return TASK_DELIVERY_STAGE_LABELS[stage]
}
