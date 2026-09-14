import { FileSpreadsheet, FileText, Trash2, Upload } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import type {
  RunInputArtifact,
  SkillInputRequestResponse,
  SkillInputSubmitRequest,
  SkillPlan,
  Skill,
} from '../../features/workspace/types'
import { Button } from '../ui/Button'

interface SkillInputPreflightPanelProps {
  response: SkillInputRequestResponse
  plan?: SkillPlan
  skills?: Skill[]
  pendingAction: 'upload' | 'remove' | 'submit' | 'cancel' | null
  error: string | null
  onUpload: (fieldId: string, file: File) => void
  onRemove: (artifactId: string) => void
  onSubmit: (request: SkillInputSubmitRequest) => void
  onCancel: () => void
}

const ERROR_LABELS: Record<string, string> = {
  input_artifact_not_ready: '文件尚未解析完成',
  input_artifact_binding_invalid: '文件与当前字段不匹配',
  input_artifact_count_invalid: '文件数量不符合要求',
  input_text_too_short: '填写内容过短',
  input_text_too_long: '填写内容超过长度限制',
  input_encoding_invalid: '文件必须使用 UTF-8 编码',
  input_csv_header_invalid: 'CSV 表头不能为空',
  input_csv_duplicate_header: 'CSV 存在重复表头',
  input_csv_shape_invalid: 'CSV 行列结构不一致或超出限制',
  input_csv_cell_too_large: 'CSV 单元格内容过长',
  input_csv_schema_mismatch: 'CSV 缺少必需列',
  input_content_too_large: '内容过大，请缩小范围后重新上传',
  input_media_type_mismatch: '文件扩展名与文件类型不一致',
  input_media_type_unsupported: '当前字段不支持这种文件类型',
  input_content_quarantined: '内容包含疑似指令，已隔离，不能用于执行',
  input_credential_detected: '检测到凭据内容，已隔离；请移除密钥、令牌或密码后重试',
}

function artifactIcon(artifact: RunInputArtifact) {
  return artifact.media_type === 'text/csv'
    ? <FileSpreadsheet className="h-4 w-4" aria-hidden="true" />
    : <FileText className="h-4 w-4" aria-hidden="true" />
}

function acceptedExtensions(mediaTypes: string[]) {
  const extensions = mediaTypes.flatMap((mediaType) => {
    if (mediaType === 'text/csv') return ['.csv']
    if (mediaType === 'text/markdown') return ['.md', '.markdown']
    if (mediaType === 'text/plain') return ['.txt']
    return []
  })
  return extensions.join(',')
}

function artifactSummary(artifact: RunInputArtifact): string | null {
  const summary = artifact.summary
  if (!summary) return null
  const rows = typeof summary.row_count === 'number' ? summary.row_count : null
  const columns = Array.isArray(summary.columns)
    ? summary.columns.filter((item): item is string => typeof item === 'string')
    : []
  if (rows === null && columns.length === 0) return null
  return `${rows ?? 0} 行 · ${columns.length} 列${columns.length ? ` · ${columns.join('、')}` : ''}`
}

