import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi, afterEach } from 'vitest'
import { ApiError } from '../../api/client'
import { createRelation, queryRelations, relationError, relationKey, relationReference, type RelationGraph } from '../../features/knowledge/relationsApi'
import { MemoryRelationsPanel, MemoryRelationsView } from './MemoryRelationsPanel'

const context = { userId: 'owner', workspaceId: 'ws', projectId: 'project' }
const root = { record_type: 'user_memory_item', record_id: 'memory' } as const
const graph: RelationGraph = {
  schema_version: 'memory-relation-graph-v1', data_mode: 'real', project_id: 'project',
  root_key: 'user_memory_item:memory', snapshot_at: '2026-10-07T00:00:00Z',
  nodes: [
    { ...root, title: '<script>rollout</script>', version: 2, content_hash: 'a'.repeat(64), status: 'active',
      navigation_href: '/knowledge?project=project&memory=memory', depth: 0 },
    { record_type: 'document', record_id: 'doc', title: 'Assignments', version: 3, content_hash: 'b'.repeat(64), status: 'current',
      navigation_href: '/knowledge?project=project&document=doc', depth: 1 },
  ],
  edges: [{ id: 'relation', from_key: 'user_memory_item:memory', to_key: 'document:doc', relation_type: 'supports',
    assertion: 'candidate', evidence: { record_type: 'document', record_id: 'doc', version: 3, content_hash: 'b'.repeat(64) } }],
  truncated: true, diagnostics: ['node_limit'],
}

afterEach(() => vi.unstubAllGlobals())

describe('memory relations', () => {
  it('shows versions, evidence, candidate status and bounded results without unsafe markup or links', () => {
    const html = renderToStaticMarkup(<MemoryRelationsView graph={graph} />)
    expect(html).toContain('&lt;script&gt;rollout&lt;/script&gt;')
    expect(html).toContain('候选关联')
    expect(html).toContain('文档依据 · v3')
    expect(html).toContain('仅展示部分关联')
    expect(html).toContain('/knowledge?project=project&amp;document=doc')
    const unsafe = { ...graph, nodes: graph.nodes.map((node) => ({ ...node, navigation_href: 'javascript:alert(1)' })) }
    expect(renderToStaticMarkup(<MemoryRelationsView graph={unsafe} />)).not.toContain('javascript:')
    expect(renderToStaticMarkup(<MemoryRelationsView graph={{ ...graph, edges: [], truncated: false }} />)).toContain('暂无可展示的关联')
  })

  it('isolates caches by account, workspace and project and requires explicit creation capability', () => {
    const client = new QueryClient()
    client.setQueryData(relationKey(context, root), graph)
    client.setQueryData(relationKey({ ...context, userId: 'peer' }, root), { ...graph, nodes: [{ ...graph.nodes[0], title: 'PRIVATE PEER' }] })
    const render = (canCreate: boolean) => renderToStaticMarkup(<QueryClientProvider client={client}>
      <MemoryRelationsPanel context={context} root={root} canCreate={canCreate} />
    </QueryClientProvider>)
    expect(render(false)).not.toContain('PRIVATE PEER')
    expect(render(false)).not.toContain('保存关联')
    expect(render(true)).toContain('选择当前任务或文档')
    expect(render(true)).toContain('我已核对依据，确认此关联')
    expect(render(true)).not.toContain('checked=""')
    expect(relationKey(context, root)).not.toEqual(relationKey({ ...context, workspaceId: 'other' }, root))
    expect(relationKey(context, root)).not.toEqual(relationKey({ ...context, projectId: 'other' }, root))
    client.clear()
  })

  it('sends the selected project and frozen evidence through the API without provider calls', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(graph), { headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    await queryRelations(context, root)
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ project_id: 'project', root, max_hops: 2 })
    await createRelation({ project_id: 'project', command_id: 'command', source: relationReference(graph.nodes[0]), target: relationReference(graph.nodes[1]),
      evidence: relationReference(graph.nodes[1]), relation_type: 'supports', assertion: 'candidate' })
    expect(fetch.mock.calls[1][0]).toBe('/api/memory/relations')
    expect(JSON.parse(fetch.mock.calls[1][1].body).source).toEqual({ ...root, version: 2, content_hash: 'a'.repeat(64) })
  })

  it('explains stale or revoked references without displaying raw server details', () => {
    expect(relationError(new ApiError(409, 'private ref', null))).toContain('依据已更新')
    expect(relationError(new ApiError(404, 'private ref', null))).toContain('无法访问')
    expect(relationError(new Error('secret body'))).not.toContain('secret body')
  })
})
