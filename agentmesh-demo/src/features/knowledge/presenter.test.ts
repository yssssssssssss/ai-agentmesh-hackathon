import { describe, expect, it } from 'vitest'

import { KNOWLEDGE_ASSETS, SHARE_EVENTS } from '../../data/mockData'
import type { PresentationState } from '../../lib/presentation'
import type {
  DocumentRecord,
  InboxItem,
  MemoryItem,
  MemoryOverview,
  UserMemoryItem,
} from './api'
import { buildKnowledgeViewModel } from './presenter'

type Resource<T> = {
  state: PresentationState
  data?: T
  error?: string
}

const userMemory: UserMemoryItem = {
  id: 'ka-tag',
  user_id: 'user-1',
  layer: 'short_term',
  title: '服务端个人知识',
  summary: '个人记忆中的真实结论。',
  source_kind: 'project_review',
  memory_type: 'design_rule',
  sensitivity: 'normal',
  scope: 'private',
  workspace_id: 'workspace-1',
  project_id: 'project-1',
  sources: [],
  status: 'active',
  updated_at: '2026-08-14T08:00:00Z',
}

const acceptedMemory: MemoryItem = {
  id: 'ka-floor',
  title: '服务端团队知识',
  summary: '团队已接受的真实结论。',
  memory_type: 'decision_method',
  scope: 'team_accepted',
  status: 'accepted',
  workspace_id: 'workspace-1',
  project_id: 'project-1',
  sources: [],
  created_at: '2026-08-13T08:00:00Z',
  allowed_actions: ['read'],
}

const candidateMemory: MemoryItem = {
  id: 'candidate-1',
  title: '服务端团队候选',
  summary: '等待负责人审核。',
  memory_type: 'project_experience',
  scope: 'team_candidate',
  status: 'proposed',
  workspace_id: 'workspace-1',
  project_id: 'project-1',
  sources: [],
  created_at: '2026-08-14T09:00:00Z',
  allowed_actions: ['accept'],
}

const ignoredCandidate: MemoryItem = {
  ...candidateMemory,
  id: 'candidate-accepted',
  title: '不应重复进入待确认',
  status: 'accepted',
  allowed_actions: [],
}

const openInbox: InboxItem = {
  id: 'inbox-1',
  title: '确认 Brief 知识',
  summary: '确认后生成团队候选。',
  item_type: 'brief_confirmation',
  scope: 'private',
  user_id: 'user-1',
  status: 'open',
  workspace_id: 'workspace-1',
  project_id: 'project-1',
  metadata: {
    document_id: 'document-1',
  },
  created_at: '2026-08-14T10:00:00Z',
  updated_at: '2026-08-14T10:00:00Z',
  allowed_actions: ['confirm_brief', 'snooze'],
}

const resolvedInbox: InboxItem = {
  ...openInbox,
  id: 'inbox-resolved',
  title: '已处理 Inbox',
  status: 'resolved',
  allowed_actions: [],
}

const document: DocumentRecord = {
  id: 'document-1',
  title: '服务端 Brief 文档',
  text: '文档中的真实正文。',
  file_name: 'brief-v7.md',
  version: 7,
}

const overview: MemoryOverview = {
  project_id: 'project-1',
  sections: {
    short: [userMemory],
    project: [],
    archive: [],
    team: [acceptedMemory, candidateMemory],
  },
  counts: { short: 1, project: 0, archive: 0, team: 2 },
}

const realReuseEvent = {
  id: 'reuse-real-1',
  type: 'reused' as const,
  knowledgeId: 'ka-floor',
  knowledgeTitle: '服务端团队知识',
  actor: '真实数字员工',
  project: '真实复用项目',
  purpose: '验证楼层排序',
  time: '2026-08-14T11:00:00Z',
  statusLabel: '已授权',
  tone: 'mint' as const,
  description: '真实复用记录。',
  primaryAction: '查看引用详情',
  allowed_actions: ['read'],
}

