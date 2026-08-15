import { apiRequest } from '../../../api/client'
import type { MarketMeView } from '../types'

export const marketApi = {
  me: () => apiRequest<MarketMeView>('/api/market/me'),
}
