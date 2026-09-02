import { useMemo, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, ArrowRightLeft, CheckCircle2, FolderKanban, Layers3, RefreshCw, UserRound, UsersRound } from 'lucide-react'

import { ApiError } from '../api/client'
import { AssetsPanel } from '../components/knowledge/AssetsPanel'
import { ConfirmKnowledgeModal } from '../components/knowledge/ConfirmKnowledgeModal'
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
import {
  buildKnowledgeViewModel,
  type KnowledgeAssetView,
  type KnowledgeResource,
  type PendingKnowledgeView,
} from '../features/knowledge/presenter'
import {
  governanceErrorMessage,
  useDocumentQuery,
  useKnowledgeMutations,
  useKnowledgeQueries,
} from '../features/knowledge/queries'

const KNOWLEDGE_TABS = ['assets', 'pending', 'shared'] as const
type KnowledgeTab = (typeof KNOWLEDGE_TABS)[number]
type PendingAction = 'confirm' | 'snooze' | 'resolve' | 'release' | 'discard' | 'accept'
type ToolApprovalAction = 'approve' | 'reject'

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
  const context = {
    userId: user?.id ?? '',
    workspaceId: user?.workspace_id ?? '',
    projectId: user?.default_project_id ?? '',
  }
  const projectName = bootstrap?.project.name ?? context.projectId
  const queries = useKnowledgeQueries(context)
  const mutations = useKnowledgeMutations()
  const [tab, setTabState] = useState<KnowledgeTab>(() => normalizeTab(searchParams.get('tab') ?? location.state?.tab))
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
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const selectedBrief = queries.inbox.data?.items.find((item) => item.id === selectedBriefId) ?? null
  const documentId = selectedBrief?.metadata?.document_id ?? null
  const documentQuery = useDocumentQuery(context, documentId)
  const busy = Object.values(mutations).some((mutation) => mutation.isPending)
  const pendingToolApproval = mutations.resolveToolApproval.isPending
    ? mutations.resolveToolApproval.variables
    : null
  const pendingReadOnly = viewModel.pending.loading || viewModel.pending.error !== null
  const documentReadOnly = documentQuery.isLoading || documentQuery.error !== null
  const queryError = queries.inbox.error ?? queries.memory.error ?? queries.overview.error ?? queries.documents.error

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
          <Button variant="subtle" size="sm" icon={<RefreshCw className="h-4 w-4" />} onClick={() => void Promise.all(Object.values(queries).map((query) => query.refetch()))}>重试</Button>
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
            onOpenTaskReview={(item) => {
              if (item.taskId.value) navigate(`/tasks?manage=${encodeURIComponent(item.taskId.value)}`)
            }}
            onOpenDetail={(item) => setDrawerTarget({ kind: 'pending', item })}
          />
        </ModuleState>
      ) : null}

      {tab === 'shared' ? (
        <ModuleState loading={viewModel.usage.loading} error={viewModel.usage.error} empty={viewModel.usage.data.items.length === 0} emptyText="暂无使用与反馈动态。">
          <ShareTimeline events={viewModel.usage.data.items} totalCount={viewModel.tabs[2].count} sources={viewModel.usage.sources} onOpenEvent={openUsage} />
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
      <KnowledgeDetailDrawer open={drawerTarget !== null} target={drawerTarget} busy={busy} readOnly={pendingReadOnly} onClose={() => setDrawerTarget(null)} onPendingAction={handlePendingAction} />
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
          actions={['转回项目范围', '更新团队版本']}
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
          <button
            key={action}
            type="button"
            disabled
            className="rounded-full border border-white/[0.06] bg-white/[0.03] px-2.5 py-1 text-[11px] text-slate-400"
            title="待接入服务端知识流转接口"
          >
            {action}
          </button>
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
