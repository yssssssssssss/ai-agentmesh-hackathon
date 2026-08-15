import type { MemoryItem } from '../../features/knowledge/api'
import { KnowledgeCard } from './KnowledgeCard'

export function ReuseSection({ items, projectName }: { items: MemoryItem[]; projectName: string }) {
  if (items.length === 0) {
    return <div className="card-base py-12 text-center text-sm text-slate-400">暂无已共享的团队经验。</div>
  }
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {items.map((item) => (
        <KnowledgeCard
          key={item.id}
          accent="mint"
          data={{
            id: item.id ?? item.title,
            title: item.title,
            summary: item.summary,
            memoryType: item.memory_type,
            scope: '团队已接受',
            project: projectName,
            updated: item.created_at,
            sources: item.sources,
          }}
        />
      ))}
    </div>
  )
}
