import { BookMarked, Check, FileSearch, ShieldAlert, X } from 'lucide-react'

import type { CollaborationAuthorizationView } from '../../features/collaboration/presenter'
import { Avatar } from '../ui/Avatar'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { DataSourceBadge } from '../ui/DataSourceBadge'

interface HelpRequestCardProps {
  authorization: CollaborationAuthorizationView
  onDetail?: () => void
}

export function HelpRequestCard({ authorization, onDetail }: HelpRequestCardProps) {
  const actions = authorization.actions.value
  const metadata = authorization.metadata.value
  const requestedKnowledge = metadata.knowledge ?? metadata.question ?? authorization.title.value

  return (
    <article className="card-base flex min-h-[280px] flex-col p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <Avatar name={authorization.applicant.value} tone="collab" size="lg" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold text-white">{authorization.title.value}</h3>
              <DataSourceBadge source={authorization.title.source} />
            </div>
            <p className="mt-1 text-sm text-slate-400">申请人：{authorization.applicant.value}</p>
          </div>
        </div>
        <Badge tone="remind" dot>等待授权</Badge>
      </div>

      <div className="mt-4 space-y-3 rounded-soft bg-surface-2 p-4">
        <div className="flex gap-2.5">
          <BookMarked className="mt-0.5 h-4 w-4 shrink-0 text-knowledge" />
          <div className="min-w-0 text-sm">
            <div className="text-slate-400">申请引用</div>
            <div className="mt-1 font-medium text-slate-100">{requestedKnowledge}</div>
          </div>
        </div>
        <div className="text-sm leading-relaxed">
          <span className="text-slate-400">使用场景：</span>
          <span className="text-slate-300">{authorization.summary.value}</span>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
          <span>范围：{authorization.scope.value}</span>
          <span>项目：{authorization.projectId.value ?? '未绑定项目'}</span>
        </div>
      </div>

      <div className="mt-3 flex items-start gap-2.5 rounded-soft border border-remind/20 bg-remind/[0.05] px-3.5 py-2.5">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-remind" />
        <p className="text-xs leading-relaxed text-remind">
          服务端返回了授权意图，但当前前端没有对应的专用 approve / deny 命令，操作不会在本地模拟成功。
        </p>
      </div>

      <div className="mt-auto pt-4">
        <div className="flex flex-wrap items-center gap-2.5 border-t border-white/[0.06] pt-4">
          {actions.includes('approve') ? (
            <Button disabled icon={<Check className="h-4 w-4" />} title="当前没有专用授权接口">
              允许暂不可用
            </Button>
          ) : null}
          {actions.includes('deny') ? (
            <Button disabled variant="secondary" icon={<X className="h-4 w-4" />} title="当前没有专用驳回接口">
              驳回暂不可用
            </Button>
          ) : null}
          {actions.length === 0 ? <Badge tone="neutral">服务端未提供授权命令</Badge> : null}
          {authorization.taskId.value && onDetail ? (
            <Button variant="ghost" icon={<FileSearch className="h-4 w-4" />} onClick={onDetail}>
              查看关联协作
            </Button>
          ) : null}
        </div>

        <details className="mt-3 rounded-soft border border-white/[0.06] bg-surface-2/70 px-3 py-2 text-xs">
          <summary className="min-h-8 cursor-pointer py-1.5 text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50">技术详情</summary>
          <div className="mt-2 border-t border-white/[0.06] pt-3">
            <DataSourceBadge source={authorization.metadata.source} />
            <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-5 text-slate-400">{JSON.stringify({
              id: authorization.id.value,
              status: authorization.status.value,
              taskId: authorization.taskId.value,
              allowedActions: authorization.actions.value,
              metadata,
            }, null, 2)}</pre>
          </div>
        </details>
      </div>
    </article>
  )
}
