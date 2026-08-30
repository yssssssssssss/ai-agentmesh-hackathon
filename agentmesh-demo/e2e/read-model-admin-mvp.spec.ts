import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

function responseItemId(payload: unknown): string {
  if (
    payload && typeof payload === 'object' && 'item' in payload &&
    payload.item && typeof payload.item === 'object' && 'id' in payload.item &&
    typeof payload.item.id === 'string'
  ) return payload.item.id
  throw new Error('Expected response item id')
}

test('Digital Self and Insights use real scoped read-model handlers', async ({ page }) => {
  await loginAs(page, 'usr_admin', 'admin123')
  const projectResponse = await page.request.post('/api/projects', {
    data: {
      workspace_id: 'ws_home_appliance_design',
      name: `Read model isolation ${Date.now()}`,
      goal: 'Verify non-member read-model isolation',
    },
  })
  expect(projectResponse.status()).toBe(200)
  const restrictedProjectId = responseItemId(await projectResponse.json())

  await loginAs(page)
  for (const path of [
    `/api/activity/today?project_id=${restrictedProjectId}`,
    `/api/blackboard/task-cards?project_id=${restrictedProjectId}`,
    `/api/insights/audit?project_id=${restrictedProjectId}`,
  ]) {
    expect((await page.request.get(path)).status()).toBe(404)
  }

  const postResponse = await page.request.post('/api/blackboard/posts', {
    data: {
      post_type: 'request',
      title: 'E2E active personal task',
      content: 'Exercise canonical runtime hydration through real HTTP handlers.',
      scope: 'project',
      permission: 'project_visible',
    },
  })
  expect(postResponse.status()).toBe(200)
  const postId = responseItemId(await postResponse.json())
  expect((await page.request.post(`/api/blackboard/posts/${postId}/lock`, {
    data: { owner_agent_id: 'agent_personal_current' },
  })).status()).toBe(200)

  await page.goto('/digital-self')
  await expect(page.getByRole('heading', { level: 1, name: /何云深/ })).toBeVisible()
  await expect(page.getByText('我的个人 Agent')).toBeVisible()
  await expect(page.getByText('online', { exact: true })).toBeVisible()
  await expect(page.getByText('E2E active personal task')).toBeVisible()

  await page.getByRole('link', { name: '工作洞察' }).click()
  await expect(page.getByRole('heading', { name: '工作洞察' })).toBeVisible()
  await page.getByRole('heading', { name: '当前项目原始读模型' }).click()
  await expect(page.getByRole('heading', { name: '当前任务卡片', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '活动记录', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '项目记忆', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '最近审计', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^(今日|本周|本月)$/ })).toHaveCount(0)
})

test('regular user is denied Admin UI and direct Admin APIs', async ({ page }) => {
  await loginAs(page)

  const deniedReads = await Promise.all([
    page.request.get('/api/users'),
    page.request.get('/api/agents'),
    page.request.get('/api/agents/agent_research/tools'),
    page.request.get('/api/users/permission-policies'),
    page.request.get('/api/risk/policies'),
    page.request.get('/api/health/providers'),
    page.request.get('/api/integrations/o2/status'),
    page.request.get('/api/audit'),
  ])
  expect(deniedReads.map((response) => response.status())).toEqual(Array(deniedReads.length).fill(403))
  const deniedMutation = await page.request.post('/api/users', {
    data: { name: '越权用户', role: 'user', password: 'blocked-pass-123' },
  })
  expect(deniedMutation.status()).toBe(403)

  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: '无权访问' })).toBeVisible()
  await expect(page.getByText('当前账号没有可用的管理能力。')).toBeVisible()
})

