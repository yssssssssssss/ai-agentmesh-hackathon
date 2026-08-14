import { Sparkles } from 'lucide-react'
import type {
  ChatTurnTrace,
  MemoryKind,
  MemorySearchScope,
  MemorySearchTrace,
  Source,
} from '../../lib/api'
import { Badge } from '../ui/Badge'
import { useChat, type ChatViewMessage } from '../../store/ChatContext'

const STEP_LABELS: Record<string, string> = {
  received_user_message: '收到用户消息',
  parsed_skill_command: '识别任务意图',
  searched_memory: '检索工作记忆',
  created_blackboard_request: '创建协作请求',
  requested_tool_call_approval: '请求工具调用审批',
  received_data_agent_evidence: '收到数据查询结果',
  received_acquisition_evidence: '收到资料获取结果',
  quarantined_acquisition_evidence: '隔离待审核资料',
  received_blackboard_evidence: '收到协作补充',
  quarantined_research_evidence: '隔离待审核研究资料',
  released_quarantined_research_evidence: '放行审核资料',
  discarded_quarantined_research_evidence: '丢弃审核资料',
  returned_chat_response: '返回对话结果',
  task_failed: '任务执行失败',
  memory_searched: '检索工作记忆',
  external_research_requested: '请求外部研究',
  evidence_received: '收到资料',
  synthesized: '整理结果',
  brief_drafted: '生成 Brief 草稿',
  review_requested: '请求审核',
  approved: '审核通过',
  memory_candidate_created: '创建记忆候选',
}

const EXTERNAL_REFERENCE = /^https?:\/\//i
const MEMORY_SCOPE_LABELS: Record<MemorySearchScope, string> = {
  auto: '自动（个人 / 项目 / 团队）',
  personal: '个人记忆',
  project: '当前项目记忆',
  team: '团队已采纳记忆',
}

const MEMORY_KIND_META = {
  personal: { label: '个人记忆', tone: 'knowledge' },
  project: { label: '项目记忆', tone: 'mint' },
  team: { label: '团队记忆', tone: 'collab' },
} as const satisfies Record<MemoryKind, { label: string; tone: 'knowledge' | 'mint' | 'collab' }>

export function ConversationThread() {
  const {
    messages,
    tracesByAssistantMessageId,
    sending,
    loadingHistory,
    lastError,
  } = useChat()

  if (loadingHistory) {
    return (
      <div className="flex min-h-[420px] items-center justify-center text-[13px] text-slate-500">
        正在恢复对话…
      </div>
    )
  }

  if (lastError && messages.length === 0) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center text-center">
        <h1 className="text-[17px] font-semibold text-slate-200">无法恢复这段对话</h1>
        <p className="mt-2 text-[12.5px] text-slate-500">请开始新对话，或从左侧选择其他记录。</p>
      </div>
    )
  }

  if (messages.length === 0) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-[14px] bg-mint-400/10 text-mint-300">
          <Sparkles className="h-5 w-5" />
        </span>
        <h1 className="mt-4 text-[19px] font-semibold text-white">开始新对话</h1>
        <p className="mt-2 max-w-[420px] text-[13px] leading-relaxed text-slate-500">
          在下方输入任务或问题，数字员工会在你的权限范围内调用工作知识。
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {messages.map((message) =>
        message.role === 'user' ? (
          <UserMessage key={message.id} message={message} />
        ) : (
          <AssistantMessage
            key={message.id}
            message={message}
            trace={tracesByAssistantMessageId[message.id]}
          />
        ),
      )}
      {sending ? (
        <div className="flex items-center gap-2 text-[12.5px] text-slate-500">
          <span className="h-2 w-2 animate-pulse rounded-full bg-mint-300" />
          数字员工正在思考……
        </div>
      ) : null}
    </div>
  )
}

function UserMessage({ message }: { message: ChatViewMessage }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[90%] whitespace-pre-wrap rounded-[14px] rounded-tr-sm bg-surface-3 px-4 py-3 text-[14px] leading-relaxed text-slate-100">
        <div>{message.content}</div>
        {message.delivery === 'pending' ? (
          <div className="mt-1 text-right text-[10.5px] text-slate-500">发送中…</div>
        ) : null}
        {message.delivery === 'failed' ? (
          <div className="mt-1 text-right text-[10.5px] text-remind">发送失败，内容未保存</div>
        ) : null}
      </div>
    </div>
  )
}

function AssistantMessage({
  message,
  trace,
}: {
  message: ChatViewMessage
  trace?: ChatTurnTrace
}) {
  const sources = mergeSources(trace?.sources ?? [], message.sources)

  return (
    <div className="w-full space-y-3">
      <div className="whitespace-pre-wrap text-[14px] leading-[1.75] text-slate-100">
        {message.content}
      </div>
      {trace ? <TurnTrace trace={trace} /> : null}
      {sources.length > 0 ? <SourceList sources={sources} /> : null}
    </div>
  )
}

