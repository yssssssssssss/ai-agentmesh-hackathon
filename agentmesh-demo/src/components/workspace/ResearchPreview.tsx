import { ArrowDown, CircleHelp, Search, Sparkles } from 'lucide-react'

import type {
  ResearchRunProjection,
} from '../../features/workspace/types'

interface ResearchPreviewProps {
  projection: ResearchRunProjection
}

const PHASE_LABELS: Record<ResearchRunProjection['workflow']['phase'], string> = {
  requirement: '理解需求',
  planning: '制定计划',
  execution: '执行研究',
  result: '整理结果',
  terminal: '已结束',
}

const GATE_LABELS: Record<ResearchRunProjection['workflow']['active_gate'], string> = {
  none: '系统正在准备下一步',
  clarification: '需要补充研究范围',
  plan_confirmation: '推荐计划已就绪',
  tool_approval: '等待独立工具审批',
  recovery_decision: '需要确认恢复方式',
}

const STEP_TITLES: Record<string, string> = {
  'Research external evidence': '检索并封存外部证据',
  'Build competitive analysis': '基于证据生成竞品分析',
}

function actorLabel(actorType: 'tool' | 'skill', actorId: string): string {
  if (actorType === 'tool' && actorId === 'tool_web_research') return 'web_research'
  if (actorType === 'skill') return '$competitive-analysis'
  return '研究工具'
}

export function ResearchPreview({ projection }: ResearchPreviewProps) {
  const { workflow, requirement } = projection
  const plans = projection.plans ?? []
  const plan = plans.find((candidate) => candidate.recommended) ?? plans[0]
  const steps = plan?.steps ?? []
  const questions = requirement?.clarification_questions?.slice(0, 3) ?? []
  const hasStartedExecution = projection.attempt !== null && projection.attempt !== undefined
  const statusTitle = workflow.phase === 'terminal'
    ? projection.attempt?.status === 'completed'
      ? '研究结果已就绪'
      : projection.attempt?.status === 'cancelled'
        ? '研究已安全终止'
        : '研究已结束'
    : GATE_LABELS[workflow.active_gate]

  return (
    <section aria-label="研究任务预览" className="mt-6 overflow-hidden rounded-[16px] border border-mint-400/15 bg-surface-1 shadow-card">
      <div className="border-b border-white/[0.06] bg-gradient-to-r from-mint-400/[0.08] to-transparent px-5 py-5 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold text-mint-300">
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              竞品研究预览
            </div>
            <h2 className="mt-2 text-lg font-semibold text-slate-100">
              {statusTitle}
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              {PHASE_LABELS[workflow.phase]} · 状态版本 {workflow.state_version}
            </p>
          </div>
          <span className="rounded-full border border-amber-300/20 bg-amber-300/10 px-3 py-1 text-xs font-semibold text-amber-200">
            {hasStartedExecution ? '执行视图' : '计划预览'}
          </span>
        </div>
      </div>

      <div className="space-y-5 px-5 py-5 sm:px-6">
        {requirement ? (
          <section aria-labelledby="research-requirement-title">
            <h3 id="research-requirement-title" className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">
              系统理解的任务
            </h3>
            <p className="mt-3 text-base font-medium leading-7 text-slate-100">{requirement.research_goal}</p>
            <div className="mt-3 rounded-[10px] border border-white/[0.06] bg-base/60 px-4 py-3">
              <p className="text-[11px] font-semibold text-slate-500">对比范围</p>
              <p className="mt-1 text-sm text-slate-300">{requirement.competitor_scope ?? '待补充'}</p>
            </div>
          </section>
        ) : (
          <p role="status" className="text-sm text-slate-400">正在整理研究目标与范围…</p>
        )}

        {questions.length > 0 ? (
          <section aria-labelledby="research-questions-title" className="rounded-[12px] border border-amber-300/15 bg-amber-300/[0.06] p-4">
            <div className="flex items-center gap-2">
              <CircleHelp className="h-4 w-4 text-amber-200" aria-hidden="true" />
              <h3 id="research-questions-title" className="text-sm font-semibold text-amber-100">开始前需要澄清</h3>
            </div>
            <ol className="mt-3 space-y-2 pl-5 text-sm leading-6 text-slate-300">
              {questions.map((question) => (
                <li key={question.question_id} className="list-decimal pl-1">{question.prompt}</li>
              ))}
            </ol>
          </section>
        ) : null}

        {plan ? (
          <section aria-labelledby="research-plan-title">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 id="research-plan-title" className="text-sm font-semibold text-slate-100">推荐执行计划</h3>
                <p className="mt-1 text-xs text-slate-500">单一路径 · Plan v{plan.version}</p>
              </div>
              <span className="text-xs font-semibold text-mint-300">Tool → Skill</span>
            </div>
            <ol className="mt-4">
              {steps.map((step, index) => (
                <li key={step.step_number}>
                  <article className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 rounded-[12px] border border-white/[0.07] bg-base/60 p-4">
                    <span className="flex h-8 w-8 items-center justify-center rounded-full bg-mint-400/10 text-xs font-bold text-mint-300">
                      {step.step_number}
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                          {step.actor_type === 'tool' ? 'Tool' : 'Skill'}
                        </span>
                        <span className="text-xs text-slate-500">{actorLabel(step.actor_type, step.actor_id)}</span>
                      </div>
                      <p className="mt-2 text-sm font-medium text-slate-200">{STEP_TITLES[step.name] ?? step.name}</p>
                      <p className="mt-1 text-xs text-slate-500">{step.required ? '必需步骤' : '可选步骤'}</p>
                    </div>
                  </article>
                  {index < steps.length - 1 ? (
                    <div className="flex h-8 items-center justify-center text-slate-600" aria-hidden="true">
                      <ArrowDown className="h-4 w-4" />
                    </div>
                  ) : null}
                </li>
              ))}
            </ol>
          </section>
        ) : workflow.phase === 'planning' && questions.length === 0 && requirement ? (
          <div role="status" className="flex items-center gap-2 rounded-[10px] bg-base/60 px-4 py-3 text-sm text-slate-400">
            <Search className="h-4 w-4 text-mint-300" aria-hidden="true" />
            正在生成推荐研究计划…
          </div>
        ) : null}

        <p role="status" className="rounded-[10px] border border-white/[0.06] bg-base px-4 py-3 text-sm text-slate-400">
          {hasStartedExecution
            ? '执行状态已建立，请以当前研究进度为准。'
            : '尚未执行任何工具或 Skill。刷新或重新连接只会恢复这份预览。'}
        </p>
      </div>
    </section>
  )
}
