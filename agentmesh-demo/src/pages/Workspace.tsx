import { FileSearch, Search } from 'lucide-react'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Composer } from '../components/workspace/Composer'
import { ConversationThread } from '../components/workspace/ConversationThread'
import { DetailPanel } from '../components/workspace/DetailPanel'
import {
  useDocumentJobsQuery,
  useSearchQuery,
  useSendMessageMutation,
  useSkillsQuery,
  useThreadDetailQuery,
  useUploadDocumentMutation,
  useWorkspaceScope,
  workspaceErrorMessage,
  ChatSendError,
} from '../features/workspace/queries'
import type { ResourceSelection } from '../features/workspace/types'

function threadIdFromPath(pathname: string): string | null {
  const encoded = pathname.match(/^\/workspace\/thread\/([^/]+)$/)?.[1]
  if (!encoded) return null
  try {
    return decodeURIComponent(encoded)
  } catch {
    return null
  }
}

const JOB_STATUS_LABEL = {
  queued: '排队中',
  running: '处理中',
  completed: '完成',
  failed: '失败',
} as const

export function Workspace() {
  const scope = useWorkspaceScope()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const threadId = threadIdFromPath(pathname)
  const thread = useThreadDetailQuery(scope, threadId)
  const skills = useSkillsQuery(scope)
  const sendMessage = useSendMessageMutation(scope)
  const upload = useUploadDocumentMutation(scope)
  const jobs = useDocumentJobsQuery(scope)
  const [draft, setDraft] = useState('')
  const [clientTurnId, setClientTurnId] = useState(() => crypto.randomUUID())
  const [pending, setPending] = useState<{
    content: string
    status: 'sending' | 'retryable' | 'processing' | 'failed' | 'unknown'
  } | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [selection, setSelection] = useState<ResourceSelection | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const search = useSearchQuery(scope, submittedSearch)
  const scrollRef = useRef<HTMLDivElement>(null)

  async function send(content = draft) {
    const normalized = content.trim()
    if (!normalized || sendMessage.isPending) return
    setPending({ content: normalized, status: 'sending' })
    setDraft('')
    setSendError(null)
    try {
      const response = await sendMessage.mutateAsync({
        threadId,
        content: normalized,
        clientTurnId,
      })
      if (response.thread_id !== threadId) {
        navigate(`/workspace/thread/${encodeURIComponent(response.thread_id)}`)
      }
      setPending(null)
      setClientTurnId(crypto.randomUUID())
    } catch (error) {
      setDraft(normalized)
      const state = error instanceof ChatSendError ? error.state : 'unknown'
      setPending({ content: normalized, status: state })
      setSendError(workspaceErrorMessage(error))
      if (error instanceof ChatSendError && error.threadId && error.threadId !== threadId) {
        navigate(`/workspace/thread/${encodeURIComponent(error.threadId)}`)
      }
    }
  }

  const messages = thread.data?.messages ?? []
  const tracesByAssistantMessageId = useMemo(
    () => new Map(
      (thread.data?.turn_traces ?? []).map((trace) => [trace.assistant_message_id, trace]),
    ),
    [thread.data?.turn_traces],
  )

  useLayoutEffect(() => {
    const scrollContainer = scrollRef.current
    if (!scrollContainer) return
    scrollContainer.scrollTop = scrollContainer.scrollHeight
  }, [messages.length, pending?.content, pending?.status, thread.isLoading])
  const uploadFileName = upload.variables?.name

  return (
    <div className="relative flex h-full min-w-0 overflow-hidden">
      <div ref={scrollRef} aria-label="对话滚动区域" className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1120px] px-4 pb-52 pt-6 md:px-6 md:pt-8">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
            <div className="min-w-0">
              {sendError ? (
                <p role="alert" className="mb-4 rounded-[10px] border border-rose/25 bg-rose/10 px-4 py-3 text-sm text-rose">
                  {sendError}
                </p>
              ) : null}
              {thread.isError ? (
                <div className="mb-4 rounded-[12px] border border-rose/20 bg-rose/10 px-4 py-4">
                  <p role="alert" className="text-sm text-rose">{workspaceErrorMessage(thread.error)}</p>
                  <button type="button" onClick={() => navigate('/workspace')} className="mt-3 text-xs font-semibold text-mint-300">
                    返回新对话
                  </button>
                </div>
              ) : null}
              <ConversationThread
                title={thread.data?.thread.title}
                messages={messages}
                tracesByAssistantMessageId={tracesByAssistantMessageId}
                pending={pending}
                loading={thread.isLoading}
                onOpenSource={(source) => setSelection({ kind: 'source', source })}
              />
            </div>

            <aside className="space-y-4" aria-label="Workspace resources">
              <section className="rounded-[14px] border border-white/[0.07] bg-surface-1 p-4">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                  <Search className="h-4 w-4 text-mint-300" aria-hidden="true" />
                  搜索可见资料
                </div>
                <form
                  className="mt-3 flex gap-2"
                  onSubmit={(event) => {
                    event.preventDefault()
                    setSubmittedSearch(searchInput.trim())
                  }}
                >
                  <input
                    aria-label="搜索资料"
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                    className="min-w-0 flex-1 rounded-[9px] border border-white/[0.08] bg-base px-3 py-2 text-xs text-slate-100 outline-none focus:border-mint-400/40"
                    placeholder="关键词"
                  />
                  <button type="submit" disabled={!searchInput.trim()} className="rounded-[9px] bg-mint-400 px-3 py-2 text-xs font-semibold text-[#06231c] disabled:opacity-40">
                    搜索
                  </button>
                </form>
                {search.isFetching ? <p className="mt-3 text-xs text-slate-500">正在搜索…</p> : null}
                {search.isError ? <p role="alert" className="mt-3 text-xs text-rose">{workspaceErrorMessage(search.error)}</p> : null}
                {search.data?.items.length === 0 ? <p className="mt-3 text-xs text-slate-500">没有可见结果。</p> : null}
                <div className="mt-3 space-y-2">
                  {search.data?.items.map((result) => (
                    <article key={`${result.result_type}-${result.id}`} data-testid="search-result" className="rounded-[10px] border border-white/[0.06] bg-base p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-xs font-semibold text-slate-200">{result.title}</p>
                          <p className="mt-1 text-[11px] text-slate-500">{result.result_type} · {result.scope}</p>
                        </div>
                        {result.result_type === 'document' || result.sources?.[0] ? (
                          <button
                            type="button"
                            onClick={() => setSelection(
                              result.result_type === 'document'
                                ? { kind: 'document', id: result.id }
                                : { kind: 'source', source: result.sources![0] },
                            )}
                            className="shrink-0 text-[11px] font-semibold text-mint-300"
                          >
                            查看详情
                          </button>
                        ) : null}
                      </div>
                      <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-400">{result.summary}</p>
                      {result.sources?.map((source) => (
                        <p key={source.id ?? source.reference} className="mt-1 truncate text-[11px] text-slate-500">来源：{source.title} · {source.source_type}</p>
                      ))}
                    </article>
                  ))}
                </div>
              </section>

              {upload.isPending || upload.data || upload.isError ? (
                <section data-testid="upload-status" className="rounded-[14px] border border-white/[0.07] bg-surface-1 p-4 text-xs">
                  <div className="flex items-center gap-2 font-semibold text-slate-200"><FileSearch className="h-4 w-4 text-mint-300" aria-hidden="true" />文档上传</div>
                  <p className="mt-2 break-all text-slate-400">{uploadFileName}</p>
                  {upload.isPending ? <p className="mt-1 text-slate-500">正在提交…</p> : null}
                  {upload.data?.item ? <p className="mt-1 text-mint-300">已导入 · {upload.data.item.completed_chunks}/{upload.data.item.expected_chunks} chunks</p> : null}
                  {upload.data?.job ? <p className="mt-1 text-amber-300">已进入任务队列</p> : null}
                  {upload.isError ? <p role="alert" className="mt-1 text-rose">{workspaceErrorMessage(upload.error)}</p> : null}
                </section>
              ) : null}

              {jobs.data?.items.length ? (
                <section className="rounded-[14px] border border-white/[0.07] bg-surface-1 p-4">
                  <h2 className="text-sm font-semibold text-slate-200">我的导入任务</h2>
                  <div className="mt-3 space-y-2">
                    {jobs.data.items.map((job) => (
                      <article key={job.id} data-testid="document-job" className="rounded-[9px] bg-base p-3 text-xs">
                        <div className="flex items-center justify-between gap-2"><span className="truncate text-slate-300">{job.file_name}</span><span className={job.status === 'failed' ? 'text-rose' : 'text-mint-300'}>{JOB_STATUS_LABEL[job.status]}</span></div>
                        <p className="mt-1 text-slate-500">{job.completed_chunks}/{job.expected_chunks} chunks</p>
                        {job.status === 'failed' ? <p role="alert" className="mt-2 text-rose">{job.error ?? '导入失败'}</p> : null}
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}
            </aside>
          </div>
        </div>
      </div>

      <Composer
        value={draft}
        skills={skills.data?.items ?? []}
        sending={sendMessage.isPending}
        sendState={pending?.status === 'sending' ? null : pending?.status ?? null}
        statusMessage={pending?.status === 'sending' ? null : sendError}
        onChange={(value) => {
          setDraft(value)
          if (pending?.status === 'retryable') {
            setPending(null)
            setClientTurnId(crypto.randomUUID())
          }
          setSendError(null)
        }}
        onSend={() => void send()}
        onRetry={() => void send(pending?.content ?? draft)}
        onUpload={(file) => upload.mutate(file)}
      />
      <DetailPanel selection={selection} scope={scope} onClose={() => setSelection(null)} />
    </div>
  )
}
