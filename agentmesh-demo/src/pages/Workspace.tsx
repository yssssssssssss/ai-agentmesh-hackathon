import { FileSearch } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Composer } from '../components/workspace/Composer'
import { DemoConversationThread } from '../components/workspace/DemoConversationThread'
import { DemoConversationDetailPanel, type DemoDetailSelection } from '../components/workspace/DemoConversationDetailPanel'
import { ConversationThread } from '../components/workspace/ConversationThread'
import { DetailPanel } from '../components/workspace/DetailPanel'
import { ToolLauncherBar } from '../features/tool-labs/ToolLauncherBar'
import { WorkspaceToolDialog } from '../features/tool-labs/WorkspaceToolDialog'
import type { WorkspaceToolId } from '../features/tool-labs/types'
import {
  useDocumentJobsQuery,
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

const DEMO_THREAD_ID = 'thread_graph_demo'

export function Workspace() {
  const scope = useWorkspaceScope()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const threadId = threadIdFromPath(pathname)
  const isDemoThread = threadId === DEMO_THREAD_ID
  const thread = useThreadDetailQuery(scope, isDemoThread ? null : threadId)
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
  const [activeTool, setActiveTool] = useState<WorkspaceToolId | null>(null)
  const closeActiveTool = useCallback(() => setActiveTool(null), [])
  const [demoSelection, setDemoSelection] = useState<DemoDetailSelection | null>(null)
  useEffect(() => {
    if (!isDemoThread) setDemoSelection(null)
  }, [isDemoThread])
  const scrollRef = useRef<HTMLDivElement>(null)

  async function send(content = draft) {
    const normalized = content.trim()
    if (!normalized || sendMessage.isPending) return
    setPending({ content: normalized, status: 'sending' })
    setDraft('')
    setSendError(null)
    try {
      const response = await sendMessage.mutateAsync({
        threadId: isDemoThread ? null : threadId,
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
    if (isDemoThread) {
      scrollContainer.scrollTop = 0
      return
    }
    scrollContainer.scrollTop = scrollContainer.scrollHeight
  }, [isDemoThread, messages.length, pending?.content, pending?.status, thread.isLoading])
  const uploadFileName = upload.variables?.name
  const showResources = Boolean(upload.isPending || upload.data || upload.isError || jobs.data?.items.length)

  return (
    <div className="relative flex h-full min-w-0 overflow-hidden">
      <div ref={scrollRef} aria-label="对话滚动区域" className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1120px] px-4 pb-52 pt-6 md:px-6 md:pt-8">
          <div className={showResources ? 'grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]' : ''}>
            <div className="min-w-0">
              {sendError ? (
                <p role="alert" className="mb-4 rounded-[10px] border border-rose/25 bg-rose/10 px-4 py-3 text-sm text-rose">
                  {sendError}
                </p>
              ) : null}
              {!isDemoThread && thread.isError ? (
                <div className="mb-4 rounded-[12px] border border-rose/20 bg-rose/10 px-4 py-4">
                  <p role="alert" className="text-sm text-rose">{workspaceErrorMessage(thread.error)}</p>
                  <button type="button" onClick={() => navigate('/workspace')} className="mt-3 text-xs font-semibold text-mint-300">
                    返回新对话
                  </button>
                </div>
              ) : null}
              {isDemoThread ? (
                <DemoConversationThread
                  activeRefId={demoSelection?.kind === 'ref' ? demoSelection.ref.id : undefined}
                  onOpenRef={(reference) => setDemoSelection({ kind: 'ref', ref: reference })}
                  onOpenSources={() => setDemoSelection({ kind: 'sources' })}
                  onOpenBrief={() => setDemoSelection({ kind: 'brief' })}
                />
              ) : (
                <ConversationThread
                  title={thread.data?.thread.title}
                  messages={messages}
                  tracesByAssistantMessageId={tracesByAssistantMessageId}
                  pending={pending}
                  loading={thread.isLoading}
                  onOpenSource={(source) => setSelection({ kind: 'source', source })}
                />
              )}
            </div>

            {showResources ? <aside className="space-y-4" aria-label="Workspace resources">

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
            </aside> : null}
          </div>
        </div>
      </div>

      <Composer
        value={draft}
        skills={skills.data?.items ?? []}
        sending={sendMessage.isPending}
        sendState={pending?.status === 'sending' ? null : pending?.status ?? null}
        statusMessage={pending?.status === 'sending' ? null : sendError}
        toolLauncher={<ToolLauncherBar activeTool={activeTool} onOpen={setActiveTool} />}
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
      <WorkspaceToolDialog activeTool={activeTool} onClose={closeActiveTool} />
      {isDemoThread ? (
        <DemoConversationDetailPanel selection={demoSelection} onClose={() => setDemoSelection(null)} />
      ) : (
        <DetailPanel selection={selection} scope={scope} onClose={() => setSelection(null)} />
      )}
    </div>
  )
}
