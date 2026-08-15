import { RadioTower, RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { PageHeader } from '../components/ui/PageHeader'
import { useAuth } from '../features/auth/AuthProvider'
import { useMarketMe } from '../features/market/api/useMarketMe'
import { PresenceTiles } from '../features/market/components/PresenceTiles'
import { GraphCanvas } from '../features/market/components/graph/GraphCanvas'
import { ExchangeTabs } from '../features/market/components/ExchangeTabs'

export function Market() {
  const { user } = useAuth()
  const context = { userId: user?.id ?? '', workspaceId: user?.workspace_id ?? '' }
  const query = useMarketMe(context)
  const data = query.data

  return (
    <div className="space-y-6">
      <PageHeader
        title="协作市场"
        subtitle="我的分身在市场里发出的求助、收到的回答，以及给别人的回应，一次呈现。"
        actions={
          <Button
            variant="subtle"
            size="sm"
            icon={<RefreshCw className="h-4 w-4" />}
            onClick={() => void query.refetch()}
            loading={query.isFetching && !query.isLoading}
          >
            立即刷新
          </Button>
        }
      />

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
          <GraphCanvas graph={data.graph} meId={data.user.id} />
          <ExchangeTabs timeline={data.timeline} />
        </>
      ) : null}
    </div>
  )
}
