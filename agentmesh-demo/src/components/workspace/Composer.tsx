import { ArrowUp, ChevronRight, Paperclip, RotateCcw, SearchCheck, Sparkles } from 'lucide-react'
import { useMemo, useRef, useState, type ReactNode, type Ref } from 'react'

import { deepSearchAvailabilityMessage } from '../../features/deepsearch/presentation'
import type { AgentPlanningMode, DeepSearchAvailability } from '../../features/deepsearch/types'
import type { Skill } from '../../features/workspace/types'
import { groupSkillsByDesignStage, isCallableSkill } from '../../features/workspace/skillPresentation'
import { cn } from '../../lib/cn'
import { WORKSPACE_RESOURCE_GRID_CLASS } from './layout'

interface ComposerProps {
  rootRef?: Ref<HTMLDivElement>
  value: string
  skills: Skill[]
  sending: boolean
  locked?: boolean
  hasResourceRail?: boolean
  scrollbarGutter?: number
  planningMode: AgentPlanningMode
  deepSearchAvailability: DeepSearchAvailability
  sendState: 'retryable' | 'processing' | 'approval' | 'failed' | 'unknown' | null
  statusMessage: string | null
  toolLauncher?: ReactNode
  onChange: (value: string) => void
  onPlanningModeChange: (mode: AgentPlanningMode) => void
  onSend: () => void
  onRetry: () => void
  onUpload: (file: File) => void
}

type SkillGroup = ReturnType<typeof groupSkillsByDesignStage>[number]

export function resolveActiveSkillSelection(
  groups: SkillGroup[],
  activeGroupKey: string,
  selectedIndex: number,
): { group: SkillGroup | undefined; skill: Skill | undefined } {
  const group = groups.find((item) => item.key === activeGroupKey) ?? groups[0]
  return { group, skill: group?.items[selectedIndex] ?? group?.items[0] }
}

