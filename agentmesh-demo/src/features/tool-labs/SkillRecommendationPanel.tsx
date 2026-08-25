import { ArrowUpRight, Search } from 'lucide-react'
import { useState } from 'react'

import { Button } from '../../components/ui/Button'
import { useSkillMatchesMutation, workspaceErrorMessage } from '../workspace/queries'
import { missingToolsSummary } from '../workspace/skillPresentation'
import type { SkillMatch, SkillMatchResponse } from '../workspace/types'

const STAGE_LABELS: Record<NonNullable<SkillMatch['primary_stage']>, string> = {
  pre_design: '设计前',
  during_design: '设计中',
  post_design: '设计后',
  platform: '平台能力',
}

export function skillMatchCommand(match: SkillMatch): string {
  const name = match.command.trim().replace(/^\$/, '')
  return `$${name}`
}

export function skillMatchDraft(match: SkillMatch, task: string): string {
  const command = skillMatchCommand(match)
  const content = task.trim()
  return content ? `${command} ${content}` : `${command} `
}

export function visibleSkillMatches(matches: SkillMatch[]): SkillMatch[] {
  return matches
    .filter((match) => match.readiness !== 'unavailable' && match.execution_readiness !== 'unavailable')
    .slice(0, 5)
}

export function skillMatchResponseMatchesTask(submittedTask: string, currentTask: string): boolean {
  return Boolean(submittedTask) && submittedTask === currentTask.trim()
}

export function shouldResetSkillMatchState(
  submittedTask: string,
  currentTask: string,
  mutationIsIdle: boolean,
): boolean {
  return !mutationIsIdle && !skillMatchResponseMatchesTask(submittedTask, currentTask)
}

export function skillMatchModePresentation(response: SkillMatchResponse): { label: string; degraded: boolean } {
  const diagnostics = new Set(response.diagnostics ?? [])
  if (response.mode === 'llm_reranked') return { label: 'LLM 语义重排', degraded: false }
  if (response.mode === 'hybrid') return { label: '关键词 + 向量语义', degraded: false }
  if (response.mode === 'fallback') {
    if (diagnostics.has('embedding_unavailable') || diagnostics.has('embedding_timeout')) {
      return { label: '当前使用关键词匹配 · 语义召回已降级', degraded: true }
    }
    return { label: 'LLM 重排已降级 · 已使用确定性匹配', degraded: true }
  }
  const degraded = diagnostics.has('embedding_unavailable') || diagnostics.has('llm_unavailable')
  return {
    label: degraded ? '当前使用关键词匹配 · 语义能力已降级' : '关键词匹配',
    degraded,
  }
}

export function SkillMatchResults({
  matches,
  submittedTask,
  onUseSkill,
}: {
  matches: SkillMatch[]
  submittedTask: string
  onUseSkill: (draft: string) => void
}) {
  const visible = visibleSkillMatches(matches)
  if (visible.length === 0) {
    return (
      <p className="rounded-[10px] bg-base/70 px-4 py-5 text-sm text-slate-400">
        没有找到当前可调用的 Skill。可以补充任务目标、输入材料或期望产出后重试。
      </p>
    )
  }

  return (
    <ol className="space-y-2.5">
      {visible.map((match) => {
        const command = skillMatchCommand(match)
        const toolLimited = match.execution_readiness === 'tool_limited'
        const missingTools = missingToolsSummary(match.missing_tools)
        return (
          <li
            key={match.skill_id}
            data-testid="skill-match-result"
            className="flex flex-col gap-3 rounded-[12px] border border-white/[0.07] bg-base/70 p-4 sm:flex-row sm:items-start"
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="min-w-0 break-words text-sm font-semibold text-slate-100">{match.title}</h3>
                <span className="rounded-full bg-white/[0.06] px-2 py-1 text-[11px] text-slate-400">
                  {match.primary_stage ? STAGE_LABELS[match.primary_stage] : '未分类 Skill'}
                </span>
                <span className={toolLimited ? 'text-[11px] text-amber-300' : match.planner_eligible ? 'text-[11px] text-mint-300' : 'text-[11px] text-slate-400'}>
                  {toolLimited ? '已接入 · 工具待接通' : match.planner_eligible ? '可自动编排' : '可显式调用'}
                </span>
              </div>
              <p className="mt-1 break-all font-mono text-xs text-mint-300">{command}</p>
              <p className="mt-2 break-words text-xs leading-5 text-slate-300">{match.reason}</p>
              <p className="mt-1 break-words text-xs leading-5 text-slate-500">{match.description}</p>
              {toolLimited ? (
                <p className="mt-2 break-words text-xs leading-5 text-amber-200/80" title={match.missing_tools?.join('、')}>
                  待接通工具：{missingTools}
                </p>
              ) : null}
            </div>
            <Button
              type="button"
              aria-label={`使用 Skill：${match.title}`}
              variant="secondary"
              size="md"
              className="self-start"
              iconRight={<ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />}
              onClick={() => onUseSkill(skillMatchDraft(match, submittedTask))}
            >
              使用此 Skill
            </Button>
          </li>
        )
      })}
    </ol>
  )
}

