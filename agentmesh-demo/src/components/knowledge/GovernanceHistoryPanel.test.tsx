import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { MemoryGovernanceFilters } from '../../features/knowledge/api'
import type { KnowledgeAssetView } from '../../features/knowledge/presenter'
import { GovernanceHistoryPanel } from './GovernanceHistoryPanel'

const filters: MemoryGovernanceFilters = {
  page: 2,
  pageSize: 25,
  status: 'deprecated',
  scope: 'all',
  kind: 'all',
  layer: 'all',
}

function real<T>(value: T) {
  return { value, source: 'T' as const }
}

function deprecatedAsset(): KnowledgeAssetView {
  return {
    kind: 'accepted_memory',
    id: real('memory-deprecated'),
    title: real('已废弃团队知识'),
    conclusion: real('旧版本仍可审计。'),
    type: real('method'),
    scope: real('团队范围'),
    sourceProject: real('项目 A'),
    contributor: real('user-1'),
    verified: real('deprecated'),
    visibility: real('team'),
    citedBy: real(0),
    updated: real('2026-09-03T00:00:00Z'),
    hasNewFeedback: real(false),
    problem: real(''),
    evidence: real([]),
    limitation: real(''),
    citations: real([]),
    allowedActions: real(['archive']),
    version: real(3),
    status: real('deprecated'),
    memoryKind: real('team_knowledge'),
    supersedesMemoryId: real(null),
    contentHash: real('a'.repeat(64)),
    archivedFromStatus: real(null),
    sourceTaskId: real('task-1'),
    sourceRunId: real('run-1'),
    sourceReviewId: real('review-1'),
  }
}

describe('GovernanceHistoryPanel', () => {
  it('keeps filters and previous-page recovery visible for an empty page', () => {
    const html = renderToStaticMarkup(
      <GovernanceHistoryPanel
        items={[]}
        filters={filters}
        total={0}
        hasNext={false}
        onFiltersChange={vi.fn()}
        onPageChange={vi.fn()}
        onOpen={vi.fn()}
      />,
    )

    expect(html).toContain('生命周期状态')
    expect(html).toContain('当前筛选下没有治理历史')
    expect(html).toContain('当前第 2 页')
    expect(html).toContain('上一页')
    expect(html).toContain('下一页')
  })

  it('renders the server-filtered page without applying a second local filter', () => {
    const html = renderToStaticMarkup(
      <GovernanceHistoryPanel
        items={[deprecatedAsset()]}
        filters={{ ...filters, status: 'archived', page: 1 }}
        total={1}
        hasNext={false}
        onFiltersChange={vi.fn()}
        onPageChange={vi.fn()}
        onOpen={vi.fn()}
      />,
    )

    expect(html).toContain('已废弃团队知识')
    expect(html).toContain('已废弃')
  })
})
