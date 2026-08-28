import { CheckCircle2, FileCheck2, Link2, Loader2, ShieldCheck, TriangleAlert } from 'lucide-react'

import { MarkdownContent } from '../../components/ui/MarkdownContent'
import { ReportActions } from '../../components/workspace/ReportActions'
import { cn } from '../../lib/cn'
import { deepSearchFinalizationLabel } from './presentation'
import type {
  DeepSearchEvidenceCoverage,
  DeepSearchFinalizationStage,
  DeepSearchReport,
  DeepSearchReportReview,
} from './types'

interface DeepSearchEvidenceStatusProps {
  finalizationStage?: DeepSearchFinalizationStage
  coverage: DeepSearchEvidenceCoverage | null
  review: DeepSearchReportReview | null
  sourceCount: number
  terminal: boolean
}

const REVIEW_LABEL: Record<DeepSearchReportReview['outcome'], string> = {
  not_run: '未执行语义审核',
  pass: '审核通过',
  revise: '需要一次修订',
  block: '审核阻断',
  error: '审核未完成',
}

function Ratio({ covered, total }: { covered: number; total: number }) {
  const percentage = total === 0 ? 0 : Math.round((covered / total) * 100)
  return (
    <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]" aria-label={`覆盖 ${covered}/${total}`}>
      <span className="block h-full rounded-full bg-mint-400 transition-[width] duration-500 motion-reduce:transition-none" style={{ width: `${percentage}%` }} />
    </div>
  )
}

export function DeepSearchEvidenceStatus({
  finalizationStage,
  coverage,
  review,
  sourceCount,
  terminal,
}: DeepSearchEvidenceStatusProps) {
  const finalizationDone = finalizationStage === 'terminal_committed'
  const reviewing = !terminal && finalizationStage !== undefined && finalizationStage !== 'none'

  return (
    <section aria-labelledby="deepsearch-evidence-title" className="mt-4 rounded-soft bg-surface-1 px-5 py-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-mint-300">Evidence / Review</p>
          <h2 id="deepsearch-evidence-title" className="mt-1.5 text-lg font-semibold text-slate-100">
            {deepSearchFinalizationLabel(finalizationStage)}
          </h2>
        </div>
        <span className={cn(
          'inline-flex items-center gap-1.5 text-xs font-medium',
          finalizationDone ? 'text-mint-300' : 'text-slate-400',
        )}>
          {reviewing ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />}
          {finalizationDone ? '已完成终态提交' : '服务端门禁'}
        </span>
      </div>

      <div className="mt-5 grid gap-5 border-t border-white/[0.06] pt-4 sm:grid-cols-3">
        <div>
          <p className="text-[11px] text-slate-400">已归一化来源</p>
          <p className="mt-1 text-xl font-semibold text-slate-100">{sourceCount}</p>
          <p className="mt-1 text-[11px] leading-4 text-slate-400">来源数量本身不代表 Evidence 充分</p>
        </div>
        <div>
          <p className="text-[11px] text-slate-400">问题覆盖</p>
          <p className="mt-1 text-xl font-semibold text-slate-100">
            {coverage ? `${coverage.covered_question_ids.length}/${coverage.required_question_ids.length}` : '—'}
          </p>
          {coverage ? <Ratio covered={coverage.covered_question_ids.length} total={coverage.required_question_ids.length} /> : null}
        </div>
        <div>
          <p className="text-[11px] text-slate-400">成功标准覆盖</p>
          <p className="mt-1 text-xl font-semibold text-slate-100">
            {coverage ? `${coverage.covered_success_criterion_ids.length}/${coverage.required_success_criterion_ids.length}` : '—'}
          </p>
          {coverage ? <Ratio covered={coverage.covered_success_criterion_ids.length} total={coverage.required_success_criterion_ids.length} /> : null}
        </div>
      </div>

      {coverage ? (
        <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
          <span className={cn(
            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1',
            coverage.passed ? 'bg-mint-400/10 text-mint-300' : 'bg-amber-300/10 text-amber-200',
          )}>
            {coverage.passed ? <CheckCircle2 className="h-3 w-3" aria-hidden="true" /> : <TriangleAlert className="h-3 w-3" aria-hidden="true" />}
            {coverage.passed ? '确定性覆盖检查通过' : '存在 Evidence 缺口'}
          </span>
          <span className="rounded-full bg-white/[0.05] px-2.5 py-1 text-slate-400">
            可信结论 {coverage.validated_claim_ids.length}
          </span>
          {coverage.invalid_claim_ids.length > 0 ? (
            <span className="rounded-full bg-rose/10 px-2.5 py-1 text-rose">已排除结论 {coverage.invalid_claim_ids.length}</span>
          ) : null}
        </div>
      ) : (
        <p className="mt-4 text-xs leading-5 text-slate-400">节点完成后，系统会封存 Evidence Manifest，再检查每条结论的证据覆盖。</p>
      )}

      {review ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4">
          <div className="flex items-center gap-2 text-xs text-slate-300">
            <FileCheck2 className="h-4 w-4 text-mint-300" aria-hidden="true" />
            Report Review · {REVIEW_LABEL[review.outcome]}
          </div>
          <span className="text-[11px] text-slate-400">
            revision {review.revision_count}{review.reason_code ? ` · ${review.reason_code}` : ''}
          </span>
        </div>
      ) : null}

      {coverage?.gap_codes.length ? (
        <details className="mt-4 text-[11px] text-slate-400">
          <summary className="cursor-pointer hover:text-slate-300">查看覆盖缺口</summary>
          <ul className="mt-2 space-y-1 font-mono text-[11px]">
            {coverage.gap_codes.map((code) => <li key={code}>{code}</li>)}
          </ul>
        </details>
      ) : null}
    </section>
  )
}

