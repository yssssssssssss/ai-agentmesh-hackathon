import { describe, expect, it } from 'vitest'

import type { BlackboardPost, TaskCard, TaskDetail } from '../collaboration/api'
import {
  buildTaskCenterViewModel,
  buildTaskDetailViewModel,
  TASK_STAGE_OPTIONS,
  TASK_STATUS_OPTIONS,
} from './presenter'

interface CardOptions {
  id?: string
  title?: string
  owner?: string | null
  doneWhen?: string | null
  stage?: NonNullable<TaskCard['stage']>
  status?: TaskCard['task']['status']
  createdAt?: string
  updatedAt?: string
  latestPostAt?: string
  steps?: readonly string[]
  postCount?: number
  activeLock?: NonNullable<TaskCard['active_lock']> | null
}

function makeCard(options: CardOptions = {}): TaskCard {
  const id = options.id ?? 'task-1'
  const stage = options.stage ?? 'discussion'
  const status = options.status ?? 'created'
  const owner = options.owner === undefined ? '策略 Agent' : options.owner
  const doneWhen = options.doneWhen === undefined ? '负责人确认结论' : options.doneWhen
  const createdAt = options.createdAt ?? '2026-08-25T08:00:00Z'
  const updatedAt = options.updatedAt ?? '2026-08-25T09:00:00Z'

  return {
    task: {
      id,
      thread_id: `thread-${id}`,
      intent: 'general_chat',
      status,
      collaboration_stage: stage,
      current_owner_agent_id: owner ? 'agent-strategy' : null,
      current_owner_label: owner,
      execution_lock: null,
      done_when: doneWhen,
      title: options.title ?? `任务 ${id}`,
      steps: options.steps ? [...options.steps] : ['收集资料', '输出结论'],
      created_at: createdAt,
      updated_at: updatedAt,
    },
    latest_post: options.latestPostAt ? makePost({
      id: `post-${id}`,
      taskId: id,
      stage,
      createdAt: options.latestPostAt,
    }) : null,
    stage,
    owner,
    done_when: doneWhen,
    active_lock: options.activeLock ?? null,
    post_count: options.postCount ?? 2,
    initiator_user_id: 'user-1',
    initiated_by_current_user: true,
    claimed_by_personal_agent: false,
    upstream_agents: ['洞察 Agent'],
    downstream_agents: ['策略 Agent'],
    target_post_id: `post-${id}`,
    allowed_actions: [],
  }
}

interface PostOptions {
  id?: string
  taskId?: string
  stage?: NonNullable<TaskCard['stage']>
  createdAt?: string
}

function makePost(options: PostOptions = {}): BlackboardPost {
  return {
    id: options.id ?? 'post-1',
    task_id: options.taskId ?? 'task-1',
    post_type: 'evidence',
    actor: '洞察 Agent',
    title: '补充调研证据',
    content: '完成近 90 天入口数据验证',
    scope: 'project',
    permission: 'project_visible',
    status: 'published',
    sources: [],
    metadata: {},
    read_by_agents: [],
    related_post_id: null,
    collaboration_stage: options.stage ?? 'execution',
    current_owner_agent_id: 'agent-strategy',
    current_owner_label: '策略 Agent',
    execution_lock: null,
    done_when: '负责人确认结论',
    handoff: null,
    created_at: options.createdAt ?? '2026-08-25T09:00:00Z',
    allowed_actions: [],
  }
}

