import { describe, expect, it } from 'vitest'

import type { components } from '../../api/generated/schema'
import {
  CURRENT_PROJECT_INSIGHT,
  INSIGHT_OVERVIEW,
  RECURRING_PROBLEM,
  REVIEW_FLOW,
  REVIEW_PROJECT,
} from '../../data/mockData'
import type { PresentationState } from '../../lib/presentation'
import type {
  ActivityTodayResponse,
  AuditListResponse,
  BlackboardTaskCardsResponse,
  MemoryOverviewResponse,
} from './api'
import { buildInsightsViewModel, gateInsightsAggregates } from './presenter'

type Project = components['schemas']['Project']

const project = {
  id: 'project-618',
  workspace_id: 'workspace-design',
  name: '真实 618 项目',
  goal: '验证首屏入口效率',
  status: 'active',
} satisfies Project

const tasks = {
  items: [
    {
      task: {
        id: 'task-brief',
        thread_id: 'thread-brief',
        intent: 'generate_brief',
        status: 'running',
        collaboration_stage: 'discussion',
        title: '真实 Brief 任务',
      },
      done_when: '负责人确认 Brief',
      post_count: 2,
      initiated_by_current_user: true,
      claimed_by_personal_agent: true,
      allowed_actions: ['open'],
    },
  ],
} satisfies BlackboardTaskCardsResponse

const activity = {
  personal: [
    {
      id: 'activity-personal',
      actor: '林知夏',
      title: '真实项目活动',
      summary: '确认了首屏数据口径',
      category: 'project',
      scope: 'project',
      project_id: project.id,
    },
  ],
  external: [],
} satisfies ActivityTodayResponse

const memory = {
  project_id: project.id,
  sections: { short: [], project: [], archive: [], team: [] },
  counts: { short: 1, project: 2, archive: 3, team: 4 },
} satisfies MemoryOverviewResponse

const audit = {
  items: [
    {
      id: 'audit-1',
      actor: 'agent-1',
      action: 'brief.read',
      target_type: 'task',
      target_id: 'task-brief',
      project_id: project.id,
    },
  ],
  total: 1,
  limit: 20,
  counts: { 'brief.read': 1 },
} satisfies AuditListResponse

const resource = <T>(state: PresentationState, data?: T, error?: string) => ({ state, data, error })
const unavailable = (state: PresentationState, error?: string) => ({ state, error })

const input = (aggregateState: PresentationState = 'unsupported') => ({
  project,
  tasks: resource('available', tasks),
  activity: resource('available', activity),
  memory: resource('available', memory),
  audit: resource('available', audit),
  aggregates: {
    crossProjectInsight: unavailable(aggregateState),
    kpis: unavailable(aggregateState),
    review: unavailable(aggregateState),
    workflowRecommendation: unavailable(aggregateState),
  },
})

const knowledgeFormationReference = {
  missingHint: REVIEW_FLOW.missingHint,
  resultPlaceholder: REVIEW_FLOW.resultPlaceholder,
  candidateReadyHint: REVIEW_FLOW.candidateReadyHint,
  candidateTitle: REVIEW_FLOW.candidateTitle,
}


