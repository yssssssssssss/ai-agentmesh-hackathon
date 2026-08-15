import { useQuery } from '@tanstack/react-query'

import { apiRequest } from '../../api/client'
import { queryKeys } from '../../app/queryKeys'
import type { components } from '../../api/generated/schema'

export type ActivityTodayResponse = components['schemas']['ActivityTodayResponse']
export type Agent = components['schemas']['Agent']
export type MemoryOverviewResponse = components['schemas']['MemoryOverviewResponse']

export function useDigitalSelfReadModel(context: {
  userId: string
  workspaceId: string
  projectId: string
}) {
  const agent = useQuery({
    queryKey: queryKeys.digitalSelf.agent(context.userId, context.workspaceId, context.projectId),
    queryFn: () => apiRequest<Agent>('/api/agents/me'),
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

  return { agent, activity, memory }
}
