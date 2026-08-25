import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { ResearchRunProjection } from '../../features/workspace/types'
import { ResearchExecution } from './ResearchExecution'

function projection(): ResearchRunProjection {
  return {
    run_id: 'run-research-execute',
    orchestration_version: 'research-v2',
    status: 'waiting_plan_approval',
    error_code: null,
    workflow: {
      phase: 'planning',
      active_gate: 'plan_confirmation',
      state_version: 2,
      active_requirement_version_id: 'requirement-1',
      active_plan_version_id: 'plan-1',
      active_attempt_id: null,
    },
    requirement: null,
    plans: [{
      plan_version_id: 'plan-1',
      version: 1,
      recommended: true,
      plan_hash: 'a'.repeat(64),
      steps: [],
    }],
    attempt: null,
    gaps: [],
    artifacts: {},
    result: {
      evidence: [],
      claims: [],
    },
    provenance: {
      requested_model: 'gpt-primary',
      tool_implementation_id: 'ToolGateway.web_research',
      tool_execution_mode: 'real',
    },
    tool_approval: null,
    recovery: null,
    integrity_errors: [],
  }
}

function render(value: ResearchRunProjection): string {
  return renderToStaticMarkup(<ResearchExecution projection={value} />)
}

describe('ResearchExecution', () => {
  it('renders every historical gate without mutation controls', () => {
    const value = projection()
    value.attempt = {
      attempt_id: 'attempt-1',
      attempt_number: 1,
      status: 'running',
      steps: [
        { step_number: 1, status: 'running', attempt_count: 1 },
        { step_number: 2, status: 'pending', attempt_count: 0 },
      ],
    }
    const gates = ['plan_confirmation', 'none', 'tool_approval', 'recovery_decision'] as const
    const mutationLabels = [
      '确认此计划',
      '开始执行研究',
      '批准工具调用',
      '拒绝并终止',
      '确认后再次发送',
      '安全终止',
      '取消运行',
    ]

    for (const activeGate of gates) {
      value.workflow = {
        ...value.workflow,
        phase: activeGate === 'plan_confirmation' || activeGate === 'none' ? 'planning' : 'execution',
        active_gate: activeGate,
        active_attempt_id: 'attempt-1',
      }
      const html = render(value)

      expect(html).toContain('只读历史记录')
      expect(html).toContain('执行进度')
      expect(html).toContain('检索并封存外部证据')
      expect(html).not.toContain('<button')
      for (const label of mutationLabels) expect(html).not.toContain(label)
    }
  })

  it('hides a Report after integrity failure while preserving verified artifacts and details', () => {
    const value = projection()
    value.status = 'failed'
    value.error_code = 'artifact_integrity_failed'
    value.workflow = {
      ...value.workflow,
      phase: 'terminal',
      active_gate: 'none',
      state_version: 9,
      active_attempt_id: 'attempt-1',
    }
    value.attempt = {
      attempt_id: 'attempt-1',
      attempt_number: 1,
      status: 'completed',
      steps: [
        { step_number: 1, status: 'completed', attempt_count: 1, result_artifact_id: 'tool-output-1' },
        { step_number: 2, status: 'completed', attempt_count: 1, result_artifact_id: 'skill-output-1' },
      ],
    }
    value.artifacts = {
      evidence_manifest_id: 'manifest-safe',
      claim_ledger_id: 'claims-safe',
      deliverable_id: 'deliverable-safe',
      review_id: 'review-safe',
      report_id: 'report-corrupt',
    }
    value.integrity_errors = ['evidence_manifest:artifact_integrity_failed']

    const html = render(value)

    expect(html).toContain('结果完整性校验未通过')
    expect(html).toContain('最终 Report 已隐藏')
    expect(html).toContain('原始 Artifact 与审计标识')
    expect(html).toContain('manifest-safe')
    expect(html).not.toContain('report-corrupt')
  })

  it('renders readable verified results and links each factual Claim to its Evidence excerpt', () => {
    const value = projection()
    value.status = 'completed'
    value.workflow = {
      ...value.workflow,
      phase: 'terminal',
      active_gate: 'none',
      state_version: 9,
      active_attempt_id: 'attempt-1',
    }
    value.result = {
      evidence: [{
        evidence_id: 'evidence_1',
        quote: 'Source excerpt with traceable evidence.',
        conflict_status: 'none',
        risk_flags: [],
        sources: [{
          source_id: 'source-1',
          title: 'Primary source',
          url: 'https://example.com/source',
          retrieved_at: '2026-08-20T00:00:00Z',
        }],
      }],
      claims: [{
        claim_id: 'claim_fact_1',
        claim_type: 'fact',
        statement: 'A factual comparison.',
        evidence_ids: ['evidence_1'],
        parent_claim_ids: [],
        confidence: 'high',
        conflict_status: 'none',
      }],
      deliverable: {
        summary: 'Structured deliverable summary.',
        summary_claim_ids: ['claim_fact_1'],
        comparison: [],
        recommendations: [],
        limitations: ['Limited public data.'],
      },
      review: {
        status: 'pass',
        checks: [{ code: 'claim_coverage', passed: true }],
      },
      report: {
        title: 'Verified competitive report',
        markdown: [
          '# Verified competitive report',
          '',
          '## Summary',
          '',
          '**Readable report** with [primary evidence](https://example.com/evidence).',
          '',
          '- Evidence is traceable',
          '- Raw HTML stays inert',
          '',
          '| Product | Score |',
          '| --- | ---: |',
          '| AgentMesh | 9 |',
          '',
          '<script>alert(1)</script>',
        ].join('\n'),
      },
    }

    const html = render(value)

    expect(html).toContain('Verified competitive report')
    expect(html.match(/Verified competitive report/g)).toHaveLength(1)
    expect(html).toContain('<h2')
    expect(html).toContain('>Summary</h2>')
    expect(html).toContain('<strong>Readable report</strong>')
    expect(html).toContain('<ul>')
    expect(html).toContain('<table>')
    expect(html).toContain('href="https://example.com/evidence"')
    expect(html).toContain('Structured deliverable summary')
    expect(html).toContain('A factual comparison.')
    expect(html).toContain('Source excerpt with traceable evidence.')
    expect(html).toContain('href="#research-evidence-evidence_1"')
    expect(html).toContain('href="https://example.com/source"')
    expect(html).toContain('确定性 Review · 通过')
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
    expect(html).not.toContain('<script>alert(1)</script>')
  })

  it('labels a blocked deliverable as an unapproved research draft', () => {
    const value = projection()
    value.status = 'failed'
    value.error_code = 'deterministic_review_blocked'
    value.workflow = {
      ...value.workflow,
      phase: 'terminal',
      active_gate: 'none',
      state_version: 9,
      active_attempt_id: 'attempt-1',
    }
    value.result = {
      evidence: [],
      claims: [],
      deliverable: {
        summary: 'Draft findings that need more evidence.',
        summary_claim_ids: [],
        comparison: [],
        recommendations: [],
        limitations: ['Missing first-party evidence.'],
      },
      review: {
        status: 'block',
        checks: [
          { code: 'evidence_policy', passed: false },
          { code: 'schema_valid', passed: true },
        ],
      },
    }

    const html = render(value)

    expect(html).toContain('未通过审核的研究草稿')
    expect(html).toContain('不能作为已审核通过的最终报告')
    expect(html).toContain('evidence_policy')
    expect(html).toContain('Draft findings that need more evidence.')
    expect(html).not.toContain('确定性 Review · 通过')
  })

  it('does not present a failed empty run as a successful empty Report', () => {
    const value = projection()
    value.status = 'failed'
    value.error_code = 'tool_runtime_not_real'
    value.workflow = {
      ...value.workflow,
      phase: 'terminal',
      active_gate: 'none',
      active_plan_version_id: null,
      state_version: 3,
    }
    value.plans = []

    const html = render(value)

    expect(html).not.toContain('本次运行未生成可展示的最终 Report')
  })

  it('keeps the empty Report message for a completed run', () => {
    const value = projection()
    value.status = 'completed'
    value.workflow = {
      ...value.workflow,
      phase: 'terminal',
      active_gate: 'none',
      state_version: 3,
    }

    expect(render(value)).toContain('本次运行未生成可展示的最终 Report')
  })
})
