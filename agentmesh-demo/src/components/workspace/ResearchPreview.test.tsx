import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { ResearchRunProjection } from '../../features/workspace/types'
import { ResearchPreview } from './ResearchPreview'

function projection(): ResearchRunProjection {
  return {
    run_id: 'run-research-1',
    orchestration_version: 'research-v2',
    workflow: {
      phase: 'planning',
      active_gate: 'plan_confirmation',
      state_version: 2,
      active_requirement_version_id: 'requirement-1',
      active_plan_version_id: 'plan-1',
    },
    requirement: {
      requirement_version_id: 'requirement-1',
      version: 1,
      research_goal: '比较 Figma 和 Miro 的多人协作体验',
      competitor_scope: 'Figma 和 Miro',
      blocking: false,
      clarification_questions: [],
    },
    plans: [{
      plan_version_id: 'plan-1',
      version: 1,
      recommended: true,
      plan_hash: 'a'.repeat(64),
      steps: [
        {
          step_number: 1,
          name: 'Research external evidence',
          actor_type: 'tool',
          actor_id: 'tool_web_research',
          required: true,
        },
        {
          step_number: 2,
          name: 'Build competitive analysis',
          actor_type: 'skill',
          actor_id: 'skill_competitive',
          required: true,
        },
      ],
    }],
    attempt: null,
    gaps: [],
    artifacts: {},
    provenance: {},
    recovery: null,
  }
}

describe('ResearchPreview', () => {
  it('shows the requirement and one recommended Tool-to-Skill plan without implying execution', () => {
    const html = renderToStaticMarkup(<ResearchPreview projection={projection()} />)

    expect(html).toContain('竞品研究预览')
    expect(html).toContain('比较 Figma 和 Miro 的多人协作体验')
    expect(html).toContain('Figma 和 Miro')
    expect(html).toContain('状态版本 2')
    expect(html).toContain('Tool → Skill')
    expect(html).toContain('web_research')
    expect(html).toContain('$competitive-analysis')
    expect(html).toContain('尚未执行任何工具或 Skill')
    expect(html).not.toContain('a'.repeat(64))
  })

  it('shows at most the blocking clarification questions and no invented plan', () => {
    const blocked = projection()
    blocked.workflow = {
      ...blocked.workflow,
      phase: 'requirement',
      active_gate: 'clarification',
      active_plan_version_id: null,
      state_version: 1,
    }
    blocked.requirement = {
      ...blocked.requirement!,
      blocking: true,
      competitor_scope: null,
      clarification_questions: [
        { question_id: 'q1', prompt: '需要比较哪些产品？' },
        { question_id: 'q2', prompt: '重点关注哪些场景？' },
        { question_id: 'q3', prompt: '报告服务于什么决策？' },
        { question_id: 'q4', prompt: '这条不应出现' },
      ],
    }
    blocked.plans = []

    const html = renderToStaticMarkup(<ResearchPreview projection={blocked} />)

    expect(html).toContain('开始前需要澄清')
    expect(html).toContain('需要比较哪些产品？')
    expect(html).toContain('报告服务于什么决策？')
    expect(html).not.toContain('这条不应出现')
    expect(html).not.toContain('推荐执行计划')
  })

  it('does not claim that a plan is still being generated after fail-closed termination', () => {
    const failed = projection()
    failed.workflow = {
      ...failed.workflow,
      phase: 'terminal',
      active_gate: 'none',
      active_plan_version_id: null,
      state_version: 3,
    }
    failed.plans = []

    const html = renderToStaticMarkup(<ResearchPreview projection={failed} />)

    expect(html).toContain('研究已结束')
    expect(html).not.toContain('正在生成推荐研究计划')
  })
})
