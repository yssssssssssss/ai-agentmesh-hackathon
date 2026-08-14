import { useEffect, useState, type ReactNode } from 'react'
import {
  ClipboardList,
  CheckCircle2,
  AlertCircle,
  ChevronLeft,
  Sparkles,
  ArrowRight,
  PartyPopper,
  Save,
  Clock,
  BookMarked,
} from 'lucide-react'
import { Drawer } from '../ui/Drawer'
import { Button } from '../ui/Button'
import { cn } from '../../lib/cn'
import {
  REVIEW_PROJECT,
  REVIEW_FLOW,
  type ReviewStatus,
  type KnowledgeCandidateStatus,
} from '../../data/mockData'
import { useDemo } from '../../store/DemoContext'

interface ProjectReviewDrawerProps {
  open: boolean
  onClose: () => void
  reviewStatus: ReviewStatus
  candidateStatus: KnowledgeCandidateStatus
  onStatusChange: (review: ReviewStatus, candidate: KnowledgeCandidateStatus) => void
  onGoKnowledge: () => void
}

const STEPS = ['确认项目背景', '检查已有证据', '补充缺失结果', '生成知识候选']

/**
 * 项目复盘抽屉：四步引导用户从已完成项目中提炼知识候选。
 * 关键约束（见修改文档 §10）：不在打开时立即生成知识，必须经过证据检查 + 结果补充，
 * 材料完整后才允许「生成知识候选」，成功后引导前往「我的知识」确认。
 */
