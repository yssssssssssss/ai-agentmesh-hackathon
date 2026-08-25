import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test.describe.serial('read-only task center', () => {
  test('shows real task cards, keeps both status axes, filters, and opens a read-only timeline', async ({ page }) => {
    await loginAs(page)
    await page.goto('/tasks')

    await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
    await expect(page.getByText('本页只提供观察，不提供创建、编辑或分派。')).toBeVisible()
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
    await expect(page.getByText('只有现有 Agent 或协作流程产生')).toBeVisible()
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
