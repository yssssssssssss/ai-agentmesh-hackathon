import { afterEach, describe, expect, it, vi } from 'vitest'

import { parseAgentRunEvent, subscribeAgentRunEvents } from './api'

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
    stream.emit('node_completed', { run_id: 'another-run', sequence: 7, event_type: 'node_completed', payload: {} })

    expect(received).toEqual([1, 2, 3, 4, 5, 6])
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
