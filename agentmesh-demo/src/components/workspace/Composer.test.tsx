import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { Composer } from './Composer'

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
