import { useEffect, useRef, useState } from 'react'
import { BookOpen, BrainCircuit, CheckCircle2 } from 'lucide-react'

import { Button } from '../../components/ui/Button'
import { SectionCard } from '../../components/ui/Card'
import { EXPERIENCE_MOCK_RESULT, EXPERIENCE_MODELS } from './fixtures'
import type { ExperienceRecommendation } from './types'

const inputClass = 'mt-1.5 w-full rounded-[9px] border border-white/[0.08] bg-base px-3 py-2 text-sm text-slate-100 outline-none focus:border-mint-400/40'

function recommendations(preferred: string[], manual: string): ExperienceRecommendation[] {
  const preferredInCatalogOrder = EXPERIENCE_MODELS.filter((model) => preferred.includes(model.id)).map((model) => model.id)
  const ordered = [manual, ...preferredInCatalogOrder, ...EXPERIENCE_MOCK_RESULT.defaultModelIds].filter(Boolean)
  const unique = [...new Set(ordered)].slice(0, 3)
  return unique.map((modelId, index) => ({
    modelId,
    score: [0.94, 0.89, 0.84][index] ?? 0.8,
    reasons: EXPERIENCE_MOCK_RESULT.reasons[modelId] ?? ['由演示选择项加入推荐组合。'],
  }))
}

