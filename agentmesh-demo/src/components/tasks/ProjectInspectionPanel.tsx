import { useMutation } from '@tanstack/react-query'

import { taskManagementApi } from '../../features/tasks/api'
import { taskManagementErrorMessage } from '../../features/tasks/queries'
import type { InspectionTemplate, ProjectInspectionReport } from '../../features/tasks/types'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'

export const TEMPLATES: Record<InspectionTemplate, string> = {
  daily_progress: '每日进展', blockers: '阻塞与逾期', pending_reviews: '待审核',
}
const OUTCOMES = {
  completed: '巡检完成', no_change: '没有变化', insufficient_evidence: '资料不足',
}
const CHANGE_LABELS = {
  created: '新建', updated: '更新', completed: '完成', reopened: '重新打开',
  blocked: '阻塞', unblocked: '解除阻塞', pending_review: '提交审核', archived: '归档',
}
const REASON_LABELS = {
  blocked: '已阻塞', dependency: '等待依赖', overdue: '已逾期', stale: '7 天未更新',
}
const SOURCE_LABELS: Record<string, string> = {
  tasks: '任务', task_reviews: '交付审核', memory_reviews: '分配给我的记忆审核',
}
const MISSING_LABELS: Record<string, string> = {
  no_shared_project_tasks: '项目还没有可供巡检的共享任务。',
  project_task_limit_exceeded: '任务数量超过单次巡检范围，请缩小项目范围。',
  project_review_limit_exceeded: '审核记录超过单次巡检范围。',
  task_history_limit_exceeded: '任务历史超过单次巡检范围。',
  task_history_incomplete: '部分任务缺少完整变更历史，无法判断其历史变化。',
  task_relationship_evidence_unavailable: '部分任务关系不可用，无法核对全部依赖。',
  task_review_subject_changed: '部分任务在提交审核后已改变，请核对最新版本。',
  memory_review_subject_changed: '部分记忆在提交审核后已改变，请核对最新版本。',
  inspection_history_window_truncated: '距上次完整巡检已超过一年，本次仅核对最近一年的记录。',
}
const DATE_FORMAT = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
})
function formatDate(value: string): string {
  return DATE_FORMAT.format(new Date(value))
}

interface InspectionViewProps {
  report?: ProjectInspectionReport
  loading: boolean
  error: string | null
  onInspect?: (template: InspectionTemplate) => void
}

export function ProjectInspectionView({ report, loading, error, onInspect }: InspectionViewProps) {
  const changes = report?.changes ?? []
  const blockers = report?.blockers ?? []
  const reviews = report?.pending_reviews ?? []
  return (
    <section aria-label="项目巡检" aria-busy={loading} className="rounded-soft border border-white/[0.08] bg-surface-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">项目巡检</h2>
          <p className="mt-1 text-xs text-slate-400">基于项目任务与审核记录，查询不会更改任务。</p>
        </div>
        {onInspect ? <div className="flex flex-wrap gap-2">
          {Object.entries(TEMPLATES).map(([template, label]) => (
            <Button key={template} size="sm" variant="subtle" disabled={loading}
              onClick={() => onInspect(template as InspectionTemplate)}>{label}</Button>
          ))}
        </div> : null}
      </div>
      {loading ? <p role="status" className="mt-3 text-sm text-slate-400">正在核对项目记录…</p> : null}
      {error ? <p role="alert" className="mt-3 text-sm text-rose">{error}</p> : null}
      {report && !loading && !error ? (
        <div className="mt-4 space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2" role="status">
            <Badge tone="mint">真实项目数据</Badge>
            <Badge tone={report.outcome === 'insufficient_evidence' ? 'remind' : 'neutral'}>{OUTCOMES[report.outcome]}</Badge>
            <span className="text-xs text-slate-400">{TEMPLATES[report.template_id]} · {formatDate(report.snapshot_at)}</span>
          </div>
          {(report.missing_data ?? []).length ? (
            <ul className="space-y-1 rounded-lg bg-remind/10 p-3 text-xs text-remind">
              {(report.missing_data ?? []).map((code) => <li key={code}>{MISSING_LABELS[code] ?? '部分资料无法读取，请核对项目记录。'}</li>)}
            </ul>
          ) : null}
          {changes.length ? <div>
            <h3 className="mb-2 font-medium text-slate-200">进展变化（{changes.length}）</h3>
            <ul className="space-y-2">{changes.slice(0, 50).map((item) => <li key={`${item.task_id}:${item.version}`}>
              <a href={item.navigation_href} className="text-mint-300 hover:underline">{item.title}</a>
              <span className="ml-2 text-xs text-slate-400">{CHANGE_LABELS[item.kind]} · {formatDate(item.occurred_at)} · v{item.version}</span>
            </li>)}</ul>
          </div> : null}
          {blockers.length ? <div>
            <h3 className="mb-2 font-medium text-slate-200">需关注的任务（{blockers.length}）</h3>
            <ul className="space-y-2">{blockers.slice(0, 50).map((item) => <li key={item.task_id} className="rounded-lg bg-white/[0.03] p-3">
              <a href={item.navigation_href} className="text-mint-300 hover:underline">{item.title}</a>
              <span className="ml-2 text-xs text-remind">{item.reasons.map((reason) => REASON_LABELS[reason]).join(' · ')}</span>
              {item.blocked_reason ? <p className="mt-1 text-xs text-slate-400">{item.blocked_reason}</p> : null}
              {item.due_at ? <p className="mt-1 text-xs text-slate-400">截止：{formatDate(item.due_at)}</p> : null}
            </li>)}</ul>
          </div> : null}
          {reviews.length ? <div>
            <h3 className="mb-2 font-medium text-slate-200">待审核事项（{reviews.length}）</h3>
            <ul className="space-y-2">{reviews.slice(0, 50).map((item) => <li key={item.review_id}>
              <a href={item.navigation_href} className="text-mint-300 hover:underline">{item.title}</a>
              <span className="ml-2 text-xs text-slate-400">{item.kind === 'task_review' ? '交付审核' : '记忆审核'} · {item.assigned_to_me ? '分配给我' : '由项目审核人处理'}</span>
            </li>)}</ul>
          </div> : null}
          {[changes, blockers, reviews].some((items) => items.length > 50) ? <p className="text-xs text-slate-400">各类结果仅显示前 50 项，请在任务列表查看其他事项。</p> : null}
          <details className="text-xs text-slate-400">
            <summary className="cursor-pointer py-1">来源记录与查询范围</summary>
            <p className="mt-2">{formatDate(report.since)} — {formatDate(report.snapshot_at)}</p>
            <ul className="mt-2 space-y-1">{Object.entries(report.source_watermarks).map(([source, watermark]) => <li key={source}>
              {SOURCE_LABELS[source] ?? '项目记录'}：{watermark.record_count} 条{watermark.latest_updated_at ? ` · 最近更新 ${formatDate(watermark.latest_updated_at)}` : ''}
            </li>)}</ul>
            <p className="mt-2">操作前请打开来源详情核对当前版本。</p>
          </details>
        </div>
      ) : null}
    </section>
  )
}

export function ProjectInspectionPanel({ projectId }: { projectId: string }) {
  const inspection = useMutation({
    mutationFn: (template: InspectionTemplate) => taskManagementApi.inspect(projectId, { template_id: template }),
  })
  return <ProjectInspectionView
    report={inspection.data?.project_id === projectId ? inspection.data : undefined}
    loading={inspection.isPending}
    error={inspection.error ? taskManagementErrorMessage(inspection.error) : null}
    onInspect={(template) => inspection.mutate(template)}
  />
}
