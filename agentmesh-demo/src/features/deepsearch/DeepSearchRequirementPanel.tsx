import { Check, CircleHelp, LockKeyhole, MessageSquareText } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'

import { Button } from '../../components/ui/Button'
import { cn } from '../../lib/cn'
import type {
  ClarificationAnswer,
  DeepSearchClarificationQuestion,
  DeepSearchClarifyRequest,
  DeepSearchRequirement,
} from './types'

interface DeepSearchRequirementPanelProps {
  requirement: DeepSearchRequirement
  planExists: boolean
  waitingForClarification: boolean
  submitting: boolean
  error: string | null
  onSubmit: (request: DeepSearchClarifyRequest) => void
}

const CONSTRAINT_LABEL = {
  time: '时间',
  cost: '成本',
  source: '来源',
  permission: '权限',
  format: '格式',
} as const

function createClientTurnId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `deepsearch-clarify-${Date.now()}`
}

function initialAnswers(questions: DeepSearchClarificationQuestion[]): Record<string, ClarificationAnswer> {
  return Object.fromEntries(
    questions.flatMap((question) => (
      question.default_value == null ? [] : [[question.id, question.default_value]]
    )),
  )
}

function hasAnswer(question: DeepSearchClarificationQuestion, value: ClarificationAnswer | undefined): boolean {
  if (question.answer_kind === 'multi_choice') return Array.isArray(value) && value.length > 0
  return typeof value === 'string' && value.trim().length > 0
}

function answerText(answer: ClarificationAnswer | undefined): string {
  if (Array.isArray(answer)) return answer.join('、')
  return answer ?? '未回答'
}

function DetailList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div>
      <dt className="text-[11px] font-medium text-slate-400">{title}</dt>
      <dd className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span key={item} className="rounded-full bg-white/[0.05] px-2.5 py-1 text-xs text-slate-300">{item}</span>
        ))}
      </dd>
    </div>
  )
}

