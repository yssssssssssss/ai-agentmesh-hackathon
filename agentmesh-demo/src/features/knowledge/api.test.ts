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
