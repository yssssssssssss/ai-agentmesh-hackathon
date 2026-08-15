import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { presentedModule, presentedValue } from '../../lib/presentation'
import { buildDigitalSelfViewModel, type DigitalSelfViewModel } from '../../features/digital-self/presenter'
import { TodayWork } from './TodayWork'

function renderPending(model: DigitalSelfViewModel['pending']): string {
  return renderToStaticMarkup(
    createElement(MemoryRouter, null, createElement(TodayWork, { model })),
  )
}

describe('TodayWork', () => {
  it('keeps T ActivityLog route-free in the presenter and read-only in the component', () => {
    const model = buildDigitalSelfViewModel({
      bootstrap: { state: 'loading' },
      agent: { state: 'loading' },
      activity: {
        state: 'available',
        data: {
          personal: [{
            id: 'activity-1',
            actor: '真实数字员工',
            title: '整理项目资料',
            summary: '已完成服务端活动记录整理',
            category: 'brief_generation',
            scope: 'private',
          }],
          external: [],
        },
      },
      memory: { state: 'loading' },
    }).pending
    const html = renderPending(model)

    expect(model.data.items[0]).not.toHaveProperty('to')
    expect(model.data.items[0]).not.toHaveProperty('cta')
    expect(html).toContain('今日工作记录')
    expect(html).toContain('<article')
    expect(html).toContain('只读活动')
    expect(html).not.toContain('<button')
  })

  it('keeps reference pending rows disabled when their route is M data', () => {
    const item = {
      id: presentedValue('pending-1', 'M'),
      title: presentedValue('参考待处理事项', 'M'),
      context: presentedValue('仅用于恢复参考展示', 'M'),
      tag: presentedValue('参考数据', 'M'),
      cta: presentedValue('去处理', 'M'),
      to: presentedValue('/workspace', 'M'),
    }
    const html = renderPending(presentedModule({ items: [item] }, Object.values(item)))

    expect(html).toContain('需要你处理')
    expect(html).toContain('<button')
    expect(html).toContain('disabled=""')
    expect(html).toContain('参考展示事项，当前不可操作')
  })

  it('enables navigation only when the route itself is explicit T data', () => {
    const item = {
      id: presentedValue('pending-2', 'T'),
      title: presentedValue('真实待处理事项', 'T'),
      context: presentedValue('后端明确提供了处理入口', 'T'),
      tag: presentedValue('待处理', 'T'),
      cta: presentedValue('去处理', 'T'),
      to: presentedValue('/workspace', 'T'),
    }
    const html = renderPending(presentedModule({ items: [item] }, Object.values(item)))

    expect(html).toContain('<button')
    expect(html).not.toContain('disabled=""')
  })
})
