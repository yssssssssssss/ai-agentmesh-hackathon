import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test('displays source-backed fact intervals from real local APIs and reports conflicting confirmations', async ({ page }) => {
  await loginAs(page)
  const uploaded = await page.request.post('/api/documents/upload', {
    multipart: { file: { name: 'owners.txt', mimeType: 'text/plain', buffer: Buffer.from('项目负责人有两种记录：Alice 或 Bob。') } },
  })
  expect(uploaded.status()).toBe(200)
  const { item: document } = await uploaded.json()
  const evidence = await page.request.get(`/api/memory/facts/source-documents/${encodeURIComponent(document.id)}`)
  expect(evidence.ok()).toBeTruthy()
  const ref = await evidence.json()
  const command = `owners-${Date.now()}`
  const body = {
    command_id: command, title: `负责人有效时间 ${command}`, summary: '显式确认的负责人记录',
    project_id: document.project_id, source_document_id: document.id, source_version: ref.version, source_hash: ref.content_hash,
    facts: [{ subject_type: 'project', subject_id: document.project_id, predicate: 'owner', value: 'Bob',
      valid_from: '2026-10-01T00:00:00+00:00', time_precision: 'day' }],
  }
  const remembered = await page.request.post('/api/memory/facts/remember', { data: body })
  expect(remembered.status()).toBe(201)
  const memory = await remembered.json()
  const query = { project_id: document.project_id, subject_type: 'project', subject_id: document.project_id, predicate: 'owner' }
  const known = await page.request.post('/api/memory/facts/query', { data: query })
  expect((await known.json()).outcome).toBe('known')

  await page.goto(`/knowledge?project=${encodeURIComponent(document.project_id)}&memory=${encodeURIComponent(memory.id)}`)
  const detail = page.getByRole('dialog')
  await expect(detail.getByRole('heading', { name: body.title })).toBeVisible()
  const structured = detail.getByRole('region', { name: '结构化记忆' })
  await expect(structured.getByText('Bob', { exact: true })).toBeVisible()
  await expect(structured.getByText('人类确认', { exact: true })).toBeVisible()
  await expect(structured.getByText('有效时间：', { exact: true })).toBeVisible()
  await expect(structured.getByText('记录时间：', { exact: true })).toBeVisible()
  await expect(structured.getByRole('list', { name: '事实证据' })).toContainText(document.id)

  const conflicting = await page.request.post('/api/memory/facts/remember', { data: {
    ...body, command_id: `${command}-conflict`, facts: [{ ...body.facts[0], value: 'Alice' }],
  } })
  expect(conflicting.status()).toBe(201)
  const result = await page.request.post('/api/memory/facts/query', { data: query })
  const report = await result.json()
  expect(report.outcome).toBe('conflict')
  expect(report.automatic_context_eligible).toBe(false)
  expect(report.facts.map((hit: { fact: { value: string } }) => hit.fact.value).sort()).toEqual(['Alice', 'Bob'])
})
