import { useMemo, useState } from 'react'
import { Wrench, Zap, Users, Clock } from 'lucide-react'
import { StatTile } from '../ui/StatTile'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { CONFIGURED_SKILLS, type SkillSource } from '../../data/mockData'
import { useDemo } from '../../store/DemoContext'
import { cn } from '../../lib/cn'

const SOURCE_TONE: Record<SkillSource, 'collab' | 'knowledge' | 'neutral'> = {
  团队共享: 'collab',
  个人配置: 'knowledge',
  平台内置: 'neutral',
}

/**
 * 能力与 Skill —— 数字人已配置的能力。
 * 概览 3 指标 + Skill 列表(来源/用途/状态/最近调用 + 启用/停用)。
 * 启用/停用为临时本地态,离开页面重置(Demo 可接受)。
 */
export function SkillsSection() {
  const { showToast } = useDemo()
  const [enabledMap, setEnabledMap] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(CONFIGURED_SKILLS.map((s) => [s.id, s.status === 'enabled'])),
  )

  const stats = useMemo(() => {
    const enabled = CONFIGURED_SKILLS.filter((s) => enabledMap[s.id]).length
    const team = CONFIGURED_SKILLS.filter((s) => s.source === '团队共享').length
    return { total: CONFIGURED_SKILLS.length, enabled, team }
  }, [enabledMap])

  const toggle = (id: string, name: string) => {
    setEnabledMap((prev) => {
      const next = { ...prev, [id]: !prev[id] }
      showToast(next[id] ? `已启用「${name}」` : `已停用「${name}」`, 'info')
      return next
    })
  }

  return (
    <div className="animate-fade-in space-y-6">
      <header>
        <h1 className="flex items-center gap-2.5 text-xl font-semibold text-white">
          <Wrench className="h-5 w-5 text-mint-300" />
          能力与 Skill
        </h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">
          数字人在工作中可调用的能力。来源包括团队共享、你的个人配置与平台内置,你可以按需启用或停用。
        </p>
      </header>

      <div className="grid grid-cols-3 gap-3">
        <StatTile label="可用 Skill" value={stats.total} icon={<Wrench className="h-4 w-4" />} tone="mint" />
        <StatTile label="已启用" value={stats.enabled} icon={<Zap className="h-4 w-4" />} tone="knowledge" />
        <StatTile label="团队共享" value={stats.team} icon={<Users className="h-4 w-4" />} tone="collab" />
      </div>

      <ul className="space-y-3">
        {CONFIGURED_SKILLS.map((s) => {
          const on = enabledMap[s.id]
          return (
            <li key={s.id} className="card-base p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[14.5px] font-semibold text-slate-100">{s.name}</h3>
                    <Badge tone={SOURCE_TONE[s.source]}>{s.source}</Badge>
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 text-[11.5px]',
                        on ? 'text-mint-300' : 'text-slate-500',
                      )}
                    >
                      <span className={cn('h-1.5 w-1.5 rounded-full', on ? 'bg-mint-400' : 'bg-slate-600')} />
                      {on ? '已启用' : '已停用'}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-slate-400">{s.purpose}</p>
                  <p className="mt-1.5 inline-flex items-center gap-1 text-[11.5px] text-slate-500">
                    <Clock className="h-3 w-3" />
                    最近调用:{s.lastUsed}
                  </p>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  variant={on ? 'subtle' : 'primary'}
                  size="sm"
                  onClick={() => toggle(s.id, s.name)}
                >
                  {on ? '停用' : '启用'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => showToast('该 Skill 的调用详情为演示数据', 'info')}
                >
                  查看详情
                </Button>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
