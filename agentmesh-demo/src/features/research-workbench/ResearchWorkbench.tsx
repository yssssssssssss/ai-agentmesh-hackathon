import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from 'react'

import { buildResearchDag, describeResearchDag } from './dag'
import { presentWorkbench, type CurrentWorkbenchPresentation } from './presenter'
import type {
  ActorType,
  ExecutionPlanVersionV3,
  PlanCandidateV3,
  ReportBlockV3,
  ResearchTaskV3,
  ResearchV2HistoryWorkbenchAggregateV1,
  ResearchV3WorkbenchAggregateV1,
  ResearchWorkbenchActions,
  StepStatus,
  WorkbenchAggregateV1,
  WorkbenchApprovalV1,
} from './types'
import './research-workbench.css'

export interface ResearchWorkbenchProps {
  aggregate?: WorkbenchAggregateV1 | null
  status?: 'ready' | 'loading' | 'error'
  errorMessage?: string
  actions?: ResearchWorkbenchActions
  className?: string
}

export function ResearchWorkbench({
  aggregate,
  status = 'ready',
  errorMessage = '研究任务暂时无法读取。',
  actions = {},
  className = '',
}: ResearchWorkbenchProps) {
  const rootClassName = `research-workbench-current${className ? ` ${className}` : ''}`

  if (status === 'loading') {
    return (
      <section className={rootClassName} data-workbench-state="loading">
        <div className="rw-flow"><LoadingState /></div>
      </section>
    )
  }
  if (status === 'error' || !aggregate) {
    return (
      <section className={rootClassName} data-workbench-state="error">
        <div className="rw-flow"><ErrorState message={errorMessage} onRetry={actions.onRetryLoad} /></div>
      </section>
    )
  }

  const presentation = presentWorkbench(aggregate)
  if (presentation.kind === 'history') {
    return (
      <section className={rootClassName} data-workbench-state="history" data-projection-kind={aggregate.projection_kind}>
        <div className="rw-flow"><ResearchV2History aggregate={presentation.aggregate} /></div>
      </section>
    )
  }

  return (
    <section
      className={rootClassName}
      data-workbench-state={presentation.state}
      data-projection-kind={aggregate.projection_kind}
      aria-label={`研究工作台：${presentation.stateLabel}`}
    >
      <div className={presentation.showReport ? 'rw-report-flow' : 'rw-flow'}>
        <CurrentWorkbench presentation={presentation} actions={actions} />
      </div>
    </section>
  )
}

function CurrentWorkbench({
  presentation,
  actions,
}: {
  presentation: CurrentWorkbenchPresentation
  actions: ResearchWorkbenchActions
}) {
  const { aggregate } = presentation
  const task = aggregate.requirement?.payload

  if (presentation.showWelcome) return <Welcome onPick={actions.onSuggestion} />

  return (
    <>
      {task ? <UserBubble text={task.research_goal} /> : null}
      {presentation.showClarification && task ? (
        <Stage1Clarify task={task} onSubmit={actions.onClarificationSubmit} />
      ) : null}
      {presentation.showRequirement && task ? (
        <Stage1Understand task={task} activatedNodes={aggregate.selected_plan?.payload.activated_nodes ?? []} />
      ) : null}
      {presentation.showCandidates && aggregate.candidates ? (
        <Stage2Candidates
          candidates={aggregate.candidates.candidates}
          onSelect={actions.onCandidateSelect}
        />
      ) : null}
      {presentation.showPlan && aggregate.selected_plan ? (
        <Stage2Plan
          plan={aggregate.selected_plan}
          task={task}
          locked={presentation.showApproval}
          onConfirm={actions.onPlanConfirm}
          onRevise={actions.onPlanRevise}
        />
      ) : null}
      {presentation.showApproval ? (
        <ApprovalReadyStage approvals={aggregate.approvals} onApprove={actions.onApprove} onExecute={actions.onExecute} />
      ) : null}
      {presentation.showDag && aggregate.selected_plan ? (
        <Stage3Dag aggregate={aggregate} />
      ) : null}
      {aggregate.selected_plan?.payload.capability_gaps.length ? (
        <GapNotice gaps={aggregate.selected_plan.payload.capability_gaps} />
      ) : null}
      {presentation.showRecovery && aggregate.recovery ? (
        <PausedRecoveryStage aggregate={aggregate} onAction={actions.onRecoveryAction} />
      ) : null}
      {presentation.showReport && aggregate.report ? (
        <Stage4TextReport aggregate={aggregate} />
      ) : null}
    </>
  )
}

