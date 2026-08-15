import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  advanceSessionGeneration,
  apiRequest,
  onUnauthorized,
} from './client'

const jsonResponse = (status: number, payload: unknown) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

describe('apiRequest', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('uses same-origin credentials and adds JSON content type for JSON bodies', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)

    await apiRequest('/api/example', { method: 'POST', body: JSON.stringify({ value: 1 }) })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/example',
      expect.objectContaining({
        credentials: 'same-origin',
        headers: expect.any(Headers),
      }),
    )
    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('lets the browser set multipart boundaries for FormData', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)
    const body = new FormData()
    body.append('file', new Blob(['content']), 'example.txt')

    await apiRequest('/api/documents/upload', { method: 'POST', body })

    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.has('Content-Type')).toBe(false)
  })

  it('throws a structured ApiError and notifies unauthorized subscribers on 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'Session expired' })))
    const unauthorized = vi.fn()
    const unsubscribe = onUnauthorized(unauthorized)

    await expect(apiRequest('/api/bootstrap')).rejects.toEqual(
      expect.objectContaining({ status: 401, detail: 'Session expired' }),
    )
    expect(unauthorized).toHaveBeenCalledTimes(1)
    unsubscribe()
  })

  it('reports the captured generation when an old request returns 401 after a new session starts', async () => {
    let resolveResponse!: (response: Response) => void
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(
        () =>
          new Promise<Response>((resolve) => {
            resolveResponse = resolve
          }),
      ),
    )
    const unauthorized = vi.fn()
    const unsubscribe = onUnauthorized(unauthorized)
    const oldGeneration = advanceSessionGeneration()
    const oldRequest = apiRequest('/api/bootstrap')

    const newGeneration = advanceSessionGeneration()
    resolveResponse(jsonResponse(401, { detail: 'Old session expired' }))

    await expect(oldRequest).rejects.toEqual(expect.objectContaining({ status: 401 }))
    expect(newGeneration).toBeGreaterThan(oldGeneration)
    expect(unauthorized).toHaveBeenCalledWith(oldGeneration)
    unsubscribe()
  })

  it('aborts an in-flight request when the session generation advances', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((_path: string, init: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true })
        })
      }),
    )
    advanceSessionGeneration()
    const staleRequest = apiRequest('/api/bootstrap')

    advanceSessionGeneration()

    await expect(staleRequest).rejects.toEqual(expect.objectContaining({ name: 'AbortError' }))
  })

  it('does not notify unauthorized subscribers for a 403 response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(403, { detail: 'Permission denied' })))
    const unauthorized = vi.fn()
    const unsubscribe = onUnauthorized(unauthorized)

    await expect(apiRequest('/api/bootstrap')).rejects.toEqual(
      expect.objectContaining({ status: 403, detail: 'Permission denied' }),
    )
    expect(unauthorized).not.toHaveBeenCalled()
    unsubscribe()
  })

  it('rejects requests outside the same-origin API namespace', async () => {
    await expect(apiRequest('https://example.com/api/users')).rejects.toThrow(
      'API paths must start with /api',
    )
  })
})
