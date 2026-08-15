import { IdentityCard } from '../components/digital-self/IdentityCard'
import { RecentGrowth } from '../components/digital-self/RecentGrowth'
import { TodayWork } from '../components/digital-self/TodayWork'
import { UnderstandingList } from '../components/digital-self/UnderstandingList'
import { WelcomeHero } from '../components/digital-self/WelcomeHero'
import { useAuth } from '../features/auth/AuthProvider'
import { useDigitalSelfReadModel } from '../features/digital-self/api'

function DigitalSelfContent({
  userId,
  workspaceId,
  projectId,
}: {
  userId: string
  workspaceId: string
  projectId: string
}) {
  const { user, bootstrap } = useAuth()
  const readModel = useDigitalSelfReadModel({ userId, workspaceId, projectId })
  if (!user || !bootstrap) return null

  return (
    <div className="space-y-6">
      <WelcomeHero user={user} project={bootstrap.project} workspace={bootstrap.workspace} />
      <IdentityCard
        agent={readModel.agent.data}
        loading={readModel.agent.isLoading}
        error={readModel.agent.isError}
      />
      <UnderstandingList />
      <div className="grid gap-6 xl:grid-cols-2">
        <TodayWork
          data={readModel.activity.data}
          loading={readModel.activity.isLoading}
          error={readModel.activity.isError}
        />
        <RecentGrowth
          data={readModel.memory.data}
          loading={readModel.memory.isLoading}
          error={readModel.memory.isError}
        />
      </div>
    </div>
  )
}

export function DigitalSelf() {
  const { user, bootstrap } = useAuth()
  if (!user?.id || !bootstrap?.workspace.id || !bootstrap.project.id) return null
  return (
    <DigitalSelfContent
      userId={user.id}
      workspaceId={bootstrap.workspace.id}
      projectId={bootstrap.project.id}
    />
  )
}