function resource<T>(state: PresentationState, data?: T, error?: string): Resource<T> {
  return { state, data, error }
}

function input(overrides: Record<string, unknown> = {}) {
  return {
    projectId: 'project-1',
    projectName: '真实项目',
    inbox: resource('available', { items: [openInbox, resolvedInbox] }),
    memory: resource('available', {
      items: [acceptedMemory, candidateMemory, ignoredCandidate],
    }),
    overview: resource('available', overview),
    documents: resource('available', { items: [document] }),
    usage: resource('available', { items: [realReuseEvent] }),
    ...overrides,
  }
}

describe('buildKnowledgeViewModel', () => {
  it('maps canonical resources into exactly the three reference tabs with T-first provenance', () => {
    const viewModel = buildKnowledgeViewModel(input())

    expect(viewModel.tabs).toEqual([
      { key: 'assets', label: '已沉淀知识', count: { value: 3, source: 'T' } },
      { key: 'pending', label: '待我确认', count: { value: 2, source: 'T' } },
      { key: 'shared', label: '使用与反馈', count: { value: 2, source: 'T' } },
    ])

    expect(viewModel.assets.data.items.map((item) => item.kind)).toEqual([
      'user_memory',
      'accepted_memory',
      'document',
    ])
    expect(viewModel.assets.data.items.map((item) => item.title.value)).toEqual([
      '服务端个人知识',
      '服务端团队知识',
      '服务端 Brief 文档',
    ])
    expect(viewModel.assets.data.items.every((item) => item.title.source === 'T')).toBe(true)
    expect(viewModel.assets.sources).toEqual(['T', 'M'])

    const acceptedAsset = viewModel.assets.data.items.find((item) => item.kind === 'accepted_memory')
    expect(acceptedAsset?.title).toEqual({ value: '服务端团队知识', source: 'T' })
    expect(acceptedAsset?.allowedActions).toEqual({ value: ['read'], source: 'T' })
    expect(acceptedAsset?.citedBy).toMatchObject({
      value: KNOWLEDGE_ASSETS.find((item) => item.id === 'ka-floor')?.citedBy,
      source: 'M',
    })

    const documentAsset = viewModel.assets.data.items.find((item) => item.kind === 'document')
    expect(documentAsset?.version).toEqual({ value: 7, source: 'T' })

    expect(viewModel.pending.data.items.map((item) => item.kind)).toEqual([
      'inbox',
      'team_candidate',
    ])
    expect(viewModel.pending.data.items.map((item) => item.id.value)).toEqual([
      'inbox-1',
      'candidate-1',
    ])
    expect(viewModel.pending.data.items[0]).toMatchObject({
      allowedActions: { value: ['confirm_brief', 'snooze'], source: 'T' },
      documentVersion: { value: 7, source: 'T' },
    })
    expect(viewModel.pending.data.items[1].allowedActions).toEqual({
      value: ['accept'],
      source: 'T',
    })

    expect(viewModel.usage.data.items.map((item) => item.kind)).toEqual([
      'accepted_memory',
      'reuse_event',
    ])
    expect(viewModel.usage.data.items.map((item) => item.id.value)).toEqual([
      'ka-floor',
      'reuse-real-1',
    ])
    expect(viewModel.usage.data.items[1].allowedActions).toEqual({
      value: ['read'],
      source: 'T',
    })
    expect(viewModel.usage.sources).toEqual(['T'])
  })

  it.each([
    { state: 'unsupported', fallback: true },
    { state: 'empty', fallback: true },
    { state: 'error', fallback: false },
    { state: 'forbidden', fallback: false },
  ] as const)(
    'uses the reference timeline for $state only when fallback is safe',
    ({ state, fallback }) => {
      const error = state === 'error' ? '网络请求失败' : state === 'forbidden' ? '没有查看权限' : undefined
      const viewModel = buildKnowledgeViewModel(
        input({
          memory: resource('available', { items: [] }),
          overview: resource('available', {
            ...overview,
            sections: { short: [], project: [], archive: [], team: [] },
            counts: { short: 0, project: 0, archive: 0, team: 0 },
          }),
          usage: resource(state, undefined, error),
        }),
      )

      if (fallback) {
        expect(viewModel.usage.sources).toEqual(['M'])
        expect(viewModel.usage.data.items.map((item) => item.id.value)).toEqual(
          SHARE_EVENTS.map((event) => event.id),
        )
        expect(viewModel.usage.data.items.every((item) => item.allowedActions.value.length === 0)).toBe(true)
        expect(viewModel.tabs[2].count).toEqual({ value: SHARE_EVENTS.length, source: 'M' })
      } else {
        expect(viewModel.usage.sources).toEqual([])
        expect(viewModel.usage.data.items).toEqual([])
        expect(viewModel.usage.error).toBe(error)
        expect(viewModel.tabs[2].count).toEqual({ value: 0, source: 'T' })
      }
    },
  )

  it('clones reference events and never exposes a mock-backed mutation', () => {
    const before = structuredClone(SHARE_EVENTS)
    const viewModel = buildKnowledgeViewModel(
      input({
        memory: resource('available', { items: [] }),
        usage: resource('unsupported'),
      }),
    )

    expect(SHARE_EVENTS).toEqual(before)
    expect(viewModel.usage.data.items[0]).not.toBe(SHARE_EVENTS[0])
    expect(
      viewModel.usage.data.items.every(
        (item) =>
          item.allowedActions.source === 'M' &&
          item.allowedActions.value.length === 0 &&
          Object.values(item).every((value) => typeof value !== 'function'),
      ),
    ).toBe(true)
  })

  it('resolves the Brief version from the referenced canonical document', () => {
    const viewModel = buildKnowledgeViewModel(
      input({
        inbox: resource('available', {
          items: [
            {
              ...openInbox,
              metadata: {
                document_id: 'document-1',
              },
            },
          ],
        }),
      }),
    )

    expect(viewModel.pending.data.items[0].documentVersion).toEqual({
      value: 7,
      source: 'T',
    })
  })

  it('maps SDK tool interruptions into distinct call-scoped approvals', () => {
    const toolApproval: InboxItem = {
      ...openInbox,
      id: 'inbox-tool-approval',
      item_type: 'sdk_tool_approval',
      metadata: {
        run_id: 'run-1',
        interruptions: JSON.stringify([
          { call_id: 'call-a', name: 'web_research', argument_keys: 'query, locale' },
          { call_id: 'call-b', name: 'save_draft', argument_keys: 'content' },
          { call_id: 'call-a', name: 'duplicate', argument_keys: '' },
          { name: 'missing_call_id', argument_keys: '' },
        ]),
      },
      allowed_actions: ['snooze', 'approve_tool', 'reject_tool'],
    }
    const viewModel = buildKnowledgeViewModel(input({
      inbox: resource('available', { items: [toolApproval] }),
    }))

    expect(viewModel.pending.data.items[0].toolCalls).toEqual({
      source: 'T',
      value: [
        { callId: 'call-a', name: 'web_research', argumentKeys: ['query', 'locale'] },
        { callId: 'call-b', name: 'save_draft', argumentKeys: ['content'] },
      ],
    })
  })

  it('fails closed when SDK tool interruption metadata is malformed', () => {
    const viewModel = buildKnowledgeViewModel(input({
      inbox: resource('available', {
        items: [{
          ...openInbox,
          item_type: 'sdk_tool_approval',
          metadata: { interruptions: '{not-json' },
          allowed_actions: ['approve_tool', 'reject_tool'],
        }],
      }),
    }))

    expect(viewModel.pending.data.items[0].toolCalls).toEqual({ value: [], source: 'T' })
  })
})
