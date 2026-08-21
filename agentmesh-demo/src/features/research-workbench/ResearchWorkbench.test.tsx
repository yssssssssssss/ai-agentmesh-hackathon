import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import approvalFixture from '../../../../tests/fixtures/research_v3_workbench/approval.json'
import candidatesFixture from '../../../../tests/fixtures/research_v3_workbench/candidates.json'
import clarifyFixture from '../../../../tests/fixtures/research_v3_workbench/clarify.json'
import dagFixture from '../../../../tests/fixtures/research_v3_workbench/dag_or_executing.json'
import idleFixture from '../../../../tests/fixtures/research_v3_workbench/idle.json'
import integrationDepthFixture from '../../../../tests/fixtures/research_v3_integration/competitive_text_depth.json'
import pausedFixture from '../../../../tests/fixtures/research_v3_workbench/paused.json'
import planFixture from '../../../../tests/fixtures/research_v3_workbench/plan.json'
import textReportFixture from '../../../../tests/fixtures/research_v3_workbench/text_report.json'
import { adaptWorkbenchAggregate } from './adapter'
import { CANONICAL_WORKBENCH_SCHEMA_SHA256 } from './canonicalValidation'
import { ResearchWorkbench } from './ResearchWorkbench'
import { ResearchWorkbenchFixtureGallery } from './ResearchWorkbenchFixtureGallery'
import type { ResearchWorkbenchRenderV1 } from './types'

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

