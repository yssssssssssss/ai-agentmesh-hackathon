import { describe, expect, it, vi } from 'vitest'

import idleFixture from '../../../../tests/fixtures/research_v3_workbench/idle.json'
import {
  buildResearchV3Request,
  createResearchV3ApiClient,
  researchV3AggregateQuery,
  researchV3IdempotencyKey,
} from './apiClient'

const repositoryFixture = {
  ...idleFixture,
  provenance: {
    ...idleFixture.provenance,
    source_kind: 'repository_projection',
    baseline_state_id: null,
  },
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('feature-local research-v3 API client', () => {
  it('reads and refreshes only exact repository projections', async () => {
    const fetcher = vi.fn(async () => jsonResponse(repositoryFixture)) as unknown as typeof fetch
    const client = createResearchV3ApiClient(fetcher)

    const aggregate = await client.readAggregate('run_1')
    const refreshed = await client.refreshAggregate('run_1')
    const query = researchV3AggregateQuery(client, 'run_1')

    expect(aggregate.provenance.source_kind).toBe('repository_projection')
    expect(refreshed).toEqual(aggregate)
    expect(fetcher).toHaveBeenNthCalledWith(1, '/api/agent/runs/run_1/research', {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    expect(fetcher).toHaveBeenNthCalledWith(2, '/api/agent/runs/run_1/research/refresh', {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    expect(query.queryKey).toEqual(['research-v3-aggregate', 'run_1'])
    expect(client.planStreamUrl('run_1', 7)).toBe(
      '/api/agent/runs/run_1/research/plan/stream?after_state_version=7',
    )
  })

  it('rejects isolated fixtures and unknown aggregate fields at the client boundary', async () => {
    const fixtureClient = createResearchV3ApiClient(
      vi.fn(async () => jsonResponse(idleFixture)) as unknown as typeof fetch,
    )
    const extraClient = createResearchV3ApiClient(
      vi.fn(async () => jsonResponse({ ...repositoryFixture, ambient_state: true })) as unknown as typeof fetch,
    )

    await expect(fixtureClient.readAggregate('run_1')).rejects.toThrow(
      'research-v3 API accepts only authoritative repository projections',
    )
    await expect(extraClient.readAggregate('run_1')).rejects.toThrow(
      'Invalid research-workbench-aggregate-v1',
    )
  })

  it('builds the same canonical request hash as the backend contract', () => {
    const request = buildResearchV3Request('run_1', 'select_candidate', {
      expected_state_version: 1,
      candidate_id: 'speed',
    })

    expect(request.request_hash).toBe('4598956c53d7cf83ee0c324e97fa82ee4ee86eec8cd15d3a6249114974edcc35')
    expect(researchV3IdempotencyKey('select_candidate', request)).toBe(
      'web:select_candidate:1:4598956c53d7cf83ee0c324e',
    )
  })

  it('rejects a mutation receipt that is not bound to the submitted command', async () => {
    const request = {
      expected_state_version: 4,
      request_hash: 'a'.repeat(64),
      plan_version_id: 'plan_1',
    }
    const fetcher = vi.fn(async () => jsonResponse({
      run_id: 'run_other',
      command_type: 'execute',
      request_hash: request.request_hash,
      previous_state_version: 4,
      state_version: 5,
      accepted: true,
      replayed: false,
    }, 202)) as unknown as typeof fetch
    const client = createResearchV3ApiClient(fetcher)

    await expect(client.mutate('run_1', 'execute', 'execute.1', request)).rejects.toThrow(
      'research-v3 mutation response is invalid',
    )
  })

  it('sends the idempotency contract and validates the exact mutation receipt', async () => {
    const response = {
      run_id: 'run_1',
      command_type: 'execute',
      request_hash: 'a'.repeat(64),
      previous_state_version: 4,
      state_version: 5,
      accepted: true,
      replayed: false,
    }
    const fetcher = vi.fn(async () => jsonResponse(response, 202)) as unknown as typeof fetch
    const client = createResearchV3ApiClient(fetcher)
    const request = {
      expected_state_version: 4,
      request_hash: 'a'.repeat(64),
      plan_version_id: 'plan_1',
    }

    await expect(client.mutate('run_1', 'execute', 'execute.1', request)).resolves.toEqual(response)
    expect(fetcher).toHaveBeenCalledWith('/api/agent/runs/run_1/research/execute', {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'Idempotency-Key': 'execute.1',
      },
      body: JSON.stringify(request),
    })
  })
})
