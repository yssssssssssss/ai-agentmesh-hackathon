import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { components } from '../../api/generated/schema'
import { DocumentImportRow } from './DocumentImportPanel'

const job: components['schemas']['DocumentParseJob'] = {
  id: 'job', file_name: '原始资料.md', content_type: 'text/markdown', workspace_id: 'ws', project_id: 'project',
  uploaded_by: 'owner', status: 'failed', input_contract: 'document-input-v1', attempt_count: 1, state_version: 3,
  input_cleanup_pending: false, input_purged: false, version: 1, expected_chunks: 0, completed_chunks: 0,
}
const row = (changes: Partial<typeof job>, userId = 'owner') => renderToStaticMarkup(
  <DocumentImportRow job={{ ...job, ...changes }} userId={userId} busy={false} onRetry={() => {}} />,
)

describe('document import outcomes', () => {
  it('distinguishes queued input from a completed import', () => {
    const queued = row({ status: 'queued' })
    expect(queued).toContain('等待解析')
    expect(queued).not.toContain('已导入')
    const completed = row({ status: 'completed', completed_chunks: 2, input_cleanup_pending: true })
    expect(completed).toContain('已导入 2 个检索片段')
    expect(completed).toContain('本次上传 v1')
    expect(completed).toContain('导入结果仍有效')
  })

  it('offers retry only to the uploader with remaining durable input', () => {
    expect(row({})).toContain('重试解析')
    expect(row({}, 'admin')).not.toContain('重试解析')
    expect(row({ attempt_count: 3 })).not.toContain('重试解析')
    expect(row({ input_purged: true, error: 'document_input_expired' })).not.toContain('重试解析')
    expect(row({ input_contract: null })).not.toContain('重试解析')
  })

  it('does not turn failed cleanup into a successful import or expose raw errors', () => {
    const html = row({ input_cleanup_pending: true, error: 'private-parser-body' })
    expect(html).toContain('导入失败')
    expect(html).not.toContain('导入结果仍有效')
    expect(html).not.toContain('private-parser-body')
  })
})
