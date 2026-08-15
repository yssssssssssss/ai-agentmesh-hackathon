import {
  ActivityPanel,
  AuditPanel,
  MemoryPanel,
  TaskCardsPanel,
} from '../components/insights/ReadModelPanels'
import { PageHeader } from '../components/ui/PageHeader'
import { useAuth } from '../features/auth/AuthProvider'
import { useInsightsReadModel } from '../features/insights/api'

function InsightsContent({ userId, workspaceId, projectId }: { userId: string; workspaceId: string; projectId: string }) {
  const { bootstrap } = useAuth()
  const readModel = useInsightsReadModel({ userId, workspaceId, projectId })
  if (!bootstrap) return null

  return (
    <div className="space-y-6">
      <PageHeader
        title="工作洞察"
        subtitle="仅汇总当前项目的任务、活动、记忆和审计记录，不生成本地判断。"
      />
      <section className="rounded-[16px] border border-white/[0.06] bg-surface-1 p-6">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mint-300">Current project</p>
        <h2 className="mt-2 text-xl font-semibold text-white">{bootstrap.project.name}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-400">{bootstrap.project.goal}</p>
        <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-500">
          <span className="rounded-full bg-white/[0.05] px-3 py-1">{bootstrap.project.status}</span>
          <span className="rounded-full bg-white/[0.05] px-3 py-1">项目 ID：{bootstrap.project.id}</span>
        </div>
      </section>
      <div className="grid gap-6 xl:grid-cols-2">
        <TaskCardsPanel data={readModel.tasks.data} loading={readModel.tasks.isLoading} error={readModel.tasks.isError} />
        <ActivityPanel data={readModel.activity.data} loading={readModel.activity.isLoading} error={readModel.activity.isError} />
        <MemoryPanel data={readModel.memory.data} loading={readModel.memory.isLoading} error={readModel.memory.isError} />
        <AuditPanel data={readModel.audit.data} loading={readModel.audit.isLoading} error={readModel.audit.isError} />
      </div>
    </div>
  )
}

export function Insights() {
  const { user, bootstrap } = useAuth()
  if (!user?.id || !bootstrap?.workspace.id || !bootstrap.project.id) return null
  return (
    <InsightsContent
      userId={user.id}
      workspaceId={bootstrap.workspace.id}
      projectId={bootstrap.project.id}
    />
  )
}