function TurnTrace({ trace }: { trace: ChatTurnTrace }) {
  return (
    <section className="rounded-[12px] border border-white/[0.07] bg-surface-1 px-3.5 py-3" aria-label="本轮执行依据">
      <div className="text-[12.5px] font-medium text-slate-300">本轮执行依据</div>
      <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] leading-relaxed text-slate-500">
        <TraceMeta label="意图" value={trace.intent} />
        <TraceMeta label="来源" value={trace.source} />
        <TraceMeta label="工作流" value={trace.selected_workflow} />
        <TraceMeta label="生成方式" value={trace.llm_used ? '大模型生成' : '规则或回退生成'} />
        <TraceMeta label="记录状态" value={trace.persisted ? '已保存' : '未保存'} />
        {trace.fallback_reason ? <TraceMeta label="回退原因" value={trace.fallback_reason} /> : null}
      </dl>
      {trace.steps.length > 0 ? (
        <ol className="mt-3 space-y-2 border-t border-white/[0.06] pt-3">
          {trace.steps.map((step, index) => (
            <li key={`${step}-${index}`} className="flex gap-2.5 text-[12px] leading-relaxed">
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-white/[0.06] text-[9.5px] tabular-nums text-slate-500">
                {index + 1}
              </span>
              <span className="min-w-0 text-slate-400">
                {STEP_LABELS[step] ?? '执行步骤'}
                <code className="ml-2 break-all text-[10.5px] text-slate-600">{step}</code>
              </span>
            </li>
          ))}
        </ol>
      ) : null}
      {trace.memory_search ? <MemorySearchSection memorySearch={trace.memory_search} /> : null}
    </section>
  )
}

function MemorySearchSection({ memorySearch }: { memorySearch: MemorySearchTrace }) {
  return (
    <section className="mt-3 border-t border-white/[0.06] pt-3" aria-label="记忆检索">
      <div className="text-[12px] font-medium text-slate-400">记忆检索</div>
      <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] leading-relaxed text-slate-500">
        <TraceMeta label="请求范围" value={MEMORY_SCOPE_LABELS[memorySearch.requested_scope]} />
        <TraceMeta label="个人" value={String(memorySearch.personal_count)} />
        <TraceMeta label="项目" value={String(memorySearch.project_count)} />
        <TraceMeta label="团队" value={String(memorySearch.team_count)} />
      </dl>
      {memorySearch.results.length > 0 ? (
        <ol className="mt-3 space-y-2">
          {memorySearch.results.map((result) => {
            const kindMeta = MEMORY_KIND_META[result.memory_kind]
            return (
              <li key={result.result_id} className="rounded-[10px] border border-white/[0.06] px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[11px] font-medium text-slate-400">[{result.citation_label}]</span>
                  <Badge tone={kindMeta.tone} className="px-2 py-0.5 text-[10px]">
                    {kindMeta.label}
                  </Badge>
                  <h4 className="min-w-0 text-[12.5px] font-medium text-slate-200">{result.title}</h4>
                </div>
                <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">{result.summary}</p>
              </li>
            )
          })}
        </ol>
      ) : null}
    </section>
  )
}

function TraceMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 gap-1">
      <dt>{label}</dt>
      <dd className="break-all text-slate-400">{value}</dd>
    </div>
  )
}

function SourceList({ sources }: { sources: Source[] }) {
  return (
    <section className="space-y-2" aria-label="本轮资料来源">
      <div className="text-[12px] font-medium text-slate-400">资料来源</div>
      <ul className="space-y-1.5">
        {sources.map((source) => (
          <li key={source.id} className="rounded-[10px] border border-white/[0.06] px-3 py-2 text-[12px] leading-relaxed">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-slate-300">{source.title}</span>
              <span className="text-[10.5px] text-slate-600">{source.source_type}</span>
              {isDemoSource(source.id) ? (
                <span className="rounded-full bg-remind/10 px-1.5 py-0.5 text-[10px] font-medium text-remind">演示来源</span>
              ) : null}
            </div>
            {source.reference ? <SourceReference reference={source.reference} /> : null}
          </li>
        ))}
      </ul>
    </section>
  )
}

function SourceReference({ reference }: { reference: string }) {
  if (EXTERNAL_REFERENCE.test(reference)) {
    return (
      <a
        href={reference}
        target="_blank"
        rel="noreferrer"
        className="mt-0.5 block break-all text-[11px] text-mint-300 transition-colors hover:text-mint-200"
      >
        {reference}
      </a>
    )
  }
  return <div className="mt-0.5 break-all text-[11px] text-slate-600">{reference}</div>
}

function isDemoSource(id: string) {
  return id.startsWith('src_demo_') || id.startsWith('src_seed_')
}

function mergeSources(traceSources: Source[], messageSources: Source[]) {
  const sourcesById = new Map<string, Source>()
  for (const source of traceSources) sourcesById.set(source.id, source)
  for (const source of messageSources) {
    if (!sourcesById.has(source.id)) sourcesById.set(source.id, source)
  }
  return [...sourcesById.values()]
}
