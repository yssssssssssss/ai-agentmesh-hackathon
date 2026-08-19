import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { AgentSecondaryNav } from './AgentSecondaryNav'

describe('AgentSecondaryNav responsive layout', () => {
  it('uses horizontal mobile tabs and preserves the desktop sidebar', () => {
    const html = renderToStaticMarkup(
      <AgentSecondaryNav section="skills" onSelect={vi.fn()} />,
    )

    expect(html).toContain('aria-label="数字员工管理分区"')
    expect(html).toContain('overflow-x-auto')
    expect(html).toContain('md:w-[240px]')
    expect(html).toContain('md:flex-col')
    expect(html).toContain('能力与 Skill')
    expect(html).not.toContain('transition-all')
  })
})
