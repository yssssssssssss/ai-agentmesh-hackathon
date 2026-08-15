import { useQuery } from '@tanstack/react-query'
import { marketApi } from './marketApi'

export interface MarketMeContext {
  userId: string
  workspaceId: string
}

export const marketKeys = {
  root: ['market'] as const,
  me: (context: MarketMeContext) => ['market', 'me', context.userId, context.workspaceId] as const,
}

/** Personal-view aggregation for /market page. Polls every 30s while mounted. */
export function useMarketMe(context: MarketMeContext, enabled = true) {
  return useQuery({
    queryKey: marketKeys.me(context),
    queryFn: () => marketApi.me(),
    enabled: enabled && !!context.userId,
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  })
}
