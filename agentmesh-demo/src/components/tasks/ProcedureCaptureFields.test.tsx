import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ProcedureCaptureFields, procedureDraft, type ProcedureForm } from './ProcedureCaptureFields'

const form: ProcedureForm = { enabled: true, goal: '检查项目约束', steps: '查看证据\n核对版本',
  validation: '独立审核通过', preconditions: '人工核实企业环境', toolVersions: { tool_project_state: '1' } }

describe('procedure capture', () => {
  it('requires explicit opt-in and does not emit a payload for ordinary captures', () => {
    expect(procedureDraft({ ...form, enabled: false })).toEqual({ valid: true })
    const html = renderToStaticMarkup(<ProcedureCaptureFields disabled={false} onChange={() => {}} />)
    expect(html).toContain('记录可复用的方法')
    expect(html).not.toContain('适用目标')
  })

  it('retains human conditions and the selected tool version without inventing reviewed evidence', () => {
    const result = procedureDraft(form)
    expect(result.valid).toBe(true)
    expect(result.value?.steps).toEqual(['查看证据', '核对版本'])
    expect(result.value?.preconditions).toEqual(['project_member', '人工核实企业环境'])
    expect(result.value?.tool_versions).toEqual({ tool_project_state: '1' })
    expect(result.value).not.toHaveProperty('successful_runs')
    expect(result.value).not.toHaveProperty('human_confirmed_by')
  })

  it('rejects incomplete, oversized and excessive lists before allowing capture', () => {
    expect(procedureDraft({ ...form, goal: '' }).valid).toBe(false)
    expect(procedureDraft({ ...form, validation: '' }).valid).toBe(false)
    expect(procedureDraft({ ...form, steps: Array(21).fill('步骤').join('\n') }).valid).toBe(false)
    expect(procedureDraft({ ...form, steps: 'x'.repeat(1001) }).valid).toBe(false)
  })
})
