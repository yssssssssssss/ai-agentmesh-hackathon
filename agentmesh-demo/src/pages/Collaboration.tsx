import { useState, type ReactNode } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Activity, Handshake, RadioTower, RefreshCw, Users } from 'lucide-react'

import { ApiError } from '../api/client'
import { CollabTimelineDrawer } from '../components/collaboration/CollabTimelineDrawer'
import { HelpRequestCard } from '../components/collaboration/HelpRequestCard'
import { MyCollabCard } from '../components/collaboration/MyCollabCard'
import { PeerCard } from '../components/collaboration/PeerCard'
import { Badge } from '../components/ui/Badge'
import { BarRow } from '../components/ui/BarRow'
import { Button } from '../components/ui/Button'
import { DataSourceBadge } from '../components/ui/DataSourceBadge'
import { PageHeader } from '../components/ui/PageHeader'
import { Tabs, type TabItem } from '../components/ui/Tabs'
import { useAuth } from '../features/auth/AuthProvider'
import { collaborationApi, type MarketWorkerState } from '../features/collaboration/api'
import {
  buildCollaborationViewModel,
  collaborationDetailTaskIds,
  type CollaborationResource,
} from '../features/collaboration/presenter'
import {
  collaborationErrorMessage,
  collaborationKeys,
  useCollaborationMutations,
  useMarketQueries,
  useTaskCards,
} from '../features/collaboration/queries'
import { knowledgeApi } from '../features/knowledge/api'
import { governanceErrorMessage, knowledgeKeys } from '../features/knowledge/queries'
import type { PresentedValue, PresentationState } from '../lib/presentation'

const CAPABILITY_TONES = ['mint', 'knowledge', 'collab', 'remind'] as const

function queryState(
  error: unknown,
  isLoading: boolean,
  hasData: boolean,
  isEmpty: boolean,
): PresentationState {
  if (error instanceof ApiError && error.status === 403) return 'forbidden'
  if (error) return 'error'
  if (isLoading && !hasData) return 'loading'
  if (!hasData || isEmpty) return 'empty'
  return 'available'
}

