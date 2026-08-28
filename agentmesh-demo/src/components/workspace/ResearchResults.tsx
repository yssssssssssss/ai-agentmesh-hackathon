import { Check, ExternalLink, FileText, ShieldCheck, X } from 'lucide-react'

import type { ResearchRunProjection } from '../../features/workspace/types'
import { MarkdownContent } from '../ui/MarkdownContent'

const ARTIFACT_LABELS = {
  evidence_manifest_id: 'Evidence 清单',
  claim_ledger_id: 'Claim 证据账本',
  deliverable_id: '结构化 Deliverable',
  review_id: '确定性 Review',
  report_id: '最终 Report',
} as const

const CLAIM_TYPE_LABEL = {
  fact: '事实',
  inference: '推断',
  recommendation: '建议',
} as const

function artifactUrl(artifactId: string): string {
  return `/api/artifacts/${encodeURIComponent(artifactId)}`
}

function evidenceAnchor(evidenceId: string): string {
  return `research-evidence-${evidenceId}`
}

function withoutDuplicateLeadingTitle(markdown: string, title: string): string {
  const lines = markdown.trimStart().split(/\r?\n/)
  const heading = lines[0]?.match(/^#\s+(.+?)\s*#*$/)?.[1]?.trim()
  if (heading?.toLocaleLowerCase() !== title.trim().toLocaleLowerCase()) return markdown
  return lines.slice(1).join('\n').trimStart()
}

function EvidenceLinks({ evidenceIds }: { evidenceIds: string[] }) {
  if (evidenceIds.length === 0) return <span className="text-slate-400">无直接 Evidence</span>
  return (
    <span className="flex flex-wrap gap-1.5">
      {evidenceIds.map((evidenceId) => (
        <a
          key={evidenceId}
          href={`#${evidenceAnchor(evidenceId)}`}
          className="rounded-full bg-mint-400/10 px-2 py-1 font-mono text-[11px] text-mint-300 hover:bg-mint-400/20"
        >
          {evidenceId}
        </a>
      ))}
    </span>
  )
}

type ResultProjection = NonNullable<ResearchRunProjection['result']>
type ClaimProjection = NonNullable<ResultProjection['claims']>[number]

function ClaimList({ claims }: { claims: ClaimProjection[] }) {
  if (claims.length === 0) return null
  return (
    <ul className="mt-3 space-y-3">
      {claims.map((claim) => (
        <li key={claim.claim_id} id={`research-claim-${claim.claim_id}`} className="rounded-soft bg-base/60 p-4">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-semibold text-mint-300">{CLAIM_TYPE_LABEL[claim.claim_type]}</span>
            <span className="text-slate-400">{claim.confidence} confidence</span>
            {claim.conflict_status !== 'none' ? (
              <span className="rounded-full bg-amber-300/10 px-2 py-0.5 text-amber-100">
                {claim.conflict_status}
              </span>
            ) : null}
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-200">{claim.statement}</p>
          <div className="mt-3 text-xs">
            <EvidenceLinks evidenceIds={claim.evidence_ids ?? []} />
          </div>
        </li>
      ))}
    </ul>
  )
}

export function ResearchResults({ projection }: { projection: ResearchRunProjection }) {
  const completed = projection.status === 'completed'
  const integrityErrors = projection.integrity_errors ?? []
  const result = integrityErrors.length === 0 ? projection.result : undefined
  const evidence = result?.evidence ?? []
  const claims = result?.claims ?? []
  const deliverable = result?.deliverable
  const comparison = deliverable?.comparison ?? []
  const recommendations = deliverable?.recommendations ?? []
  const limitations = deliverable?.limitations ?? []
  const review = result?.review
  const reviewChecks = review?.checks ?? []
  const report = result?.report
  const artifacts = projection.artifacts ?? {}
  const artifactEntries = Object.entries(ARTIFACT_LABELS).flatMap(([key, label]) => {
    const id = artifacts[key as keyof typeof ARTIFACT_LABELS]
    if (key === 'report_id' && integrityErrors.length > 0) return []
    return id ? [{ id, label }] : []
  })
  const showResults = completed
    || artifactEntries.length > 0
    || (projection.gaps?.length ?? 0) > 0
    || evidence.length > 0
    || claims.length > 0
    || Boolean(deliverable || review || report)

  if (!showResults && integrityErrors.length === 0) return null

  return (
    <>
      {integrityErrors.length > 0 ? (
        <section role="alert" aria-labelledby="research-integrity-title" className="rounded-soft border border-rose/25 bg-rose/[0.08] p-5">
          <h3 id="research-integrity-title" className="text-sm font-semibold text-rose">结果完整性校验未通过</h3>
          <p className="mt-2 text-sm leading-6 text-slate-300">最终 Report 已隐藏；未通过校验的内容不会进入结果视图。</p>
          <details className="mt-3 text-xs text-slate-400">
            <summary className="cursor-pointer font-semibold">查看技术错误</summary>
            <ul className="mt-2 space-y-1 font-mono">
              {integrityErrors.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </details>
        </section>
      ) : null}

      {showResults ? (
        <section aria-labelledby="research-results-title" className="rounded-soft border border-white/[0.07] bg-surface-1 p-5 shadow-card">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-mint-300" aria-hidden="true" />
            <h3 id="research-results-title" className="text-sm font-semibold text-slate-100">研究结果</h3>
          </div>

          {review?.status === 'block' ? (
            <section role="alert" className="mt-4 rounded-soft border border-amber-300/20 bg-amber-300/[0.07] p-4">
              <h4 className="text-sm font-semibold text-amber-100">未通过审核的研究草稿</h4>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                当前内容仅供补证与修订，不能作为已审核通过的最终报告。
              </p>
              <ul className="mt-2 space-y-1 font-mono text-xs text-amber-100/80">
                {reviewChecks.filter((check) => !check.passed).map((check) => (
                  <li key={check.code}>• {check.code}</li>
                ))}
              </ul>
            </section>
          ) : null}

          {report ? (
            <article aria-labelledby="research-report-title" className="mt-4 rounded-soft border border-mint-400/15 bg-base/55 p-5">
              <h4 id="research-report-title" className="text-base font-semibold text-slate-100">{report.title}</h4>
              <MarkdownContent className="mt-4" content={withoutDuplicateLeadingTitle(report.markdown, report.title)} />
            </article>
          ) : completed && integrityErrors.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">本次运行未生成可展示的最终 Report。</p>
          ) : null}

          {deliverable ? (
            <details open className="mt-4 rounded-soft border border-white/[0.06] bg-base/45 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-100">结构化 Deliverable</summary>
              <p className="mt-3 text-sm leading-6 text-slate-300">{deliverable.summary}</p>
              {comparison.length > 0 ? (
                <div className="mt-4">
                  <p className="text-xs font-semibold text-slate-400">对比结论</p>
                  <ClaimList claims={comparison} />
                </div>
              ) : null}
              {recommendations.length > 0 ? (
                <div className="mt-4">
                  <p className="text-xs font-semibold text-slate-400">建议</p>
                  <ClaimList claims={recommendations} />
                </div>
              ) : null}
              {limitations.length > 0 ? (
                <div className="mt-4 rounded-soft bg-amber-300/[0.05] p-3">
                  <p className="text-xs font-semibold text-amber-100">局限</p>
                  <ul className="mt-2 space-y-1 text-sm text-slate-300">
                    {limitations.map((item) => <li key={item}>• {item}</li>)}
                  </ul>
                </div>
              ) : null}
            </details>
          ) : null}

          {claims.length > 0 ? (
            <details className="mt-4 rounded-soft border border-white/[0.06] bg-base/45 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-100">Claim 证据账本（{claims.length}）</summary>
              <ClaimList claims={claims} />
            </details>
          ) : null}

          {evidence.length > 0 ? (
            <section aria-labelledby="research-evidence-title" className="mt-4 rounded-soft border border-white/[0.06] bg-base/45 p-4">
              <h4 id="research-evidence-title" className="text-sm font-semibold text-slate-100">Evidence 来源片段</h4>
              <ul className="mt-3 space-y-3">
                {evidence.map((item) => (
                  <li key={item.evidence_id} id={evidenceAnchor(item.evidence_id)} className="scroll-mt-6 rounded-soft bg-surface-2 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-mint-300">{item.evidence_id}</span>
                      {item.conflict_status !== 'none' ? (
                        <span className="rounded-full bg-amber-300/10 px-2 py-0.5 text-[11px] text-amber-100">
                          {item.conflict_status}
                        </span>
                      ) : null}
                    </div>
                    <blockquote className="mt-3 border-l-2 border-mint-400/30 pl-3 text-sm leading-6 text-slate-300">
                      {item.quote}
                    </blockquote>
                    <ul className="mt-3 space-y-1.5">
                      {(item.sources ?? []).map((source) => (
                        <li key={source.source_id}>
                          <a
                            href={source.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs text-mint-300 hover:underline"
                          >
                            {source.title} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                          </a>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {(projection.gaps?.length ?? 0) > 0 ? (
            <div className="mt-4 rounded-soft border border-amber-300/15 bg-amber-300/[0.05] p-4">
              <p className="text-xs font-semibold text-amber-100">仍需补证的缺口</p>
              <ul className="mt-2 space-y-1 text-sm text-slate-300">
                {projection.gaps?.map((gap) => <li key={gap.code}>• {gap.message}</li>)}
              </ul>
            </div>
          ) : null}

          {review ? (
            <details className="mt-4 rounded-soft border border-white/[0.06] bg-base/45 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-100">
                确定性 Review · {review.status === 'pass' ? '通过' : '阻断'}
              </summary>
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                {reviewChecks.map((check) => (
                  <li key={check.code} className="flex items-center gap-2 text-xs text-slate-300">
                    {check.passed
                      ? <Check className="h-3.5 w-3.5 text-mint-300" aria-hidden="true" />
                      : <X className="h-3.5 w-3.5 text-rose" aria-hidden="true" />}
                    {check.code}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {artifactEntries.length > 0 ? (
            <details className="mt-4 rounded-soft border border-white/[0.06] bg-base/60 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-200">原始 Artifact 与审计标识</summary>
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                {artifactEntries.map((artifact) => (
                  <li key={artifact.id}>
                    <a
                      href={artifactUrl(artifact.id)}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center justify-between gap-2 rounded-soft bg-surface-2 px-3 py-2 text-xs text-mint-300 hover:bg-surface-3"
                    >
                      {artifact.label}
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    </a>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          <details className="mt-3 text-xs text-slate-400">
            <summary className="flex cursor-pointer items-center gap-1.5 font-semibold">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" /> 技术详情与 Provider provenance
            </summary>
            <dl className="mt-2 grid gap-2 sm:grid-cols-2">
              <div><dt>请求模型</dt><dd className="mt-0.5 break-all text-slate-300">{projection.provenance?.requested_model ?? '未记录'}</dd></div>
              <div><dt>实际模型</dt><dd className="mt-0.5 break-all text-slate-300">{projection.provenance?.actual_model ?? '尚未执行'}</dd></div>
              <div className="sm:col-span-2"><dt>Tool 实现</dt><dd className="mt-0.5 break-all font-mono text-slate-300">{projection.provenance?.tool_implementation_id ?? '未记录'}</dd></div>
            </dl>
          </details>
        </section>
      ) : null}
    </>
  )
}
