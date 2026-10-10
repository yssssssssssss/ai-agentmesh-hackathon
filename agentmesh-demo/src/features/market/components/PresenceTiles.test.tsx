import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { PresenceTiles } from './PresenceTiles'

describe('PresenceTiles', () => {
  it('reports an absent signal without inferring opt-out or absent material', () => {
    const html = renderToStaticMarkup(<PresenceTiles enabled presence={{
      memory_count: 6, signal_on: false, signal_refreshed_at: null, received_count: 0, given_count: 0,
    }} />)
    expect(html).toContain('当前没有已发布的协作摘要')
    expect(html).not.toContain('未参与市场或无素材')
  })
})