export function Welcome({ onPick }: { onPick?: (suggestion: string) => void }) {
  const suggestions = [
    '我要为直播场域做一次数字人竞品研究',
    '帮我规划一次直播带货的用户体验研究',
    '分析虚拟主播赛道的主要竞品差异',
  ]
  return (
    <div className="rw-welcome">
      <p className="rw-eyebrow">RESEARCH WORKBENCH</p>
      <h1>你想研究什么？</h1>
      <p>输入一句话，我会给出两份可比较的方案 ·「深度优先 / 速度优先」由你挑一份。</p>
      <div className="rw-welcome-suggestions" aria-label="研究任务示例">
        {suggestions.map((suggestion) => (
          <button key={suggestion} type="button" onClick={() => onPick?.(suggestion)}>{suggestion}</button>
        ))}
      </div>
    </div>
  )
}

export function UserBubble({ text }: { text: string }) {
  return <div className="rw-user-row"><p className="rw-user-bubble">{text}</p></div>
}

function StageHeader({ number, title, note }: { number: string; title: string; note?: string }) {
  return (
    <header className="rw-stage-header">
      <span className="rw-stage-number" aria-hidden="true">{number}</span>
      <h2>{title}</h2>
      {note ? <span>· {note}</span> : null}
    </header>
  )
}

export function Stage1Understand({ task, activatedNodes }: { task: ResearchTaskV3; activatedNodes: string[] }) {
  return (
    <article className="rw-stage-card" data-stage="understand">
      <StageHeader number="1" title="任务理解" note="由 AI 结构化为 ResearchTask" />
      <dl className="rw-definition-grid">
        <dt>任务类型</dt><dd><code>{task.task_type}</code></dd>
        <dt>业务场域</dt><dd><code>{task.business_domain}</code></dd>
        <dt>研究目标</dt><dd>{task.research_goal}</dd>
        <dt>研究范围</dt><dd>{task.scope.length ? task.scope.join(' · ') : '待澄清'}</dd>
        <dt>比较维度</dt><dd>{task.comparison_dimensions?.join(' · ') ?? '未指定'}</dd>
        <dt>决策节点</dt>
        <dd className="rw-dim-text">
          {activatedNodes.length ? `${activatedNodes.length} 个 · ${activatedNodes.join(' / ')}` : '将在规划后激活'}
        </dd>
      </dl>
      {task.assumptions.length ? (
        <div className="rw-assumptions">
          <h3>系统假设</h3>
          <ul>{task.assumptions.map((assumption) => <li key={assumption.key}><b>{assumption.key}</b>：{assumption.value}</li>)}</ul>
        </div>
      ) : null}
    </article>
  )
}

export function Stage1Clarify({
  task,
  onSubmit,
}: {
  task: ResearchTaskV3
  onSubmit?: ResearchWorkbenchActions['onClarificationSubmit']
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const missing = task.clarification_questions.filter((question) => !answers[question.key]?.trim())

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (missing.length === 0) onSubmit?.(answers)
  }

  return (
    <form className="rw-stage-card" data-stage="clarify" aria-labelledby="rw-clarify-title" onSubmit={submit}>
      <StageHeader number="1" title="澄清需求" note="先确认缺少的信息，再生成候选方案" />
      <div className="rw-current-understanding">
        <h3 id="rw-clarify-title">当前理解</h3>
        <p>{task.research_goal}</p>
        <span>{task.business_domain} · {task.task_type}</span>
      </div>
      {task.ambiguities.length ? (
        <section className="rw-ambiguities">
          <h3>仍有歧义</h3>
          <ul>{task.ambiguities.map((item) => <li key={item.id}>{item.statement}{item.blocking ? '（需回答）' : ''}</li>)}</ul>
        </section>
      ) : null}
      <div className="rw-question-list">
        {task.clarification_questions.map((question) => (
          <label key={question.key}>
            <b>{question.question}</b>
            <span>为什么要问：{question.rationale}</span>
            <input
              value={answers[question.key] ?? ''}
              onChange={(event) => setAnswers((current) => ({ ...current, [question.key]: event.target.value }))}
              placeholder="请明确回答，系统建议不会自动代替你的回答"
            />
          </label>
        ))}
      </div>
      <button className="rw-button-primary" type="submit" disabled={missing.length > 0 || !onSubmit}>
        {missing.length ? `请回答全部必答问题（还缺 ${missing.length} 项）` : '提交澄清并更新候选方案'}
      </button>
    </form>
  )
}