export function ExperienceModelMockPanel() {
  const [query, setQuery] = useState('')
  const [preferred, setPreferred] = useState<string[]>([])
  const [manualModel, setManualModel] = useState('')
  const [result, setResult] = useState<ExperienceRecommendation[] | null>(null)
  const resultRef = useRef<HTMLElement>(null)
  useEffect(() => {
    if (result) resultRef.current?.scrollIntoView({ block: 'start' })
  }, [result])

  const togglePreferred = (modelId: string) => {
    setPreferred((current) => current.includes(modelId) ? current.filter((id) => id !== modelId) : [...current, modelId])
  }
  const selectedModels = (result ?? [])
    .map((item) => EXPERIENCE_MODELS.find((model) => model.id === item.modelId))
    .filter((model) => model !== undefined)
  const selectedNames = selectedModels.map((model) => model.label)
  const summary = selectedNames.length
    ? `建议组合使用 ${selectedNames.join('、')} 回答当前研究问题，并把结论保持为可验证假设。`
    : EXPERIENCE_MOCK_RESULT.summary
  const frameworkSummary = selectedNames.length
    ? `${selectedNames.join(' + ')} 组成当前演示框架；各模型只提供方法视角，不代表真实调研结论。`
    : EXPERIENCE_MOCK_RESULT.frameworkSummary
  const questionTemplates = selectedModels.map((model) => `使用 ${model.label} 评估“${model.bestFor}”时，最需要验证的用户信号是什么？`)

  return (
    <div data-testid="experience-model-panel" className="grid gap-5 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.18fr)]">
      <div className="space-y-4">
        <div className="rounded-[12px] border border-amber-300/20 bg-amber-300/[0.07] px-4 py-3 text-xs leading-5 text-amber-100">
          <strong>Mock 演示：</strong>固定推荐样例，不代表实际研究结论。不会读取资料或发起网络请求。
        </div>
        <SectionCard title="研究问题" desc="描述要评估的体验目标或场景。" icon={<BrainCircuit className="h-4 w-4" />}>
          <label className="text-xs font-medium text-slate-400">
            研究问题
            <textarea
              aria-label="研究问题"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              rows={5}
              placeholder="例如：评估新版首页是否提升用户参与和任务成功率"
              className={`${inputClass} resize-none leading-6`}
            />
          </label>
        </SectionCard>

        <SectionCard title="偏好模型" desc="可选择多个方向，结果仍为确定性演示。">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {EXPERIENCE_MODELS.map((model) => (
              <label key={model.id} className="flex items-center gap-2 rounded-[9px] border border-white/[0.06] bg-base px-3 py-2 text-xs text-slate-300">
                <input type="checkbox" aria-label={model.label} checked={preferred.includes(model.id)} onChange={() => togglePreferred(model.id)} />
                {model.label}
              </label>
            ))}
          </div>
          <label className="mt-4 block text-xs font-medium text-slate-400">
            人工指定模型
            <select aria-label="人工指定模型" value={manualModel} onChange={(event) => setManualModel(event.target.value)} className={inputClass}>
              <option value="">不指定</option>
              {EXPERIENCE_MODELS.map((model) => <option key={model.id} value={model.id}>{model.resultLabel}</option>)}
            </select>
          </label>
        </SectionCard>

        <SectionCard title="模型目录" desc="仅展示内置方法名称和适用场景。" icon={<BookOpen className="h-4 w-4" />}>
          <div className="space-y-2">
            {EXPERIENCE_MODELS.map((model) => (
              <div key={model.id} className="rounded-[9px] border border-white/[0.06] bg-base p-3">
                <div className="flex items-center justify-between gap-3"><strong className="text-xs text-slate-200">{model.label}</strong><span className="text-[10px] text-slate-600">{model.bestFor}</span></div>
                <p className="mt-1 text-[11px] leading-5 text-slate-500">{model.description}</p>
              </div>
            ))}
          </div>
        </SectionCard>
        <Button type="button" block size="lg" disabled={!query.trim()} onClick={() => setResult(recommendations(preferred, manualModel))}>
          生成演示推荐
        </Button>
      </div>

      <div className="min-w-0 space-y-4" aria-live="polite">
        {result ? (
          <>
            <section ref={resultRef} className="rounded-[14px] border border-mint-400/20 bg-mint-400/[0.06] p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mint-300">Mock output</p>
              <h3 className="mt-1 text-xl font-semibold text-white">推荐结果</h3>
              <p data-testid="experience-summary" className="mt-3 text-sm leading-6 text-slate-300">{summary}</p>
            </section>

            <SectionCard title="推荐模型" icon={<CheckCircle2 className="h-4 w-4" />}>
              <div className="grid gap-3 md:grid-cols-3">
                {result.map((item) => {
                  const model = EXPERIENCE_MODELS.find((option) => option.id === item.modelId)
                  if (!model) return null
                  return (
                    <article key={item.modelId} className="rounded-[11px] border border-mint-400/15 bg-base p-4">
                      <div className="flex items-center justify-between gap-2"><h4 data-testid="recommended-model-name" className="text-sm font-semibold text-slate-100">{model.resultLabel}</h4><span className="text-xs font-semibold text-mint-300">{Math.round(item.score * 100)}%</span></div>
                      <ul className="mt-3 space-y-2 text-xs leading-5 text-slate-400">{item.reasons.map((reason) => <li key={reason}>• {reason}</li>)}</ul>
                    </article>
                  )
                })}
              </div>
            </SectionCard>
            <SectionCard title="框架总结"><p className="text-sm leading-6 text-slate-300">{frameworkSummary}</p></SectionCard>
            <SectionCard title="研究问题模板">
              <ol className="space-y-3">
                {questionTemplates.map((question, index) => (
                  <li data-testid="question-template" key={question} className="flex gap-3 rounded-[9px] bg-base px-3 py-2.5 text-sm leading-6 text-slate-300"><span className="font-semibold text-mint-300">{index + 1}</span>{question}</li>
                ))}
              </ol>
            </SectionCard>
            <div className="grid gap-4 lg:grid-cols-2">
              <SectionCard title="方法资料索引" icon={<BookOpen className="h-4 w-4" />}>
                <ul className="space-y-2 text-xs text-slate-400">{selectedModels.map((model) => <li key={model.id} className="rounded-[8px] bg-base px-3 py-2">{model.resultLabel}方法资料（Mock）</li>)}</ul>
              </SectionCard>
              <SectionCard title="边界说明">
                <ul className="space-y-2 text-xs leading-5 text-slate-400">{[...EXPERIENCE_MOCK_RESULT.warnings, ...EXPERIENCE_MOCK_RESULT.boundaryNotes].map((note) => <li key={note}>• {note}</li>)}</ul>
              </SectionCard>
            </div>
          </>
        ) : (
          <div className="flex min-h-[420px] items-center justify-center rounded-[14px] border border-dashed border-white/[0.1] bg-surface-1/50 px-6 text-center">
            <div><BrainCircuit className="mx-auto h-7 w-7 text-slate-600" aria-hidden="true" /><p className="mt-3 text-sm text-slate-400">填写研究问题并生成固定推荐样例</p><p className="mt-1 text-xs text-slate-600">不会调用模型、后端或资料检索。</p></div>
          </div>
        )}
      </div>
    </div>
  )
}
