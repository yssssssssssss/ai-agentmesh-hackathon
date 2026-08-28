import { Bot, CircleDot, Cpu } from 'lucide-react'

import type { Agent } from '../../features/digital-self/api'
import { Badge } from '../ui/Badge'
import { SectionCard } from '../ui/Card'

interface IdentityCardProps {
  agent?: Agent
  loading: boolean
  error: boolean
}

export function IdentityCard({ agent, loading, error }: IdentityCardProps) {
  const capabilities = agent?.capabilities ?? []
  return (
    <SectionCard title="当前数字人" icon={<Bot className="h-4 w-4" />} desc="身份与运行状态均来自服务端。">
      {loading ? <p className="text-sm text-slate-400">正在加载数字人…</p> : null}
      {error ? <p role="alert" className="text-sm text-rose">数字人资源暂时不可用。</p> : null}
      {!loading && !error && !agent ? <p className="text-sm text-slate-400">当前账号尚未绑定数字人。</p> : null}
      {agent ? (
        <div className="grid gap-4 md:grid-cols-[1.3fr_1fr]">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-white">{agent.name}</h2>
              <Badge tone={agent.status === 'online' ? 'mint' : 'neutral'} dot>{agent.status}</Badge>
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-400">{agent.description}</p>
            {capabilities.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {capabilities.map((capability) => <Badge key={capability}>{capability}</Badge>)}
              </div>
            ) : <p className="mt-3 text-xs text-slate-400">尚未声明能力。</p>}
          </div>
          <dl className="space-y-3 rounded-soft border border-white/[0.06] bg-surface-2 p-4 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="flex items-center gap-2 text-slate-400"><CircleDot className="h-4 w-4" />运行态</dt>
              <dd className="font-medium text-slate-200">{agent.runtime_status}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="flex items-center gap-2 text-slate-400"><Cpu className="h-4 w-4" />模型</dt>
              <dd className="font-medium text-slate-200">{agent.model_id ?? '未配置'}</dd>
            </div>
            <div>
              <dt className="text-slate-400">当前任务</dt>
              <dd className="mt-1 text-slate-200">{agent.current_task_title ?? '当前没有运行中的任务'}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </SectionCard>
  )
}
