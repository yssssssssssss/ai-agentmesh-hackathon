import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ReportActions } from './ReportActions'

describe('ReportActions', () => {
  it('opens the encoded report URL in a safe new tab and exposes an HTML download', () => {
    const html = renderToStaticMarkup(<ReportActions runId="run/report 1" />)

    expect(html).toContain('aria-label="报告操作"')
    expect(html).toContain('href="/api/agent/runs/run%2Freport%201/report.html"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('href="/api/agent/runs/run%2Freport%201/report.html?download=true"')
    expect(html).toContain('download=""')
    expect(html).toContain('独立查看')
    expect(html).toContain('下载 HTML')
  })
})