export function ProjectReviewDrawer({
  open,
  onClose,
  reviewStatus,
  candidateStatus,
  onStatusChange,
  onGoKnowledge,
}: ProjectReviewDrawerProps) {
  const { showToast } = useDemo()
  const [step, setStep] = useState(0)
  const [resultText, setResultText] = useState('')
  const [resultsFilled, setResultsFilled] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [generated, setGenerated] = useState(false)

  const missingCount = REVIEW_FLOW.evidence.filter((e) => !e.ready).length

  // 打开时根据传入状态初始化；若已生成候选则直接停在成功态
  useEffect(() => {
    if (!open) return
    setSubmitting(false)
    if (candidateStatus === 'pending_confirmation' || reviewStatus === 'candidate_ready') {
      setStep(3)
      setResultsFilled(true)
      setGenerated(true)
    } else {
      setStep(0)
      setResultsFilled(false)
      setGenerated(false)
      setResultText('')
      if (reviewStatus === 'suggested') onStatusChange('in_progress', 'none')
    }
    // 仅在开合时初始化
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // 进入「补充缺失结果」步骤且尚未补充时，复盘状态为待补充结果
  const goToStep = (next: number) => {
    if (next === 2 && !resultsFilled) onStatusChange('missing_evidence', candidateStatus)
    setStep(next)
  }

  const handleSupplement = () => {
    if (!resultText.trim()) return
    setResultsFilled(true)
    onStatusChange('in_progress', 'draft')
    setStep(3)
  }

  const handleGenerate = () => {
    setSubmitting(true)
    window.setTimeout(() => {
      setSubmitting(false)
      setGenerated(true)
      onStatusChange('candidate_ready', 'pending_confirmation')
    }, 900)
  }

  /* ---------- footer ---------- */
  let footer: ReactNode
  if (generated) {
    footer = (
      <div className="flex justify-between gap-3">
        <Button variant="ghost" onClick={() => setStep(0)}>
          继续查看复盘
        </Button>
        <Button variant="primary" icon={<BookMarked className="h-4 w-4" />} onClick={onGoKnowledge}>
          前往我的知识
        </Button>
      </div>
    )
  } else {
    footer = (
      <div className="flex justify-between gap-3">
        {step > 0 ? (
          <Button
            variant="ghost"
            icon={<ChevronLeft className="h-4 w-4" />}
            onClick={() => goToStep(step - 1)}
          >
            上一步
          </Button>
        ) : (
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
        )}

        {step < 2 && (
          <Button variant="primary" iconRight={<ArrowRight className="h-4 w-4" />} onClick={() => goToStep(step + 1)}>
            下一步
          </Button>
        )}
        {step === 2 && (
          <Button variant="primary" disabled={!resultText.trim()} onClick={handleSupplement}>
            补充结果并继续
          </Button>
        )}
        {step === 3 && (
          <Button
            variant="primary"
            loading={submitting}
            disabled={!resultsFilled}
            icon={<Sparkles className="h-4 w-4" />}
            onClick={handleGenerate}
          >
            生成知识候选
          </Button>
        )}
      </div>
    )
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={560}
      icon={<ClipboardList className="h-4 w-4" />}
      title={`项目复盘 · ${REVIEW_PROJECT.name}`}
      subtitle="数字人整理项目材料，确认结果后可形成知识候选"
      footer={footer}
    >
      {/* 步骤指示：紧凑圆点 + 当前步骤标题，适配抽屉宽度 */}
      <div className="mb-5">
        <div className="flex items-center">
          {STEPS.map((label, i) => {
            const active = i === step
            const complete = i < step || (generated && i <= 3)
            return (
              <div key={label} className="flex flex-1 items-center last:flex-none">
                <span
                  className={cn(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold transition-colors',
                    active
                      ? 'bg-knowledge text-white'
                      : complete
                        ? 'bg-knowledge/20 text-knowledge'
                        : 'bg-white/[0.06] text-slate-500',
                  )}
                >
                  {complete && !active ? <CheckCircle2 className="h-4 w-4" /> : i + 1}
                </span>
                {i < STEPS.length - 1 && (
                  <span className={cn('mx-2 h-px flex-1', i < step ? 'bg-knowledge/40' : 'bg-white/[0.08]')} />
                )}
              </div>
            )
          })}
        </div>
        <div className="mt-3">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            步骤 {Math.min(step + 1, 4)} / 4
          </div>
          <h3 className="mt-0.5 text-[15px] font-semibold text-white">{STEPS[step]}</h3>
        </div>
      </div>

      {/* 步骤内容 */}
      {step === 0 && <StepBackground />}
      {step === 1 && <StepEvidence missingCount={missingCount} />}
      {step === 2 && (
        <StepSupplement
          value={resultText}
          onChange={setResultText}
          onSaveDraft={() => {
            onStatusChange('in_progress', 'draft')
            showToast('复盘草稿已保存（演示）', 'info')
          }}
          onLater={onClose}
        />
      )}
      {step === 3 && (generated ? <StepSuccess /> : <StepGenerate ready={resultsFilled} />)}
    </Drawer>
  )
}

/* ---------- 步骤一：确认项目背景 ---------- */
function StepBackground() {
  return (
    <div className="space-y-4 animate-fade-in">
      <p className="text-[13px] leading-relaxed text-slate-400">
        数字人已根据项目记录整理出以下背景信息，请确认是否准确。
      </p>
      <div className="space-y-3">
        {REVIEW_FLOW.background.map((f) => (
          <div key={f.label}>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
              {f.label}
            </div>
            <p className="text-[13px] leading-relaxed text-slate-300">{f.value}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------- 步骤二：检查已有证据 ---------- */
function StepEvidence({ missingCount }: { missingCount: number }) {
  return (
    <div className="space-y-4 animate-fade-in">
      <p className="text-[13px] leading-relaxed text-slate-400">
        复盘需要完整的过程与结果证据。数字人已核对现有材料：
      </p>
      <ul className="space-y-2">
        {REVIEW_FLOW.evidence.map((e) => (
          <li
            key={e.label}
            className={cn(
              'flex items-start gap-3 rounded-[10px] border px-3.5 py-3',
              e.ready
                ? 'border-white/[0.06] bg-surface-1'
                : 'border-remind/25 bg-remind/[0.06]',
            )}
          >
            {e.ready ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-mint-300" />
            ) : (
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-remind" />
            )}
            <div className="min-w-0">
              <div className="text-[13px] font-medium text-slate-200">{e.label}</div>
              <div className={cn('mt-0.5 text-[12px] leading-relaxed', e.ready ? 'text-slate-500' : 'text-remind/90')}>
                {e.note}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {missingCount > 0 && (
        <div className="rounded-[10px] bg-remind/[0.08] px-3.5 py-2.5 text-[12.5px] leading-relaxed text-remind">
          还缺少 {missingCount} 项结果类材料，需要在下一步补充后才能形成经过验证的知识。
        </div>
      )}
    </div>
  )
}

/* ---------- 步骤三：补充缺失结果 ---------- */
function StepSupplement({
  value,
  onChange,
  onSaveDraft,
  onLater,
}: {
  value: string
  onChange: (v: string) => void
  onSaveDraft: () => void
  onLater: () => void
}) {
  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex items-start gap-2.5 rounded-[10px] border border-remind/25 bg-remind/[0.06] px-3.5 py-3">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-remind" />
        <p className="text-[13px] leading-relaxed text-remind">{REVIEW_FLOW.missingHint}</p>
      </div>

      <div>
        <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">
          待补充的结果材料
        </div>
        <ul className="grid grid-cols-2 gap-2">
          {REVIEW_PROJECT.missing.map((m) => (
            <li
              key={m}
              className="rounded-[8px] border border-white/[0.06] bg-surface-1 px-3 py-2 text-[12.5px] text-slate-300"
            >
              {m}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-slate-500">
          补充项目实际结果
        </label>
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={4}
          placeholder={REVIEW_FLOW.resultPlaceholder}
          className="w-full resize-none rounded-[10px] border border-white/[0.08] bg-surface-1 px-3.5 py-2.5 text-[13px] leading-relaxed text-slate-100 outline-none transition-colors placeholder:text-slate-600 focus:border-knowledge/50"
        />
      </div>

      <div className="flex gap-2.5">
        <Button variant="subtle" size="sm" icon={<Save className="h-3.5 w-3.5" />} onClick={onSaveDraft}>
          保存复盘草稿
        </Button>
        <Button variant="ghost" size="sm" icon={<Clock className="h-3.5 w-3.5" />} onClick={onLater}>
          暂后处理
        </Button>
      </div>
    </div>
  )
}

/* ---------- 步骤四（未生成）：生成知识候选 ---------- */
function StepGenerate({ ready }: { ready: boolean }) {
  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex items-start gap-2.5 rounded-[10px] border border-mint-400/20 bg-mint-400/[0.06] px-3.5 py-3">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-mint-300" />
        <p className="text-[13px] leading-relaxed text-slate-200">
          {ready
            ? '项目材料已补充完整，可以从这次复盘中提炼知识候选。'
            : '请先在上一步补充项目实际结果，材料完整后才能生成知识候选。'}
        </p>
      </div>

      <div>
        <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">
          预计可形成的知识方向
        </div>
        <ul className="space-y-2">
          {REVIEW_PROJECT.directions.map((d) => (
            <li key={d} className="flex items-start gap-2.5 text-[13px] leading-relaxed text-slate-300">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-knowledge/70" />
              {d}
            </li>
          ))}
        </ul>
      </div>

      <p className="text-[12px] leading-relaxed text-slate-500">
        生成后会作为知识候选，等待你在「我的知识」中确认，确认后才会成为团队可引用的知识。
      </p>
    </div>
  )
}

/* ---------- 步骤四（已生成）：成功态 ---------- */
function StepSuccess() {
  return (
    <div className="flex flex-col items-center py-4 text-center animate-scale-in">
      <span className="flex h-16 w-16 items-center justify-center rounded-full bg-knowledge/15 text-knowledge">
        <PartyPopper className="h-8 w-8" />
      </span>
      <h3 className="mt-4 text-[17px] font-semibold text-white">已形成 1 条知识候选</h3>
      <p className="mt-2 max-w-sm text-[13px] leading-relaxed text-slate-400">
        {REVIEW_FLOW.candidateReadyHint}
      </p>
      <div className="mt-5 w-full rounded-[12px] border border-knowledge/20 bg-knowledge/[0.06] px-4 py-3.5 text-left">
        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-knowledge">
          <BookMarked className="h-3 w-3" />
          知识候选
        </div>
        <div className="text-[14px] font-semibold text-slate-100">{REVIEW_FLOW.candidateTitle}</div>
        <div className="mt-1.5 text-[12px] text-slate-500">来源：{REVIEW_PROJECT.name} · 待你在「我的知识」确认</div>
      </div>
    </div>
  )
}
