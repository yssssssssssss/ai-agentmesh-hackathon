import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test.describe.serial('MVP governance and collaboration', () => {
  test('Brief confirmation is atomic, versioned and canonical across UI refreshes', async ({ page }) => {
    test.setTimeout(90_000)
    await loginAs(page)
    const briefResponse = await page.request.post('/api/chat/messages', {
      data: { content: `$brief.create M8 治理验证 ${Date.now()}` },
    })
    expect(briefResponse.ok()).toBeTruthy()
    const briefItem = (await briefResponse.json()).inbox_items[0]
    const documentId = briefItem.metadata.document_id
    const initialDocument = (await (await page.request.get(`/api/documents/${documentId}`)).json()).item
    const briefContent = `M8 端到端确认后的 Brief 正文 ${Date.now()}`

    const genericResolve = await page.request.patch(`/api/inbox/${briefItem.id}`, { data: { status: 'resolved' } })
    expect(genericResolve.status()).toBe(409)
    await page.goto('/knowledge')
    await page.getByRole('tab', { name: /待我确认/ }).click()
    await page.locator(`[data-inbox-item-id="${briefItem.id}"]`).getByRole('button', { name: '确认并沉淀' }).click()
    await page.getByLabel('Brief 正文').fill(briefContent)
    await page.getByRole('button', { name: '确认 Brief' }).click()
    await expect(page.getByRole('status')).toContainText('Brief 已确认', { timeout: 15_000 })

    const duplicate = await page.request.post(`/api/inbox/${briefItem.id}/confirm-brief`, {
      data: { text: briefContent, expected_document_version: initialDocument.version },
    })
    expect(duplicate.status()).toBe(409)
    const persistedDocument = (await (await page.request.get(`/api/documents/${documentId}`)).json()).item
    expect(persistedDocument.text).toBe(briefContent)
    expect(persistedDocument.version).toBe(initialDocument.version + 1)
    const resolvedInbox = (await (await page.request.get('/api/inbox?include_snoozed=true')).json()).items
      .find((item: { id: string }) => item.id === briefItem.id)
    expect(resolvedInbox.status).toBe('resolved')
    const confirmedMemoryId = resolvedInbox.metadata.confirmed_memory_id
    expect(confirmedMemoryId).toMatch(/^mem_/)

    const staleResponse = await page.request.post('/api/chat/messages', {
      data: { content: `$brief.create M8 冲突输入保留验证 ${Date.now()}` },
    })
    const staleItem = (await staleResponse.json()).inbox_items[0]
    const staleDocumentId = staleItem.metadata.document_id
    const staleDocument = (await (await page.request.get(`/api/documents/${staleDocumentId}`)).json()).item
    const losingDraft = `M8 应保留的失败输入 ${Date.now()}`
    const concurrentText = `M8 服务端并发正文 ${Date.now()}`
    await page.reload()
    await page.locator(`[data-inbox-item-id="${staleItem.id}"]`).getByRole('button', { name: '确认并沉淀' }).click()
    await page.getByLabel('Brief 正文').fill(losingDraft)
    expect((await page.request.patch(`/api/documents/${staleDocumentId}`, {
      data: { text: concurrentText, expected_version: staleDocument.version },
    })).ok()).toBeTruthy()
    await page.getByRole('button', { name: '确认 Brief' }).click()
    await expect(page.getByRole('alert')).toContainText('状态已被其他操作更新')
    await expect(page.getByLabel('Brief 正文')).toHaveValue(losingDraft)
    const canonicalAfterConflict = (await (await page.request.get(`/api/documents/${staleDocumentId}`)).json()).item
    expect(canonicalAfterConflict.text).toBe(concurrentText)
    expect(canonicalAfterConflict.version).toBe(staleDocument.version + 1)
    const staleInbox = (await (await page.request.get('/api/inbox?include_snoozed=true')).json()).items
      .find((item: { id: string }) => item.id === staleItem.id)
    expect(staleInbox.status).toBe('open')
    expect(staleInbox.metadata.confirmed_memory_id).toBeUndefined()
    await page.getByRole('button', { name: '取消' }).click()

    const snoozeResponse = await page.request.post('/api/chat/messages', {
      data: { content: `$brief.create M8 稍后处理验证 ${Date.now()}` },
    })
    const snoozeItem = (await snoozeResponse.json()).inbox_items[0]
    await page.reload()
    await page.locator(`[data-inbox-item-id="${snoozeItem.id}"]`).getByRole('button', { name: '稍后处理' }).click()
    await expect(page.getByRole('status')).toContainText('已稍后处理')
    await page.reload()
    await expect(page.locator(`[data-inbox-item-id="${snoozeItem.id}"]`)).toContainText('已稍后处理')
    expect((await page.request.patch(`/api/inbox/${snoozeItem.id}`, { data: { status: 'resolved' } })).status()).toBe(409)

    await page.getByRole('button', { name: '退出登录' }).click()
    await loginAs(page, 'usr_team_lead', 'lead123')
    const candidateById = (await (await page.request.get('/api/memory')).json()).items
      .filter((item: { id: string }) => item.id === confirmedMemoryId)
    expect(candidateById).toHaveLength(1)
    await page.goto('/knowledge')
    await page.getByRole('tab', { name: /待我确认/ }).click()
    const candidate = page.locator('article').filter({ hasText: briefContent }).first()
    await candidate.getByRole('button', { name: '接受候选' }).click()
    await expect(page.getByRole('status')).toContainText('团队候选已接受')
    await page.reload()
    await page.getByRole('tab', { name: /已沉淀知识/ }).click()
    await expect(page.getByText(briefContent).first()).toBeVisible()
  })

  test('task reply, personal lock/unlock/handoff and market participation persist', async ({ page }) => {
    test.setTimeout(90_000)
    await loginAs(page)
    const taskMarker = `M8-collaboration-${Date.now()}`
    const taskResponse = await page.request.post('/api/chat/messages', {
      data: { content: `$research.request ${taskMarker}` },
    })
    expect(taskResponse.ok()).toBeTruthy()
    const taskPayload = await taskResponse.json()
    const task = taskPayload.task

    await page.goto('/collaboration')
    await page.getByRole('tab', { name: /我的申请/ }).click()
    const card = page.locator(`[data-task-id="${task.id}"]`)
    await card.getByRole('button', { name: '查看协作详情' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('这次协作是如何发生的')

    const replyText = `M8 协作回复证据 ${Date.now()}`
    const currentResult = '证据已补充'
    const doneWhen = '下一位 owner 完成复核'
    const nextOwner = '组长 Agent'
    const replyEndpoint = '**/api/blackboard/posts/*/reply'
    await page.route(replyEndpoint, (route) => route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Transient collaboration failure' }),
    }))
    await dialog.getByLabel('回复任务').fill(replyText)
    await dialog.getByRole('button', { name: '发送回复' }).click()
    await expect(dialog.getByRole('alert')).toContainText('Transient collaboration failure')
    await expect(dialog.getByLabel('回复任务')).toHaveValue(replyText)
    await page.unroute(replyEndpoint)
    await dialog.getByRole('button', { name: '发送回复' }).click()
    await expect(dialog.getByRole('status')).toContainText('回复已保存')
    await dialog.getByRole('button', { name: '锁定给我的数字分身' }).click()
    await expect(dialog.getByRole('status')).toContainText('取得执行锁')
    await dialog.getByRole('button', { name: '释放执行锁' }).click()
    await expect(dialog.getByRole('status')).toContainText('执行锁已释放')
    await dialog.getByRole('button', { name: '锁定给我的数字分身' }).click()
    await dialog.getByLabel('下一位负责人').selectOption({ label: nextOwner })
    await dialog.getByLabel('当前结果').fill(currentResult)
    await dialog.getByLabel('完成条件').fill(doneWhen)
    await dialog.getByRole('button', { name: '确认交接' }).click()
    await expect(dialog.getByRole('status')).toContainText('任务已交接')

    await page.reload()
    await page.getByRole('tab', { name: /我的申请/ }).click()
    const persistedCard = page.locator(`[data-task-id="${task.id}"]`)
    await persistedCard.getByRole('button', { name: '查看协作详情' }).click()
    const persistedDialog = page.getByRole('dialog')
    await expect(persistedDialog.getByText(replyText, { exact: true })).toBeVisible()
    await expect(persistedDialog.getByText(nextOwner, { exact: true }).first()).toBeVisible()
    await expect(persistedDialog.getByText(doneWhen, { exact: true }).first()).toBeVisible()
    await expect(persistedDialog.getByRole('heading', { name: '任务交接', exact: true })).toBeVisible()
    await expect(persistedDialog.getByText(`当前结果：${currentResult}。`, { exact: false })).toBeVisible()
    await expect(persistedDialog.getByText(/执行锁：/)).toHaveCount(0)
    await persistedDialog.getByRole('button', { name: '关闭' }).click()

    const initialParticipationResponse = await page.request.get('/api/market/participation')
    expect(initialParticipationResponse.ok()).toBeTruthy()
    const initialParticipation = await initialParticipationResponse.json()
    const initialParticipationLabel = initialParticipation.enabled ? '退出市场' : '加入市场'
    const persistedParticipationLabel = initialParticipation.enabled ? '加入市场' : '退出市场'
    await expect(page.getByRole('heading', { name: '组织协作参与者' })).toBeVisible()
    const participation = page.getByRole('button', { name: initialParticipationLabel, exact: true })
    await participation.click()
    await expect(page.getByRole('status')).toContainText(/已加入协作市场|已退出协作市场/)
    await expect(page.getByRole('button', { name: persistedParticipationLabel, exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('button', { name: persistedParticipationLabel, exact: true })).toBeVisible()
    const persistedParticipationResponse = await page.request.get('/api/market/participation')
    expect(persistedParticipationResponse.ok()).toBeTruthy()
    expect((await persistedParticipationResponse.json()).enabled).toBe(!initialParticipation.enabled)
  })

  test('unauthorized task action is absent and direct API is denied', async ({ page }) => {
    await loginAs(page, 'usr_team_lead', 'lead123')
    const created = await page.request.post('/api/chat/messages', {
      data: { content: `$research.request M8 隐藏协作 ${Date.now()}` },
    })
    const payload = await created.json()
    const task = payload.task
    const post = payload.request_post
    await page.getByRole('button', { name: '退出登录' }).click()
    await loginAs(page)

    await page.goto('/collaboration')
    await expect(page.getByText(task.title, { exact: true })).toHaveCount(0)
    const denied = await page.request.post(`/api/blackboard/posts/${post.id}/reply`, {
      data: { post_type: 'evidence', title: 'Unauthorized', content: 'Must be denied' },
    })
    expect(denied.status()).toBe(404)
  })
})
