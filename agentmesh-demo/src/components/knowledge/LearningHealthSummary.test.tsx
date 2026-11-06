import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { LearningStatus } from '../../features/knowledge/learningApi'
import { LearningHealthSummary } from './LearningHealthSummary'

const status: LearningStatus = {
  mode: 'execute', learning_enabled: true, daily_reserved_tokens: 64000, cleanup_pending: 2,
  source_byte_limit: 12000, job_token_cap: 32000, daily_token_cap: 64000,
  queue: { ready: 3, running: 1, retry_wait: 2, expired_leases: 0, failures: 0, blocked: 0, unreported_attempts: 1 },
  alerts: ['budget_exhausted', 'cleanup_delayed', 'usage_unreported'],
}

describe('LearningHealthSummary', () => {
  it('shows owned counts and budget separately from reported usage', () => {
    const html = renderToStaticMarkup(<LearningHealthSummary status={status} />)
    expect(html).toContain('待处理 3')
    expect(html).toContain('今日预算预留 64000/64000 Token')
    expect(html).toContain('预算预留继续保留')
    expect(html).toContain('索引清理等待超过一分钟')
  })

  it('does not invent health for an older response', () => {
    expect(renderToStaticMarkup(<LearningHealthSummary status={{
      mode: 'off', learning_enabled: false, daily_reserved_tokens: 0, cleanup_pending: 0,
      source_byte_limit: 12000, job_token_cap: 32000, daily_token_cap: 64000,
    }} />)).toBe('')
  })
})
