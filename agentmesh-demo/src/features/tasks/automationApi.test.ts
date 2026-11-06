import { afterEach, describe, expect, it, vi } from 'vitest'

import { automationApi } from './automationApi'

afterEach(() => vi.unstubAllGlobals())

describe('inspection schedule API', () => {
  it('keeps command and version identities on retries and never supplies an execution owner', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'schedule-1' }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const payload = {
      command_id: 'stable-create', title: 'Daily progress', project_id: 'project/1',
      template_id: 'daily_progress' as const, schedule: '30 9 * * *', timezone: 'Asia/Shanghai', enabled: true, on_project_changes: false,
    }
    await automationApi.create(payload)
    await automationApi.create(payload)
    const bodies = fetchMock.mock.calls.map(([, request]) => JSON.parse(request.body))
    expect(bodies).toEqual([payload, payload])
    expect(bodies[0]).not.toHaveProperty('owner_user_id')
    expect(bodies[0]).not.toHaveProperty('agent_id')
    await automationApi.runNow('schedule/1', 'stable-run', 3)
    expect(fetchMock.mock.calls[2][0]).toBe('/api/agents/scheduled-tasks/schedule%2F1/run-now')
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ command_id: 'stable-run', expected_version: 3 })
  })
})
