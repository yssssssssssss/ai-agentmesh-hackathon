import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

const naturalMessage = `workspace-natural-${Date.now()}`
const researchMarker = `workspace-source-${Date.now()}`

test.beforeEach(async ({ page }) => {
  await loginAs(page)
  await page.getByRole('link', { name: 'AI 工作台' }).click()
  await expect(page.getByRole('heading', { name: 'AI 工作台' })).toBeVisible()
})

test('creates, selects, sends natural and explicit skill messages, and reloads persisted history', async ({ page }) => {
  await page.getByRole('button', { name: '开始新对话' }).click()
  const composer = page.getByLabel('消息')
  await composer.fill(naturalMessage)
  const firstSendResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/chat/messages') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '发送' }).click()
  const firstSend = await firstSendResponse
  const firstRequest = firstSend.request().postDataJSON() as {
    thread_id: string | null
    client_turn_id: string
  }
  const firstTurn = await firstSend.json() as { thread_id: string }
  expect(firstSend.status()).toBe(200)
  expect(firstRequest.thread_id).toBeNull()
  expect(firstRequest.client_turn_id).toMatch(/^[0-9a-f-]{36}$/)
  await expect(page).toHaveURL(new RegExp(`/workspace/thread/${firstTurn.thread_id}$`))

  const userMessage = page.getByTestId('user-message').filter({ hasText: naturalMessage })
  const assistantMessage = page.getByTestId('assistant-message').last()
  await expect(userMessage).toBeVisible()
  await expect(assistantMessage).toBeVisible({ timeout: 15_000 })
  const [userMaxWidth, assistantMaxWidth] = await Promise.all([
    userMessage.evaluate((element) => getComputedStyle(element).maxWidth),
    assistantMessage.evaluate((element) => getComputedStyle(element).maxWidth),
  ])
  expect(userMaxWidth).toBe(assistantMaxWidth)
  expect(userMaxWidth).not.toBe('none')
  await expect(page.getByTestId('workspace-composer')).toHaveCSS('max-width', '992px')
  await expect(page.getByTestId('provider-provenance')).toContainText(/请求提供方/)
  await expect(page.getByTestId('provider-provenance')).toContainText(/实际提供方/)
  await expect(page.getByRole('button', { name: naturalMessage, exact: true })).toBeVisible()

  await page.getByRole('button', { name: '选择 Skill' }).click()
  await page.getByRole('button', { name: /^\$research\.request 请求外部资料/ }).click()
  await expect(composer).toHaveValue('$research.request ')
  await composer.fill(`$research.request ${researchMarker}`)
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByTestId('user-message').filter({ hasText: `$research.request ${researchMarker}` })).toBeVisible()
  await expect(page.getByTestId('provider-provenance').last()).toContainText(/实际提供方.*(mock|o2|web_research)/)
  await expect(page.getByRole('button', { name: /2025 618 家电会场复盘/ })).toBeVisible()

  await page.reload()
  await expect(page.getByTestId('user-message').filter({ hasText: naturalMessage })).toBeVisible()
  await expect(page.getByTestId('user-message').filter({ hasText: `$research.request ${researchMarker}` })).toBeVisible()
  await expect(page.getByTestId('provider-provenance').last()).toContainText(/请求提供方.*research/)
  await expect(page.getByTestId('provider-provenance').last()).toContainText(/实际提供方.*(mock|o2|web_research)/)

  await page.getByRole('button', { name: '开始新对话' }).click()
  await expect(page.getByText('选择一个对话，或发送第一条消息开始。')).toBeVisible()
  await page.getByRole('button', { name: naturalMessage, exact: true }).click()
  await expect(page.getByTestId('user-message').filter({ hasText: naturalMessage })).toBeVisible()
})

