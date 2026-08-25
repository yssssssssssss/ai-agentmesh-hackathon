import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { Modal } from './Modal'

describe('Modal', () => {
  it('keeps the dialog inside short viewports and makes its body scrollable', () => {
    const html = renderToStaticMarkup(
      <Modal open onClose={vi.fn()} title="Skill 推荐" subtitle="描述任务">
        <div>内容</div>
      </Modal>,
    )

    expect(html).toContain('max-h-[calc(100dvh-1rem)]')
    expect(html).toContain('flex shrink-0 items-start')
    expect(html).toContain('min-h-0 overscroll-contain overflow-x-hidden overflow-y-auto')
  })
})