describe('buildTaskCenterViewModel', () => {
  it('keeps execution status separate from collaboration stage and exposes the complete read-only card', () => {
    const lock = {
      owner_agent_id: 'agent-review',
      owner_label: '评审 Agent',
      acquired_at: '2026-08-25T09:30:00Z',
      released_at: null,
      released_reason: null,
    }
    const card = makeCard({
      id: 'task-mismatch',
      title: '确认 618 会场策略',
      stage: 'review',
      status: 'running',
      activeLock: lock,
      postCount: 4,
    })

    const view = buildTaskCenterViewModel([card])
    const item = view.items[0]

    expect(item.executionStatus).toEqual({
      value: 'running',
      rawValue: 'running',
      label: '运行中',
      tone: 'collab',
    })
    expect(item.collaborationStage).toEqual({
      value: 'review',
      rawValue: 'review',
      label: '评审',
      tone: 'remind',
    })
    expect(item).toMatchObject({
      id: 'task-mismatch',
      title: '确认 618 会场策略',
      owner: '策略 Agent',
      doneWhen: '负责人确认结论',
      activeLock: lock,
      steps: ['收集资料', '输出结论'],
      createdAt: '2026-08-25T08:00:00Z',
      updatedAt: '2026-08-25T09:00:00Z',
      postCount: 4,
    })
    expect(item.card).toBe(card)
  })

  it('does not treat a created task as running or an execution lock holder as the collaboration owner', () => {
    const card = makeCard({
      owner: null,
      status: 'created',
      activeLock: {
        owner_agent_id: 'agent-lock-holder',
        owner_label: '执行锁持有人',
        acquired_at: '2026-08-25T09:30:00Z',
        released_at: null,
        released_reason: null,
      },
    })

    const view = buildTaskCenterViewModel([card])

    expect(view.items[0].owner).toBeNull()
    expect(view.stats.activeVisible).toBe(0)
    expect(view.stats.locked).toBe(1)
  })

  it.each([
    ['title', '会场策略', { title: '确认 618 会场策略' }],
    ['owner', '风控 agent', { owner: '风控 Agent' }],
    ['done when', '完成验收', { doneWhen: '业务负责人完成验收' }],
    ['step', '输出报告', { steps: ['收集资料', '输出报告'] }],
  ] as const)('searches normalized task %s text', (_label, query, options) => {
    const match = makeCard({ id: 'task-match', ...options })
    const other = makeCard({ id: 'task-other', title: '其他任务', owner: '其他 Agent', doneWhen: '归档' })

    const view = buildTaskCenterViewModel([other, match], { query })

    expect(view.items.map((item) => item.id)).toEqual(['task-match'])
    expect(view.filters.query).toBe(query.toLocaleLowerCase())
    expect(view.hasActiveFilters).toBe(true)
  })

  it('combines collaboration-stage and execution-status filters without conflating them', () => {
    const cards = [
      makeCard({ id: 'review-running', stage: 'review', status: 'running' }),
      makeCard({ id: 'review-completed', stage: 'review', status: 'completed' }),
      makeCard({ id: 'execution-running', stage: 'execution', status: 'running' }),
    ]

    const view = buildTaskCenterViewModel(cards, {
      collaborationStage: 'review',
      executionStatus: 'running',
    })

    expect(view.items.map((item) => item.id)).toEqual(['review-running'])
    expect(view.groups).toHaveLength(1)
    expect(view.groups[0].stage.value).toBe('review')
    expect(view.groups[0].items.map((item) => item.id)).toEqual(['review-running'])
  })

  it('sorts deterministically by latest activity and keeps groups in the workflow order', () => {
    const cards = [
      makeCard({ id: 'older', title: 'Z', stage: 'review', updatedAt: '2026-08-25T09:00:00Z' }),
      makeCard({ id: 'latest-b', title: 'B', stage: 'discussion', updatedAt: '2026-08-25T11:00:00Z' }),
      makeCard({ id: 'latest-a', title: 'A', stage: 'discussion', updatedAt: '2026-08-25T11:00:00Z' }),
      makeCard({
        id: 'post-is-latest',
        title: 'Post',
        stage: 'execution',
        updatedAt: '2026-08-25T08:30:00Z',
        latestPostAt: '2026-08-25T12:00:00Z',
      }),
    ]

    const view = buildTaskCenterViewModel(cards)

    expect(view.items.map((item) => item.id)).toEqual([
      'post-is-latest',
      'latest-a',
      'latest-b',
      'older',
    ])
    expect(view.groups.map((group) => group.stage.value)).toEqual([
      'discussion',
      'execution',
      'review',
      'blocked',
      'completed',
    ])
    expect(view.groups[0].items.map((item) => item.id)).toEqual(['latest-a', 'latest-b'])
    expect(cards.map((card) => card.task.id)).toEqual(['older', 'latest-b', 'latest-a', 'post-is-latest'])
  })

  it('reports API-visible totals separately from the filtered result statistics', () => {
    const activeLock = {
      owner_agent_id: 'agent-execution',
      owner_label: '执行 Agent',
      acquired_at: '2026-08-25T08:00:00Z',
      released_at: null,
      released_reason: null,
    }
    const cards = [
      makeCard({ id: 'blocked-complete', stage: 'blocked', status: 'completed' }),
      makeCard({ id: 'blocked-running', stage: 'blocked', status: 'running', activeLock }),
      makeCard({ id: 'completed-running', stage: 'completed', status: 'running' }),
      makeCard({ id: 'failed', stage: 'review', status: 'failed' }),
    ]

    const view = buildTaskCenterViewModel(cards, { collaborationStage: 'blocked' })

    expect(view.stats).toEqual({
      totalVisible: 4,
      filteredVisible: 2,
      locked: 1,
      activeVisible: 1,
      blockedVisible: 2,
      completedVisible: 1,
      byStage: {
        discussion: 0,
        execution: 0,
        review: 1,
        blocked: 2,
        completed: 1,
        unknown: 0,
      },
      byExecutionStatus: {
        created: 0,
        running: 2,
        waiting_external_agent: 0,
        synthesizing: 0,
        completed: 1,
        failed: 1,
        unknown: 0,
      },
    })
  })

  it('falls back safely for empty or future stage/status values and still keeps them filterable', () => {
    const releasedLock = {
      owner_agent_id: 'agent-old',
      owner_label: '旧负责人',
      acquired_at: '2026-08-25T08:00:00Z',
      released_at: '2026-08-25T08:30:00Z',
      released_reason: 'done',
    }
    const card = makeCard({ id: 'unknown-task', title: '   ', postCount: -2 })
    card.stage = '' as TaskCard['stage']
    card.task.collaboration_stage = 'future_stage' as TaskCard['task']['collaboration_stage']
    card.task.status = 'paused' as TaskCard['task']['status']
    card.task.created_at = 'invalid date'
    card.task.updated_at = ''
    card.task.execution_lock = releasedLock
    card.task.steps = ['  ', '保留这个步骤  ']

    const view = buildTaskCenterViewModel([card], {
      collaborationStage: 'unknown',
      executionStatus: 'unknown',
    })
    const item = view.items[0]

    expect(item.collaborationStage).toEqual({
      value: 'unknown',
      rawValue: 'future_stage',
      label: '未知阶段',
      tone: 'neutral',
    })
    expect(item.executionStatus).toEqual({
      value: 'unknown',
      rawValue: 'paused',
      label: '未知状态',
      tone: 'neutral',
    })
    expect(item).toMatchObject({
      title: '未命名任务',
      activeLock: null,
      steps: ['保留这个步骤'],
      createdAt: null,
      updatedAt: null,
      lastActivityAt: null,
      postCount: 0,
    })
    expect(view.groups.map((group) => group.stage.value)).toEqual(['unknown'])
    expect(view.stats.byStage.unknown).toBe(1)
    expect(view.stats.byExecutionStatus.unknown).toBe(1)
  })

  it('distinguishes a truly empty API result from filters with no matches', () => {
    expect(buildTaskCenterViewModel([]).emptyReason).toBe('no-visible-tasks')
    expect(buildTaskCenterViewModel([makeCard()], { query: '不存在' }).emptyReason).toBe('no-filter-matches')
  })

  it('exports stable filter option orders including explicit unknown fallbacks', () => {
    expect(TASK_STAGE_OPTIONS.map((option) => option.value)).toEqual([
      'discussion',
      'execution',
      'review',
      'blocked',
      'completed',
      'unknown',
    ])
    expect(TASK_STATUS_OPTIONS.map((option) => option.value)).toEqual([
      'created',
      'running',
      'waiting_external_agent',
      'synthesizing',
      'completed',
      'failed',
      'unknown',
    ])
  })
})

