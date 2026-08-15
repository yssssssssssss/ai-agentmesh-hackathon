import { ArrowRight, PlayCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { DigitalSelfViewModel } from '../../features/digital-self/presenter'
import { Button } from '../ui/Button'
import { ModuleSourceBadges, ValueSourceBadge } from './SourceBadges'

interface WelcomeHeroProps {
  model: DigitalSelfViewModel['hero']
}

export function WelcomeHero({ model }: WelcomeHeroProps) {
  const navigate = useNavigate()
  const hero = model.data

  if (!hero) {
    return (
      <section className="border-b border-white/[0.08] pb-7" aria-live="polite">
        {model.loading ? <p className="text-sm text-slate-400">正在读取当前进展…</p> : null}
        {model.error ? <p role="alert" className="text-sm text-rose">{model.error}</p> : null}
        {!model.loading && !model.error ? <p className="text-sm text-slate-500">当前工作上下文不可用。</p> : null}
      </section>
    )
  }

  return (
    <section className="border-b border-white/[0.08] pb-7" aria-labelledby="digital-self-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-mint-300">当前进展</div>
        <ModuleSourceBadges sources={model.sources} />
      </div>
      <h1 id="digital-self-heading" className="mt-3 text-[28px] font-bold tracking-tight text-white">
        {hero.greeting.value}
      </h1>
      <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[13px] text-slate-400">
        <span>{hero.workspaceName.value}</span>
        <span aria-hidden="true" className="text-slate-600">·</span>
        <span className="font-medium text-slate-200">{hero.projectName.value}</span>
        <ValueSourceBadge value={hero.projectName} />
      </div>
      <p className="mt-2 max-w-4xl text-[13px] leading-6 text-slate-500">项目目标：{hero.projectGoal.value}</p>
      <div className="mt-3 flex max-w-5xl flex-wrap items-center gap-x-2 gap-y-1 text-[15px] leading-7 text-slate-300">
        <span>{hero.progressNarrative.value}</span>
        <ValueSourceBadge value={hero.progressNarrative} />
        <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
          参考参与人数 {hero.participantCount.value}
          <ValueSourceBadge value={hero.participantCount} />
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-slate-400">
        {hero.agentName ? (
          <span className="inline-flex items-center gap-1.5">
            {hero.agentName.value}
            <ValueSourceBadge value={hero.agentName} />
          </span>
        ) : null}
        {hero.agentStatus ? (
          <span className="rounded-pill bg-mint-400/10 px-2 py-1 font-medium text-mint-300">
            {hero.agentStatus.value}
          </span>
        ) : null}
        {hero.currentTask?.value ? <span>当前任务：{hero.currentTask.value}</span> : null}
        {model.loading ? <span role="status" className="text-slate-500">正在同步数字员工状态…</span> : null}
        {model.error ? <span role="alert" className="text-rose">{model.error}</span> : null}
      </div>

      <div className="mt-5">
        <Button
          size="lg"
          icon={<PlayCircle className="h-[18px] w-[18px]" aria-hidden="true" />}
          iconRight={<ArrowRight className="h-4 w-4" aria-hidden="true" />}
          onClick={() => navigate('/workspace')}
        >
          继续当前项目
        </Button>
      </div>
    </section>
  )
}
