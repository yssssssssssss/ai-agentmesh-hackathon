import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { knowledgeApi } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('manual document commands', () => {
  it('saves the selected version and imports that explicit version separately', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ item: { id: 'doc/1', version: 2 } }), {
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    await knowledgeApi.updateDocument({ documentId: 'doc/1', expectedVersion: 1, text: 'revised text' })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents/doc%2F1')
    expect(fetchMock.mock.calls[0][1].method).toBe('PATCH')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ expected_version: 1, text: 'revised text' })
    await knowledgeApi.importDocument({ documentId: 'doc/1', expectedVersion: 2 })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/documents/doc%2F1/import-to-memory?expected_version=2')
    expect(fetchMock.mock.calls[1][1].method).toBe('POST')
  })

  it('keeps a stale version rejection visible instead of claiming an import succeeded', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'document_version_conflict' }), {
      status: 409, headers: { 'Content-Type': 'application/json' },
    })))
    await expect(knowledgeApi.importDocument({ documentId: 'doc', expectedVersion: 1 })).rejects.toBeInstanceOf(ApiError)
  })
})
