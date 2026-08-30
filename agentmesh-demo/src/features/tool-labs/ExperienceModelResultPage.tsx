import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, BrainCircuit, CheckCircle2, Clipboard, FlaskConical, HelpCircle, Route } from 'lucide-react'

import { Button } from '../../components/ui/Button'
import { SectionCard } from '../../components/ui/Card'
import { CaseStudyFigure } from './CaseStudyFigure'
import { EXPERIENCE_MOCK_RESULT } from './fixtures'
import type { ExperienceModelOption, ExperienceRecommendation } from './types'

interface ExperienceModelResultPageProps {
  query: string
  result: ExperienceRecommendation[]
  selectedModels: ExperienceModelOption[]
  summary: string
  frameworkSummary: string
  questionTemplates: string[]
  onBack: () => void
}

function TextList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-2 text-sm leading-6 text-slate-300">
      {items.map((item) => (
        <li key={item} className="flex gap-2">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-mint-300" aria-hidden="true" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  )
}

export function ExperienceModelResultPage({
  query,
  result,
  selectedModels,
  summary,
  frameworkSummary,
  questionTemplates,
  onBack,
}: ExperienceModelResultPageProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const caseStudy = EXPERIENCE_MOCK_RESULT.caseStudy
  const selectedNames = selectedModels.map((model) => model.label).join(' + ')
  const copyText = [
    '【体验模型示例】' + caseStudy.title,
    '推荐模型：' + selectedNames,
    summary,
    '研究问题：' + (query.trim() || caseStudy.question),
    '体验假设：',
    ...caseStudy.hypotheses.map((item) => '- ' + item),
  ].join('\n')

  useEffect(() => {
    const root = rootRef.current
    root?.focus({ preventScroll: true })
    root?.scrollIntoView({ block: 'start' })
  }, [])

  async function copySummary() {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(copyText)
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
  }

  return (
    <div ref={rootRef} tabIndex={-1} className="space-y-5 focus:outline-none" data-testid="experience-result-page">
      <section className="rounded-overlay border border-amber-300/20 bg-amber-300/[0.055] p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <button
              type="button"
              onClick={onBack}
              className="mb-4 inline-flex min-h-10 items-center gap-2 rounded-soft px-2.5 text-xs font-semibold text-slate-400 transition-colors hover:bg-white/[0.06] hover:text-slate-100 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              返回配置
            </button>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-200">示例输出</p>
            <h3 className="mt-1 text-xl font-semibold text-white">推荐结果</h3>
            <h4 className="mt-2 text-2xl font-semibold tracking-tight text-white">{caseStudy.title}</h4>
            <p data-testid="experience-summary" className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">{summary}</p>
          </div>
          <div className="rounded-soft border border-amber-300/20 bg-base px-5 py-4">
            <p className="text-xs text-slate-400">推荐组合</p>
            <p className="mt-2 text-lg font-semibold text-amber-100">{selectedNames}</p>
          </div>
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(280px,0.72fr)_minmax(0,1.28fr)]">
        <CaseStudyFigure
          alt={caseStudy.imageAlt}
          regions={caseStudy.regions}
          className="xl:sticky xl:top-0 xl:self-start"
        />
        <div className="min-w-0 space-y-4">
          <SectionCard title="研究问题" icon={<BrainCircuit className="h-4 w-4" />}>
            <div className="space-y-3">
              <p className="rounded-soft bg-base px-4 py-3 text-sm leading-6 text-slate-200">{query.trim() || caseStudy.question}</p>
              <p className="text-sm leading-6 text-slate-400">{caseStudy.scenario}</p>
            </div>
          </SectionCard>

          <SectionCard title="推荐模型" icon={<CheckCircle2 className="h-4 w-4" />}>
            <div className="grid gap-3 md:grid-cols-3">
              {result.map((item) => {
                const model = selectedModels.find((option) => option.id === item.modelId)
                if (!model) return null
                return (
                  <article key={item.modelId} className="rounded-soft border border-amber-300/15 bg-base p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h4 data-testid="recommended-model-name" className="text-sm font-semibold text-slate-100">{model.resultLabel}</h4>
                        <p className="mt-1 text-[11px] leading-5 text-slate-400">{model.bestFor}</p>
                      </div>
                      <span className="font-mono text-sm font-semibold text-amber-200">{Math.round(item.score * 100)}%</span>
                    </div>
                    <ul className="mt-3 space-y-2 text-xs leading-5 text-slate-400">
                      {item.reasons.map((reason) => <li key={reason}>• {reason}</li>)}
                    </ul>
                  </article>
                )
              })}
            </div>
          </SectionCard>

          <SectionCard title="框架总结" icon={<Route className="h-4 w-4" />}>
            <p className="text-sm leading-6 text-slate-300">{frameworkSummary}</p>
          </SectionCard>

          <SectionCard title="体验假设">
            <TextList items={caseStudy.hypotheses} />
          </SectionCard>

          <SectionCard title="GSM 指标拆解">
            <div className="space-y-3">
              {caseStudy.gsmGoals.map((item) => (
                <article key={item.goal} className="rounded-soft bg-base p-3">
                  <h4 className="text-sm font-semibold text-slate-100">{item.goal}</h4>
                  <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
                    <div><dt className="text-slate-400">信号</dt><dd className="mt-1 leading-5 text-slate-300">{item.signals}</dd></div>
                    <div><dt className="text-slate-400">指标</dt><dd className="mt-1 leading-5 text-slate-300">{item.metrics}</dd></div>
                  </dl>
                </article>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="HEART 指标建议">
            <div className="grid gap-2 md:grid-cols-2">
              {caseStudy.heartMetrics.map((item) => (
                <div key={item.dimension} className="rounded-soft bg-base px-3 py-2.5">
                  <p className="text-xs font-semibold text-amber-200">{item.dimension}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-400">{item.metrics}</p>
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="研究问题模板" icon={<HelpCircle className="h-4 w-4" />}>
            <ol className="space-y-3">
              {questionTemplates.map((question, index) => (
                <li data-testid="question-template" key={question} className="flex gap-3 rounded-soft bg-base px-3 py-2.5 text-sm leading-6 text-slate-300">
                  <span className="font-mono font-semibold text-mint-300">{index + 1}</span>
                  <span>{question}</span>
                </li>
              ))}
            </ol>
            <div className="mt-4 border-t border-white/[0.06] pt-4">
              <TextList items={caseStudy.researchQuestions} />
            </div>
          </SectionCard>

          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="建议实验" icon={<FlaskConical className="h-4 w-4" />}>
              <div className="space-y-2">
                {caseStudy.experiments.map((experiment) => (
                  <article key={experiment.name} className="rounded-soft bg-base px-3 py-2.5">
                    <h4 className="text-xs font-semibold text-slate-100">{experiment.name}</h4>
                    <p className="mt-1 text-xs leading-5 text-slate-400">{experiment.description}</p>
                  </article>
                ))}
              </div>
            </SectionCard>
            <SectionCard title="方法资料索引">
              <ul className="space-y-2 text-xs text-slate-400">
                {selectedModels.map((model) => <li key={model.id} className="rounded-control bg-base px-3 py-2">{model.resultLabel}方法资料（示例）</li>)}
              </ul>
            </SectionCard>
          </div>

          <SectionCard title="边界说明">
            <TextList items={[...EXPERIENCE_MOCK_RESULT.warnings, ...EXPERIENCE_MOCK_RESULT.boundaryNotes]} />
          </SectionCard>

          <div className="flex flex-wrap justify-end gap-3">
            <Button type="button" variant="subtle" onClick={onBack} icon={<ArrowLeft className="h-4 w-4" />}>
              返回修改问题
            </Button>
            <Button type="button" onClick={() => void copySummary()} icon={<Clipboard className="h-4 w-4" />}>
              {copyState === 'copied' ? '已复制摘要' : copyState === 'failed' ? '复制失败' : '复制报告摘要'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