export function SkillMatchOutcome({
  response,
  submittedTask,
  onUseSkill,
}: {
  response: SkillMatchResponse
  submittedTask: string
  onUseSkill: (draft: string) => void
}) {
  const clarification = response.clarification?.trim()
  if (clarification) {
    return (
      <div className="rounded-[10px] border border-amber-300/20 bg-amber-300/[0.08] px-4 py-4">
        <h2 className="text-sm font-semibold text-amber-200">还需要补充任务信息</h2>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-300">{clarification}</p>
      </div>
    )
  }

  const mode = skillMatchModePresentation(response)

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-100">推荐结果</h2>
        <span className="text-xs tabular-nums text-slate-500">
          {visibleSkillMatches(response.items).length} 个
        </span>
      </div>
      <p
        role={mode.degraded ? 'status' : undefined}
        className={mode.degraded ? 'mb-3 text-xs text-amber-300' : 'mb-3 text-xs text-slate-500'}
      >
        匹配方式：{mode.label}
      </p>
      <SkillMatchResults matches={response.items} submittedTask={submittedTask} onUseSkill={onUseSkill} />
    </div>
  )
}

export function SkillRecommendationPanel({ onUseSkill }: { onUseSkill: (draft: string) => void }) {
  const [task, setTask] = useState('')
  const [submittedTask, setSubmittedTask] = useState('')
  const matches = useSkillMatchesMutation()
  const responseMatchesTask = skillMatchResponseMatchesTask(submittedTask, task)

  return (
    <div data-testid="skill-recommendation-panel" className="mx-auto max-w-3xl space-y-5">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          const content = task.trim()
          if (content) {
            setSubmittedTask(content)
            matches.mutate({ content, limit: 5 })
          }
        }}
      >
        <label htmlFor="skill-match-task" className="text-xs font-medium text-slate-300">
          要完成的任务
        </label>
        <textarea
          id="skill-match-task"
          name="skill-match-task"
          value={task}
          maxLength={4000}
          rows={4}
          placeholder="例如：评审这份商品详情页方案，并给出可执行的体验优化建议"
          onChange={(event) => {
            const nextTask = event.target.value
            setTask(nextTask)
            if (shouldResetSkillMatchState(submittedTask, nextTask, matches.isIdle)) matches.reset()
          }}
          className="mt-2 min-h-28 w-full resize-y rounded-[10px] border border-white/[0.08] bg-base px-3.5 py-3 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-600 focus-visible:border-mint-400/40 focus-visible:ring-2 focus-visible:ring-mint-400/30"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs leading-5 text-slate-500">
            根据任务语义匹配当前已接入且启用的 Skill，执行时仍会检查工具权限与资源。
          </p>
          <Button
            type="submit"
            size="md"
            loading={matches.isPending}
            disabled={!task.trim()}
            icon={<Search className="h-4 w-4" aria-hidden="true" />}
          >
            获取推荐
          </Button>
        </div>
      </form>

      <section aria-live="polite" aria-busy={matches.isPending}>
        {matches.isPending ? (
          <p role="status" className="rounded-[10px] bg-base/70 px-4 py-5 text-sm text-slate-400">
            正在匹配 Skill…
          </p>
        ) : null}
        {matches.isError && responseMatchesTask ? (
          <p role="alert" className="rounded-[10px] border border-rose/25 bg-rose/10 px-4 py-3 text-sm text-rose">
            {workspaceErrorMessage(matches.error)}
          </p>
        ) : null}
        {matches.isSuccess && responseMatchesTask ? (
          <SkillMatchOutcome response={matches.data} submittedTask={submittedTask} onUseSkill={onUseSkill} />
        ) : null}
        {!matches.isPending && (!matches.isError || !responseMatchesTask) && (!matches.isSuccess || !responseMatchesTask) ? (
          <div className="rounded-[12px] border border-dashed border-white/[0.08] px-4 py-8 text-center">
            <Search className="mx-auto h-5 w-5 text-slate-600" aria-hidden="true" />
            <p className="mt-2 text-sm text-slate-400">
              {submittedTask ? '任务已更新，请重新获取推荐。' : '描述任务后，系统会推荐最匹配的 Skill。'}
            </p>
          </div>
        ) : null}
      </section>
    </div>
  )
}
