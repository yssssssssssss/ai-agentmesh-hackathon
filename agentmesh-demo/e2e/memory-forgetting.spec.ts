import { expect, test } from '@playwright/test'
import { loginAs } from './support/auth'

test('persists private preferences and forgets a real source-backed memory from its detail page', async ({ page }) => {
  await loginAs(page)
  await page.goto('/digital-self')
  const settings = page.getByRole('region', { name: '我的记忆设置' })
  await expect(settings.getByLabel('核心偏好（每行一条，最多 8 条）')).toBeVisible()
  await settings.getByLabel('核心偏好（每行一条，最多 8 条）').fill('引用资料时给出证据\n优先中文')
  await settings.getByRole('button', { name: '保存记忆设置' }).click()
  await expect(settings.getByRole('status')).toContainText('记忆设置已保存')
  const preferences = await page.request.get('/api/memory/preferences')
  expect((await preferences.json()).core_preferences).toEqual(['引用资料时给出证据', '优先中文'])
  await page.reload()
  await expect(settings.getByLabel('核心偏好（每行一条，最多 8 条）')).toHaveValue('引用资料时给出证据\n优先中文')

  const uploaded = await page.request.post('/api/documents/upload', {
    multipart: { file: { name: 'forgettable.txt', mimeType: 'text/plain', buffer: Buffer.from('本项目唯一代码为 forgettable-pilot。') } },
  })
  expect(uploaded.status()).toBe(200)
  const { item: document } = await uploaded.json()
  const source = await (await page.request.get(`/api/memory/facts/source-documents/${document.id}`)).json()
  const title = `可遗忘的项目事实-${Date.now()}`
  const remembered = await page.request.post('/api/memory/facts/remember', { data: {
    command_id: title, title, summary: '本人显式确认的项目代码', project_id: document.project_id,
    source_document_id: document.id, source_version: source.version, source_hash: source.content_hash,
    facts: [{ subject_type: 'project', subject_id: document.project_id, predicate: 'project_code', value: 'forgettable-pilot',
      valid_from: '2026-10-01T00:00:00Z', time_precision: 'day' }],
  } })
  expect(remembered.status()).toBe(201)
  const memory = await remembered.json()
  await page.goto(`/knowledge?memory=${memory.id}&project=${document.project_id}`)
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: title })).toBeVisible()
  await dialog.getByRole('button', { name: '遗忘此私有记忆' }).click()
  await expect(dialog.getByText(/已交付内容、审计和备份不在本次删除范围内/)).toBeVisible()
  await dialog.getByRole('button', { name: '确认遗忘' }).click()
  await expect(dialog).toBeHidden()
  const query = await page.request.post('/api/memory/facts/query', { data: {
    project_id: document.project_id, subject_type: 'project', subject_id: document.project_id, predicate: 'project_code',
  } })
  expect((await query.json()).outcome).toBe('unknown')
  expect((await page.request.get(`/api/documents/${document.id}`)).status()).toBe(200)
  await page.goto('/knowledge')
  await expect(page.getByRole('heading', { name: title })).toHaveCount(0)
  const replay = await page.request.post('/api/memory/facts/remember', { data: {
    command_id: title, title, summary: '本人显式确认的项目代码', project_id: document.project_id,
    source_document_id: document.id, source_version: source.version, source_hash: source.content_hash,
    facts: [{ subject_type: 'project', subject_id: document.project_id, predicate: 'project_code', value: 'forgettable-pilot',
      valid_from: '2026-10-01T00:00:00Z', time_precision: 'day' }],
  } })
  expect(replay.status()).toBe(409)
})
