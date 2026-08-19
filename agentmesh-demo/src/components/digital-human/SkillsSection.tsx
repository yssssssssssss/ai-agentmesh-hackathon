import { ArrowUpRight, Clock, Search, Users, Wrench, Zap } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  useSkillCatalogQuery,
  useSkillRecommendationsMutation,
  useUpdateSkillBindingMutation,
  useWorkspaceScope,
} from '../../features/workspace/queries'
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
  const updateBinding = useUpdateSkillBindingMutation(scope)
  const recommendations = useSkillRecommendationsMutation()
  const [recommendationInput, setRecommendationInput] = useState('')
  const skills = catalog.data?.items ?? []
  const enabled = skills.filter((skill) => skill.enabled !== false).length
  const bound = skills.filter((skill) => skill.binding_enabled !== false).length
  const team = skills.filter((skill) => skill.source === 'workspace').length

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
          来自 Agent Skills 标准目录的真实能力。启停状态绑定到当前数字员工，并同步影响工作台的 Skill 选择器。
        </p>
      </header>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 sm:gap-3">
        <StatTile label="可用 Skill" value={enabled} icon={<Wrench className="h-4 w-4" />} tone="mint" />
        <StatTile label="已启用" value={bound} icon={<Zap className="h-4 w-4" />} tone="knowledge" />
        <StatTile label="团队共享" value={team} icon={<Users className="h-4 w-4" />} tone="collab" />
      </div>

      {catalog.isLoading ? <p className="text-sm text-slate-400">正在加载 Skill 目录…</p> : null}
      {catalog.isError ? <p className="text-sm text-red-300">Skill 目录加载失败，请刷新重试。</p> : null}

      <section className="rounded-[14px] bg-surface-1 p-4 shadow-card" aria-labelledby="skill-recommendation-title">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-mint-300" aria-hidden="true" />
          <h2 id="skill-recommendation-title" className="text-sm font-semibold text-slate-100">按目标推荐 Skill</h2>
        </div>
        <p className="mt-1.5 text-xs leading-5 text-slate-500">只分析意图和安全画像，不创建 Run，也不会读取 Skill 指令或调用工具。</p>
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
            aria-label="描述你的目标"
            placeholder="例如：根据 PRD 评估方案并准备用户访谈"
            className="min-h-10 min-w-0 flex-1 rounded-[10px] bg-base px-3.5 text-sm text-slate-100 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)] outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
          />
          <Button
            type="submit"
            size="sm"
            className="w-full sm:w-auto"
            loading={recommendations.isPending}
            disabled={!recommendationInput.trim()}
          >
            获取推荐
          </Button>
        </form>
        {recommendations.isError ? <p role="alert" className="mt-3 text-xs text-rose">推荐失败，请稍后重试。</p> : null}
        {recommendations.data ? (
          <div className="mt-4 border-t border-white/[0.06] pt-4">
            <p className="text-xs text-slate-400">识别目标：<span className="text-slate-200">{recommendations.data.intent.goal}</span></p>
            <ol className="mt-3 space-y-2">
              {recommendations.data.candidates.slice(0, 5).map((candidate, index) => (
                <li key={candidate.skill_id} className="flex items-start gap-3 rounded-[10px] bg-base px-3.5 py-3">
                  <span className="font-mono text-xs text-mint-300">{String(index + 1).padStart(2, '0')}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-slate-200">{candidate.title}</span>
                      <span className="font-mono text-[10px] text-slate-500">score {candidate.score.total.toFixed(2)}</span>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-slate-500">{candidate.reason}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </section>

      <ul className="space-y-3">
        {skills.map((skill) => {
          const on = skill.binding_enabled !== false
          const ready = skill.readiness === 'ready'
          const source = sourceMeta(skill)
          const pending = updateBinding.isPending && updateBinding.variables?.skillId === skill.id
          return (
            <li key={skill.id ?? skill.command} className="card-base p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[14.5px] font-semibold text-slate-100">{skill.title}</h3>
                    <Badge tone={source.tone}>{source.label}</Badge>
                    <span className={cn('inline-flex items-center gap-1 text-[11.5px]', on ? 'text-mint-300' : 'text-slate-500')}>
                      <span className={cn('h-1.5 w-1.5 rounded-full', on ? 'bg-mint-400' : 'bg-slate-600')} />
                      {on ? '已启用' : '已停用'}
                    </span>
                    <span className={cn('text-[11px]', ready ? 'text-slate-400' : 'text-amber-300')}>
                      {ready ? '已就绪' : '未就绪'}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">{skill.description}</p>
                  <p className="mt-1.5 flex items-start gap-1 text-[11.5px] text-slate-500">
                    <Clock className="mt-0.5 h-3 w-3 shrink-0" />
                    <span className="min-w-0 break-words">
                      {skill.command} · v{skill.version ?? '1'} · {skill.activation_policy === 'model_allowed' ? '可自动激活' : '显式调用'}
                    </span>
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {skill.primary_stage ?? '未标注阶段'} · {skill.capability_type ?? '未标注类型'} · {skill.side_effect ? SIDE_EFFECT[skill.side_effect] : '未标注边界'} · {skill.planner_eligible ? '可参与规划' : '不参与规划'}
                  </p>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button variant={on ? 'subtle' : 'primary'} size="sm" disabled={pending} onClick={() => toggle(skill)}>
                  {pending ? '更新中…' : on ? '停用' : '启用'}
                </Button>
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
    </div>
  )
}
