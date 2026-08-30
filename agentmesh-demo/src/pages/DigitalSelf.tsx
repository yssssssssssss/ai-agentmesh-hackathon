import { ApiError } from '../api/client'
import { MyImpact } from '../components/digital-self/MyImpact'
import { RecentGrowth } from '../components/digital-self/RecentGrowth'
import { TodayWork } from '../components/digital-self/TodayWork'
import { UnderstandingList } from '../components/digital-self/UnderstandingList'
import { WelcomeHero } from '../components/digital-self/WelcomeHero'
import { useAuth } from '../features/auth/AuthProvider'
import type { BootstrapState } from '../features/auth/api'
import {
  useDigitalSelfReadModel,
  type ActivityTodayResponse,
  type Agent,
  type MemoryOverviewResponse,
} from '../features/digital-self/api'
import {
  buildDigitalSelfViewModel,
  type DigitalSelfResource,
} from '../features/digital-self/presenter'

function resourceError(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  if (error instanceof Error) return error.message
  return '请求失败，请稍后重试'
}

function queryResource<T>(
  data: T | undefined,
  loading: boolean,
  error: unknown,
  isEmpty: (value: T) => boolean,
): DigitalSelfResource<T> {
  if (loading) return { state: 'loading' }
  if (error instanceof ApiError && (error.status === 404 || error.status === 501)) {
    return { state: 'unsupported' }
  }
  if (error) {
    return {
      state: error instanceof ApiError && error.status === 403 ? 'forbidden' : 'error',
      error: resourceError(error),
    }
  }
  if (data === undefined) return { state: 'empty' }
  if (isEmpty(data)) return { state: 'empty', data }
  return { state: 'available', data }
}

function DigitalSelfContent({
  bootstrap,
  userId,
  workspaceId,
  projectId,
}: {
  bootstrap: BootstrapState
  userId: string
  workspaceId: string
  projectId: string
}) {
  const readModel = useDigitalSelfReadModel({ userId, workspaceId, projectId })
  const agent = queryResource<Agent>(
    readModel.agent.data,
    readModel.agent.isLoading,
    readModel.agent.error,
    () => false,
  )
  const activity = queryResource<ActivityTodayResponse>(
    readModel.activity.data,
    readModel.activity.isLoading,
    readModel.activity.error,
    (value) => value.personal.length === 0 && value.external.length === 0,
  )
  const memory = queryResource<MemoryOverviewResponse>(
    readModel.memory.data,
    readModel.memory.isLoading,
    readModel.memory.error,
    (value) => Object.values(value.sections).every((section) => section.length === 0),
  )
  const viewModel = buildDigitalSelfViewModel({
    bootstrap: { state: 'available', data: bootstrap },
    agent,
    activity,
    memory,
  })

  return (
    <div className="space-y-5">
      <section>
        <WelcomeHero model={viewModel.hero} />
        <TodayWork model={viewModel.pending} />
      </section>

      <section className="border-t border-white/[0.08] pt-5" aria-labelledby="digital-self-activity-heading">
        <div className="mb-3">
          <h2 id="digital-self-activity-heading" className="text-[16px] font-semibold text-slate-100">数字员工动态</h2>
          <p className="mt-0.5 text-[12px] text-slate-400">近期形成的工作理解、成长与经验价值</p>
        </div>
        <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-3">
          <UnderstandingList model={viewModel.understanding} />
          <RecentGrowth model={viewModel.growth} />
          <MyImpact model={viewModel.impact} />
        </div>
      </section>
    </div>
  )
}

export function DigitalSelf() {
  const { user, bootstrap } = useAuth()
  const userId = user?.id
  const workspaceId = bootstrap?.workspace.id
  const projectId = bootstrap?.project.id

  if (!bootstrap || !userId || !workspaceId || !projectId) {
    return <p role="alert" className="card-base p-5 text-sm text-rose">当前工作空间上下文不完整，无法读取数字员工。</p>
  }

  return (
    <DigitalSelfContent
      bootstrap={bootstrap}
      userId={userId}
      workspaceId={workspaceId}
      projectId={projectId}
    />
  )
}
