import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test.describe.serial('task center', () => {
  test('shows real task cards, keeps both status axes, filters, and opens a read-only timeline', async ({ page }) => {
    await loginAs(page)
    await page.goto('/tasks')

    await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
    await expect(page.getByText('管理当前项目任务；Agent 执行与项目交付状态保持独立。')).toBeVisible()
    await expect(page.getByRole('link', { name: '任务中心' })).toHaveAttribute('aria-current', 'page')
    await expect(page.getByRole('region', { name: '任务看板' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '协作完成' })).toBeVisible()
    await expect(page.locator('[data-task-id="task_graph_demo_1"]')).toContainText('执行完成')

    const taskTitle = '查询竞品首屏布局方案'
    await page.getByLabel('搜索任务').fill('不存在的任务标题')
    await expect(page.getByRole('heading', { name: '没有符合筛选的任务' })).toBeVisible()
    await page.getByLabel('筛选可见任务').getByRole('button', { name: '清除筛选' }).click()
    await page.getByLabel('搜索任务').fill('竞品首屏')
    await expect(page.getByText('1 项结果', { exact: true })).toBeVisible()
    await page.getByLabel('执行状态').selectOption('waiting_external_agent')
    await page.getByLabel('协作阶段').selectOption('blocked')
    await expect(page.locator('[data-task-id="task_graph_demo_3"]')).toBeVisible()

    await page.getByRole('button', { name: '列表', exact: true }).click()
    await expect(page.getByRole('table')).toContainText(taskTitle)
    await expect(page.getByRole('table')).toContainText('等待外部 Agent')
    await expect(page.getByRole('table')).toContainText('阻塞')

    await page.getByRole('button', { name: `查看任务：${taskTitle}` }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('只读视图，仅展示当前账号可见的任务事实')
    await expect(dialog.getByText('执行状态', { exact: true })).toBeVisible()
    await expect(dialog.getByText('协作阶段', { exact: true })).toBeVisible()
    await expect(dialog.getByRole('heading', { name: '任务步骤' })).toBeVisible()
    await expect(dialog.getByRole('heading', { name: '黑板时间线' })).toBeVisible()
    await expect(dialog.getByText('以下动态已由服务端按当前账号权限过滤。')).toBeVisible()
    await expect(dialog.getByText('修正：需补充竞品时间范围')).toBeVisible()
    await expect(dialog.getByRole('button', { name: /发送回复|确认交接|执行锁/ })).toHaveCount(0)
  })

  test('distinguishes loading from an empty visible task collection', async ({ page }) => {
    await loginAs(page)
    let releaseResponse!: () => void
    const responseGate = new Promise<void>((resolve) => {
      releaseResponse = resolve
    })
    await page.route('**/api/blackboard/task-cards?*', async (route) => {
      await responseGate
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [] }),
      })
    })

    await page.goto('/tasks')
    await expect(page.getByText('正在读取可见任务')).toBeAttached()
    releaseResponse()
    await expect(page.getByRole('heading', { name: '当前没有可见任务' })).toBeVisible()
    await expect(page.getByText('当前项目还没有可见任务。任务可以由用户创建')).toBeVisible()
  })

  test('shows a recoverable list error and retries the same real endpoint', async ({ page }) => {
    await loginAs(page)
    let attempts = 0
    await page.route('**/api/blackboard/task-cards?*', async (route) => {
      attempts += 1
      if (attempts === 1) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Task cards temporarily unavailable' }),
        })
        return
      }
      await route.continue()
    })

    await page.goto('/tasks')
    await expect(page.getByRole('alert')).toContainText('Task cards temporarily unavailable')
    await page.getByRole('button', { name: '重试', exact: true }).click()
    await expect(page.getByText('查询 618 家电会场首屏历史经验', { exact: true })).toBeVisible()
    expect(attempts).toBeGreaterThanOrEqual(2)
  })

  test('handles an unavailable detail without exposing stale content', async ({ page }) => {
    await loginAs(page)
    let attempts = 0
    await page.route('**/api/blackboard/tasks/task_graph_demo_1', async (route) => {
      attempts += 1
      if (attempts === 1) {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Task not found' }),
        })
        return
      }
      await route.continue()
    })
    await page.goto('/tasks')

    await page.getByRole('button', { name: '查看任务：查询 618 家电会场首屏历史经验' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: '无法查看该任务' })).toBeVisible()
    await expect(dialog).toContainText('任务已不存在或当前账号不可见')
    await expect(dialog.getByRole('heading', { name: '黑板时间线' })).toHaveCount(0)
    await dialog.getByRole('button', { name: '重试' }).click()
    await expect(dialog.getByRole('heading', { name: '黑板时间线' })).toBeVisible()
    await expect(dialog.getByText('摘要：首屏经验综合结论')).toBeVisible()
    expect(attempts).toBeGreaterThanOrEqual(2)
  })

  test('creates, edits, assigns, and advances a durable project task', async ({ page }) => {
    await loginAs(page)
    await page.goto('/tasks')

    await page.getByRole('button', { name: '新建任务' }).click()
    const createDialog = page.getByRole('dialog')
    await createDialog.getByLabel('任务标题').fill('验证独立任务闭环')
    await createDialog.getByLabel('任务描述').fill('不依赖外部 Provider 的项目任务')
    await createDialog.getByLabel('优先级').selectOption('p1')
    await createDialog.getByLabel('负责人').selectOption('user:usr_current_designer')
    await createDialog.getByLabel('标签').fill('standalone, task')
    await createDialog.getByRole('button', { name: '创建任务' }).click()

    const card = page.locator('[data-task-id]').filter({ hasText: '验证独立任务闭环' })
    await expect(card).toBeVisible()
    await expect(card).toContainText('待办')
    await expect(card).toContainText('P1')
    await expect(card).toContainText('协作负责人')
    await expect(card).toContainText('未指定')
    await expect(card).toContainText('交付负责人：何云深')
    await card.getByRole('button', { name: '管理' }).click()

    const editDialog = page.getByRole('dialog')
    await expect(editDialog.getByRole('heading', { name: '编辑任务' })).toBeVisible()
    await editDialog.getByLabel('任务标题').fill('验证独立任务与记忆闭环')
    await editDialog.getByRole('button', { name: '保存任务' }).click()

    const updatedCard = page.locator('[data-task-id]').filter({ hasText: '验证独立任务与记忆闭环' })
    await expect(updatedCard).toBeVisible()
    await updatedCard.getByRole('button', { name: '管理' }).click()
    await page.getByRole('dialog').getByRole('button', { name: '进入计划' }).click()
    await expect(updatedCard).toContainText('已计划')
  })

  test('reuses the browser command ID after an ambiguous create response', async ({ page }) => {
    await loginAs(page)
    const commandIds: string[] = []
    let attempts = 0
    await page.route('**/api/tasks', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.continue()
        return
      }
      attempts += 1
      commandIds.push(JSON.parse(route.request().postData() ?? '{}').command_id)
      if (attempts === 1) {
        const response = await route.fetch()
        expect(response.ok()).toBe(true)
        await route.abort('failed')
        return
      }
      await route.continue()
    })
    await page.goto('/tasks')
    await page.getByRole('button', { name: '新建任务' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('任务标题').fill('验证幂等创建')
    await dialog.getByRole('button', { name: '创建任务' }).click()
    await expect(dialog.getByRole('alert')).toBeVisible()
    await dialog.getByRole('button', { name: '创建任务' }).click()

    await expect(page.locator('[data-task-id]').filter({ hasText: '验证幂等创建' })).toHaveCount(1)
    expect(commandIds).toHaveLength(2)
    expect(commandIds[1]).toBe(commandIds[0])
  })

  test('concurrent archive converts a stale edit dialog to read-only without losing its draft', async ({ page, request }) => {
    await loginAs(page)
    await page.goto('/tasks')
    await page.getByRole('button', { name: '新建任务' }).click()
    const createDialog = page.getByRole('dialog')
    await createDialog.getByLabel('任务标题').fill('并发归档测试')
    await createDialog.getByRole('button', { name: '创建任务' }).click()
    const card = page.locator('[data-task-id]').filter({ hasText: '并发归档测试' })
    await expect(card).toBeVisible()
    const taskId = await card.getAttribute('data-task-id')
    expect(taskId).toBeTruthy()
    await card.getByRole('button', { name: '管理' }).click()
    const editDialog = page.getByRole('dialog')
    await editDialog.getByLabel('任务标题').fill('未提交的本地标题')

    const login = await request.post('/api/auth/login', {
      data: { user_id: 'usr_team_lead', password: 'lead123' },
    })
    expect(login.ok()).toBe(true)
    let version = 1
    for (const action of ['plan', 'start', 'submit_review', 'complete']) {
      const transition = await request.post(`/api/tasks/${taskId}/transitions`, {
        data: { command_id: `archive-race-${action}`, expected_version: version, action },
      })
      expect(transition.ok()).toBe(true)
      version += 1
    }
    const archive = await request.post(`/api/tasks/${taskId}/archive`, {
      data: { command_id: 'archive-race-final', expected_version: version },
    })
    expect(archive.ok()).toBe(true)

    await editDialog.getByRole('button', { name: '保存任务' }).click()
    await expect(editDialog.getByRole('alert')).toContainText('任务已在其他会话归档')
    await expect(editDialog.getByRole('status')).toContainText('该任务已归档')
    await expect(editDialog.getByLabel('任务标题')).toHaveValue('未提交的本地标题')
    await expect(editDialog.getByLabel('任务标题')).toBeDisabled()
    await expect(editDialog.getByRole('button', { name: '保存任务' })).toHaveCount(0)
  })

  test('keeps tablet and desktop task management views inside the viewport', async ({ page }) => {
    await loginAs(page)
    for (const viewport of [
      { width: 768, height: 1024 },
      { width: 1512, height: 982 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/tasks')
      await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
      await expect(page.getByRole('button', { name: '新建任务' })).toBeVisible()
      const documentMetrics = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }))
      expect(documentMetrics.scrollWidth).toBe(documentMetrics.clientWidth)
    }
  })

  test('keeps the board and drawer inside a 390px viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await loginAs(page)
    await page.goto('/tasks')

    await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
    await expect(page.getByRole('region', { name: '任务看板' })).toBeVisible()
    const documentMetrics = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }))
    expect(documentMetrics.scrollWidth).toBe(documentMetrics.clientWidth)

    await page.getByRole('button', { name: '查看任务：查询竞品首屏布局方案' }).click()
    const drawerBounds = await page.getByRole('dialog').boundingBox()
    expect(drawerBounds).not.toBeNull()
    expect(drawerBounds?.width ?? 0).toBeLessThanOrEqual(390)
    expect(drawerBounds?.x ?? -1).toBeGreaterThanOrEqual(0)
  })
})
