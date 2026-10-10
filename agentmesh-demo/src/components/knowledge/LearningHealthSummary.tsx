import type { LearningStatus } from '../../features/knowledge/learningApi'

const ALERT_LABELS: Record<string, string> = {
  queue_delayed: '学习队列等待超过五分钟。',
  lease_expired: '有学习任务未按时续租，将重新检查后恢复。',
  budget_exhausted: '今日后台学习预算已用尽。',
  cleanup_delayed: '有撤回资料的索引清理等待超过一分钟。',
  usage_unreported: '有尝试尚未报告用量，预算预留继续保留。',
}

export function LearningHealthSummary({ status }: { status: LearningStatus }) {
  if (!status.queue) return null
  return <div className="rounded-control bg-surface-1 p-3 text-xs text-slate-400" aria-label="本人学习队列状态">
    <p>本人可访问项目：待处理 {status.queue.ready ?? 0} · 学习中 {status.queue.running ?? 0} · 等待重试 {status.queue.retry_wait ?? 0}</p>
    <p className="mt-1">今日预算预留 {status.daily_reserved_tokens}/{status.daily_token_cap ?? 64000} Token · 待清理 {status.cleanup_pending}</p>
    {(status.alerts ?? []).map((alert) => ALERT_LABELS[alert] ?
      <p key={alert} role="status" className="mt-1 text-amber-300">{ALERT_LABELS[alert]}</p> : null)}
  </div>
}
