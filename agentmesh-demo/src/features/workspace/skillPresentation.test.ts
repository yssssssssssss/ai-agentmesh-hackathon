import { describe, expect, it } from 'vitest'

import type { Skill } from './types'
import {
  groupSkillsByDesignStage,
  isCallableSkill,
  missingToolsSummary,
  skillAvailabilityLabel,
} from './skillPresentation'

function skill(overrides: Partial<Skill>): Skill {
  return {
    id: '$skill',
    command: '$skill',
    title: 'Skill',
    description: 'Skill description',
    usage: '$skill <input>',
    placeholder: 'Input',
    aliases: [],
    requires_input: true,
    source: 'builtin',
    version: '1',
    activation_policy: 'explicit_only',
    enabled: true,
    binding_enabled: true,
    planner_eligible: false,
    readiness: 'ready',
    execution_readiness: 'complete',
    missing_tools: [],
    input_kinds: [],
    output_kinds: [],
    ...overrides,
  }
}

describe('Skill presentation', () => {
  it('groups a ready profileless Skill as other instead of a tool', () => {
    const profileless = skill({ command: '$profileless', title: 'Profileless' })
    const tool = skill({ command: '$memory.search', title: 'Memory search' })

    const groups = groupSkillsByDesignStage([tool, profileless])

    expect(groups.map((group) => group.key)).toEqual(['other', 'tools'])
    expect(groups[0]?.items.map((item) => item.command)).toEqual(['$profileless'])
    expect(groups[1]?.items.map((item) => item.command)).toEqual(['$memory.search'])
  })

  it('distinguishes explicit invocation, automatic planning, tools, and unavailable Skills', () => {
    expect(skillAvailabilityLabel(skill({ planner_eligible: false }))).toBe('可显式调用')
    expect(skillAvailabilityLabel(skill({ planner_eligible: true }))).toBe('可自动编排')
    expect(skillAvailabilityLabel(skill({ command: '$memory.search' }))).toBe('可直接调用')
    expect(skillAvailabilityLabel(skill({ execution_readiness: 'tool_limited' }))).toBe('已接入 · 工具待接通')
    expect(skillAvailabilityLabel(skill({ readiness: 'unavailable' }))).toBe('未就绪')
    expect(isCallableSkill(skill({ execution_readiness: 'tool_limited' }))).toBe(true)
    expect(isCallableSkill(skill({ execution_readiness: 'unavailable' }))).toBe(false)
  })

  it('summarizes missing tools without hiding the total', () => {
    expect(missingToolsSummary(['Bash', 'Read', 'Write', 'Edit'])).toBe('Bash、Read、Write 等 4 项')
    expect(missingToolsSummary([])).toBe('')
  })
})