test('Team Lead can use granted Agent module but is denied unrelated Admin APIs', async ({ page }) => {
  await loginAs(page, 'usr_team_lead', 'lead123')

  const agents = await page.request.get('/api/agents')
  const grants = await page.request.get('/api/agents/agent_research/tools')
  expect(agents.status()).toBe(200)
  expect(grants.status()).toBe(200)
  const deniedReads = await Promise.all([
    page.request.get('/api/users'),
    page.request.get('/api/users/permission-policies'),
    page.request.get('/api/risk/policies'),
    page.request.get('/api/health/providers'),
    page.request.get('/api/integrations/o2/status'),
    page.request.get('/api/audit'),
  ])
  expect(deniedReads.map((response) => response.status())).toEqual(Array(deniedReads.length).fill(403))

  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: '管理控制台' })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Agent 配置' })).toBeVisible()
  await page.getByRole('button', { name: /^research_agent 公共/ }).click()
  await expect(page.getByRole('heading', { name: 'research_agent', exact: true })).toBeVisible()
  await expect(page.getByRole('tab', { name: '用户管理' })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Provider 与 O2' })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: '策略只读' })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: '审计日志' })).toHaveCount(0)
})

test('Admin lifecycle, audit filters, and diagnostics use persisted backend state', async ({ page, request }, testInfo) => {
  const suffix = `${Date.now()}-${testInfo.workerIndex}`
  const memberName = `服务端新成员-${suffix}`
  const initialPassword = `initial-${suffix}-pass`
  const resetPassword = `reset-${suffix}-pass`

  await loginAs(page, 'usr_admin', 'admin123')
  await page.goto('/admin')

  await page.getByRole('button', { name: '创建用户' }).click()
  const nameInput = page.getByLabel('姓名')
  await nameInput.click()
  await nameInput.pressSequentially(memberName, { delay: 5 })
  await expect(nameInput).toBeFocused()
  await expect(nameInput).toHaveValue(memberName)
  await page.getByLabel('初始密码').fill(initialPassword)
  const createResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith('/api/users') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '确认创建' }).click()
  const createResponse = await createResponsePromise
  expect(createResponse.status()).toBe(200)
  const createdUser = (await createResponse.json()).item as { id: string }
  const createdRow = page.getByRole('row', { name: new RegExp(memberName) })
  await expect(createdRow).toBeVisible()

  await createdRow.getByRole('button', { name: '重置密码' }).click()
  await page.getByLabel('新密码').fill(resetPassword)
  const resetResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith(`/api/users/${createdUser.id}/password`) && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '确认重置' }).click()
  expect((await resetResponsePromise).status()).toBe(200)
  const resetLogin = await request.post('/api/auth/login', {
    data: { user_id: createdUser.id, password: resetPassword },
  })
  expect(resetLogin.status()).toBe(200)

  await createdRow.getByRole('button', { name: '禁用' }).click()
  await expect(createdRow.getByText('disabled', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('row', { name: new RegExp(memberName) }).getByText('disabled', { exact: true })).toBeVisible()
  const disabledLogin = await request.post('/api/auth/login', {
    data: { user_id: createdUser.id, password: resetPassword },
  })
  expect(disabledLogin.status()).toBe(401)

  const providerResponse = await page.request.get('/api/health/providers')
  expect(providerResponse.status()).toBe(200)
  const providerPayload = await providerResponse.json()
  const providerJson = JSON.stringify(providerPayload)
  expect(providerJson).not.toMatch(/api[_-]?key|access[_-]?token|client[_-]?secret|authorization|base_url/i)
  await page.getByRole('tab', { name: 'Provider 与 O2' }).click()
  await expect(page.getByRole('heading', { name: 'Provider diagnostics' })).toBeVisible()
  await expect(page.locator('table tbody tr').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'O2 registry' })).toBeVisible()

  await page.getByRole('tab', { name: '审计日志' }).click()
  await page.getByLabel('审计动作').fill('reset_password')
  await page.getByLabel('审计对象类型').fill('user')
  await page.getByRole('button', { name: '筛选' }).click()
  const auditRows = page.locator('table tbody tr')
  await expect(auditRows).not.toHaveCount(0)
  await expect(auditRows.first().getByText('reset_password', { exact: true })).toBeVisible()
  await expect(auditRows.first().getByText(`user · ${createdUser.id}`, { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '清除' }).click()
  await expect(page.getByLabel('审计动作')).toHaveValue('')
  await expect(page.getByLabel('审计对象类型')).toHaveValue('')
})
