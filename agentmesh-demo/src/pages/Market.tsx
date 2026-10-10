import { useState } from 'react'
import { Power, PowerOff, RadioTower, RefreshCw } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '../components/ui/Button'
import { PageHeader } from '../components/ui/PageHeader'
import { useAuth } from '../features/auth/AuthProvider'
import { useMarketMe, useMarketActivity, marketKeys } from '../features/market/api/useMarketMe'
import { collaborationApi } from '../features/collaboration/api'
import { collaborationErrorMessage } from '../features/collaboration/queries'
import { PresenceTiles } from '../features/market/components/PresenceTiles'
import { GraphCanvas } from '../features/market/components/graph/GraphCanvas'
import { ExchangeTabs } from '../features/market/components/ExchangeTabs'
import { ActivityFeed } from '../features/market/components/ActivityFeed'

export function Market() {
  const { user } = useAuth()
  const context = {
    userId: user?.id ?? '', workspaceId: user?.workspace_id ?? '', projectId: user?.default_project_id ?? '',
  }
  const query = useMarketMe(context)
  const data = query.data
  const activityQuery = useMarketActivity(context)

  const queryClient = useQueryClient()
  const participationKey = ['market', 'participation', context.userId, context.workspaceId]
  const participation = useQuery({
    queryKey: participationKey,
    queryFn: collaborationApi.participation,
    enabled: !!context.userId,
  })
  const [participationError, setParticipationError] = useState<string | null>(null)
  const toggle = useMutation({
    mutationFn: collaborationApi.setParticipation,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: participationKey })
      void queryClient.invalidateQueries({ queryKey: marketKeys.me(context) })
      void queryClient.invalidateQueries({ queryKey: marketKeys.activity(context) })
    },
  })
  const joined = participation.data?.enabled ?? false

  const onToggle = async () => {
    setParticipationError(null)
    try {
      await toggle.mutateAsync(!joined)
    } catch (error) {
      setParticipationError(collaborationErrorMessage(error))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="协作市场"
        subtitle="加入后会用本人普通文本记忆和当前项目任务标题发布协作摘要；高敏材料不参与。"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant={joined ? 'secondary' : 'primary'}
              size="sm"
              icon={joined ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
              onClick={() => void onToggle()}
              loading={toggle.isPending}
              disabled={participation.isLoading}
            >
              {joined ? '暂停我的分身' : '让分身参与'}
            </Button>
            <Button
              variant="subtle"
              size="sm"
              icon={<RefreshCw className="h-4 w-4" />}
              onClick={() => void query.refetch()}
              loading={query.isFetching && !query.isLoading}
            >
              立即刷新
            </Button>
          </div>
        }
      />

      {participationError ? (
        <div role="alert" className="rounded-soft border border-rose/25 bg-rose/10 px-4 py-3 text-sm text-rose">
          {participationError}
        </div>
      ) : null}

      {query.isLoading ? (
        <div className="card-base py-16 text-center text-sm text-slate-400">正在读取市场数据…</div>
      ) : query.isError ? (
        <div role="alert" className="card-base py-16 text-center text-sm text-rose">
          <RadioTower className="mx-auto mb-3 h-6 w-6 opacity-60" />
          市场数据暂不可用，请稍后重试。
        </div>
      ) : data ? (
        <>
          <PresenceTiles presence={data.presence} enabled={data.enabled} workers={data.workers} />
          <p className="text-xs text-slate-400">当前项目的最近协作记录。关系图最多显示 200 位成员，关系与往来取最近 200 条匹配记录；顶部数量为当前可见范围的总计。</p>
          <div className="grid gap-6 lg:grid-cols-[1.7fr_1fr]">
            <GraphCanvas graph={data.graph} meId={data.user.id} />
            <ActivityFeed items={activityQuery.data?.items ?? []} live={data.enabled} />
          </div>
          <ExchangeTabs timeline={data.timeline} />
        </>
      ) : null}
    </div>
  )
}
