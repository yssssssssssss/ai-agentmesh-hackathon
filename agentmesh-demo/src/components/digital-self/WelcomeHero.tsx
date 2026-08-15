import { Sparkles } from 'lucide-react'

import type { components } from '../../api/generated/schema'

interface WelcomeHeroProps {
  user: components['schemas']['User']
  project: components['schemas']['Project']
  workspace: components['schemas']['Workspace']
}

export function WelcomeHero({ user, project, workspace }: WelcomeHeroProps) {
  return (
    <header className="overflow-hidden rounded-[16px] border border-mint-400/15 bg-gradient-to-br from-mint-400/[0.09] via-surface-1 to-surface-1 p-6 md:p-8">
      <div className="flex items-start gap-4">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] bg-mint-400/15 text-mint-300">
          <Sparkles className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mint-300">Digital Self</p>
          <h1 className="mt-2 text-2xl font-bold tracking-tight text-white md:text-3xl">{user.name}的数字人</h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            {workspace.name} · 当前项目：{project.name}
          </p>
        </div>
      </div>
    </header>
  )
}
