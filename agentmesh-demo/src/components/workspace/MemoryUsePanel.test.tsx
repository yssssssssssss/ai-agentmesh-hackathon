import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { MemoryUseView } from '../../features/workspace/types'
import { MemoryUsePanel } from './MemoryUsePanel'

const use: MemoryUseView = {
  receipt: {
    schema_version: 'memory-use-receipt-v1',
    id: 'memory-use-1',
    run_id: 'run-1',
    task_id: 'task-1',
    memory_id: 'memory-1',
    memory_kind: 'team',
    memory_layer: 'long_term',
    memory_record_type: 'memory_item',
    memory_version: 2,
    memory_hash: 'a'.repeat(64),
    retrieval_reason: 'automatic_run_context',
    retrieval_query_hash: 'b'.repeat(64),
    citation_label: 'T1',
    agent_id: 'agent-1',
    source_ids: ['source-1'],
    created_at: '2026-09-03T00:00:00Z',
  },
  title: '团队审核经验',
  scope: 'team_accepted',
  layer: 'long_term',
  sources: [{
    id: 'source-1',
    title: '原始交付证据',
    source_type: 'task_artifact',
    reference: 'artifact://source-1',
    created_at: '2026-09-03T00:00:00Z',
  }],
  cited_in_output: true,
  memory_navigation_href: '/knowledge?project=project-1&memory=memory-1',
  task_navigation_href: '/tasks?task=task-1',
}

describe('MemoryUsePanel', () => {
  it('renders only durable Run Memory-use facts and source citations', () => {
    const html = renderToStaticMarkup(<MemoryUsePanel items={[use]} />)

    expect(html).toContain('本次使用的记忆')
    expect(html).toContain('[T1]')
    expect(html).toContain('团队审核经验')
    expect(html).toContain('v2')
    expect(html).toContain('输出已引用')
    expect(html).toContain('原始来源：原始交付证据')
    expect(html).toContain('/knowledge?project=project-1&amp;memory=memory-1')
  })

  it('does not add an empty decorative section', () => {
    expect(renderToStaticMarkup(<MemoryUsePanel items={[]} />)).toBe('')
  })
})
