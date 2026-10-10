import { apiRequest } from '../../api/client'
import type { components } from '../../api/generated/schema'

export type MemoryPreferences = Required<components['schemas']['MemoryPreferencesV1']>
export type LearningJob = Required<components['schemas']['MemoryLearningJobV1']>
export type LearnedCandidate = Required<components['schemas']['UserMemoryItem']>
export type SourceSpan = components['schemas']['DocumentSourceSpanV1']
export type LearningStatus = components['schemas']['MemoryLearningStatusV1']

export const learningApi = {
  preferences: () => apiRequest<MemoryPreferences>('/api/memory/preferences'),
  status: () => apiRequest<LearningStatus>('/api/memory/learning/status'),
  patchPreferences: (payload: components['schemas']['MemoryPreferencesPatchV1']) =>
    apiRequest<MemoryPreferences>('/api/memory/preferences', { method: 'PATCH', body: JSON.stringify(payload) }),
  jobs: () => apiRequest<LearningJob[]>('/api/memory/learning/jobs'),
  learn: (payload: components['schemas']['DocumentLearnRequestV1']) =>
    apiRequest<LearningJob>('/api/memory/learning/jobs', { method: 'POST', body: JSON.stringify(payload) }),
  candidate: (jobId: string) => apiRequest<LearnedCandidate>(`/api/memory/learning/jobs/${encodeURIComponent(jobId)}/candidate`),
  span: (spanId: string) => apiRequest<SourceSpan>(`/api/memory/source-spans/${encodeURIComponent(spanId)}`),
  confirm: (jobId: string, payload: components['schemas']['LearningConfirmationV1']) =>
    apiRequest<LearnedCandidate>(`/api/memory/learning/jobs/${encodeURIComponent(jobId)}/confirm`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  retry: (job: LearningJob) => apiRequest<LearningJob>(`/api/memory/learning/jobs/${encodeURIComponent(job.id)}/retry`, {
    method: 'POST', body: JSON.stringify({ command_id: crypto.randomUUID(), expected_lease_epoch: job.lease_epoch }),
  }),
  sourceIdentity: (documentId: string) => apiRequest<components['schemas']['MemoryEvidenceRefV1']>(
    `/api/memory/facts/source-documents/${encodeURIComponent(documentId)}`,
  ),
  forget: (kind: 'memory' | 'document', id: string, version: number) =>
    apiRequest<components['schemas']['MemoryForgetResultV1']>(
      kind === 'memory' ? `/api/memory/${encodeURIComponent(id)}/forget`
        : `/api/memory/sources/documents/${encodeURIComponent(id)}/withdraw`,
      { method: 'POST', body: JSON.stringify({ command_id: crypto.randomUUID(), expected_version: version }) },
    ),
}

const ERROR_MESSAGES: Record<string, string> = {
  memory_learning_unavailable: '后台资料学习尚未启用。',
  memory_learning_paused: '资料学习已暂停，可在数字员工页面开启。',
  memory_learning_source_not_found: '资料已撤回或当前不可读取。',
  memory_learning_source_changed: '资料已更新，请基于最新版本重新学习。',
  memory_learning_source_too_large: '资料超过本次学习上限，请拆分为较小的文档。',
  memory_learning_quote_mismatch: '候选引用与原文不一致，未保存记忆。',
  memory_learning_model_auth_unavailable: '模型服务鉴权失败，请检查服务端配置。',
  model_unavailable: '没有可用模型，未生成记忆。',
  memory_learning_budget_exhausted: '本任务已达到学习预算或尝试上限。',
  memory_learning_daily_budget_exhausted: '今日后台学习预算已用尽，可在次日重试。',
  memory_learning_content_requires_review: '候选包含需检查的指令内容，未保存记忆。',
  memory_learning_extraction_failed: '资料抽取失败，未生成可用记忆。',
  memory_learning_transient_failure: '模型服务暂时不可用，等待重试。',
  memory_learning_retry_window_unavailable: '模型要求的等待时间超过一天，自动重试已停止。',
  memory_learning_lease_lost: '学习任务的执行权限或租约已变化，此次结果未保存。',
  memory_learning_policy_changed: '学习策略已变化，此次结果未保存。',
  memory_learning_actor_unavailable: '当前账户已不可执行学习。',
  memory_learning_project_unavailable: '当前项目权限已变化，此次结果未保存。',
  memory_learning_model_changed: '所选模型已变化，请重新提交重试。',
  memory_learning_usage_unavailable: '模型未返回用量，未生成可用记忆。',
  memory_learning_usage_invalid: '模型用量超出本次约定，未生成可用记忆。',
}

export function learningError(code: unknown): string {
  const text = typeof code === 'string' ? code : code instanceof Error ? code.message : ''
  return ERROR_MESSAGES[text] ?? '操作未完成，请刷新状态后重试。'
}
