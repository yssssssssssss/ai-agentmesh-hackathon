import { useEffect, useState } from 'react'
import {
  Check,
  ChevronLeft,
  Lightbulb,
  ShieldCheck,
  Target,
  PartyPopper,
  BookMarked,
  Users,
} from 'lucide-react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { cn } from '../../lib/cn'
import {
  KNOWLEDGE_TYPE_LABELS,
  NEW_KNOWLEDGE,
  VISIBILITY_LABELS,
  type KnowledgeType,
  type Visibility,
} from '../../data/mockData'
import { useDemo, type ConfirmCandidatePayload } from '../../store/DemoContext'

interface ConfirmKnowledgeModalProps {
  open: boolean
  onClose: () => void
  onDone?: () => void
}

const TYPE_OPTIONS: { key: KnowledgeType; label: string; desc: string }[] = [
  { key: 'design_rule', label: '设计规范', desc: '设计规则或组件层级要求' },
  { key: 'decision_method', label: '决策方法', desc: '如何在多个方案间做出判断' },
  { key: 'project_experience', label: '项目经验', desc: '来自具体项目的结果与总结' },
  { key: 'data_insight', label: '数据经验', desc: '经过测量或对比得出的规律' },
  { key: 'workflow_method', label: '流程方法', desc: '工作方式、流程或分工' },
  { key: 'risk_boundary', label: '风险与边界', desc: '容易出错的情况或限制条件' },
]

const VISIBILITY_OPTIONS: {
  key: Visibility
  label: string
  desc: string
  detail?: string
}[] = [
  { key: 'private', label: '仅自己', desc: '只用于你的数字人' },
  { key: 'project', label: '当前项目', desc: '当前项目内的数字人可引用' },
  {
    key: 'team',
    label: '家电设计组',
    desc: '组内数字人可引用(AI 建议)',
    detail: '家电设计组',
  },
  { key: 'custom', label: '更多团队', desc: '扩展到相关营销设计团队', detail: '相关营销设计团队' },
]

const STEPS = [
  { icon: Lightbulb, label: '确认知识内容' },
  { icon: BookMarked, label: '设置知识类型' },
  { icon: ShieldCheck, label: '设置使用权限' },
]

/**
 * 3 步确认(修改文档 §9.6):
 *   步 1:确认内容(标题 / 结论 / 适用范围 / 限制条件,可修改)
 *   步 2:设置知识类型(6 选 1,默认决策方法)
 *   步 3:设置使用权限(4 选 1,默认家电设计组)
 * 完成后调用 confirmCandidate 更新 DemoContext:
 *   pendingCount 1→0, assetCount 24→25, 首位插入新资产,权限≠private 时追加共享动态。
 */
