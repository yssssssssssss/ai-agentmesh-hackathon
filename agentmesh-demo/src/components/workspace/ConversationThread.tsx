import { Bot, FileText, UserRound } from 'lucide-react'

import type {
  ChatMessage,
  ChatTurnTrace,
  MemorySearchTrace,
  Source,
} from '../../features/workspace/types'

interface PendingMessage {
  content: string
  status: 'sending' | 'retryable' | 'processing' | 'failed' | 'unknown'
}

const PENDING_STATUS_LABEL: Record<PendingMessage['status'], string> = {
  sending: '正在发送…',
  retryable: '服务端未收到，可安全重试',
  processing: '服务端已受理，正在核对状态',
  failed: '服务端已受理但未完成',
  unknown: '暂时无法核对服务端状态',
}

const STEP_LABELS: Record<string, string> = {
  received_user_message: '收到用户消息',
  parsed_skill_command: '识别任务意图',
  searched_memory: '检索工作记忆',
  memory_searched: '检索工作记忆',
  created_blackboard_request: '创建协作请求',
  external_research_requested: '请求外部研究',
  evidence_received: '收到资料',
  synthesized: '整理结果',
  brief_drafted: '生成 Brief 草稿',
  review_requested: '请求审核',
  approved: '审核通过',
  memory_candidate_created: '创建记忆候选',
  returned_chat_response: '返回对话结果',
  task_failed: '任务执行失败',
}

const MEMORY_SCOPE_LABELS: Record<MemorySearchTrace['requested_scope'], string> = {
  auto: '自动（个人 / 项目 / 团队）',
  personal: '个人记忆',
  project: '当前项目记忆',
  team: '团队已采纳记忆',
}

const MEMORY_KIND_LABELS: Record<MemorySearchTrace['results'][number]['memory_kind'], string> = {
  personal: '个人记忆',
  project: '项目记忆',
  team: '团队记忆',
}

interface ConversationThreadProps {
  title?: string
  messages: ChatMessage[]
  tracesByAssistantMessageId: ReadonlyMap<string, ChatTurnTrace>
  pending: PendingMessage | null
  loading: boolean
  onOpenSource: (source: Source) => void
}

function Provenance({ message }: { message: ChatMessage }) {
  const trace = message.workflow_trace
  if (!trace) return null
  return (
    <dl data-testid="provider-provenance" className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
      <div className="flex gap-1"><dt>请求提供方</dt><dd className="text-slate-300">{trace.requested_provider ?? 'agentmesh'}</dd></div>
      <div className="flex gap-1"><dt>实际提供方</dt><dd className="text-slate-300">{trace.actual_provider ?? trace.requested_provider ?? 'agentmesh'}</dd></div>
      {trace.requested_model ? <div className="flex gap-1"><dt>请求模型</dt><dd className="text-slate-300">{trace.requested_model}</dd></div> : null}
      {trace.actual_model ? <div className="flex gap-1"><dt>实际模型</dt><dd className="text-slate-300">{trace.actual_model}</dd></div> : null}
      <div className="flex gap-1"><dt>模式</dt><dd className="text-slate-300">{trace.provider_mode ?? (trace.llm_used ? 'real' : 'fallback')}</dd></div>
      {trace.latency_ms != null ? <div className="flex gap-1"><dt>延迟</dt><dd className="text-slate-300">{Math.round(trace.latency_ms)} ms</dd></div> : null}
      {trace.fallback_reason ? <div className="flex gap-1"><dt>降级原因</dt><dd className="text-amber-300">{trace.fallback_reason}</dd></div> : null}
      {trace.model_fallback_reason ? <div className="flex gap-1"><dt>模型切换原因</dt><dd className="text-amber-300">{trace.model_fallback_reason}</dd></div> : null}
      <div className="flex gap-1"><dt>工作流</dt><dd className="text-slate-300">{trace.selected_workflow}</dd></div>
    </dl>
  )
}

function TraceMeta({ label, value }: { label: string; value: string }) {
  return <div className="flex min-w-0 gap-1"><dt>{label}</dt><dd className="break-all text-slate-300">{value}</dd></div>
}

