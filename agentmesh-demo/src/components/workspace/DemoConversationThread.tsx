import { useState } from 'react'
import { ArrowRight, Brain, ChevronDown, FileText, Search, Sparkles } from 'lucide-react'
import {
  BRIEF,
  WORKSPACE_ANSWER,
  WORKSPACE_REFERENCES,
  type WorkspaceRef,
} from '../../data/mockData'
import { useDemo } from '../../store/DemoContext'
import { cn } from '../../lib/cn'
import { DataSourceBadge } from '../ui/DataSourceBadge'

interface DemoConversationThreadProps {
  activeRefId?: string
  onOpenRef: (ref: WorkspaceRef) => void
  onOpenSources: () => void
  onOpenBrief: () => void
}

type AnalysisSegment = string | { ref: WorkspaceRef }

interface AnalysisStep {
  title: string
  description: AnalysisSegment[]
}

function refById(id: string): WorkspaceRef {
  const reference = WORKSPACE_REFERENCES.find((item) => item.id === id)
  if (!reference) throw new Error(`未找到演示引用 ${id}`)
  return reference
}

const ANALYSIS_STEPS: AnalysisStep[] = [
  {
    title: '理解任务',
    description: ['识别当前处于 618 会场改版准备阶段，本次需要解决的是首屏结构与核心入口效率问题。'],
  },
  {
    title: '查找相似项目',
    description: ['找到 3 个相关项目：', { ref: refById('ref-2025') }, '、', { ref: refById('ref-2024') }, ' 等。'],
  },
  {
    title: '检索已确认团队经验',
    description: ['找到 2 条已确认经验，与首屏入口效率和沉浸式头图使用相关。'],
  },
  {
    title: '查询近期业务数据',
    description: ['调用数据查询 Skill，读取近 90 天 ', { ref: refById('ref-data') }, '。数据范围：近 90 天 · 当前用户有权访问。'],
  },
  {
    title: '邀请数字员工补充判断',
    description: ['李明的数字员工补充项目经验，王晨的数字员工补充入口数据并提醒确认数据统计口径。'],
  },
  {
    title: '本次依据摘要',
    description: ['3 个相似项目 · 2 条已确认经验 · 近 90 天业务数据 · 2 位数字员工贡献。'],
  },
]

const FOLLOW_UPS = ['继续补充重点商品入口方案', '对比两种首屏结构', '创建后续任务']

export function DemoConversationThread({
  activeRefId,
  onOpenRef,
  onOpenSources,
  onOpenBrief,
}: DemoConversationThreadProps) {
  const { showToast } = useDemo()
  const [analysisOpen, setAnalysisOpen] = useState(false)

  return (
    <div className="space-y-6">
      <div className="border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-slate-400">
          <Sparkles className="h-3.5 w-3.5 text-mint-300" />
          当前任务
          <DataSourceBadge source="M" />
        </div>
        <h1 className="mt-1.5 text-[19px] font-bold tracking-tight text-white">2026 年 618 家电会场首页改版</h1>
        <p className="mt-1 text-[12px] text-slate-400">准备阶段 · 当前目标：确定首屏设计方向</p>
      </div>

      <div className="flex justify-end">
        <div className="max-w-[90%] rounded-soft rounded-tr-sm bg-surface-3 px-4 py-3 text-[14px] leading-relaxed text-slate-100">
          我要做今年 618 家电会场首页改版，帮我查找过去有没有类似项目经验，并给出首屏设计建议。
        </div>
      </div>

      <div className="space-y-4">
        <div className="flex gap-2.5 text-[12.5px] leading-relaxed">
          <Brain className="mt-[3px] h-4 w-4 shrink-0 text-slate-400" />
          <div className="min-w-0 flex-1">
            <div className="font-medium text-slate-300">项目理解</div>
            <p className="mt-0.5 text-slate-400">家电设计师 · 618 会场改版 · 首屏结构决策 · 基于本人及团队已授权工作知识分析</p>
          </div>
        </div>

        <div>
          <button type="button" onClick={() => setAnalysisOpen((open) => !open)} className="flex items-center gap-1.5 text-left">
            <Search className="h-4 w-4 shrink-0 text-slate-400" />
            <span className="text-[12.5px] font-medium text-slate-300">任务分析</span>
            <ChevronDown className={cn('h-3.5 w-3.5 text-slate-400 transition-transform', analysisOpen && 'rotate-180')} />
          </button>

          {analysisOpen ? (
            <ol className="mt-2.5 space-y-2.5 pl-[26px]">
              {ANALYSIS_STEPS.map((step, index) => (
                <li key={step.title} className="flex gap-2.5">
                  <span className="mt-[3px] flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-[11px] font-medium tabular-nums text-slate-400">
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[12.5px] font-medium text-slate-300">{step.title}</div>
                    <p className="mt-0.5 text-[12.5px] leading-relaxed text-slate-400">
                      {step.description.map((segment, segmentIndex) =>
                        typeof segment === 'string' ? (
                          <span key={segmentIndex}>{segment}</span>
                        ) : (
                          <button
                            key={segmentIndex}
                            type="button"
                            onClick={() => onOpenRef(segment.ref)}
                            className={cn(
                              'mx-0.5 rounded-control underline decoration-dotted underline-offset-2 transition-colors',
                              activeRefId === segment.ref.id
                                ? 'text-mint-200 decoration-mint-300'
                                : 'text-mint-300/90 decoration-mint-400/40 hover:text-mint-200',
                            )}
                          >
                            {segment.ref.title}
                          </button>
                        ),
                      )}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <div className="ml-[26px] mt-1 space-y-1 text-[12px] leading-relaxed text-slate-400">
              <p>检索了 3 个相似项目、2 条已确认经验和近 90 天业务数据，并获得 2 位数字员工的补充判断。</p>
              <button type="button" onClick={onOpenSources} className="text-mint-300 transition-colors hover:text-mint-200">
                查看全部资料
              </button>
            </div>
          )}
        </div>

        <div className="border-t border-white/[0.08] pt-4">
          <p className="whitespace-pre-wrap text-[14px] leading-[1.75] text-slate-100">{WORKSPACE_ANSWER}</p>
        </div>

        <button
          type="button"
          onClick={onOpenBrief}
          className="group flex w-full items-center gap-3.5 rounded-soft border border-white/[0.07] bg-surface-1 px-4 py-4 text-left transition-colors hover:border-white/[0.16] hover:bg-surface-2"
        >
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-soft bg-knowledge/12 text-knowledge">
            <FileText className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14px] font-semibold text-slate-100">{BRIEF.title}</div>
            <p className="mt-1 truncate text-[12.5px] text-slate-400">项目目标、历史经验、核心问题、设计原则、推荐方向和数据依据</p>
          </div>
          <span className="flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-slate-400 transition-colors group-hover:text-slate-200">
            查看
            <ArrowRight className="h-3.5 w-3.5" />
          </span>
        </button>

        <div className="space-y-2.5">
          <p className="text-[12px] leading-relaxed text-slate-400">本次引用的团队经验和资料来源已记录在 Brief 中。</p>
          <div className="flex flex-col items-start gap-2">
            {FOLLOW_UPS.map((followUp) => (
              <button
                key={followUp}
                type="button"
                onClick={() => showToast(`${followUp}（演示）`, 'info')}
                className="w-fit rounded-soft border border-white/[0.08] bg-surface-1 px-3 py-2 text-left text-[12.5px] text-slate-400 transition-colors hover:border-white/[0.18] hover:bg-surface-2 hover:text-slate-200"
              >
                {followUp}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
