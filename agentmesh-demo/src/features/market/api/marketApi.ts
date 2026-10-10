import { apiRequest } from '../../../api/client'
import type { MarketActivityFeed, MarketMeView } from '../types'
import type { components } from '../../../api/generated/schema'

export type QueryView = components['schemas']['DelegatedQueryView']
export type QueryCreate = components['schemas']['DelegatedQueryCreate']
export type QueryConsent = components['schemas']['QueryConsentView']
export type QueryConsentCommand = components['schemas']['QueryConsentRequest']
export type QueryAdoptCommand = components['schemas']['QueryAdoptRequest']

export const marketApi = {
  me: (projectId: string) => apiRequest<MarketMeView>(`/api/market/me?project_id=${encodeURIComponent(projectId)}`),
  activity: (projectId: string) => apiRequest<MarketActivityFeed>(`/api/market/activity?project_id=${encodeURIComponent(projectId)}`),
  queries: (projectId: string) => apiRequest<{ items: QueryView[] }>(
    `/api/market/queries?project_id=${encodeURIComponent(projectId)}`,
  ),
  query: (id: string) => apiRequest<QueryView>(`/api/market/queries/${encodeURIComponent(id)}`),
  createQuery: (request: QueryCreate) => apiRequest<QueryView>('/api/market/queries', {
    method: 'POST', body: JSON.stringify(request),
  }),
  resolveQuery: (id: string, action: 'approve' | 'deny', version: number) =>
    apiRequest<QueryView>(`/api/market/queries/${encodeURIComponent(id)}/resolve`, {
      method: 'POST', body: JSON.stringify({ action, expected_version: version }),
    }),
  resumeQuery: (id: string) => apiRequest<QueryView>(`/api/market/queries/${encodeURIComponent(id)}/resume`, { method: 'POST' }),
  adoptQuery: (id: string, request: QueryAdoptCommand) =>
    apiRequest<components['schemas']['QueryAdoptionV1']>(`/api/market/queries/${encodeURIComponent(id)}/adopt`, {
      method: 'POST', body: JSON.stringify(request),
    }),
  consents: (projectId: string) => apiRequest<{ items: QueryConsent[] }>(
    `/api/market/query-consents?project_id=${encodeURIComponent(projectId)}`,
  ),
  setConsent: (request: QueryConsentCommand) => apiRequest<QueryConsent>('/api/market/query-consents', {
    method: 'PUT', body: JSON.stringify(request),
  }),
  resolveDelegated: (inboxItemId: string, action: 'approve' | 'deny') =>
    apiRequest<{ status: string; answer: string | null; citations: string[] }>(
      `/api/market/delegated-answers/${encodeURIComponent(inboxItemId)}/resolve?action=${action}`,
      { method: 'POST' },
    ),
}
