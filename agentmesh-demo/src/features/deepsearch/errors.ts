import { ApiError } from '../../api/client'

const ERROR_COPY: Record<string, string> = {
  deepsearch_requirement_version_conflict: '需求状态已更新，已重新载入最新一轮，请核对后再提交。',
  deepsearch_requirement_idempotency_conflict: '本次回答与已提交请求不一致，请核对最新需求状态。',
  deepsearch_requirement_state_conflict: '当前 DeepSearch 阶段已经变化，已重新载入最新状态。',
  deepsearch_clarification_invalid: '回答不符合当前问题要求，请检查必填项和选项。',
  deepsearch_clarification_payload_too_large: '本轮回答过长，请精简后重试。',
  deepsearch_requirement_integrity_failed: '需求状态未通过完整性校验，已停止继续执行。',
  deepsearch_execution_unavailable: '当前环境不能继续执行 DeepSearch。',
  deepsearch_planner_unavailable: 'DeepSearch 规划器暂不可用。',
}

export function deepSearchErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.detail && typeof error.detail === 'object') {
    const detail = error.detail as { code?: unknown; message?: unknown }
    if (typeof detail.message === 'string' && detail.message.trim()) return detail.message
    if (typeof detail.code === 'string' && ERROR_COPY[detail.code]) return ERROR_COPY[detail.code]
  }
  if (error instanceof ApiError && typeof error.detail === 'string') return error.detail
  if (error instanceof Error) return error.message
  return 'DeepSearch 请求失败，请稍后重试'
}
