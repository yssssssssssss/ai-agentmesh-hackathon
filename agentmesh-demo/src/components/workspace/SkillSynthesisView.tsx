import { FileText, Link2, Sparkles, TriangleAlert } from 'lucide-react'

import type {
  CompletionCheckResult,
  Skill,
  SkillNodeResult,
  SkillResultSource,
  SkillSynthesisResult,
} from '../../features/workspace/types'

interface SkillSynthesisViewProps {
  synthesis: SkillSynthesisResult
  results: SkillNodeResult[]
  skillsById: ReadonlyMap<string, Skill>
  partial?: boolean
  completionCheck?: CompletionCheckResult | null
  onOpenSource: (source: SkillResultSource) => void
  onOpenArtifact: (artifactId: string) => void
}

export function SkillSynthesisView({
  synthesis,
  results,
  skillsById,
  partial = false,
  completionCheck,
  onOpenSource,
  onOpenArtifact,
}: SkillSynthesisViewProps) {
  const resultsById = new Map(results.map((result) => [result.id, result]))
  const sourcesById = new Map(
    results.flatMap((result) => (result.sources ?? []).map((source) => [source.id, source] as const)),
  )

  return (
    <section aria-labelledby="skill-synthesis-title" className="mt-6 rounded-[14px] bg-surface-1 p-5 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-mint-300" aria-hidden="true" />
          <h2 id="skill-synthesis-title" className="text-lg font-semibold text-slate-100">综合结果</h2>
        </div>
        <span className={partial ? 'text-xs font-medium text-amber-300' : 'text-xs font-medium text-mint-300'}>
          {partial ? 'Partial，部分节点降级' : '完整输出'}
        </span>
      </div>

      <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-slate-200">{synthesis.summary}</p>

      {(synthesis.sections ?? []).length > 0 ? (
        <div className="mt-5 space-y-3 border-t border-white/[0.06] pt-4">
          {synthesis.sections?.map((section, index) => (
            <p key={`${index}-${section.slice(0, 24)}`} className="whitespace-pre-wrap text-sm leading-6 text-slate-300">{section}</p>
          ))}
        </div>
      ) : null}

      {(synthesis.claims ?? []).length > 0 ? (
        <section className="mt-5 border-t border-white/[0.06] pt-4" aria-label="结论血缘">
          <h3 className="flex items-center gap-2 text-xs font-semibold text-slate-300">
            <Link2 className="h-3.5 w-3.5 text-mint-300" aria-hidden="true" />
            结论与血缘
          </h3>
          <ol className="mt-3 space-y-3">
            {synthesis.claims?.map((claim, index) => {
              const linkedResults = claim.node_result_ids.flatMap((resultId) => {
                const result = resultsById.get(resultId)
                return result ? [result] : []
              })
              const sourceIds = claim.source_ids ?? []
              return (
                <li key={`${index}-${claim.text.slice(0, 24)}`} className="rounded-[10px] bg-base px-3.5 py-3">
                  <p className="text-sm leading-6 text-slate-200">{claim.text}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                    {claim.recommendation ? <span className="rounded-full bg-knowledge/10 px-2 py-0.5 text-knowledge">建议</span> : null}
                    {linkedResults.map((result) => (
                      <span key={result.id} className="rounded-full bg-white/[0.05] px-2 py-0.5">
                        {skillsById.get(result.skill_id)?.title ?? result.skill_id}
                      </span>
                    ))}
                  </div>
                  {sourceIds.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {sourceIds.map((sourceId) => {
                        const source = sourcesById.get(sourceId)
                        return source ? (
                          <button
                            key={source.id}
                            type="button"
                            onClick={() => onOpenSource(source)}
                            className="flex min-h-10 items-center gap-1.5 rounded-[9px] bg-white/[0.04] px-2.5 text-[11px] text-slate-300 transition-[transform,background-color,color] duration-150 active:scale-95 hover:bg-white/[0.08] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
                          >
                            <FileText className="h-3.5 w-3.5" aria-hidden="true" />
                            {source.title}
                          </button>
                        ) : null
                      })}
                    </div>
                  ) : null}
                </li>
              )
            })}
          </ol>
        </section>
      ) : null}

      {completionCheck && !completionCheck.completed ? (
        <section className="mt-5 rounded-[10px] bg-amber-300/[0.07] px-3.5 py-3" aria-label="完成度检查">
          <h3 className="flex items-center gap-2 text-xs font-semibold text-amber-200">
            <TriangleAlert className="h-3.5 w-3.5" aria-hidden="true" />
            完成度检查
          </h3>
          {(completionCheck.missing_outputs ?? []).length > 0 ? (
            <p className="mt-2 text-xs leading-5 text-amber-100/80">
              缺少输出：{(completionCheck.missing_outputs ?? []).join('、')}
            </p>
          ) : null}
          {(completionCheck.gaps ?? []).length > 0 ? (
            <p className="mt-1 text-xs leading-5 text-amber-100/70">能力缺口：{(completionCheck.gaps ?? []).join('；')}</p>
          ) : null}
        </section>
      ) : null}

      {(synthesis.limitations ?? []).length > 0 ? (
        <section className="mt-5 rounded-[10px] bg-amber-300/[0.07] px-3.5 py-3" aria-label="限制">
          <h3 className="flex items-center gap-2 text-xs font-semibold text-amber-200">
            <TriangleAlert className="h-3.5 w-3.5" aria-hidden="true" />
            限制
          </h3>
          <ul className="mt-2 space-y-1 text-xs leading-5 text-amber-100/80">
            {synthesis.limitations?.map((limitation) => <li key={limitation}>• {limitation}</li>)}
          </ul>
        </section>
      ) : null}

      {(synthesis.next_actions ?? []).length > 0 ? (
        <section className="mt-5 border-t border-white/[0.06] pt-4" aria-label="下一步">
          <h3 className="text-xs font-semibold text-slate-300">下一步</h3>
          <ol className="mt-2 space-y-1.5 text-sm leading-6 text-slate-300">
            {synthesis.next_actions?.map((action, index) => <li key={action}>{index + 1}. {action}</li>)}
          </ol>
        </section>
      ) : null}

      {(synthesis.artifact_ids ?? []).length > 0 ? (
        <div className="mt-5 flex flex-wrap gap-2 border-t border-white/[0.06] pt-4">
          {synthesis.artifact_ids?.map((artifactId) => (
            <button
              key={artifactId}
              type="button"
              onClick={() => onOpenArtifact(artifactId)}
              className="min-h-10 rounded-[9px] bg-white/[0.04] px-3 text-xs text-slate-300 transition-[transform,background-color] duration-150 active:scale-95 hover:bg-white/[0.08]"
            >
              打开 Artifact · {artifactId}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  )
}
