import { describe, expect, it } from 'vitest'

import {
  KNOWLEDGE_ASSETS,
  PRIORITY_ITEMS,
  SHARE_EVENTS,
  UNDERSTANDINGS,
} from '../../data/mockData'
import type { BootstrapState } from '../auth/api'
import type { ActivityTodayResponse, Agent, MemoryOverviewResponse } from './api'
import { buildDigitalSelfViewModel } from './presenter'

const bootstrap: BootstrapState = {
  workspace: {
    id: 'workspace-1',
    name: '真实工作空间',
    description: '服务端工作空间',
  },
  project: {
    id: 'project-1',
    workspace_id: 'workspace-1',
    name: '真实项目',
    goal: '提升真实项目的首屏效率',
    status: 'active',
  },
  user: {
    id: 'user-1',
    workspace_id: 'workspace-1',
    default_project_id: 'project-1',
    name: '真实用户',
    role: 'user',
    status: 'active',
    personal_agent_id: 'agent-1',
  },
  users: [],
  agents: [],
  metrics: {
    personal_activity_count: 1,
    external_activity_count: 0,
    memory_candidate_count: 0,
    source_count: 2,
    inbox_open_count: 1,
  },
  capabilities: ['workspace:read'],
  agent_runtime_enabled: false,
  skill_orchestration_mode: 'off',
}

const agent: Agent = {
  id: 'agent-1',
  workspace_id: 'workspace-1',
  name: '真实用户的数字人',
  agent_type: 'personal',
  description: '真实 Agent 描述',
  status: 'online',
  runtime_status: 'working',
  current_task_id: 'task-1',
  current_task_title: '正在处理真实项目',
  owner_user_id: 'user-1',
  capabilities: ['memory:read'],
}

const activity: ActivityTodayResponse = {
  personal: [
    {
      id: 'activity-1',
      actor: '真实用户的数字人',
      user_id: 'user-1',
      title: '整理真实项目资料',
      summary: '已完成服务端活动记录整理',
      category: 'brief_generation',
      scope: 'private',
      workspace_id: 'workspace-1',
      project_id: 'project-1',
    },
  ],
  external: [],
}

const memory: MemoryOverviewResponse = {
  project_id: 'project-1',
  sections: {
    short: [
      {
        id: 'memory-1',
        user_id: 'user-1',
        layer: 'short_term',
        title: '真实近期工作重点',
        summary: '优先提升真实项目的首屏入口效率',
        source_kind: 'chat',
        memory_type: 'understanding',
        sensitivity: 'normal',
        scope: 'private',
        workspace_id: 'workspace-1',
        project_id: 'project-1',
        status: 'active',
      },
    ],
    project: [],
    archive: [],
    team: [],
  },
  counts: { short: 1, project: 2, archive: 3, team: 4 },
}

const available = <T>(data: T) => ({ state: 'available' as const, data })
const baseInput = {
  bootstrap: available(bootstrap),
  agent: available(agent),
  activity: available(activity),
  memory: available(memory),
}

const CATEGORY_REASON = '后端暂无经验、方法与协作分类聚合'
const IMPACT_REASON = '后端暂无经验复用记录'
const EMPTY_FALLBACK_REASON = '真实列表为空，使用参考展示数据'

const mockGrowthCategories = () => {
  const experiences = KNOWLEDGE_ASSETS.filter((item) => item.type === 'project_experience')
  const methods = KNOWLEDGE_ASSETS.filter((item) => item.type === 'decision_method')
  const reused = SHARE_EVENTS.filter((event) => event.type === 'reused')
  const collaborators = new Set(reused.map((event) => event.actor)).size

  return [
    {
      metric: { value: `+${experiences.length}`, source: 'M', reason: CATEGORY_REASON },
      label: { value: '已确认经验', source: 'M', reason: CATEGORY_REASON },
      value: { value: experiences[0]?.title ?? '暂无参考经验', source: 'M', reason: CATEGORY_REASON },
    },
    {
      metric: { value: `+${methods.length}`, source: 'M', reason: CATEGORY_REASON },
      label: { value: '工作方法', source: 'M', reason: CATEGORY_REASON },
      value: { value: methods[0]?.title ?? '暂无参考方法', source: 'M', reason: CATEGORY_REASON },
    },
    {
      metric: { value: `+${reused.length}`, source: 'M', reason: CATEGORY_REASON },
      label: { value: '次协作', source: 'M', reason: CATEGORY_REASON },
      value: { value: `${collaborators} 位数字人复用经验`, source: 'M', reason: CATEGORY_REASON },
    },
  ]
}

