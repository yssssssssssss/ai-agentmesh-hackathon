import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { QueryView } from '../api/marketApi'
import { DelegatedQueryPanel } from './DelegatedQueryPanel'

function render(userId: string, items: QueryView[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['delegated-queries', userId, 'project'], { items })
  client.setQueryData(['delegated-consents', userId, 'project'], { items: [] })
  return renderToStaticMarkup(<QueryClientProvider client={client}>
    <DelegatedQueryPanel userId={userId} projectId="project" peers={[{ id: 'peer', name: '同事' }]} />
  </QueryClientProvider>)
}

const pending: QueryView = {
  id: 'query', project_id: 'project', requester_id: 'requester', target_id: 'target', question: '项目问题',
  version: 1, status: 'awaiting_confirm', created_at: '2026-10-06T00:00:00Z',
  confidence: 'none', current_available: false,
}

describe('owned delegated query controls', () => {
  it('offers confirmation only to the answering owner', () => {
    expect(render('target', [pending])).toContain('同意本次代答')
    expect(render('requester', [pending])).not.toContain('同意本次代答')
  })
  it('allows adoption only of a currently readable delivered artifact by the requester', () => {
    const answered: QueryView = { ...pending, status: 'answered', answer: '受限答复', current_available: true, artifact_hash: 'a'.repeat(64) }
    expect(render('requester', [answered])).toContain('采纳到我的私有知识')
    expect(render('target', [answered])).not.toContain('采纳到我的私有知识</button>')
    const withheld = render('requester', [{ ...answered, answer: null, current_available: false, artifact_hash: null }])
    expect(withheld).toContain('答案不可读取或采纳')
    expect(withheld).not.toContain('受限答复')
    expect(withheld).not.toContain('采纳到我的私有知识</button>')
  })
  it('never offers adoption for unavailable, insufficient, denied or interrupted requests', () => {
    const statuses: QueryView['status'][] = ['blocked', 'insufficient_evidence', 'denied', 'failed']
    const html = render('requester', statuses.map((status) => ({ ...pending, id: status, status })))
    expect(html).toContain('资料不足')
    expect(html).toContain('已中断')
    expect(html).not.toContain('已回答')
    expect(html).not.toContain('采纳到我的私有知识</button>')
  })
})
