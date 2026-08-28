import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  isDeepSearchPlanDetailResponse,
  isDeepSearchPlanTransitionResponse,
  parseAgentRunEvent,
  subscribeAgentRunEvents,
  workspaceApi,
} from './api'
import type { PlanDetailResponse, PlanTransitionResponse } from './types'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  readonly listeners = new Map<string, Set<EventListener>>()
  readonly url: string
  onerror: ((event: Event) => void) | null = null
  closed = false

  constructor(url: string | URL) {
    this.url = String(url)
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    if (typeof listener !== 'function') return
    const listeners = this.listeners.get(type) ?? new Set<EventListener>()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    if (typeof listener === 'function') this.listeners.get(type)?.delete(listener)
  }

  close() {
    this.closed = true
  }

  emit(type: string, payload: object) {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) })
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }
}

afterEach(() => {
  FakeEventSource.instances = []
  vi.unstubAllGlobals()
})

describe('Agent Run event stream', () => {
  it('rejects malformed or unsafe event data', () => {
    expect(parseAgentRunEvent('not-json')).toBeNull()
    expect(parseAgentRunEvent(JSON.stringify({ run_id: 'run-1', sequence: 0, event_type: 'node_started' }))).toBeNull()
    expect(parseAgentRunEvent(JSON.stringify({ run_id: 'run-1', sequence: 1, event_type: 'node_started', payload: [] }))).toBeNull()
  })

  it('deduplicates by sequence and closes on cleanup', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const received: number[] = []
    const close = subscribeAgentRunEvents('run-1', {
      onEvent: (event) => received.push(event.sequence),
      onError: vi.fn(),
    })
    const stream = FakeEventSource.instances[0]

    stream.emit('node_started', { run_id: 'run-1', sequence: 1, event_type: 'node_started', payload: {} })
    stream.emit('node_started', { run_id: 'run-1', sequence: 1, event_type: 'node_started', payload: {} })
    stream.emit('node_completed', { run_id: 'run-1', sequence: 2, event_type: 'node_completed', payload: {} })
    stream.emit('research_updated', { run_id: 'run-1', sequence: 3, event_type: 'research_updated', payload: {} })
    stream.emit('research_step_claimed', {
      run_id: 'run-1', sequence: 4, event_type: 'research_step_claimed', payload: {},
    })
    stream.emit('research_recovery_required', {
      run_id: 'run-1', sequence: 5, event_type: 'research_recovery_required', payload: {},
    })
    stream.emit('research_artifacts_sealed', {
      run_id: 'run-1', sequence: 6, event_type: 'research_artifacts_sealed', payload: {},
    })
    stream.emit('deepsearch_report_sealed', {
      run_id: 'run-1', sequence: 7, event_type: 'deepsearch_report_sealed', payload: {},
    })
    stream.emit('model_stream_retry_exhausted', {
      run_id: 'run-1', sequence: 8, event_type: 'model_stream_retry_exhausted', payload: {},
    })
    stream.emit('node_completed', { run_id: 'another-run', sequence: 9, event_type: 'node_completed', payload: {} })

    expect(received).toEqual([1, 2, 3, 4, 5, 6, 7, 8])
    expect(stream.url).toContain('after_sequence=0')
    close()
    expect(stream.closed).toBe(true)
  })

  it('closes after a terminal event', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const close = subscribeAgentRunEvents('run-terminal', { onEvent: vi.fn(), onError: vi.fn() })
    const stream = FakeEventSource.instances[0]

    stream.emit('run_partial', {
      run_id: 'run-terminal',
      sequence: 4,
      event_type: 'run_partial',
      payload: {},
    })

    expect(stream.closed).toBe(true)
    close()
  })
})

describe('Skill matching API', () => {
  it('posts a bounded task match request', async () => {
    const response = { items: [] }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(workspaceApi.matchSkills('评审商品详情页体验', 5)).resolves.toEqual(response)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/skills/matches')
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ method: 'POST' }))
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual({
      content: '评审商品详情页体验',
      limit: 5,
    })
  })
})

describe('Agent Run creation API', () => {
  it('sends an explicit DeepSearch planning mode without an explicit Skill', async () => {
    const response = { item: { id: 'run-deepsearch' } }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), {
      status: 202,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await workspaceApi.startAgentRun({
      threadId: 'thread/1',
      content: '比较三个候选方案',
      clientTurnId: 'turn-1',
      orchestrationMode: 'auto',
      planningMode: 'deepsearch',
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/runs')
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual({
      thread_id: 'thread/1',
      content: '比较三个候选方案',
      client_turn_id: 'turn-1',
      orchestration_mode: 'auto',
      planning_mode: 'deepsearch',
    })
  })
})

describe('shared Plan response discrimination', () => {
  it('uses the public DTO boundary rather than nullable DeepSearch fields', () => {
    const standard = {
      plan: { planning_mode: 'standard', requirement_version_id: null },
    } as PlanDetailResponse
    const deepSearch = {
      plan: { requirement_version_id: 'requirement-1' },
    } as PlanDetailResponse

    expect(isDeepSearchPlanDetailResponse(standard)).toBe(false)
    expect(isDeepSearchPlanDetailResponse(deepSearch)).toBe(true)
    expect(isDeepSearchPlanTransitionResponse(standard as PlanTransitionResponse)).toBe(false)
    expect(isDeepSearchPlanTransitionResponse(deepSearch as PlanTransitionResponse)).toBe(true)
  })
})
