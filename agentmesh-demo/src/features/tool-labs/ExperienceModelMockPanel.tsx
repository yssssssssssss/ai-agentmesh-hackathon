import { useState } from 'react'
import { BookOpen, BrainCircuit } from 'lucide-react'

import { Button } from '../../components/ui/Button'
import { SectionCard } from '../../components/ui/Card'
import { CaseStudyFigure } from './CaseStudyFigure'
import { ExperienceModelResultPage } from './ExperienceModelResultPage'
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

  if (result) {
    return (
      <ExperienceModelResultPage
        query={query}
        result={result}
        selectedModels={selectedModels}
        summary={summary}
        frameworkSummary={frameworkSummary}
        questionTemplates={questionTemplates}
        onBack={() => setResult(null)}
      />
    )
  }

  return (
    <div data-testid="experience-model-panel" className="grid gap-5 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.18fr)]">
      <div className="space-y-4">
        <div className="rounded-[12px] border border-amber-300/20 bg-amber-300/[0.07] px-4 py-3 text-xs leading-5 text-amber-100">
          <strong>示例演示：</strong>固定推荐样例，不代表实际研究结论。不会读取资料或发起网络请求。
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
        <CaseStudyFigure
          alt={EXPERIENCE_MOCK_RESULT.caseStudy.imageAlt}
          regions={[]}
        />
        <SectionCard title="将生成的研究框架" desc="结果会围绕当前截图生成研究假设，不代表真实调研结论。">
          <ul className="space-y-2 text-sm leading-6 text-slate-300">
            <li>• 推荐 HEART、GSM、认知负荷等模型组合</li>
            <li>• 回显当前研究问题和案例场景</li>
            <li>• 输出体验假设、GSM 指标拆解和 HEART 指标建议</li>
            <li>• 给出可用于访谈、可用性测试或 A/B 实验的问题模板</li>
          </ul>
        </SectionCard>
      </div>
    </div>
  )
}
