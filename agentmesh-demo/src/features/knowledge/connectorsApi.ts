import { apiRequest } from '../../api/client'
import type { components } from '../../api/generated/schema'

export type ConnectorStatus = components['schemas']['ConnectorStatusV1']
export type ConnectorCursor = components['schemas']['ConnectorSyncCursorV1']
export type ConnectorSyncRequest = components['schemas']['ConnectorSyncRequestV1']
export type ConnectorControlRequest = components['schemas']['ConnectorControlRequestV1']

export const connectorsApi = {
  status: (projectId: string) => apiRequest<components['schemas']['ConnectorStatusListV1']>(
    `/api/projects/${encodeURIComponent(projectId)}/connectors`,
  ),
  sync: (projectId: string, provider: ConnectorStatus['provider'], request: ConnectorSyncRequest) =>
    apiRequest<ConnectorCursor>(`/api/projects/${encodeURIComponent(projectId)}/connectors/${provider}/sync`, {
      method: 'POST', body: JSON.stringify(request),
    }),
  control: (projectId: string, cursorId: string, request: ConnectorControlRequest) =>
    apiRequest<ConnectorCursor>(`/api/projects/${encodeURIComponent(projectId)}/connectors/${encodeURIComponent(cursorId)}/control`, {
      method: 'POST', body: JSON.stringify(request),
    }),
}
