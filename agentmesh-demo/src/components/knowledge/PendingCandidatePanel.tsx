import {
  Lightbulb,
  AlertCircle,
  BarChart3,
  Workflow,
  Target,
  User as UserIcon,
  Clock,
  Check,
  Pencil,
  Sparkles,
  ArrowUpRight,
  Users,
  Info,
} from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { NEW_KNOWLEDGE } from '../../data/mockData'
import { useDemo } from '../../store/DemoContext'
import type { ReactNode } from 'react'

interface Props {
  onConfirm: () => void
  onModify: () => void
  onOpenDetail: () => void
}

/**
 * Tab 2 · 待我确认(修改文档 §9.5):
 *   区域一:知识候选结论(标题 / 结论 / 状态 / 类型 / 来源)
 *   区域二:形成依据(问题 / 数据 / 决策 / 结果 / 适用范围 / 限制条件)
 *   区域三:确认与权限(AI 建议 + 主要操作)
 * 不使用整页高饱和绿色边框(§13),主按钮只保留"确认并沉淀"。
 */
export function PendingCandidatePanel({ onConfirm, onModify, onOpenDetail }: Props) {
  const { showToast } = useDemo()

  return (
    <div className="space-y-6 animate-fade-in">
      {/* ────── 区域一:知识候选结论 ────── */}
      <section className="card-base p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3.5">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-mint-400/12 text-mint-300">
              <Lightbulb className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone="remind" dot>
                  待确认
                </Badge>
                <Badge tone="knowledge">{NEW_KNOWLEDGE.suggestedTypeLabel}</Badge>
                <Badge tone="neutral">{NEW_KNOWLEDGE.sourceProject}</Badge>
              </div>
              <h2 className="mt-2 text-[18px] font-semibold leading-snug text-white">
                {NEW_KNOWLEDGE.title}
              </h2>
              <p className="mt-2 text-[14px] leading-relaxed text-slate-300">
                {NEW_KNOWLEDGE.conclusion}
              </p>
            </div>
          </div>
          <button
            onClick={onOpenDetail}
            className="hidden shrink-0 items-center gap-1 text-xs text-slate-500 transition-colors hover:text-slate-200 md:inline-flex"
          >
            查看完整复盘 <ArrowUpRight className="h-3 w-3" />
          </button>
        </div>
      </section>

      {/* ────── 区域二:形成依据 ────── */}
      <section className="card-base p-6">
        <SubTitle icon={<Info className="h-4 w-4" />} label="形成依据" />
        <div className="mt-4 grid gap-5 lg:grid-cols-2">
          {/* 项目问题 */}
          <EvidenceBlock icon={<AlertCircle className="h-4 w-4" />} label="项目问题">
            <p>{NEW_KNOWLEDGE.problem}</p>
          </EvidenceBlock>

          {/* 原始数据 */}
          <EvidenceBlock icon={<BarChart3 className="h-4 w-4" />} label="原始数据">
            <ul className="space-y-2">
              {NEW_KNOWLEDGE.rawData.map((d) => (
                <li
                  key={d.label}
                  className="flex items-center justify-between gap-2 rounded-[9px] border border-white/[0.06] bg-surface-1 px-3 py-2"
                >
                  <span className="text-[12.5px] text-slate-400">{d.label}</span>
                  <span className="tabular-nums text-[12.5px] font-semibold text-slate-200">
                    {d.value}
                  </span>
                </li>
              ))}
            </ul>
          </EvidenceBlock>

          {/* 项目决策 */}
          <EvidenceBlock icon={<Workflow className="h-4 w-4" />} label="项目决策">
            <ul className="space-y-1.5">
              {NEW_KNOWLEDGE.decisions.map((d) => (
                <li key={d} className="flex gap-2 text-[13px] leading-relaxed text-slate-300">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-500" />
                  {d}
                </li>
              ))}
            </ul>
          </EvidenceBlock>

          {/* 项目结果(不编造提升比例) */}
          <EvidenceBlock icon={<Check className="h-4 w-4" />} label="项目结果">
            <p>{NEW_KNOWLEDGE.result}</p>
          </EvidenceBlock>

          {/* 适用范围 */}
          <EvidenceBlock icon={<Target className="h-4 w-4" />} label="适用范围">
            <div className="flex flex-wrap gap-1.5">
              {NEW_KNOWLEDGE.scope.map((s) => (
                <Badge key={s} tone="knowledge">
                  {s}
                </Badge>
              ))}
            </div>
          </EvidenceBlock>

          {/* 限制条件 */}
          <EvidenceBlock icon={<AlertCircle className="h-4 w-4" />} label="限制条件">
            <p>{NEW_KNOWLEDGE.limitation}</p>
          </EvidenceBlock>
        </div>

        {/* 来源与贡献 */}
        <div className="mt-5 flex flex-wrap items-center gap-4 rounded-[10px] border border-white/[0.05] bg-surface-1 px-4 py-3 text-[12px] text-slate-400">
          <span className="inline-flex items-center gap-1.5">
            <UserIcon className="h-3.5 w-3.5 text-slate-500" />
            项目负责人:
            <span className="text-slate-200">{NEW_KNOWLEDGE.contributor}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-slate-500" />
            提炼时间:
            <span className="text-slate-200">{NEW_KNOWLEDGE.formedAt}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Sparkles className="h-3.5 w-3.5 text-slate-500" />
            形成方式:
            <span className="text-slate-200">{NEW_KNOWLEDGE.formationMethod}</span>
          </span>
        </div>
      </section>

      {/* ────── 区域三:确认与权限 ────── */}
      <section className="card-base p-6">
        <SubTitle icon={<Users className="h-4 w-4" />} label="确认与权限" />
        <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <p className="max-w-2xl text-[13px] leading-relaxed text-slate-400">
            AI 建议将这条知识共享给「
            <span className="text-slate-200">{NEW_KNOWLEDGE.recommendVisibilityLabel}</span>
            」,方便家电设计组的其他数字人在类似决策中引用。你可以在确认时修改类型、适用范围或权限,
            <span className="text-slate-300">所有引用都会保留来源与适用范围</span>。
          </p>
          <div className="rounded-[10px] border border-knowledge/20 bg-knowledge/[0.05] px-3.5 py-2 text-xs text-knowledge">
            AI 建议共享给「{NEW_KNOWLEDGE.recommendVisibilityLabel}」
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-2.5">
          <Button variant="primary" icon={<Check className="h-4 w-4" />} onClick={onConfirm}>
            确认并沉淀
          </Button>
          <Button variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={onModify}>
            修改内容
          </Button>
          <Button
            variant="subtle"
            icon={<Clock className="h-4 w-4" />}
            onClick={() =>
              showToast('已暂后处理,数字人会保留候选,不会自动共享或引用', 'info')
            }
          >
            暂后处理
          </Button>
          <Button
            variant="ghost"
            icon={<ArrowUpRight className="h-4 w-4" />}
            onClick={() =>
              showToast('已退回补充复盘,请到工作洞察补充材料后再形成候选', 'info')
            }
          >
            退回补充复盘
          </Button>
        </div>
      </section>

      {/* 底部提示:确认与权限的边界 */}
      <div className="flex items-start gap-2 text-[12px] leading-relaxed text-slate-500">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        AI 从项目复盘中形成候选,但不会直接称为知识。只有你确认后才成为知识资产;只有你授权后其他数字人才能引用。
      </div>
    </div>
  )
}

/* ---------- 小组件 ---------- */
function SubTitle({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-2 text-[13px] font-semibold text-slate-100">
      <span className="text-mint-300">{icon}</span>
      {label}
    </div>
  )
}

function EvidenceBlock({
  icon,
  label,
  children,
}: {
  icon: ReactNode
  label: string
  children: ReactNode
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[11.5px] font-medium uppercase tracking-wide text-slate-500">
        <span className="text-slate-400">{icon}</span>
        {label}
      </div>
      <div className="text-[13px] leading-relaxed text-slate-300">{children}</div>
    </div>
  )
}