export function DeepSearchRequirementPanel({
  requirement,
  planExists,
  waitingForClarification,
  submitting,
  error,
  onSubmit,
}: DeepSearchRequirementPanelProps) {
  const payload = requirement.payload
  const questions = payload.clarification_questions
  const [answers, setAnswers] = useState<Record<string, ClarificationAnswer>>(() => initialAnswers(questions))
  const [clientTurnId] = useState(createClientTurnId)
  const canSubmit = useMemo(
    () => questions.every((question) => !question.required || hasAnswer(question, answers[question.id])),
    [answers, questions],
  )

  function updateAnswer(questionId: string, value: ClarificationAnswer) {
    setAnswers((current) => ({ ...current, [questionId]: value }))
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit || submitting) return
    const submittedAnswers = Object.fromEntries(
      questions.flatMap((question) => {
        const answer = answers[question.id]
        return hasAnswer(question, answer) && answer !== undefined ? [[question.id, answer]] : []
      }),
    )
    onSubmit({
      client_turn_id: clientTurnId,
      expected_requirement_version: requirement.version,
      answers: submittedAnswers,
    })
  }

  return (
    <section aria-labelledby="deepsearch-requirement-title" className="mt-4 rounded-soft bg-surface-1 px-5 py-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-mint-300">Requirement · v{requirement.version}</p>
          <h2 id="deepsearch-requirement-title" className="mt-1.5 text-lg font-semibold text-slate-100">当前需求理解</h2>
        </div>
        {planExists ? (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-400">
            <LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />
            Plan 已生成，需求只读
          </span>
        ) : (
          <span className="text-[11px] text-slate-400">澄清后由服务端生成唯一 Plan</span>
        )}
      </div>

      <div className="mt-5 border-l-2 border-mint-400/35 pl-4">
        <p className="text-[11px] text-slate-400">研究目标</p>
        <p className="mt-1.5 text-base leading-7 text-slate-100">{payload.goal}</p>
      </div>

      <dl className="mt-5 grid gap-4 border-t border-white/[0.06] pt-4 sm:grid-cols-2">
        <DetailList title="研究对象" items={payload.scope.objects} />
        <DetailList title="目标受众" items={payload.scope.audiences} />
        <DetailList title="区域" items={payload.scope.regions} />
        <DetailList title="边界" items={payload.scope.boundaries} />
        {payload.scope.time_range ? (
          <div>
            <dt className="text-[11px] font-medium text-slate-400">时间范围</dt>
            <dd className="mt-1.5 text-xs leading-5 text-slate-300">{payload.scope.time_range}</dd>
          </div>
        ) : null}
      </dl>

      <div className="mt-5 grid gap-5 border-t border-white/[0.06] pt-4 md:grid-cols-2">
        <section aria-labelledby="deepsearch-deliverables-title">
          <h3 id="deepsearch-deliverables-title" className="text-xs font-semibold text-slate-300">交付物</h3>
          <ul className="mt-2 space-y-1.5 text-xs leading-5 text-slate-400">
            {payload.deliverables.map((item) => <li key={item}>— {item}</li>)}
          </ul>
        </section>
        <section aria-labelledby="deepsearch-success-title">
          <h3 id="deepsearch-success-title" className="text-xs font-semibold text-slate-300">成功标准</h3>
          <ul className="mt-2 space-y-1.5 text-xs leading-5 text-slate-400">
            {payload.success_criteria.map((item) => (
              <li key={item.id} className="flex gap-2">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mint-300" aria-hidden="true" />
                {item.statement}
              </li>
            ))}
          </ul>
        </section>
      </div>

      {payload.constraints.length > 0 ? (
        <section aria-labelledby="deepsearch-constraints-title" className="mt-5 border-t border-white/[0.06] pt-4">
          <h3 id="deepsearch-constraints-title" className="text-xs font-semibold text-slate-300">约束</h3>
          <dl className="mt-2 space-y-2 text-xs leading-5">
            {payload.constraints.map((constraint, index) => (
              <div key={`${constraint.kind}-${index}`} className="flex gap-3">
                <dt className="w-10 shrink-0 text-slate-400">{CONSTRAINT_LABEL[constraint.kind]}</dt>
                <dd className="text-slate-300">{constraint.statement}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {payload.assumptions.length > 0 ? (
        <section aria-labelledby="deepsearch-assumptions-title" className="mt-5 border-t border-white/[0.06] pt-4">
          <h3 id="deepsearch-assumptions-title" className="text-xs font-semibold text-slate-300">显式假设</h3>
          <ul className="mt-2 space-y-2 text-xs leading-5 text-slate-400">
            {payload.assumptions.map((assumption) => (
              <li key={assumption.id} className="flex items-start justify-between gap-3">
                <span>{assumption.statement}</span>
                <span className="shrink-0 text-[11px] text-slate-400">
                  {planExists || !assumption.editable_before_plan ? '只读' : '确认 Plan 前可调整'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {payload.clarification_history.length > 0 ? (
        <details className="mt-5 border-t border-white/[0.06] pt-4">
          <summary className="cursor-pointer text-xs font-semibold text-slate-400 hover:text-slate-200">
            已完成 {payload.clarification_history.length} 轮澄清
          </summary>
          <ol className="mt-3 space-y-4">
            {payload.clarification_history.map((history) => (
              <li key={history.round} className="border-l border-white/[0.09] pl-3">
                <p className="text-[11px] font-medium text-slate-400">第 {history.round} 轮</p>
                <dl className="mt-2 space-y-2">
                  {history.questions.map((question) => (
                    <div key={question.id}>
                      <dt className="text-xs text-slate-400">{question.prompt}</dt>
                      <dd className="mt-0.5 text-xs text-slate-200">{answerText(history.answers[question.id])}</dd>
                    </div>
                  ))}
                </dl>
              </li>
            ))}
          </ol>
        </details>
      ) : null}

      {waitingForClarification && questions.length > 0 ? (
        <form onSubmit={submit} className="mt-5 border-t border-mint-400/15 pt-5" aria-labelledby="deepsearch-clarification-title">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="deepsearch-clarification-title" className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              <MessageSquareText className="h-4 w-4 text-mint-300" aria-hidden="true" />
              请补充关键信息
            </h3>
            <span className="text-[11px] text-mint-300">第 {payload.clarification_round} / 3 轮</span>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-400">回答后系统会更新当前理解；仍有阻塞歧义时会继续下一轮。</p>

          <div className="mt-4 space-y-5">
            {questions.map((question, index) => {
              const answer = answers[question.id]
              const labelId = `deepsearch-question-${question.id}`
              return (
                <fieldset key={question.id} className="min-w-0">
                  <legend id={labelId} className="text-sm font-medium leading-6 text-slate-200">
                    {index + 1}. {question.prompt}
                    <span className={cn(
                      'ml-2 rounded-full px-2 py-0.5 text-[11px]',
                      question.required ? 'bg-rose/10 text-rose' : 'bg-white/[0.05] text-slate-400',
                    )}>
                      {question.required ? '阻塞问题' : question.default_value == null ? '可选' : '可采用默认值'}
                    </span>
                  </legend>
                  {question.answer_kind === 'text' ? (
                    <textarea
                      aria-labelledby={labelId}
                      aria-required={question.required}
                      maxLength={question.max_length}
                      rows={3}
                      value={typeof answer === 'string' ? answer : ''}
                      onChange={(event) => updateAnswer(question.id, event.target.value)}
                      className="mt-2 w-full resize-y rounded-soft border border-white/[0.08] bg-base px-3 py-2.5 text-sm leading-6 text-slate-100 outline-none placeholder:text-slate-500 focus:border-mint-400/45"
                      placeholder={question.default_value ? `默认：${String(question.default_value)}` : '请输入回答'}
                    />
                  ) : (
                    <div className="mt-2 grid gap-2 sm:grid-cols-2">
                      {question.options.map((option) => {
                        const checked = question.answer_kind === 'single_choice'
                          ? answer === option
                          : Array.isArray(answer) && answer.includes(option)
                        return (
                          <label key={option} className={cn(
                            'flex min-h-11 cursor-pointer items-center gap-2.5 rounded-soft border px-3 py-2 text-xs transition-[border-color,background-color,color] duration-150',
                            checked
                              ? 'border-mint-400/35 bg-mint-400/[0.07] text-slate-100'
                              : 'border-white/[0.07] bg-base text-slate-400 hover:border-white/[0.14]',
                          )}>
                            <input
                              type={question.answer_kind === 'single_choice' ? 'radio' : 'checkbox'}
                              name={question.id}
                              value={option}
                              checked={checked}
                              onChange={() => {
                                if (question.answer_kind === 'single_choice') {
                                  updateAnswer(question.id, option)
                                  return
                                }
                                const current = Array.isArray(answer) ? answer : []
                                updateAnswer(
                                  question.id,
                                  checked ? current.filter((item) => item !== option) : [...current, option],
                                )
                              }}
                              className="accent-[#2dd4a8]"
                            />
                            {option}
                          </label>
                        )
                      })}
                    </div>
                  )}
                </fieldset>
              )
            })}
          </div>

          {error ? <p role="alert" className="mt-4 text-sm text-rose">{error}</p> : null}
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <p className="flex items-center gap-1.5 text-[11px] text-slate-400">
              <CircleHelp className="h-3.5 w-3.5" aria-hidden="true" />
              必填问题完成后才会继续规划
            </p>
            <Button type="submit" size="sm" loading={submitting} disabled={!canSubmit}>
              提交本轮回答
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  )
}
