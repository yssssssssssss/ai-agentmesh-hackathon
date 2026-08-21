import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import candidatesFixture from '../../../../tests/fixtures/research_v3_workbench/candidates.json'
import { ResearchWorkbenchContainer } from '../research-workbench/ResearchWorkbenchContainer'
import { workspaceKeys } from './keys'
import { invalidateAgentRunEvent } from './queries'
import type { AgentRun, WorkspaceScope } from './types'

const scope: WorkspaceScope = {
  userId: 'user_gate2_preview_1',
  workspaceId: 'workspace_gate2',
  projectId: 'project_gate2',
}

const run = {
  id: 'run_gate2_preview',
  thread_id: 'thread_gate2_preview',
  user_id: scope.userId,
  workspace_id: scope.workspaceId,
  project_id: scope.projectId,
  input_text: 'Compare Alpha and Beta.',
  status: 'waiting_plan_approval',
  orchestration_version: 'research-v3',
  orchestration_mode: 'preview',
  writer_generation_epoch: 2,
  agent_definition_version: '1',
  project_chat: true,
  tool_call_count: 0,
} satisfies AgentRun

const repositoryProjection = {
  ...candidatesFixture,
  provenance: {
    ...candidatesFixture.provenance,
    source_kind: 'repository_projection',
    baseline_state_id: null,
  },
}

describe('research-current stored-version Workspace binding', () => {
  it('renders the accepted v3 Workbench with an explicit provider-free preview notice', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    })
    queryClient.setQueryData(workspaceKeys.research(scope, run.id), repositoryProjection)

    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <ResearchWorkbenchContainer scope={scope} run={run} />
      </QueryClientProvider>,
    )

    expect(html).toContain('Preview only')
    expect(html).toContain('未调用任何外部 Provider')
    expect(html).toContain('data-workbench-state="candidates"')
    expect(html).not.toContain('开始执行')
  })

  it('invalidates the v3 aggregate by stored orchestration version', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const researchKey = workspaceKeys.research(scope, run.id)
    const runKey = workspaceKeys.run(scope, run.id)
    queryClient.setQueryData(researchKey, repositoryProjection)
    queryClient.setQueryData(runKey, { item: run })

    await invalidateAgentRunEvent(
      queryClient,
      scope,
      run,
      'research_updated',
      vi.fn(async () => undefined),
    )

    expect(queryClient.getQueryState(researchKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(runKey)?.isInvalidated).toBe(true)
  })
})