export function Composer({
  rootRef,
  value,
  skills,
  sending,
  locked = false,
  hasResourceRail = false,
  scrollbarGutter = 0,
  planningMode,
  deepSearchAvailability,
  sendState,
  statusMessage,
  toolLauncher,
  onChange,
  onPlanningModeChange,
  onSend,
  onRetry,
  onUpload,
}: ComposerProps) {
  const [skillsDismissed, setSkillsDismissed] = useState(false)
  const [activeSkillGroupKey, setActiveSkillGroupKey] = useState('pre_design')
  const [selectedSkillIndex, setSelectedSkillIndex] = useState(0)
  const fileInput = useRef<HTMLInputElement>(null)
  const interactionLocked = locked || sendState === 'processing' || sendState === 'approval'
  const deepSearchAvailabilityHint = deepSearchAvailabilityMessage(deepSearchAvailability)
  const canRetry = sendState === 'retryable' || sendState === 'processing' || sendState === 'unknown'
  const skillQuery = value.trim().toLowerCase()
  const acceptsSkillSelection = planningMode === 'standard' && skillQuery.startsWith('$') && !skillQuery.includes(' ')
  const matchingSkills = useMemo(() => {
    if (!acceptsSkillSelection) return []
    return skills.filter(isCallableSkill).filter((skill) => {
      const searchable = [skill.command, skill.title, skill.description, ...(skill.aliases ?? [])]
      return searchable.some((item) => item.toLowerCase().includes(skillQuery))
    })
  }, [acceptsSkillSelection, skillQuery, skills])
  const groupedSkills = useMemo(() => groupSkillsByDesignStage(matchingSkills), [matchingSkills])
  const { group: activeSkillGroup, skill: selectedSkill } = resolveActiveSkillSelection(
    groupedSkills,
    activeSkillGroupKey,
    selectedSkillIndex,
  )
  const skillMenuOpen = acceptsSkillSelection && !skillsDismissed

  function activateSkillGroup(groupKey: string) {
    setActiveSkillGroupKey(groupKey)
    const group = groupedSkills.find((item) => item.key === groupKey)
    if (group?.items.length) setSelectedSkillIndex(0)
  }

  function moveSkillGroup(offset: number) {
    if (!activeSkillGroup || groupedSkills.length === 0) return
    const currentIndex = groupedSkills.findIndex((group) => group.key === activeSkillGroup.key)
    const nextIndex = (currentIndex + offset + groupedSkills.length) % groupedSkills.length
    const next = groupedSkills[nextIndex]
    if (next) activateSkillGroup(next.key)
  }

  function moveWithinActiveGroup(offset: number) {
    if (!activeSkillGroup || activeSkillGroup.items.length === 0) return
    const currentIndex = Math.min(selectedSkillIndex, activeSkillGroup.items.length - 1)
    setSelectedSkillIndex(
      (currentIndex + offset + activeSkillGroup.items.length) % activeSkillGroup.items.length,
    )
  }

  function chooseSkill(skill: Skill) {
    onChange(`${skill.command}${skill.requires_input !== false ? ' ' : ''}`)
    setSkillsDismissed(true)
  }

  return (
    <div
      ref={rootRef}
      data-testid="workspace-composer-root"
      style={{ right: scrollbarGutter }}
      className="pointer-events-none absolute bottom-0 left-0 z-10 bg-gradient-to-t from-base via-base/95 to-transparent px-4 pb-5 pt-10 md:px-6"
    >
      <div
        data-testid="workspace-composer"
        className={cn(
          'pointer-events-auto mx-auto w-full max-w-[992px]',
          hasResourceRail && WORKSPACE_RESOURCE_GRID_CLASS,
        )}
      >
        <div className="min-w-0">
          {toolLauncher ? <div className="mb-2">{toolLauncher}</div> : null}
          {sendState ? (
            <div className="mb-2 flex items-center justify-between gap-3 rounded-soft border border-rose/25 bg-rose/10 px-3 py-2 text-xs text-rose">
              <span>{statusMessage ?? '发送状态已变化，草稿已保留。'}</span>
              {canRetry ? (
                <button type="button" onClick={onRetry} className="flex shrink-0 items-center gap-1 font-semibold">
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  {sendState === 'processing' || sendState === 'unknown' ? '重新核对' : '重试发送'}
                </button>
              ) : null}
            </div>
          ) : null}
          <div
            data-testid="workspace-composer-surface"
            data-planning-mode={planningMode}
            className="relative rounded-overlay border border-white/[0.08] bg-surface-1 shadow-card transition-[border-color,background-color] duration-200 focus-within:border-white/[0.16]"
          >
            {skillMenuOpen ? (
              <div
                data-testid="skill-hierarchy-menu"
                className="absolute bottom-full left-0 mb-2 h-[min(18rem,55vh)] w-full overflow-hidden rounded-soft border border-white/[0.1] bg-surface-2 shadow-card sm:w-[620px]"
              >
                {activeSkillGroup ? (
                  <div className="grid h-full min-h-0 grid-cols-[104px_minmax(0,1fr)] sm:grid-cols-[150px_minmax(0,1fr)]">
                    <div className="min-h-0 overflow-y-auto border-r border-white/[0.07] bg-base/45 p-1.5" role="tablist" aria-label="Skill 分类">
                      {groupedSkills.map((group) => {
                        const active = group.key === activeSkillGroup.key
                        return (
                          <button
                            key={group.key}
                            id={`skill-category-${group.key}`}
                            type="button"
                            role="tab"
                            aria-selected={active}
                            aria-controls={`skill-group-${group.key}`}
                            onMouseEnter={() => activateSkillGroup(group.key)}
                            onFocus={() => activateSkillGroup(group.key)}
                            onClick={() => activateSkillGroup(group.key)}
                            className={cn(
                              'mb-1 flex min-h-11 w-full items-center justify-between gap-2 rounded-soft px-2.5 text-left text-xs transition-[transform,background-color,color] duration-150 last:mb-0 active:scale-[0.97]',
                              active ? 'bg-white/[0.09] text-slate-100' : 'text-slate-400 hover:bg-white/[0.05] hover:text-slate-200',
                            )}
                          >
                            <span className="inline-flex min-w-0 items-center gap-2">
                              <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', group.dotClass)} aria-hidden="true" />
                              <span className="truncate">{group.label}</span>
                            </span>
                            <ChevronRight className={cn('h-3.5 w-3.5 shrink-0', active ? 'text-slate-300' : 'text-slate-400')} aria-hidden="true" />
                          </button>
                        )
                      })}
                    </div>

                    <section
                      key={activeSkillGroup.key}
                      id={`skill-group-${activeSkillGroup.key}`}
                      role="tabpanel"
                      aria-labelledby={`skill-category-${activeSkillGroup.key}`}
                      className="flex min-h-0 min-w-0 flex-col p-2"
                    >
                      <div className="shrink-0 px-2 py-1.5">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-xs font-semibold text-slate-200">{activeSkillGroup.label}</p>
                            <p className="mt-0.5 text-[11px] text-slate-400">{activeSkillGroup.description}</p>
                          </div>
                          <span className="text-[11px] text-slate-400">{activeSkillGroup.items.length}</span>
                        </div>
                      </div>
                      <div data-testid="skill-submenu-scroll" className="mt-1 min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1">
                        {activeSkillGroup.items.map((skill, index) => (
                          <button
                            key={skill.command}
                            type="button"
                            onMouseEnter={() => setSelectedSkillIndex(index)}
                            onClick={() => chooseSkill(skill)}
                            className={cn(
                              'block w-full rounded-soft px-2.5 py-2 text-left transition-[transform,background-color] duration-150 active:scale-[0.98]',
                              index === selectedSkillIndex ? 'bg-white/[0.08]' : 'hover:bg-white/[0.05]',
                            )}
                          >
                            <span className="block text-xs font-semibold text-mint-300">{skill.command}</span>
                            <span className="mt-0.5 block text-xs leading-5 text-slate-400">{skill.title} · {skill.description}</span>
                          </button>
                        ))}
                      </div>
                    </section>
                  </div>
                ) : (
                  <p className="px-3 py-3 text-xs text-slate-400">没有匹配的 Skill</p>
                )}
              </div>
            ) : null}
            <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] px-3 py-2">
              <div role="group" aria-label="回答模式" className="inline-flex rounded-soft bg-base p-0.5">
                <button
                  type="button"
                  aria-pressed={planningMode === 'standard'}
                  disabled={interactionLocked}
                  onClick={() => onPlanningModeChange('standard')}
                  className={cn(
                    'min-h-9 rounded-control px-3 text-xs font-medium transition-[transform,background-color,color] duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50 disabled:cursor-not-allowed disabled:opacity-50',
                    planningMode === 'standard'
                      ? 'bg-surface-3 text-slate-100'
                      : 'text-slate-400 hover:text-slate-300',
                  )}
                >
                  标准
                </button>
                <button
                  type="button"
                  aria-pressed={planningMode === 'deepsearch'}
                  aria-describedby={!deepSearchAvailability.available ? 'deepsearch-availability-hint' : undefined}
                  disabled={interactionLocked || !deepSearchAvailability.available}
                  onClick={() => onPlanningModeChange('deepsearch')}
                  className={cn(
                    'flex min-h-9 items-center gap-1.5 rounded-control px-3 text-xs font-medium transition-[transform,background-color,color] duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50 disabled:cursor-not-allowed disabled:opacity-45',
                    planningMode === 'deepsearch'
                      ? 'bg-mint-400/12 text-mint-300'
                      : 'text-slate-400 hover:text-slate-300',
                  )}
                >
                  <SearchCheck className="h-3.5 w-3.5" aria-hidden="true" />
                  DeepSearch
                </button>
              </div>
              <p id="deepsearch-availability-hint" className="text-[11px] leading-4 text-slate-400">
                {planningMode === 'deepsearch'
                  ? '先澄清需求和确认计划，再执行检索并封存报告'
                  : deepSearchAvailability.available
                    ? '复杂研究可切换 DeepSearch'
                    : deepSearchAvailabilityHint}
              </p>
            </div>
            <textarea
              aria-label="消息"
              value={value}
              onChange={(event) => {
                onChange(event.target.value)
                setSelectedSkillIndex(0)
                setActiveSkillGroupKey('pre_design')
                setSkillsDismissed(false)
              }}
              onKeyDown={(event) => {
                if (skillMenuOpen && activeSkillGroup && activeSkillGroup.items.length > 0) {
                  if (event.key === 'ArrowDown') {
                    event.preventDefault()
                    moveWithinActiveGroup(1)
                    return
                  }
                  if (event.key === 'ArrowUp') {
                    event.preventDefault()
                    moveWithinActiveGroup(-1)
                    return
                  }
                  if (event.key === 'ArrowRight') {
                    event.preventDefault()
                    moveSkillGroup(1)
                    return
                  }
                  if (event.key === 'ArrowLeft') {
                    event.preventDefault()
                    moveSkillGroup(-1)
                    return
                  }
                  if (event.key === 'Enter' || event.key === 'Tab') {
                    event.preventDefault()
                    if (selectedSkill) chooseSkill(selectedSkill)
                    return
                  }
                }
                if (event.key === 'Escape' && skillMenuOpen) {
                  event.preventDefault()
                  setSkillsDismissed(true)
                  return
                }
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  onSend()
                }
              }}
              rows={2}
              disabled={sending || interactionLocked}
              placeholder={planningMode === 'deepsearch'
                ? '描述研究目标、范围、交付形式和判断标准…'
                : '输入问题，或选择 Skill 执行明确工作流…'}
              className="max-h-40 w-full resize-none bg-transparent px-4 pt-3.5 text-sm leading-relaxed text-slate-100 placeholder:text-slate-500 focus:outline-none disabled:opacity-60"
            />
            <div className="flex items-center justify-between px-3 pb-3 pt-1">
              <div className="flex items-center gap-1">
                <input
                  ref={fileInput}
                  type="file"
                  aria-label="上传文档"
                  className="sr-only"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) onUpload(file)
                    event.target.value = ''
                  }}
                />
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  className="flex min-h-10 items-center gap-1.5 rounded-control px-2.5 py-1.5 text-xs text-slate-400 transition-[transform,background-color,color] duration-150 active:scale-95 hover:bg-white/[0.05] hover:text-slate-200"
                >
                  <Paperclip className="h-3.5 w-3.5" aria-hidden="true" />
                  上传文档
                </button>
                <button
                  type="button"
                  aria-expanded={skillMenuOpen}
                  disabled={planningMode === 'deepsearch' || interactionLocked}
                  onClick={() => {
                    onChange('$')
                    setSkillsDismissed(false)
                    setActiveSkillGroupKey('pre_design')
                    setSelectedSkillIndex(0)
                  }}
                  className="flex min-h-10 items-center gap-1.5 rounded-control px-2.5 py-1.5 text-xs text-slate-400 transition-[transform,background-color,color] duration-150 active:scale-95 hover:bg-white/[0.05] hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-35"
                >
                  <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                  选择 Skill
                </button>
              </div>
              <button
                type="button"
                onClick={onSend}
                disabled={!value.trim() || sending || interactionLocked}
                className={cn(
                  'flex h-10 min-w-10 items-center justify-center rounded-soft px-2 transition-[transform,background-color,color] duration-150 active:scale-95',
                  value.trim() && !sending && !interactionLocked
                    ? 'bg-mint-400 text-[#06231c] hover:bg-mint-300'
                    : 'cursor-not-allowed bg-white/[0.06] text-slate-400',
                )}
                aria-label="发送"
              >
                {sending ? <span className="text-xs">发送中</span> : <ArrowUp className="h-4 w-4" aria-hidden="true" />}
              </button>
            </div>
          </div>
          <p className="mt-2 text-center text-[11px] text-slate-400">回答与来源均来自当前账号可见的服务端数据</p>
        </div>
      </div>
    </div>
  )
}