export function SkillInputPreflightPanel({
  response,
  plan,
  skills = [],
  pendingAction,
  error,
  onUpload,
  onRemove,
  onSubmit,
  onCancel,
}: SkillInputPreflightPanelProps) {
  const request = response.item
  const skillNames = useMemo(
    () => new Map(skills.map((skill) => [skill.id, skill.title])),
    [skills],
  )
  const [textValues, setTextValues] = useState<Record<string, string>>({})
  const requestId = useRef<string | null>(null)
  const dirtyTextFields = useRef(new Set<string>())
  const fields = request.fields ?? []
  const artifactsByField = useMemo(() => {
    const groups = new Map<string, RunInputArtifact[]>()
    for (const artifact of response.artifacts ?? []) {
      groups.set(artifact.field_id, [...(groups.get(artifact.field_id) ?? []), artifact])
    }
    return groups
  }, [response.artifacts])

  useEffect(() => {
    const changedRequest = requestId.current !== request.id
    if (changedRequest) {
      requestId.current = request.id
      dirtyTextFields.current.clear()
    }
    setTextValues((current) => Object.fromEntries(
      fields
        .filter((field) => field.value_kind === 'text')
        .map((field) => [
          field.id,
          !changedRequest && dirtyTextFields.current.has(field.id)
            ? current[field.id] ?? field.text_value ?? ''
            : field.text_value ?? '',
        ]),
    ))
  }, [request.id, request.version])

  const submit = (advance: boolean) => {
    const artifactIds = Object.fromEntries(
      fields
        .filter((field) => field.value_kind === 'artifact')
        .map((field) => [
          field.id,
          (artifactsByField.get(field.id) ?? [])
            .filter((artifact) => artifact.status === 'ready')
            .map((artifact) => artifact.id),
        ]),
    )
    onSubmit({
      client_turn_id: crypto.randomUUID(),
      expected_request_version: request.version,
      expected_plan_version: plan?.version,
      text_values: textValues,
      artifact_ids: artifactIds,
      advance,
    })
  }

  const renderField = (field: SkillInputRequestResponse['item']['fields'][number]) => {
    const fieldArtifacts = artifactsByField.get(field.id) ?? []
    const fieldError = field.error_codes?.map((code) => ERROR_LABELS[code] ?? code).join('；')
    return (
      <div key={field.id} className="rounded-soft border border-white/[0.07] bg-base/55 p-3.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <label htmlFor={`skill-input-${field.id}`} className="text-sm font-semibold text-slate-200">
            {field.title}
            <span className={field.required ? 'ml-2 text-xs text-amber-300' : 'ml-2 text-xs text-slate-500'}>
              {field.required ? '必填' : '可选'}
            </span>
          </label>
          <span className="text-[11px] text-slate-500">${field.skill_name}</span>
        </div>
        {field.description ? <p className="mt-1 text-xs leading-5 text-slate-400">{field.description}</p> : null}
        {field.value_kind === 'text' ? (
          field.options?.length ? (
            <select
              id={`skill-input-${field.id}`}
              value={textValues[field.id] ?? ''}
              disabled={pendingAction !== null}
              onChange={(event) => {
                dirtyTextFields.current.add(field.id)
                setTextValues((current) => ({ ...current, [field.id]: event.target.value }))
              }}
              className="mt-3 min-h-10 w-full rounded-control border border-white/[0.09] bg-surface-1 px-3 text-sm text-slate-100 outline-none focus:border-mint-400/45"
            >
              <option value="">请选择</option>
              {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          ) : (
            <textarea
              id={`skill-input-${field.id}`}
              value={textValues[field.id] ?? ''}
              maxLength={field.max_length ?? undefined}
              disabled={pendingAction !== null}
              onChange={(event) => {
                dirtyTextFields.current.add(field.id)
                setTextValues((current) => ({ ...current, [field.id]: event.target.value }))
              }}
              className="mt-3 min-h-24 w-full resize-y rounded-control border border-white/[0.09] bg-surface-1 px-3 py-2 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-500 focus:border-mint-400/45"
              placeholder={field.description || `请填写${field.title}`}
            />
          )
        ) : (
          <div className="mt-3 space-y-2">
            <label className="inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-control border border-white/[0.1] bg-surface-1 px-3 text-xs font-semibold text-slate-200 hover:bg-white/[0.05]">
              <Upload className="h-3.5 w-3.5 text-mint-300" aria-hidden="true" />
              选择文件
              <input
                id={`skill-input-${field.id}`}
                type="file"
                className="sr-only"
                accept={acceptedExtensions(field.accepted_media_types ?? [])}
                multiple={field.multiple}
                disabled={pendingAction !== null}
                onChange={(event) => {
                  for (const file of Array.from(event.target.files ?? [])) onUpload(field.id, file)
                  event.currentTarget.value = ''
                }}
              />
            </label>
            <p className="text-[11px] text-slate-500">
              支持 {(field.accepted_media_types ?? []).join('、')}
              {field.max_items ? `；最多 ${field.max_items} 个` : field.multiple ? '' : '；最多 1 个'}
              {field.required_columns?.length ? `；必需列：${field.required_columns.join('、')}` : ''}
            </p>
            {fieldArtifacts.length > 0 ? (
              <ul className="space-y-1.5">
                {fieldArtifacts.map((artifact) => {
                  const summary = artifactSummary(artifact)
                  return (
                  <li key={artifact.id} className="flex items-center gap-2 rounded-control bg-white/[0.04] px-2.5 py-2 text-xs">
                    <span className="text-mint-300">{artifactIcon(artifact)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-slate-300" title={artifact.file_name}>{artifact.file_name}</span>
                      {summary ? <span className="mt-0.5 block truncate text-[11px] text-slate-500">{summary}</span> : null}
                    </span>
                    <span className={artifact.status === 'ready' ? 'text-mint-300' : 'text-rose'}>
                      {artifact.status === 'ready' ? '已就绪' : ERROR_LABELS[artifact.error_code ?? ''] ?? '解析失败'}
                    </span>
                    <button
                      type="button"
                      aria-label={`删除 ${artifact.file_name}`}
                      disabled={pendingAction !== null}
                      onClick={() => onRemove(artifact.id)}
                      className="rounded-control p-1 text-slate-400 hover:bg-white/[0.06] hover:text-rose disabled:opacity-50"
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  </li>
                  )
                })}
              </ul>
            ) : null}
          </div>
        )}
        {field.value_kind === 'text' && (field.min_length != null || field.max_length != null) ? (
          <p className="mt-1 text-[11px] text-slate-500">
            长度限制：{field.min_length ?? 0}～{field.max_length ?? '不限'} 字
          </p>
        ) : null}
        {fieldError ? <p role="alert" className="mt-2 text-xs text-rose">{fieldError}</p> : null}
      </div>
    )
  }

  const requiredFields = fields.filter((field) => field.required)
  const optionalFields = fields.filter((field) => !field.required)
  const busy = pendingAction !== null

  return (
    <section aria-labelledby="skill-input-title" className="mt-6 rounded-soft border border-mint-400/20 bg-surface-1 p-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-mint-300">Skill input · v{request.version}</p>
          <h2 id="skill-input-title" className="mt-1 text-lg font-semibold text-slate-100">
            {plan ? '确认计划并补充资料' : '执行前需要补充资料'}
          </h2>
          <p className="mt-1 text-sm leading-6 text-slate-400">
            {plan
              ? '下列计划与必需资料将在一次确认后开始执行。'
              : '必需资料完成并通过服务端校验后才会执行 Skill。'}
          </p>
        </div>
        <span className="rounded-full bg-amber-300/10 px-3 py-1.5 text-xs font-medium text-amber-300">
          尚未执行任何节点
        </span>
      </div>

      {plan ? (
        <section aria-label="本次执行计划" className="mt-4 rounded-soft border border-white/[0.07] bg-base/55 p-3.5">
          <h3 className="text-xs font-semibold text-slate-300">本次执行计划 · v{plan.version}</h3>
          <ol className="mt-2 space-y-2">
            {(plan.nodes ?? []).map((node, index) => (
              <li key={node.id ?? `${node.skill_id}-${index}`} className="text-xs leading-5 text-slate-400">
                <span className="font-semibold text-slate-200">{index + 1}. {skillNames.get(node.skill_id) ?? node.skill_id}</span>
                <span> · {node.reason}</span>
                {(node.depends_on ?? []).length > 0 ? <span> · 依赖 {(node.depends_on ?? []).join('、')}</span> : null}
                <span> · {node.side_effect === 'read' ? '只读' : node.side_effect === 'draft' ? '生成草稿' : '包含写入'}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {error ? <p role="alert" className="mt-4 rounded-control bg-rose/10 px-3 py-2 text-xs text-rose">{error}</p> : null}
      <div className="mt-5 space-y-3">{requiredFields.map(renderField)}</div>
      {optionalFields.length > 0 ? (
        <details className="mt-4 rounded-soft border border-white/[0.06] bg-base/35 p-3.5">
          <summary className="cursor-pointer text-xs font-semibold text-slate-300">可选资料（不影响继续）</summary>
          <div className="mt-3 space-y-3">{optionalFields.map(renderField)}</div>
        </details>
      ) : null}

      <div aria-live="polite" className="mt-4 text-xs text-slate-400">
        {request.missing_required_field_ids.length > 0
          ? `仍有 ${request.missing_required_field_ids.length} 项必填资料需要补充`
          : '必填资料已填写，请提交服务端校验'}
      </div>
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <Button variant="danger" size="sm" disabled={busy} loading={pendingAction === 'cancel'} onClick={onCancel}>
          取消任务
        </Button>
        <Button variant="secondary" size="sm" disabled={busy} loading={pendingAction === 'submit'} onClick={() => submit(false)}>
          保存草稿
        </Button>
        <Button size="sm" disabled={busy} loading={pendingAction === 'submit'} onClick={() => submit(true)}>
          {plan ? '确认资料与计划，继续' : '资料齐全，继续'}
        </Button>
      </div>
    </section>
  )
}
