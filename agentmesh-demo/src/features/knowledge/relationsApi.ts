import { ApiError, apiRequest } from '../../api/client'
import type { components } from '../../api/generated/schema'
import type { QueryScope } from '../../app/queryKeys'

export type RelationRoot = components['schemas']['RelationLookupV1']
export type RelationGraph = components['schemas']['MemoryRelationGraphV1'] & {
  nodes: components['schemas']['RelationNodeV1'][]
  edges: components['schemas']['RelationEdgeV1'][]
}
export type RelationNode = components['schemas']['RelationNodeV1']
export type RelationCreate = components['schemas']['MemoryRelationCreateV1']

export const relationKey = (context: QueryScope, root: RelationRoot) => [
  'memory', 'relations', context.userId, context.workspaceId, context.projectId, root.record_type, root.record_id,
] as const

export function queryRelations(context: QueryScope, root: RelationRoot, signal?: AbortSignal) {
  return apiRequest<RelationGraph>('/api/memory/relations/query', {
    method: 'POST', signal,
    body: JSON.stringify({ project_id: context.projectId, root, max_hops: 2 }),
  })
}

export function createRelation(request: RelationCreate) {
  return apiRequest<components['schemas']['MemoryRelation']>('/api/memory/relations', {
    method: 'POST', body: JSON.stringify(request),
  })
}

export function relationError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return '关联依据已更新，请刷新后重新选择。'
    if ([401, 403, 404].includes(error.status)) return '当前账号无法访问或关联这些记录。'
  }
  return '关联查询或保存失败，请稍后重试。'
}

export function relationReference(node: RelationNode) {
  return { record_type: node.record_type, record_id: node.record_id, version: node.version, content_hash: node.content_hash }
}

export function relationHref(href: string): string | undefined {
  return /^\/(tasks\?|knowledge\?|api\/artifacts\/)/.test(href) ? href : undefined
}
