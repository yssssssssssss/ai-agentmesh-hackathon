import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { PresentedValue } from '../../lib/presentation'
import type { PendingKnowledgeView } from '../../features/knowledge/presenter'
import { PendingCandidatePanel } from './PendingCandidatePanel'

function real<T>(value: T): PresentedValue<T> {
  return { value, source: 'T' }
}

function toolApprovalItem(toolCalls: PendingKnowledgeView['toolCalls']['value']): PendingKnowledgeView {
  return {
    kind: 'inbox',
    id: real('inbox-tool-1'),
    title: real('审批 Agent 工具调用'),
    summary: real('运行已暂停，等待逐项处理工具调用。'),
    itemType: real('sdk_tool_approval'),
    memoryType: real('sdk_tool_approval'),
    scope: real('private'),
    status: real('open'),
    sourceProject: real('当前项目'),
    createdAt: real('2026-08-19T09:00:00Z'),
    updatedAt: real('2026-08-19T09:00:00Z'),
    documentId: real(null),
    documentVersion: real(null),
    toolCalls: real(toolCalls),
    allowedActions: real(['snooze', 'approve_tool', 'reject_tool']),
  }
}

function render(item: PendingKnowledgeView) {
  return renderToStaticMarkup(
    <PendingCandidatePanel
      items={[item]}
      busy={false}
      pendingToolApproval={null}
      readOnly={false}
      onConfirm={vi.fn()}
      onSnooze={vi.fn()}
      onResolve={vi.fn()}
      onInjection={vi.fn()}
      onToolApproval={vi.fn()}
      onAccept={vi.fn()}
      onOpenDetail={vi.fn()}
    />,
  )
}

describe('PendingCandidatePanel tool approvals', () => {
  it('renders approve and reject actions for every call_id and distinguishes Plan Approval', () => {
    const html = render(toolApprovalItem([
      { callId: 'call-a', name: 'web_research', argumentKeys: ['query'] },
      { callId: 'call-b', name: 'save_draft', argumentKeys: ['content', 'title'] },
    ]))

    expect(html).toContain('单次工具确认')
    expect(html).toContain('Skill 内已获用户授权的常规只读工具不会重复询问')
    expect(html).toContain('data-tool-call-id="call-a"')
    expect(html).toContain('data-tool-call-id="call-b"')
    expect(html.match(/允许本次操作/g)).toHaveLength(2)
    expect(html.match(/拒绝本次操作/g)).toHaveLength(2)
    expect(html).not.toContain('稍后处理整组调用')
    expect(html).not.toContain('标记已解决')
  })

  it('does not render unsafe approval buttons without a valid call_id', () => {
    const html = render(toolApprovalItem([]))

    expect(html).toContain('审批详情缺少可用的 call_id，无法安全处理')
    expect(html).not.toContain('允许本次操作')
    expect(html).not.toContain('拒绝本次操作')
  })
})