export function Stage2Candidates({
  candidates,
  selectedId,
  onSelect,
  readOnly = false,
}: {
  candidates: readonly PlanCandidateV3[]
  selectedId?: PlanCandidateV3['candidate_id']
  onSelect?: ResearchWorkbenchActions['onCandidateSelect']
  readOnly?: boolean
}) {
  const initialIndex = Math.max(0, candidates.findIndex((candidate) => candidate.candidate_id === selectedId))
  const [currentIndex, setCurrentIndex] = useState(initialIndex)
  const [chosenId, setChosenId] = useState(selectedId)
  const cards = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => {
    setCurrentIndex(initialIndex)
    setChosenId(selectedId)
  }, [initialIndex, selectedId])

  function focusCandidate(index: number) {
    setCurrentIndex(index)
    if (typeof window !== 'undefined') window.requestAnimationFrame(() => cards.current[index]?.focus())
  }

  function navigate(event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || candidates.length === 0) return
    let nextIndex: number | null = null
    if (event.key === 'ArrowLeft') nextIndex = Math.max(0, currentIndex - 1)
    if (event.key === 'ArrowRight') nextIndex = Math.min(candidates.length - 1, currentIndex + 1)
    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = candidates.length - 1
    if (nextIndex === null) return
    event.preventDefault()
    focusCandidate(nextIndex)
  }

  function choose(candidate: PlanCandidateV3, index: number) {
    if (index !== currentIndex) {
      focusCandidate(index)
      return
    }
    setChosenId(candidate.candidate_id)
    onSelect?.(candidate.candidate_id)
  }

  const trackStyle = { '--rw-candidate-offset': `${currentIndex * -82}%` } as CSSProperties
  const currentCandidate = candidates[currentIndex]

  return (
    <article className="rw-stage-card rw-candidate-stage" data-stage="candidates">
      <StageHeader number="2" title="待选执行方案" note={readOnly ? '左右查看，旧任务不可修改' : '左右对比，点击主卡片选择'} />
      <div
        className="rw-candidate-carousel"
        role="region"
        aria-roledescription="carousel"
        aria-label="执行方案"
        onKeyDown={navigate}
      >
        <div className="rw-candidate-viewport">
          <div className="rw-candidate-track" style={trackStyle}>
            {candidates.map((candidate, index) => {
              const current = index === currentIndex
              const chosen = candidate.candidate_id === chosenId
              return (
                <div
                  key={candidate.candidate_id}
                  className={`rw-candidate-slide${current ? ' is-current' : ''}`}
                  role="group"
                  aria-roledescription="slide"
                  aria-label={`${index + 1} / ${candidates.length}`}
                >
                  <button
                    ref={(element) => { cards.current[index] = element }}
                    type="button"
                    className={`rw-candidate-card${chosen ? ' is-active' : ''}`}
                    aria-label={`${current ? '选择' : '查看'}方案：${candidate.title}`}
                    aria-pressed={chosen}
                    disabled={readOnly}
                    tabIndex={current ? 0 : -1}
                    onClick={() => choose(candidate, index)}
                  >
                    <div className="rw-candidate-head">
                      <span className={`rw-candidate-tag tone-${candidate.candidate_id}`}>
                        {candidate.candidate_id === 'depth' ? '深度优先' : '速度优先'}
                      </span>
                      <b>{candidate.title}</b>
                    </div>
                    <p>{candidate.rationale}</p>
                    <div className="rw-candidate-tradeoff"><span>代价</span>{candidate.tradeoffs}</div>
                    <ol className="rw-candidate-steps">
                      {candidate.proposed_steps.map((step) => (
                        <li key={step.proposed_step_number}>
                          <ActorBadge actorType={step.actor_type} />
                          <span>{step.name}</span>
                          <code title={step.actor_id}>{step.actor_id}</code>
                        </li>
                      ))}
                    </ol>
                    <div className="rw-candidate-meta">
                      <span>共 {candidate.proposed_steps.length} 步</span>
                      <span>{readOnly ? '只读预览' : current ? '点击选择' : '点击查看'}</span>
                    </div>
                  </button>
                </div>
              )
            })}
          </div>
        </div>
        {candidates.length > 1 ? (
          <div className="rw-carousel-controls" aria-label="方案滑动导航">
            <button type="button" aria-label="上一个方案" disabled={currentIndex === 0} onClick={() => focusCandidate(currentIndex - 1)}>‹</button>
            <span aria-hidden="true">{String(currentIndex + 1).padStart(2, '0')} / {String(candidates.length).padStart(2, '0')}</span>
            <div className="rw-carousel-dots">
              {candidates.map((candidate, index) => (
                <button
                  key={candidate.candidate_id}
                  type="button"
                  className={index === currentIndex ? 'is-current' : ''}
                  aria-current={index === currentIndex ? 'true' : undefined}
                  aria-label={`查看第 ${index + 1} 个方案：${candidate.title}`}
                  tabIndex={index === currentIndex ? 0 : -1}
                  onClick={() => focusCandidate(index)}
                />
              ))}
            </div>
            <button type="button" aria-label="下一个方案" disabled={currentIndex === candidates.length - 1} onClick={() => focusCandidate(currentIndex + 1)}>›</button>
          </div>
        ) : null}
        <p className="rw-sr-only" aria-live="polite">
          {currentCandidate ? `正在查看第 ${currentIndex + 1} 个方案：${currentCandidate.title}` : '暂无可选方案'}
        </p>
      </div>
    </article>
  )
}

