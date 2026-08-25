import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Children, isValidElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { SkillMatch, SkillMatchResponse } from '../workspace/types'
import {
  SkillRecommendationPanel,
  SkillMatchOutcome,
  SkillMatchResults,
  skillMatchDraft,
  skillMatchModePresentation,
  skillMatchResponseMatchesTask,
  shouldResetSkillMatchState,
  visibleSkillMatches,
} from './SkillRecommendationPanel'

function match(index: number, overrides: Partial<SkillMatch> = {}): SkillMatch {
  return {
    skill_id: `skill-${index}`,
    skill_name: `skill-${index}`,
    command: `$skill-${index}`,
    title: `Skill ${index}`,
    description: `Skill ${index} description`,
    primary_stage: 'pre_design',
    score: 0.8,
    planner_eligible: false,
    readiness: 'ready',
    execution_readiness: 'complete',
    missing_tools: [],
    reason: `Reason ${index}`,
    ...overrides,
  }
}

function response(overrides: Partial<SkillMatchResponse> = {}): SkillMatchResponse {
  return {
    items: [],
    mode: 'hybrid',
    ...overrides,
  }
}

function firstClickHandler(node: ReactNode): (() => void) | undefined {
  if (!isValidElement<{ children?: ReactNode; onClick?: () => void }>(node)) return undefined
  if (node.props.onClick) return node.props.onClick
  for (const child of Children.toArray(node.props.children)) {
    const handler = firstClickHandler(child)
    if (handler) return handler
  }
  return undefined
}

