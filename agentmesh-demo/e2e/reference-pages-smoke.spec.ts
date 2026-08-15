import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test.beforeEach(async ({ page }) => {
  await loginAs(page)
})

test('DigitalSelf keeps the reference activity composition with provenance', async ({ page }) => {
  await page.goto('/digital-self')
  await expect(page.getByText('需要你处理', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '数字员工动态' })).toBeVisible()
  await expect(page.getByText('对你的工作理解', { exact: true })).toBeVisible()
  await expect(page.getByText('本周新掌握', { exact: true })).toBeVisible()
  await expect(page.getByText('我的经验正在被复用', { exact: true })).toBeVisible()
  await expect(page.getByLabel('T数据').first()).toBeVisible()
  await expect(page.getByLabel('M数据').first()).toBeVisible()
})

test('Knowledge exposes the three reference tabs and M/T provenance', async ({ page }) => {
  await page.goto('/knowledge')
  await expect(page.getByRole('heading', { name: '我的知识' })).toBeVisible()
  const tabs = page.getByRole('tablist')
  await expect(tabs.getByRole('tab', { name: /已沉淀知识/ })).toBeVisible()
  await expect(tabs.getByRole('tab', { name: /待我确认/ })).toBeVisible()
  await expect(tabs.getByRole('tab', { name: /使用与反馈/ })).toBeVisible()
  await expect(page.getByLabel('T数据').first()).toBeVisible()
})

test('Collaboration keeps the narrative overview and detail entry', async ({ page }) => {
  await page.goto('/collaboration')
  await expect(page.getByRole('heading', { name: '协作网络' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '我的协作网络' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '协作能力类型' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '协作明细' })).toBeVisible()
  await expect(page.getByLabel('T数据').first()).toBeVisible()
  await expect(page.getByLabel('M数据').first()).toBeVisible()

  const detail = page.getByRole('button', { name: '查看协作详情' }).first()
  await expect(detail).toBeVisible()
  await detail.click()
  await expect(page.getByText('这次协作是如何发生的', { exact: true })).toBeVisible()
  await expect(page.getByText('任务技术详情', { exact: true })).toBeVisible()
})

test('Insights restores the reference vertical narrative with honest fallbacks', async ({ page }) => {
  await page.goto('/insights')
  await expect(page.getByRole('heading', { name: '工作洞察' })).toBeVisible()
  const headings = ['近期工作概览', '洞察反馈', '值得复盘的历史项目', '复盘证据', '知识形成']
  for (const heading of headings) {
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  }
  await expect(page.getByLabel('T数据').first()).toBeVisible()
  await expect(page.getByLabel('M数据').first()).toBeVisible()
  await expect(page.getByRole('button', { name: /暂不可用/ }).first()).toBeDisabled()
})
