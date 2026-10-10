import { ApiError, apiRequest } from '../../api/client'
import type { components } from '../../api/generated/schema'

export type ProjectTerminology = Required<components['schemas']['ProjectTermAliasesV1']>
export type TermAliasUpdate = components['schemas']['TermAliasUpdateV1']

export const terminologyApi = {
  get: (projectId: string) => apiRequest<ProjectTerminology>(
    `/api/memory/facts/terminology/${encodeURIComponent(projectId)}`,
  ),
  update: (projectId: string, payload: TermAliasUpdate) => apiRequest<ProjectTerminology>(
    `/api/memory/facts/terminology/${encodeURIComponent(projectId)}`,
    { method: 'PUT', body: JSON.stringify(payload) },
  ),
}

export function terminologyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return '当前账户没有确认项目术语的权限。'
    if (error.status === 404) return '项目已不可访问，请重新选择项目。'
    if (error.status === 409) return '术语库已变化，请重新加载后核对修改。'
    if (error.status === 422) return '请检查名称长度、重复映射及别名链。'
  }
  return '无法完成术语库操作，请重试。'
}
