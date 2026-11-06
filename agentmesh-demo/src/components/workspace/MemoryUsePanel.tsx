import { BookOpenCheck, ExternalLink, Quote } from 'lucide-react'

import type { MemoryUseView } from '../../features/workspace/types'
import type { components } from '../../api/generated/schema'
import { Badge } from '../ui/Badge'

export function MemoryUsePanel({ items, requests = [], candidates = [] }: {
  items: MemoryUseView[]
  requests?: components['schemas']['ContextRequestMeasurementV1'][]
  candidates?: components['schemas']['MemoryContextCandidateViewV1'][]
}) {
  const latest = requests[requests.length - 1]
  if (items.length === 0 && !latest && candidates.length === 0) return null
  return (
    <section
      aria-labelledby="run-memory-context-heading"
      className="mt-6 rounded-soft border border-white/[0.06] bg-surface-1 px-5 py-4 shadow-card"
    >
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-soft bg-mint-400/10 text-mint-300">
          <BookOpenCheck className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 id="run-memory-context-heading" className="text-sm font-semibold text-slate-100">{items.length ? '本次使用的记忆' : '上下文检查'}</h2>
          <p className="mt-1 text-xs leading-5 text-slate-400">记忆回执记录通过安全、授权和预算检查后的模型交付版本。</p>
        </div>
      </div>
      {candidates.length ? <div className="mt-3" aria-label="记忆候选选择">
        <p className="text-xs leading-5 text-slate-400">检索候选 {candidates.length} 条；待使用仅表示已准备，实际使用以交付回执为准。</p>
        <ul className="mt-2 space-y-2">
          {candidates.map((view) => (
            <li key={`${view.candidate.memory_record_type}:${view.candidate.memory_id}:${view.candidate.memory_version}:${view.candidate.memory_hash}`} className="text-xs leading-5">
              <Badge tone={view.state === 'delivered' ? 'mint' : 'neutral'}>{CANDIDATE_STATES[view.state]}</Badge>
              <span className="ml-2 text-slate-300">{view.title ?? view.candidate.memory_id} · v{view.candidate.memory_version}</span>
              <p className="mt-1 text-slate-400">{view.state === 'delivered' && !view.current_available
                ? '此版本曾交付；当前权限、版本或来源已失效。'
                : CANDIDATE_EXPLANATIONS[view.state]}</p>
            </li>
          ))}
        </ul>
      </div> : null}
      {latest ? <div className="mt-3 text-xs leading-5 text-slate-400" aria-label="上下文请求预算">
        <Badge tone={latest.decision === 'allowed' ? 'mint' : 'neutral'}>
          {latest.decision === 'allowed' ? '请求预算已通过' : '请求预算超限，未交付'}
        </Badge>
        <p className="mt-1">完整请求 {latest.total_chars.toLocaleString()} 字符 · 保守估算 {latest.estimated_input_tokens.toLocaleString()} Token · 输出上限 {latest.output_token_cap.toLocaleString()}</p>
        <p>包含指令、会话和工具内容。估算使用 UTF-8 字节与协议预留，并非 Provider 实测用量。</p>
        {latest.decision === 'withheld' ? <p className="text-amber-300">请缩小资料范围或新建会话后重试。</p> : null}
      </div> : null}
      <ol className="mt-4 divide-y divide-white/[0.06]">
        {items.map((item) => (
          <li key={item.receipt.id} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs font-semibold text-mint-300">[{item.receipt.citation_label}]</span>
                <span className="text-sm font-medium text-slate-100">{item.title ?? item.receipt.memory_id}</span>
                <Badge tone={item.cited_in_output ? 'mint' : 'neutral'}>
                  {item.cited_in_output ? '输出已引用' : '已进入上下文'}
                </Badge>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                v{item.receipt.memory_version} · {SCOPE_LABELS[item.scope ?? ''] ?? item.scope ?? '当前不可见'} · {LAYER_LABELS[item.layer ?? ''] ?? item.layer ?? '未标注层级'}
              </p>
              {item.sources.length > 0 ? (
                <p className="mt-1 flex items-center gap-1 text-[11px] text-slate-400">
                  <Quote className="h-3 w-3" aria-hidden="true" />
                  原始来源：{item.sources.map((source) => source.title).join('、')}
                </p>
              ) : null}
            </div>
            {item.memory_navigation_href ? (
              <a
                href={item.memory_navigation_href}
                className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-control px-3 text-xs text-mint-300 transition-colors active:scale-[0.98] hover:bg-white/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-mint-400/50"
              >
                查看记忆 <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              </a>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  )
}

const CANDIDATE_STATES = {
  prepared: '待使用', withheld: '暂不可用', quarantined: '安全隔离', budget_dropped: '超出预算', delivered: '已使用',
}

const CANDIDATE_EXPLANATIONS = {
  prepared: '通过准备检查，尚未记录模型交付。',
  withheld: '当前来源、权限或适用条件不满足，不展示正文。',
  quarantined: '安全检查未通过，内容未进入上下文。',
  budget_dropped: '候选未进入本次上下文预算。',
  delivered: '存在此版本的实际模型交付回执。',
}

const SCOPE_LABELS: Record<string, string> = {
  private: '个人范围',
  project: '项目范围',
  team_accepted: '团队范围',
}

const LAYER_LABELS: Record<string, string> = {
  short_term: '短期',
  mid_term: '中期',
  long_term: '长期',
}