export function ConfirmKnowledgeModal({ open, onClose, onDone }: ConfirmKnowledgeModalProps) {
  const { confirmCandidate } = useDemo()

  const [step, setStep] = useState(0)
  const [title, setTitle] = useState(NEW_KNOWLEDGE.title)
  const [conclusion, setConclusion] = useState(NEW_KNOWLEDGE.conclusion)
  const [scope, setScope] = useState(NEW_KNOWLEDGE.scope.join('、'))
  const [limitation, setLimitation] = useState(NEW_KNOWLEDGE.limitation)
  const [type, setType] = useState<KnowledgeType>(NEW_KNOWLEDGE.recommendType)
  const [visibility, setVisibility] = useState<Visibility>(NEW_KNOWLEDGE.recommendVisibility)
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (open) {
      setStep(0)
      setTitle(NEW_KNOWLEDGE.title)
      setConclusion(NEW_KNOWLEDGE.conclusion)
      setScope(NEW_KNOWLEDGE.scope.join('、'))
      setLimitation(NEW_KNOWLEDGE.limitation)
      setType(NEW_KNOWLEDGE.recommendType)
      setVisibility(NEW_KNOWLEDGE.recommendVisibility)
      setSubmitting(false)
      setDone(false)
    }
  }, [open])

  const handleSubmit = () => {
    const payload: ConfirmCandidatePayload = {
      title,
      conclusion,
      scope,
      limitation,
      type,
      visibility,
      visibilityDetail:
        visibility === 'team'
          ? '家电设计组'
          : visibility === 'custom'
            ? '相关营销设计团队'
            : undefined,
    }
    setSubmitting(true)
    window.setTimeout(() => {
      confirmCandidate(payload)
      setSubmitting(false)
      setDone(true)
    }, 700)
  }

  const handleFinish = () => {
    onDone?.()
    onClose()
  }

  const footer = done ? (
    <Button variant="primary" onClick={handleFinish} icon={<Check className="h-4 w-4" />}>
      查看知识资产
    </Button>
  ) : (
    <>
      {step > 0 ? (
        <Button
          variant="ghost"
          onClick={() => setStep((s) => s - 1)}
          icon={<ChevronLeft className="h-4 w-4" />}
        >
          上一步
        </Button>
      ) : (
        <Button variant="ghost" onClick={onClose}>
          取消
        </Button>
      )}
      {step < STEPS.length - 1 ? (
        <Button variant="primary" onClick={() => setStep((s) => s + 1)}>
          下一步
        </Button>
      ) : (
        <Button variant="primary" loading={submitting} onClick={handleSubmit}>
          确认并沉淀
        </Button>
      )}
    </>
  )

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={done ? '已沉淀为知识资产' : '确认并沉淀新知识'}
      subtitle={done ? undefined : '由你确认知识内容、类型与权限,数字人不会自动改写'}
      footer={footer}
    >
      {done ? (
        <SuccessView title={title} visibility={visibility} type={type} />
      ) : (
        <>
          {/* 步骤条 */}
          <div className="mb-6 flex items-center">
            {STEPS.map((s, i) => {
              const active = i === step
              const complete = i < step
              return (
                <div key={s.label} className="flex flex-1 items-center last:flex-none">
                  <div className="flex items-center gap-2.5">
                    <span
                      className={cn(
                        'flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold transition-colors',
                        active
                          ? 'bg-mint-400 text-[#04241c]'
                          : complete
                            ? 'bg-mint-400/20 text-mint-300'
                            : 'bg-white/[0.06] text-slate-500',
                      )}
                    >
                      {complete ? <Check className="h-4 w-4" /> : i + 1}
                    </span>
                    <span
                      className={cn(
                        'text-sm font-medium',
                        active ? 'text-white' : 'text-slate-500',
                      )}
                    >
                      {s.label}
                    </span>
                  </div>
                  {i < STEPS.length - 1 && (
                    <div
                      className={cn(
                        'mx-3 h-px flex-1',
                        complete ? 'bg-mint-400/40' : 'bg-white/[0.08]',
                      )}
                    />
                  )}
                </div>
              )
            })}
          </div>

          {/* 步骤 1:确认知识内容 */}
          {step === 0 && (
            <div className="space-y-4 animate-fade-in">
              <Field label="知识标题">
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className={inputCls}
                />
              </Field>
              <Field label="核心结论">
                <textarea
                  value={conclusion}
                  onChange={(e) => setConclusion(e.target.value)}
                  rows={4}
                  className={cn(inputCls, 'resize-none leading-relaxed')}
                />
              </Field>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="适用范围" hint="以顿号或逗号分隔">
                  <input
                    value={scope}
                    onChange={(e) => setScope(e.target.value)}
                    className={inputCls}
                  />
                </Field>
                <Field label="限制条件">
                  <input
                    value={limitation}
                    onChange={(e) => setLimitation(e.target.value)}
                    className={inputCls}
                  />
                </Field>
              </div>
              <div className="flex items-start gap-2 rounded-[10px] bg-surface-1 px-3.5 py-2.5 text-xs text-slate-500">
                <Target className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
                标题和结论构成知识的最高视觉层级;适用范围和限制条件用于避免这条知识被误用。
              </div>
            </div>
          )}

          {/* 步骤 2:设置知识类型 */}
          {step === 1 && (
            <div className="space-y-3 animate-fade-in">
              <p className="text-sm text-slate-400">
                AI 建议类型为「
                <span className="text-slate-200">
                  {KNOWLEDGE_TYPE_LABELS[NEW_KNOWLEDGE.recommendType]}
                </span>
                」。你可以更改。
              </p>
              <div className="grid grid-cols-2 gap-3">
                {TYPE_OPTIONS.map((opt) => {
                  const active = type === opt.key
                  const isRecommend = opt.key === NEW_KNOWLEDGE.recommendType
                  return (
                    <button
                      key={opt.key}
                      onClick={() => setType(opt.key)}
                      className={cn(
                        'rounded-[12px] border p-3.5 text-left transition-all',
                        active
                          ? 'border-mint-400/50 bg-mint-400/[0.08]'
                          : 'border-white/[0.06] bg-surface-1 hover:border-white/[0.12]',
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
                          {opt.label}
                          {isRecommend && (
                            <Badge tone="mint">
                              <span className="text-[10px]">AI 建议</span>
                            </Badge>
                          )}
                        </span>
                        <Radio active={active} />
                      </div>
                      <p className="mt-1 text-xs text-slate-500">{opt.desc}</p>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* 步骤 3:设置使用权限 */}
          {step === 2 && (
            <div className="space-y-3 animate-fade-in">
              <p className="text-sm text-slate-400">
                AI 建议共享给「
                <span className="text-slate-200">{NEW_KNOWLEDGE.recommendVisibilityLabel}</span>
                」。授权后其他数字人才能在授权范围内引用这条知识,引用时保留来源与适用范围。
              </p>
              <div className="grid grid-cols-2 gap-3">
                {VISIBILITY_OPTIONS.map((opt) => {
                  const active = visibility === opt.key
                  const isRecommend = opt.key === NEW_KNOWLEDGE.recommendVisibility
                  return (
                    <button
                      key={opt.key}
                      onClick={() => setVisibility(opt.key)}
                      className={cn(
                        'rounded-[12px] border p-3.5 text-left transition-all',
                        active
                          ? 'border-mint-400/50 bg-mint-400/[0.08]'
                          : 'border-white/[0.06] bg-surface-1 hover:border-white/[0.12]',
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
                          {opt.label}
                          {isRecommend && (
                            <Badge tone="mint">
                              <span className="text-[10px]">AI 建议</span>
                            </Badge>
                          )}
                        </span>
                        <Radio active={active} />
                      </div>
                      <p className="mt-1 text-xs text-slate-500">{opt.desc}</p>
                    </button>
                  )
                })}
              </div>
              <div className="flex items-start gap-2 rounded-[10px] bg-knowledge/[0.06] px-3.5 py-2.5 text-xs text-knowledge">
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {visibility === 'private'
                  ? '仅自己可见时,不会出现在"共享与引用"动态中,他人不能引用。'
                  : `已选择:${VISIBILITY_LABELS[visibility]}。你可以在知识资产中随时调整权限。`}
              </div>
            </div>
          )}
        </>
      )}
    </Modal>
  )
}

/* ---------- Success View ---------- */
function SuccessView({
  title,
  visibility,
  type,
}: {
  title: string
  visibility: Visibility
  type: KnowledgeType
}) {
  const targetLabel =
    visibility === 'team'
      ? '家电设计组'
      : visibility === 'custom'
        ? '相关营销设计团队'
        : visibility === 'project'
          ? '当前项目'
          : '你自己的数字人'

  return (
    <div className="flex flex-col items-center py-4 text-center animate-scale-in">
      <span className="flex h-16 w-16 items-center justify-center rounded-full bg-mint-400/15 text-mint-300">
        <PartyPopper className="h-8 w-8" />
      </span>
      <h3 className="mt-4 text-lg font-semibold text-white">已沉淀为知识资产</h3>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-400">
        「{title}」已{visibility === 'private' ? '保存为个人知识' : `按照你的权限共享给 ${targetLabel}`}
        ,并按照你的权限设置提供给数字人使用。
      </p>
      <div className="mt-5 grid w-full grid-cols-2 gap-3 text-left">
        <SummaryCard label="待我确认" value="1 → 0" />
        <SummaryCard label="知识资产" value="24 → 25" />
        <SummaryCard label="知识类型" value={KNOWLEDGE_TYPE_LABELS[type]} icon={<BookMarked className="h-3 w-3" />} />
        <SummaryCard
          label="使用权限"
          value={visibility === 'team' ? `已共享给 ${targetLabel}` : VISIBILITY_LABELS[visibility]}
          icon={visibility === 'private' ? <ShieldCheck className="h-3 w-3" /> : <Users className="h-3 w-3" />}
        />
      </div>
    </div>
  )
}

function SummaryCard({
  label,
  value,
  icon,
}: {
  label: string
  value: string
  icon?: React.ReactNode
}) {
  return (
    <div className="rounded-[10px] border border-white/[0.06] bg-surface-1 p-3">
      <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-sm font-medium text-slate-100">{value}</div>
    </div>
  )
}

/* ---------- 表单原语 ---------- */
const inputCls =
  'w-full rounded-[10px] border border-white/[0.08] bg-surface-1 px-3.5 py-2.5 text-sm text-slate-100 outline-none transition-colors placeholder:text-slate-500 focus:border-mint-400/50'

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <label className="text-xs font-medium text-slate-400">{label}</label>
        {hint && <span className="text-[11px] text-slate-500">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

function Radio({ active }: { active: boolean }) {
  return (
    <span
      className={cn(
        'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
        active ? 'border-mint-400 bg-mint-400' : 'border-white/20',
      )}
    >
      {active && <Check className="h-3 w-3 text-[#04241c]" />}
    </span>
  )
}
