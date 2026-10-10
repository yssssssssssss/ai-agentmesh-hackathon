import { ApiError, apiRequest } from '../../api/client'
import type { components } from '../../api/generated/schema'

export type FactQuery = components['schemas']['FactQueryV1']
export type FactQueryResult = components['schemas']['FactQueryResultV1']
export interface FactQueryForm {
  subjectType: 'project' | 'term'; subject: string; predicate: string
  timeMode: 'current' | 'point' | 'interval'; at: string; until: string; observedBefore: string
}

export function buildFactQuery(projectId: string, form: FactQueryForm): FactQuery {
  const subject = form.subjectType === 'project' ? projectId : form.subject.trim()
  if (!subject) throw new Error('请填写要查询的概念或模块名称。')
  const instant = (value: string) => {
    const date = new Date(value)
    if (!value || Number.isNaN(date.getTime())) throw new Error('请选择有效的查询时间。')
    return date.toISOString()
  }
  const request: FactQuery = {
    project_id: projectId, subject_type: form.subjectType, subject_id: subject, predicate: form.predicate,
  }
  if (form.timeMode === 'point') request.as_of = instant(form.at)
  if (form.timeMode === 'interval') {
    request.interval_from = instant(form.at)
    request.interval_to = instant(form.until)
    if (request.interval_to <= request.interval_from) throw new Error('结束时间必须晚于开始时间。')
  }
  if (form.observedBefore) request.observed_before = instant(form.observedBefore)
  return request
}

export function queryFacts(request: FactQuery, signal?: AbortSignal): Promise<FactQueryResult> {
  return apiRequest('/api/memory/facts/query', { method: 'POST', body: JSON.stringify(request), signal })
}

export function factQueryError(error: unknown): string {
  if (error instanceof ApiError) {
    if ([401, 403, 404].includes(error.status)) return '当前账号无法查询该项目，请检查项目选择和访问权限。'
    if (error.status === 422) return '查询条件无法识别，请检查名称和时间。'
  }
  return '事实查询未完成，可以稍后重试。'
}
