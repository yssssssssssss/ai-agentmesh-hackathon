import {
  Ban,
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  Loader2,
  Pause,
  RotateCcw,
  SkipForward,
  X,
} from 'lucide-react'

import type { PlanNodeView, Skill, SkillNodeResult } from '../../features/workspace/types'
import { cn } from '../../lib/cn'
import {
  degradationCopy,
  failurePolicy,
  nodeStatusDescription,
  skillStatusLabel,
} from './skillPlanPresentation'

interface SkillPlanNodeCardProps {
  node: PlanNodeView
  skill?: Skill
  result?: SkillNodeResult
  mode: 'preview' | 'progress'
  selected?: boolean
  disabled?: boolean
  canMoveUp?: boolean
  canMoveDown?: boolean
  onToggle?: (skillId: string) => void
  onMove?: (skillId: string, direction: 'up' | 'down') => void
  onSelectOnly?: (skillId: string) => void
}

const STATUS = {
  pending: { label: '等待开始', icon: Circle, tone: 'text-slate-400', dot: 'bg-slate-600' },
  ready: { label: '即将开始', icon: RotateCcw, tone: 'text-knowledge', dot: 'bg-knowledge' },
  running: { label: '正在分析', icon: Loader2, tone: 'text-mint-300', dot: 'bg-mint-400' },
  waiting_tool_approval: { label: '等待高风险操作确认', icon: Pause, tone: 'text-amber-300', dot: 'bg-amber-300' },
  completed: { label: '已完成', icon: Check, tone: 'text-mint-300', dot: 'bg-mint-400' },
  failed: { label: '执行失败', icon: X, tone: 'text-rose', dot: 'bg-rose' },
  skipped: { label: '未执行', icon: SkipForward, tone: 'text-slate-400', dot: 'bg-slate-600' },
  cancelled: { label: '已取消', icon: Ban, tone: 'text-slate-400', dot: 'bg-slate-600' },
} as const

const SIDE_EFFECT_LABEL = {
  read: '只读',
  draft: '生成草稿',
  local_write: '本地写入，调用时审批',
  external_write: '外部写入，调用时审批',
} as const

