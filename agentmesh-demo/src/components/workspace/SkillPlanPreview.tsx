import { GitBranch, Plus, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import { useMemo, useState } from 'react'

import type {
  Skill,
  PlanDetailResponse,
  SkillPlanUpdateRequest,
  SkillPlanVersionRequest,
} from '../../features/workspace/types'
import { Button } from '../ui/Button'
import { SkillPlanNodeCard } from './SkillPlanNodeCard'
import { capabilityGapLabel, degradationCopy } from './skillPlanPresentation'

interface SkillPlanPreviewProps {
  detail: PlanDetailResponse
  candidates: Skill[]
  orchestrationMode: 'preview' | 'execute'
  pendingAction: 'update' | 'approve' | 'reject' | null
  error: string | null
  onUpdate: (request: SkillPlanUpdateRequest) => void
  onApprove: (request: SkillPlanVersionRequest) => void
  onReject: (request: SkillPlanVersionRequest) => void
}

export function SkillPlanPreview({
  detail,
  candidates,
  orchestrationMode,
  pendingAction,
  error,
  onUpdate,
  onApprove,
  onReject,
}: SkillPlanPreviewProps) {
  const nodes = detail.plan.nodes ?? []
  const route = detail.plan.routing_result
  const scenarioOptions = detail.scenario_assignment_options ?? {}
  const candidateSkillIds = detail.plan.candidate_skill_ids ?? []
  const [selected, setSelected] = useState(() => new Set(nodes.map((node) => node.skill_id)))
  const [order, setOrder] = useState(() => nodes.map((node) => node.skill_id))
  const [scenarioAssignments, setScenarioAssignments] = useState<Record<string, string>>(
    () => Object.fromEntries(
      nodes.flatMap((node) => node.scenario_id ? [[node.skill_id, node.scenario_id]] : []),
    ),
  )
  const skillsById = useMemo(() => new Map(candidates.map((skill) => [skill.id, skill])), [candidates])
  const nodeSkillIds = useMemo(() => new Set(nodes.map((node) => node.skill_id)), [nodes])
  const addableCandidates = useMemo(
    () => candidateSkillIds
      .filter((skillId) => !nodeSkillIds.has(skillId))
      .flatMap((skillId) => {
        const skill = skillsById.get(skillId)
        return skill ? [skill] : []
      }),
    [candidateSkillIds, nodeSkillIds, skillsById],
  )
  const orderedNodes = useMemo(() => {
    const nodesBySkill = new Map(nodes.map((node) => [node.skill_id, node]))
    return order.flatMap((skillId) => {
      const node = nodesBySkill.get(skillId)
      return node ? [node] : []
    })
  }, [nodes, order])
  const originalSelected = nodes.map((node) => node.skill_id)
  const originalScenarioAssignments = new Map(
    nodes.map((node) => [node.skill_id, node.scenario_id ?? '']),
  )
  const selectedOrder = order.filter((skillId) => selected.has(skillId))
  const ambiguousSelections = selectedOrder.flatMap((skillId) => {
    const options = scenarioOptions[skillId] ?? []
    return options.length > 1 ? [{ skillId, options }] : []
  })
  const unresolvedScenarioAssignments = ambiguousSelections.filter(
    ({ skillId, options }) => !options.some(
      (option) => option.scenario_id === scenarioAssignments[skillId],
    ),
  )
  const scenarioDirty = ambiguousSelections.some(
    ({ skillId }) => (scenarioAssignments[skillId] ?? '') !== (
      originalScenarioAssignments.get(skillId) ?? ''
    ),
  )
  const dirty = selectedOrder.join('|') !== originalSelected.join('|')
    || selected.size !== originalSelected.length
    || scenarioDirty
  const busy = pendingAction !== null
  const approvalBlocked = unresolvedScenarioAssignments.length > 0
  const planNotice = detail.plan.degradation ? degradationCopy(detail.plan.degradation) : null

  const toggle = (skillId: string) => {
    const node = nodes.find((item) => item.skill_id === skillId)
    if (node?.required) return
    const adding = !selected.has(skillId)
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(skillId)) next.delete(skillId)
      else next.add(skillId)
      return next
    })
    if (adding) {
      setOrder((current) => current.includes(skillId) ? current : [...current, skillId])
    }
  }

  const move = (skillId: string, direction: 'up' | 'down') => {
    setOrder((current) => {
      const index = current.indexOf(skillId)
      const target = direction === 'up' ? index - 1 : index + 1
      if (index < 0 || target < 0 || target >= current.length) return current
      const next = [...current]
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  return (
    <section aria-labelledby="skill-plan-preview-title" className="mt-6 rounded-soft bg-surface-1 p-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-mint-300">
            <GitBranch className="h-4 w-4" aria-hidden="true" />
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em]">Skill plan · v{detail.plan.version}</p>
          </div>
          <h2 id="skill-plan-preview-title" className="mt-2 text-lg font-semibold text-slate-100">执行前确认计划</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-400">{detail.plan.intent.goal}</p>
        </div>
        <span className="rounded-full bg-amber-300/10 px-3 py-1.5 text-xs font-medium text-amber-300">尚未执行任何节点</span>
      </div>

      {route ? (
        <section aria-label="任务路由" className="mt-5 rounded-soft border border-mint-400/15 bg-mint-400/[0.04] px-3.5 py-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-semibold text-mint-300">{route.task.task_id}</span>
            <span className="text-slate-400">/</span>
            <span className="text-slate-200">{route.scenario.scenario_id}</span>
            <span className="rounded-full bg-white/[0.05] px-2 py-0.5 text-[11px] text-slate-400">
              {route.task.execution_relation}
            </span>
          </div>
          {(route.scenario.supporting_scenarios ?? []).length > 0 ? (
            <p className="mt-2 text-[11px] leading-5 text-slate-400">
              前置场景：{(route.scenario.supporting_scenarios ?? []).join('、')}
            </p>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
            {route.evidence_requirement?.external_evidence_required ? (
              <span className="rounded-full bg-knowledge/10 px-2 py-1 text-knowledge">需要外部证据</span>
            ) : null}
            {(detail.plan.capability_gaps ?? []).map((gap) => (
              <span key={gap} className="rounded-full bg-rose/10 px-2 py-1 text-rose" title={gap}>
                能力缺口：{capabilityGapLabel(gap)}
              </span>
            ))}
            {(route.skill_routing?.planned_skills ?? []).map((skillId) => (
              <span key={skillId} className="rounded-full bg-amber-300/10 px-2 py-1 text-amber-300" title={skillId}>
                候选能力尚未接入
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {!route && (detail.plan.capability_gaps ?? []).length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
          {(detail.plan.capability_gaps ?? []).map((gap) => (
            <span key={gap} className="rounded-full bg-rose/10 px-2 py-1 text-rose" title={gap}>
              能力缺口：{capabilityGapLabel(gap)}
            </span>
          ))}
        </div>
      ) : null}

      <dl className="mt-5 grid gap-3 text-xs sm:grid-cols-2">
        <div className="rounded-soft bg-base px-3.5 py-3">
          <dt className="text-slate-400">已有输入</dt>
          <dd className="mt-1 text-slate-200">{detail.plan.intent.input_kinds?.join('、') || '当前对话内容'}</dd>
        </div>
        <div className="rounded-soft bg-base px-3.5 py-3">
          <dt className="text-slate-400">预计交付</dt>
          <dd className="mt-1 text-slate-200">{detail.plan.output_contract?.join('、') || '综合结论'}</dd>
        </div>
      </dl>

      <div className="mt-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
          <SlidersHorizontal className="h-4 w-4 text-slate-400" aria-hidden="true" />
          有限调整
        </div>
        <p className="text-[11px] text-slate-400">必需节点不可移除，服务端会重新计算依赖</p>
      </div>
      <ol className="mt-3 space-y-2.5">
        {orderedNodes.map((node, index) => (
          <li key={node.id ?? node.skill_id}>
            <SkillPlanNodeCard
              node={node}
              skill={skillsById.get(node.skill_id)}
              mode="preview"
              selected={selected.has(node.skill_id)}
              disabled={busy}
              canMoveUp={index > 0}
              canMoveDown={index < orderedNodes.length - 1}
              onToggle={toggle}
              onMove={move}
              onSelectOnly={(skillId) => {
                const requiredIds = nodes.filter((item) => item.required).map((item) => item.skill_id)
                setSelected(new Set([...requiredIds, skillId]))
                setOrder((current) => [
                  ...current.filter((item) => requiredIds.includes(item)),
                  ...current.filter((item) => item === skillId && !requiredIds.includes(item)),
                  ...current.filter((item) => !requiredIds.includes(item) && item !== skillId),
                ])
              }}
            />
          </li>
        ))}
      </ol>

      {addableCandidates.length > 0 ? (
        <section aria-labelledby="skill-plan-candidates-title" className="mt-4 rounded-soft border border-white/[0.06] bg-base/60 p-3.5">
          <h3 id="skill-plan-candidates-title" className="text-xs font-semibold text-slate-300">可添加候选</h3>
          <p className="mt-1 text-[11px] leading-5 text-slate-400">只能从服务端已校验的候选集中添加；保存后由服务端重新计算先后依赖和可并行步骤。</p>
          <ul className="mt-3 space-y-2">
            {addableCandidates.map((skill) => {
              const added = selected.has(skill.id)
              return (
                <li key={skill.id} className="flex flex-col gap-2 rounded-soft bg-surface-1 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-200">{skill.title}</p>
                    <p className="mt-0.5 text-[11px] leading-5 text-slate-400">{skill.description}</p>
                  </div>
                  <Button
                    variant={added ? 'subtle' : 'secondary'}
                    size="sm"
                    disabled={busy}
                    icon={added ? undefined : <Plus className="h-3.5 w-3.5" />}
                    onClick={() => toggle(skill.id)}
                  >
                    {added ? '移除候选' : '加入计划'}
                  </Button>
                </li>
              )
            })}
          </ul>
        </section>
      ) : null}

      {ambiguousSelections.length > 0 ? (
        <section aria-labelledby="scenario-assignment-title" className="mt-4 rounded-soft border border-amber-300/15 bg-amber-300/[0.05] p-3.5">
          <h3 id="scenario-assignment-title" className="text-xs font-semibold text-amber-100">确认场景归属</h3>
          <p className="mt-1 text-[11px] leading-5 text-slate-400">同一能力匹配多个场景时，必须先选择本次实际交付的场景。</p>
          <div className="mt-3 grid gap-3">
            {ambiguousSelections.map(({ skillId, options }) => (
              <label key={skillId} className="text-xs text-slate-300">
                {skillsById.get(skillId)?.title ?? skillId}
                <select
                  aria-label={`场景归属：${skillsById.get(skillId)?.title ?? skillId}`}
                  value={scenarioAssignments[skillId] ?? ''}
                  disabled={busy}
                  onChange={(event) => setScenarioAssignments((current) => ({
                    ...current,
                    [skillId]: event.target.value,
                  }))}
                  className="mt-1.5 h-10 w-full rounded-soft border border-white/[0.08] bg-surface-1 px-3 text-slate-100 outline-none focus:border-mint-400/50"
                >
                  <option value="">请选择场景</option>
                  {options.map((option) => (
                    <option key={option.scenario_id} value={option.scenario_id}>
                      {option.title}{(option.output_labels ?? []).length > 0 ? ` · ${(option.output_labels ?? []).join('、')}` : ''}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </section>
      ) : null}

      {planNotice && detail.plan.degradation ? (
        <section className="mt-4 rounded-soft border border-amber-300/15 bg-amber-300/[0.06] px-3.5 py-3">
          <p className="text-xs font-semibold text-amber-100">{planNotice.title}</p>
          <p className="mt-1 text-xs leading-5 text-slate-300">{planNotice.description}</p>
          <details className="mt-1.5 text-[11px] text-slate-400">
            <summary className="cursor-pointer select-none hover:text-slate-300">查看技术诊断</summary>
            <code className="mt-1 block break-all">{detail.plan.degradation}</code>
          </details>
        </section>
      ) : null}
      {error ? <p role="alert" className="mt-4 text-sm text-rose">{error}</p> : null}
      {approvalBlocked ? (
        <p className="mt-4 text-xs leading-5 text-rose">
          请选择所有多义节点的场景归属，保存后才能批准计划。
        </p>
      ) : null}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4">
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <ShieldCheck className="h-4 w-4 text-mint-300" aria-hidden="true" />
          确认计划不会批准任何写入工具
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => onReject({ expected_version: detail.plan.version })}
          >
            拒绝计划
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={
              !dirty
              || selected.size === 0
              || busy
              || unresolvedScenarioAssignments.length > 0
            }
            loading={pendingAction === 'update'}
            onClick={() => onUpdate({
              expected_version: detail.plan.version,
              selected_skill_ids: selectedOrder,
              preferred_order: selectedOrder,
              scenario_assignments: Object.fromEntries(
                ambiguousSelections.map(({ skillId }) => [
                  skillId,
                  scenarioAssignments[skillId],
                ]),
              ),
            })}
          >
            保存调整
          </Button>
          <Button
            size="sm"
            disabled={dirty || busy || approvalBlocked}
            loading={pendingAction === 'approve'}
            onClick={() => onApprove({ expected_version: detail.plan.version })}
          >
            {orchestrationMode === 'preview' ? '确认计划，仅预览' : '确认并开始执行'}
          </Button>
        </div>
      </div>
    </section>
  )
}
