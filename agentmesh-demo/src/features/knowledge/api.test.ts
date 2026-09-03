import { afterEach, describe, expect, it, vi } from 'vitest'

import { knowledgeApi } from './api'

const jsonResponse = (payload: unknown) => new Response(JSON.stringify(payload), {
  status: 200,
  headers: { 'Content-Type': 'application/json' },
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('knowledgeApi.resolveToolApproval', () => {
  it.each(['approve', 'reject'] as const)('posts one call-scoped %s decision using the Inbox route contract', async (action) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      item: { id: 'inbox/1', status: 'open' },
      run_id: 'run-1',
      waiting_approval: true,
    }))
    vi.stubGlobal('fetch', fetchMock)

    await knowledgeApi.resolveToolApproval('inbox/1', 'call id/2', action)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/inbox/inbox%2F1/resolve-tool-approval?action=${action}&call_id=call%20id%2F2`,
      expect.objectContaining({ method: 'POST', credentials: 'same-origin' }),
    )
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined()
  })
})

describe('knowledgeApi Memory governance', () => {
  it('loads active memory and server-filtered governance history separately', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 100, has_next: false }))
    vi.stubGlobal('fetch', fetchMock)

    await knowledgeApi.memory('project/1')
    await knowledgeApi.governance('project/1', {
      page: 2,
      pageSize: 25,
      status: 'deprecated',
      scope: 'team_accepted',
      kind: 'team_knowledge',
      layer: 'all',
    })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/memory/entries?project_id=project%2F1&page_size=100',
    )
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/memory/entries?project_id=project%2F1&include_archived=true&page=2&page_size=25&status=deprecated&scope=team_accepted&kind=team_knowledge',
    )
  })

  it('posts revision and lifecycle commands with stable caller-provided identities', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ item: { id: 'memory-1' } }))
    vi.stubGlobal('fetch', fetchMock)

    await knowledgeApi.createMemoryRevision({
      memoryId: 'memory/1',
      payload: {
        command_id: 'revision-command',
        expected_version: 2,
        title: 'Revised title',
        summary: 'Revised summary',
        memory_type: 'method',
      },
    })
    await knowledgeApi.transitionMemory({
      memoryId: 'memory/1',
      payload: {
        command_id: 'transition-command',
        expected_version: 2,
        action: 'dispute',
      },
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/memory/memory%2F1/revisions')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      command_id: 'revision-command',
      expected_version: 2,
    })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/memory/memory%2F1/transitions')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toEqual({
      command_id: 'transition-command',
      expected_version: 2,
      action: 'dispute',
    })
  })
})

describe('knowledgeApi.decideMemoryReview', () => {
  it('posts a versioned independent Memory Review decision', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      item: { id: 'memory-1', version: 2, status: 'accepted' },
      memory_review: { review: { id: 'review-1', status: 'accepted' } },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await knowledgeApi.decideMemoryReview({
      reviewId: 'review/1',
      commandId: 'decision-1',
      expectedMemoryVersion: 1,
      expectedReviewVersion: 1,
      decision: 'accepted',
      decisionNote: '可复用。',
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/memory-reviews/review%2F1/decisions')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual({
      command_id: 'decision-1',
      expected_memory_version: 1,
      expected_review_version: 1,
      decision: 'accepted',
      decision_note: '可复用。',
    })
  })
})
