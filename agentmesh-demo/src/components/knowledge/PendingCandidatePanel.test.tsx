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
    projectId: real('project-1'),
    createdAt: real('2026-08-19T09:00:00Z'),
    updatedAt: real('2026-08-19T09:00:00Z'),
    documentId: real(null),
    documentVersion: real(null),
    taskId: real(null),
    memoryId: real(null),
    memoryVersion: real(null),
    memoryReview: real(null),
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
      onMemoryReview={vi.fn()}
      onOpenTaskReview={vi.fn()}
      onOpenMemoryReview={vi.fn()}
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

  it('renders a dedicated Task Review action instead of generic resolution', () => {
    const item: PendingKnowledgeView = {
      ...toolApprovalItem([]),
      id: real('inbox-review-1'),
      title: real('审核任务交付'),
      itemType: real('task_review'),
      memoryType: real('task_review'),
      taskId: real('task-1'),
      allowedActions: real(['snooze', 'open_task_review']),
    }

    const html = render(item)

    expect(html).toContain('打开任务审核')
    expect(html).not.toContain('标记已解决')
  })

  it('renders independent Memory Review actions for a governed team candidate', () => {
    const item: PendingKnowledgeView = {
      ...toolApprovalItem([]),
      kind: 'team_candidate',
      id: real('memory-candidate-1'),
      title: real('团队候选'),
      itemType: real('team_candidate'),
      memoryType: real('project_experience'),
      memoryId: real('memory-candidate-1'),
      memoryVersion: real(1),
      memoryReview: real({
        schema_version: 'memory-review-v1',
        id: 'memory-review-1',
        memory_id: 'memory-candidate-1',
        source_task_review_id: 'task-review-1',
        requested_by: 'user-1',
        reviewer_id: 'reviewer-1',
        status: 'pending',
        decision_note: null,
        memory_version: 1,
        version: 1,
        created_at: '2026-09-02T00:00:00Z',
        updated_at: '2026-09-02T00:00:00Z',
        decided_at: null,
      }),
      allowedActions: real(['accept_review', 'reject_review']),
    }

    const html = render(item)

    expect(html).toContain('接受为团队知识')
    expect(html).toContain('拒绝原因')
    expect(html).toContain('拒绝候选')
    expect(html).not.toContain('接受候选</button>')
  })

  it('does not render unsafe approval buttons without a valid call_id', () => {
    const html = render(toolApprovalItem([]))

    expect(html).toContain('审批详情缺少可用的 call_id，无法安全处理')
    expect(html).not.toContain('允许本次操作')
    expect(html).not.toContain('拒绝本次操作')
  })
})
