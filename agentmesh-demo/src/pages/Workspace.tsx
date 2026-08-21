import { FileSearch, Search } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Composer } from '../components/workspace/Composer'
import { ConversationThread } from '../components/workspace/ConversationThread'
import { DetailPanel } from '../components/workspace/DetailPanel'
import { ResearchExecution, type ResearchPendingAction } from '../components/workspace/ResearchExecution'
import { ResearchPreview } from '../components/workspace/ResearchPreview'
import { SkillPlanPreview } from '../components/workspace/SkillPlanPreview'
import { SkillPlanProgress } from '../components/workspace/SkillPlanProgress'
import { SkillSynthesisView } from '../components/workspace/SkillSynthesisView'
import { WORKSPACE_RESOURCE_GRID_CLASS } from '../components/workspace/layout'
import { Button } from '../components/ui/Button'
import { useAuth } from '../features/auth/AuthProvider'
import { ResearchWorkbenchContainer } from '../features/research-workbench'
import { ToolLauncherBar } from '../features/tool-labs/ToolLauncherBar'
import { WorkspaceToolDialog } from '../features/tool-labs/WorkspaceToolDialog'
import type { WorkspaceToolId } from '../features/tool-labs/types'
import {
  useDocumentJobsQuery,
  useAgentRunEventSubscription,
  useAgentRunQuery,
  useCancelAgentRunMutation,
  useRetryAgentRunMutation,
  useResearchMutations,
  useResearchRunQuery,
  useSearchQuery,
  useSendAgentRunMutation,
  useSendMessageMutation,
  useSkillPlanMutations,
  useSkillPlanQuery,
  useSkillsQuery,
  useThreadDetailQuery,
  useUploadDocumentMutation,
  useWorkspaceScope,
  workspaceErrorMessage,
  ChatSendError,
} from '../features/workspace/queries'
import type { ResourceSelection, SkillResultSource } from '../features/workspace/types'

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
  const { bootstrap } = useAuth()
  const { pathname, search: locationSearch } = useLocation()
  const navigate = useNavigate()
  const threadId = threadIdFromPath(pathname)
  const searchParams = useMemo(() => new URLSearchParams(locationSearch), [locationSearch])
  const explicitRunId = searchParams.get('run')
  const prefilledSkill = searchParams.get('skill')
  const thread = useThreadDetailQuery(scope, threadId)
  const runId = explicitRunId ?? thread.data?.latest_research_run_id ?? null
  const skills = useSkillsQuery(scope)
  const sendMessage = useSendMessageMutation(scope)
  const sendAgentRun = useSendAgentRunMutation(scope)
  const runQuery = useAgentRunQuery(scope, runId)
  const currentRun = runQuery.data?.item
  const isResearchV2 = currentRun?.orchestration_version === 'research-v2'
  const isResearchV3 = currentRun?.orchestration_version === 'research-v3'
  const isResearchRun = isResearchV2 || isResearchV3
  const researchQuery = useResearchRunQuery(scope, isResearchV2 ? currentRun : null)
  const researchMutations = useResearchMutations(scope, isResearchV2 ? currentRun : null)
  const planQuery = useSkillPlanQuery(scope, runId, isResearchRun ? null : currentRun?.plan_id)
  const planMutations = useSkillPlanMutations(scope, runId)
  const cancelRun = useCancelAgentRunMutation(scope)
  const retryRun = useRetryAgentRunMutation(scope)
  useAgentRunEventSubscription(scope, currentRun)
  const runtimeV2 = bootstrap?.agent_runtime_enabled === true
  const orchestrationMode = bootstrap?.skill_orchestration_mode ?? 'off'
  const upload = useUploadDocumentMutation(scope)
  const jobs = useDocumentJobsQuery(scope)
  const [draft, setDraft] = useState('')
  const [clientTurnId, setClientTurnId] = useState(() => crypto.randomUUID())
  const [pending, setPending] = useState<{
    content: string
    status: 'sending' | 'retryable' | 'processing' | 'approval' | 'failed' | 'unknown'
  } | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [selection, setSelection] = useState<ResourceSelection | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const searchQuery = useSearchQuery(scope, submittedSearch)
  const [activeTool, setActiveTool] = useState<WorkspaceToolId | null>(null)
  const closeActiveTool = useCallback(() => setActiveTool(null), [])
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrollbarGutter, setScrollbarGutter] = useState(0)
  const runIsActive = Boolean(currentRun && [
    'created',
    'planning',
    'waiting_plan_approval',
    'running',
    'waiting_approval',
  ].includes(currentRun.status))

  useEffect(() => {
    if (!prefilledSkill) return
    setDraft((current) => current.trim() ? current : `${prefilledSkill} `)
  }, [prefilledSkill])

  async function send(content = draft) {
    const normalized = content.trim()
    if (!normalized || sendMessage.isPending || sendAgentRun.isPending || runIsActive) return
    setPending({ content: normalized, status: 'sending' })
    setDraft('')
    setSendError(null)
    try {
      const command = normalized.split(/\s+/, 1)[0]
      const legacyCommand = command.startsWith('$') && command.includes('.')
      const explicitSkillName = command.startsWith('$') && !legacyCommand ? command.slice(1) : undefined
      const shouldUseRuntime = runtimeV2 && !legacyCommand
      if (shouldUseRuntime) {
        const runtimeContent = explicitSkillName
          ? normalized.slice(command.length).trim() || normalized
          : normalized
        const response = await sendAgentRun.mutateAsync({
            threadId,
            content: runtimeContent,
            clientTurnId,
            explicitSkillName,
            orchestrationMode: explicitSkillName || orchestrationMode === 'off' ? 'single' : 'auto',
          })
        const started = response.item
        navigate(`/workspace/thread/${encodeURIComponent(started.thread_id)}?run=${encodeURIComponent(started.id)}`)
      } else {
        const response = await sendMessage.mutateAsync({ threadId, content: normalized, clientTurnId })
        if (response.thread_id !== threadId) {
          navigate(`/workspace/thread/${encodeURIComponent(response.thread_id)}`)
        }
      }
      setPending(null)
      setClientTurnId(crypto.randomUUID())
    } catch (error) {
      const state = error instanceof ChatSendError ? error.state : 'unknown'
      if (state === 'approval') {
        setDraft('')
        setClientTurnId(crypto.randomUUID())
      } else {
        setDraft(normalized)
      }
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
  const skillsById = useMemo(
    () => new Map((skills.data?.items ?? []).map((skill) => [skill.id, skill])),
    [skills.data?.items],
  )
  const planDetail = planQuery.data
  const planPendingAction = planMutations.update.isPending
    ? 'update'
    : planMutations.approve.isPending
      ? 'approve'
      : planMutations.reject.isPending
        ? 'reject'
        : null
  const planMutationError = planMutations.update.error
    ?? planMutations.approve.error
    ?? planMutations.reject.error
  const planError = planMutationError ? workspaceErrorMessage(planMutationError) : null
  const researchPendingAction: ResearchPendingAction = researchMutations.confirm.isPending
    ? 'confirm'
    : researchMutations.execute.isPending
      ? 'execute'
      : researchMutations.resolveTool.isPending
        ? researchMutations.resolveTool.variables?.action === 'reject' ? 'reject-tool' : 'approve-tool'
        : researchMutations.recover.isPending
          ? researchMutations.recover.variables?.action === 'abort' ? 'abort' : 'retry'
          : cancelRun.isPending && isResearchV2
            ? 'cancel'
            : null
  const researchMutationError = researchMutations.confirm.error
    ?? researchMutations.execute.error
    ?? researchMutations.resolveTool.error
    ?? researchMutations.recover.error
  const researchError = researchMutationError ? workspaceErrorMessage(researchMutationError) : null
  const canRetryRun = Boolean(currentRun && ['partial', 'failed', 'rejected', 'cancelled'].includes(currentRun.status))

  const openSkillSource = (source: SkillResultSource) => {
    setSelection({
      kind: 'source',
      source: {
        id: source.id,
        title: source.title,
        source_type: source.source_type,
        reference: source.reference,
      },
    })
  }

  const cancelCurrentRun = () => {
    if (!currentRun) return
    void cancelRun.mutateAsync(currentRun).catch((error) => setSendError(workspaceErrorMessage(error)))
  }

  const retryCurrentRun = () => {
    if (!currentRun) return
    setSendError(null)
    void retryRun.mutateAsync({ runId: currentRun.id, clientTurnId })
      .then((response) => {
        const nextRun = response.item
        setClientTurnId(crypto.randomUUID())
        navigate(`/workspace/thread/${encodeURIComponent(nextRun.thread_id)}?run=${encodeURIComponent(nextRun.id)}`)
      })
      .catch((error) => setSendError(workspaceErrorMessage(error)))
  }

  useLayoutEffect(() => {
    const scrollContainer = scrollRef.current
    if (!scrollContainer) return
    scrollContainer.scrollTop = scrollContainer.scrollHeight
  }, [
    currentRun?.status,
    messages.length,
    pending?.content,
    pending?.status,
    planDetail?.plan.updated_at,
    researchQuery.data?.workflow.state_version,
    thread.isLoading,
  ])
  const uploadFileName = upload.variables?.name
  const showResources = Boolean(upload.isPending || upload.data || upload.isError || jobs.data?.items.length)

  useLayoutEffect(() => {
    const scrollContainer = scrollRef.current
    if (!scrollContainer) return
    const updateScrollbarGutter = () => {
      setScrollbarGutter(scrollContainer.offsetWidth - scrollContainer.clientWidth)
    }
    updateScrollbarGutter()
    const observer = new ResizeObserver(updateScrollbarGutter)
    observer.observe(scrollContainer)
    return () => observer.disconnect()
  }, [])

  return (
    <div className="relative flex h-full min-w-0 overflow-hidden">
      <div ref={scrollRef} aria-label="对话滚动区域" className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1040px] px-4 pb-52 pt-6 md:px-6 md:pt-8">
          <div className={showResources ? WORKSPACE_RESOURCE_GRID_CLASS : ''}>
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

              {runId && runQuery.isLoading ? (
                <section role="status" className="mt-6 rounded-[14px] bg-surface-1 px-5 py-8 text-center text-sm text-slate-400 shadow-card">
                  正在恢复 Agent Run…
                </section>
              ) : null}
              {runQuery.isError ? (
                <p role="alert" className="mt-6 rounded-[12px] bg-rose/10 px-4 py-3 text-sm text-rose">
                  {workspaceErrorMessage(runQuery.error)}
                </p>
              ) : null}
              {isResearchV2 && researchQuery.isLoading ? (
                <section role="status" className="mt-6 rounded-[14px] bg-surface-1 px-5 py-8 text-center text-sm text-slate-400 shadow-card">
                  正在恢复研究预览…
                </section>
              ) : null}
              {isResearchV2 && researchQuery.isError ? (
                <p role="alert" className="mt-6 rounded-[12px] bg-rose/10 px-4 py-3 text-sm text-rose">
                  {workspaceErrorMessage(researchQuery.error)}
                </p>
              ) : null}
              {isResearchV2 && researchQuery.data ? (
                <>
                  <ResearchPreview projection={researchQuery.data} />
                  <ResearchExecution
                    projection={researchQuery.data}
                    pendingAction={researchPendingAction}
                    executionEnabled={currentRun?.orchestration_mode === 'execute' && orchestrationMode === 'execute'}
                    error={researchError}
                    onConfirmPlan={(planVersionId, stateVersion) => {
                      researchMutations.confirm.mutate({ planVersionId, stateVersion })
                    }}
                    onExecute={(stateVersion) => researchMutations.execute.mutate({ stateVersion })}
                    onResolveTool={(itemId, callId, action) => {
                      researchMutations.resolveTool.mutate({ itemId, callId, action })
                    }}
                    onRecover={(invocationId, stateVersion, action) => {
                      researchMutations.recover.mutate({ invocationId, stateVersion, action })
                    }}
                    onCancel={cancelCurrentRun}
                  />
                </>
              ) : null}
              {isResearchV3 && currentRun ? (
                <ResearchWorkbenchContainer scope={scope} run={currentRun} />
              ) : null}
              {!isResearchRun && currentRun?.plan_id && planQuery.isLoading ? (
                <section role="status" className="mt-6 rounded-[14px] bg-surface-1 px-5 py-8 text-center text-sm text-slate-400 shadow-card">
                  正在加载 Skill Plan…
                </section>
              ) : null}
              {!isResearchRun && planQuery.isError ? (
                <p role="alert" className="mt-6 rounded-[12px] bg-rose/10 px-4 py-3 text-sm text-rose">
                  {workspaceErrorMessage(planQuery.error)}
                </p>
              ) : null}
              {currentRun && currentRun.orchestration_version === 'v1' && !currentRun.plan_id ? (
                <section aria-label="单 Skill 运行状态" className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-[14px] bg-surface-1 px-5 py-4 shadow-card">
                  <div>
                    <p className="text-xs font-semibold text-mint-300">{currentRun.skill_name ? `$${currentRun.skill_name}` : 'Agent Runtime v2'}</p>
                    <p className="mt-1 text-sm text-slate-300">状态：{currentRun.status}</p>
                    {currentRun.error_code ? <p className="mt-1 text-xs text-rose">{currentRun.error_code}</p> : null}
                  </div>
                  <div className="flex gap-2">
                    {runIsActive ? <Button variant="danger" size="sm" loading={cancelRun.isPending} onClick={cancelCurrentRun}>取消</Button> : null}
                    {canRetryRun ? <Button variant="secondary" size="sm" loading={retryRun.isPending} onClick={retryCurrentRun}>重试</Button> : null}
                  </div>
                </section>
              ) : null}
              {!isResearchRun && currentRun?.status === 'waiting_plan_approval' && planDetail ? (
                <SkillPlanPreview
                  key={`${planDetail.plan.id}-${planDetail.plan.version}`}
                  detail={planDetail}
                  candidates={skills.data?.items ?? []}
                  orchestrationMode={currentRun.orchestration_mode === 'preview' ? 'preview' : 'execute'}
                  pendingAction={planPendingAction}
                  error={planError}
                  onUpdate={(request) => planMutations.update.mutate(request)}
                  onApprove={(request) => planMutations.approve.mutate(request)}
                  onReject={(request) => planMutations.reject.mutate(request)}
                />
              ) : null}
              {!isResearchRun && currentRun?.plan_id && planDetail && currentRun.status !== 'waiting_plan_approval' ? (
                <SkillPlanProgress
                  run={currentRun}
                  detail={planDetail}
                  skillsById={skillsById}
                  cancelling={cancelRun.isPending}
                  onCancel={cancelCurrentRun}
                  onOpenToolApproval={() => navigate('/knowledge?tab=pending')}
                />
              ) : null}
              {!isResearchRun && currentRun && planDetail?.synthesis ? (
                <SkillSynthesisView
                  synthesis={planDetail.synthesis}
                  results={planDetail.results ?? []}
                  skillsById={skillsById}
                  partial={currentRun.status === 'partial'}
                  onOpenSource={openSkillSource}
                  onOpenArtifact={(artifactId) => window.open(`/api/artifacts/${encodeURIComponent(artifactId)}`, '_blank', 'noopener,noreferrer')}
                />
              ) : null}
              {!isResearchRun && currentRun?.plan_id && canRetryRun ? (
                <div className="mt-4 flex justify-end">
                  <Button variant="secondary" size="sm" loading={retryRun.isPending} onClick={retryCurrentRun}>
                    以新 Run 重试
                  </Button>
                </div>
              ) : null}
            </div>

            {showResources ? <aside className="space-y-4" aria-label="Workspace resources">
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
                  <button
                    type="submit"
                    disabled={!searchInput.trim()}
                    className="rounded-[9px] bg-mint-400 px-3 py-2 text-xs font-semibold text-[#06231c] disabled:opacity-40"
                  >
                    搜索
                  </button>
                </form>
                {searchQuery.isFetching ? <p className="mt-3 text-xs text-slate-500">正在搜索…</p> : null}
                {searchQuery.isError ? <p role="alert" className="mt-3 text-xs text-rose">{workspaceErrorMessage(searchQuery.error)}</p> : null}
                {searchQuery.data?.items.length === 0 ? <p className="mt-3 text-xs text-slate-500">没有可见结果。</p> : null}
                <div className="mt-3 space-y-2">
                  {searchQuery.data?.items.map((result) => (
                    <article
                      key={`${result.result_type}-${result.id}`}
                      data-testid="search-result"
                      className="rounded-[10px] border border-white/[0.06] bg-base p-3"
                    >
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
                        <p key={source.id ?? source.reference} className="mt-1 truncate text-[11px] text-slate-500">
                          来源：{source.title} · {source.source_type}
                        </p>
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
            </aside> : null}
          </div>
        </div>
      </div>

      <Composer
        value={draft}
        skills={skills.data?.items ?? []}
        sending={sendMessage.isPending || sendAgentRun.isPending}
        locked={runIsActive}
        hasResourceRail={showResources}
        scrollbarGutter={scrollbarGutter}
        sendState={pending?.status === 'sending' ? null : pending?.status ?? null}
        statusMessage={pending?.status === 'sending' ? null : sendError}
        toolLauncher={<ToolLauncherBar activeTool={activeTool} onOpen={setActiveTool} />}
        onChange={(value) => {
          setDraft(value)
          if (pending && ['retryable', 'failed', 'unknown'].includes(pending.status)) {
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
      <DetailPanel selection={selection} scope={scope} onClose={() => setSelection(null)} />
    </div>
  )
}
