import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BookMarked, CheckCircle2, FileText, RefreshCw } from 'lucide-react'

import { ConfirmKnowledgeModal } from '../components/knowledge/ConfirmKnowledgeModal'
import { KnowledgeCard } from '../components/knowledge/KnowledgeCard'
import { PendingKnowledgeCard } from '../components/knowledge/PendingKnowledgeCard'
import { ReuseSection } from '../components/knowledge/ReuseSection'
import { Button } from '../components/ui/Button'
import { PageHeader } from '../components/ui/PageHeader'
import { Tabs, type TabItem } from '../components/ui/Tabs'
import type { InboxItem, UserMemoryItem } from '../features/knowledge/api'
import {
  governanceErrorMessage,
  useDocumentQuery,
  useKnowledgeMutations,
  useKnowledgeQueries,
} from '../features/knowledge/queries'
import { useAuth } from '../features/auth/AuthProvider'

function userMemoryCard(item: UserMemoryItem, projectName: string, currentProjectId: string) {
  return {
    id: item.id ?? item.title,
    title: item.title,
    summary: item.summary,
    memoryType: item.memory_type,
    scope: '仅自己',
    project: item.project_id === currentProjectId ? projectName : item.project_id ?? '未关联项目',
    updated: item.updated_at,
    sources: item.sources,
  }
}

const KNOWLEDGE_TABS = ['pending', 'personal', 'candidates', 'shared', 'documents'] as const
type KnowledgeTab = (typeof KNOWLEDGE_TABS)[number]

function normalizeTab(value: string | null): KnowledgeTab {
  return KNOWLEDGE_TABS.includes(value as KnowledgeTab) ? (value as KnowledgeTab) : 'pending'
}

