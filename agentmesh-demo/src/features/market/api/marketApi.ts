import { apiRequest } from '../../../api/client'
import type { MarketActivityFeed, MarketMeView } from '../types'

export const marketApi = {
  me: () => apiRequest<MarketMeView>('/api/market/me'),
  activity: () => apiRequest<MarketActivityFeed>('/api/market/activity'),
  resolveDelegated: (inboxItemId: string, action: 'approve' | 'deny') =>
    apiRequest<{ status: string; answer: string | null; citations: string[] }>(
      `/api/market/delegated-answers/${encodeURIComponent(inboxItemId)}/resolve?action=${action}`,
      { method: 'POST' },
    ),
  adopt: (helperId: string, question: string) =>
    apiRequest<{ point_id: string; awarded_to: string; relation_id: string }>(
      `/api/market/delegated-answers/adopt?helper_id=${encodeURIComponent(helperId)}&question=${encodeURIComponent(question)}`,
      { method: 'POST' },
    ),
}
