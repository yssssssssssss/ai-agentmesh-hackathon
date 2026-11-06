import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test('saves, edits, pauses and restores a project inspection with truthful execution status', async ({ page }) => {
  await loginAs(page, 'usr_team_lead', 'lead123')
  await page.goto('/tasks')
  const panel = page.getByRole('region', { name: '自动巡检', exact: true })
  await panel.getByRole('button', { name: '新增巡检' }).click()
  await panel.getByLabel('名称', { exact: true }).fill('自动巡检验收')
  await panel.getByLabel('巡检模板').selectOption('blockers')
  await panel.getByLabel('五段 cron').fill('* * * * *')
  await panel.getByRole('button', { name: '保存巡检' }).click()
  await expect(panel.getByRole('alert')).toContainText('最短间隔为 5 分钟')
  await panel.getByLabel('五段 cron').fill('30 9 * * *')
  await panel.getByRole('button', { name: '保存巡检' }).click()
  const card = panel.locator('article').filter({ has: page.getByRole('heading', { name: '自动巡检验收', exact: true }) })
  await expect(card.getByText('配置已启用', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: '暂停', exact: true }).click()
  await expect(card.getByText('已暂停', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: '恢复', exact: true }).click()
  await expect(card.getByText('配置已启用', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: '编辑', exact: true }).click()
  await panel.getByLabel('五段 cron').fill('0 10 * * *')
  await panel.getByRole('button', { name: '保存巡检' }).click()
  await expect(card.getByText(/0 10 \* \* \*/)).toBeVisible()
  const status = await (await page.request.get('/api/agents/scheduled-tasks/status')).json()
  if (status.mode === 'execute' && status.runtime_available) {
    await card.getByRole('button', { name: '立即巡检' }).click()
    await expect(panel.getByText('读取完成', { exact: false })).toBeVisible()
    await panel.getByRole('button', { name: '查看报告', exact: true }).first().click()
    await expect(panel.getByText('真实项目数据')).toBeVisible()
    await expect(page).toHaveURL(/inspection=run_/)
  } else {
    await expect(panel.getByText('自动执行已关闭', { exact: false })).toBeVisible()
    await expect(card.getByRole('button', { name: '立即巡检' })).toBeDisabled()
  }
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBeFalsy()
})