export function Knowledge() {
  const { user, bootstrap } = useAuth()
  const [params, setParams] = useSearchParams()
  const context = {
    userId: user?.id ?? '',
    workspaceId: user?.workspace_id ?? '',
    projectId: user?.default_project_id ?? '',
  }
  const projectName = bootstrap?.project.name ?? context.projectId
  const queries = useKnowledgeQueries(context)
  const mutations = useKnowledgeMutations()
  const tab = normalizeTab(params.get('tab'))
  const setTab = (nextTab: string) => {
    const next = new URLSearchParams(params)
    if (nextTab === 'pending') next.delete('tab')
    else next.set('tab', nextTab)
    setParams(next, { replace: true })
  }
  const [selectedBrief, setSelectedBrief] = useState<InboxItem | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const documentId = selectedBrief?.metadata?.document_id ?? null
  const documentQuery = useDocumentQuery(context, documentId)

  const inboxItems = queries.inbox.data?.items ?? []
  const openInbox = inboxItems.filter((item) => item.status !== 'resolved')
  const memories = (queries.memory.data?.items ?? []).filter((item) => item.project_id === context.projectId)
  const candidates = memories.filter((item) => item.scope === 'team_candidate' && item.status === 'proposed')
  const shared = memories.filter((item) => item.scope === 'team_accepted')
  const personal = queries.overview.data?.sections.short ?? []
  const project = queries.overview.data?.sections.project ?? []
  const archive = queries.overview.data?.sections.archive ?? []
  const documents = queries.documents.data?.items ?? []

  const tabs: TabItem[] = [
    { key: 'pending', label: '待我确认', count: openInbox.length },
    { key: 'personal', label: '个人知识', count: personal.length + project.length + archive.length },
    { key: 'candidates', label: '团队候选', count: candidates.length },
    { key: 'shared', label: '已共享', count: shared.length },
    { key: 'documents', label: '文档', count: documents.length },
  ]
  const busy = Object.values(mutations).some((mutation) => mutation.isPending)
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

  const confirmBrief = async (text: string, expectedDocumentVersion: number) => {
    if (!selectedBrief) return
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

  return (
    <div className="space-y-6">
      <PageHeader title="我的知识" subtitle="Inbox、个人记忆、团队候选和文档均来自服务端 canonical state。" />
      <Tabs items={tabs} value={tab} onChange={setTab} />

      {queryError ? (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-[12px] border border-rose/25 bg-rose/10 p-4 text-sm text-rose">
          <span>{governanceErrorMessage(queryError)}</span>
          <Button variant="subtle" size="sm" icon={<RefreshCw className="h-4 w-4" />} onClick={() => void Promise.all(Object.values(queries).map((query) => query.refetch()))}>
            重试
          </Button>
        </div>
      ) : null}
      {error ? <p role="alert" className="rounded-[10px] border border-rose/25 bg-rose/10 px-4 py-3 text-sm text-rose">{error}</p> : null}
      {message ? <p role="status" className="rounded-[10px] border border-mint-400/20 bg-mint-400/[0.06] px-4 py-3 text-sm text-mint-300">{message}</p> : null}

      {tab === 'pending' ? (
        <section className="space-y-4" aria-label="待处理 Inbox">
          {openInbox.map((item) => (
            <PendingKnowledgeCard
              key={item.id}
              item={item}
              busy={busy}
              onConfirm={() => setSelectedBrief(item)}
              onSnooze={() => void run(() => mutations.updateInbox.mutateAsync({ itemId: item.id ?? '', status: 'snoozed' }), '已稍后处理，刷新后状态仍会保留。')}
              onResolve={() => void run(() => mutations.updateInbox.mutateAsync({ itemId: item.id ?? '', status: 'resolved' }), 'Inbox 项已解决。')}
              onInjection={(action) => void run(() => mutations.resolveInjection.mutateAsync({ itemId: item.id ?? '', action }), action === 'release' ? '隔离内容已释放并继续处理。' : '隔离内容已丢弃。')}
            />
          ))}
          {queries.inbox.isLoading ? <p className="text-sm text-slate-400">正在读取 Inbox…</p> : null}
          {!queries.inbox.isLoading && openInbox.length === 0 ? (
            <div className="card-base flex flex-col items-center py-12 text-center">
              <CheckCircle2 className="h-7 w-7 text-mint-300" />
              <h2 className="mt-3 text-base font-semibold text-white">暂无待处理事项</h2>
            </div>
          ) : null}
        </section>
      ) : null}

      {tab === 'personal' ? (
        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="个人知识">
          {[...personal, ...project, ...archive].map((item) => (
            <KnowledgeCard key={item.id} data={userMemoryCard(item, projectName, context.projectId)} />
          ))}
          {personal.length + project.length + archive.length === 0 ? <EmptyState text="暂无个人记忆。" /> : null}
        </section>
      ) : null}

      {tab === 'candidates' ? (
        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="团队候选">
          {candidates.map((item) => (
            <KnowledgeCard
              key={item.id}
              accent="knowledge"
              data={{
                id: item.id ?? item.title,
                title: item.title,
                summary: item.summary,
                memoryType: item.memory_type,
                scope: '待审核',
                project: item.project_id === context.projectId ? projectName : item.project_id ?? '未关联项目',
                updated: item.created_at,
                sources: item.sources,
              }}
              actions={item.allowed_actions.includes('accept') ? (
                <Button size="sm" loading={mutations.acceptMemory.isPending} onClick={() => void run(() => mutations.acceptMemory.mutateAsync(item.id ?? ''), '团队候选已接受并进入共享知识。')}>
                  接受候选
                </Button>
              ) : undefined}
            />
          ))}
          {candidates.length === 0 ? <EmptyState text="当前账号没有待审核的团队候选。" /> : null}
        </section>
      ) : null}

      {tab === 'shared' ? <ReuseSection items={shared} projectName={projectName} /> : null}

      {tab === 'documents' ? (
        <section className="grid grid-cols-1 gap-4 md:grid-cols-2" aria-label="文档">
          {documents.map((document) => (
            <article key={document.id} className="card-base p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-100"><FileText className="h-4 w-4 text-knowledge" />{document.title}</div>
              <p className="mt-2 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-slate-400">{document.text}</p>
              <p className="mt-3 text-xs text-slate-600">{document.file_name} · v{document.version}</p>
            </article>
          ))}
          {documents.length === 0 ? <EmptyState text="暂无可见文档。" /> : null}
        </section>
      ) : null}

      <div className="flex items-center gap-2 text-xs text-slate-600">
        <BookMarked className="h-3.5 w-3.5" />
        共享列表只展示当前项目中服务端返回的 team_accepted 记录，来源保留在卡片内。
      </div>

      <ConfirmKnowledgeModal
        open={selectedBrief !== null}
        item={selectedBrief}
        document={documentQuery.data?.item ?? null}
        loading={documentQuery.isLoading}
        onClose={() => setSelectedBrief(null)}
        onConfirm={confirmBrief}
      />
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return <div className="card-base col-span-full py-12 text-center text-sm text-slate-400">{text}</div>
}
