import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { ToolLauncherBar } from './ToolLauncherBar'

describe('ToolLauncherBar', () => {
  it('exposes the Skill recommendation entry as a 40px keyboard-focusable control', () => {
    const html = renderToStaticMarkup(
      <ToolLauncherBar activeTool={null} skillRecommendationsEnabled onOpen={vi.fn()} />,
    )

    expect(html).toContain('aria-label="Skill 推荐"')
    expect(html).toContain('h-10')
    expect(html).toContain('focus-visible:ring-2')
    expect(html).not.toContain('transition-all')
  })

  it('does not offer a Skill command that the legacy runtime cannot execute', () => {
    const html = renderToStaticMarkup(
      <ToolLauncherBar activeTool={null} skillRecommendationsEnabled={false} onOpen={vi.fn()} />,
    )

    expect(html).not.toContain('Skill 推荐')
    expect(html).toContain('美学量化')
  })
})
