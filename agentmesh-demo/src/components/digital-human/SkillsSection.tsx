import { AlertTriangle, ArrowUpRight, CheckCircle2, Clock, Search, Wrench, Zap } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  useSkillCatalogQuery,
  useSkillRecommendationsMutation,
  useSkillsQuery,
  useUpdateSkillBindingMutation,
  useWorkspaceScope,
} from '../../features/workspace/queries'
import {
  groupSkillsByDesignStage,
  isCallableSkill,
  missingToolsSummary,
  skillAvailabilityLabel,
} from '../../features/workspace/skillPresentation'
import type { Skill } from '../../features/workspace/types'
import { useDemo } from '../../store/DemoContext'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { StatTile } from '../ui/StatTile'
import { cn } from '../../lib/cn'

const SOURCE = {
  builtin: { label: '平台内置', tone: 'neutral' as const },
  workspace: { label: '团队共享', tone: 'collab' as const },
  project: { label: '项目配置', tone: 'knowledge' as const },
}

const SIDE_EFFECT = {
  read: '只读',
  draft: '草稿',
  local_write: '本地写入',
  external_write: '外部写入',
} as const

function sourceMeta(skill: Skill) {
  return SOURCE[skill.source ?? 'builtin']
}

/** Agent Skills backed by the authenticated AgentMesh catalog and bindings. */
export function SkillsSection() {
  const { showToast } = useDemo()
  const navigate = useNavigate()
  const scope = useWorkspaceScope()
  const catalog = useSkillCatalogQuery(scope)
  const callableCatalog = useSkillsQuery(scope)
  const updateBinding = useUpdateSkillBindingMutation(scope)
  const recommendations = useSkillRecommendationsMutation()
  const [recommendationInput, setRecommendationInput] = useState('')
  const skills = catalog.data?.items ?? []
  const tools = (callableCatalog.data?.items ?? []).filter((skill) => skill.command.includes('.'))
  const callableSkills = skills.filter(isCallableSkill)
  const completeSkills = callableSkills.filter((skill) => skill.execution_readiness !== 'tool_limited').length
  const toolLimitedSkills = callableSkills.filter((skill) => skill.execution_readiness === 'tool_limited').length
  const plannableSkills = callableSkills.filter((skill) => skill.planner_eligible).length
  const groupedSkills = groupSkillsByDesignStage([...skills, ...tools])

  const toggle = (skill: Skill) => {
    const next = skill.binding_enabled === false
    updateBinding.mutate(
      { skillId: skill.id, enabled: next },
      {
        onSuccess: () => showToast(next ? `已启用「${skill.title}」` : `已停用「${skill.title}」`, 'info'),
        onError: () => showToast('Skill 状态更新失败，请稍后重试', 'info'),
      },
    )
  }

  return (
    <div className="animate-fade-in space-y-6">
      <header>
        <h1 className="flex items-center gap-2.5 text-xl font-semibold text-white">
          <Wrench className="h-5 w-5 text-mint-300" />
          能力与 Skill
        </h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">
          来自 Agent Skills 标准目录的真实能力。已接入 Skill 均可显式启动；外部工具尚未接通的能力会单独标注，且不会扩大运行权限。
        </p>
      </header>

      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4 lg:gap-3">
        <StatTile label="已接入 Skill" value={skills.length} icon={<Wrench className="h-4 w-4" />} tone="mint" />
        <StatTile label="完整可执行" value={completeSkills} icon={<CheckCircle2 className="h-4 w-4" />} tone="collab" />
        <StatTile label="工具待接通" value={toolLimitedSkills} icon={<AlertTriangle className="h-4 w-4" />} tone="remind" />
        <StatTile label="可自动编排" value={plannableSkills} icon={<Zap className="h-4 w-4" />} tone="knowledge" />
      </div>

      {catalog.isLoading || callableCatalog.isLoading ? <p className="text-sm text-slate-400">正在加载 Skill 目录…</p> : null}
      {catalog.isError || callableCatalog.isError ? <p className="text-sm text-red-300">Skill 目录加载失败，请刷新重试。</p> : null}

      <section className="rounded-soft bg-surface-1 p-4 shadow-card" aria-labelledby="skill-recommendation-title">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-mint-300" aria-hidden="true" />
          <h2 id="skill-recommendation-title" className="text-sm font-semibold text-slate-100">自动编排候选预检</h2>
        </div>
        <p className="mt-1.5 text-xs leading-5 text-slate-400">
          仅预检当前受治理、可自动编排的 Skill 候选。不创建 Run，也不读取 Skill 指令或调用工具。
        </p>
        <form
          className="mt-3 flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault()
            const content = recommendationInput.trim()
            if (content) recommendations.mutate({ content })
          }}
        >
          <input
            value={recommendationInput}
            onChange={(event) => setRecommendationInput(event.target.value)}
            aria-label="描述自动编排目标"
            placeholder="例如：根据 PRD 评估方案并准备用户访谈"
            className="min-h-10 min-w-0 flex-1 rounded-soft bg-base px-3.5 text-sm text-slate-100 shadow-input outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
          />
          <Button
            type="submit"
            size="sm"
            className="w-full sm:w-auto"
            loading={recommendations.isPending}
            disabled={!recommendationInput.trim()}
          >
            开始预检
          </Button>
        </form>
        {recommendations.isError ? <p role="alert" className="mt-3 text-xs text-rose">预检失败，请稍后重试。</p> : null}
        {recommendations.data ? (
          <div className="mt-4 border-t border-white/[0.06] pt-4">
            <p className="text-xs text-slate-400">识别目标：<span className="text-slate-200">{recommendations.data.intent.goal}</span></p>
            <ol className="mt-3 space-y-2">
              {recommendations.data.candidates.slice(0, 5).map((candidate, index) => (
                <li key={candidate.skill_id} className="flex items-start gap-3 rounded-soft bg-base px-3.5 py-3">
                  <span className="font-mono text-xs text-mint-300">{String(index + 1).padStart(2, '0')}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-slate-200">{candidate.title}</span>
                      <span className="font-mono text-[11px] text-slate-400">score {candidate.score.total.toFixed(2)}</span>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-slate-400">{candidate.reason}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </section>

      <div className="space-y-6">
        {groupedSkills.map((group) => (
          <section
            key={group.key}
            aria-labelledby={`skill-stage-${group.key}`}
            className="rounded-overlay border border-white/[0.07] bg-surface-1 p-4 shadow-card sm:p-5"
          >
            <div className="mb-4 flex flex-wrap items-end justify-between gap-2 border-b border-white/[0.06] pb-3">
              <div>
                <h2 id={`skill-stage-${group.key}`} className="flex items-center gap-2 text-sm font-semibold text-slate-100">
                  <span className={cn('h-2 w-2 rounded-full', group.dotClass)} aria-hidden="true" />
                  {group.label}
                </h2>
                <p className="mt-1 text-xs text-slate-400">{group.description}</p>
              </div>
              <span className="text-xs text-slate-400">{group.items.length} 个 Skill</span>
            </div>
            <ul className="space-y-3">
              {group.items.map((skill) => {
                const managed = !skill.command.includes('.') && Boolean(skill.id)
                const on = skill.binding_enabled !== false
                const ready = isCallableSkill(skill)
                const availability = skillAvailabilityLabel(skill)
                const toolLimited = skill.execution_readiness === 'tool_limited'
                const missingTools = missingToolsSummary(skill.missing_tools)
                const source = sourceMeta(skill)
                const pending = managed && updateBinding.isPending && updateBinding.variables?.skillId === skill.id
                return (
                  <li key={skill.id ?? skill.command} className="rounded-soft border border-white/[0.06] bg-base/70 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-[14.5px] font-semibold text-slate-100">{skill.title}</h3>
                          <Badge tone={source.tone}>{source.label}</Badge>
                          {managed ? (
                            <span className={cn('inline-flex items-center gap-1 text-[11.5px]', on ? 'text-mint-300' : 'text-slate-400')}>
                              <span className={cn('h-1.5 w-1.5 rounded-full', on ? 'bg-mint-400' : 'bg-slate-600')} />
                              {on ? '已启用' : '已停用'}
                            </span>
                          ) : null}
                          <span className={cn('text-[11px]', toolLimited || !ready ? 'text-amber-300' : 'text-slate-400')}>
                            {availability}
                          </span>
                        </div>
                        <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">{skill.description}</p>
                        <p className="mt-1.5 flex items-start gap-1 text-[11.5px] text-slate-400">
                          <Clock className="mt-0.5 h-3 w-3 shrink-0" />
                          <span className="min-w-0 break-words">
                            {skill.command} · v{skill.version ?? '1'} · {skill.activation_policy === 'model_allowed' ? '可自动激活' : '显式调用'}
                          </span>
                        </p>
                        <p className="mt-1 text-[11px] text-slate-400">
                          {group.label} · {skill.capability_type ?? '工具调用'} · {skill.side_effect ? SIDE_EFFECT[skill.side_effect] : '按账号权限'} · {managed ? skill.planner_eligible ? '可进入自动规划' : '仅支持显式调用' : '直接工具调用'}
                        </p>
                        {toolLimited ? (
                          <p className="mt-1.5 break-words text-[11px] leading-5 text-amber-200/80" title={skill.missing_tools?.join('、')}>
                            待接通工具：{missingTools}。当前可启动并读取 Skill 说明，涉及这些工具的步骤会受限。
                          </p>
                        ) : null}
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {managed ? (
                        <Button variant={on ? 'subtle' : 'primary'} size="sm" disabled={pending} onClick={() => toggle(skill)}>
                          {pending ? '更新中…' : on ? '停用' : '启用'}
                        </Button>
                      ) : null}
                      <Button variant="ghost" size="sm" onClick={() => showToast(skill.usage, 'info')}>
                        查看用法
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        iconRight={<ArrowUpRight className="h-3.5 w-3.5" />}
                        disabled={!on || !ready}
                        onClick={() => navigate(`/workspace?skill=${encodeURIComponent(skill.command)}`)}
                      >
                        在工作台中使用
                      </Button>
                    </div>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}
