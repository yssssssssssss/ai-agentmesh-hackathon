import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { MemoryPreferences } from '../../features/knowledge/learningApi'
import { MemoryPreferencesForm } from './MemoryPreferencesPanel'

const preferences: MemoryPreferences = {
  schema_version: 'memory-preferences-v1', id: 'owner', user_id: 'owner', workspace_id: 'workspace',
  version: 1, learning_enabled: false, core_preferences: ['中文回答', '先列证据'], daily_token_cap: 64000,
  updated_at: '2026-10-04T00:00:00Z',
}

describe('MemoryPreferencesForm', () => {
  it('shows private preferences independently of unavailable background learning', () => {
    const html = renderToStaticMarkup(<MemoryPreferencesForm preferences={preferences} executable={false} pending={false} onSave={() => {}} />)
    expect(html).toContain('后台资料学习尚未启用；核心偏好可以独立保存。')
    expect(html).toContain('中文回答')
    expect(html).toContain('先列证据')
    expect(html).toContain('保存记忆设置')
    expect(html).not.toContain('已完成学习')
  })

  it('prevents saving an oversized preference set and locks controls during a write', () => {
    const html = renderToStaticMarkup(<MemoryPreferencesForm preferences={{ ...preferences, core_preferences: Array(9).fill('Too many') }}
      executable pending onSave={() => {}} />)
    expect(html).toContain('请检查偏好条数、单条长度和预算范围。')
    expect(html).toContain('disabled=""')
  })
})
