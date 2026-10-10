import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { MemoryUseView } from '../../features/workspace/types'
import type { components } from '../../api/generated/schema'
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

  it('shows prepared and withheld candidates without inventing a delivery receipt', () => {
    const states = ['prepared', 'withheld', 'quarantined', 'budget_dropped', 'delivered'] as const
    const candidates: components['schemas']['MemoryContextCandidateViewV1'][] = states.map((state) => ({
      candidate: {memory_id: `opaque-${state}`, memory_record_type: 'user_memory_item', memory_version: 1,
        memory_hash: 'c'.repeat(64), decision: state === 'delivered' ? 'prepared' : state, reason: 'selected'},
      state, title: null, citation_label: null, current_available: false,
    }))
    const html = renderToStaticMarkup(<MemoryUsePanel items={[]} candidates={candidates} />)
    for (const label of ['待使用', '暂不可用', '安全隔离', '超出预算', '已使用']) expect(html).toContain(label)
    expect(html).toContain('尚未记录模型交付')
    expect(html).toContain('此版本曾交付')
    expect(html).not.toContain('本次使用的记忆')
    expect(html).not.toContain('已进入上下文')
  })

  it('explains a rejected complete request without claiming memory delivery', () => {
    const html = renderToStaticMarkup(<MemoryUsePanel items={[]} requests={[{
      model_id: 'enterprise', estimation_method: 'utf8_conservative', total_chars: 50000,
      estimated_input_tokens: 100000, output_token_cap: 8192, decision: 'withheld',
    }]} />)
    expect(html).toContain('请求预算超限，未交付')
    expect(html).toContain('并非 Provider 实测用量')
    expect(html).not.toContain('本次使用的记忆')
    expect(html).not.toContain('已进入上下文')
  })
})
