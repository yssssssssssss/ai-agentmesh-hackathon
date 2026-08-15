import { useQuery } from '@tanstack/react-query'

import { apiRequest } from '../../api/client'
import { queryKeys } from '../../app/queryKeys'
import type { components } from '../../api/generated/schema'

export type ActivityTodayResponse = components['schemas']['ActivityTodayResponse']
export type AuditListResponse = components['schemas']['AuditListResponse']
export type BlackboardTaskCardsResponse = components['schemas']['BlackboardTaskCardsResponse']
export type MemoryOverviewResponse = components['schemas']['MemoryOverviewResponse']

export function useInsightsReadModel(context: {
  userId: string
  workspaceId: string
  projectId: string
}) {
  const tasks = useQuery({
    queryKey: queryKeys.insights.tasks(context.userId, context.workspaceId, context.projectId),
    queryFn: () =>
      apiRequest<BlackboardTaskCardsResponse>(
        `/api/blackboard/task-cards?project_id=${encodeURIComponent(context.projectId)}`,
      ),
  })
  const activity = useQuery({
    queryKey: queryKeys.insights.activity(context.userId, context.workspaceId, context.projectId),
    queryFn: () =>
      apiRequest<ActivityTodayResponse>(
        `/api/activity/today?project_id=${encodeURIComponent(context.projectId)}`,
      ),
  })
  const memory = useQuery({
    queryKey: queryKeys.insights.memory(context.userId, context.workspaceId, context.projectId),
    queryFn: () =>
      apiRequest<MemoryOverviewResponse>(
        `/api/memory/overview?project_id=${encodeURIComponent(context.projectId)}`,
      ),
  })
  const audit = useQuery({
    queryKey: queryKeys.insights.audit(context.userId, context.workspaceId, context.projectId),
    queryFn: () =>
      apiRequest<AuditListResponse>(
        `/api/insights/audit?project_id=${encodeURIComponent(context.projectId)}&limit=20`,
      ),
  })

  return { tasks, activity, memory, audit }
}