function MemorySearch({ trace }: { trace: MemorySearchTrace }) {
  return (
    <section className="mt-3 border-t border-white/[0.06] pt-3" aria-label="记忆检索">
      <dl className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
        <TraceMeta label="检索范围" value={MEMORY_SCOPE_LABELS[trace.requested_scope]} />
        <TraceMeta label="个人" value={String(trace.personal_count)} />
        <TraceMeta label="项目" value={String(trace.project_count)} />
        <TraceMeta label="团队" value={String(trace.team_count)} />
      </dl>
      {trace.results.length > 0 ? (
        <ol className="mt-3 space-y-2">
          {trace.results.map((result) => (
            <li key={result.result_id} className="rounded-[9px] border border-white/[0.06] bg-base px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <span className="font-mono font-semibold text-mint-300">[{result.citation_label}]</span>
                <span className="text-slate-500">{MEMORY_KIND_LABELS[result.memory_kind]}</span>
                <span className="font-medium text-slate-200">{result.title}</span>
              </div>
              <p className="mt-1 text-[11px] leading-5 text-slate-500">{result.summary}</p>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  )
}

function TurnTrace({ trace }: { trace: ChatTurnTrace }) {
  return (
    <section data-testid="turn-trace" className="mt-3 rounded-[10px] border border-white/[0.06] bg-white/[0.025] px-3 py-3" aria-label="本轮执行依据">
      <div className="text-xs font-semibold text-slate-300">本轮执行依据</div>
      <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
        <TraceMeta label="意图" value={trace.intent} />
        <TraceMeta label="来源" value={trace.source} />
        <TraceMeta label="工作流" value={trace.selected_workflow} />
        <TraceMeta label="生成方式" value={trace.llm_used ? '大模型生成' : '规则或回退生成'} />
        <TraceMeta label="记录状态" value={trace.persisted ? '已保存' : '未保存'} />
        {trace.fallback_reason ? <TraceMeta label="回退原因" value={trace.fallback_reason} /> : null}
      </dl>
      {trace.steps.length > 0 ? (
        <ol className="mt-3 flex flex-wrap gap-1.5 border-t border-white/[0.06] pt-3">
          {trace.steps.map((step, index) => (
            <li key={`${step}-${index}`} className="rounded-full bg-white/[0.05] px-2.5 py-1 text-[10px] text-slate-400" title={step}>
              {index + 1}. {STEP_LABELS[step] ?? step}
            </li>
          ))}
        </ol>
      ) : null}
      {trace.memory_search ? <MemorySearch trace={trace.memory_search} /> : null}
    </section>
  )
}

function sourceKey(source: Source): string {
  return source.id ?? `${source.source_type}:${source.reference}`
}

function mergeSources(messageSources: Source[], trace?: ChatTurnTrace): Source[] {
  const sources = new Map<string, Source>()
  for (const source of messageSources) sources.set(sourceKey(source), source)
  for (const source of trace?.sources ?? []) sources.set(sourceKey(source), source)
  for (const result of trace?.memory_search?.results ?? []) {
    for (const source of result.sources) sources.set(sourceKey(source), source)
  }
  return [...sources.values()]
}

export function ConversationThread({
  title,
  messages,
  tracesByAssistantMessageId,
  pending,
  loading,
  onOpenSource,
}: ConversationThreadProps) {
  return (
    <section aria-label="对话内容" className="space-y-6">
      <header className="border-b border-white/[0.06] pb-4">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-mint-300">AI 工作台</p>
        <h1 className="mt-1.5 text-xl font-semibold text-white">{title ?? 'AI 工作台'}</h1>
      </header>

      {loading ? <p className="py-10 text-center text-sm text-slate-500">正在加载对话…</p> : null}
      {!loading && messages.length === 0 && !pending ? (
        <div className="rounded-[14px] border border-dashed border-white/[0.1] px-5 py-12 text-center">
          <Bot className="mx-auto h-6 w-6 text-mint-300" aria-hidden="true" />
          <p className="mt-3 text-sm text-slate-300">选择一个对话，或发送第一条消息开始。</p>
        </div>
      ) : null}

      {messages.map((message) => {
        const trace = message.role === 'assistant' ? tracesByAssistantMessageId.get(message.id) : undefined
        const sources = mergeSources(message.sources ?? [], trace)
        return (
          <article key={message.id} className={message.role === 'user' ? 'flex justify-end gap-3' : 'flex gap-3'}>
            {message.role === 'assistant' ? (
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-mint-400/10 text-mint-300">
                <Bot className="h-4 w-4" aria-hidden="true" />
              </span>
            ) : null}
            <div
              data-testid={message.role === 'assistant' ? 'assistant-message' : 'user-message'}
              className={message.role === 'user'
                ? 'max-w-[85%] rounded-[14px] rounded-tr-sm bg-surface-3 px-4 py-3 text-sm leading-6 text-slate-100'
                : 'min-w-0 max-w-[92%] rounded-[14px] rounded-tl-sm border border-white/[0.06] bg-surface-1 px-4 py-3 text-sm leading-6 text-slate-200'}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
              {sources.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-2 border-t border-white/[0.06] pt-3">
                  {sources.map((source) => (
                    <button
                      key={sourceKey(source)}
                      type="button"
                      aria-label={source.title}
                      onClick={() => onOpenSource(source)}
                      className="flex items-center gap-1.5 rounded-full bg-white/[0.05] px-2.5 py-1 text-xs text-slate-300 hover:bg-white/[0.09] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
                    >
                      <FileText className="h-3 w-3" aria-hidden="true" />
                      {source.title}
                    </button>
                  ))}
                </div>
              ) : null}
              {message.role === 'assistant' ? <Provenance message={message} /> : null}
              {trace ? <TurnTrace trace={trace} /> : null}
            </div>
            {message.role === 'user' ? (
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-white/[0.06] text-slate-300">
                <UserRound className="h-4 w-4" aria-hidden="true" />
              </span>
            ) : null}
          </article>
        )
      })}

      {pending ? (
        <article className="flex justify-end gap-3">
          <div className="max-w-[85%] rounded-[14px] rounded-tr-sm bg-surface-3 px-4 py-3 text-sm leading-6 text-slate-100 opacity-75">
            <p className="whitespace-pre-wrap">{pending.content}</p>
            <p className={`mt-1 text-[11px] ${pending.status === 'sending' ? 'text-slate-500' : 'text-rose'}`}>
              {PENDING_STATUS_LABEL[pending.status]}
            </p>
          </div>
        </article>
      ) : null}
    </section>
  )
}