export function Stage2Plan({
  plan,
  task,
  locked,
  onConfirm,
  onRevise,
}: {
  plan: ExecutionPlanVersionV3
  task?: ResearchTaskV3
  locked: boolean
  onConfirm?: () => void
  onRevise?: () => void
}) {
  return (
    <article className="rw-stage-card" data-stage="plan">
      <StageHeader number="2" title="待执行计划" note={locked ? '计划内容已锁定' : '确认前不执行'} />
      <div className="rw-plan-summary">
        <span className={`rw-candidate-tag tone-${plan.payload.candidate_id}`}>{plan.payload.candidate_title}</span>
        <p>{plan.payload.candidate_rationale}</p>
        <small>{plan.payload.candidate_tradeoffs}</small>
      </div>
      <ol className="rw-plan-steps">
        {plan.payload.steps.map((step) => (
          <li key={step.step_number}>
            <span className="rw-plan-step-number">{step.step_number}</span>
            <div><b>{step.name}</b><span>{step.expected_outputs.map((output) => output.description).join(' · ')}</span></div>
            <ActorBadge actorType={step.actor_type} />
            {step.requires_approval ? <span className="rw-approval-badge">需审批</span> : null}
          </li>
        ))}
      </ol>
      {task?.assumptions.length ? (
        <section className="rw-plan-assumptions">
          <h3>系统假设</h3>
          {task.assumptions.map((assumption) => <p key={assumption.key}><span>{assumption.key}</span>{assumption.value}</p>)}
        </section>
      ) : null}
      {!locked ? (
        <div className="rw-button-row">
          <button type="button" className="rw-button-primary" disabled={!onConfirm} onClick={onConfirm}>✓ 确认计划</button>
          <button type="button" className="rw-button-ghost" disabled={!onRevise} onClick={onRevise}>调整计划</button>
        </div>
      ) : <p className="rw-locked-note">✓ 计划已确认，内容已锁定</p>}
    </article>
  )
}

export function ApprovalReadyStage({
  approvals,
  onApprove,
  onExecute,
}: {
  approvals: readonly WorkbenchApprovalV1[]
  onApprove?: ResearchWorkbenchActions['onApprove']
  onExecute?: ResearchWorkbenchActions['onExecute']
}) {
  const pending = approvals.filter((approval) => approval.decision === 'pending')
  const ready = approvals.length > 0 && pending.length === 0 && approvals.every((approval) => approval.decision === 'approved')
  const roleLabels: Record<WorkbenchApprovalV1['role'], string> = { owner: '任务负责人', legal: '法务', security: '安全' }
  return (
    <article className="rw-stage-card" data-stage="approval" aria-live="polite">
      <StageHeader number="2" title={ready ? '计划已就绪' : '计划等待授权审批'} note={ready ? '需要明确开始执行' : '未批准前不会执行'} />
      <div className="rw-approval-list">
        {approvals.map((approval) => (
          <div key={approval.gate_key}>
            <div><b>{humanize(approval.gate_key)}</b><span>{roleLabels[approval.role]} · {approvalDecisionLabel(approval.decision)}</span></div>
            {approval.decision === 'pending' ? (
              <button type="button" className="rw-button-primary" disabled={!onApprove} onClick={() => onApprove?.(approval.gate_key)}>批准</button>
            ) : null}
          </div>
        ))}
      </div>
      {ready ? <button type="button" className="rw-button-primary" disabled={!onExecute} onClick={onExecute}>开始执行</button> : null}
    </article>
  )
}

