import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { ResearchRunProjection } from '../../features/workspace/types'
import { ResearchExecution } from './ResearchExecution'

function projection(): ResearchRunProjection {
  return {
    run_id: 'run-research-execute',
    orchestration_version: 'research-v2',
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

function render(value: ResearchRunProjection, executionEnabled = true): string {
  return renderToStaticMarkup(
    <ResearchExecution
      projection={value}
      pendingAction={null}
      executionEnabled={executionEnabled}
      onConfirmPlan={() => undefined}
      onExecute={() => undefined}
      onResolveTool={() => undefined}
      onRecover={() => undefined}
      onCancel={() => undefined}
    />,
  )
}

describe('ResearchExecution', () => {
  it('keeps Plan Confirmation separate from Tool Approval and Provider execution', () => {
    const html = render(projection())

    expect(html).toContain('确认研究计划')
    expect(html).toContain('不会批准工具调用，也不会访问 Provider')
    expect(html).toContain('确认此计划')
    expect(html).not.toContain('独立 Tool Approval')
  })

  it('shows a call-scoped Tool Approval before any Provider execution', () => {
    const value = projection()
    value.workflow = {
      ...value.workflow,
      phase: 'execution',
      active_gate: 'tool_approval',
      state_version: 4,
      active_attempt_id: 'attempt-1',
    }
    value.attempt = {
      attempt_id: 'attempt-1',
      attempt_number: 1,
      status: 'pending',
      steps: [
        { step_number: 1, status: 'ready', attempt_count: 0 },
        { step_number: 2, status: 'pending', attempt_count: 0 },
      ],
    }
    value.tool_approval = {
      inbox_item_id: 'inbox-1',
      call_id: 'research-tool:attempt-1:1',
      tool_name: 'web_research',
    }

    const html = render(value)

    expect(html).toContain('独立 Tool Approval')
    expect(html).toContain('Provider 尚未被调用')
    expect(html).toContain('批准工具调用')
    expect(html).toContain('拒绝并终止')
    expect(html).toContain('检索并封存外部证据')
  })

  it('keeps a confirmed preview read-only when execution is disabled', () => {
    const value = projection()
    value.workflow = { ...value.workflow, active_gate: 'none', state_version: 3 }

    const html = render(value, false)

    expect(html).toContain('当前为预览或关闭模式')
    expect(html).not.toContain('开始执行研究</button>')
  })

  it('discloses UNKNOWN without silently retrying and offers only retry or abort', () => {
    const value = projection()
    value.workflow = {
      ...value.workflow,
      phase: 'execution',
      active_gate: 'recovery_decision',
      state_version: 7,
      active_attempt_id: 'attempt-1',
    }
    value.recovery = {
      invocation_id: 'invocation-1',
      state: 'unknown',
      send_count: 1,
      error_code: 'tool_result_unknown',
    }

    const html = render(value)

    expect(html).toContain('外部结果未知')
    expect(html).toContain('系统没有自动重试')
    expect(html).toContain('确认后再次发送')
    expect(html).toContain('安全终止')
  })

  it('hides a Report after integrity failure while preserving verified artifacts and details', () => {
    const value = projection()
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
})
