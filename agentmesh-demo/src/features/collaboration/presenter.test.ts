import { describe, expect, it } from 'vitest'

import type { InboxItem } from '../knowledge/api'
import type { MarketBoard, TaskCard, TaskDetail } from './api'
import {
  COLLAB_OVERVIEW,
  MY_COLLAB,
  MY_COLLABORATIONS,
  RECOMMENDED_PEERS,
} from '../../data/mockData'
import type { PresentationState } from '../../lib/presentation'
import { buildCollaborationViewModel, collaborationDetailTaskIds } from './presenter'

interface Resource<T> {
  state: PresentationState
  data?: T
  error?: string
}

const available = <T>(data: T): Resource<T> => ({ state: 'available', data })

const taskCard: TaskCard = {
  task: {
    id: 'task-618',
    thread_id: 'thread-618',
    intent: 'request_external_research',
    status: 'running',
    collaboration_stage: 'execution',
    current_owner_agent_id: 'agent-owner',
    current_owner_label: '林知夏的数字人',
    execution_lock: {
      owner_agent_id: 'agent-owner',
      owner_label: '林知夏的数字人',
      acquired_at: '2026-08-15T08:00:00Z',
    },
    done_when: '形成可引用的 618 会场结论',
    title: '查找 618 家电会场历史经验',
    updated_at: '2026-08-15T09:00:00Z',
  },
  latest_post: null,
  stage: 'execution',
  owner: '林知夏的数字人',
  done_when: '形成可引用的 618 会场结论',
  active_lock: {
    owner_agent_id: 'agent-owner',
    owner_label: '林知夏的数字人',
    acquired_at: '2026-08-15T08:00:00Z',
  },
  post_count: 2,
  initiated_by_current_user: true,
  claimed_by_personal_agent: true,
  upstream_agents: ['项目发起人'],
  downstream_agents: ['Brief 生成 Agent'],
  target_post_id: 'post-handoff',
  allowed_actions: ['reply', 'handoff', 'unlock', 'read'],
}

const detail: TaskDetail = {
  task_card: taskCard,
  posts: [
    {
      id: 'post-evidence',
      task_id: 'task-618',
      post_type: 'evidence',
      actor: '李明的数字人',
      title: '补充 2025 年会场复盘',
      content: '沉浸式头图降低了首屏入口可见性。',
      scope: 'project',
      permission: 'project_visible',
      status: 'published',
      sources: [
        {
          id: 'source-review',
          title: '2025 年 618 会场复盘',
          source_type: 'document',
          reference: 'doc://review-618',
        },
      ],
      collaboration_stage: 'execution',
      allowed_actions: ['reply', 'read'],
    },
    {
      id: 'post-handoff',
      task_id: 'task-618',
      post_type: 'handoff',
      actor: '李明的数字人',
      title: '交接入口数据验证',
      content: '历史复盘已整理，下一步验证近 90 天入口数据。',
      scope: 'project',
      permission: 'project_visible',
      status: 'published',
      collaboration_stage: 'execution',
      handoff: {
        goal: '确认入口数据是否支持历史结论',
        current_result: '已整理 2025 年会场复盘',
        done_when: '完成近 90 天入口数据验证',
        next_owner_agent_id: '王晨的数字人',
      },
      allowed_actions: ['reply', 'lock'],
    },
  ],
}

const marketBoard: MarketBoard = {
  enabled: true,
  publish_worker: {
    enabled: true,
    running: true,
    last_run_at: '2026-08-15T09:00:00Z',
    last_error: null,
  },
  scout_worker: {
    enabled: true,
    running: true,
    last_run_at: '2026-08-15T09:01:00Z',
    last_error: null,
  },
  counts: {
    signals: 7,
    matches: 3,
    consent_grants: 2,
    participants: 5,
  },
  signals: [
    {
      owner_id: 'agent-liming',
      owner_name: '李明的数字人',
      participating: true,
      capability: '营销会场、数据复盘',
      offer: '2025 年 618 会场复盘',
      need: '近 90 天入口数据',
      created_at: '2026-08-15T08:30:00Z',
    },
  ],
  matches: [
    {
      helper_id: 'agent-liming',
      helper_name: '李明的数字人',
      needer_id: 'agent-owner',
      needer_name: '林知夏的数字人',
      status: 'matched',
      at: '2026-08-15T08:45:00Z',
    },
  ],
}

const authorization: InboxItem = {
  id: 'inbox-auth-1',
  title: '王晨申请引用会场经验',
  summary: '仅用于家电暑期会场改版。',
  item_type: 'collaboration_authorization',
  scope: 'project',
  status: 'open',
  project_id: 'project-618',
  metadata: { task_id: 'task-618', applicant: '王晨' },
  allowed_actions: ['approve'],
}

