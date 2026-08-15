import { useState } from 'react'
import { Activity, CheckCircle2, Network, RadioTower, RefreshCw, Users } from 'lucide-react'

import { CollabTimelineDrawer } from '../components/collaboration/CollabTimelineDrawer'
import { MyCollabCard } from '../components/collaboration/MyCollabCard'
import { PeerCard } from '../components/collaboration/PeerCard'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { PageHeader } from '../components/ui/PageHeader'
import { StatTile } from '../components/ui/StatTile'
import { Tabs, type TabItem } from '../components/ui/Tabs'
import { useAuth } from '../features/auth/AuthProvider'
import type { TaskCard } from '../features/collaboration/api'
import {
  collaborationErrorMessage,
  useCollaborationMutations,
  useMarketQueries,
  useTaskCards,
} from '../features/collaboration/queries'

export function Collaboration() {
  const { user, bootstrap } = useAuth()
  const context = {
    userId: user?.id ?? '',
    workspaceId: user?.workspace_id ?? '',
    projectId: user?.default_project_id ?? '',
  }
  const [tab, setTab] = useState('active')
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const cardsQuery = useTaskCards(context)
  const market = useMarketQueries(context, tab === 'market')
  const mutations = useCollaborationMutations()
  const cards = cardsQuery.data?.items ?? []
  const mine = cards.filter((card) => card.initiated_by_current_user)
  const active = cards.filter((card) => card.task.status !== 'completed')
  const completed = cards.filter((card) => card.task.status === 'completed')
  const controlled = cards.filter((card) => card.allowed_actions.length > 1)
  const eligibleHandoffAgents = (bootstrap?.agents ?? []).filter((agent) => {
    if (agent.workspace_id !== context.workspaceId || agent.status !== 'online') return false
    if (!agent.owner_user_id) return agent.agent_type !== 'personal'
    const owner = bootstrap?.users.find((candidate) => candidate.id === agent.owner_user_id)
    const ownerId = owner?.id
    if (!ownerId || owner.status !== 'active' || owner.workspace_id !== context.workspaceId) return false
    return owner.default_project_id === context.projectId || (bootstrap?.project.member_ids ?? []).includes(ownerId)
  })

  const tabs: TabItem[] = [
    { key: 'active', label: '协作中', count: active.length },
    { key: 'mine', label: '我发起的', count: mine.length },
    { key: 'all', label: '全部任务', count: cards.length },
    { key: 'done', label: '已完成', count: completed.length },
    { key: 'market', label: '协作市场' },
  ]
  const displayCards: TaskCard[] = tab === 'mine' ? mine : tab === 'done' ? completed : tab === 'all' ? cards : active
  const marketError = market.status.error ?? market.board.error ?? market.participation.error

  const toggleParticipation = async () => {
    setError(null)
    setMessage(null)
    try {
      const next = !(market.participation.data?.enabled ?? false)
      await mutations.participation.mutateAsync(next)
      setMessage(next ? '已加入协作市场。' : '已退出协作市场。')
    } catch (actionError) {
      setError(collaborationErrorMessage(actionError))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="协作网络" subtitle="Task、Blackboard 时间线、执行锁、交接与市场参与均由服务端授权。" />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="可见任务" value={cards.length} icon={<Users className="h-4 w-4" />} tone="knowledge" />
        <StatTile label="协作进行中" value={active.length} icon={<Activity className="h-4 w-4" />} tone="mint" />
        <StatTile label="我发起的" value={mine.length} icon={<Network className="h-4 w-4" />} tone="collab" />
        <StatTile label="可控制任务" value={controlled.length} icon={<CheckCircle2 className="h-4 w-4" />} tone="remind" />
      </div>
      <Tabs items={tabs} value={tab} onChange={setTab} />

      {cardsQuery.error ? (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-[12px] border border-rose/25 bg-rose/10 p-4 text-sm text-rose">
          <span>{collaborationErrorMessage(cardsQuery.error)}</span>
          <Button size="sm" variant="subtle" icon={<RefreshCw className="h-4 w-4" />} onClick={() => void cardsQuery.refetch()}>重试</Button>
        </div>
      ) : null}
      {error ? <p role="alert" className="rounded-[10px] border border-rose/25 bg-rose/10 px-4 py-3 text-sm text-rose">{error}</p> : null}
      {message ? <p role="status" className="rounded-[10px] border border-mint-400/20 bg-mint-400/[0.06] px-4 py-3 text-sm text-mint-300">{message}</p> : null}

      {tab !== 'market' ? (
        <section className="grid grid-cols-1 gap-4 xl:grid-cols-2" aria-label="协作任务">
          {displayCards.map((card) => (
            <MyCollabCard key={card.task.id} card={card} onDetail={() => setSelectedTaskId(card.task.id ?? null)} />
          ))}
          {cardsQuery.isLoading ? <p className="text-sm text-slate-400">正在读取任务卡…</p> : null}
          {!cardsQuery.isLoading && displayCards.length === 0 ? <div className="card-base col-span-full py-12 text-center text-sm text-slate-400">当前分类暂无可见任务。</div> : null}
        </section>
      ) : (
        <section className="space-y-5" aria-label="协作市场">
          {marketError ? <p role="alert" className="text-sm text-rose">{collaborationErrorMessage(marketError)}</p> : null}
          <div className="card-base p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <RadioTower className="h-5 w-5 text-collab" />
                  <h2 className="text-base font-semibold text-white">{market.status.data?.enabled ? '市场运行中' : '市场已关闭'}</h2>
                  {market.polling ? <Badge tone="mint">30 秒轮询</Badge> : <Badge tone="neutral">轮询已暂停</Badge>}
                </div>
                <p className="mt-2 text-sm text-slate-400">仅在 Market 标签和文档同时可见时轮询。</p>
              </div>
              {market.participation.data ? (
                <Button loading={mutations.participation.isPending} variant={market.participation.data.enabled ? 'secondary' : 'primary'} onClick={() => void toggleParticipation()}>
                  {market.participation.data.enabled ? '退出市场' : '加入市场'}
                </Button>
              ) : null}
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <WorkerStatus label="发布 Worker" worker={market.status.data?.publish_worker} />
              <WorkerStatus label="发现 Worker" worker={market.status.data?.scout_worker} />
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {market.board.data?.signals.map((signal) => <PeerCard key={`${signal.owner_id}-${signal.created_at}`} signal={signal} />)}
            {market.board.data && market.board.data.signals.length === 0 ? <div className="card-base col-span-full py-12 text-center text-sm text-slate-400">暂无市场信号。</div> : null}
          </div>
        </section>
      )}

      <div className="flex items-center gap-2 text-xs text-slate-600"><Network className="h-3.5 w-3.5" />页面只渲染 task detail 返回的 allowed_actions。</div>
      <CollabTimelineDrawer
        open={selectedTaskId !== null}
        taskId={selectedTaskId}
        context={context}
        currentAgentId={user?.personal_agent_id ?? ''}
        agents={eligibleHandoffAgents}
        onClose={() => setSelectedTaskId(null)}
      />
    </div>
  )
}

function WorkerStatus({ label, worker }: { label: string; worker?: { enabled: boolean; running: boolean; last_error: string | null } }) {
  return (
    <div className="rounded-[10px] border border-white/[0.06] bg-surface-1 p-3">
      <div className="flex items-center justify-between gap-2"><span className="text-sm text-slate-200">{label}</span><Badge tone={worker?.running ? 'mint' : 'neutral'}>{worker?.running ? 'running' : worker?.enabled ? 'enabled' : 'disabled'}</Badge></div>
      <p className={`mt-2 text-xs ${worker?.last_error ? 'text-rose' : 'text-slate-500'}`}>{worker?.last_error ?? '无错误'}</p>
    </div>
  )
}
