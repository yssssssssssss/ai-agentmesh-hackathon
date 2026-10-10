import { useState } from 'react'
import type { components } from '../../api/generated/schema'

export type ProcedureDraft = components['schemas']['ProcedureDraftV1']
export interface ProcedureForm {
  enabled: boolean; goal: string; steps: string; validation: string; preconditions: string
  toolVersions: Record<string, string>
}
const emptyForm: ProcedureForm = { enabled: false, goal: '', steps: '', validation: '', preconditions: '', toolVersions: {} }
const lines = (value: string) => value.split('\n').map((item) => item.trim()).filter(Boolean)

export function procedureDraft(form: ProcedureForm): { value?: ProcedureDraft; valid: boolean } {
  if (!form.enabled) return { valid: true }
  const steps = lines(form.steps), validation = lines(form.validation), preconditions = lines(form.preconditions)
  const values = [form.goal.trim(), ...steps, ...validation, ...preconditions]
  const valid = Boolean(form.goal.trim() && steps.length && validation.length) && steps.length <= 20
    && validation.length <= 12 && preconditions.length <= 11 && values.every((value) => value.length <= 1000)
    && Object.keys(form.toolVersions).length <= 16
  return { valid, value: { goal_patterns: [form.goal.trim()], steps, validation_conditions: validation,
    preconditions: ['project_member', ...preconditions], tool_versions: form.toolVersions, environment_versions: {} } }
}

export function ProcedureCaptureFields({ tools = [], disabled, onChange }: {
  tools?: components['schemas']['ToolDefinition'][]; disabled: boolean
  onChange: (value: ProcedureDraft | undefined, valid: boolean) => void
}) {
  const [form, setForm] = useState(emptyForm)
  const change = (next: ProcedureForm) => {
    setForm(next)
    const result = procedureDraft(next)
    onChange(result.value, result.valid)
  }
  const inputClass = 'mt-1 block w-full rounded-control border border-white/10 bg-surface-1 p-2 text-sm'
  return <fieldset disabled={disabled} className="space-y-3" aria-label="记录程序经验">
    <label className="flex items-center gap-2 text-sm text-slate-300">
      <input type="checkbox" checked={form.enabled} onChange={(event) => change({ ...form, enabled: event.target.checked })} />
      记录可复用的方法
    </label>
    {form.enabled ? <>
      <p className="text-xs text-slate-400">后续请求含相同目标文字时可检查适用性。验收来源由本次审核记录提供；方法用于参考，工具调用仍遵守当前授权和审批。</p>
      <label className="block text-xs text-slate-300">适用目标
        <input className={inputClass} maxLength={1000} value={form.goal}
          onChange={(event) => change({ ...form, goal: event.target.value })} />
      </label>
      <label className="block text-xs text-slate-300">建议步骤（每行一项，最多 20 项）
        <textarea className={inputClass} rows={3} value={form.steps} maxLength={20_020}
          onChange={(event) => change({ ...form, steps: event.target.value })} />
      </label>
      <label className="block text-xs text-slate-300">验证条件（每行一项，最多 12 项）
        <textarea className={inputClass} rows={2} value={form.validation} maxLength={12_012}
          onChange={(event) => change({ ...form, validation: event.target.value })} />
      </label>
      <label className="block text-xs text-slate-300">其他前置条件（每行一项，最多 11 项）
        <textarea className={inputClass} rows={2} value={form.preconditions} maxLength={11_011}
          onChange={(event) => change({ ...form, preconditions: event.target.value })} />
      </label>
      <p className="text-xs text-slate-400">系统可核对本项目成员身份。其他文字条件需要人工核实，填写后将保留为待确认经验。</p>
      {tools.length ? <div className="space-y-2 text-xs text-slate-300">
        <p>方法依赖的已授权工具（保留选中时的版本）</p>
        {tools.map((tool) => <label key={tool.id} className="flex items-center gap-2">
          <input type="checkbox" checked={Object.prototype.hasOwnProperty.call(form.toolVersions, tool.id)} onChange={(event) => {
            const next = { ...form.toolVersions }
            if (event.target.checked) next[tool.id] = tool.implementation_version ?? '1'
            else delete next[tool.id]
            change({ ...form, toolVersions: next })
          }} />{tool.name} · v{form.toolVersions[tool.id] ?? tool.implementation_version ?? '1'}
        </label>)}
      </div> : null}
      {!procedureDraft(form).valid ? <p className="text-xs text-amber-300">请填写目标、步骤和验证条件，并检查条数及每项长度。</p> : null}
    </> : null}
  </fieldset>
}
