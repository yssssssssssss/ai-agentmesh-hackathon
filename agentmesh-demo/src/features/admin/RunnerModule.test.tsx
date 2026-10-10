import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useRunnerAdmin } from './api'
import { RunnerModule } from './RunnerModule'

vi.mock('./api', () => ({
  useRunnerAdmin: vi.fn(),
}))

const context = { userId: 'usr_current', workspaceId: 'ws_current' }

const capabilities = {
  schema_version: 'runner-capabilities-v1' as const,
  platform: 'darwin',
  architecture: 'arm64',
  runner_version: '0.1.0',
  protocol_version: 'runner-v1' as const,
  tools: ['git'],
  model_capabilities: ['streaming'],
}

describe('RunnerModule', () => {
  beforeEach(() => {
    vi.mocked(useRunnerAdmin).mockReturnValue({
      runners: {
        data: {
          items: [{
            schema_version: 'runner-device-v1',
            id: 'runner_1',
            owner_user_id: context.userId,
            workspace_id: context.workspaceId,
            name: 'My Mac',
            capabilities,
            status: 'active',
            last_seen_at: '2026-09-17T00:00:00Z',
            created_at: '2026-09-17T00:00:00Z',
            updated_at: '2026-09-17T00:00:00Z',
          }],
        },
        isLoading: false,
        isFetching: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      },
      enrollment: {
        data: {
          runner_id: 'runner_1',
          device_name: 'My Mac',
          capabilities,
          status: 'pending',
          expires_at: '2026-09-17T00:10:00Z',
        },
        isLoading: false,
        isError: false,
        error: null,
      },
      approve: { isPending: false, isError: false, error: null, mutate: vi.fn() },
      revoke: { isPending: false, isError: false, error: null, mutate: vi.fn() },
    } as never)
  })

  it('shows the enrollment confirmation and the current user runner', () => {
    const html = renderToStaticMarkup(
      <RunnerModule context={context} enrollmentCode="ABCD-2345" />,
    )

    expect(html).toContain('确认本地 Runner')
    expect(html).toContain('ABCD-2345')
    expect(html).toContain('确认连接此设备')
    expect(html).toContain('My Mac')
    expect(html).toContain('撤销')
  })
})
