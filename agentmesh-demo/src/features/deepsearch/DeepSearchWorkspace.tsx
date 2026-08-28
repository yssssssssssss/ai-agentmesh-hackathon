import { BrainCircuit, RotateCcw, Square, TriangleAlert } from 'lucide-react'

import { SkillPlanPreview } from '../../components/workspace/SkillPlanPreview'
import { SkillPlanProgress } from '../../components/workspace/SkillPlanProgress'
import { Button } from '../../components/ui/Button'
import type {
  DeepSearchPlanDetailResponse,
  Skill,
  SkillPlanUpdateRequest,
  SkillPlanVersionRequest,
} from '../workspace/types'
import { activeDeepSearchStage } from './presentation'
import type { DeepSearchClarifyRequest, DeepSearchPlan, DeepSearchReport, DeepSearchState } from './types'
import { DeepSearchEvidenceStatus, DeepSearchReportView } from './DeepSearchEvidenceReport'
import { DeepSearchRequirementPanel } from './DeepSearchRequirementPanel'
import { DeepSearchStageRail } from './DeepSearchStageRail'

interface DeepSearchWorkspaceProps {
  state: DeepSearchState | undefined
  loading: boolean
  error: string | null
  skills: Skill[]
  planPendingAction: 'update' | 'approve' | 'reject' | null
  planError: string | null
  clarificationPending: boolean
  clarificationError: string | null
  report: DeepSearchReport | undefined
  reportLoading: boolean
  reportError: string | null
  cancelling: boolean
  retrying: boolean
  onClarify: (request: DeepSearchClarifyRequest) => void
  onUpdatePlan: (request: SkillPlanUpdateRequest) => void
  onApprovePlan: (request: SkillPlanVersionRequest) => void
  onRejectPlan: (request: SkillPlanVersionRequest) => void
  onCancel: () => void
  onRetry: () => void
  onReviseGoal: (goal: string) => void
  onOpenToolApproval: () => void
}

const TERMINAL_STATUSES = new Set(['completed', 'partial', 'failed', 'rejected', 'cancelled'])

const FAILURE_COPY: Record<string, string> = {
  deepsearch_clarification_unresolved: '三轮澄清后仍存在阻塞歧义。本次未执行任何检索，请修改目标后新建 DeepSearch。',
  deepsearch_planning_failed: '当前需求无法形成可验证的研究计划，本次没有降级为普通回答。',
  deepsearch_budget_exhausted: '本次研究已达到预算上限。只有满足安全发布条件时才会提供部分报告。',
  deepsearch_delivery_unavailable: '证据或交付条件不足，系统没有发布未经验证的研究结论。',
  deepsearch_evidence_integrity_failed: 'Evidence 的归属或完整性校验失败，系统已停止发布报告。',
  deepsearch_review_not_passed: '报告审核未通过。只有已排除争议结论的安全部分报告才会发布。',
}

function planDetailFromAggregate(plan: DeepSearchPlan): DeepSearchPlanDetailResponse {
  return {
    plan,
    results: [],
    synthesis: null,
  }
}

function DeepSearchPlanningPlaceholder({ cancelling, onCancel }: { cancelling: boolean; onCancel: () => void }) {
  return (
    <section aria-labelledby="deepsearch-planning-title" className="mt-4 rounded-soft bg-surface-1 px-5 py-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-soft bg-mint-400/10 text-mint-300">
            <span className="planning-orbit absolute inset-1 rounded-full border border-transparent border-t-mint-300/80" aria-hidden="true" />
            <BrainCircuit className="h-4 w-4" aria-hidden="true" />
          </span>
          <div role="status" aria-live="polite">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-mint-300">Requirement</p>
            <h2 id="deepsearch-planning-title" className="mt-1.5 text-base font-semibold text-slate-100">正在建立需求边界</h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-400">
              系统正在提取目标、范围、交付物和成功标准。需要决定的歧义会在执行前向你提问。
            </p>
          </div>
        </div>
        <Button variant="danger" size="sm" loading={cancelling} icon={<Square className="h-3.5 w-3.5" />} onClick={onCancel}>
          取消
        </Button>
      </div>
    </section>
  )
}