describe('SkillRecommendationPanel', () => {
  it('keeps the task in the Composer draft selected from a recommendation', () => {
    expect(skillMatchDraft(match(1), '  评审商品详情页体验  ')).toBe('$skill-1 评审商品详情页体验')
  })

  it('keeps a completed recommendation bound to task A after the editor changes to task B', () => {
    const submittedTask = '任务 A：评审商品详情页'
    const currentEditorTask = '任务 B：生成用户访谈纲要'
    const onUseSkill = vi.fn()
    const results = SkillMatchResults({ matches: [match(1)], submittedTask, onUseSkill })

    const onClick = firstClickHandler(results)
    expect(onClick).toBeTypeOf('function')
    onClick?.()

    expect(onUseSkill).toHaveBeenCalledWith('$skill-1 任务 A：评审商品详情页')
    expect(onUseSkill).not.toHaveBeenCalledWith(expect.stringContaining(currentEditorTask))
  })

  it('does not present a completed response beside a different editor task', () => {
    expect(skillMatchResponseMatchesTask('任务 A：评审商品详情页', '任务 B：生成用户访谈纲要')).toBe(false)
    expect(skillMatchResponseMatchesTask('任务 A：评审商品详情页', ' 任务 A：评审商品详情页 ')).toBe(true)
  })

  it('discards pending or completed state as soon as the editor task changes', () => {
    expect(shouldResetSkillMatchState('任务 A', '任务 B', false)).toBe(true)
    expect(shouldResetSkillMatchState('任务 A', ' 任务 A ', false)).toBe(false)
    expect(shouldResetSkillMatchState('任务 A', '任务 B', true)).toBe(false)
  })

  it('gives the task editor a stable form name', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <SkillRecommendationPanel onUseSkill={vi.fn()} />
      </QueryClientProvider>,
    )

    expect(html).toContain('name="skill-match-task"')
  })

  it('shows at most five callable matches with stage, reason, and invocation mode', () => {
    const matches = [
      match(1, { primary_stage: undefined }),
      match(2, { primary_stage: 'during_design', planner_eligible: true }),
      match(3),
      match(4),
      match(5),
      match(6),
      match(7, { readiness: 'unavailable' }),
      match(8, { execution_readiness: 'unavailable' }),
    ]

    expect(visibleSkillMatches(matches).map((item) => item.skill_id)).toEqual([
      'skill-1',
      'skill-2',
      'skill-3',
      'skill-4',
      'skill-5',
    ])

    const html = renderToStaticMarkup(
      <SkillMatchResults matches={matches} submittedTask="评审商品详情页体验" onUseSkill={vi.fn()} />,
    )

    expect(html.match(/data-testid="skill-match-result"/g)).toHaveLength(5)
    expect(html).toContain('未分类 Skill')
    expect(html).toContain('设计中')
    expect(html).toContain('Reason 2')
    expect(html).toContain('可自动编排')
    expect(html).toContain('可显式调用')
    expect(html).toContain('使用此 Skill')
    expect(html).toContain('aria-label="使用 Skill：Skill 1"')
    expect(html).toContain('break-words')
    expect(html).toContain('break-all')
    expect(html).not.toContain('Skill 6')
    expect(html).not.toContain('Skill 7')
    expect(html).not.toContain('Skill 8')
  })

  it('marks missing tools without blocking explicit invocation', () => {
    const onUseSkill = vi.fn()
    const limited = match(1, {
      execution_readiness: 'tool_limited',
      missing_tools: ['Bash', 'Read', 'Write', 'mcp__zero-design__get_screenshot'],
    })
    const results = SkillMatchResults({ matches: [limited], submittedTask: '评审商品详情页体验', onUseSkill })
    const html = renderToStaticMarkup(results)

    expect(html).toContain('已接入 · 工具待接通')
    expect(html).toContain('待接通工具：Bash、Read、Write 等 4 项')
    expect(html).toContain('使用此 Skill')

    firstClickHandler(results)?.()
    expect(onUseSkill).toHaveBeenCalledWith('$skill-1 评审商品详情页体验')
  })

  it('shows clarification instead of an empty recommendation result', () => {
    const html = renderToStaticMarkup(
      <SkillMatchOutcome
        response={response({
          mode: 'llm_reranked',
          clarification: '请补充希望评审的页面和目标用户。',
          diagnostics: ['provider_timeout'],
        })}
        submittedTask="帮我评审"
        onUseSkill={vi.fn()}
      />,
    )

    expect(html).toContain('还需要补充任务信息')
    expect(html).toContain('请补充希望评审的页面和目标用户。')
    expect(html).not.toContain('推荐结果')
    expect(html).not.toContain('0 个')
    expect(html).not.toContain('没有找到')
    expect(html).not.toContain('provider_timeout')
  })

  it('keeps the existing result presentation when matches are available', () => {
    const html = renderToStaticMarkup(
      <SkillMatchOutcome
        response={response({ items: [match(1)] })}
        submittedTask="评审商品详情页体验"
        onUseSkill={vi.fn()}
      />,
    )

    expect(html).toContain('推荐结果')
    expect(html).toContain('1 个')
    expect(html).toContain('Skill 1')
    expect(html).toContain('使用此 Skill')
  })

  it.each([
    ['lexical', ['embedding_unavailable'], '当前使用关键词匹配 · 语义能力已降级', true],
    ['hybrid', [], '关键词 + 向量语义', false],
    ['llm_reranked', [], 'LLM 语义重排', false],
    ['fallback', ['embedding_unavailable', 'llm_unavailable'], '当前使用关键词匹配 · 语义召回已降级', true],
    ['fallback', ['llm_unavailable'], 'LLM 重排已降级 · 已使用确定性匹配', true],
  ] as const)(
    'shows an accurate, quiet matching-mode label for %s mode',
    (mode, diagnostics, label, degraded) => {
      const matchResponse = response({ mode, diagnostics: [...diagnostics], items: [match(1)] })
      const html = renderToStaticMarkup(
        <SkillMatchOutcome
          response={matchResponse}
          submittedTask="评审商品详情页体验"
          onUseSkill={vi.fn()}
        />,
      )

      expect(skillMatchModePresentation(matchResponse)).toEqual({ label, degraded })
      expect(html).toContain(`匹配方式：${label}`)
      expect(html.includes('role="status"')).toBe(degraded)
    },
  )

  it('keeps the existing no-match guidance when clarification is absent', () => {
    const html = renderToStaticMarkup(
      <SkillMatchOutcome
        response={response({ mode: 'fallback', diagnostics: ['lexical_no_match'] })}
        submittedTask="未知任务"
        onUseSkill={vi.fn()}
      />,
    )

    expect(html).toContain('推荐结果')
    expect(html).toContain('0 个')
    expect(html).toContain('没有找到当前可调用的 Skill')
    expect(html).not.toContain('lexical_no_match')
    expect(html).toContain('匹配方式：LLM 重排已降级 · 已使用确定性匹配')
  })
})