test('manages existing tasks from the compact actions menu', async ({ page }) => {
  const marker = Date.now()
  const firstTitle = `待置顶任务-${marker}`
  const secondTitle = `待删除任务-${marker}`
  const renamedTitle = `已重命名任务-${marker}`
  const createThread = async (title: string) => {
    const response = await page.request.post('/api/chat/threads', { data: { title } })
    expect(response.status()).toBe(200)
    return (await response.json()).thread as { id: string }
  }
  const first = await createThread(firstTitle)
  const second = await createThread(secondTitle)
  await page.reload()

  await expect(page.getByRole('button', { name: firstTitle, exact: true })).toHaveCSS('font-size', '12px')

  const firstMenuTrigger = page.getByRole('button', { name: `更多任务操作：${firstTitle}` })
  await firstMenuTrigger.focus()
  await firstMenuTrigger.press('Enter')
  const menu = page.getByRole('menu', { name: `任务操作：${firstTitle}` })
  await expect(menu.getByRole('menuitem')).toHaveCount(3)
  await expect(menu.getByRole('menuitem', { name: '置顶', exact: true })).toBeFocused()
  await page.keyboard.press('ArrowDown')
  await expect(menu.getByRole('menuitem', { name: '重命名', exact: true })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(firstMenuTrigger).toBeFocused()

  await firstMenuTrigger.click()
  const pinResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/api/chat/threads/${first.id}`)
    && response.request().method() === 'PATCH',
  )
  await page.getByRole('menuitem', { name: '置顶', exact: true }).click()
  expect((await pinResponse).status()).toBe(200)
  await expect(page.getByTestId('conversation-task').first()).toHaveAttribute('data-thread-id', first.id)
  await expect(page.getByTestId('conversation-task').first().getByLabel('已置顶')).toBeVisible()

  await page.getByRole('button', { name: `更多任务操作：${firstTitle}` }).click()
  await expect(page.getByRole('menuitem', { name: '取消置顶', exact: true })).toBeVisible()
  await page.getByRole('menuitem', { name: '重命名', exact: true }).click()
  const renameInput = page.getByRole('textbox', { name: `重命名任务：${firstTitle}` })
  await expect(renameInput).toBeFocused()
  await renameInput.fill(renamedTitle)
  const renameResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/api/chat/threads/${first.id}`)
    && response.request().method() === 'PATCH',
  )
  await page.getByRole('button', { name: '保存任务名称' }).click()
  expect((await renameResponse).status()).toBe(200)
  await expect(page.getByRole('button', { name: renamedTitle, exact: true })).toBeVisible()

  await page.reload()
  await expect(page.getByTestId('conversation-task').first()).toHaveAttribute('data-thread-id', first.id)
  await expect(page.getByRole('button', { name: renamedTitle, exact: true })).toBeVisible()

  await page.getByRole('button', { name: `更多任务操作：${secondTitle}` }).click()
  await page.getByRole('menuitem', { name: '删除', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '删除任务？' })
  await expect(dialog).toContainText(secondTitle)
  const deleteResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/api/chat/threads/${second.id}`)
    && response.request().method() === 'DELETE',
  )
  await dialog.getByRole('button', { name: '删除任务' }).click()
  expect((await deleteResponse).status()).toBe(204)
  await expect(page.getByRole('button', { name: secondTitle, exact: true })).toHaveCount(0)
  expect((await page.request.get(`/api/chat/threads/${second.id}`)).status()).toBe(404)
})

test('persists the seeded 618 demo conversation and replies on the same thread', async ({ page }) => {
  await page.goto('/workspace/thread/thread_graph_demo')
  await expect(page.getByRole('heading', { name: '2026 年 618 家电会场首页改版' })).toBeVisible()
  await expect(page.getByTestId('user-message').filter({ hasText: '我要做今年 618 家电会场首页改版' })).toBeVisible()
  await expect(page.getByTestId('assistant-message').filter({ hasText: '首屏应优先保证核心入口效率' })).toBeVisible()
  await expect(page.getByTestId('assistant-message').filter({ hasText: '2026 年 618 家电会场首页设计 Brief' })).toBeVisible()
  await expect(page.getByTestId('assistant-message').filter({ hasText: '技术执行记录' })).toBeVisible()
  await expect(page.getByRole('button', { name: '团队经验：首屏核心入口优先' })).toBeVisible()

  const reply = `graph-demo-reply-${Date.now()}`
  const sendResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/chat/messages') && response.request().method() === 'POST',
  )
  await page.getByLabel('消息').fill(reply)
  await page.getByRole('button', { name: '发送' }).click()
  const sent = await sendResponse
  const request = sent.request().postDataJSON() as { thread_id: string | null }

  expect(sent.status()).toBe(200)
  expect(request.thread_id).toBe('thread_graph_demo')
  await expect(page.getByTestId('user-message').filter({ hasText: reply })).toBeVisible()

  await page.reload()
  await expect(page.getByTestId('user-message').filter({ hasText: reply })).toBeVisible()
})

test('shows pending immediately, follows conversation updates, and opens skills from dollar prefix', async ({ page }) => {
  const threadId = 'thread_workspace_regression'
  const marker = `workspace-regression-${Date.now()}`
  const messages = Array.from({ length: 18 }, (_, index) => ({
    id: `msg_workspace_regression_${index}`,
    thread_id: threadId,
    role: index % 2 === 0 ? 'user' : 'assistant',
    content: `历史消息 ${index} ${'用于撑开对话滚动区域。'.repeat(8)}`,
    scope: 'private',
    sources: [],
    created_at: new Date(Date.now() - (18 - index) * 1000).toISOString(),
  }))
  await page.route(`**/api/chat/threads/${threadId}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        thread: {
          id: threadId,
          workspace_id: 'ws_home_appliance_design',
          project_id: 'prj_618_home_appliance',
          user_id: 'usr_current_designer',
          title: 'Workspace 回归测试',
          status: 'active',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        messages,
        turn_traces: [],
      }),
    }),
  )
  let releaseSend = () => {}
  const sendGate = new Promise<void>((resolve) => {
    releaseSend = resolve
  })
  await page.route('**/api/chat/messages', async (route) => {
    await sendGate
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{"detail":"delayed regression response"}',
    })
  })

  await page.goto(`/workspace/thread/${threadId}`)
  await expect(page.getByText('Workspace 回归测试', { exact: true })).toBeVisible()
  const scrollContainer = page.locator('div.min-w-0.flex-1.overflow-y-auto').first()
  await scrollContainer.evaluate((element) => {
    element.scrollTop = 0
  })
  const composer = page.getByLabel('消息')

  await composer.fill('$')
  await expect(page.getByRole('button', { name: /^\$memory\.search 查询记忆\/经验/ })).toBeVisible()

  await composer.fill(marker)
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText(marker, { exact: true })).toBeVisible()
  await expect(page.getByText('正在发送…', { exact: true })).toBeVisible()
  await expect.poll(() => scrollContainer.evaluate(
    (element) => Math.abs(element.scrollHeight - element.clientHeight - element.scrollTop) <= 2,
  )).toBe(true)

  releaseSend()
  await expect(page.getByRole('alert')).toContainText('服务端未收到本次请求')
})


