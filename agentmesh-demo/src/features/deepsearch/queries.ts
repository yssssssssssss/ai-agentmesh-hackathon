import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { workspaceKeys } from '../workspace/keys'
import type { AgentRun, WorkspaceScope } from '../workspace/types'
import { deepSearchApi } from './api'
import type { DeepSearchClarifyRequest, DeepSearchState } from './types'

export function useDeepSearchStateQuery(
  scope: WorkspaceScope,
  run: AgentRun | null | undefined,
) {
  const runId = run?.planning_mode === 'deepsearch' ? run.id : null
  return useQuery({
    queryKey: workspaceKeys.deepSearch(scope, runId ?? 'none'),
    queryFn: () => deepSearchApi.state(runId ?? ''),
    enabled: Boolean(runId),
  })
}

export function useDeepSearchClarificationMutation(scope: WorkspaceScope, runId: string | null) {
  const queryClient = useQueryClient()
  const refresh = async () => {
    if (!runId) return
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: workspaceKeys.deepSearch(scope, runId), exact: true }),
      queryClient.invalidateQueries({ queryKey: workspaceKeys.run(scope, runId), exact: true }),
    ])
  }

  return useMutation({
    mutationFn: (request: DeepSearchClarifyRequest) => {
      if (!runId) throw new Error('缺少 DeepSearch Run')
      return deepSearchApi.clarify(runId, request)
    },
    onSuccess: (state: DeepSearchState) => {
      queryClient.setQueryData(workspaceKeys.deepSearch(scope, state.run.id), state)
      queryClient.setQueryData(workspaceKeys.run(scope, state.run.id), { item: state.run })
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) await refresh()
    },
  })
}

export function useDeepSearchReportQuery(
  scope: WorkspaceScope,
  runId: string | null,
  artifactId: string | null | undefined,
) {
  return useQuery({
    queryKey: workspaceKeys.deepSearchReport(scope, runId ?? 'none', artifactId ?? 'none'),
    queryFn: async () => {
      const report = await deepSearchApi.report(artifactId ?? '')
      if (report.run_id !== runId) throw new Error('报告与当前 DeepSearch Run 不匹配')
      return report
    },
    enabled: Boolean(runId && artifactId),
    staleTime: Infinity,
  })
}
