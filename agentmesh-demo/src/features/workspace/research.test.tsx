import { QueryClient } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { workspaceApi } from './api'
import { workspaceKeys } from './keys'
import { invalidateAgentRunEvent } from './queries'
import type { AgentRun, ResearchRunProjection, WorkspaceScope } from './types'

const scope: WorkspaceScope = {
  userId: 'user-1',
  workspaceId: 'workspace-1',
  projectId: 'project-1',
}

const researchRun = {
  id: 'run/research-1',
  thread_id: 'thread-1',
  user_id: scope.userId,
  workspace_id: scope.workspaceId,
  project_id: scope.projectId,
  input_text: '比较 Figma 和 Miro',
  status: 'waiting_plan_approval',
  orchestration_version: 'research-v2',
  orchestration_mode: 'preview',
  agent_definition_version: '1',
  project_chat: true,
  tool_call_count: 0,
} satisfies AgentRun

const projection = {
  run_id: researchRun.id,
  orchestration_version: 'research-v2',
  status: 'waiting_plan_approval',
  error_code: null,
  workflow: {
    phase: 'planning',
    active_gate: 'plan_confirmation',
    state_version: 2,
  },
  requirement: null,
  plans: [],
  attempt: null,
  gaps: [],
  artifacts: {},
  provenance: {},
  recovery: null,
} satisfies ResearchRunProjection

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('research-v2 Workspace data flow', () => {
  it('reads the owner-scoped aggregate projection from the run research endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(projection), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(workspaceApi.researchRun(researchRun.id)).resolves.toEqual(projection)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/runs/run%2Fresearch-1/research')
  })

  it('sends research mutations to the versioned control plane with idempotency headers', async () => {
    const response = {
      run_id: researchRun.id,
      command_type: 'confirm_plan',
      state_version: 3,
      accepted: true,
      replayed: false,
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), {
      status: 202,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await workspaceApi.confirmResearchPlan(
      researchRun.id,
      'plan/1',
      { expected_state_version: 2 },
      'web-confirm-plan-v2',
    )
    await workspaceApi.executeResearch(
      researchRun.id,
      { expected_state_version: 3 },
      'web-execute-v3',
    )
    await workspaceApi.recoverResearch(
      researchRun.id,
      { expected_state_version: 5, invocation_id: 'invocation/1', action: 'retry' },
      'web-recover-retry-v5',
    )
    await workspaceApi.resolveResearchToolApproval('inbox/1', 'call id/1', 'approve')

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/api/agent/runs/run%2Fresearch-1/research/plans/plan%2F1/confirm',
      '/api/agent/runs/run%2Fresearch-1/research/execute',
      '/api/agent/runs/run%2Fresearch-1/research/recover',
      '/api/inbox/inbox%2F1/resolve-tool-approval?action=approve&call_id=call%20id%2F1',
    ])
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get('Idempotency-Key')).toBe('web-confirm-plan-v2')
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get('Idempotency-Key')).toBe('web-execute-v3')
    expect(new Headers(fetchMock.mock.calls[2][1].headers).get('Idempotency-Key')).toBe('web-recover-retry-v5')
  })

  it('invalidates the aggregate projection and coarse run when research SSE changes state', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const researchKey = workspaceKeys.research(scope, researchRun.id)
    const runKey = workspaceKeys.run(scope, researchRun.id)
    const planKey = workspaceKeys.plan(scope, researchRun.id)
    queryClient.setQueryData(researchKey, projection)
    queryClient.setQueryData(runKey, { item: researchRun })
    queryClient.setQueryData(planKey, { plan: {} })
    const refreshBootstrap = vi.fn(async () => undefined)

    await invalidateAgentRunEvent(queryClient, scope, researchRun, 'research_updated', refreshBootstrap)

    expect(queryClient.getQueryState(researchKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(runKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(planKey)?.isInvalidated).toBe(false)
    expect(refreshBootstrap).not.toHaveBeenCalled()
  })

  it('refreshes the final chat projection when a research run becomes terminal', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const threadKey = workspaceKeys.thread(scope, researchRun.thread_id)
    const threadsKey = workspaceKeys.threads(scope)
    queryClient.setQueryData(workspaceKeys.research(scope, researchRun.id), projection)
    queryClient.setQueryData(workspaceKeys.run(scope, researchRun.id), { item: researchRun })
    queryClient.setQueryData(threadKey, { messages: [] })
    queryClient.setQueryData(threadsKey, { items: [] })
    const refreshBootstrap = vi.fn(async () => undefined)

    await invalidateAgentRunEvent(queryClient, scope, researchRun, 'run_completed', refreshBootstrap)

    expect(queryClient.getQueryState(threadKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(threadsKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(workspaceKeys.run(scope, researchRun.id))?.isInvalidated).toBe(true)
    expect(refreshBootstrap).toHaveBeenCalledTimes(1)
  })

  it('preserves the existing v1 run and Skill Plan invalidation path', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const v1Run = { ...researchRun, id: 'run-v1', orchestration_version: 'v1' } satisfies AgentRun
    const runKey = workspaceKeys.run(scope, v1Run.id)
    const planKey = workspaceKeys.plan(scope, v1Run.id)
    queryClient.setQueryData(runKey, { item: v1Run })
    queryClient.setQueryData(planKey, { plan: {} })

    await invalidateAgentRunEvent(queryClient, scope, v1Run, 'plan_updated', vi.fn(async () => undefined))

    expect(queryClient.getQueryState(runKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(planKey)?.isInvalidated).toBe(true)
  })
})