test('renders requested and actual model provenance after reload', async ({ page }) => {
  const marker = `workspace-model-provenance-${Date.now()}`
  const modelFields = {
    requested_model: 'GPT-5.2-joybuilder',
    actual_model: 'DeepSeek-V4-Flash',
    model_fallback_reason: 'timeout',
    llm_used: true,
    provider_mode: 'fallback',
  }
  await page.route('**/api/chat/messages', async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.workflow_trace = { ...payload.workflow_trace, ...modelFields }
    payload.assistant_message.workflow_trace = { ...payload.assistant_message.workflow_trace, ...modelFields }
    await route.fulfill({ response, json: payload })
  })
  await page.route('**/api/chat/threads/*', async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    payload.messages = payload.messages.map((message: { role: string; workflow_trace?: object }) =>
      message.role === 'assistant'
        ? { ...message, workflow_trace: { ...message.workflow_trace, ...modelFields } }
        : message,
    )
    await route.fulfill({ response, json: payload })
  })

  await page.getByRole('button', { name: '开始新对话' }).click()
  await page.getByLabel('消息').fill(marker)
  await page.getByRole('button', { name: '发送' }).click()
  const provenance = page.getByTestId('provider-provenance').last()
  await expect(provenance).toContainText('请求模型GPT-5.2-joybuilder')
  await expect(provenance).toContainText('实际模型DeepSeek-V4-Flash')
  await expect(provenance).toContainText('模型切换原因timeout')

  await page.reload()
  const reloaded = page.getByTestId('provider-provenance').last()
  await expect(reloaded).toContainText('请求模型GPT-5.2-joybuilder')
  await expect(reloaded).toContainText('实际模型DeepSeek-V4-Flash')
  await expect(reloaded).toContainText('模型切换原因timeout')
})

