import { useEffect, useRef, useState } from 'react'
import { ImagePlus, Plus, Target, Trash2 } from 'lucide-react'

import jdNewArrivalsCaseImage from '../../assets/jd-new-arrivals-case.jpg'
import { Button } from '../../components/ui/Button'
import { SectionCard } from '../../components/ui/Card'
import { AestheticQuantResultPage } from './AestheticQuantResultPage'
import { CaseStudyFigure } from './CaseStudyFigure'
import { AESTHETIC_MOCK_RESULT, DEFAULT_ROIS } from './fixtures'
import type { AestheticDepth, AestheticProfile, RoiInput } from './types'

const inputClass = 'mt-1.5 w-full rounded-soft border border-white/[0.08] bg-base px-3 py-2 text-sm text-slate-100 outline-none focus:border-mint-400/40'

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
    <div className="rounded-soft border border-white/[0.07] bg-base/70 p-3">
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
        <img src={previewUrl} alt="设计图预览" width={360} height={112} loading="lazy" className="mb-3 h-28 w-full rounded-soft border border-white/[0.08] object-cover" />
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
          <div key={roi.id} className="rounded-soft border border-white/[0.06] bg-base p-3">
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
                className="rounded-md p-1.5 text-slate-400 hover:bg-white/[0.05] hover:text-rose disabled:opacity-30"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(['x', 'y', 'width', 'height'] as const).map((field) => (
                <label key={field} className="text-[11px] text-slate-400">
                  {field}
                  <input
                    aria-label={`ROI ${index + 1} ${field}`}
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={roi[field]}
                    onChange={(event) => update(roi.id, field, Math.min(1, Math.max(0, Number(event.target.value))))}
                    className="mt-1 w-full rounded-control border border-white/[0.07] bg-surface-1 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-mint-400/40"
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
  const previewUrl = useObjectUrl(designImage)
  const result = AESTHETIC_MOCK_RESULT
  const attentionIncluded = enableAttention && includeAttention

  if (showResult) {
    return (
      <AestheticQuantResultPage
        result={result}
        profile={profile}
        depth={depth}
        enableAttention={enableAttention}
        attentionIncluded={attentionIncluded}
        roiCount={rois.length}
        onBack={() => setShowResult(false)}
      />
    )
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.18fr)]">
      <div className="space-y-4">
        <div className="rounded-soft border border-amber-300/20 bg-amber-300/[0.07] px-4 py-3 text-xs leading-5 text-amber-100">
          <strong>示例演示：</strong>报告基于内置京东新品频道截图生成。上传图片仅替换本地预览，不会上传，也不会改变固定结论。
        </div>
        <SectionCard title="分析输入" desc="配置设计素材和演示参数。" icon={<ImagePlus className="h-4 w-4" />}>
          <div className="grid gap-3 sm:grid-cols-3">
            <ImageInput label="上传设计图" file={designImage} onChange={setDesignImage} previewUrl={previewUrl ?? jdNewArrivalsCaseImage} />
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
            <label className="flex items-center gap-2 rounded-soft border border-white/[0.06] bg-base px-3 py-2 text-xs text-slate-300">
              <input type="checkbox" checked={enableAttention} onChange={(event) => { setEnableAttention(event.target.checked); if (!event.target.checked) setIncludeAttention(false) }} />
              启用注意力分析
            </label>
            <label className="flex items-center gap-2 rounded-soft border border-white/[0.06] bg-base px-3 py-2 text-xs text-slate-300">
              <input type="checkbox" checked={includeAttention} disabled={!enableAttention} onChange={(event) => setIncludeAttention(event.target.checked)} />
              注意力计入综合分
            </label>
          </div>
        </SectionCard>
        <RoiEditor rois={rois} onChange={setRois} />
        <Button type="button" block size="lg" onClick={() => setShowResult(true)}>
          生成案例报告
        </Button>
      </div>

      <div className="min-w-0 space-y-4" aria-live="polite">
        <CaseStudyFigure
          alt={result.caseStudy.imageAlt}
          regions={[]}
        />
        <SectionCard title="将生成的报告" desc="报告内容会和当前案例图绑定，不写入后端。">
          <ul className="space-y-2 text-sm leading-6 text-slate-300">
            <li>• 综合分、置信度和示例边界说明</li>
            <li>• 案例截图 ROI 标注与热点示意</li>
            <li>• 频道识别、搜索可见性、信息层级等结构化指标</li>
            <li>• 针对红包浮层、活动区和商品流的发现与建议</li>
          </ul>
        </SectionCard>
      </div>
    </div>
  )
}