describe('buildDigitalSelfViewModel', () => {
  it('preserves the reference module order and keeps every available backend field as T data', () => {
    const viewModel = buildDigitalSelfViewModel(baseInput)

    expect(Object.keys(viewModel)).toEqual([
      'hero',
      'pending',
      'understanding',
      'growth',
      'impact',
    ])
    expect(viewModel.hero).toMatchObject({
      data: {
        greeting: { value: '下午好，真实用户', source: 'T' },
        workspaceName: { value: '真实工作空间', source: 'T' },
        projectName: { value: '真实项目', source: 'T' },
        projectGoal: { value: '提升真实项目的首屏效率', source: 'T' },
        agentName: { value: '真实用户的数字人', source: 'T' },
        agentStatus: { value: 'online', source: 'T' },
        currentTask: { value: '正在处理真实项目', source: 'T' },
        progressNarrative: {
          source: 'M',
          reason: '后端暂无推进叙事',
        },
        participantCount: {
          source: 'M',
          reason: '后端暂无参与人数聚合',
        },
      },
      sources: ['T', 'M'],
      missingFields: ['progressNarrative', 'participantCount'],
      loading: false,
      error: null,
    })
    expect(viewModel.pending).toEqual({
      data: {
        items: [
          {
            id: { value: 'activity-1', source: 'T' },
            title: { value: '整理真实项目资料', source: 'T' },
            context: { value: '已完成服务端活动记录整理', source: 'T' },
            tag: { value: 'brief_generation', source: 'T' },
            actor: { value: '真实用户的数字人', source: 'T' },
          },
        ],
      },
      sources: ['T'],
      missingFields: [],
      loading: false,
      error: null,
    })
    expect(viewModel.understanding).toEqual({
      data: {
        items: [
          {
            id: { value: 'memory-1', source: 'T' },
            text: { value: '优先提升真实项目的首屏入口效率', source: 'T' },
            basis: { value: '真实近期工作重点', source: 'T' },
            source: { value: 'chat', source: 'T' },
          },
        ],
      },
      sources: ['T'],
      missingFields: [],
      loading: false,
      error: null,
    })
  })

  it('keeps real memory totals while marking only the unavailable growth categories as M data', () => {
    const growth = buildDigitalSelfViewModel(baseInput).growth

    expect(growth).toEqual({
      data: {
        memoryCounts: {
          short: { value: 1, source: 'T' },
          project: { value: 2, source: 'T' },
          archive: { value: 3, source: 'T' },
          team: { value: 4, source: 'T' },
        },
        categories: mockGrowthCategories(),
      },
      sources: ['T', 'M'],
      missingFields: ['categoryAggregation'],
      loading: false,
      error: null,
    })
  })

  it('builds the impact card only from current mockData and exposes no mock mutation', () => {
    const reused = SHARE_EVENTS.filter((event) => event.type === 'reused')
    const collaborators = new Set(reused.map((event) => event.actor)).size
    const impact = buildDigitalSelfViewModel(baseInput).impact

    expect(impact).toEqual({
      data: {
        items: [
          ...reused.slice(0, 2).map((event) => ({
            label: { value: event.knowledgeTitle, source: 'M', reason: IMPACT_REASON },
            value: { value: event.description, source: 'M', reason: IMPACT_REASON },
            meta: { value: event.time, source: 'M', reason: IMPACT_REASON },
          })),
          {
            label: { value: '本周影响', source: 'M', reason: IMPACT_REASON },
            value: {
              value: `帮助 ${collaborators} 位同事 · 被调用 ${reused.length} 次`,
              source: 'M',
              reason: IMPACT_REASON,
            },
            meta: { value: '', source: 'M', reason: IMPACT_REASON },
          },
        ],
        mutation: null,
      },
      sources: ['M'],
      missingFields: ['reuseRecords'],
      loading: false,
      error: null,
    })
  })

  it('uses the reference lists for allowed empty or unsupported display-only resources', () => {
    const viewModel = buildDigitalSelfViewModel({
      ...baseInput,
      activity: { state: 'empty' as const },
      memory: { state: 'unsupported' as const },
    })

    expect(viewModel.pending.data.items).toEqual(
      PRIORITY_ITEMS.map((item) => ({
        id: { value: item.id, source: 'M', reason: EMPTY_FALLBACK_REASON },
        title: { value: item.title, source: 'M', reason: EMPTY_FALLBACK_REASON },
        context: { value: item.context, source: 'M', reason: EMPTY_FALLBACK_REASON },
        tag: { value: item.tag, source: 'M', reason: EMPTY_FALLBACK_REASON },
        cta: { value: item.cta, source: 'M', reason: EMPTY_FALLBACK_REASON },
        to: { value: item.to, source: 'M', reason: EMPTY_FALLBACK_REASON },
      })),
    )
    expect(viewModel.pending).toMatchObject({
      sources: ['M'],
      missingFields: ['activity'],
      loading: false,
      error: null,
    })
    expect(viewModel.understanding.data.items).toEqual(
      UNDERSTANDINGS.map((item) => ({
        id: { value: item.id, source: 'M', reason: EMPTY_FALLBACK_REASON },
        text: { value: item.text, source: 'M', reason: EMPTY_FALLBACK_REASON },
        basis: { value: item.basis, source: 'M', reason: EMPTY_FALLBACK_REASON },
        source: { value: item.source, source: 'M', reason: EMPTY_FALLBACK_REASON },
      })),
    )
    expect(viewModel.understanding).toMatchObject({
      sources: ['M'],
      missingFields: ['memory'],
      loading: false,
      error: null,
    })
    expect(viewModel.growth).toEqual({
      data: {
        memoryCounts: null,
        categories: mockGrowthCategories(),
      },
      sources: ['M'],
      missingFields: ['memoryOverview', 'categoryAggregation'],
      loading: false,
      error: null,
    })
  })

  it.each([
    ['empty', true, null],
    ['unsupported', true, null],
    ['forbidden', false, '403 Forbidden'],
    ['error', false, 'memory unavailable'],
  ] as const)(
    'uses reference understanding for %s memory only when the state is an allowed fallback',
    (state, allowsFallback, error) => {
      const understanding = buildDigitalSelfViewModel({
        ...baseInput,
        memory: error === null ? { state } : { state, error },
      }).understanding

      expect(understanding.data.items).toHaveLength(allowsFallback ? UNDERSTANDINGS.length : 0)
      expect(understanding.sources).toEqual(allowsFallback ? ['M'] : [])
      expect(understanding.error).toBe(error)
    },
  )

  it('does not turn loading resources into mock content', () => {
    const viewModel = buildDigitalSelfViewModel({
      ...baseInput,
      agent: { state: 'loading' as const },
      activity: { state: 'loading' as const },
      memory: { state: 'loading' as const },
    })

    expect(viewModel.hero).toMatchObject({
      data: {
        agentName: null,
        agentStatus: null,
        currentTask: null,
      },
      loading: true,
    })
    expect(viewModel.pending).toMatchObject({
      data: { items: [] },
      sources: [],
      loading: true,
      error: null,
    })
    expect(viewModel.understanding).toMatchObject({
      data: { items: [] },
      sources: [],
      loading: true,
      error: null,
    })
    expect(viewModel.growth).toMatchObject({
      data: { memoryCounts: null, categories: [] },
      sources: [],
      loading: true,
      error: null,
    })
  })

  it('propagates backend failures without substituting identity, activity, or memory mock data', () => {
    const viewModel = buildDigitalSelfViewModel({
      bootstrap: { state: 'error' as const, error: 'bootstrap unavailable' },
      agent: { state: 'error' as const, error: 'agent unavailable' },
      activity: { state: 'error' as const, error: 'activity unavailable' },
      memory: { state: 'error' as const, error: 'memory unavailable' },
    })

    expect(viewModel.hero).toEqual({
      data: null,
      sources: [],
      missingFields: [],
      loading: false,
      error: 'bootstrap unavailable',
    })
    expect(viewModel.pending).toMatchObject({
      data: { items: [] },
      sources: [],
      error: 'activity unavailable',
    })
    expect(viewModel.understanding).toMatchObject({
      data: { items: [] },
      sources: [],
      error: 'memory unavailable',
    })
    expect(viewModel.growth).toMatchObject({
      data: { memoryCounts: null, categories: [] },
      sources: [],
      error: 'memory unavailable',
    })
    expect(viewModel.impact.sources).toEqual(['M'])
  })

  it('keeps permission-filtered resources empty instead of leaking reference records', () => {
    const viewModel = buildDigitalSelfViewModel({
      ...baseInput,
      activity: { state: 'forbidden' as const, error: '403 Forbidden' },
      memory: { state: 'forbidden' as const, error: '403 Forbidden' },
    })

    expect(viewModel.pending).toMatchObject({
      data: { items: [] },
      sources: [],
      error: '403 Forbidden',
    })
    expect(viewModel.understanding).toMatchObject({
      data: { items: [] },
      sources: [],
      error: '403 Forbidden',
    })
    expect(viewModel.growth).toMatchObject({
      data: { memoryCounts: null, categories: [] },
      sources: [],
      error: '403 Forbidden',
    })
  })
})