function approvalDecisionLabel(decision: WorkbenchApprovalV1['decision']): string {
  if (decision === 'approved') return '已批准'
  if (decision === 'rejected') return '已拒绝'
  return '待审批'
}

function humanize(value: string): string {
  return value.replace(/_/g, ' ')
}

function ActorBadge({ actorType }: { actorType: ActorType }) {
  const labels: Record<ActorType, string> = { tool: 'TOOL', skill: 'SKILL', llm: 'MODEL', reviewer: 'REVIEW' }
  return <span className={`rw-actor-badge actor-${actorType}`}>{labels[actorType]}</span>
}

const STATUS_LABELS: Record<StepStatus, string> = {
  pending: '等待',
  running: '运行中',
  succeeded: '完成',
  failed: '失败',
  skipped: '已跳过',
}

export function Stage3Dag({ aggregate }: { aggregate: ResearchV3WorkbenchAggregateV1 }) {
  const markerId = `rw-dag-arrow-${useId().replace(/:/g, '')}`
  const steps = aggregate.selected_plan?.payload.steps ?? []
  const dag = useMemo(() => buildResearchDag(steps, aggregate.attempt?.steps), [aggregate.attempt?.steps, steps])
  const description = describeResearchDag(dag)
  const completed = dag.nodes.filter((node) => node.status === 'succeeded' || node.status === 'skipped').length
  const graphWidth = Math.max(220, dag.layers.length * 238)
  const graphHeight = Math.max(168, ...dag.layers.map((layer) => layer.length * 108 + 36))
  const positions = new Map<number, { x: number; y: number }>()
  dag.layers.forEach((layer, layerIndex) => {
    layer.forEach((stepNumber, rowIndex) => positions.set(stepNumber, { x: 20 + layerIndex * 238, y: 24 + rowIndex * 108 }))
  })
  const phaseLabel = aggregate.workflow.state === 'paused'
    ? '执行已暂停'
    : aggregate.workflow.state === 'text_report' ? '运行完成' : '执行中'

  return (
    <article className="rw-stage-card rw-dag-card" data-stage="dag">
      <StageHeader number="3" title="运行流程" note="状态来自冻结工作台投影" />
      <div className="rw-dag-summary" aria-live="polite"><StatusMark status={aggregate.workflow.state === 'paused' ? 'failed' : aggregate.workflow.state === 'text_report' ? 'succeeded' : 'running'} /><b>{phaseLabel}</b><span>{completed}/{dag.nodes.length} 个执行节点已结束</span></div>
      <div className="rw-dag-viewport" role="img" aria-label={description} tabIndex={0}>
        <div className="rw-dag-canvas" style={{ width: graphWidth, height: graphHeight }}>
          <svg viewBox={`0 0 ${graphWidth} ${graphHeight}`} aria-hidden="true">
            <defs><marker id={markerId} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" /></marker></defs>
            {dag.edges.map((edge) => {
              const source = positions.get(edge.source)
              const target = positions.get(edge.target)
              if (!source || !target) return null
              return <path key={edge.id} className={`status-${edge.status}`} d={`M ${source.x + 184} ${source.y + 36} C ${source.x + 210} ${source.y + 36}, ${target.x - 26} ${target.y + 36}, ${target.x} ${target.y + 36}`} markerEnd={`url(#${markerId})`} />
            })}
          </svg>
          {dag.nodes.map((node) => {
            const position = positions.get(node.stepNumber)
            if (!position) return null
            return (
              <div key={node.id} className={`rw-dag-node status-${node.status}`} style={{ left: position.x, top: position.y }}>
                <div><StatusMark status={node.status} /><span>{STATUS_LABELS[node.status]}</span><code>#{node.stepNumber}</code></div>
                <b>{node.name}</b>
                <p><ActorBadge actorType={node.actorType} /><code>{node.actorId}</code></p>
              </div>
            )
          })}
        </div>
      </div>
      <ol className="rw-sr-only">
        {dag.nodes.map((node) => <li key={node.id}>步骤 {node.stepNumber}，{node.name}，状态 {STATUS_LABELS[node.status]}{node.dependsOn.length ? `，依赖步骤 ${node.dependsOn.join('、')}` : ''}</li>)}
      </ol>
      <div className="rw-dag-legend" aria-hidden="true">
        {(Object.keys(STATUS_LABELS) as StepStatus[]).map((status) => <span key={status}><StatusMark status={status} />{STATUS_LABELS[status]}</span>)}
      </div>
    </article>
  )
}

