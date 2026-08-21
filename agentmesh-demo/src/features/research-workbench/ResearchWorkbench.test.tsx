import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import approvalFixture from '../../../../tests/fixtures/research_v3_workbench/approval.json'
import candidatesFixture from '../../../../tests/fixtures/research_v3_workbench/candidates.json'
import clarifyFixture from '../../../../tests/fixtures/research_v3_workbench/clarify.json'
import dagFixture from '../../../../tests/fixtures/research_v3_workbench/dag_or_executing.json'
import idleFixture from '../../../../tests/fixtures/research_v3_workbench/idle.json'
import pausedFixture from '../../../../tests/fixtures/research_v3_workbench/paused.json'
import planFixture from '../../../../tests/fixtures/research_v3_workbench/plan.json'
import textReportFixture from '../../../../tests/fixtures/research_v3_workbench/text_report.json'
import { adaptWorkbenchAggregate } from './adapter'
import { ResearchWorkbench } from './ResearchWorkbench'
import { ResearchWorkbenchFixtureGallery } from './ResearchWorkbenchFixtureGallery'
import type { ResearchV2HistoryWorkbenchAggregateV1 } from './types'

const FIXTURES = [
  ['idle', idleFixture, ['你想研究什么？', 'RESEARCH WORKBENCH']],
  ['clarify', clarifyFixture, ['澄清需求', 'Which competitors are in scope?']],
  ['candidates', candidatesFixture, ['待选执行方案', '深度优先', '速度优先']],
  ['plan', planFixture, ['待执行计划', 'Collect public evidence', '确认计划']],
  ['approval', approvalFixture, ['计划等待授权审批', 'public sources only', '待审批']],
  ['dag_or_executing', dagFixture, ['运行流程', '执行中', 'Analyze competitors']],
  ['paused', pausedFixture, ['执行已暂停', 'worker_loss', '重试失败执行']],
  ['text_report', textReportFixture, ['Alpha versus Beta', 'Executive Summary', 'Alpha documents the compared capability.']],
] as const

describe('research-workbench-aggregate-v1 fixture renderer', () => {
  it.each(FIXTURES)('adapts and renders the %s fixture', (state, fixture, expectedText) => {
    const aggregate = adaptWorkbenchAggregate(fixture)
    const html = renderToStaticMarkup(<ResearchWorkbench aggregate={aggregate} />)

    expect(aggregate.projection_kind).toBe('research-v3-current')
    if (aggregate.projection_kind !== 'research-v3-current') throw new Error('expected current projection')
    expect(aggregate.workflow.state).toBe(state)
    expect(html).toContain(`data-workbench-state="${state}"`)
    for (const text of expectedText) expect(html).toContain(text)
  })

  it('keeps candidate controls keyboard-addressable and exposes carousel semantics', () => {
    const html = renderToStaticMarkup(<ResearchWorkbench aggregate={adaptWorkbenchAggregate(candidatesFixture)} />)

    expect(html).toContain('aria-roledescription="carousel"')
    expect(html).toContain('aria-label="上一个方案"')
    expect(html).toContain('aria-label="下一个方案"')
    expect(html).toContain('tabindex="0"')
  })

  it('provides a complete text alternative for the visual DAG', () => {
    const html = renderToStaticMarkup(<ResearchWorkbench aggregate={adaptWorkbenchAggregate(dagFixture)} />)

    expect(html).toContain('role="img"')
    expect(html).toContain('研究执行流程，共 2 个步骤')
    expect(html).toContain('依赖步骤 1')
  })

  it('renders only sanitized evidence and never raw Tool Artifact references', () => {
    const html = renderToStaticMarkup(<ResearchWorkbench aggregate={adaptWorkbenchAggregate(textReportFixture)} />)

    expect(html).toContain('Alpha product documentation')
    expect(html).toContain('example.test')
    expect(html).toContain('已脱敏')
    expect(html).not.toContain('artifact_tool_1')
    expect(html).not.toContain('5f7a8b1d1b262967b9b8498f496b6a51668d8b373402819c0d4b48a05fbf3156')
  })

  it('presents v2 history as read-only and ignores Tool Artifact-shaped payload fields', () => {
    const history: ResearchV2HistoryWorkbenchAggregateV1 = {
      schema_version: 'research-workbench-aggregate-v1',
      projection_kind: 'research-v2-history',
      orchestration_version: 'research-v2',
      read_only: true,
      run_id: 'run_v2',
      history_payload: {
        title: '旧版竞品研究',
        status: 'completed',
        original_input: '比较旧版 Alpha 与 Beta',
        report_summary: '历史结论可供阅读。',
        tool_artifact: 'RAW-TOOL-ARTIFACT-MUST-NOT-RENDER',
      },
      provenance: {
        baseline_state_id: 'text_report',
        projected_at: '2026-08-21T00:00:00Z',
        projection_schema_version: 'research-workbench-aggregate-v1',
        source_kind: 'v2_history_adapter',
        source_state_version: 7,
      },
    }
    const html = renderToStaticMarkup(<ResearchWorkbench aggregate={adaptWorkbenchAggregate(history)} />)

    expect(html).toContain('旧版竞品研究')
    expect(html).toContain('历史结论可供阅读。')
    expect(html).toContain('只读')
    expect(html).not.toContain('RAW-TOOL-ARTIFACT-MUST-NOT-RENDER')
  })

  it('renders scoped loading and error states', () => {
    const loading = renderToStaticMarkup(<ResearchWorkbench status="loading" />)
    const error = renderToStaticMarkup(<ResearchWorkbench status="error" errorMessage="读取超时" actions={{ onRetryLoad: () => undefined }} />)

    expect(loading).toContain('role="status"')
    expect(loading).toContain('正在读取研究任务')
    expect(error).toContain('role="alert"')
    expect(error).toContain('读取超时')
  })

  it('rejects shape fallback across stored orchestration versions', () => {
    expect(() => adaptWorkbenchAggregate({ ...idleFixture, orchestration_version: 'research-v2' })).toThrow(
      'research-v3-current requires research-v3 orchestration',
    )
    expect(() => adaptWorkbenchAggregate({ ...idleFixture, projection_kind: 'unknown' })).toThrow(
      'Unsupported workbench projection kind',
    )
  })

  it('keeps exact ai-x colors and the 760px flow scoped to the feature root', () => {
    const cssPath = fileURLToPath(new URL('./research-workbench.css', import.meta.url))
    const css = readFileSync(cssPath, 'utf8')

    for (const token of [
      '--bg: #0a0d16', '--bg-elev: #10141f', '--bg-card: #151a27', '--bg-card-hi: #1c2233',
      '--border: #232a3d', '--text: #e6e9f0', '--text-dim: #a5adbf', '--text-faint: #6b7488',
      '--primary: #7c7cf0', '--primary-strong: #9ea0ff', '--ok: #34d399', '--warn: #fbbf24',
      '--danger: #f87171', '--report-paper: #f6f4ee', '--report-ink: #1c2230', '--report-accent: #5f60d9',
    ]) expect(css).toContain(token)
    expect(css).toContain('width: min(100%, 760px)')
    expect(css).toContain('@media (max-width: 720px)')
  })

  it('renders all eight frozen fixtures in the standalone gallery', () => {
    const html = renderToStaticMarkup(
      <ResearchWorkbenchFixtureGallery fixtures={FIXTURES.map(([id, aggregate]) => ({ id, label: id, aggregate }))} />,
    )

    expect(html.match(/data-fixture-id=/g)).toHaveLength(8)
    expect(html).toContain('Research workbench fixture gallery')
  })
})