export function SkillPlanNodeCard({
  node,
  skill,
  result,
  mode,
  selected = true,
  disabled = false,
  canMoveUp = false,
  canMoveDown = false,
  onToggle,
  onMove,
  onSelectOnly,
}: SkillPlanNodeCardProps) {
  const status = STATUS[node.status]
  const StatusIcon = status.icon
  const nodeKey = node.id ?? node.skill_id
  const interactive = mode === 'preview'
  const skillStatus = 'skill_status' in node ? node.skill_status : undefined
  const inputBindings = 'input_bindings' in node ? node.input_bindings : undefined
  const knowledgeBindings = 'knowledge_bindings' in node ? node.knowledge_bindings : undefined
  const registryStatus = skillStatusLabel(skillStatus)
  const resultNotice = result?.degradation ? degradationCopy(result.degradation) : null

  return (
    <article
      data-node-status={node.status}
      className={cn(
        'rounded-soft bg-base px-4 py-3.5 shadow-input',
        !selected && 'opacity-45',
      )}
    >
      <div
        className={cn(
          'grid items-start gap-3',
          interactive
            ? 'grid-cols-[auto_minmax(0,1fr)] sm:grid-cols-[auto_minmax(0,1fr)_auto]'
            : 'grid-cols-[auto_minmax(0,1fr)]',
        )}
      >
        {interactive ? (
          <button
            type="button"
            aria-label={`${selected ? '移除' : '加入'} ${skill?.title ?? node.skill_id}`}
            aria-pressed={selected}
            disabled={disabled || node.required}
            onClick={() => onToggle?.(node.skill_id)}
            className={cn(
              'mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-soft transition-[transform,background-color,color] duration-150 active:scale-95',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50',
              selected ? 'bg-mint-400/12 text-mint-300' : 'bg-white/[0.04] text-slate-400',
              (disabled || node.required) && 'cursor-not-allowed',
            )}
          >
            {selected ? <Check className="h-4 w-4" aria-hidden="true" /> : <Circle className="h-4 w-4" aria-hidden="true" />}
          </button>
        ) : (
          <span className={cn('mt-1 h-2.5 w-2.5 shrink-0 rounded-full', status.dot, node.status === 'running' && 'animate-pulse motion-reduce:animate-none')} />
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 className="text-sm font-semibold text-slate-100">{skill?.title ?? node.skill_id}</h3>
            <span className="rounded-full bg-white/[0.05] px-2 py-0.5 text-[11px] text-slate-400">
              {node.required ? '必需节点' : '可选节点'}
            </span>
            {registryStatus ? (
              <span
                className="rounded-full bg-amber-300/10 px-2 py-0.5 text-[11px] text-amber-300"
                title={skillStatus === 'draft' ? '合约已自动校验，但仍处于草案状态' : undefined}
              >
                {registryStatus}
              </span>
            ) : null}
            {node.scenario_id ? (
              <span className="rounded-full bg-white/[0.05] px-2 py-0.5 text-[11px] text-slate-400">
                {node.scenario_id}
              </span>
            ) : null}
            {node.parallel_group ? (
              <span
                className="rounded-full bg-knowledge/10 px-2 py-0.5 text-[11px] text-knowledge"
                title={`执行组 ${node.parallel_group}`}
              >
                可与其他步骤并行
              </span>
            ) : null}
          </div>
          <p className="mt-1.5 text-xs leading-5 text-slate-400">{node.reason}</p>
          <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-400">
            <div className="flex gap-1"><dt>输入</dt><dd className="text-slate-300">{(inputBindings ?? []).join('、') || '当前请求'}</dd></div>
            <div className="flex gap-1"><dt>产出</dt><dd className="text-slate-300">{(node.output_contract ?? []).join('、') || '标准化结果'}</dd></div>
            <div className="flex gap-1"><dt>边界</dt><dd className="text-slate-300">{SIDE_EFFECT_LABEL[node.side_effect]}</dd></div>
          </dl>
          {(node.required_tool_names ?? []).length > 0 ? (
            <p className="mt-2 text-[11px] text-knowledge">工具：{(node.required_tool_names ?? []).join('、')}</p>
          ) : null}
          {((knowledgeBindings?.required ?? []).length + (knowledgeBindings?.optional ?? []).length) > 0 ? (
            <p className="mt-1 text-[11px] text-slate-400">
              知识资料：必需 {knowledgeBindings?.required?.length ?? 0}，按需 {knowledgeBindings?.optional?.length ?? 0}
            </p>
          ) : null}
          {(node.completion_criteria ?? []).length > 0 ? (
            <p className="mt-1 text-[11px] text-slate-400">完成标准：{(node.completion_criteria ?? []).join('；')}</p>
          ) : null}
          {(node.depends_on ?? []).length > 0 ? (
            <p className="mt-2 text-[11px] text-slate-400">依赖：{node.depends_on?.join('、')}</p>
          ) : null}
          {mode === 'progress' ? (
            <div className="mt-2.5 rounded-soft border border-white/[0.05] bg-surface-1/55 px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <span className={cn('inline-flex items-center gap-1 font-semibold', status.tone)}>
                  <StatusIcon className={cn('h-3.5 w-3.5', node.status === 'running' && 'animate-spin motion-reduce:animate-none')} aria-hidden="true" />
                  {status.label}
                </span>
                {node.attempt > 0 ? <span className="text-slate-400">第 {node.attempt} 次执行</span> : null}
              </div>
              <p className={cn('mt-1.5 text-[11px] leading-5', node.status === 'failed' ? 'text-rose/90' : 'text-slate-400')}>
                {nodeStatusDescription(node)}
              </p>
              {node.status === 'failed' ? (
                <p className="mt-1.5 text-[11px] leading-5 text-slate-400">{failurePolicy(node.error_code, node.attempt)}</p>
              ) : null}
              {node.error_code ? (
                <details className="mt-1.5 text-[11px] text-slate-400">
                  <summary className="cursor-pointer select-none hover:text-slate-300">查看技术原因</summary>
                  <code className="mt-1 block break-all">{node.error_code}</code>
                </details>
              ) : null}
            </div>
          ) : null}
          {result ? (
            <div className="mt-3 border-t border-white/[0.06] pt-2.5">
              <p className="text-xs leading-5 text-slate-300">{result.summary}</p>
              {resultNotice ? (
                <div className="mt-2 rounded-control bg-amber-300/[0.06] px-2.5 py-2 text-[11px] leading-5 text-amber-100">
                  <span className="font-semibold">{resultNotice.title}：</span>{resultNotice.description}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {interactive ? (
          <div className="col-span-2 flex shrink-0 items-center justify-end gap-1 border-t border-white/[0.06] pt-2 sm:col-span-1 sm:border-t-0 sm:pt-0">
            <button
              type="button"
              aria-label={`上移 ${skill?.title ?? nodeKey}`}
              disabled={disabled || !selected || !canMoveUp}
              onClick={() => onMove?.(node.skill_id, 'up')}
              className="flex h-10 w-10 items-center justify-center rounded-soft text-slate-400 transition-[transform,background-color,color] duration-150 active:scale-95 hover:bg-white/[0.05] hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
            >
              <ChevronUp className="h-4 w-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              aria-label={`下移 ${skill?.title ?? nodeKey}`}
              disabled={disabled || !selected || !canMoveDown}
              onClick={() => onMove?.(node.skill_id, 'down')}
              className="flex h-10 w-10 items-center justify-center rounded-soft text-slate-400 transition-[transform,background-color,color] duration-150 active:scale-95 hover:bg-white/[0.05] hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
            >
              <ChevronDown className="h-4 w-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onSelectOnly?.(node.skill_id)}
              className="min-h-10 rounded-soft px-2 text-[11px] font-medium text-slate-400 transition-[transform,background-color,color] duration-150 active:scale-95 hover:bg-white/[0.05] hover:text-slate-200 disabled:opacity-40"
            >
              仅此项
            </button>
          </div>
        ) : null}
      </div>
    </article>
  )
}