function canonicalToken(value: unknown): string {
  if (value === null || typeof value === 'number' || typeof value === 'boolean') return JSON.stringify(value)
  if (typeof value === 'string') return JSON.stringify(value.normalize('NFC'))
  if (Array.isArray(value)) return `[${value.map(canonicalToken).join(',')}]`
  if (typeof value === 'object') {
    return `{${Object.entries(value).sort(([left], [right]) => left.localeCompare(right, 'en'))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalToken(item)}`).join(',')}}`
  }
  throw new TypeError('unsupported test value')
}

function resealReport(fixture: { report: { artifact: { content_hash: string }; content: unknown } }): void {
  fixture.report.artifact.content_hash = createHash('sha256').update(canonicalToken(fixture.report.content)).digest('hex')
}

type MutableArtifactIdentity = {
  content_hash: string
  kind: string
  schema_version: string
}

type TextReportFixture = typeof textReportFixture

const CONTEXTUAL_ARTIFACT_IDENTITIES: ReadonlyArray<{
  label: string
  artifact: (fixture: TextReportFixture) => MutableArtifactIdentity
  kind: string
  schemaVersion: string
  schemaEnforced?: boolean
}> = [
  {
    label: 'Plan Problem Graph reference',
    artifact: (fixture) => fixture.selected_plan.payload.problem_graph_artifact,
    kind: 'problem_graph',
    schemaVersion: 'problem-graph-v1',
    schemaEnforced: true,
  },
  {
    label: 'Plan control snapshot reference',
    artifact: (fixture) => fixture.selected_plan.payload.control_snapshot_artifact,
    kind: 'research_control_snapshot',
    schemaVersion: 'research-control-snapshot-v3',
  },
  {
    label: 'Evidence wrapper',
    artifact: (fixture) => fixture.evidence.artifact,
    kind: 'evidence_manifest',
    schemaVersion: 'evidence-manifest-v3',
    schemaEnforced: true,
  },
  {
    label: 'Deliverable Evidence Manifest reference',
    artifact: (fixture) => fixture.deliverable.content.evidence_manifest_artifact,
    kind: 'evidence_manifest',
    schemaVersion: 'evidence-manifest-v3',
    schemaEnforced: true,
  },
  {
    label: 'Deliverable wrapper',
    artifact: (fixture) => fixture.deliverable.artifact,
    kind: 'research_deliverable',
    schemaVersion: 'research-deliverable-v3',
  },
  {
    label: 'Review Deliverable reference',
    artifact: (fixture) => fixture.review.content.deliverable_artifact,
    kind: 'research_deliverable',
    schemaVersion: 'research-deliverable-v3',
  },
  {
    label: 'Review wrapper',
    artifact: (fixture) => fixture.review.artifact,
    kind: 'report_review',
    schemaVersion: 'report-review-v3',
  },
  {
    label: 'Report Deliverable reference',
    artifact: (fixture) => fixture.report.content.deliverable_artifact,
    kind: 'research_deliverable',
    schemaVersion: 'research-deliverable-v3',
  },
  {
    label: 'Report Review reference',
    artifact: (fixture) => fixture.report.content.review_artifact,
    kind: 'report_review',
    schemaVersion: 'report-review-v3',
  },
  {
    label: 'Report wrapper',
    artifact: (fixture) => fixture.report.artifact,
    kind: 'report_document',
    schemaVersion: 'report-document-v3',
  },
]

describe('research-workbench-aggregate-v1 fixture renderer', () => {
  it.each(FIXTURES)('adapts and renders the %s fixture', (state, fixture, expectedText) => {
    const aggregate = adaptWorkbenchAggregate(fixture)
    const html = renderToStaticMarkup(<ResearchWorkbench aggregate={aggregate} />)

    expect(aggregate.render_schema_version).toBe('research-workbench-render-v1')
    expect(aggregate.source_schema_version).toBe('research-workbench-aggregate-v1')
    expect(aggregate.render_kind).toBe('current')
    if (aggregate.render_kind !== 'current') throw new Error('expected current render projection')
    expect(aggregate.workflow.state).toBe(state)
    expect(html).toContain(`data-workbench-state="${state}"`)
    for (const text of expectedText) expect(html).toContain(text)
  })

  it('consumes the full synthetic Competitive Text integration aggregate through the frozen adapter', () => {
    const aggregate = adaptWorkbenchAggregate(integrationDepthFixture)
    const html = renderToStaticMarkup(<ResearchWorkbench aggregate={aggregate} />)

    expect(aggregate.render_kind).toBe('current')
    if (aggregate.render_kind !== 'current') throw new Error('expected current render projection')
    expect(aggregate.provenance.source_kind).toBe('repository_projection')
    expect(aggregate.workflow.state).toBe('text_report')
    expect(aggregate.selected_plan?.payload.candidate_id).toBe('depth')
    expect(aggregate.attempt?.steps).toHaveLength(4)
    expect(html).toContain('Alpha vs Beta — Competitive Analysis')
    expect(html).toContain('Alpha synthetic product documentation')
    expect(html).not.toContain('artifact_actor_attempt_depth_1')
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
    const history = {
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
        baseline_state_id: null,
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

  it('rejects relabelled states, gate mismatches, and cross-version provenance', () => {
    const relabelledIdle = structuredClone(idleFixture)
    relabelledIdle.workflow = {
      state: 'text_report',
      state_version: 7,
      gate: { kind: 'none', status: 'inactive', required_role: null },
    }
    relabelledIdle.provenance.baseline_state_id = 'text_report'
    relabelledIdle.provenance.source_state_version = 7
    expect(() => adaptWorkbenchAggregate(relabelledIdle)).toThrow(
      'Workbench aggregate fields do not match the frozen state projection',
    )

    const gateMismatch = structuredClone(idleFixture)
    gateMismatch.workflow.gate = { kind: 'clarification', status: 'pending', required_role: null }
    expect(() => adaptWorkbenchAggregate(gateMismatch)).toThrow(
      'Workbench workflow state and active gate do not agree',
    )

    expect(() => adaptWorkbenchAggregate({ ...idleFixture, orchestration_version: 'research-v2' })).toThrow(
      'Invalid research-workbench-aggregate-v1',
    )
    expect(() => adaptWorkbenchAggregate({ ...idleFixture, projection_kind: 'unknown' })).toThrow(
      'Invalid research-workbench-aggregate-v1',
    )
    expect(() => adaptWorkbenchAggregate({
      ...idleFixture,
      provenance: { ...idleFixture.provenance, source_kind: 'v2_history_adapter', baseline_state_id: null },
    })).toThrow('research-v3 current projections cannot use v2 history provenance')
  })

  it('accepts repository projection provenance only with a null baseline state', () => {
    const repositoryProjection = {
      ...idleFixture,
      provenance: { ...idleFixture.provenance, source_kind: 'repository_projection', baseline_state_id: null },
    }
    const aggregate = adaptWorkbenchAggregate(repositoryProjection)

    expect(aggregate.render_kind).toBe('current')
    expect(aggregate.provenance).toEqual(expect.objectContaining({
      source_kind: 'repository_projection',
      baseline_state_id: null,
    }))
    expect(() => adaptWorkbenchAggregate({
      ...repositoryProjection,
      provenance: { ...repositoryProjection.provenance, baseline_state_id: 'idle' },
    })).toThrow('baseline_state_id must be null for non-fixture projections')
  })

  it('keeps the workflow at 760px while the text report uses the 1240px report container', () => {
    const html = renderToStaticMarkup(<ResearchWorkbench aggregate={adaptWorkbenchAggregate(textReportFixture)} />)
    const workflowStart = html.indexOf('data-layout="workflow"')
    const dagStart = html.indexOf('data-stage="dag"')
    const reportStart = html.indexOf('data-layout="report"')
    const documentStart = html.indexOf('data-stage="text-report"')

    expect(workflowStart).toBeGreaterThan(-1)
    expect(dagStart).toBeGreaterThan(workflowStart)
    expect(dagStart).toBeLessThan(reportStart)
    expect(documentStart).toBeGreaterThan(reportStart)

    const cssPath = fileURLToPath(new URL('./research-workbench.css', import.meta.url))
    const css = readFileSync(cssPath, 'utf8')
    expect(css).toMatch(/\.rw-flow\s*\{[^}]*width: min\(100%, 760px\)/s)
    expect(css).toMatch(/\.rw-report-flow\s*\{[^}]*width: min\(100%, 1240px\)/s)
  })

  it('uses AA-contrast primary button tokens for normal and hover states', () => {
    const cssPath = fileURLToPath(new URL('./research-workbench.css', import.meta.url))
    const css = readFileSync(cssPath, 'utf8')
    const token = (name: string) => {
      const value = css.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, 'i'))?.[1]
      if (!value) throw new Error(`missing color token ${name}`)
      return value
    }
    const luminance = (hex: string) => {
      const channels = hex.match(/[0-9a-f]{2}/gi)
      if (!channels) throw new Error(`invalid hex color ${hex}`)
      const [red, green, blue] = channels.map((channel) => {
        const value = Number.parseInt(channel, 16) / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    }
    const contrast = (foreground: string, background: string) => {
      const values = [luminance(foreground), luminance(background)].sort((left, right) => right - left)
      return (values[0] + 0.05) / (values[1] + 0.05)
    }

    expect(token('--button-primary-bg')).toBe('#5f60d9')
    expect(token('--button-primary-bg-hover')).toBe('#5556bd')
    expect(token('--button-primary-text')).toBe('#ffffff')
    expect(contrast(token('--button-primary-text'), token('--button-primary-bg'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(token('--button-primary-text'), token('--button-primary-bg-hover'))).toBeGreaterThanOrEqual(4.5)
    expect(css).toContain('background: var(--button-primary-bg)')
    expect(css).toContain('background: var(--button-primary-bg-hover)')
  })

  it('rejects nested extras and missing required canonical fields before projection', () => {
    const nestedExtra = structuredClone(clarifyFixture) as unknown as {
      requirement: { payload: Record<string, unknown> }
    }
    nestedExtra.requirement.payload.untrusted_extra = true
    expect(() => adaptWorkbenchAggregate(nestedExtra)).toThrow('Invalid research-workbench-aggregate-v1')

    const missingField = structuredClone(candidatesFixture) as unknown as {
      candidates: { candidates: Array<Record<string, unknown>> }
    }
    delete missingField.candidates.candidates[0].tradeoffs
    expect(() => adaptWorkbenchAggregate(missingField)).toThrow('Invalid research-workbench-aggregate-v1')
  })

  it('rejects kind-only and schema-only relabelling for every context-bound canonical Artifact', () => {
    for (const identity of CONTEXTUAL_ARTIFACT_IDENTITIES) {
      for (const field of ['kind', 'schema_version'] as const) {
        const relabelled = structuredClone(textReportFixture)
        const artifact = identity.artifact(relabelled)
        const original = structuredClone(artifact)
        artifact[field] = field === 'kind' ? 'relabelled_artifact' : 'relabelled-schema-v1'

        expect(artifact.content_hash, `${identity.label} ${field} hash`).toBe(original.content_hash)
        expect(artifact, `${identity.label} ${field} mutation`).toEqual({
          ...original,
          [field]: field === 'kind' ? 'relabelled_artifact' : 'relabelled-schema-v1',
        })
        const expected = identity.schemaEnforced
          ? 'Invalid research-workbench-aggregate-v1'
          : `${field} must be ${field === 'kind' ? identity.kind : identity.schemaVersion}`
        expect(() => adaptWorkbenchAggregate(relabelled), `${identity.label} ${field}`).toThrow(expected)
      }
    }
  })

  it('rejects stale hashes and broken lineage references', () => {
    const staleReport = structuredClone(textReportFixture)
    staleReport.report.content.title = 'Tampered without resealing'
    expect(() => adaptWorkbenchAggregate(staleReport)).toThrow('report artifact hash does not match canonical content')

    const staleRequirement = structuredClone(planFixture)
    staleRequirement.requirement.payload.research_goal = 'Tampered requirement'
    expect(() => adaptWorkbenchAggregate(staleRequirement)).toThrow('requirement.content_hash does not match canonical content')

    const brokenLineage = structuredClone(textReportFixture)
    brokenLineage.evidence.plan_version_id = 'plan_other'
    expect(() => adaptWorkbenchAggregate(brokenLineage)).toThrow('Workbench Evidence Manifest lineage is invalid')
  })

  it('rejects invalid fact and metric Evidence bindings', () => {
    const emptyFactEvidence = structuredClone(textReportFixture)
    const findings = emptyFactEvidence.report.content.sections.find((section) => section.id === 'findings')
    if (!findings || findings.blocks[0]?.type !== 'fact') throw new Error('expected fact fixture')
    ;(findings.blocks[0] as { evidence_ids: string[] }).evidence_ids = []
    resealReport(emptyFactEvidence)
    expect(() => adaptWorkbenchAggregate(emptyFactEvidence)).toThrow('Invalid research-workbench-aggregate-v1')

    const unknownMetricEvidence = structuredClone(textReportFixture)
    const metrics = unknownMetricEvidence.report.content.sections.find((section) => section.id === 'key-metrics')
    if (!metrics) throw new Error('expected metrics section')
    ;(metrics as unknown as { blocks: unknown[] }).blocks = [
      { id: 'block_metric', type: 'metric', label: 'Score', value: 4, evidence_ids: ['evidence_missing'] },
    ]
    resealReport(unknownMetricEvidence)
    expect(() => adaptWorkbenchAggregate(unknownMetricEvidence)).toThrow('Workbench report block references unknown Evidence')
  })

  it('pins the feature-local canonical schema copy and strips canonical identities from render models', () => {
    const localSchemaPath = fileURLToPath(new URL('./research-workbench-aggregate-v1.schema.json', import.meta.url))
    const backendSchemaPath = fileURLToPath(new URL('../../../../agentmesh/schemas/research/research-workbench-aggregate-v1.schema.json', import.meta.url))
    const localSchema = readFileSync(localSchemaPath)
    expect(localSchema.equals(readFileSync(backendSchemaPath))).toBe(true)
    expect(createHash('sha256').update(localSchema).digest('hex')).toBe(CANONICAL_WORKBENCH_SCHEMA_SHA256)

    const renderModel = adaptWorkbenchAggregate(textReportFixture)
    expect(renderModel.render_schema_version).toBe('research-workbench-render-v1')
    expect(renderModel).not.toHaveProperty('schema_version')
    expect(renderModel).not.toHaveProperty('projection_kind')
    expect(JSON.stringify(renderModel)).not.toMatch(/"(?:artifact|content_hash|plan_hash|contract_hash|step_contract_hash)"/)
  })

  it('renders metric Evidence from an explicitly unsealed render-model variant', () => {
    const metricRender = structuredClone(adaptWorkbenchAggregate(textReportFixture)) as ResearchWorkbenchRenderV1
    if (metricRender.render_kind !== 'current' || !metricRender.report) throw new Error('expected report render model')
    const metrics = metricRender.report.content.sections.find((section) => section.id === 'key-metrics')
    const findings = metricRender.report.content.sections.find((section) => section.id === 'findings')
    if (!metrics || !findings || findings.blocks[0]?.type !== 'fact') throw new Error('expected fixture report sections')
    metrics.blocks = [{
      id: 'block_metric',
      type: 'metric',
      label: 'Supported capability score',
      value: 4,
      evidence_ids: ['evidence_1'],
    }]
    findings.blocks[0].evidence_ids = []

    const html = renderToStaticMarkup(<ResearchWorkbench aggregate={metricRender} />)
    expect(html.match(/查看证据（1）/g)).toHaveLength(1)
    expect(html).toMatch(/rw-report-metric-block[\s\S]*Supported capability score[\s\S]*<dd>4<\/dd>[\s\S]*查看证据（1）/)
    expect(html).toMatch(/rw-report-metric-block[\s\S]*Alpha product documentation/)
  })

  it('meets AA contrast for every normal-size token pair used by the feature', () => {
    const cssPath = fileURLToPath(new URL('./research-workbench.css', import.meta.url))
    const css = readFileSync(cssPath, 'utf8')
    const token = (name: string) => {
      const value = css.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, 'i'))?.[1]
      if (!value) throw new Error(`missing color token ${name}`)
      return value
    }
    const luminance = (hex: string) => {
      const channels = hex.slice(1).match(/[0-9a-f]{2}/gi)
      if (!channels) throw new Error(`invalid hex color ${hex}`)
      const [red, green, blue] = channels.map((channel) => {
        const value = Number.parseInt(channel, 16) / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    }
    const contrast = (foreground: string, background: string) => {
      const values = [luminance(foreground), luminance(background)].sort((left, right) => right - left)
      return (values[0] + 0.05) / (values[1] + 0.05)
    }
    const pairs = [
      ['--text', '--bg'], ['--text', '--bg-elev'], ['--text', '--bg-card'], ['--text', '--bg-card-hi'],
      ['--text-dim', '--bg'], ['--text-dim', '--bg-elev'], ['--text-dim', '--bg-card'], ['--text-dim', '--bg-card-hi'],
      ['--text-faint', '--bg'], ['--text-faint', '--bg-elev'], ['--text-faint', '--bg-card'],
      ['--text-faint', '--bg-card-hi'], ['--text-faint', '--border'], ['--muted', '--bg-card'],
      ['--primary-strong', '--bg-card-hi'], ['--ok', '--bg-card-hi'], ['--warn', '--bg-card-hi'],
      ['--danger', '--bg-card-hi'], ['--skill-fg', '--bg-card-hi'], ['--tool-fg', '--bg-card-hi'],
      ['--llm-fg', '--bg-card-hi'], ['--reviewer-fg', '--bg-card-hi'],
      ['--button-primary-text', '--button-primary-bg'], ['--button-primary-text', '--button-primary-bg-hover'],
      ['--button-primary-text', '--stage-number-bg'], ['--button-primary-text', '--stage-number-bg-hover'],
      ['--report-ink', '--report-paper'], ['--report-muted', '--report-paper'], ['--report-accent', '--report-paper'],
      ['--report-ok', '--report-paper'],
    ] as const
    for (const [foreground, background] of pairs) {
      expect(contrast(token(foreground), token(background)), `${foreground} on ${background}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('computes AA contrast after compositing de-emphasized candidates and skipped DAG nodes', () => {
    const cssPath = fileURLToPath(new URL('./research-workbench.css', import.meta.url))
    const css = readFileSync(cssPath, 'utf8')
    type Rgba = readonly [number, number, number, number]
    type Rgb = readonly [number, number, number]
    const token = (name: string): Rgba => {
      const raw = css.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6}|rgba\\([^)]*\\))`, 'i'))?.[1]
      if (!raw) throw new Error(`missing color token ${name}`)
      if (raw.startsWith('#')) {
        const channels = raw.slice(1).match(/[0-9a-f]{2}/gi)?.map((channel) => Number.parseInt(channel, 16))
        if (!channels || channels.length !== 3) throw new Error(`invalid hex color ${raw}`)
        return [channels[0], channels[1], channels[2], 1]
      }
      const channels = raw.match(/[\d.]+/g)?.map(Number)
      if (!channels || channels.length !== 4) throw new Error(`invalid rgba color ${raw}`)
      return [channels[0], channels[1], channels[2], channels[3]]
    }
    const composite = (foreground: Rgba, background: Rgb): Rgb => [
      foreground[0] * foreground[3] + background[0] * (1 - foreground[3]),
      foreground[1] * foreground[3] + background[1] * (1 - foreground[3]),
      foreground[2] * foreground[3] + background[2] * (1 - foreground[3]),
    ]
    const opaque = (color: Rgba): Rgb => {
      if (color[3] !== 1) throw new Error('expected an opaque parent background')
      return [color[0], color[1], color[2]]
    }
    const luminance = (color: Rgb) => {
      const [red, green, blue] = color.map((channel) => {
        const value = channel / 255
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
      })
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    }
    const contrast = (foreground: Rgb, background: Rgb) => {
      const values = [luminance(foreground), luminance(background)].sort((left, right) => right - left)
      return (values[0] + 0.05) / (values[1] + 0.05)
    }
    const effectiveContrast = (foregroundToken: string, background: Rgb) => (
      contrast(composite(token(foregroundToken), background), background)
    )

    const candidateRule = css.match(/\.rw-candidate-slide\s*\{([^}]*)\}/s)?.[1]
    const skippedRule = css.match(/\.rw-dag-node\.status-skipped\s*\{([^}]*)\}/s)?.[1]
    expect(candidateRule).toBeDefined()
    expect(skippedRule).toBeDefined()
    expect(candidateRule).not.toMatch(/\bopacity\s*:/)
    expect(skippedRule).not.toMatch(/\bopacity\s*:/)
    expect(css).toContain('background: var(--candidate-muted-bg)')
    expect(css).toContain('color: var(--candidate-muted-title)')
    expect(css).toContain('color: var(--candidate-muted-body)')
    expect(css).toContain('color: var(--candidate-muted-label)')
    expect(css).toContain('background: var(--skipped-node-bg)')
    expect(css).toContain('color: var(--skipped-node-title)')
    expect(css).toContain('color: var(--skipped-node-label)')

    const candidateBackground = composite(token('--candidate-muted-bg'), opaque(token('--bg-card')))
    for (const [label, foreground] of [
      ['non-current candidate title', '--candidate-muted-title'],
      ['non-current candidate body', '--candidate-muted-body'],
      ['non-current candidate 10–11px labels', '--candidate-muted-label'],
    ] as const) {
      expect(effectiveContrast(foreground, candidateBackground), label).toBeGreaterThanOrEqual(4.5)
    }

    const skippedBackground = composite(token('--skipped-node-bg'), opaque(token('--bg')))
    for (const [label, foreground] of [
      ['skipped-node 12px title', '--skipped-node-title'],
      ['skipped-node 9–10px labels', '--skipped-node-label'],
    ] as const) {
      expect(effectiveContrast(foreground, skippedBackground), label).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('keeps exact ai-x colors and the 760px flow scoped to the feature root', () => {
    const cssPath = fileURLToPath(new URL('./research-workbench.css', import.meta.url))
    const css = readFileSync(cssPath, 'utf8')

    for (const token of [
      '--bg: #0a0d16', '--bg-elev: #10141f', '--bg-card: #151a27', '--bg-card-hi: #1c2233',
      '--border: #232a3d', '--text: #e6e9f0', '--text-dim: #a5adbf', '--text-faint: #8d96aa',
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