function input(overrides: Partial<{
  projectId: string
  taskCards: Resource<TaskCard[]>
  taskDetails: Resource<TaskDetail[]>
  marketBoard: Resource<MarketBoard>
  inbox: Resource<InboxItem[]>
}> = {}) {
  return {
    projectId: 'project-618',
    taskCards: available([taskCard]),
    taskDetails: available([detail]),
    marketBoard: available(marketBoard),
    inbox: available([authorization]),
    ...overrides,
  }
}

describe('buildCollaborationViewModel', () => {
  it('uses real Task, Post, status, owner, lock, source, actions and market facts as T data', () => {
    const view = buildCollaborationViewModel(input())

    expect(view.overview.data).toMatchObject({
      visibleTasks: { value: 1, source: 'T' },
      activeTasks: { value: 1, source: 'T' },
      marketParticipants: { value: 5, source: 'T' },
    })
    expect(view.tabs.data.map((tab) => [tab.key, tab.count])).toEqual([
      ['all', { value: 1, source: 'T' }],
      ['mine', { value: 1, source: 'T' }],
      ['authorization', { value: 1, source: 'T' }],
    ])
    expect(view.records.data[0]).toMatchObject({
      id: { value: 'task-618', source: 'T' },
      title: { value: taskCard.task.title, source: 'T' },
      status: { value: 'running', source: 'T' },
      owner: { value: '林知夏的数字人', source: 'T' },
      lock: { value: taskCard.active_lock, source: 'T' },
      doneWhen: { value: taskCard.done_when, source: 'T' },
      actions: { value: taskCard.allowed_actions, source: 'T' },
    })
    expect(view.records.data[0].sources).toEqual({
      value: detail.posts[0].sources,
      source: 'T',
    })
    expect(view.market.data.counts).toEqual({ value: marketBoard.counts, source: 'T' })
    expect(view.market.data.signals).toEqual({ value: marketBoard.signals, source: 'T' })
    expect(view.market.data.matches.value[0]).toMatchObject(marketBoard.matches[0])
    expect(view.market.data.matches.source).toBe('T')
  })

  it('maps upstream, downstream, actor and handoff into T participants, contributions and a user narrative timeline', () => {
    const view = buildCollaborationViewModel(input())
    const record = view.records.data[0]

    expect(record.participants).toEqual({
      value: expect.arrayContaining([
        { name: '项目发起人', relationship: 'upstream' },
        { name: 'Brief 生成 Agent', relationship: 'downstream' },
        { name: '李明的数字人', relationship: 'actor' },
        { name: '王晨的数字人', relationship: 'handoff' },
      ]),
      source: 'T',
    })
    expect(record.contributions).toEqual({
      value: expect.arrayContaining([
        expect.objectContaining({ actor: '李明的数字人', detail: detail.posts[0].content }),
        expect.objectContaining({
          actor: '李明的数字人',
          detail: detail.posts[1].handoff?.current_result,
        }),
      ]),
      source: 'T',
    })
    expect(view.timeline.data).toEqual([
      expect.objectContaining({
        actor: { value: '李明的数字人', source: 'T' },
        action: { value: '补充经验', source: 'T' },
        narrative: { value: detail.posts[0].content, source: 'T' },
        technical: {
          value: expect.objectContaining({
            postType: 'evidence',
            sources: detail.posts[0].sources,
            allowedActions: detail.posts[0].allowed_actions,
          }),
          source: 'T',
        },
      }),
      expect.objectContaining({
        actor: { value: '李明的数字人', source: 'T' },
        action: { value: '交接任务', source: 'T' },
        narrative: { value: detail.posts[1].content, source: 'T' },
        technical: {
          value: expect.objectContaining({
            postType: 'handoff',
            handoff: detail.posts[1].handoff,
            allowedActions: detail.posts[1].allowed_actions,
          }),
          source: 'T',
        }
      }),
    ])
    expect(view.timeline.sources).toEqual(['T'])
  })

  it('attributes handoff current results to the actor that produced them, not the next owner', () => {
    const record = buildCollaborationViewModel(input()).records.data[0]
    const currentResult = detail.posts[1].handoff?.current_result

    expect(record.contributions.value).toContainEqual(expect.objectContaining({
      actor: detail.posts[1].actor,
      detail: currentResult,
    }))
    expect(record.contributions.value).not.toContainEqual(expect.objectContaining({
      actor: detail.posts[1].handoff?.next_owner_agent_id,
      detail: currentResult,
    }))
  })

  it('counts only server states that represent active work', () => {
    const statuses = [
      'created',
      'running',
      'waiting_external_agent',
      'synthesizing',
      'completed',
      'failed',
    ] as const
    const cards = statuses.map((status) => ({
      ...taskCard,
      task: { ...taskCard.task, id: `task-${status}`, status },
    }))
    const view = buildCollaborationViewModel(input({
      taskCards: available(cards),
      taskDetails: available([]),
    }))

    expect(view.overview.data.visibleTasks).toEqual({ value: 6, source: 'T' })
    expect(view.overview.data.activeTasks).toEqual({ value: 4, source: 'T' })
  })

  it('scopes authorizations and linked detail task ids to the current project', () => {
    const linkedAuthorization: InboxItem = {
      ...authorization,
      id: 'inbox-auth-linked',
      metadata: { task_id: 'task-auth-only', applicant: '陈晓' },
    }
    const otherProjectAuthorization: InboxItem = {
      ...authorization,
      id: 'inbox-auth-other',
      project_id: 'project-other',
      metadata: { task_id: 'task-other', applicant: '赵敏' },
    }
    const inbox = [authorization, linkedAuthorization, otherProjectAuthorization]
    const view = buildCollaborationViewModel(input({ inbox: available(inbox) }))

    expect(view.authorizations.data.map((item) => item.id.value)).toEqual([
      'inbox-auth-1',
      'inbox-auth-linked',
    ])
    expect(view.tabs.data[2].count).toEqual({ value: 2, source: 'T' })
    expect(collaborationDetailTaskIds([taskCard], inbox, 'project-618')).toEqual([
      'task-618',
      'task-auth-only',
    ])
  })

  it('uses current mock data only for unavailable aggregates, capability percentages and matching reasons', () => {
    const view = buildCollaborationViewModel(input())
    const expectedPeriodAggregates = {
      all: MY_COLLABORATIONS.length,
      ongoing: MY_COLLABORATIONS.filter((item) => item.status === 'ongoing').length,
      completed: MY_COLLABORATIONS.filter((item) => item.status === 'done').length,
    }
    const expectedCapabilityPercentages = MY_COLLAB.capabilities.map((capability) => ({
      label: capability.name,
      percentage: 100 / MY_COLLAB.capabilities.length,
    }))

    expect(view.overview.data.receivedSupport).toEqual({
      value: COLLAB_OVERVIEW.receivedSupport,
      source: 'M',
      reason: '后端暂无周期聚合',
    })
    expect(view.overview.data.periodAggregates).toEqual({
      value: expectedPeriodAggregates,
      source: 'M',
      reason: '后端暂无周期聚合',
    })
    expect(view.overview.data.capabilityPercentages).toEqual({
      value: expectedCapabilityPercentages,
      source: 'M',
      reason: '后端暂无能力占比',
    })
    expect(view.market.data.matches.value[0].reason).toEqual({
      value: RECOMMENDED_PEERS[0].reason,
      source: 'M',
      reason: '后端暂无匹配原因',
    })
    expect(view.overview.sources).toEqual(['T', 'M'])
    expect(view.overview.missingFields).toEqual(expect.arrayContaining([
      'receivedSupport',
      'periodAggregates',
      'capabilityPercentages',
    ]))
    expect(view.market.sources).toEqual(['T', 'M'])
    expect(view.market.missingFields).toContain('matches.reason')
  })

  it.each([
    ['no server command', [], []],
    ['unrelated server command', ['snooze'], []],
    ['approve command', ['approve'], ['approve']],
    ['deny command', ['deny'], ['deny']],
    ['both commands', ['approve', 'deny'], ['approve', 'deny']],
  ] as const)('keeps authorization actions absent for %s', (_label, allowedActions, expected) => {
    const inboxItem = { ...authorization, allowed_actions: [...allowedActions] }
    const view = buildCollaborationViewModel(input({ inbox: available([inboxItem]) }))

    expect(view.authorizations.data[0].actions).toEqual({ value: expected, source: 'T' })
    expect('mockMutation' in view.authorizations.data[0]).toBe(false)
  })

  it.each([
    ['permission-filtered result', 'forbidden', '没有权限访问协作数据'],
    ['403 response', 'forbidden', '403 Forbidden'],
    ['network error', 'error', 'Network unavailable'],
  ] as const)('does not use Mock fallback for %s', (_label, state, error) => {
    const view = buildCollaborationViewModel(input({
      taskCards: { state, data: [], error },
      taskDetails: { state, data: [], error },
      marketBoard: { state, error },
      inbox: { state, data: [], error },
    }))

    expect(view.records.data).toEqual([])
    expect(view.timeline.data).toEqual([])
    expect(view.authorizations.data).toEqual([])
    expect(view.market.data.signals.value).toEqual([])
    expect(view.market.data.matches.value).toEqual([])
    for (const module of [
      view.overview,
      view.tabs,
      view.records,
      view.timeline,
      view.market,
      view.authorizations,
    ]) {
      expect(module.sources).not.toContain('M')
      expect(module.error).toBe(error)
    }
  })
})
