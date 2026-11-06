import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import type { DocumentRecord } from '../../features/knowledge/api'
import { DocumentMaintenancePanel } from './DocumentMaintenancePanel'

const own: DocumentRecord = { id: 'own', title: '本人当前资料', text: 'private body', version: 2, file_name: 'guide.md',
  uploaded_by: 'owner', project_id: 'project', expected_chunks: 0, completed_chunks: 0 }
const render = (documents: DocumentRecord[], error = false) => renderToStaticMarkup(
  <QueryClientProvider client={new QueryClient()}>
    <DocumentMaintenancePanel userId="owner" projectId="project" documents={documents} error={error} />
  </QueryClientProvider>,
)

describe('document maintenance selection', () => {
  it('offers only the current project uploader documents and explains the two separate commands', () => {
    const html = render([own, { ...own, id: 'peer', uploaded_by: 'peer', title: '同事资料' },
      { ...own, id: 'foreign', project_id: 'foreign', title: '其他项目资料' }])
    expect(html).toContain('本人当前资料 · v2')
    expect(html).not.toContain('同事资料')
    expect(html).not.toContain('其他项目资料')
    expect(html).not.toContain('private body')
    expect(html).toContain('保存正文会使旧片段失效')
    expect(html).toContain('重新导入单独生成当前版本')
  })

  it('makes missing and unreadable source lists visible', () => {
    expect(render([])).toContain('当前项目尚无本人资料')
    expect(render([], true)).toContain('无法读取资料')
    expect(render([], true)).not.toContain('当前项目尚无本人资料')
  })
})
