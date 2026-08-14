import { useEffect, useMemo, useRef, useState } from 'react'
import { Paperclip, Sparkles, UserPlus, ArrowUp, Square } from 'lucide-react'
import { useDemo } from '../../store/DemoContext'
import { useChat } from '../../store/ChatContext'
import { api, type ChatSkill } from '../../lib/api'
import { cn } from '../../lib/cn'

export function Composer({ beforeSend }: { beforeSend?: () => void }) {
  const { showToast } = useDemo()
  const { send, sending, loadingHistory } = useChat()
  const [value, setValue] = useState('')
  const [skills, setSkills] = useState<ChatSkill[]>([])
  const [skillsLoaded, setSkillsLoaded] = useState(false)
  const [skillError, setSkillError] = useState(false)
  const [selectedSkillIndex, setSelectedSkillIndex] = useState(0)
  const [skillMenuDismissed, setSkillMenuDismissed] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    let cancelled = false
    api.chat.skills()
      .then((items) => {
        if (cancelled) return
        setSkills(items)
        setSkillsLoaded(true)
      })
      .catch(() => {
        if (cancelled) return
        setSkillError(true)
        setSkillsLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const skillQuery = value.trim().toLowerCase()
  const acceptsSkillSelection = skillQuery.startsWith('$') && !skillQuery.includes(' ')
  const filteredSkills = useMemo(() => {
    if (!acceptsSkillSelection) return []
    return skills.filter((skill) => {
      const searchable = [skill.command, skill.title, skill.description, ...skill.aliases]
      return searchable.some((item) => item.toLowerCase().includes(skillQuery))
    })
  }, [acceptsSkillSelection, skillQuery, skills])
  const skillMenuOpen = acceptsSkillSelection && !skillMenuDismissed

  function handleSend() {
    const text = value.trim()
    if (!text || sending || loadingHistory) return
    beforeSend?.()
    setSkillMenuDismissed(true)
    setValue('')
    send(text).catch(() => {
      showToast('发送失败，请重试', 'info')
    })
  }

  function chooseSkill(skill: ChatSkill) {
    setValue(`${skill.command}${skill.requires_input ? ' ' : ''}`)
    setSkillMenuDismissed(true)
    window.requestAnimationFrame(() => textareaRef.current?.focus())
  }

  function handleInputKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (skillMenuOpen && filteredSkills.length > 0) {
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setSelectedSkillIndex((index) => (index + 1) % filteredSkills.length)
        return
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setSelectedSkillIndex((index) => (index - 1 + filteredSkills.length) % filteredSkills.length)
        return
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault()
        chooseSkill(filteredSkills[selectedSkillIndex] ?? filteredSkills[0])
        return
      }
    }
    if (event.key === 'Escape' && skillMenuOpen) {
      event.preventDefault()
      setSkillMenuDismissed(true)
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSend()
    }
  }

  function openSkillMenu() {
    setValue('$')
    setSelectedSkillIndex(0)
    setSkillMenuDismissed(false)
    window.requestAnimationFrame(() => textareaRef.current?.focus())
  }

  function handleStop() {
    showToast('实时生成中，暂不支持中断', 'info')
  }

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-base via-base/95 to-transparent px-6 pb-5 pt-8">
      <div className="pointer-events-auto mx-auto max-w-[800px]">
        {skillMenuOpen ? (
          <div className="mb-2 max-h-[300px] overflow-y-auto rounded-[14px] border border-white/[0.09] bg-surface-1 p-1.5 shadow-pop" role="listbox" aria-label="可用 Skill">
            {!skillsLoaded ? (
              <div className="px-3 py-3 text-[12px] text-slate-500">正在加载 Skill…</div>
            ) : skillError ? (
              <div className="px-3 py-3 text-[12px] text-remind">Skill 列表加载失败，请稍后重试</div>
            ) : filteredSkills.length === 0 ? (
              <div className="px-3 py-3 text-[12px] text-slate-500">没有匹配的 Skill</div>
            ) : (
              filteredSkills.map((skill, index) => (
                <button
                  key={skill.command}
                  type="button"
                  role="option"
                  aria-selected={index === selectedSkillIndex}
                  onMouseEnter={() => setSelectedSkillIndex(index)}
                  onClick={() => chooseSkill(skill)}
                  className={cn(
                    'block w-full rounded-[10px] px-3 py-2.5 text-left transition-colors',
                    index === selectedSkillIndex ? 'bg-white/[0.07]' : 'hover:bg-white/[0.04]',
                  )}
                >
                  <div className="flex items-center gap-2">
                    <code className="text-[12.5px] font-medium text-mint-300">{skill.command}</code>
                    <span className="text-[12px] text-slate-300">{skill.title}</span>
                  </div>
                  <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">{skill.description}</p>
                </button>
              ))
            )}
          </div>
        ) : null}

        <div className="rounded-[16px] border border-white/[0.08] bg-surface-1 shadow-card transition-colors focus-within:border-white/[0.16]">
          <textarea
            ref={textareaRef}
            value={value}
            disabled={loadingHistory}
            onChange={(event) => {
              setValue(event.target.value)
              setSelectedSkillIndex(0)
              setSkillMenuDismissed(false)
            }}
            onKeyDown={handleInputKeyDown}
            rows={1}
            placeholder={loadingHistory ? '正在恢复对话…' : '继续推进这个任务，或输入 $ 选择 Skill……'}
            className="max-h-40 w-full resize-none bg-transparent px-4 pt-3.5 text-[14px] leading-relaxed text-slate-100 placeholder:text-slate-600 focus:outline-none"
          />
          <div className="flex items-center justify-between px-3 pb-3 pt-1">
            <div className="flex items-center gap-1">
              <ToolButton icon={Paperclip} label="上传附件" onClick={() => showToast('已打开附件上传（演示）', 'info')} />
              <ToolButton icon={Sparkles} label="选择 Skill" onClick={openSkillMenu} />
              <ToolButton icon={UserPlus} label="邀请数字员工" onClick={() => showToast('已打开数字员工邀请（演示）', 'info')} />
            </div>
            {loadingHistory ? (
              <span className="px-2 text-[12px] text-slate-500">正在恢复对话…</span>
            ) : sending ? (
              <button onClick={handleStop} className="flex items-center gap-1.5 rounded-[10px] border border-white/[0.1] bg-surface-2 px-3 py-2 text-[13px] font-medium text-slate-200 transition-colors hover:bg-surface-3">
                <Square className="h-3 w-3 fill-current" />
                停止生成
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!value.trim()}
                className={cn(
                  'flex h-8 w-8 items-center justify-center rounded-[10px] transition-all',
                  value.trim()
                    ? 'bg-mint-400 text-[#06231c] hover:bg-mint-300 active:scale-95'
                    : 'cursor-not-allowed bg-white/[0.06] text-slate-600',
                )}
                aria-label="发送"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
        <div className="mt-2 text-center text-[11px] text-slate-600">数字员工回答基于团队知识与历史项目，请结合实际判断使用</div>
      </div>
    </div>
  )
}

function ToolButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof Paperclip
  label: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-[8px] px-2.5 py-1.5 text-[12px] text-slate-400 transition-colors hover:bg-white/[0.05] hover:text-slate-200"
    >
      <Icon className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">{label}</span>
    </button>
  )
}
