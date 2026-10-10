import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { MarketActivityItem } from '../types'
import { ActivityFeed } from './ActivityFeed'

describe('ActivityFeed', () => {
  it('labels unavailable and insufficient exchanges without claiming completion', () => {
    const statuses: MarketActivityItem['status'][] = ['blocked', 'insufficient_evidence']
    const items: MarketActivityItem[] = statuses.map((status, index) => ({
      id: `match-${index}`, at: '2026-10-06T00:00:00Z', kind: 'match',
      status, text: '尚无可交付答复', actor_name: '同事',
      counterpart_name: '本人', topic: '项目问题', involves_me: true,
    }))
    const html = renderToStaticMarkup(<ActivityFeed items={items} live={false} />)
    expect(html).toContain('暂不可用')
    expect(html).toContain('资料不足')
    expect(html).not.toContain('完成代答')
  })
})