function ProblemGraphSummary({ state }: { state: DeepSearchState }) {
  if (!state.problem_graph) return null
  return (
    <section aria-labelledby="deepsearch-questions-title" className="mt-4 rounded-soft bg-surface-1 px-5 py-5 shadow-card">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-mint-300">Problem graph</p>
      <h2 id="deepsearch-questions-title" className="mt-1.5 text-base font-semibold text-slate-100">研究问题</h2>
      <ol className="mt-4 divide-y divide-white/[0.06] border-y border-white/[0.06]">
        {state.problem_graph.questions.map((question, index) => (
          <li key={question.id} className="grid gap-2 py-3 sm:grid-cols-[2rem_minmax(0,1fr)_auto] sm:items-start">
            <span className="font-mono text-xs text-slate-400">{String(index + 1).padStart(2, '0')}</span>
            <div>
              <p className="text-sm leading-6 text-slate-200">{question.question}</p>
              <p className="mt-1 text-[11px] text-slate-400">需要 {question.evidence_requirements.length} 项 Evidence 条件</p>
            </div>
            <span className={question.required ? 'text-[11px] text-mint-300' : 'text-[11px] text-slate-400'}>
              {question.required ? '必需' : '可选'}
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}

export function DeepSearchWorkspace({
  state,
  loading,
  error,
  skills,
  planPendingAction,
  planError,
  clarificationPending,
  clarificationError,
  report,
  reportLoading,
  reportError,
  cancelling,
  retrying,
  onClarify,
  onUpdatePlan,
  onApprovePlan,
  onRejectPlan,
  onCancel,
  onRetry,
  onReviseGoal,
  onOpenToolApproval,
}: DeepSearchWorkspaceProps) {
  if (loading && !state) {
    return (
      <section role="status" className="mt-6 rounded-soft bg-surface-1 px-5 py-8 text-center text-sm text-slate-400 shadow-card">
        正在恢复 DeepSearch 状态…
      </section>
    )
  }
  if (error && !state) {
    return <p role="alert" className="mt-6 rounded-soft bg-rose/10 px-4 py-3 text-sm text-rose">{error}</p>
  }
  if (!state) return null

  const run = state.run
  const terminal = TERMINAL_STATUSES.has(run.status)
  const activeStage = activeDeepSearchStage(state)
  const mergedPlanDetail = state.plan ? planDetailFromAggregate(state.plan) : null
  const skillsById = new Map(skills.map((skill) => [skill.id, skill]))
  const finalizationStarted = state.plan?.finalization_stage !== undefined
    && state.plan.finalization_stage !== 'none'
  const showEvidence = Boolean(
    state.plan
    && run.status !== 'waiting_plan_approval'
    && (finalizationStarted || ['running', 'waiting_approval', 'completed', 'partial', 'failed'].includes(run.status)),
  )

  return (
    <div data-testid="deepsearch-workspace" className="animate-fade-in motion-reduce:animate-none">
      <DeepSearchStageRail
        activeStage={activeStage}
        terminal={terminal}
        reportPublished={Boolean(state.plan?.report_artifact_id)}
      />
      {error ? (
        <p role="alert" className="mt-3 rounded-soft border border-amber-300/20 bg-amber-300/[0.07] px-4 py-3 text-xs leading-5 text-amber-100">
          {error} 当前展示的是最近一次已读取状态。
        </p>
      ) : null}

      {!state.active_requirement && ['created', 'planning'].includes(run.status) ? (
        <DeepSearchPlanningPlaceholder cancelling={cancelling} onCancel={onCancel} />
      ) : null}

      {state.active_requirement ? (
        <DeepSearchRequirementPanel
          key={`${state.active_requirement.id}:${state.active_requirement.version}`}
          requirement={state.active_requirement}
          planExists={Boolean(state.plan)}
          waitingForClarification={run.status === 'waiting_clarification'}
          submitting={clarificationPending}
          error={clarificationError}
          onSubmit={onClarify}
        />
      ) : null}

      {run.status === 'waiting_clarification' ? (
        <div className="mt-3 flex justify-end">
          <Button variant="danger" size="sm" loading={cancelling} onClick={onCancel}>取消 DeepSearch</Button>
        </div>
      ) : null}

      <ProblemGraphSummary state={state} />

      {run.status === 'waiting_plan_approval' && mergedPlanDetail ? (
        <SkillPlanPreview
          key={`${mergedPlanDetail.plan.id}-${mergedPlanDetail.plan.version}`}
          detail={mergedPlanDetail}
          candidates={skills}
          orchestrationMode="execute"
          blockApprovalForCapabilityGaps
          pendingAction={planPendingAction}
          error={planError}
          onUpdate={onUpdatePlan}
          onApprove={onApprovePlan}
          onReject={onRejectPlan}
        />
      ) : null}

      {state.plan && mergedPlanDetail && run.status !== 'waiting_plan_approval' ? (
        <SkillPlanProgress
          run={run}
          detail={mergedPlanDetail}
          skillsById={skillsById}
          cancelling={cancelling}
          onCancel={onCancel}
          onOpenToolApproval={onOpenToolApproval}
        />
      ) : null}

      {showEvidence ? (
        <DeepSearchEvidenceStatus
          finalizationStage={state.plan?.finalization_stage}
          coverage={state.evidence_coverage}
          review={state.report_review}
          sourceCount={state.evidence_coverage?.validated_source_ids.length ?? 0}
          terminal={terminal}
        />
      ) : null}

      {reportLoading ? (
        <section role="status" className="mt-4 rounded-soft bg-surface-1 px-5 py-7 text-center text-sm text-slate-400 shadow-card">
          正在读取已封存报告…
        </section>
      ) : null}
      {reportError ? <p role="alert" className="mt-4 rounded-soft bg-rose/10 px-4 py-3 text-sm text-rose">{reportError}</p> : null}
      {report ? <DeepSearchReportView report={report} reportRunId={run.id} /> : null}

      {terminal && !state.plan?.report_artifact_id && run.status === 'failed' ? (
        <section role="alert" className="mt-4 rounded-soft border border-rose/20 bg-rose/10 px-5 py-4">
          <div className="flex items-start gap-2.5">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose" aria-hidden="true" />
            <div>
              <p className="text-sm font-semibold text-rose">本次未发布报告</p>
              <p className="mt-1 text-xs leading-5 text-slate-300">
                {(run.error_code && FAILURE_COPY[run.error_code]) || '研究流程没有满足可信 Evidence、Review 和报告封存条件。'}
              </p>
              {run.error_code ? <code className="mt-2 block text-[11px] text-slate-400">{run.error_code}</code> : null}
            </div>
          </div>
        </section>
      ) : null}
      {terminal && !state.plan?.report_artifact_id && ['completed', 'partial'].includes(run.status) ? (
        <p role="alert" className="mt-4 rounded-soft border border-rose/20 bg-rose/10 px-4 py-3 text-sm text-rose">
          运行状态与 sealed Report 不一致，客户端不会展示未封存的报告内容。
        </p>
      ) : null}

      {terminal && state.retry_disposition !== 'none' ? (
        <div className="mt-4 flex justify-end">
          {state.retry_disposition === 'retry_run' ? (
            <Button variant="secondary" size="sm" loading={retrying} icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={onRetry}>
              以新 Run 重试
            </Button>
          ) : (
            <Button variant="secondary" size="sm" onClick={() => onReviseGoal(state.active_requirement?.payload.goal ?? run.input_text)}>
              修改目标并新建
            </Button>
          )}
        </div>
      ) : null}
    </div>
  )
}