describe('buildTaskDetailViewModel', () => {
  it('presents every server-visible post as a stable chronological timeline with safe fallbacks', () => {
    const card = makeCard({ id: 'task-detail', stage: 'execution', status: 'running' })
    const later = makePost({ id: 'post-later', taskId: 'task-detail', createdAt: '2026-08-25T11:00:00Z' })
    const earlier = makePost({ id: 'post-earlier', taskId: 'task-detail', createdAt: '2026-08-25T09:00:00Z' })
    const unknown = makePost({ id: 'post-unknown', taskId: 'task-detail', createdAt: 'not-a-date' })
    unknown.post_type = 'future_event' as BlackboardPost['post_type']
    unknown.collaboration_stage = '' as BlackboardPost['collaboration_stage']
    unknown.actor = ' '
    unknown.title = ''
    unknown.status = ''
    const detail: TaskDetail = { task_card: card, posts: [later, unknown, earlier] }

    const view = buildTaskDetailViewModel(detail)

    expect(view.task.card).toBe(card)
    expect(view.timeline.map((item) => item.id)).toEqual(['post-earlier', 'post-later', 'post-unknown'])
    expect(view.timeline[2]).toMatchObject({
      actor: '未知参与者',
      title: '未命名动态',
      publicationStatus: 'unknown',
      createdAt: null,
      postType: {
        value: 'unknown',
        rawValue: 'future_event',
        label: '未知动态',
        tone: 'neutral',
      },
      collaborationStage: {
        value: 'unknown',
        rawValue: null,
        label: '未知阶段',
        tone: 'neutral',
      },
    })
    expect(view.timeline[2].post).toBe(unknown)
  })
})
