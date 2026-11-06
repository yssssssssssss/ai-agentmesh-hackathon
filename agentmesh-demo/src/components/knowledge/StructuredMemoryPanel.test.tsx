import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { MemoryItem } from '../../features/knowledge/api'
import { procedureTaskDraft, taskDraftFromLocation } from '../../features/tasks/procedureReuse'
import { StructuredMemoryPanel } from './StructuredMemoryPanel'

describe('StructuredMemoryPanel', () => {
  it('carries a confirmed method goal into a project task draft without placing its body in the URL', () => {
    const procedure: NonNullable<MemoryItem['procedure']> = {
      schema_version: 'procedure-memory-v1', goal_patterns: ['核对登录网关配置'], steps: ['检查配置并报告差异'],
      validation_conditions: ['已通过独立验收'], preconditions: ['project_member'],
      human_confirmed_by: 'reviewer', human_confirmed_at: '2026-10-07T00:00:00Z', successful_runs: [{ run_id: 'accepted-run',
        review_ref: { record_type: 'task_review', record_id: 'review', version: 1, content_hash: 'a'.repeat(64) },
        artifact_refs: [{ record_type: 'artifact', record_id: 'artifact', version: 1, content_hash: 'b'.repeat(64) }] }],
    }
    const draft = procedureTaskDraft('selected/project', procedure)
    expect(draft).toEqual({ projectId: 'selected/project', title: '核对登录网关配置', description: '核对登录网关配置' })
    expect(taskDraftFromLocation({ taskDraft: draft }, 'different-project')).toBeNull()
    const html = renderToStaticMarkup(<MemoryRouter><StructuredMemoryPanel memory={{ procedure }}
      projectId="selected/project" canReuse /></MemoryRouter>)
    expect(html).toContain('href="/tasks?project=selected%2Fproject"')
    expect(html).toContain('根据方法创建任务')
    expect(html).toContain('保存和启动执行需要确认')
    expect(procedureTaskDraft('selected/project', { ...procedure, successful_runs: [] })).toBeNull()
  })

  it('renders nothing for a legacy memory', () => {
    expect(renderToStaticMarkup(<StructuredMemoryPanel memory={{}} />)).toBe('')
  })

  it('shows valid time separately from observation and preserves source classification', () => {
    const facts: NonNullable<MemoryItem['facts']> = [{
      schema_version: 'memory-fact-v1', subject_type: 'project', subject_id: 'project-1',
      predicate: 'owner', value: 'Alice <script>', valid_from: '2026-09-01T00:00:00Z',
      valid_to: '2026-10-01T00:00:00Z', time_precision: 'day', observed_at: '2026-10-04T01:00:00Z',
      source_classification: 'model_inference', evidence_refs: [{
        record_type: 'document', record_id: 'document-1', version: 3, content_hash: 'a'.repeat(64),
      }],
    }]
    const html = renderToStaticMarkup(<StructuredMemoryPanel memory={{ facts }} />)
    expect(html).toContain('有效时间')
    expect(html).toContain('记录时间')
    expect(html).toContain('不含结束时刻')
    expect(html).toContain('模型推断，待确认')
    expect(html).toContain('document-1')
    expect(html).toContain('v3')
    expect(html).toContain('Alice &lt;script&gt;')
    expect(html).not.toContain('已验证事实')
  })

  it('presents unknown time and unconfirmed procedures without an invented verification status', () => {
    const procedure: NonNullable<MemoryItem['procedure']> = {
      schema_version: 'procedure-memory-v1', goal_patterns: ['提交已审核产物'], preconditions: ['项目成员'],
      tool_versions: { artifact_store: 'v1' }, environment_versions: {}, steps: ['封存产物', '发起审核'],
      validation_conditions: ['独立审核通过'], successful_runs: [], failed_runs: ['failed-run'],
    }
    const html = renderToStaticMarkup(<StructuredMemoryPanel memory={{ procedure }} />)
    expect(html).toContain('待确认经验')
    expect(html).toContain('项目成员')
    expect(html).toContain('封存产物')
    expect(html).toContain('独立审核通过')
    expect(html).toContain('artifact_store')
    expect(html).toContain('failed-run')
    expect(html).not.toContain('已记录验收引用')
  })
})
