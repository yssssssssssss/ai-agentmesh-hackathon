import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Agent, ToolDefinition } from './api'
import { useAgentAdmin, useAgentToolsAdmin } from './api'
import { AgentModule } from './AgentModule'

vi.mock('./api', () => ({
  useAgentAdmin: vi.fn(),
  useAgentToolsAdmin: vi.fn(),
}))

const context = { userId: 'user-current', workspaceId: 'workspace-1' }

const ownAgent: Agent = {
  id: 'agent-personal-current',
  workspace_id: context.workspaceId,
  name: '我的 AI 助手',
  agent_type: 'personal',
  description: '当前用户的个人 Agent',
  status: 'online',
  runtime_status: 'idle',
  owner_user_id: context.userId,
}

const publicAgent: Agent = {
  id: 'agent-research',
  workspace_id: context.workspaceId,
  name: '研究 Agent',
  agent_type: 'public',
  description: '公共研究 Agent',
  status: 'online',
  runtime_status: 'idle',
}

const anotherUsersAgent: Agent = {
  id: 'agent-personal-other',
  workspace_id: context.workspaceId,
  name: '其他人的 AI 助手',
  agent_type: 'personal',
  description: '其他用户的个人 Agent',
  status: 'online',
  runtime_status: 'idle',
  owner_user_id: 'user-other',
}

const webResearch: ToolDefinition = {
  id: 'tool_web_research',
  name: 'Web Research',
  description: '搜索公开资料',
  category: 'research',
  enabled: true,
  risk_level: 'low',
  provider: 'builtin',
  side_effect: 'read',
  implementation_version: '1',
  idempotency_support: 'none',
  approval_required: false,
  health_ttl_seconds: 60,
  timeout_seconds: 45,
}

describe('AgentModule', () => {
  beforeEach(() => {
    vi.mocked(useAgentAdmin).mockReturnValue({
      agents: {
        data: { items: [ownAgent, publicAgent, anotherUsersAgent] },
        isLoading: false,
        isError: false,
        error: null,
      },
      models: { data: { items: [] }, isLoading: false },
      tools: {
        data: { items: [webResearch] },
        isFetching: false,
        isError: false,
        error: null,
      },
      updateModel: { isPending: false, isError: false, error: null, mutate: vi.fn() },
      updateTools: { isPending: false, isError: false, error: null, mutate: vi.fn() },
    } as never)
    vi.mocked(useAgentToolsAdmin).mockImplementation((_context, agentId) => ({
      data: { items: agentId === ownAgent.id ? [webResearch] : [] },
      isSuccess: true,
      isFetching: false,
      isError: false,
      error: null,
    }) as never)
  })

  it('让当前用户选择自己的个人 Agent 并配置工具', () => {
    const html = renderToStaticMarkup(<AgentModule context={context} />)

    expect(html).toContain('我的 AI 助手')
    expect(html).toContain('研究 Agent')
    expect(html).not.toContain('其他人的 AI 助手')
    expect(html).toMatch(/>个人<\/span>/)
    expect(html).toMatch(/>公共<\/span>/)
    expect(useAgentToolsAdmin).toHaveBeenCalledWith(context, ownAgent.id, true)
    expect(html).toContain('Web Research')
    expect(html).toMatch(/<input type="checkbox"[^>]*checked=""/)
    expect(html).not.toContain('<fieldset disabled=""')
  })
})
