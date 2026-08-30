import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { deepSearchApi } from './api'
import { DeepSearchReportView } from './DeepSearchEvidenceReport'
import { activeDeepSearchStage, deepSearchAvailabilityMessage } from './presentation'
import type { DeepSearchReport, DeepSearchState } from './types'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('DeepSearch API', () => {
  it('reads the aggregate and posts version-fenced clarification answers', async () => {
    const state = { run: { id: 'run/1' } }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(state), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(state), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    await deepSearchApi.state('run/1')
    await deepSearchApi.clarify('run/1', {
      client_turn_id: 'clarify-1',
      expected_requirement_version: 2,
      answers: { q_2_1_abcd1234: ['华东', '华南'] },
    })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/runs/run%2F1/deepsearch')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/agent/runs/run%2F1/deepsearch/clarify')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toEqual({
      client_turn_id: 'clarify-1',
      expected_requirement_version: 2,
      answers: { q_2_1_abcd1234: ['华东', '华南'] },
    })
  })
})

describe('DeepSearch presentation', () => {
  it('uses the persisted planning state instead of orchestration-version heuristics', () => {
    const state = {
      run: { status: 'waiting_clarification' },
      plan: null,
    } as DeepSearchState

    expect(activeDeepSearchStage(state)).toBe(1)
    expect(deepSearchAvailabilityMessage({
      available: false,
      enabled: true,
      runtime_mode: 'preview',
      core_ready: true,
      reason_code: 'execution_unavailable',
    })).toContain('执行模式')
  })

  it('renders only the sealed report projection with partial and review labels', () => {
    const report: DeepSearchReport = {
      schema_version: 'deepsearch-report-v1',
      run_id: 'run-1',
      requirement_version_id: 'req-1',
      plan_id: 'plan-1',
      plan_version: 1,
      review_outcome: 'block',
      review_reason_code: null,
      report_status: 'partial',
      title: '候选方案研究',
      claims: [],
      executive_summary_claim_ids: [],
      sections: [],
      sources: [{
        source_id: 'source-1',
        title: '公开资料',
        normalized_reference: 'https://example.com/source',
        content_hash: 'a'.repeat(64),
      }],
      limitations: [{
        code: 'deepsearch_review_not_passed',
        related_ids: [],
        description: '部分结论未通过审核。',
      }],
      rendered_text: '## 执行摘要\n\n仅保留了有证据支持的结论。',
    }

    const html = renderToStaticMarkup(<DeepSearchReportView report={report} reportRunId="run/report 1" />)

    expect(html).toContain('Sealed report')
    expect(html).toContain('部分报告')
    expect(html).toContain('仅保留了有证据支持的结论')
    expect(html).toContain('https://example.com/source')
    expect(html).toContain('/api/agent/runs/run%2Freport%201/report.html')
    expect(html).toContain('独立查看')
    expect(html).toContain('下载 HTML')
  })
})
