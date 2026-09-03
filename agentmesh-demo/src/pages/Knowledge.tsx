import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, ArrowRightLeft, CheckCircle2, FolderKanban, Layers3, RefreshCw, UserRound, UsersRound } from 'lucide-react'

import { ApiError } from '../api/client'
import { AssetsPanel } from '../components/knowledge/AssetsPanel'
import { ConfirmKnowledgeModal } from '../components/knowledge/ConfirmKnowledgeModal'
import { GovernanceHistoryPanel } from '../components/knowledge/GovernanceHistoryPanel'
import {
  MemoryRevisionDialog,
  MemoryTransitionDialog,
  type MemoryTransitionTarget,
} from '../components/knowledge/MemoryGovernanceDialog'
import {
  KnowledgeDetailDrawer,
  type DrawerTarget,
} from '../components/knowledge/KnowledgeDetailDrawer'
import { PendingCandidatePanel } from '../components/knowledge/PendingCandidatePanel'
import { ShareTimeline } from '../components/knowledge/ShareTimeline'
import { Button } from '../components/ui/Button'
import { DataSourceBadge } from '../components/ui/DataSourceBadge'
import { PageHeader } from '../components/ui/PageHeader'
import { Tabs, type TabItem } from '../components/ui/Tabs'
import { useAuth } from '../features/auth/AuthProvider'
import type { MemoryGovernanceFilters, MemoryLifecycleAction } from '../features/knowledge/api'
import {
  buildKnowledgeViewModel,
  memoryEntryAsset,
  type KnowledgeAssetView,
  type KnowledgeResource,
  type PendingKnowledgeView,
} from '../features/knowledge/presenter'
import {
  governanceErrorMessage,
  useDocumentQuery,
  useGovernanceHistoryQuery,
  useKnowledgeMutations,
  useKnowledgeQueries,
  useMemoryLineageQuery,
} from '../features/knowledge/queries'

const KNOWLEDGE_TABS = ['assets', 'pending', 'governance', 'shared'] as const
const DEFAULT_GOVERNANCE_FILTERS: MemoryGovernanceFilters = {
  page: 1,
  pageSize: 25,
  status: 'all',
  scope: 'all',
  kind: 'all',
  layer: 'all',
}
type KnowledgeTab = (typeof KNOWLEDGE_TABS)[number]
type PendingAction = 'confirm' | 'snooze' | 'resolve' | 'release' | 'discard' | 'accept'
type ToolApprovalAction = 'approve' | 'reject'

const TRANSITION_SUCCESS: Record<MemoryLifecycleAction, string> = {
  dispute: '团队知识已标记为存在争议，并退出自动检索。',
  deprecate: '记忆版本已废弃。',
  expire: '记忆已标记为失效。',
  archive: '记忆已归档。',
  restore: '记忆已恢复到归档前状态。',
}

function normalizeTab(value: string | null | undefined): KnowledgeTab {
  return KNOWLEDGE_TABS.includes(value as KnowledgeTab) ? value as KnowledgeTab : 'assets'
}

interface QuerySnapshot<T> {
  data?: T
  isLoading: boolean
  error: unknown
}

export function queryResource<T>(query: QuerySnapshot<T>): KnowledgeResource<T> {
  if (query.error instanceof ApiError && query.error.status === 403) {
    return { state: 'forbidden', error: governanceErrorMessage(query.error) }
  }
  if (query.error) return { state: 'error', error: governanceErrorMessage(query.error) }
  if (query.isLoading) return { state: 'loading' }
  if (query.data !== undefined) return { state: 'available', data: query.data }
  return { state: 'empty' }
}