function StatusMark({ status }: { status: StepStatus }) {
  if (status === 'running') return <span className="rw-spinner rw-status-mark" />
  const mark = status === 'succeeded' ? '✓' : status === 'failed' ? '×' : status === 'skipped' ? '↷' : '○'
  return <span className={`rw-status-mark status-${status}`}>{mark}</span>
}

export function GapNotice({ gaps }: { gaps: NonNullable<ResearchV3WorkbenchAggregateV1['selected_plan']>['payload']['capability_gaps'] }) {
  return (
    <aside className="rw-gap-notice" role="status">
      <b>能力缺口</b>
      <ul>{gaps.map((gap) => <li key={`${gap.capability_type}-${gap.capability_id}`}>{gap.message}{gap.required ? '（必需）' : '（可选）'}</li>)}</ul>
    </aside>
  )
}

export function PausedRecoveryStage({
  aggregate,
  onAction,
}: {
  aggregate: ResearchV3WorkbenchAggregateV1
  onAction?: ResearchWorkbenchActions['onRecoveryAction']
}) {
  const recovery = aggregate.recovery
  if (!recovery) return null
  const failedStep = aggregate.selected_plan?.payload.steps.find((step) => step.step_number === recovery.failed_step_number)
  const labels = { retry: '重试失败执行', skip: '跳过可选步骤', abort: '终止任务' } as const
  return (
    <article className="rw-recovery-card" data-stage="paused" role="status">
      <h2>第 {recovery.failed_step_number} 步失败{failedStep ? `：${failedStep.name}` : ''}</h2>
      <p>恢复原因：<code>{recovery.reason_code}</code>。系统不会自动重放外部调用，请明确选择恢复方式。</p>
      <div className="rw-button-row">
        {recovery.allowed_actions.map((action) => (
          <button key={action} type="button" className={action === 'retry' ? 'rw-button-primary' : 'rw-button-ghost'} disabled={!onAction} onClick={() => onAction?.(action)}>{labels[action]}</button>
        ))}
      </div>
    </article>
  )
}

function safeHttpsUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}

function ReportBlock({
  block,
  evidence,
}: {
  block: ReportBlockV3
  evidence: ResearchV3WorkbenchAggregateV1['evidence']
}) {
  if (block.type === 'list') return <ul className="rw-report-list">{block.items.map((item) => <li key={item}>{item}</li>)}</ul>
  if (block.type === 'metric') return <dl className="rw-report-metric"><dt>{block.label}</dt><dd>{block.value}</dd></dl>
  if (block.type === 'fact') {
    return (
      <div className="rw-report-fact">
        <p>{block.text}</p>
        <EvidenceDisclosure ids={block.evidence_ids} evidence={evidence} />
      </div>
    )
  }
  return <p className="rw-report-paragraph">{block.text}</p>
}

function EvidenceDisclosure({
  ids,
  evidence,
}: {
  ids: readonly string[]
  evidence: ResearchV3WorkbenchAggregateV1['evidence']
}) {
  const items = ids.flatMap((id) => {
    const item = evidence?.evidence.find((candidate) => candidate.evidence_id === id)
    return item ? [item] : []
  })
  if (!items.length) return null
  return (
    <details className="rw-evidence-disclosure">
      <summary>查看证据（{items.length}）</summary>
      <ul>
        {items.map((item) => {
          const href = safeHttpsUrl(item.url)
          return (
            <li key={item.evidence_id}>
              <div><code>{item.evidence_id}</code> · {href ? <a href={href} target="_blank" rel="noopener noreferrer">{item.title}</a> : item.title}</div>
              <blockquote>{item.quote}</blockquote>
              <small>{item.provenance.registrable_domain} · {item.provenance.retrieved_at} · {item.gap_metadata.redaction === 'masked' ? '已脱敏' : '未脱敏'}</small>
            </li>
          )
        })}
      </ul>
    </details>
  )
}

