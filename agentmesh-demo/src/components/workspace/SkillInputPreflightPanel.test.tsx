import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import type { SkillInputRequestResponse, SkillPlan } from '../../features/workspace/types'
import { SkillInputPreflightPanel } from './SkillInputPreflightPanel'

const response: SkillInputRequestResponse = {
  item: {
    id: 'input_request_1',
    run_id: 'run_1',
    plan_id: null,
    version: 2,
    schema_version: 'skill-input-request-v1',
    status: 'open',
    contract_snapshots: [{
      node_id: 'direct',
      skill_id: 'skill_metrics',
      skill_name: 'build-experience-metrics',
      skill_version: '1',
      skill_content_hash: 'a'.repeat(64),
      contract_hash: 'b'.repeat(64),
    }],
    fields: [
      {
        id: 'direct.product_goal',
        node_id: 'direct',
        skill_id: 'skill_metrics',
        skill_name: 'build-experience-metrics',
        field_id: 'product_goal',
        title: '产品与业务目标',
        description: '说明核心目标',
        required: true,
        value_kind: 'text',
        multiple: false,
        text_value: '提高激活率',
        status: 'satisfied',
      },
      {
        id: 'direct.baseline_metrics',
        node_id: 'direct',
        skill_id: 'skill_metrics',
        skill_name: 'build-experience-metrics',
        field_id: 'baseline_metrics',
        title: '历史指标数据',
        description: '上传 CSV',
        required: false,
        value_kind: 'artifact',
        multiple: true,
        accepted_media_types: ['text/csv'],
        required_columns: ['date', 'value'],
        status: 'missing',
      },
    ],
    missing_required_field_ids: [],
    next_run_status: 'running',
    created_at: '2026-09-09T00:00:00Z',
    updated_at: '2026-09-09T00:00:00Z',
    expires_at: '2026-09-10T00:00:00Z',
  },
  artifacts: [{
    id: 'input_artifact_1',
    run_id: 'run_1',
    field_id: 'direct.baseline_metrics',
    file_name: 'baseline.csv',
    media_type: 'text/csv',
    byte_size: 24,
    content_hash: 'c'.repeat(64),
    status: 'ready',
    summary: { columns: ['date', 'value'], row_count: 1, column_count: 2 },
    error_code: null,
    created_at: '2026-09-09T00:00:00Z',
    updated_at: '2026-09-09T00:00:00Z',
  }],
}

describe('SkillInputPreflightPanel', () => {
  it('renders required fields and keeps optional material collapsed', () => {
    const html = renderToStaticMarkup(
      <SkillInputPreflightPanel
        response={response}
        pendingAction={null}
        error={null}
        onUpload={vi.fn()}
        onRemove={vi.fn()}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(html).toContain('执行前需要补充资料')
    expect(html).toContain('产品与业务目标')
    expect(html).toContain('可选资料（不影响继续）')
    expect(html).toContain('baseline.csv')
    expect(html).toContain('必需列：date、value')
    expect(html).toContain('资料齐全，继续')
  })

  it('shows the frozen plan in the same final confirmation', () => {
    const plan = {
      id: 'plan_1',
      run_id: 'run_1',
      version: 3,
      status: 'waiting_approval',
      intent: {
        goal: '建立体验指标',
        primary_stage: 'post_design',
        complexity: 'direct',
        external_evidence_required: false,
      },
      candidate_skill_ids: ['skill_metrics'],
      output_contract: ['experience_metrics'],
      nodes: [{
        id: 'node_metrics',
        skill_id: 'skill_metrics',
        skill_version: '1',
        reason: '建立北极星和护栏指标',
        required: true,
        depends_on: [],
        input_bindings: [],
        output_contract: ['experience_metrics'],
        side_effect: 'draft',
        status: 'pending',
        attempt: 0,
      }],
      planning_mode: 'standard',
      report_revision_count: 0,
      finalization_stage: 'none',
      finalization_version: 0,
      created_at: '2026-09-09T00:00:00Z',
      updated_at: '2026-09-09T00:00:00Z',
    } as SkillPlan
    const html = renderToStaticMarkup(
      <SkillInputPreflightPanel
        response={response}
        plan={plan}
        skills={[]}
        pendingAction={null}
        error={null}
        onUpload={vi.fn()}
        onRemove={vi.fn()}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(html).toContain('确认计划并补充资料')
    expect(html).toContain('本次执行计划 · v3')
    expect(html).toContain('建立北极星和护栏指标')
    expect(html).toContain('确认资料与计划，继续')
  })

  it('shows stable validation errors without exposing contract bodies', () => {
    const invalid = structuredClone(response)
    invalid.item.fields[0].status = 'invalid'
    invalid.item.fields[0].error_codes = ['input_text_too_short']
    invalid.item.missing_required_field_ids = ['direct.product_goal']

    const html = renderToStaticMarkup(
      <SkillInputPreflightPanel
        response={invalid}
        pendingAction={null}
        error="版本冲突"
        onUpload={vi.fn()}
        onRemove={vi.fn()}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(html).toContain('版本冲突')
    expect(html).toContain('填写内容过短')
    expect(html).toContain('仍有 1 项必填资料需要补充')
    expect(html).not.toContain('schema_version')
  })
})
