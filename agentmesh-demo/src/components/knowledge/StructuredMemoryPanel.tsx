import { Link } from 'react-router-dom'
import type { MemoryItem } from '../../features/knowledge/api'
import { procedureTaskDraft } from '../../features/tasks/procedureReuse'
import { DataSourceBadge } from '../ui/DataSourceBadge'

export type StructuredMemory = Pick<MemoryItem, 'facts' | 'procedure'>

const classifications = {
  human_confirmed: '人类确认',
  system_observation: '系统观察',
  model_inference: '模型推断，待确认',
}
const predicates: Record<string, string> = {
  owner: '负责人', participant: '参与人', constraint: '约束', status: '状态', decision: '决策', preference: '偏好',
}

function instant(value?: string | null) {
  if (!value) return '未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '未知' : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

function Items({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null
  return <div className="mt-3">
    <h4 className="text-xs text-slate-400">{label}</h4>
    <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-slate-300">
      {values.map((value, index) => <li className="break-words" key={index}>{value}</li>)}
    </ol>
  </div>
}

export function StructuredMemoryPanel({ memory, projectId, canReuse = false }: {
  memory: StructuredMemory; projectId?: string; canReuse?: boolean
}) {
  const { facts, procedure } = memory
  const taskDraft = canReuse && projectId && procedure ? procedureTaskDraft(projectId, procedure) : null
  if (!facts?.length && !procedure) return null
  return <section className="space-y-4" aria-label="结构化记忆">
    <p className="text-xs text-slate-400">事实查询会重新检查来源版本、有效时间和冲突。<DataSourceBadge source="T" /></p>
    {facts?.map((fact, index) => <article className="rounded-soft border border-white/10 bg-surface-1 p-3" key={index}>
      <h3 className="text-sm font-medium text-slate-200">{predicates[fact.predicate] ?? fact.predicate}</h3>
      <p className="mt-2 break-words text-sm text-slate-100">{fact.value}</p>
      <dl className="mt-3 space-y-2 text-xs text-slate-400">
        <div><dt className="inline">有效时间：</dt><dd className="inline">
          {fact.time_precision === 'unknown' ? '未知，待确认' : `${instant(fact.valid_from)} 至 ${fact.valid_to ? `${instant(fact.valid_to)}（不含结束时刻）` : '未指定结束时间'}`}
        </dd></div>
        <div><dt className="inline">记录时间：</dt><dd className="inline">{instant(fact.observed_at)}</dd></div>
        <div><dt className="inline">来源类别：</dt><dd className="inline">{classifications[fact.source_classification]}</dd></div>
      </dl>
      <ul className="mt-3 space-y-1 text-xs text-slate-500" aria-label="事实证据">
        {fact.evidence_refs.map((ref, refIndex) => <li className="break-all" key={refIndex}>
          {ref.record_type} · {ref.record_id} · v{ref.version} · {ref.content_hash.slice(0, 12)}
        </li>)}
      </ul>
    </article>)}
    {procedure ? <article className="rounded-soft border border-white/10 bg-surface-1 p-3">
      <h3 className="text-sm font-medium text-slate-200">{procedure.human_confirmed_by && procedure.successful_runs?.length ? '已记录验收引用' : '待确认经验'}</h3>
      <Items label="适用目标" values={procedure.goal_patterns} />
      <Items label="前置条件" values={procedure.preconditions ?? []} />
      <Items label="建议步骤" values={procedure.steps} />
      <Items label="验证条件" values={procedure.validation_conditions} />
      <Items label="工具版本" values={Object.entries(procedure.tool_versions ?? {}).map(([key, version]) => `${key}: ${version}`)} />
      <Items label="环境版本" values={Object.entries(procedure.environment_versions ?? {}).map(([key, version]) => `${key}: ${version}`)} />
      <Items label="验收 Run" values={(procedure.successful_runs ?? []).map((run) => `${run.run_id} · ${run.review_ref.record_id} v${run.review_ref.version}`)} />
      <Items label="失败 Run" values={procedure.failed_runs ?? []} />
      <p className="mt-3 text-xs text-slate-500">复用前需要核对当前前置条件、工具版本和验收证据。</p>
      {taskDraft ? <div className="mt-3 space-y-2">
        <Link className="text-sm text-mint-300 hover:underline"
          to={`/tasks?${new URLSearchParams({ project: taskDraft.projectId })}`} state={{ taskDraft }}>
          根据方法创建任务
        </Link>
        <p className="text-xs text-slate-400">带入适用目标作为可编辑草稿。保存和启动执行需要确认；执行时重新核对方法是否仍然适用。</p>
      </div> : null}
    </article> : null}
  </section>
}