describe('buildInsightsViewModel', () => {
  it('keeps every real current-project read model as T data', () => {
    const model = buildInsightsViewModel(input())

    const realFields = [
      [model.workOverview.data.project, project],
      [model.workOverview.data.tasks, tasks],
      [model.workOverview.data.activity, activity],
      [model.insight.data.memory, memory],
      [model.insight.data.audit, audit],
    ] as const

    for (const [presented, expected] of realFields) {
      expect(presented).toEqual({ value: expected, source: 'T' })
    }
  })

  it.each(['empty', 'unsupported'] as const)(
    'preserves the reference overview, insight, review, evidence, and knowledge-formation modules with explicit M provenance for %s aggregates',
    (state) => {
      const model = buildInsightsViewModel(input(state))

      expect(Object.keys(model)).toEqual(
        expect.arrayContaining(['workOverview', 'insight', 'review', 'evidence', 'knowledgeFormation']),
      )
      const references = [
        [model.workOverview, model.workOverview.data.overview, INSIGHT_OVERVIEW],
        [model.insight, model.insight.data.currentProject, CURRENT_PROJECT_INSIGHT],
        [model.insight, model.insight.data.crossProject, RECURRING_PROBLEM],
        [model.review, model.review.data.opportunity, REVIEW_PROJECT],
        [model.review, model.review.data.kpis, REVIEW_PROJECT.materials],
        [model.evidence, model.evidence.data.items, REVIEW_FLOW.evidence],
        [model.knowledgeFormation, model.knowledgeFormation.data.flow, knowledgeFormationReference],
        [model.knowledgeFormation, model.knowledgeFormation.data.workflowRecommendation, CURRENT_PROJECT_INSIGHT.skill],
      ] as const
      for (const [module, presented, expected] of references) {
        expect(presented).toEqual({
          value: expected,
          source: 'M',
          reason: expect.any(String),
        })
        expect(module.sources).toContain('M')
      }
    },
  )
  it.each([
    ['empty', undefined],
    ['loading', undefined],
    ['forbidden', 'Permission denied'],
    ['error', 'Network unavailable'],
  ] as const)(
    'suppresses every Mock aggregate when a current-project dependency is %s',
    (state, error) => {
      const base = input('unsupported')
      const blockedMemory = resource<MemoryOverviewResponse>(state, undefined, error)
      const aggregates = gateInsightsAggregates(
        [base.tasks, base.activity, blockedMemory, base.audit],
        base.aggregates,
      )
      const model = buildInsightsViewModel({
        ...base,
        memory: blockedMemory,
        aggregates,
      })

      const references = [
        model.workOverview.data.overview,
        model.insight.data.currentProject,
        model.insight.data.crossProject,
        model.review.data.opportunity,
        model.review.data.kpis,
        model.evidence.data.items,
        model.knowledgeFormation.data.flow,
        model.knowledgeFormation.data.workflowRecommendation,
      ]
      for (const presented of references) expect(presented).toBeUndefined()
      for (const moduleName of ['workOverview', 'insight', 'review', 'evidence', 'knowledgeFormation'] as const) {
        expect(model[moduleName].sources).not.toContain('M')
        expect(model[moduleName].loading).toBe(state === 'loading')
        expect(model[moduleName].error).toBe(error ?? null)
      }
      expect(model.mockActions).toEqual([])
    },
  )


  it.each([
    ['forbidden', 'Permission denied'],
    ['error', 'Network unavailable'],
  ] as const)('does not turn %s or permission-filtered empty results into Mock data', (state, error) => {
    const emptyTasks = { items: [] } satisfies BlackboardTaskCardsResponse
    const emptyActivity = { personal: [], external: [] } satisfies ActivityTodayResponse
    const emptyMemory = {
      project_id: project.id,
      sections: { short: [], project: [], archive: [], team: [] },
      counts: { short: 0, project: 0, archive: 0, team: 0 },
    } satisfies MemoryOverviewResponse
    const emptyAudit = { items: [], total: 0, limit: 20, counts: {} } satisfies AuditListResponse

    const model = buildInsightsViewModel({
      project,
      tasks: resource(state, emptyTasks, error),
      activity: resource(state, emptyActivity, error),
      memory: resource(state, emptyMemory, error),
      audit: resource(state, emptyAudit, error),
      aggregates: {
        crossProjectInsight: unavailable(state, error),
        kpis: unavailable(state, error),
        review: unavailable(state, error),
        workflowRecommendation: unavailable(state, error),
      },
    })

    expect(model.workOverview.data.tasks).toBeUndefined()
    expect(model.workOverview.data.activity).toBeUndefined()
    expect(model.insight.data.memory).toBeUndefined()
    expect(model.insight.data.audit).toBeUndefined()
    const references = [
      model.workOverview.data.overview,
      model.insight.data.currentProject,
      model.insight.data.crossProject,
      model.review.data.opportunity,
      model.review.data.kpis,
      model.evidence.data.items,
      model.knowledgeFormation.data.flow,
      model.knowledgeFormation.data.workflowRecommendation,
    ]
    for (const presented of references) expect(presented).toBeUndefined()
    for (const moduleName of ['workOverview', 'insight', 'review', 'evidence', 'knowledgeFormation'] as const) {
      expect(model[moduleName].sources).not.toContain('M')
      expect(model[moduleName].error).toBe(error)
    }
    expect(model.mockActions).toEqual([])
  })

  it('marks Mock-only review, recommendation, and knowledge actions unavailable without exposing a success mutation', () => {
    const model = buildInsightsViewModel(input('unsupported'))

    expect(model.mockActions.map((action) => action.value.id)).toEqual(
      expect.arrayContaining(['start-review', 'apply-workflow-recommendation', 'form-knowledge-candidate']),
    )
    for (const action of model.mockActions) {
      expect(action.source).toBe('M')
      expect(action.reason).toEqual(expect.any(String))
      expect(action.value.available).toBe(false)
      expect(action.value).not.toHaveProperty('mutation')
      expect(action.value).not.toHaveProperty('mutate')
      expect(action.value).not.toHaveProperty('execute')
      expect(action.value).not.toHaveProperty('success')
      expect(action.value).not.toHaveProperty('onSuccess')
    }
  })
})
