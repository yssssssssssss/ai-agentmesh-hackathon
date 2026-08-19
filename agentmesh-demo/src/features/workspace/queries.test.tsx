import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { workspaceKeys } from './keys'
import { useRetryAgentRunMutation } from './queries'
import type { WorkspaceScope } from './types'

const scope: WorkspaceScope = {
  userId: 'user-1',
  workspaceId: 'workspace-1',
  projectId: 'project-1',
}

const jsonResponse = (payload: unknown) => new Response(JSON.stringify(payload), {
  status: 202,
  headers: { 'Content-Type': 'application/json' },
})

function retryMutation(queryClient: QueryClient) {
  const captured: { current?: ReturnType<typeof useRetryAgentRunMutation> } = {}

  function Harness() {
    captured.current = useRetryAgentRunMutation(scope)
    return null
  }

  renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  )
  if (!captured.current) throw new Error('Retry mutation was not created')
  return captured.current
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Agent Run retry mutation', () => {
  it('reuses its caller-owned turn id after a lost response and invalidates the canonical thread', async () => {
    const response = {
      item: {
        id: 'run-retried',
        thread_id: 'thread-1',
        user_id: scope.userId,
        workspace_id: scope.workspaceId,
        project_id: scope.projectId,
        input_text: 'retry this run',
        client_turn_id: 'turn-retry-stable',
        status: 'waiting_plan_approval',
        plan_id: 'plan-retried',
        orchestration_mode: 'execute',
        agent_definition_version: '1',
        project_chat: true,
        tool_call_count: 0,
      },
    }
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('response lost'))
      .mockResolvedValueOnce(jsonResponse(response))
    vi.stubGlobal('fetch', fetchMock)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    queryClient.setQueryData(workspaceKeys.thread(scope, 'thread-1'), { messages: [] })
    queryClient.setQueryData(workspaceKeys.threads(scope), { items: [] })
    const retry = retryMutation(queryClient)
    const input = { runId: 'run-original', clientTurnId: 'turn-retry-stable' }

    await expect(retry.mutateAsync(input)).rejects.toThrow('response lost')
    await retry.mutateAsync(input)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    for (const [path, init] of fetchMock.mock.calls) {
      expect(path).toBe('/api/agent/runs/run-original/retry')
      expect(JSON.parse(String(init.body))).toEqual({ client_turn_id: 'turn-retry-stable' })
    }
    expect(queryClient.getQueryState(workspaceKeys.thread(scope, 'thread-1'))?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(workspaceKeys.threads(scope))?.isInvalidated).toBe(true)
    expect(queryClient.getQueryData(workspaceKeys.run(scope, 'run-retried'))).toEqual(response)
  })
})
