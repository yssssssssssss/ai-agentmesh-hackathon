import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ConnectorCursor } from '../../features/knowledge/connectorsApi'
import { SourceSyncRow } from './SourceSyncPanel'

const cursor: ConnectorCursor = {
  schema_version: 'connector_sync_cursor_v1', scan_mode: 'incremental', consecutive_failures: 1,
  enabled: true, operator_bound: true, auto_sync_enabled: false, interval_seconds: 900,
  id: 'connector', owner_user_id: 'owner', workspace_id: 'ws', project_id: 'project', provider: 'github_issues',
  namespace: 'example/pilot', configuration_hash: 'a'.repeat(64), version: 2, observed_count: 0,
  status: 'failed', scan_started_at: '2026-10-07T00:00:00Z', last_successful_at: null,
  last_error_code: 'connector_access_unavailable',
}

describe('source synchronization outcomes', () => {
  it('offers explicit automatic sync and shows a waiting schedule with pause control', () => {
    const item = { provider: 'github_issues' as const, namespace: 'example/pilot', cursor,
      configured: true, configuration_changed: false }
    const enabled = renderToStaticMarkup(<SourceSyncRow item={item} busy={false} autoAvailable
      onSync={() => {}} onControl={() => {}} />)
    expect(enabled).toContain('开启自动同步')
    const waiting = renderToStaticMarkup(<SourceSyncRow item={{ ...item, cursor: { ...cursor,
      auto_sync_enabled: true, next_sync_at: '2099-10-07T00:00:00Z', next_allowed_at: '2099-10-07T00:00:00Z',
      last_error_code: 'connector_rate_limited' } }} busy={false} autoAvailable
      onSync={() => {}} onControl={() => {}} />)
    expect(waiting).toContain('下次读取')
    expect(waiting).toContain('暂停自动同步')
    expect(waiting).toContain('受到限流')
    expect(waiting).toContain('允许再次读取')
    expect(waiting).toContain('disabled')
  })

  it('shows failed first reads as unavailable and offers retry without claiming completion', () => {
    const html = renderToStaticMarkup(<SourceSyncRow item={{ provider: 'github_issues', namespace: 'example/pilot', cursor,
      configured: true, configuration_changed: false }}
      busy={false} onSync={() => {}} />)
    expect(html).toContain('尚未成功读取资料')
    expect(html).toContain('已停止引用旧资料')
    expect(html).toContain('重试同步')
    expect(html).not.toContain('本轮已完成')
    expect(html).not.toContain('完整复核')
  })

  it('keeps incomplete pages distinct from completion and disables actions while processing', () => {
    const html = renderToStaticMarkup(<SourceSyncRow item={{ provider: 'github_issues', namespace: 'example/pilot',
      configured: true, configuration_changed: false,
      cursor: { ...cursor, status: 'syncing', next_position: '2', last_error_code: null } }}
      busy onSync={() => {}} />)
    expect(html).toContain('等待继续')
    expect(html).toContain('继续同步')
    expect(html).toContain('disabled')
    expect(html).not.toContain('本轮已完成')
  })

  it('offers recovery for disabled sources and never offers sync or claims completion', () => {
    const html = renderToStaticMarkup(<SourceSyncRow item={{ provider: 'github_issues', namespace: 'example/pilot',
      configured: true, configuration_changed: false, cursor: { ...cursor, enabled: false, status: 'disabled' } }}
      busy={false} onSync={() => {}} onControl={() => {}} />)
    expect(html).toContain('恢复并重置')
    expect(html).not.toContain('重试同步')
    expect(html).not.toContain('本轮已完成')
  })

  it('keeps removed sources manageable without offering unavailable sync or reset', () => {
    const html = renderToStaticMarkup(<SourceSyncRow item={{ provider: 'github_issues', namespace: 'example/pilot',
      configured: false, configuration_changed: false, cursor }}
      busy={false} onSync={() => {}} onControl={() => {}} />)
    expect(html).toContain('来源配置已移除')
    expect(html).toContain('禁用同步')
    expect(html).not.toContain('重试同步')
    expect(html).not.toContain('重置进度')
  })

  it('shows an active first-page claim as reading and offers cancellation without claiming completion', () => {
    const html = renderToStaticMarkup(<SourceSyncRow item={{ provider: 'github_issues', namespace: 'example/pilot',
      configured: true, configuration_changed: false, cursor: { ...cursor, status: 'reading',
        read_claim_id: 'current-read', read_lease_until: '2026-10-07T00:01:30Z' } }}
      busy={false} onSync={() => {}} onControl={() => {}} />)
    expect(html).toContain('正在读取')
    expect(html).toContain('取消本轮')
    expect(html).toContain('disabled')
    expect(html).not.toContain('本轮已完成')
  })
})
