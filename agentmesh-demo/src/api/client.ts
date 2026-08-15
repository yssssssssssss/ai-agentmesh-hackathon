type UnauthorizedListener = (sessionGeneration: number) => void

const unauthorizedListeners = new Set<UnauthorizedListener>()
const inFlightRequests = new Map<number, Set<AbortController>>()
let sessionGeneration = 0

export class ApiError extends Error {
  readonly name = 'ApiError'

  constructor(
    public readonly status: number,
    public readonly detail: unknown,
    public readonly payload: unknown,
  ) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
  }
}

export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener)
  return () => unauthorizedListeners.delete(listener)
}

export function advanceSessionGeneration(): number {
  sessionGeneration += 1
  for (const [generation, controllers] of inFlightRequests) {
    if (generation >= sessionGeneration) continue
    for (const controller of controllers) controller.abort()
    inFlightRequests.delete(generation)
  }
  return sessionGeneration
}

function notifyUnauthorized(requestGeneration: number) {
  for (const listener of unauthorizedListeners) listener(requestGeneration)
}

async function responsePayload(response: Response): Promise<unknown> {
  if (response.status === 204) return null
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) return response.text()
  return response.json().catch(() => null)
}

function errorDetail(payload: unknown): unknown {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    return payload.detail
  }
  return payload
}

function trackRequest(generation: number, controller: AbortController): () => void {
  const controllers = inFlightRequests.get(generation)
  if (controllers) controllers.add(controller)
  else inFlightRequests.set(generation, new Set([controller]))

  return () => {
    const activeControllers = inFlightRequests.get(generation)
    activeControllers?.delete(controller)
    if (activeControllers?.size === 0) inFlightRequests.delete(generation)
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (path !== '/api' && !path.startsWith('/api/')) {
    throw new TypeError('API paths must start with /api')
  }

  const headers = new Headers(init.headers)
  if (init.body != null && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const requestGeneration = sessionGeneration
  const controller = new AbortController()
  const externalSignal = init.signal
  const forwardAbort = () => controller.abort(externalSignal?.reason)
  if (externalSignal?.aborted) forwardAbort()
  else externalSignal?.addEventListener('abort', forwardAbort, { once: true })
  const stopTracking = trackRequest(requestGeneration, controller)

  try {
    const response = await fetch(path, {
      ...init,
      credentials: 'same-origin',
      headers,
      signal: controller.signal,
    })
    const payload = await responsePayload(response)
    if (!response.ok) {
      if (response.status === 401) notifyUnauthorized(requestGeneration)
      throw new ApiError(response.status, errorDetail(payload), payload)
    }
    return payload as T
  } finally {
    externalSignal?.removeEventListener('abort', forwardAbort)
    stopTracking()
  }
}
