import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Clipboard, Eye, ScanLine, Target } from 'lucide-react'

import { Button } from '../../components/ui/Button'
import { SectionCard } from '../../components/ui/Card'
import { CaseStudyFigure } from './CaseStudyFigure'
import type { AestheticDepth, AestheticMockResult, AestheticProfile, ToolCaseMetric } from './types'

interface AestheticQuantResultPageProps {
  result: AestheticMockResult
  profile: AestheticProfile
  depth: AestheticDepth
  enableAttention: boolean
  attentionIncluded: boolean
  roiCount: number
  onBack: () => void
}

const PROFILE_LABELS: Record<AestheticProfile, string> = {
  balanced: '平衡模式',
  readability_first: '可读性优先',
  marketing_impact: '营销冲击力',
}

const DEPTH_LABELS: Record<AestheticDepth, string> = {
  lite: '快速',
  standard: '标准',
  deep: '深度',
}

function MetricRow({ metric }: { metric: ToolCaseMetric }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-100">{metric.label}</p>
          <p className="mt-0.5 text-xs leading-5 text-slate-400">{metric.note}</p>
        </div>
        <span className="shrink-0 font-mono text-lg font-semibold text-mint-300">{metric.value}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
        <div className="h-full rounded-full bg-mint-400" style={{ width: metric.value + '%' }} />
      </div>
    </div>
  )
}

function BulletList({ items }: { items: string[] }) {
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

export function AestheticQuantResultPage({
  result,
  profile,
  depth,
  enableAttention,
  attentionIncluded,
  roiCount,
  onBack,
}: AestheticQuantResultPageProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const displayedScore = result.overallScore + (attentionIncluded ? 2 : 0)
  const visibleMetrics = enableAttention
    ? result.caseStudy.metrics
    : result.caseStudy.metrics.filter((metric) => metric.label !== '注意力聚焦')
  const visibleFindings = enableAttention
    ? result.findings
    : result.findings.filter((finding) => !finding.includes('注意力'))
  const copyText = [
    `【美学量化示例】${result.caseStudy.title}`,
    `综合分：${displayedScore} / 100`,
    result.summary,
    '主要发现：',
    ...visibleFindings.map((item) => `- ${item}`),
    '优化建议：',
    ...result.recommendations.map((item) => `- ${item}`),
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
    <div ref={rootRef} tabIndex={-1} className="space-y-5 focus:outline-none" data-testid="aesthetic-result-page">
      <section className="rounded-overlay border border-mint-400/20 bg-mint-400/[0.055] p-5">
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
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mint-300">示例输出</p>
            <h3 className="mt-1 text-xl font-semibold text-white">演示结果</h3>
            <h4 className="mt-2 text-2xl font-semibold tracking-tight text-white">{result.caseStudy.title}</h4>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">{result.summary}</p>
          </div>
          <div className="rounded-soft border border-mint-400/20 bg-base px-5 py-4 text-right">
            <p className="text-xs text-slate-400">综合分 {displayedScore}</p>
            <p className="mt-1 font-mono text-4xl font-semibold text-mint-300">{displayedScore}</p>
            <p className="mt-1 text-[11px] text-slate-400">置信度 {result.confidence.level} · {result.confidence.score}</p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-slate-400">
          <span className="rounded-full bg-white/[0.05] px-2.5 py-1">{PROFILE_LABELS[profile]}</span>
          <span className="rounded-full bg-white/[0.05] px-2.5 py-1">{DEPTH_LABELS[depth]}</span>
          <span className="rounded-full bg-white/[0.05] px-2.5 py-1">ROI {roiCount}</span>
          <span className="rounded-full bg-white/[0.05] px-2.5 py-1">{attentionIncluded ? '注意力已计入演示总分' : '注意力未计入演示总分'}</span>
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(280px,0.72fr)_minmax(0,1.28fr)]">
        <CaseStudyFigure
          alt={result.caseStudy.imageAlt}
          regions={result.caseStudy.regions}
          showHeatmap={enableAttention}
          className="xl:sticky xl:top-0 xl:self-start"
        />
        <div className="min-w-0 space-y-4">
          <SectionCard title="案例信息" icon={<ScanLine className="h-4 w-4" />}>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div className="rounded-soft bg-base px-3 py-2.5">
                <dt className="text-xs text-slate-400">页面类型</dt>
                <dd className="mt-1 text-slate-200">{result.caseStudy.pageType}</dd>
              </div>
              <div className="rounded-soft bg-base px-3 py-2.5">
                <dt className="text-xs text-slate-400">核心场景</dt>
                <dd className="mt-1 text-slate-200">{result.caseStudy.scenario}</dd>
              </div>
            </dl>
          </SectionCard>

          <SectionCard title="结构化指标">
            <div className="grid gap-4 lg:grid-cols-2">
              {visibleMetrics.map((metric) => <MetricRow key={metric.label} metric={metric} />)}
            </div>
          </SectionCard>

          <SectionCard title="ROI 结果" icon={<Target className="h-4 w-4" />}>
            <div className="grid gap-3 md:grid-cols-2">
              {result.caseStudy.regions.map((region) => (
                <article key={region.id} className="rounded-soft border border-white/[0.06] bg-base p-3">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="text-sm font-semibold text-slate-100">{region.label}</h4>
                    <span className="font-mono text-sm font-semibold text-mint-300">{region.score}</span>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-400">{region.note}</p>
                </article>
              ))}
            </div>
          </SectionCard>

          {enableAttention ? (
            <SectionCard title="注意力热点示意" icon={<Eye className="h-4 w-4" />}>
              <div className="grid gap-3 md:grid-cols-3">
                {result.caseStudy.attentionHotspots.map((hotspot) => (
                  <article key={hotspot.label} className="rounded-soft bg-base p-3">
                    <p className="text-[11px] text-slate-400">{hotspot.label}</p>
                    <p className="mt-1 text-sm font-semibold text-slate-100">{hotspot.value}</p>
                    <p className="mt-2 text-xs leading-5 text-slate-400">{hotspot.note}</p>
                  </article>
                ))}
              </div>
            </SectionCard>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="主要发现"><BulletList items={visibleFindings} /></SectionCard>
            <SectionCard title="优化建议"><BulletList items={result.recommendations} /></SectionCard>
          </div>

          <SectionCard title="边界说明">
            <BulletList items={[result.confidence.note, ...result.boundaryNotes]} />
          </SectionCard>

          <div className="flex flex-wrap justify-end gap-3">
            <Button type="button" variant="subtle" onClick={onBack} icon={<ArrowLeft className="h-4 w-4" />}>
              返回修改参数
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