export function Stage4TextReport({ aggregate }: { aggregate: ResearchV3WorkbenchAggregateV1 }) {
  const report = aggregate.report?.content
  if (!report) return null
  const deliverable = aggregate.deliverable?.content
  return (
    <article className="rw-report-document" data-stage="text-report" aria-labelledby={`rw-report-title-${aggregate.run_id}`}>
      <header className="rw-report-cover">
        <p>研究报告</p>
        <h1 id={`rw-report-title-${aggregate.run_id}`}>{report.title}</h1>
        <h2>{report.subtitle}</h2>
        <p className="rw-report-summary">{report.executive_summary}</p>
        <div className="rw-report-verdict">✓ Review {aggregate.review?.content.verdict ?? report.review_verdict}</div>
      </header>
      <div className="rw-report-layout">
        <nav className="rw-report-toc" aria-label="报告章节">
          <h2>目录 / Contents</h2>
          <ol>{report.sections.map((section) => <li key={section.id}><a href={`#rw-${aggregate.run_id}-${section.id}`}>{section.title}</a></li>)}</ol>
        </nav>
        <div className="rw-report-body">
          {report.sections.map((section) => (
            <section className="rw-report-section" id={`rw-${aggregate.run_id}-${section.id}`} key={section.id}>
              <h2>{section.title}</h2>
              {section.question_ids.length ? <p className="rw-question-binding">覆盖问题：{section.question_ids.join('、')}</p> : null}
              {section.blocks.map((block) => <ReportBlock key={block.id} block={block} evidence={aggregate.evidence} />)}
              {section.id === 'recommendations' && deliverable?.recommendations.length ? (
                <ol className="rw-report-recommendations">{deliverable.recommendations.map((item) => <li key={item.id}><b>{item.priority}</b>{item.statement}</li>)}</ol>
              ) : null}
              {section.id === 'risks' && deliverable?.risks_and_open_issues.length ? (
                <ul className="rw-report-risks">{deliverable.risks_and_open_issues.map((risk) => <li key={risk}>{risk}</li>)}</ul>
              ) : null}
            </section>
          ))}
        </div>
      </div>
    </article>
  )
}

export function ResearchV2History({ aggregate }: { aggregate: ResearchV2HistoryWorkbenchAggregateV1 }) {
  const presentation = presentWorkbench(aggregate)
  if (presentation.kind !== 'history') return null
  return (
    <article className="rw-history-card" aria-labelledby={`rw-history-${aggregate.run_id}`}>
      <div className="rw-history-label"><span>历史任务</span><b>只读</b></div>
      <h1 id={`rw-history-${aggregate.run_id}`}>{presentation.title}</h1>
      {presentation.status ? <p className="rw-history-status">状态：{presentation.status}</p> : null}
      {presentation.request ? <section><h2>原始需求</h2><p>{presentation.request}</p></section> : null}
      {presentation.summary ? <section><h2>历史结果</h2><p>{presentation.summary}</p></section> : null}
      <p className="rw-history-note">此任务由 research-v2 创建，仅提供兼容阅读；不能在当前研究流程中修改或重新执行。</p>
    </article>
  )
}

function LoadingState() {
  return <div className="rw-state-card" role="status"><span className="rw-spinner" /><div><b>正在读取研究任务</b><p>正在恢复已保存的工作台状态…</p></div></div>
}

function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rw-state-card is-error" role="alert">
      <span className="rw-error-mark">!</span>
      <div><b>研究任务加载失败</b><p>{message}</p>{onRetry ? <button type="button" className="rw-button-ghost" onClick={onRetry}>重试读取</button> : null}</div>
    </div>
  )
}

export function ResearchWorkbenchShell({ children }: { children: ReactNode }) {
  return <section className="research-workbench-current"><div className="rw-flow">{children}</div></section>
}
