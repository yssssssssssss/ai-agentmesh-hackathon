import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import { workspaceKeys } from './keys'
import {
  isRetiredResearchRun,
  shouldSubscribeToAgentRunEvents,
  useRetryAgentRunMutation,
  useSkillPlanMutations,
  workspaceErrorMessage,
} from './queries'
import type { AgentRun, WorkspaceScope } from './types'

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

function planMutations(queryClient: QueryClient, deepSearch: boolean) {
  const captured: { current?: ReturnType<typeof useSkillPlanMutations> } = {}

  function Harness() {
    captured.current = useSkillPlanMutations(scope, 'run-1', deepSearch)
    return null
  }

  renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  )
  if (!captured.current) throw new Error('Plan mutations were not created')
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

describe('workspaceErrorMessage', () => {
  it('shows a safe structured API error message', () => {
    const error = new ApiError(
      503,
      { code: 'tool_runtime_not_real', message: 'Web Research 未连接真实 Provider，请完成配置后重试。' },
      {},
    )

    expect(workspaceErrorMessage(error)).toBe('Web Research 未连接真实 Provider，请完成配置后重试。')
  })
})

describe('Plan response adapters', () => {
  it('keeps a DeepSearch Plan response out of the standard Plan cache', async () => {
    const response = {
      plan: { requirement_version_id: 'requirement-1' },
      results: [],
      synthesis: null,
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(response)))
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const standardPlan = { marker: 'standard-plan' }
    queryClient.setQueryData(workspaceKeys.plan(scope, 'run-1'), standardPlan)
    queryClient.setQueryData(workspaceKeys.deepSearch(scope, 'run-1'), { marker: 'deepsearch-state' })

    await planMutations(queryClient, true).update.mutateAsync({
      expected_version: 1,
      selected_skill_ids: ['skill-1'],
      preferred_order: ['skill-1'],
    })

    expect(queryClient.getQueryData(workspaceKeys.plan(scope, 'run-1'))).toEqual(standardPlan)
    expect(queryClient.getQueryState(workspaceKeys.deepSearch(scope, 'run-1'))?.isInvalidated).toBe(true)
  })

  it('rejects a Plan response for the wrong planning mode', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      plan: { planning_mode: 'standard', requirement_version_id: null },
    })))
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })

    await expect(planMutations(queryClient, true).update.mutateAsync({
      expected_version: 1,
      selected_skill_ids: ['skill-1'],
      preferred_order: ['skill-1'],
    })).rejects.toThrow('Plan 响应与当前运行模式不匹配')
  })
})

describe('retired research runs', () => {
  const run = {
    id: 'run-retired',
    thread_id: 'thread-1',
    user_id: scope.userId,
    workspace_id: scope.workspaceId,
    project_id: scope.projectId,
    input_text: 'legacy research',
    status: 'running',
    planning_mode: 'standard',
    orchestration_version: 'v1',
    orchestration_mode: 'execute',
    agent_definition_version: '1',
    project_chat: true,
    tool_call_count: 0,
  } satisfies AgentRun

  it('classifies both frozen generations as retired', () => {
    expect(isRetiredResearchRun({ ...run, orchestration_version: 'research-v2' })).toBe(true)
    expect(isRetiredResearchRun({ ...run, orchestration_version: 'research-v3' })).toBe(true)
    expect(isRetiredResearchRun(run)).toBe(false)
  })

  it('never subscribes to events for a retired generation', () => {
    expect(shouldSubscribeToAgentRunEvents({ ...run, orchestration_version: 'research-v3' })).toBe(false)
    expect(shouldSubscribeToAgentRunEvents({ ...run, orchestration_version: 'research-v2' })).toBe(false)
    expect(shouldSubscribeToAgentRunEvents(run)).toBe(true)
    expect(shouldSubscribeToAgentRunEvents({ ...run, status: 'completed' })).toBe(false)
  })
})
