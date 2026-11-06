import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { terminologyError } from '../../features/knowledge/terminologyApi'
import { ProjectTerminologyPanel, TermAliasList } from './ProjectTerminologyPanel'

describe('project terminology', () => {
  it('escapes names and distinguishes an empty dictionary', () => {
    expect(renderToStaticMarkup(<TermAliasList aliases={{}} />)).toContain('尚未确认术语别名')
    const html = renderToStaticMarkup(<TermAliasList aliases={{ '<script>': '网关' }} />)
    expect(html).toContain('&lt;script&gt; → 网关')
    expect(html).not.toContain('<script>')
  })

  it('uses the selected project and current account cache and offers editing only with the capability', () => {
    const client = new QueryClient()
    client.setQueryData(['project-terminology', 'me', 'selected'], {
      version: 2, aliases: { '本项目入口': '网关' }, confirmed_by: 'lead',
    })
    client.setQueryData(['project-terminology', 'other-user', 'selected'], {
      version: 3, aliases: { '其他账户内容': '秘密' },
    })
    const render = (canManage: boolean) => renderToStaticMarkup(<QueryClientProvider client={client}>
      <ProjectTerminologyPanel userId="me" projectId="selected" canManage={canManage} />
    </QueryClientProvider>)
    expect(render(false)).toContain('本项目入口')
    expect(render(false)).not.toContain('其他账户内容')
    expect(render(false)).not.toContain('编辑项目术语</button>')
    expect(render(true)).toContain('编辑项目术语</button>')
    expect(render(true)).toContain('版本 2')
    client.clear()
  })

  it('presents conflicts and revoked permissions without raw server details', () => {
    expect(terminologyError(new ApiError(409, 'internal-detail', null))).toContain('重新加载')
    expect(terminologyError(new ApiError(403, 'internal-detail', null))).toContain('没有确认')
    expect(terminologyError(new ApiError(404, 'internal-detail', null))).toContain('不可访问')
    expect(terminologyError(new Error('secret body'))).not.toContain('secret body')
  })
})