test('handles synchronous upload, queued own job, search source, and stable document detail', async ({ page }) => {
  const uploadInput = page.getByLabel('上传文档')
  const syncFileName = `workspace-source-${researchMarker}.txt`
  const queuedFileName = `workspace-large-source-${researchMarker}.txt`
  await uploadInput.setInputFiles({
    name: syncFileName,
    mimeType: 'text/plain',
    buffer: Buffer.from(`${researchMarker}\nThis source belongs to the signed-in user.`),
  })
  await expect(page.getByTestId('upload-status')).toContainText(syncFileName)
  await expect(page.getByTestId('upload-status')).toContainText(/已导入|完成/)

  const queuedUploadResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/documents/upload') && response.request().method() === 'POST',
  )
  await uploadInput.setInputFiles({
    name: queuedFileName,
    mimeType: 'text/plain',
    buffer: Buffer.from(`${researchMarker}\nqueued workspace source `.repeat(10)),
  })
  const queuedUpload = await queuedUploadResponse
  const queuedPayload = await queuedUpload.json() as {
    job: { id: string; file_name: string; status: string }
  }
  expect(queuedUpload.status()).toBe(202)
  expect(queuedPayload.job.id).toBeTruthy()
  expect(queuedPayload.job.file_name).toBe(queuedFileName)
  expect(queuedPayload.job.status).toBe('queued')

  let completedJob: {
    id: string
    status: string
    document_id?: string | null
    completed_chunks: number
    expected_chunks: number
  } | null = null
  await expect.poll(async () => {
    const response = await page.request.get(`/api/documents/jobs/${queuedPayload.job.id}`)
    expect(response.status()).toBe(200)
    completedJob = (await response.json()).item
    return completedJob?.status
  }, { timeout: 30_000 }).toBe('completed')
  expect(completedJob).not.toBeNull()
  expect(completedJob!.id).toBe(queuedPayload.job.id)
  expect(completedJob!.document_id).toBeTruthy()
  expect(completedJob!.expected_chunks).toBeGreaterThan(0)
  expect(completedJob!.completed_chunks).toBe(completedJob!.expected_chunks)
  const completedDocument = await page.request.get(`/api/documents/${completedJob!.document_id}`)
  expect(completedDocument.status()).toBe(200)
  const completedDocumentPayload = await completedDocument.json()
  expect(completedDocumentPayload.item.id).toBe(completedJob!.document_id)
  expect(completedDocumentPayload.item.completed_chunks).toBe(completedJob!.completed_chunks)

  const job = page.getByTestId('document-job').filter({ hasText: queuedFileName }).first()
  await expect(job).toContainText('完成')
  await expect(job).toContainText(`${completedJob!.completed_chunks}/${completedJob!.expected_chunks} chunks`)

  await page.getByLabel('搜索资料').fill(researchMarker)
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  const result = page
    .getByTestId('search-result')
    .filter({ hasText: syncFileName })
    .filter({ has: page.getByRole('button', { name: '查看详情' }) })
    .first()
  await expect(result).toContainText(/document|文档/)
  await result.getByRole('button', { name: '查看详情' }).click()
  const detail = page.getByRole('dialog', { name: '资源详情' })
  await expect(detail).toContainText(syncFileName)
  await expect(detail).toContainText('This source belongs to the signed-in user.')
})

test('reconciles a failed new-thread send before retrying the same client turn', async ({ page }) => {
  let firstClientTurnId = ''
  let failNextSend = true
  await page.route('**/api/chat/messages', async (route) => {
    if (route.request().method() === 'POST' && failNextSend) {
      const payload = route.request().postDataJSON() as { client_turn_id: string }
      firstClientTurnId = payload.client_turn_id
      failNextSend = false
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: '{"detail":"Provider unavailable"}',
      })
      return
    }
    await route.continue()
  })
  const draft = 'retry-after-provider-failure'
  const composer = page.getByLabel('消息')
  await composer.fill(draft)
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByRole('alert')).toContainText('服务端未收到本次请求')
  await expect(composer).toHaveValue(draft)
  await expect(page.getByRole('button', { name: '重试发送' })).toBeVisible()
  expect(firstClientTurnId).toBeTruthy()

  const retryResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/chat/messages') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '重试发送' }).click()
  const retried = await retryResponse
  const retryPayload = retried.request().postDataJSON() as { client_turn_id: string }
  expect(retried.status()).toBe(200)
  expect(retryPayload.client_turn_id).toBe(firstClientTurnId)
  await expect(page.getByTestId('user-message').filter({ hasText: draft })).toHaveCount(1)
  await expect(page.getByTestId('assistant-message')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('renders a failed import job separately from successful queued completion', async ({ page }) => {
  const failedFileName = `workspace-failed-${Date.now()}.txt`
  const failedJob = {
    id: `doc_job_failed_${Date.now()}`,
    file_name: failedFileName,
    content_type: 'text/plain',
    workspace_id: 'ws_home_appliance_design',
    project_id: 'prj_618_home_appliance',
    uploaded_by: 'usr_current_designer',
    status: 'failed',
    document_id: null,
    version: 1,
    expected_chunks: 2,
    completed_chunks: 1,
    error: 'Injected parser failure',
    error_type: 'RuntimeError',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
  await page.route('**/api/documents/jobs', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [failedJob] }) }),
  )
  await page.route('**/api/documents/upload', (route) =>
    route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ job: { ...failedJob, status: 'queued', completed_chunks: 0, error: null } }),
    }),
  )

  await page.reload()
  await expect(page.getByRole('heading', { name: 'AI 工作台' })).toBeVisible()

  await page.getByLabel('上传文档').setInputFiles({
    name: failedFileName,
    mimeType: 'text/plain',
    buffer: Buffer.from('failure rendering fixture'.repeat(10)),
  })
  const failed = page.getByTestId('document-job').filter({ hasText: failedFileName })
  await expect(failed).toContainText('失败')
  await expect(failed.getByRole('alert')).toHaveText('Injected parser failure')
  await expect(failed).toContainText('1/2 chunks')
})
