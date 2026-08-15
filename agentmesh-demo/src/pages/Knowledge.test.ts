import { describe, expect, it } from 'vitest'

import { ApiError } from '../api/client'
import { queryResource } from './Knowledge'

describe('queryResource', () => {
  const cached = { items: ['stale'] }

  it('keeps cached data read-only when the latest query is forbidden', () => {
    const error = new ApiError(403, '禁止访问', { detail: '禁止访问' })

    expect(queryResource({ data: cached, isLoading: false, error })).toEqual({
      state: 'forbidden',
      error: '没有执行此操作的权限：禁止访问',
    })
  })

  it('keeps cached data read-only when the latest query failed', () => {
    expect(queryResource({ data: cached, isLoading: false, error: new Error('网络失败') })).toEqual({
      state: 'error',
      error: '网络失败',
    })
  })

  it('does not expose cached data while the query is loading', () => {
    expect(queryResource({ data: cached, isLoading: true, error: null })).toEqual({
      state: 'loading',
    })
  })
})
