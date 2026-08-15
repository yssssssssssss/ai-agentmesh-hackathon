import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { DataSourceBadge } from '../components/ui/DataSourceBadge'
import {
  dataSourceKind,
  canUseMockFallback,
  moduleSources,
  presentedModule,
  presentedValue,
} from './presentation'

describe('presentation provenance', () => {
  it('keeps real and mock values explicit', () => {
    expect(presentedValue('真实项目', 'T')).toEqual({ value: '真实项目', source: 'T' })
    expect(presentedValue(12, 'M', '后端暂无聚合')).toEqual({
      value: 12,
      source: 'M',
      reason: '后端暂无聚合',
    })
  })

  it('reports module sources without duplicates', () => {
    const values = [
      presentedValue('真实', 'T'),
      presentedValue('演示', 'M'),
      presentedValue('仍是真实', 'T'),
    ]
    expect(moduleSources(values)).toEqual(['T', 'M'])
    expect(presentedModule({ title: '模块' }, values, { missingFields: ['impact'] })).toEqual({
      data: { title: '模块' },
      sources: ['T', 'M'],
      missingFields: ['impact'],
      loading: false,
      error: null,
    })
  })

  it('rejects unknown provenance instead of silently treating it as mock', () => {
    expect(() => dataSourceKind('unknown')).toThrow('Unknown data source kind: unknown')
  })

  it.each([
    ['empty', true],
    ['unsupported', true],
    ['available', false],
    ['loading', false],
    ['forbidden', false],
    ['error', false],
  ] as const)('allows mock fallback for %s only when safe', (state, expected) => {
    expect(canUseMockFallback(state)).toBe(expected)
  })

  it.each([
    ['T', 'T数据', 'mint'],
    ['M', 'M数据', 'remind'],
  ] as const)('renders %s with the exact accessible label', (source, label, tone) => {
    const html = renderToStaticMarkup(createElement(DataSourceBadge, { source }))
    expect(html).toContain(`aria-label="${label}"`)
    expect(html).toContain(label)
    expect(html).toContain(`data-tone="${tone}"`)
  })
})
