import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { Skill } from '../../features/workspace/types'
import { groupSkillsByDesignStage } from '../../features/workspace/skillPresentation'
import { Composer, resolveActiveSkillSelection } from './Composer'

function skill(
  command: string,
  primaryStage: Skill['primary_stage'],
  readiness: Skill['readiness'] = 'ready',
  plannerEligible = true,
): Skill {
  return {
    id: command,
    command,
    title: command.slice(1),
    description: `${command} 的简短说明`,
    usage: `${command} <input>`,
    placeholder: '输入内容',
    aliases: [],
    requires_input: true,
    source: 'builtin',
    version: '1',
    activation_policy: 'explicit_only',
    enabled: true,
    binding_enabled: true,
    planner_eligible: plannerEligible,
    readiness,
    execution_readiness: readiness === 'unavailable' ? 'unavailable' : 'complete',
    missing_tools: [],
    primary_stage: primaryStage,
    capability_type: 'analysis',
    input_kinds: [],
    output_kinds: [],
    side_effect: 'read',
  }
}

describe('Composer send recovery', () => {
  it.each(['failed', 'unknown'] as const)('keeps a preserved draft editable after a %s send', (sendState) => {
    const html = renderToStaticMarkup(
      <Composer
        value="保留的草稿"
        skills={[]}
        sending={false}
        sendState={sendState}
        statusMessage="发送未完成"
        onChange={vi.fn()}
        onSend={vi.fn()}
        onRetry={vi.fn()}
        onUpload={vi.fn()}
      />,
    )
    const textarea = html.match(/<textarea\b[^>]*>/)?.[0]

    expect(textarea).toBeDefined()
    expect(textarea).not.toMatch(/\sdisabled(?:=|[\s>])/)
  })

  it('renders five categories before the active category Skill list', () => {
    const html = renderToStaticMarkup(
      <Composer
        value="$"
        skills={[
          skill('$measure', 'post_design'),
          skill('$memory.search', undefined, undefined),
          skill('$research', 'pre_design'),
          skill('$validate', 'during_design'),
          skill('$profileless', undefined, 'ready', false),
          skill('$unavailable', 'pre_design', 'unavailable'),
        ]}
        sending={false}
        sendState={null}
        statusMessage={null}
        onChange={vi.fn()}
        onSend={vi.fn()}
        onRetry={vi.fn()}
        onUpload={vi.fn()}
      />,
    )

    expect(html.indexOf('设计前')).toBeLessThan(html.indexOf('设计中'))
    expect(html.indexOf('设计中')).toBeLessThan(html.indexOf('设计后'))
    expect(html.indexOf('设计后')).toBeLessThan(html.indexOf('未分类 Skill'))
    expect(html.indexOf('未分类 Skill')).toBeLessThan(html.indexOf('工具'))
    expect(html).toContain('role="tablist"')
    expect(html).toContain('role="tabpanel"')
    expect(html).toContain('$research')
    expect(html).not.toContain('$validate')
    expect(html).not.toContain('$measure')
    expect(html).not.toContain('$memory.search')
    expect(html).not.toContain('$unavailable')
  })

  it('shows a ready profileless Skill under uncategorized Skills instead of tools', () => {
    const html = renderToStaticMarkup(
      <Composer
        value="$"
        skills={[
          skill('$memory.search', undefined),
          skill('$profileless', undefined, 'ready', false),
        ]}
        sending={false}
        sendState={null}
        statusMessage={null}
        onChange={vi.fn()}
        onSend={vi.fn()}
        onRetry={vi.fn()}
        onUpload={vi.fn()}
      />,
    )

    expect(html.indexOf('未分类 Skill')).toBeLessThan(html.indexOf('工具'))
    expect(html).toContain('$profileless')
    expect(html).not.toContain('$memory.search')
  })

  it('keeps keyboard selection inside the visible stage after a multi-stage query', () => {
    const groups = groupSkillsByDesignStage([
      skill('$research', 'pre_design'),
      skill('$review', 'post_design'),
    ])

    const selection = resolveActiveSkillSelection(groups, 'post_design', 0)

    expect(selection.group?.key).toBe('post_design')
    expect(selection.skill?.command).toBe('$review')
  })

  it('aligns the input surface with the workspace content column', () => {
    const html = renderToStaticMarkup(
      <Composer
        value=""
        skills={[]}
        sending={false}
        sendState={null}
        statusMessage={null}
        onChange={vi.fn()}
        onSend={vi.fn()}
        onRetry={vi.fn()}
        onUpload={vi.fn()}
      />,
    )

    expect(html).toContain('data-testid="workspace-composer"')
    expect(html).toContain('max-w-[992px]')
  })
})
