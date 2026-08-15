import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test('React default UI carries the MVP parity journey without local demo state', async ({ page }) => {
  test.setTimeout(90_000)
  const marker = `m10-parity-${Date.now()}`
  await page.goto('/')
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  await loginAs(page)

  await page.goto('/workspace')
  const composer = page.getByLabel('消息')
  const chatResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/chat/messages') && response.request().method() === 'POST',
  )
  await composer.fill(`$research.request ${marker}`)
  await page.getByRole('button', { name: '发送' }).click()
  const sent = await chatResponse
  expect(sent.status()).toBe(200)
  const turn = await sent.json() as { thread_id: string; task: { id: string } }
  await expect(page).toHaveURL(new RegExp(`/workspace/thread/${turn.thread_id}$`))
  await expect(page.getByTestId('user-message').filter({ hasText: marker })).toBeVisible()
  await expect(page.getByTestId('provider-provenance')).toContainText('请求提供方')
  await expect(page.getByTestId('provider-provenance')).toContainText('实际提供方')
  await expect(page.getByRole('button', { name: /2025 618 家电会场复盘/ })).toBeVisible()

  await page.reload()
  await expect(page.getByTestId('user-message').filter({ hasText: marker })).toBeVisible()
  await expect(page.getByTestId('provider-provenance')).toContainText('实际提供方')

  const uploadName = `${marker}.txt`
  await page.getByLabel('上传文档').setInputFiles({
    name: uploadName,
    mimeType: 'text/plain',
    buffer: Buffer.from(`${marker}\ncanonical parity source`),
  })
  await expect(page.getByTestId('upload-status')).toContainText(uploadName)
  await expect(page.getByTestId('upload-status')).toContainText('已导入', { timeout: 15_000 })
  await page.getByLabel('搜索资料').fill(marker)
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  const documentResult = page
    .getByTestId('search-result')
    .filter({ hasText: uploadName })
    .filter({ has: page.getByRole('button', { name: '查看详情' }) })
    .first()
  await expect(documentResult).toContainText(/document|文档/)

  const briefResponse = await page.request.post('/api/chat/messages', {
    data: { content: `$brief.create ${marker}`, client_turn_id: `${marker}-brief` },
  })
  expect(briefResponse.status()).toBe(200)
  const briefItem = (await briefResponse.json()).inbox_items[0]
  await page.goto('/knowledge')
  await page.locator(`[data-inbox-item-id="${briefItem.id}"]`).getByRole('button', { name: '确认并沉淀' }).click()
  await page.getByLabel('Brief 正文').fill(`${marker} confirmed brief`)
  await page.getByRole('button', { name: '确认 Brief' }).click()
  await expect(page.getByRole('status')).toContainText('Brief 已确认')

  await page.goto('/collaboration')
  await expect(page.getByText('正在读取任务卡…')).toHaveCount(0, { timeout: 15_000 })
  await page.getByRole('tab', { name: /我发起的/ }).click()
  const taskCard = page.locator(`[data-task-id="${turn.task.id}"]`)
  await expect(taskCard).toBeVisible({ timeout: 15_000 })
  await taskCard.getByRole('button', { name: '查看协作详情' }).click()
  await expect(page.getByRole('dialog')).toContainText('任务阶段')
  await page.getByRole('dialog').getByRole('button', { name: '关闭' }).click()

  await expect(page.getByText(/演示数据|模拟生成|正在补充分析|DemoContext/)).toHaveCount(0)

  await loginAs(page, 'usr_admin', 'admin123')
  await page.goto('/admin')
  await page.getByRole('tab', { name: 'Provider 与 O2' }).click()
  await expect(page.getByRole('heading', { name: 'Provider diagnostics' })).toBeVisible()
  await expect(page.getByText('document_parser', { exact: true })).toBeVisible({ timeout: 15_000 })

  const origin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8021'
  for (const path of ['/', `/workspace/thread/${turn.thread_id}`, '/knowledge']) {
    const response = await page.request.get(`${origin}${path}`)
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/html')
  }
  expect((await page.request.get(`${origin}/legacy/app.html`)).status()).toBe(200)
  const missingApi = await page.request.get(`${origin}/api/m10-missing`)
  expect(missingApi.status()).toBe(404)
  expect(missingApi.headers()['content-type']).toContain('application/json')
})