interface DeepSearchReportViewProps {
  report: DeepSearchReport
  reportRunId?: string
}

function safeSourceHref(reference: string): string | undefined {
  try {
    const url = new URL(reference)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : undefined
  } catch {
    return undefined
  }
}

export function DeepSearchReportView({ report, reportRunId }: DeepSearchReportViewProps) {
  return (
    <article aria-labelledby="deepsearch-report-title" className="mt-4 overflow-hidden rounded-soft border border-mint-400/15 bg-surface-1 shadow-card">
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 py-5">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-mint-300">Sealed report</p>
          <h2 id="deepsearch-report-title" className="mt-1.5 text-xl font-semibold text-slate-100">{report.title}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn(
            'rounded-full px-3 py-1.5 text-xs font-semibold',
            report.report_status === 'complete'
              ? 'bg-mint-400/10 text-mint-300'
              : 'bg-amber-300/10 text-amber-200',
          )}>
            {report.report_status === 'complete' ? '完整报告' : '部分报告'}
          </span>
          {reportRunId ? <ReportActions runId={reportRunId} /> : null}
        </div>
      </header>

      <div className="border-t border-white/[0.06] px-5 py-5">
        <MarkdownContent content={report.rendered_text} className="[&_h1:first-child]:hidden" />
      </div>

      {report.sources.length > 0 ? (
        <section aria-labelledby="deepsearch-report-sources" className="border-t border-white/[0.06] px-5 py-4">
          <h3 id="deepsearch-report-sources" className="flex items-center gap-2 text-xs font-semibold text-slate-300">
            <Link2 className="h-3.5 w-3.5 text-mint-300" aria-hidden="true" />
            报告引用 · {report.sources.length}
          </h3>
          <ol className="mt-3 space-y-2 text-xs">
            {report.sources.map((source, index) => {
              const href = safeSourceHref(source.normalized_reference)
              return (
                <li key={source.source_id} className="flex items-start gap-2 text-slate-400">
                  <span className="font-mono text-slate-400">[{index + 1}]</span>
                  <div className="min-w-0">
                    {href ? (
                      <a href={href} target="_blank" rel="noreferrer" className="break-words text-slate-200 hover:text-mint-300">
                        {source.title}
                      </a>
                    ) : <span className="text-slate-200">{source.title}</span>}
                    <p className="mt-0.5 break-all text-[11px] text-slate-400">{source.normalized_reference}</p>
                  </div>
                </li>
              )
            })}
          </ol>
        </section>
      ) : null}
    </article>
  )
}
