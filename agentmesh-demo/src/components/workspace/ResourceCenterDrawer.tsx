import { FileText, Files, Search } from 'lucide-react'
import { useState } from 'react'

import { useSearchQuery, workspaceErrorMessage } from '../../features/workspace/queries'
import type {
  DocumentJob,
  DocumentJobStatus,
  ResourceSelection,
  WorkspaceScope,
} from '../../features/workspace/types'
import { cn } from '../../lib/cn'
import { Drawer } from '../ui/Drawer'

export const DOCUMENT_JOB_STATUS_LABEL: Record<DocumentJobStatus, string> = {
  queued: '排队中',
  running: '处理中',
  completed: '完成',
  failed: '失败',
}

const DOCUMENT_JOB_STATUS_CLASS: Record<DocumentJobStatus, string> = {
  queued: 'text-amber-200',
  running: 'text-amber-200',
  completed: 'text-mint-300',
  failed: 'text-rose',
}

interface ResourceCenterDrawerProps {
  open: boolean
  scope: WorkspaceScope
  jobs: DocumentJob[]
  onClose: () => void
  onSelect: (selection: ResourceSelection) => void
}

export function ResourceCenterDrawer({
  open,
  scope,
  jobs,
  onClose,
  onSelect,
}: ResourceCenterDrawerProps) {
  const [searchInput, setSearchInput] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const searchQuery = useSearchQuery(scope, submittedSearch)

  const selectResource = (selection: ResourceSelection) => {
    onClose()
    onSelect(selection)
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="资料中心"
      subtitle="搜索工作区资料并查看文档导入状态"
      icon={<Files className="h-4 w-4" aria-hidden="true" />}
      width={420}
    >
      <div data-testid="resource-center" className="space-y-6">
        <section aria-labelledby="resource-search-heading">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-mint-300" aria-hidden="true" />
            <h3 id="resource-search-heading" className="text-sm font-semibold text-slate-200">搜索可见资料</h3>
          </div>
          <form
            className="mt-3 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              setSubmittedSearch(searchInput.trim())
            }}
          >
            <input
              aria-label="搜索资料"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              className="min-w-0 flex-1 rounded-soft border border-white/[0.08] bg-base px-3 py-2 text-xs text-slate-100 outline-none focus:border-mint-400/40"
              placeholder="输入关键词"
            />
            <button
              type="submit"
              disabled={!searchInput.trim()}
              className="rounded-soft bg-mint-400 px-3 py-2 text-xs font-semibold text-[#06231c] disabled:opacity-40"
            >
              搜索
            </button>
          </form>
          {searchQuery.isFetching ? <p className="mt-3 text-xs text-slate-400">正在搜索…</p> : null}
          {searchQuery.isError ? <p role="alert" className="mt-3 text-xs text-rose">{workspaceErrorMessage(searchQuery.error)}</p> : null}
          {searchQuery.data?.items.length === 0 ? <p className="mt-3 text-xs text-slate-400">没有可见结果。</p> : null}
          <div className="mt-3 space-y-2">
            {searchQuery.data?.items.map((result) => (
              <article
                key={`${result.result_type}-${result.id}`}
                data-testid="search-result"
                className="rounded-soft border border-white/[0.06] bg-base p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs font-semibold text-slate-200">{result.title}</p>
                    <p className="mt-1 text-[11px] text-slate-400">{result.result_type} · {result.scope}</p>
                  </div>
                  {result.result_type === 'document' || result.sources?.[0] ? (
                    <button
                      type="button"
                      onClick={() => selectResource(
                        result.result_type === 'document'
                          ? { kind: 'document', id: result.id }
                          : { kind: 'source', source: result.sources![0] },
                      )}
                      className="shrink-0 text-[11px] font-semibold text-mint-300"
                    >
                      查看详情
                    </button>
                  ) : null}
                </div>
                <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-400">{result.summary}</p>
                {result.sources?.map((source) => (
                  <p key={source.id ?? source.reference} className="mt-1 truncate text-[11px] text-slate-400">
                    来源：{source.title} · {source.source_type}
                  </p>
                ))}
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="import-jobs-heading" className="border-t border-white/[0.06] pt-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-mint-300" aria-hidden="true" />
              <h3 id="import-jobs-heading" className="text-sm font-semibold text-slate-200">导入任务</h3>
            </div>
            <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] text-slate-400">{jobs.length}</span>
          </div>
          {jobs.length === 0 ? (
            <p className="mt-3 rounded-soft bg-base px-3 py-4 text-center text-xs text-slate-400">暂无导入任务</p>
          ) : (
            <div className="mt-3 space-y-2">
              {jobs.map((job) => {
                const progress = job.expected_chunks > 0
                  ? Math.min(100, Math.round((job.completed_chunks / job.expected_chunks) * 100))
                  : 0
                return (
                  <article key={job.id} data-testid="document-job" className="rounded-soft border border-white/[0.06] bg-base p-3 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-slate-300" title={job.file_name}>{job.file_name}</span>
                      <span className={cn('shrink-0 font-medium', DOCUMENT_JOB_STATUS_CLASS[job.status])}>
                        {DOCUMENT_JOB_STATUS_LABEL[job.status]}
                      </span>
                    </div>
                    <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
                      <div
                        className={cn('h-full rounded-full', job.status === 'failed' ? 'bg-rose' : 'bg-mint-400')}
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                    <p className="mt-1.5 text-slate-400">{job.completed_chunks}/{job.expected_chunks} chunks</p>
                    {job.status === 'failed' ? <p role="alert" className="mt-2 text-rose">{job.error ?? '导入失败'}</p> : null}
                  </article>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </Drawer>
  )
}
