import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { buildFactQuery, factQueryError, queryFacts, type FactQueryResult } from '../../features/knowledge/factsApi'
import { ProjectFactResults } from './ProjectFactQueryPanel'

const empty: FactQueryResult = { schema_version: 'fact-query-result-v1', project_id: 'selected-project',
  snapshot_at: '2026-10-07T00:00:00Z', outcome: 'unknown', automatic_context_eligible: false, facts: [] }

afterEach(() => vi.unstubAllGlobals())

describe('project fact queries', () => {
  it('queries the selected project with historical validity and observation cutoffs', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(empty), {
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetch)
    const request = buildFactQuery('selected-project', { subjectType: 'term', subject: ' 登录网关 ',
      predicate: 'owner', timeMode: 'interval', at: '2026-10-01T08:00:00+08:00',
      until: '2026-10-02T08:00:00+08:00', observedBefore: '2026-10-03T08:00:00+08:00' })
    await queryFacts(request)
    expect(fetch.mock.calls[0][0]).toBe('/api/memory/facts/query')
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ project_id: 'selected-project', subject_type: 'term',
      subject_id: '登录网关', predicate: 'owner', interval_from: '2026-10-01T00:00:00.000Z',
      interval_to: '2026-10-02T00:00:00.000Z', observed_before: '2026-10-03T00:00:00.000Z' })
    expect(() => buildFactQuery('selected-project', { subjectType: 'project', subject: '', predicate: 'decision',
      timeMode: 'interval', at: '2026-10-02T00:00:00Z', until: '2026-10-01T00:00:00Z', observedBefore: '' }))
      .toThrow('结束时间必须晚于开始时间')
  })

  it('shows conflicting versions with authorized source links and escaped fact text', () => {
    const fact = { subject_type: 'project' as const, subject_id: 'selected-project', predicate: 'owner',
      value: 'Alice', valid_from: '2026-10-01T00:00:00Z', time_precision: 'instant' as const,
      schema_version: 'memory-fact-v1' as const, observed_at: '2026-10-02T00:00:00Z',
      source_classification: 'human_confirmed' as const, evidence_refs: [{ record_type: 'document' as const,
        record_id: 'source with space', version: 2, content_hash: 'a'.repeat(64) }] }
    const hit = { memory_id: 'memory-1', memory_record_type: 'user_memory_item' as const, memory_version: 3,
      memory_hash: 'b'.repeat(64), scope: 'private', status: 'active', fact }
    const result: FactQueryResult = { ...empty, outcome: 'conflict', facts: [hit,
      { ...hit, memory_id: 'memory-2', fact: { ...fact, value: '<script>Bob</script>' } }],
      conflicts: [{ group_id: 'owner-conflict', fact_indexes: [0, 1] }] }
    const html = renderToStaticMarkup(<ProjectFactResults result={result} />)
    expect(html).toContain('发现冲突，需要核对')
    expect(html).toContain('冲突记录')
    expect(html).toContain('document=source+with+space')
    expect(html).toContain('memory=memory-1')
    expect(html).toContain('查询时 v3')
    expect(html).toContain('&lt;script&gt;Bob&lt;/script&gt;')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('找到有来源的事实')
  })

  it('distinguishes missing facts from revoked evidence and hides raw failure details', () => {
    const unknown = renderToStaticMarkup(<ProjectFactResults result={empty} />)
    expect(unknown).toContain('未找到记录不代表事实不存在')
    const insufficient = renderToStaticMarkup(<ProjectFactResults result={{ ...empty, outcome: 'insufficient_evidence',
      missing_data: ['fact_evidence_unavailable'] }} />)
    expect(insufficient).toContain('证据不足')
    expect(insufficient).toContain('来源已经更新、撤回或不可访问')
    expect(factQueryError(new ApiError(404, 'private internal detail', null))).toContain('访问权限')
    expect(factQueryError(new Error('private internal detail'))).not.toContain('private internal detail')
  })
})
