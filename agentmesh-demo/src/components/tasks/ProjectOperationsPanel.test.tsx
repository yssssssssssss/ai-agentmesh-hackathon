import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { TaskOperationsSnapshot } from '../../features/tasks/types'
import { ProjectOperationsPanel } from './ProjectOperationsPanel'

const readiness = {
  state: 'waiting_dependencies' as const,
  is_execution_ready: false,
  dependency_count: 1,
  completed_dependency_count: 0,
  blocking_task_ids: ['task-research'],
  child_count: 0,
  completed_child_count: 0,
}

const task = {
  id: 'task-design',
  title: '完成方案设计',
  task_type: 'design' as const,
  delivery_stage: 'planned' as const,
  priority: 'p1' as const,
  due_at: '2030-01-15T12:00:00Z',
  assignee_kind: 'agent' as const,
  assignee_id: 'agent-1',
  parent_task_id: 'task-milestone',
  dependency_task_ids: ['task-research'],
  readiness,
  navigation_href: '/tasks?task=task-design',
}

const snapshot: TaskOperationsSnapshot = {
  schema_version: 'task-operations-snapshot-v1',
  project_id: 'project-1',
  generated_at: '2030-01-01T00:00:00Z',
  graph_task_count: 3,
  metrics: {
    tasks_by_stage: { planned: 1, done: 1 },
    tasks_by_readiness: { waiting_dependencies: 1, ready: 1 },
    runs_by_status: { running: 1 },
    reviews_by_status: { pending: 1 },
    task_count: 3,
    open_task_count: 2,
    overdue_task_count: 1,
    blocked_task_count: 0,
    active_run_count: 1,
    pending_review_count: 1,
    memory_use_count: 2,
    cited_memory_use_count: 1,
    unique_reused_memory_count: 1,
    accepted_team_knowledge_count: 3,
  },
  critical_dependency_chain: [task],
  critical_dependency_chain_total: 1,
  critical_dependency_chain_truncated: false,
  milestones: [{
    task: { ...task, id: 'task-milestone', title: '发布里程碑', task_type: 'milestone', dependency_task_ids: [], parent_task_id: null },
    descendant_count: 2,
    completed_descendant_count: 1,
    progress_percent: 50,
    overdue: false,
  }],
  milestone_total: 1,
  milestones_truncated: false,
  calendar: {
    items: [{ task, overdue: false }],
    total: 1,
    page: 1,
    page_size: 20,
    has_next: false,
    range_start: '2030-01-01T00:00:00Z',
    range_end: '2030-03-01T00:00:00Z',
  },
  agent_queue: {
    items: [{ task, queue_state: 'waiting_dependencies', active_run_status: null }],
    total: 1,
    page: 1,
    page_size: 20,
    has_next: false,
  },
}

const common = {
  data: snapshot,
  loading: false,
  error: null,
  agents: [{
    id: 'agent-1',
    name: '设计 Agent',
    description: '执行设计任务',
    agent_type: 'personal' as const,
    status: 'online' as const,
    runtime_status: 'idle',
    owner_user_id: 'user-1',
    workspace_id: 'workspace-1',
    skill_ids: [],
    tool_ids: [],
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
  }],
  selectedAgentId: '',
  onAgentChange: () => undefined,
  onRetry: () => undefined,
  onCalendarPeriodPrevious: () => undefined,
  onCalendarPeriodNext: () => undefined,
  onCalendarPrevious: () => undefined,
  onCalendarNext: () => undefined,
  onQueuePrevious: () => undefined,
  onQueueNext: () => undefined,
}

describe('ProjectOperationsPanel', () => {
  it('renders project facts, the critical dependency chain, and milestone progress', () => {
    const html = renderToStaticMarkup(<ProjectOperationsPanel {...common} section="overview" />)

    expect(html).toContain('项目运营指标')
    expect(html).toContain('关键依赖链')
    expect(html).toContain('发布里程碑')
    expect(html).toContain('50%')
    expect(html).toContain('我的记忆引用')
    expect(html).toContain('已接受团队知识')
  })

  it('renders server-paginated calendar and Agent queue views', () => {
    const calendar = renderToStaticMarkup(<ProjectOperationsPanel {...common} section="calendar" />)
    const queue = renderToStaticMarkup(<ProjectOperationsPanel {...common} section="agents" />)

    expect(calendar).toContain('项目日历')
    expect(calendar).toContain('完成方案设计')
    expect(calendar).toContain('第 1 页')
    expect(calendar).toContain('上一时间段')
    expect(calendar).toContain('下一时间段')
    expect(queue).toContain('Agent 队列')
    expect(queue).toContain('等待依赖')
    expect(queue).toContain('设计 Agent')
  })
})
