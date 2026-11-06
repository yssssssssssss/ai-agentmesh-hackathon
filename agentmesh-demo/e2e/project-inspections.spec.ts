import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test('inspects real task changes and blockers and follows the source without mutating it', async ({ page }) => {
  await loginAs(page, 'usr_team_lead', 'lead123')
  const me = await page.request.get('/api/auth/me')
  expect(me.ok(), await me.text()).toBeTruthy()
  const projectId = (await me.json()).user.default_project_id
  const created = await page.request.post('/api/tasks', { data: {
    command_id: 'e2e-inspection-task', title: '巡检验收：等待上游材料',
    due_at: new Date(Date.now() - 86_400_000).toISOString(),
  } })
  expect(created.status(), await created.text()).toBe(201)
  const task = (await created.json()).item
  const blocked = await page.request.post(`/api/tasks/${task.task.id}/transitions`, { data: {
    command_id: 'e2e-inspection-block', expected_version: task.management.version,
    action: 'block', reason: '尚未收到上游材料',
  } })
  expect(blocked.ok(), await blocked.text()).toBeTruthy()
  const blockedTask = (await blocked.json()).item
  const currentState = await page.request.get(`/api/task-operations/${projectId}/state?task_id=${task.task.id}`)
  expect(currentState.ok(), await currentState.text()).toBeTruthy()
  const state = await currentState.json()
  expect(state.data_mode).toBe('real')
  expect(state.actual_providers).toEqual(['local_task_store'])
  expect(state.task.version).toBe(blockedTask.management.version)
  expect(state.task.blocked_reason).toBe('尚未收到上游材料')
  expect(state.blocked_task_count).toBeGreaterThanOrEqual(1)
  expect(state.task_count).toBe(Object.values(state.tasks_by_stage).reduce<number>((total, count) => total + Number(count), 0))
  expect(state.task.navigation_href).toBe(`/tasks?task=${task.task.id}`)

  await page.goto('/tasks')
  const panel = page.getByRole('region', { name: '项目巡检' })
  await panel.getByRole('button', { name: '阻塞与逾期', exact: true }).click()
  await expect(panel.getByText('真实项目数据')).toBeVisible()
  await expect(panel.getByText('尚未收到上游材料')).toBeVisible()
  await expect(panel.getByRole('link', { name: task.task.title, exact: true })).toBeVisible()

  await panel.getByRole('button', { name: '每日进展', exact: true }).click()
  await expect(panel.getByText('进展变化', { exact: false })).toBeVisible()
  await expect(panel.getByText(/阻塞 · .* · v2/)).toBeVisible()
  const unchanged = await page.request.get(`/api/tasks/${task.task.id}`)
  expect((await unchanged.json()).item.management.version).toBe(blockedTask.management.version)

  await panel.getByRole('button', { name: '待审核', exact: true }).click()
  await expect(panel.getByText('来源记录与查询范围')).toBeVisible()
  await page.setViewportSize({ width: 375, height: 812 })
  await panel.getByRole('button', { name: '阻塞与逾期', exact: true }).click()
  await expect(panel.getByText('尚未收到上游材料')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(overflow).toBeFalsy()
  await panel.getByRole('link', { name: task.task.title, exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`task=${task.task.id}`))
  await expect(page.getByRole('dialog')).toBeVisible()
})