export function Knowledge() {
  const { user, bootstrap } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation() as { state?: { tab?: string } | null }
  const selectedProjectId = searchParams.get('project')?.trim() || user?.default_project_id || ''
  const context = {
    userId: user?.id ?? '',
    workspaceId: user?.workspace_id ?? '',
    projectId: selectedProjectId,
  }
  const projectName = bootstrap?.project.id === selectedProjectId
    ? bootstrap.project.name
    : selectedProjectId
  const [governanceFilters, setGovernanceFilters] = useState<MemoryGovernanceFilters>(
    DEFAULT_GOVERNANCE_FILTERS,
  )
  const queries = useKnowledgeQueries(context)
  const governanceQuery = useGovernanceHistoryQuery(context, governanceFilters)
  const mutations = useKnowledgeMutations()
  const [tab, setTabState] = useState<KnowledgeTab>(() => normalizeTab(searchParams.get('tab') ?? location.state?.tab))
  useEffect(() => {
    setGovernanceFilters((current) => ({ ...current, page: 1 }))
  }, [selectedProjectId])
  const setTab = (nextTab: string) => {
    const normalized = normalizeTab(nextTab)
    setTabState(normalized)
    const next = new URLSearchParams(searchParams)
    if (normalized === 'assets') next.delete('tab')
    else next.set('tab', normalized)
    setSearchParams(next, { replace: true })
  }

  const viewModel = useMemo(
    () => buildKnowledgeViewModel({
      projectId: context.projectId,
      projectName,
      inbox: queryResource(queries.inbox),
      memory: queryResource(queries.memory),
      governance: queryResource(governanceQuery),
      overview: queryResource(queries.overview),
      documents: queryResource(queries.documents),
      usage: { state: 'unsupported' },
    }),
    [
      context.projectId,
      projectName,
      queries.documents.data,
      queries.documents.error,
      queries.documents.isLoading,
      queries.inbox.data,
      queries.inbox.error,
      queries.inbox.isLoading,
      queries.memory.data,
      queries.memory.error,
      queries.memory.isLoading,
      governanceQuery.data,
      governanceQuery.error,
      governanceQuery.isLoading,
      queries.overview.data,
      queries.overview.error,
      queries.overview.isLoading,
    ],
  )
  const tabs: TabItem[] = viewModel.tabs.map((item) => ({
    key: item.key,
    label: item.label,
    count: item.count.value,
  }))

  const [selectedBriefId, setSelectedBriefId] = useState<string | null>(null)
  const [drawerTarget, setDrawerTarget] = useState<DrawerTarget | null>(null)
  const [revisionMemoryId, setRevisionMemoryId] = useState<string | null>(null)
  const [transitionTarget, setTransitionTarget] = useState<MemoryTransitionTarget | null>(null)
  const [governanceDialogError, setGovernanceDialogError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const memoryReviewCommands = useRef<Record<string, string>>({})
  const revisionCommands = useRef<Record<string, string>>({})
  const transitionCommands = useRef<Record<string, string>>({})
  const governedAssets = [...viewModel.assets.data.items, ...viewModel.governance.data.items]
  const revisionAsset = governedAssets.find((asset) => asset.id.value === revisionMemoryId) ?? null
  const latestTransitionVersion = transitionTarget === null
    ? null
    : governedAssets.find((asset) => asset.id.value === transitionTarget.id)?.version.value
      ?? viewModel.pending.data.items.find((item) => item.memoryId.value === transitionTarget.id)?.memoryVersion.value
      ?? transitionTarget.version
  const currentTransitionTarget = transitionTarget === null
    ? null
    : { ...transitionTarget, version: latestTransitionVersion ?? transitionTarget.version }
  const requestedMemoryId = searchParams.get('memory')?.trim() || null
  const drawerMemoryId = drawerTarget?.kind === 'asset' && drawerTarget.asset.memoryKind.value
    ? drawerTarget.asset.id.value
    : null
  const lineageQuery = useMemoryLineageQuery(context, requestedMemoryId ?? drawerMemoryId)
  const selectedBrief = queries.inbox.data?.items.find((item) => item.id === selectedBriefId) ?? null
  const documentId = selectedBrief?.metadata?.document_id ?? null
  const documentQuery = useDocumentQuery(context, documentId)
  const busy = Object.values(mutations).some((mutation) => mutation.isPending)
  const pendingToolApproval = mutations.resolveToolApproval.isPending
    ? mutations.resolveToolApproval.variables
    : null
  const pendingReadOnly = viewModel.pending.loading || viewModel.pending.error !== null
  const memoryReadOnly = viewModel.assets.loading || viewModel.governance.loading || queries.memory.error !== null
  const documentReadOnly = documentQuery.isLoading || documentQuery.error !== null
  const queryError = queries.inbox.error
    ?? queries.memory.error
    ?? governanceQuery.error
    ?? queries.overview.error
    ?? queries.documents.error

  useEffect(() => {
    const memoryId = requestedMemoryId
    if (!memoryId) return
    const asset = viewModel.assets.data.items.find((candidate) => candidate.id.value === memoryId)
    if (asset) {
      setDrawerTarget({ kind: 'asset', asset })
      return
    }
    const governance = viewModel.governance.data.items.find((candidate) => candidate.id.value === memoryId)
    if (governance) {
      setDrawerTarget({ kind: 'asset', asset: governance })
      return
    }
    const pending = viewModel.pending.data.items.find((candidate) => (
      candidate.kind === 'team_candidate' && candidate.id.value === memoryId
    ))
    if (pending) {
      setDrawerTarget({ kind: 'pending', item: pending })
      return
    }
    if (lineageQuery.data?.item.id === memoryId) {
      setDrawerTarget({
        kind: 'asset',
        asset: memoryEntryAsset(
          {
            ...lineageQuery.data.item,
            allowed_actions: lineageQuery.data.item.allowed_actions ?? [],
          },
          {
            projectId: context.projectId,
            projectName,
          },
        ),
      })
    }
  }, [
    context.projectId,
    lineageQuery.data,
    projectName,
    requestedMemoryId,
    viewModel.assets.data.items,
    viewModel.governance.data.items,
    viewModel.pending.data.items,
  ])

  const closeDrawer = () => {
    setDrawerTarget(null)
    const next = new URLSearchParams(searchParams)
    next.delete('memory')
    setSearchParams(next, { replace: true })
  }

  const run = async (action: () => Promise<unknown>, success: string) => {
    setError(null)
    setMessage(null)
    try {
      await action()
      setMessage(success)
    } catch (actionError) {
      setError(governanceErrorMessage(actionError))
    }
  }

  const openBrief = (item: PendingKnowledgeView) => {
    if (pendingReadOnly || !item.allowedActions.value.includes('confirm_brief')) return
    setDrawerTarget(null)
    setSelectedBriefId(item.id.value)
  }

  const confirmBrief = async (text: string, expectedDocumentVersion: number) => {
    if (!selectedBrief || pendingReadOnly || documentReadOnly) return
    setError(null)
    setMessage(null)
    try {
      await mutations.confirmBrief.mutateAsync({
        itemId: selectedBrief.id ?? '',
        text,
        expectedDocumentVersion,
      })
      setMessage('Brief 已确认，并进入团队候选记忆审核。')
    } catch (actionError) {
      setError(governanceErrorMessage(actionError))
      throw actionError
    }
  }

  const handlePendingAction = (item: PendingKnowledgeView, action: PendingAction) => {
    if (pendingReadOnly) return
    if (action === 'confirm') {
      openBrief(item)
      return
    }
    setDrawerTarget(null)
    if (action === 'accept') {
      void run(() => mutations.acceptMemory.mutateAsync(item.id.value), '团队候选已接受并进入共享知识。')
      return
    }
    if (action === 'snooze' || action === 'resolve') {
      const status = action === 'snooze' ? 'snoozed' : 'resolved'
      const success = action === 'snooze' ? '已稍后处理，服务端会保留该状态。' : 'Inbox 项已解决。'
      void run(() => mutations.updateInbox.mutateAsync({ itemId: item.id.value, status }), success)
      return
    }
    void run(
      () => mutations.resolveInjection.mutateAsync({ itemId: item.id.value, action }),
      action === 'release' ? '隔离内容已释放并继续处理。' : '隔离内容已丢弃。',
    )
  }

  const handleToolApproval = (item: PendingKnowledgeView, callId: string, action: ToolApprovalAction) => {
    if (pendingReadOnly || !item.allowedActions.value.includes(`${action}_tool`)) return
    setDrawerTarget(null)
    const actionLabel = action === 'approve' ? '批准' : '拒绝'
    void run(
      () => mutations.resolveToolApproval.mutateAsync({ itemId: item.id.value, callId, action }),
      `已${actionLabel}工具调用 ${callId}。`,
    )
  }

  const handleMemoryReview = (
    item: PendingKnowledgeView,
    decision: 'accepted' | 'rejected',
    note: string | null,
  ) => {
    const review = item.memoryReview.value
    const reviewId = review?.id
    const memoryVersion = item.memoryVersion.value
    if (!reviewId || memoryVersion === null || pendingReadOnly) return
    const key = `${reviewId}:${review.version}:${decision}:${note ?? ''}`
    const commandId = memoryReviewCommands.current[key]
      ?? `memory-review-${crypto.randomUUID()}`
    memoryReviewCommands.current[key] = commandId
    setDrawerTarget(null)
    void run(
      () => mutations.decideMemoryReview.mutateAsync({
        reviewId,
        commandId,
        expectedMemoryVersion: memoryVersion,
        expectedReviewVersion: review.version,
        decision,
        decisionNote: note,
      }).then((result) => {
        delete memoryReviewCommands.current[key]
        return result
      }),
      decision === 'accepted' ? '候选已接受为团队知识。' : '候选已拒绝并标记为争议。',
    )
  }

  const openRevision = (asset: KnowledgeAssetView) => {
    setGovernanceDialogError(null)
    closeDrawer()
    setRevisionMemoryId(asset.id.value)
  }

  const openTransition = (
    asset: KnowledgeAssetView,
    action: MemoryLifecycleAction,
  ) => {
    if (asset.version.value === null) return
    setGovernanceDialogError(null)
    closeDrawer()
    setTransitionTarget({
      id: asset.id.value,
      title: asset.title.value,
      version: asset.version.value,
      action,
    })
  }

  const submitMemoryRevision = async (values: {
    title: string
    summary: string
    memoryType: string
  }) => {
    if (!revisionAsset || revisionAsset.version.value === null) return
    const key = JSON.stringify({
      memoryId: revisionAsset.id.value,
      expectedVersion: revisionAsset.version.value,
      ...values,
    })
    const commandId = revisionCommands.current[key] ?? `memory-revision-${crypto.randomUUID()}`
    revisionCommands.current[key] = commandId
    setGovernanceDialogError(null)
    try {
      await mutations.createMemoryRevision.mutateAsync({
        memoryId: revisionAsset.id.value,
        payload: {
          command_id: commandId,
          expected_version: revisionAsset.version.value,
          title: values.title,
          summary: values.summary,
          memory_type: values.memoryType,
        },
      })
      delete revisionCommands.current[key]
      setRevisionMemoryId(null)
      setMessage('修订已提交为团队候选，等待独立审核。')
    } catch (actionError) {
      setGovernanceDialogError(governanceErrorMessage(actionError))
    }
  }

  const confirmMemoryTransition = async () => {
    if (!currentTransitionTarget) return
    const key = `${currentTransitionTarget.id}:${currentTransitionTarget.version}:${currentTransitionTarget.action}`
    const commandId = transitionCommands.current[key] ?? `memory-transition-${crypto.randomUUID()}`
    transitionCommands.current[key] = commandId
    setGovernanceDialogError(null)
    try {
      await mutations.transitionMemory.mutateAsync({
        memoryId: currentTransitionTarget.id,
        payload: {
          command_id: commandId,
          expected_version: currentTransitionTarget.version,
          action: currentTransitionTarget.action,
        },
      })
      delete transitionCommands.current[key]
      setTransitionTarget(null)
      setMessage(TRANSITION_SUCCESS[currentTransitionTarget.action])
    } catch (actionError) {
      setGovernanceDialogError(governanceErrorMessage(actionError))
    }
  }

  const openUsage = (event: (typeof viewModel.usage.data.items)[number]) => {
    const asset = viewModel.assets.data.items.find((item) => item.id.value === event.knowledgeId.value)
    setDrawerTarget({ kind: 'event', event, asset })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="我的知识"
        subtitle="经过确认并从真实工作中沉淀的经验，可被数字员工在后续项目中检索、引用和复用。"
      />
      <div className="flex flex-wrap items-center gap-3">
        <Tabs items={tabs} value={tab} onChange={setTab} />
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          当前计数来源 <DataSourceBadge source={viewModel.tabs.find((item) => item.key === tab)?.count.source ?? 'T'} />
        </div>
      </div>

      {queryError ? (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-soft border border-rose/25 bg-rose/10 p-4 text-sm text-rose">
          <span>{governanceErrorMessage(queryError)}</span>
          <Button
            variant="subtle"
            size="sm"
            icon={<RefreshCw className="h-4 w-4" />}
            onClick={() => void Promise.all([
              ...Object.values(queries).map((query) => query.refetch()),
              governanceQuery.refetch(),
            ])}
          >
            重试
          </Button>
        </div>
      ) : null}
      {error ? <p role="alert" className="rounded-soft border border-rose/25 bg-rose/10 px-4 py-3 text-sm text-rose">{error}</p> : null}
      {message ? <p role="status" className="rounded-soft border border-mint-400/20 bg-mint-400/[0.06] px-4 py-3 text-sm text-mint-300">{message}</p> : null}

      <KnowledgeArchitecturePanel assets={viewModel.assets.data.items} projectName={projectName} />

      {tab === 'assets' ? (
        <ModuleState loading={viewModel.assets.loading} error={viewModel.assets.error} empty={viewModel.assets.data.items.length === 0} emptyText="暂无已沉淀知识。">
          <AssetsPanel assets={viewModel.assets.data.items} totalCount={viewModel.tabs[0].count} onOpenAsset={(asset) => setDrawerTarget({ kind: 'asset', asset })} />
        </ModuleState>
      ) : null}

      {tab === 'pending' ? (
        <ModuleState loading={viewModel.pending.loading} error={viewModel.pending.error} empty={viewModel.pending.data.items.length === 0} emptyText="待确认知识已全部处理。">
          <PendingCandidatePanel
            items={viewModel.pending.data.items}
            busy={busy}
            pendingToolApproval={pendingToolApproval}
            readOnly={pendingReadOnly}
            onConfirm={openBrief}
            onSnooze={(item) => handlePendingAction(item, 'snooze')}
            onResolve={(item) => handlePendingAction(item, 'resolve')}
            onInjection={handlePendingAction}
            onToolApproval={handleToolApproval}
            onAccept={(item) => handlePendingAction(item, 'accept')}
            onMemoryReview={handleMemoryReview}
            onMemoryTransition={(item, action) => {
              if (!item.memoryId.value || item.memoryVersion.value === null) return
              setGovernanceDialogError(null)
              setDrawerTarget(null)
              setTransitionTarget({
                id: item.memoryId.value,
                title: item.title.value,
                version: item.memoryVersion.value,
                action,
              })
            }}
            onOpenTaskReview={(item) => {
              if (item.taskId.value) navigate(`/tasks?manage=${encodeURIComponent(item.taskId.value)}`)
            }}
            onOpenMemoryReview={(item) => {
              if (item.memoryId.value && item.projectId.value) {
                navigate(
                  `/knowledge?tab=pending&project=${encodeURIComponent(item.projectId.value)}&memory=${encodeURIComponent(item.memoryId.value)}`,
                )
              }
            }}
            onOpenDetail={(item) => setDrawerTarget({ kind: 'pending', item })}
          />
        </ModuleState>
      ) : null}

      {tab === 'governance' ? (
        <ModuleState
          loading={viewModel.governance.loading}
          error={viewModel.governance.error}
          empty={false}
          emptyText="暂无争议、废弃、失效或归档版本。"
        >
          <GovernanceHistoryPanel
            items={viewModel.governance.data.items}
            filters={governanceFilters}
            total={governanceQuery.data?.total ?? viewModel.governance.data.items.length}
            hasNext={governanceQuery.data?.has_next ?? false}
            onFiltersChange={setGovernanceFilters}
            onPageChange={(page) => setGovernanceFilters((current) => ({ ...current, page }))}
            onOpen={(asset) => setDrawerTarget({ kind: 'asset', asset })}
          />
        </ModuleState>
      ) : null}

      {tab === 'shared' ? (
        <ModuleState loading={viewModel.usage.loading} error={viewModel.usage.error} empty={viewModel.usage.data.items.length === 0} emptyText="暂无使用与反馈动态。">
          <ShareTimeline events={viewModel.usage.data.items} totalCount={viewModel.tabs[3].count} sources={viewModel.usage.sources} onOpenEvent={openUsage} />
        </ModuleState>
      ) : null}

      <ConfirmKnowledgeModal
        open={selectedBrief !== null}
        item={selectedBrief}
        document={documentQuery.data?.item ?? null}
        loading={documentQuery.isLoading}
        disabled={pendingReadOnly || documentReadOnly}
        onClose={() => setSelectedBriefId(null)}
        onConfirm={confirmBrief}
      />
      <KnowledgeDetailDrawer
        open={drawerTarget !== null}
        target={drawerTarget}
        busy={busy}
        readOnly={drawerTarget?.kind === 'pending' ? pendingReadOnly : memoryReadOnly}
        lineage={lineageQuery.data ?? null}
        lineageLoading={lineageQuery.isLoading}
        lineageError={lineageQuery.error ? governanceErrorMessage(lineageQuery.error) : null}
        onClose={closeDrawer}
        onPendingAction={handlePendingAction}
        onRevise={openRevision}
        onTransition={openTransition}
      />
      <MemoryRevisionDialog
        open={revisionAsset !== null}
        asset={revisionAsset}
        busy={mutations.createMemoryRevision.isPending}
        error={governanceDialogError}
        onClose={() => {
          setRevisionMemoryId(null)
          setGovernanceDialogError(null)
        }}
        onSubmit={(values) => void submitMemoryRevision(values)}
      />
      <MemoryTransitionDialog
        target={currentTransitionTarget}
        busy={mutations.transitionMemory.isPending}
        error={governanceDialogError}
        onClose={() => {
          setTransitionTarget(null)
          setGovernanceDialogError(null)
        }}
        onConfirm={() => void confirmMemoryTransition()}
      />
    </div>
  )
}

function ModuleState({ loading, error, empty, emptyText, children }: {
  loading: boolean
  error: string | null
  empty: boolean
  emptyText: string
  children: React.ReactNode
}) {
  if (loading && empty) return <div className="card-base py-12 text-center text-sm text-slate-400">正在读取知识数据…</div>
  if (error && empty) return <div role="alert" className="card-base py-12 text-center text-sm text-rose">{error}</div>
  if (empty) {
    return (
      <div className="card-base flex flex-col items-center py-14 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-mint-400/10 text-mint-300"><CheckCircle2 className="h-6 w-6" /></span>
        <h2 className="mt-3 text-sm font-semibold text-slate-100">{emptyText}</h2>
        <p className="mt-1 text-xs text-slate-400">新的服务端记录会在查询刷新后显示。</p>
      </div>
    )
  }
  return <>{children}</>
}

function KnowledgeArchitecturePanel({ assets, projectName }: {
  assets: KnowledgeAssetView[]
  projectName: string
}) {
  const personalCount = assets.filter((asset) => asset.visibility.value === 'private').length
  const projectCount = assets.filter((asset) => asset.visibility.value === 'project').length
  const teamCount = assets.filter((asset) => asset.visibility.value === 'team').length

  return (
    <section className="rounded-overlay border border-white/[0.06] bg-surface-1 p-5" aria-labelledby="knowledge-architecture-heading">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-soft bg-mint-400/[0.12] text-mint-300">
            <Layers3 className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <h2 id="knowledge-architecture-heading" className="text-[15px] font-semibold text-slate-100">知识层级与流转</h2>
            <p className="mt-1 max-w-3xl text-[12px] leading-5 text-slate-400">
              个人知识先由自己沉淀，确认后可进入当前项目；项目结论经过团队复核后进入团队知识库。项目知识和团队知识之间保留可回收、可再发布的流转路径。
            </p>
          </div>
        </div>
        <span className="rounded-full border border-white/[0.08] bg-base px-3 py-1 text-[11px] text-slate-400">
          当前项目：{projectName}
        </span>
      </div>

      <div className="mt-5 grid gap-3 lg:grid-cols-[1fr_auto_1fr_auto_1fr] lg:items-stretch">
        <KnowledgeLevelCard
          icon={<UserRound className="h-4 w-4" />}
          title="个人知识"
          desc="只有本人和个人数字员工默认可用"
          count={personalCount}
          actions={['升级为项目知识', '共享给团队']}
        />
        <FlowArrow label="确认后进入项目" />
        <KnowledgeLevelCard
          icon={<FolderKanban className="h-4 w-4" />}
          title="项目知识"
          desc="服务当前项目的复盘、规则和设计结论"
          count={projectCount}
          actions={['发布为团队知识', '收回到个人知识']}
        />
        <FlowArrow label="复核后团队共享" reversible />
        <KnowledgeLevelCard
          icon={<UsersRound className="h-4 w-4" />}
          title="团队知识"
          desc="团队成员和协作数字员工可按权限检索"
          count={teamCount}
          actions={['详情中提交修订', '按状态治理']}
        />
      </div>
    </section>
  )
}

function KnowledgeLevelCard({ icon, title, desc, count, actions }: {
  icon: React.ReactNode
  title: string
  desc: string
  count: number
  actions: string[]
}) {
  return (
    <article className="flex min-h-full flex-col rounded-soft border border-white/[0.06] bg-base p-4">
      <div className="flex items-center gap-2 text-mint-300">
        {icon}
        <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
      </div>
      <p className="mt-2 min-h-[40px] text-[12px] leading-5 text-slate-400">{desc}</p>
      <div className="mt-4 text-[11px] text-slate-400">
        已归档 <span className="text-xl font-semibold tabular-nums text-slate-100">{count}</span> 条
      </div>
      <div className="mt-auto flex flex-wrap gap-2 pt-4">
        {actions.map((action) => (
          <span
            key={action}
            className="rounded-full bg-white/[0.03] px-2.5 py-1 text-[11px] text-slate-400"
          >
            {action}
          </span>
        ))}
      </div>
    </article>
  )
}

function FlowArrow({ label, reversible = false }: {
  label: string
  reversible?: boolean
}) {
  const Icon = reversible ? ArrowRightLeft : ArrowRight
  return (
    <div className="flex items-center justify-center gap-2 text-[11px] text-slate-400 lg:flex-col">
      <Icon className="h-4 w-4 text-slate-400" aria-hidden="true" />
      <span className="whitespace-nowrap">{label}</span>
    </div>
  )
}