export function Collaboration() {
  const { user, bootstrap } = useAuth()
  const context = {
    userId: user?.id ?? '',
    workspaceId: user?.workspace_id ?? '',
    projectId: user?.default_project_id ?? '',
  }
  const [tab, setTab] = useState('all')
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [participationError, setParticipationError] = useState<string | null>(null)
  const [participationMessage, setParticipationMessage] = useState<string | null>(null)

  const cardsQuery = useTaskCards(context)
  const market = useMarketQueries(context, true)
  const inboxQuery = useQuery({
    queryKey: knowledgeKeys.inbox(context, true),
    queryFn: () => knowledgeApi.inbox(true),
  })
  const inboxItems = inboxQuery.data?.items
  const mutations = useCollaborationMutations(context)
  const taskIds = collaborationDetailTaskIds(
    cardsQuery.data?.items ?? [],
    inboxItems ?? [],
    context.projectId,
  )
  const detailQueries = useQueries({
    queries: taskIds.map((taskId) => ({
      queryKey: collaborationKeys.task(context, taskId),
      queryFn: () => collaborationApi.taskDetail(taskId),
    })),
  })

  const cardItems = cardsQuery.data?.items
  const cardsResource: CollaborationResource<NonNullable<typeof cardItems>> = {
    state: queryState(cardsQuery.error, cardsQuery.isLoading, cardItems !== undefined, cardItems?.length === 0),
    data: cardItems,
    error: cardsQuery.error ? collaborationErrorMessage(cardsQuery.error) : undefined,
  }
  const detailError = detailQueries.find((query) => query.error)?.error
  const detailItems = detailQueries.flatMap((query) => query.data ? [query.data] : [])
  const detailsState = cardsResource.state === 'forbidden' || cardsResource.state === 'error'
    ? cardsResource.state
    : queryState(
      detailError,
      detailQueries.some((query) => query.isLoading),
      taskIds.length === 0 || detailItems.length > 0,
      taskIds.length === 0,
    )
  const detailsResource: CollaborationResource<typeof detailItems> = {
    state: detailsState,
    data: detailItems,
    error: cardsResource.error ?? (detailError ? collaborationErrorMessage(detailError) : undefined),
  }
  const boardData = market.board.data
  const marketResource: CollaborationResource<NonNullable<typeof boardData>> = {
    state: queryState(market.board.error, market.board.isLoading, boardData !== undefined, false),
    data: boardData,
    error: market.board.error ? collaborationErrorMessage(market.board.error) : undefined,
  }
  const inboxResource: CollaborationResource<NonNullable<typeof inboxItems>> = {
    state: queryState(inboxQuery.error, inboxQuery.isLoading, inboxItems !== undefined, inboxItems?.length === 0),
    data: inboxItems,
    error: inboxQuery.error ? governanceErrorMessage(inboxQuery.error) : undefined,
  }
  const view = buildCollaborationViewModel({
    projectId: context.projectId,
    taskCards: cardsResource,
    taskDetails: detailsResource,
    marketBoard: marketResource,
    inbox: inboxResource,
  })

  const selectedRecord = view.records.data.find((record) => record.id.value === selectedTaskId)
  const selectedTimeline = view.timeline.data.filter((item) => item.taskId.value === selectedTaskId)
  const displayedRecords = tab === 'mine'
    ? view.records.data.filter((record) => record.initiatedByCurrentUser.value)
    : view.records.data
  const tabs: TabItem[] = view.tabs.data.map((item) => ({
    key: item.key,
    label: item.label,
    count: item.count.value,
  }))
  const eligibleHandoffAgents = (bootstrap?.agents ?? []).filter((agent) => {
    if (agent.workspace_id !== context.workspaceId || agent.status !== 'online') return false
    if (!agent.owner_user_id) return agent.agent_type !== 'personal'
    const owner = bootstrap?.users.find((candidate) => candidate.id === agent.owner_user_id)
    const ownerId = owner?.id
    if (!ownerId || owner.status !== 'active' || owner.workspace_id !== context.workspaceId) return false
    return owner.default_project_id === context.projectId || (bootstrap?.project.member_ids ?? []).includes(ownerId)
  })

  const toggleParticipation = async () => {
    setParticipationError(null)
    setParticipationMessage(null)
    try {
      const next = !(market.participation.data?.enabled ?? false)
      await mutations.participation.mutateAsync(next)
      setParticipationMessage(next ? '已加入协作市场。' : '已退出协作市场。')
    } catch (actionError) {
      setParticipationError(collaborationErrorMessage(actionError))
    }
  }

  const marketError = view.market.error
    ?? (market.status.error ? collaborationErrorMessage(market.status.error) : null)
    ?? (market.participation.error ? collaborationErrorMessage(market.participation.error) : null)

  return (
    <div className="space-y-6">
      <PageHeader
        title="协作网络"
        subtitle="数字员工按任务需要连接组织经验与能力；真实 Task、Blackboard、市场和授权状态均保留服务端来源。"
      />

      {view.overview.error ? (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-soft border border-rose/25 bg-rose/10 p-4 text-sm text-rose">
          <span>{view.overview.error}</span>
          <Button size="sm" variant="subtle" icon={<RefreshCw className="h-4 w-4" />} onClick={() => void Promise.all([cardsQuery.refetch(), market.board.refetch()])}>重试</Button>
        </div>
      ) : view.overview.loading ? (
        <div className="card-base p-6 text-sm text-slate-400">正在读取协作网络…</div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
          <section className="card-base p-6">
            <SectionHeading
              title="我的协作网络"
              desc="真实任务、市场参与和当前可用的周期参考。"
              action={<SourceLegend sources={view.overview.sources} />}
            />
            <div className="grid gap-5 sm:grid-cols-2">
              <NetworkMetric label="可见任务" value={view.overview.data.visibleTasks} desc="当前项目可见的服务端任务" icon={<Users className="h-4 w-4" />} />
              <NetworkMetric label="协作进行中" value={view.overview.data.activeTasks} desc="状态尚未完成的真实任务" icon={<Activity className="h-4 w-4" />} />
              <NetworkMetric label="市场参与者" value={view.overview.data.marketParticipants} desc="协作市场返回的参与者数量" icon={<RadioTower className="h-4 w-4" />} />
              <NetworkMetric label="获得经验支持" value={view.overview.data.receivedSupport} desc="后端暂无周期聚合，显示参考值" icon={<Handshake className="h-4 w-4" />} />
            </div>
            <div className="mt-5 grid grid-cols-3 gap-3 border-t border-white/[0.06] pt-4">
              {([
                ['全部参考', view.overview.data.periodAggregates.value.all],
                ['进行中', view.overview.data.periodAggregates.value.ongoing],
                ['已完成', view.overview.data.periodAggregates.value.completed],
              ] as const).map(([label, value]) => (
                <div key={label} className="rounded-soft bg-surface-2 px-3 py-2.5 text-center">
                  <div className="text-lg font-semibold tabular-nums text-white">{value}</div>
                  <div className="mt-1 text-[10.5px] text-slate-400">{label}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
              <DataSourceBadge source={view.overview.data.periodAggregates.source} />
              {view.overview.data.periodAggregates.reason}
            </div>
          </section>

          <section className="card-base p-6">
            <SectionHeading
              title="协作能力类型"
              desc="当前后端没有能力占比聚合，按现有参考能力等比分布。"
              action={<DataSourceBadge source={view.overview.data.capabilityPercentages.source} />}
            />
            <div className="mt-5 space-y-4">
              {view.overview.data.capabilityPercentages.value.map((capability, index) => (
                <BarRow
                  key={capability.label}
                  label={capability.label}
                  value={capability.percentage}
                  valueLabel={`${capability.percentage}%`}
                  tone={CAPABILITY_TONES[index % CAPABILITY_TONES.length]}
                />
              ))}
            </div>
            <p className="mt-5 text-xs leading-relaxed text-slate-400">{view.overview.data.capabilityPercentages.reason}</p>
          </section>
        </div>
      )}

      <section aria-labelledby="market-participants-title">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="market-participants-title" className="text-[16px] font-semibold text-slate-100">组织协作参与者</h2>
            <p className="mt-0.5 text-[12px] text-slate-400">展示市场供给、需求和匹配；匹配原因缺失时才使用 M 数据。</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SourceLegend sources={view.market.sources} />
            {market.participation.data ? (
              <Button
                size="sm"
                loading={mutations.participation.isPending}
                variant={market.participation.data.enabled ? 'secondary' : 'primary'}
                onClick={() => void toggleParticipation()}
              >
                {market.participation.data.enabled ? '退出市场' : '加入市场'}
              </Button>
            ) : null}
          </div>
        </div>

        {participationError ? <p role="alert" className="mb-3 rounded-soft border border-rose/25 bg-rose/10 px-4 py-3 text-sm text-rose">{participationError}</p> : null}
        {participationMessage ? <p role="status" className="mb-3 rounded-soft border border-mint-400/20 bg-mint-400/[0.06] px-4 py-3 text-sm text-mint-300">{participationMessage}</p> : null}
        {marketError ? (
          <div role="alert" className="flex items-center justify-between gap-3 rounded-soft border border-rose/25 bg-rose/10 p-4 text-sm text-rose">
            <span>{marketError}</span>
            <Button size="sm" variant="subtle" icon={<RefreshCw className="h-4 w-4" />} onClick={() => void Promise.all([market.status.refetch(), market.board.refetch(), market.participation.refetch()])}>重试</Button>
          </div>
        ) : view.market.loading ? (
          <div className="card-base p-6 text-sm text-slate-400">正在读取协作市场…</div>
        ) : (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              <MarketCount label="参与者" value={view.market.data.counts.value.participants} />
              <MarketCount label="供需信号" value={view.market.data.counts.value.signals} />
              <MarketCount label="完成匹配" value={view.market.data.counts.value.matches} />
              <MarketCount label="授权记录" value={view.market.data.counts.value.consent_grants} />
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {view.market.data.signals.value.map((signal) => (
                <PeerCard
                  key={`${signal.owner_id}-${signal.created_at}`}
                  signal={signal}
                  source={view.market.data.signals.source}
                  match={view.market.data.matches.value.find((match) => (
                    match.helper_id === signal.owner_id || match.needer_id === signal.owner_id
                  ))}
                />
              ))}
              {view.market.data.signals.value.length === 0 ? (
                <div className="card-base col-span-full py-12 text-center text-sm text-slate-400">当前没有可见市场参与者。</div>
              ) : null}
            </div>
            <details className="mt-4 rounded-soft border border-white/[0.06] bg-surface-1 px-4 py-3 text-xs">
              <summary className="min-h-8 cursor-pointer py-1.5 text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">市场运行技术状态</summary>
              <div className="mt-3 grid gap-3 border-t border-white/[0.06] pt-4 md:grid-cols-2">
                <WorkerStatus label="发布 Worker" worker={view.market.data.publishWorker.value} />
                <WorkerStatus label="发现 Worker" worker={view.market.data.scoutWorker.value} />
              </div>
            </details>
          </>
        )}
      </section>

      <section aria-labelledby="collaboration-records-title">
        <SectionHeading
          title="协作明细"
          desc="查看自动完成的协作、我的申请和涉及个人知识的授权记录。"
          action={<SourceLegend sources={view.tabs.sources} />}
          id="collaboration-records-title"
        />
        <Tabs items={tabs} value={tab} onChange={setTab} />

        <div className="mt-4" role="tabpanel">
          {tab === 'authorization' ? (
            view.authorizations.error ? (
              <div role="alert" className="rounded-soft border border-rose/25 bg-rose/10 p-4 text-sm text-rose">{view.authorizations.error}</div>
            ) : view.authorizations.loading ? (
              <div className="card-base p-6 text-sm text-slate-400">正在读取授权记录…</div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {view.authorizations.data.map((authorization) => (
                  <HelpRequestCard
                    key={authorization.id.value}
                    authorization={authorization}
                    onDetail={authorization.taskId.value ? () => setSelectedTaskId(authorization.taskId.value) : undefined}
                  />
                ))}
                {view.authorizations.data.length === 0 ? (
                  <div className="card-base col-span-full py-12 text-center text-sm text-slate-400">当前没有待授权请求。</div>
                ) : null}
              </div>
            )
          ) : view.records.error ? (
            <div role="alert" className="flex items-center justify-between gap-3 rounded-soft border border-rose/25 bg-rose/10 p-4 text-sm text-rose">
              <span>{view.records.error}</span>
              <Button size="sm" variant="subtle" icon={<RefreshCw className="h-4 w-4" />} onClick={() => void cardsQuery.refetch()}>重试</Button>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {displayedRecords.map((record) => (
                <MyCollabCard key={record.id.value} record={record} onDetail={() => setSelectedTaskId(record.id.value)} />
              ))}
              {!view.records.loading && displayedRecords.length === 0 ? (
                <div className="card-base col-span-full py-12 text-center text-sm text-slate-400">当前分类暂无可见任务。</div>
              ) : null}
              {view.records.loading ? <div className="card-base col-span-full p-6 text-sm text-slate-400">正在补全任务参与者与协作记录…</div> : null}
            </div>
          )}
        </div>
      </section>

      <CollabTimelineDrawer
        open={selectedTaskId !== null}
        taskId={selectedTaskId}
        context={context}
        currentAgentId={user?.personal_agent_id ?? ''}
        agents={eligibleHandoffAgents}
        record={selectedRecord}
        timeline={selectedTimeline}
        onClose={() => setSelectedTaskId(null)}
      />
    </div>
  )
}

function SectionHeading({ title, desc, action, id }: { title: string; desc: string; action?: ReactNode; id?: string }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id={id} className="text-[16px] font-semibold text-slate-100">{title}</h2>
        <p className="mt-0.5 text-[12px] text-slate-400">{desc}</p>
      </div>
      {action}
    </div>
  )
}

function SourceLegend({ sources }: { sources: Array<'M' | 'T'> }) {
  return <div className="flex items-center gap-2">{sources.map((source) => <DataSourceBadge key={source} source={source} />)}</div>
}

function NetworkMetric({
  label,
  value,
  desc,
  icon,
}: {
  label: string
  value: PresentedValue<number>
  desc: string
  icon: ReactNode
}) {
  return (
    <div className="border-b border-white/[0.06] pb-4 sm:border-0 sm:pb-0">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[12px] text-slate-400">{label}</div>
          <p className="mt-0.5 text-[10.5px] leading-relaxed text-slate-400">{desc}</p>
        </div>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.04] text-slate-400">{icon}</span>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className="text-[22px] font-semibold tabular-nums text-white">{value.value}</span>
        <DataSourceBadge source={value.source} />
      </div>
    </div>
  )
}

function MarketCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-soft border border-white/[0.06] bg-surface-1 px-4 py-3">
      <div className="text-xl font-semibold tabular-nums text-white">{value}</div>
      <div className="mt-1 text-xs text-slate-400">{label}</div>
    </div>
  )
}

function WorkerStatus({
  label,
  worker,
}: {
  label: string
  worker: MarketWorkerState
}) {
  return (
    <div className="rounded-soft bg-surface-2 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-slate-200">{label}</span>
        <Badge tone={worker.running ? 'mint' : 'neutral'}>{worker.running ? 'running' : worker.enabled ? 'enabled' : 'disabled'}</Badge>
      </div>
      <p className={`mt-2 text-xs ${worker.last_error ? 'text-rose' : 'text-slate-400'}`}>{worker.last_error ?? '无错误'}</p>
      <p className="mt-1 text-[11px] text-slate-400">最近运行：{worker.last_run_at ? new Date(worker.last_run_at).toLocaleString('zh-CN') : '暂无'}</p>
    </div>
  )
}
