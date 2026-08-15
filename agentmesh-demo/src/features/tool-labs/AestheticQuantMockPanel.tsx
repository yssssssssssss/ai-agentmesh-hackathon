import { useEffect, useRef, useState } from 'react'
import { Eye, ImagePlus, Plus, Target, Trash2 } from 'lucide-react'

import { Button } from '../../components/ui/Button'
import { SectionCard } from '../../components/ui/Card'
import { AESTHETIC_MOCK_RESULT, DEFAULT_ROIS } from './fixtures'
import type { AestheticDepth, AestheticProfile, RoiInput } from './types'

const inputClass = 'mt-1.5 w-full rounded-[9px] border border-white/[0.08] bg-base px-3 py-2 text-sm text-slate-100 outline-none focus:border-mint-400/40'

function useObjectUrl(file: File | null) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!file) {
      setUrl(null)
      return
    }
    const nextUrl = URL.createObjectURL(file)
    setUrl(nextUrl)
    return () => URL.revokeObjectURL(nextUrl)
  }, [file])
  return url
}

function ImageInput({ label, file, onChange, previewUrl }: {
  label: string
  file: File | null
  onChange: (file: File | null) => void
  previewUrl?: string | null
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  return (
    <div className="rounded-[12px] border border-white/[0.07] bg-base/70 p-3">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        aria-label={label}
        tabIndex={-1}
        className="sr-only"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      {previewUrl ? (
        <img src={previewUrl} alt="设计图预览" className="mb-3 h-28 w-full rounded-[9px] border border-white/[0.08] object-cover" />
      ) : null}
      <Button type="button" variant="subtle" size="sm" block className="min-w-0 overflow-hidden" icon={<ImagePlus className="h-4 w-4" />} onClick={() => inputRef.current?.click()}>
        <span className="min-w-0 flex-1 truncate text-left">{file ? file.name : label}</span>
      </Button>
    </div>
  )
}

function RoiEditor({ rois, onChange }: { rois: RoiInput[]; onChange: (rois: RoiInput[]) => void }) {
  const nextId = useRef(1)
  const update = (id: string, field: keyof RoiInput, value: string | number) => {
    onChange(rois.map((roi) => (roi.id === id ? { ...roi, [field]: value } : roi)))
  }
  const add = () => {
    const index = rois.length + 1
    const id = `roi-user-${nextId.current++}`
    onChange([...rois, { id, label: `区域 ${index}`, x: 0.2, y: 0.2, width: 0.3, height: 0.2 }])
  }
  return (
    <SectionCard
      title="ROI 区域"
      desc="演示控件仅编辑归一化坐标，不执行真实图像计算。"
      icon={<Target className="h-4 w-4" />}
      action={<Button type="button" variant="subtle" size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={add}>添加 ROI</Button>}
    >
      <div className="space-y-3">
        {rois.map((roi, index) => (
          <div key={roi.id} className="rounded-[10px] border border-white/[0.06] bg-base p-3">
            <div className="flex items-center gap-2">
              <input
                aria-label={`ROI 名称 ${index + 1}`}
                value={roi.label}
                onChange={(event) => update(roi.id, 'label', event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-sm font-semibold text-slate-200 outline-none"
              />
              <button
                type="button"
                aria-label={`删除 ${roi.label}`}
                disabled={rois.length === 1}
                onClick={() => onChange(rois.filter((item) => item.id !== roi.id))}
                className="rounded-md p-1.5 text-slate-500 hover:bg-white/[0.05] hover:text-rose disabled:opacity-30"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(['x', 'y', 'width', 'height'] as const).map((field) => (
                <label key={field} className="text-[11px] text-slate-500">
                  {field}
                  <input
                    aria-label={`ROI ${index + 1} ${field}`}
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={roi[field]}
                    onChange={(event) => update(roi.id, field, Math.min(1, Math.max(0, Number(event.target.value))))}
                    className="mt-1 w-full rounded-[8px] border border-white/[0.07] bg-surface-1 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-mint-400/40"
                  />
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  )
}

export function AestheticQuantMockPanel() {
  const [designImage, setDesignImage] = useState<File | null>(null)
  const [foregroundImage, setForegroundImage] = useState<File | null>(null)
  const [backgroundImage, setBackgroundImage] = useState<File | null>(null)
  const [profile, setProfile] = useState<AestheticProfile>('balanced')
  const [depth, setDepth] = useState<AestheticDepth>('standard')
  const [enableAttention, setEnableAttention] = useState(true)
  const [includeAttention, setIncludeAttention] = useState(false)
  const [rois, setRois] = useState<RoiInput[]>(DEFAULT_ROIS)
  const [showResult, setShowResult] = useState(false)
  const resultRef = useRef<HTMLElement>(null)
  const previewUrl = useObjectUrl(designImage)
  const result = AESTHETIC_MOCK_RESULT
  useEffect(() => {
    if (showResult) resultRef.current?.scrollIntoView({ block: 'start' })
  }, [showResult])
  const attentionIncluded = enableAttention && includeAttention
  const displayedScore = result.overallScore + (attentionIncluded ? 2 : 0)
  const visibleMetrics = enableAttention ? result.metrics : result.metrics.filter((metric) => metric.label !== '注意力聚焦')
  const visibleFindings = enableAttention ? result.findings : result.findings.filter((finding) => !finding.includes('注意力'))

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.18fr)]">
      <div className="space-y-4">
        <div className="rounded-[12px] border border-amber-300/20 bg-amber-300/[0.07] px-4 py-3 text-xs leading-5 text-amber-100">
          <strong>Mock 演示：</strong>前端固定样例，不代表真实图片分析。图片仅在当前浏览器中预览，不会上传。
        </div>
        <SectionCard title="分析输入" desc="配置设计素材和演示参数。" icon={<ImagePlus className="h-4 w-4" />}>
          <div className="grid gap-3 sm:grid-cols-3">
            <ImageInput label="上传设计图" file={designImage} onChange={setDesignImage} previewUrl={previewUrl} />
            <ImageInput label="选择前景图" file={foregroundImage} onChange={setForegroundImage} />
            <ImageInput label="选择背景图" file={backgroundImage} onChange={setBackgroundImage} />
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium text-slate-400">
              分析模式
              <select aria-label="分析模式" value={profile} onChange={(event) => setProfile(event.target.value as AestheticProfile)} className={inputClass}>
                <option value="balanced">平衡模式</option>
                <option value="readability_first">可读性优先</option>
                <option value="marketing_impact">营销冲击力</option>
              </select>
            </label>
            <label className="text-xs font-medium text-slate-400">
              分析深度
              <select aria-label="分析深度" value={depth} onChange={(event) => setDepth(event.target.value as AestheticDepth)} className={inputClass}>
                <option value="lite">快速</option>
                <option value="standard">标准</option>
                <option value="deep">深度</option>
              </select>
            </label>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            <label className="flex items-center gap-2 rounded-[9px] border border-white/[0.06] bg-base px-3 py-2 text-xs text-slate-300">
              <input type="checkbox" checked={enableAttention} onChange={(event) => { setEnableAttention(event.target.checked); if (!event.target.checked) setIncludeAttention(false) }} />
              启用注意力分析
            </label>
            <label className="flex items-center gap-2 rounded-[9px] border border-white/[0.06] bg-base px-3 py-2 text-xs text-slate-300">
              <input type="checkbox" checked={includeAttention} disabled={!enableAttention} onChange={(event) => setIncludeAttention(event.target.checked)} />
              注意力计入综合分
            </label>
          </div>
        </SectionCard>
        <RoiEditor rois={rois} onChange={setRois} />
        <Button type="button" block size="lg" disabled={!designImage} onClick={() => setShowResult(true)}>
          生成演示结果
        </Button>
      </div>

      <div className="min-w-0 space-y-4" aria-live="polite">
        {showResult ? (
          <>
            <section ref={resultRef} className="rounded-[14px] border border-mint-400/20 bg-mint-400/[0.06] p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mint-300">Mock output</p>
                  <h3 className="mt-1 text-xl font-semibold text-white">演示结果</h3>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">{result.summary}</p>
                </div>
                <div className="rounded-[12px] border border-mint-400/20 bg-base px-4 py-3 text-right">
                  <p className="text-xs text-slate-500">综合分 {displayedScore}</p>
                  <p className="mt-1 text-2xl font-semibold text-mint-300">{displayedScore}</p>
                  <p className="mt-1 text-[11px] text-slate-500">置信度 {result.confidence.level} · {result.confidence.score}</p>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-slate-400">
                <span className="rounded-full bg-white/[0.05] px-2.5 py-1">模式 {profile}</span>
                <span className="rounded-full bg-white/[0.05] px-2.5 py-1">{attentionIncluded ? '注意力已计入演示总分' : '注意力未计入演示总分'}</span>
                <span className="rounded-full bg-white/[0.05] px-2.5 py-1">深度 {depth}</span>
                <span className="rounded-full bg-white/[0.05] px-2.5 py-1">ROI {rois.length}</span>
              </div>
            </section>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              {visibleMetrics.map((metric) => (
                <div key={metric.label} className="rounded-[11px] border border-white/[0.07] bg-surface-1 p-3">
                  <p className="text-[11px] text-slate-500">{metric.label}</p>
                  <p className="mt-1 text-lg font-semibold text-slate-100">{metric.value}</p>
                </div>
              ))}
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <SectionCard title="整图指标" bodyClassName="grid grid-cols-2 gap-2">
                {result.imageStats.map((item) => (
                  <div key={item.label} className="rounded-[8px] bg-base px-3 py-2 text-xs">
                    <span className="text-slate-500">{item.label}</span>
                    <span className="float-right font-semibold text-slate-200">{item.value}</span>
                  </div>
                ))}
              </SectionCard>
              <SectionCard title="前后景配对" bodyClassName="grid grid-cols-2 gap-2">
                {result.pairResult.map((item) => (
                  <div key={item.label} className="rounded-[8px] bg-base px-3 py-2 text-xs">
                    <span className="text-slate-500">{item.label}</span>
                    <span className="float-right font-semibold text-slate-200">{item.value}</span>
                  </div>
                ))}
              </SectionCard>
            </div>

            <SectionCard title="ROI 结果" icon={<Target className="h-4 w-4" />}>
              <div className="grid gap-3 sm:grid-cols-2">
                {result.roiResults.map((roi) => (
                  <div key={roi.label} className="rounded-[10px] border border-white/[0.06] bg-base p-3 text-xs">
                    <div className="flex items-center justify-between"><strong className="text-slate-200">{roi.label}</strong><span className="text-mint-300">{roi.score} 分</span></div>
                    <p className="mt-2 text-slate-500">亮度 {roi.brightness} · 饱和度 {roi.saturation}{enableAttention ? ` · 注意力 #${roi.attentionRank}` : ''}</p>
                  </div>
                ))}
              </div>
            </SectionCard>

            {enableAttention ? (
              <SectionCard title="注意力热点示意" icon={<Eye className="h-4 w-4" />}>
                <div className="grid gap-4 sm:grid-cols-[180px_1fr]">
                  <div className="grid aspect-square grid-cols-8 overflow-hidden rounded-[10px] border border-white/[0.08] bg-slate-950" aria-label="注意力热图">
                    {result.attention.heatmap.map((value, index) => (
                      <span key={index} style={{ backgroundColor: `rgba(251, 191, 36, ${Math.max(0.08, value)})` }} />
                    ))}
                  </div>
                  <div className="grid grid-cols-3 gap-2 self-start">
                    <div className="rounded-[9px] bg-base p-3"><p className="text-[11px] text-slate-500">峰值注意力</p><p className="mt-1 font-semibold text-slate-200">{result.attention.peak}</p></div>
                    <div className="rounded-[9px] bg-base p-3"><p className="text-[11px] text-slate-500">焦点平衡</p><p className="mt-1 font-semibold text-slate-200">{result.attention.balance}</p></div>
                    <div className="rounded-[9px] bg-base p-3"><p className="text-[11px] text-slate-500">分散风险</p><p className="mt-1 font-semibold text-slate-200">{result.attention.distraction}</p></div>
                  </div>
                </div>
              </SectionCard>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <SectionCard title="发现"><ul className="space-y-2 text-sm leading-6 text-slate-300">{visibleFindings.map((item) => <li key={item}>• {item}</li>)}</ul></SectionCard>
              <SectionCard title="优化建议"><ul className="space-y-2 text-sm leading-6 text-slate-300">{result.recommendations.map((item) => <li key={item}>• {item}</li>)}</ul></SectionCard>
            </div>
            <SectionCard title="边界说明"><ul className="space-y-2 text-xs leading-5 text-slate-400">{[result.confidence.note, ...result.boundaryNotes].map((item) => <li key={item}>• {item}</li>)}</ul></SectionCard>
          </>
        ) : (
          <div className="flex min-h-[420px] items-center justify-center rounded-[14px] border border-dashed border-white/[0.1] bg-surface-1/50 px-6 text-center">
            <div><Eye className="mx-auto h-7 w-7 text-slate-600" aria-hidden="true" /><p className="mt-3 text-sm text-slate-400">上传设计图并生成固定演示结果</p><p className="mt-1 text-xs text-slate-600">不会调用后端，也不会保存图片。</p></div>
          </div>
        )}
      </div>
    </div>
  )
}
