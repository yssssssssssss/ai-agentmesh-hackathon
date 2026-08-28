import { apiRequest } from '../../api/client'
import type { DeepSearchClarifyRequest, DeepSearchReport, DeepSearchState } from './types'

const pathId = (value: string) => encodeURIComponent(value)

export const deepSearchApi = {
  state: (runId: string) =>
    apiRequest<DeepSearchState>(`/api/agent/runs/${pathId(runId)}/deepsearch`),
  clarify: (runId: string, request: DeepSearchClarifyRequest) =>
    apiRequest<DeepSearchState>(`/api/agent/runs/${pathId(runId)}/deepsearch/clarify`, {
      method: 'POST',
      body: JSON.stringify(request),
    }),
  report: (artifactId: string) =>
    apiRequest<DeepSearchReport>(`/api/artifacts/${pathId(artifactId)}`),
}
