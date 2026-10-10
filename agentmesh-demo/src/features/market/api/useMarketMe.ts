import { useQuery } from '@tanstack/react-query'
import { marketApi } from './marketApi'

export interface MarketMeContext {
  userId: string
  workspaceId: string
  projectId: string
}

export const marketKeys = {
  root: ['market'] as const,
  me: (context: MarketMeContext) => ['market', 'me', context.userId, context.workspaceId, context.projectId] as const,
  activity: (context: MarketMeContext) => ['market', 'activity', context.userId, context.workspaceId, context.projectId] as const,
}

/** Personal-view aggregation for /market page. Polls every 30s while mounted. */
export function useMarketMe(context: MarketMeContext, enabled = true) {
  return useQuery({
    queryKey: marketKeys.me(context),
    queryFn: () => marketApi.me(context.projectId),
    enabled: enabled && !!context.userId && !!context.projectId,
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  })
}

/** Current-project activity, kept separate across account/project switches. */
export function useMarketActivity(context: MarketMeContext, enabled = true) {
  return useQuery({
    queryKey: marketKeys.activity(context),
    queryFn: () => marketApi.activity(context.projectId),
    enabled: enabled && !!context.userId && !!context.projectId,
    staleTime: 8_000,
    refetchInterval: 20_000,
    refetchOnWindowFocus: true,
  })
}
