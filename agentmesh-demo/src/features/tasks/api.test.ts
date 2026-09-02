import { afterEach, describe, expect, it, vi } from 'vitest'

import { taskManagementApi } from './api'

function jsonResponse(payload: object) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('task management API', () => {
  it('loads every management page before rendering the board', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        items: [{ task: { id: 'task-1' }, management: {}, allowed_actions: [] }],
        total: 101,
        page: 1,
        page_size: 100,
        has_next: true,
        counts: {},
      }))
      .mockResolvedValueOnce(jsonResponse({
        items: [{ task: { id: 'task-101' }, management: {}, allowed_actions: [] }],
        total: 101,
        page: 2,
        page_size: 100,
        has_next: false,
        counts: {},
      }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await taskManagementApi.list('project/1')

    expect(result.items).toHaveLength(2)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/tasks?project_id=project%2F1&page=1&page_size=100')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/tasks?project_id=project%2F1&page=2&page_size=100')
  })

  it('loads linked run and Artifact summaries from task detail', async () => {
    const response = {
      item: { task: { id: 'task-1' }, management: {}, allowed_actions: [] },
      runs: [{ id: 'run-1', status: 'completed', planning_mode: 'standard', artifact_count: 1 }],
      artifacts: [{ id: 'artifact-1', run_id: 'run-1', artifact_type: 'task_output' }],
    }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(response))
    vi.stubGlobal('fetch', fetchMock)

    await expect(taskManagementApi.get('task/1')).resolves.toEqual(response)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/tasks/task%2F1')
  })

  it('creates a task with a stable command payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ item: { task: { id: 'task-1' } } }))
    vi.stubGlobal('fetch', fetchMock)

    await taskManagementApi.create({
      command_id: 'command-1',
      title: '准备项目复盘',
      description: '整理本轮结论',
      task_type: 'review',
      priority: 'p1',
      due_at: null,
      assignee_kind: null,
      assignee_id: null,
      tags: ['复盘'],
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/tasks')
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ method: 'POST' }))
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual(expect.objectContaining({
      command_id: 'command-1',
      title: '准备项目复盘',
      priority: 'p1',
    }))
  })

  it('uses versioned transition and archive endpoints', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ item: { task: { id: 'task-1' } } }))
    vi.stubGlobal('fetch', fetchMock)

    await taskManagementApi.transition('task/1', {
      command_id: 'transition-1',
      expected_version: 3,
      action: 'start',
      reason: null,
    })
    await taskManagementApi.archive('task/1', {
      command_id: 'archive-1',
      expected_version: 4,
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/tasks/task%2F1/transitions')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/tasks/task%2F1/archive')
  })
})
