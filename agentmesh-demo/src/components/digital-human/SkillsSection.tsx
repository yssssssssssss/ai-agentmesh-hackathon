import { Clock, Users, Wrench, Zap } from 'lucide-react'

import { useSkillCatalogQuery, useUpdateSkillBindingMutation, useWorkspaceScope } from '../../features/workspace/queries'
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

function sourceMeta(skill: Skill) {
  return SOURCE[skill.source ?? 'builtin']
}

/** Agent Skills backed by the authenticated AgentMesh catalog and bindings. */
export function SkillsSection() {
  const { showToast } = useDemo()
  const scope = useWorkspaceScope()
  const catalog = useSkillCatalogQuery(scope)
  const updateBinding = useUpdateSkillBindingMutation(scope)
  const skills = catalog.data?.items ?? []
  const enabled = skills.filter((skill) => skill.enabled !== false).length
  const team = skills.filter((skill) => skill.source === 'workspace').length

  const toggle = (skill: Skill) => {
    if (!skill.id) return
    const next = skill.enabled === false
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

      <div className="grid grid-cols-3 gap-3">
        <StatTile label="可用 Skill" value={skills.length} icon={<Wrench className="h-4 w-4" />} tone="mint" />
        <StatTile label="已启用" value={enabled} icon={<Zap className="h-4 w-4" />} tone="knowledge" />
        <StatTile label="团队共享" value={team} icon={<Users className="h-4 w-4" />} tone="collab" />
      </div>

      {catalog.isLoading ? <p className="text-sm text-slate-400">正在加载 Skill 目录…</p> : null}
      {catalog.isError ? <p className="text-sm text-red-300">Skill 目录加载失败，请刷新重试。</p> : null}

      <ul className="space-y-3">
        {skills.map((skill) => {
          const on = skill.enabled !== false
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
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">{skill.description}</p>
                  <p className="mt-1.5 inline-flex items-center gap-1 text-[11.5px] text-slate-500">
                    <Clock className="h-3 w-3" />
                    {skill.command} · v{skill.version ?? '1'} · {skill.activation_policy === 'model_allowed' ? '可自动激活' : '显式调用'}
                  </p>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button variant={on ? 'subtle' : 'primary'} size="sm" disabled={!skill.id || pending} onClick={() => toggle(skill)}>
                  {pending ? '更新中…' : on ? '停用' : '启用'}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => showToast(skill.usage, 'info')}>
                  查看用法
                </Button>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
