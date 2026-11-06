import { expect, test } from '@playwright/test'
import { loginAs } from './support/auth'

test('confirms project aliases through real APIs and refuses stale edits before exposing conflicts', async ({ page }) => {
  await loginAs(page, 'usr_team_lead', 'lead123')
  const bootstrap = await (await page.request.get('/api/bootstrap')).json()
  const projectId = bootstrap.project.id
  const url = `/api/memory/facts/terminology/${encodeURIComponent(projectId)}`
  const original = await (await page.request.get(url)).json()
  const suffix = Date.now()
  const alias = `入口-${suffix}`
  const canonical = `网关-${suffix}`
  const uploaded = await page.request.post('/api/documents/upload', {
    multipart: { file: { name: 'terms.txt', mimeType: 'text/plain', buffer: Buffer.from('网关版本存在 V1 和 V2 两条记录。') } },
  })
  const { item: document } = await uploaded.json()
  const source = await (await page.request.get(`/api/memory/facts/source-documents/${document.id}`)).json()
  for (const [subject_id, value] of [[alias, 'V1'], [canonical, 'V2']]) {
    const response = await page.request.post('/api/memory/facts/remember', { data: {
      command_id: `${subject_id}-fact`, title: subject_id, summary: '确认的项目术语版本', project_id: projectId,
      source_document_id: document.id, source_version: source.version, source_hash: source.content_hash,
      facts: [{ subject_type: 'term', subject_id, predicate: 'version', value, valid_from: '2026-10-01T00:00:00Z' }],
    } })
    expect(response.status()).toBe(201)
  }
  await page.goto(`/knowledge?project=${encodeURIComponent(projectId)}`)
  await page.getByText('项目术语库', { exact: true }).click()
  const panel = page.getByRole('region', { name: '项目术语库' })
  await panel.getByRole('button', { name: '编辑项目术语', exact: true }).click()
  await panel.getByLabel('别名', { exact: true }).fill(alias)
  await panel.getByLabel('规范名称', { exact: true }).fill(canonical)
  await panel.getByRole('button', { name: '加入映射' }).click()
  // Another member confirms a change while this browser is still editing the old version.
  expect((await page.request.put(url, { data: { command_id: `concurrent-${suffix}`,
    expected_version: original.version, aliases: { ...original.aliases, [`其他入口-${suffix}`]: canonical } },
  })).status()).toBe(200)
  await panel.getByRole('button', { name: '确认保存术语' }).click()
  await expect(panel.getByRole('alert')).toContainText('重新加载')
  await expect(panel.getByRole('button', { name: '确认保存术语' })).toBeDisabled()
  await panel.getByRole('button', { name: '重新加载术语' }).click()
  await expect(panel).toContainText(`其他入口-${suffix}`)
  await panel.getByRole('button', { name: '编辑项目术语', exact: true }).click()
  await panel.getByLabel('别名', { exact: true }).fill(alias)
  await panel.getByLabel('规范名称', { exact: true }).fill(canonical)
  await panel.getByRole('button', { name: '加入映射' }).click()
  await panel.getByRole('button', { name: '确认保存术语' }).click()
  await expect(panel.getByRole('list', { name: '已确认术语别名' })).toContainText(`${alias} → ${canonical}`)
  await page.reload()
  await page.getByText('项目术语库', { exact: true }).click()
  await expect(page.getByRole('list', { name: '已确认术语别名' })).toContainText(alias)
  const report = await (await page.request.post('/api/memory/facts/query', { data: {
    project_id: projectId, subject_type: 'term', subject_id: canonical, predicate: 'version',
  } })).json()
  expect(report.outcome).toBe('conflict')
  expect(report.automatic_context_eligible).toBe(false)
  expect(report.term_resolution.alias_version).toBe(original.version + 2)
  await loginAs(page)
  await page.goto(`/knowledge?project=${encodeURIComponent(projectId)}`)
  await page.getByText('项目术语库', { exact: true }).click()
  await expect(page.getByRole('region', { name: '项目术语库' })).toContainText(alias)
  await expect(page.getByRole('button', { name: '编辑项目术语', exact: true })).toHaveCount(0)
})
