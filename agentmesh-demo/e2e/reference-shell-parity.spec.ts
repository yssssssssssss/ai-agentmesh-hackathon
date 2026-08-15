import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test.beforeEach(async ({ page }) => {
  await loginAs(page)
})

test('matches the reference desktop shell and tab semantics', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 944 })
  await page.goto('/digital-self')

  const sidebar = page.locator('aside').first()
  await expect(sidebar).toBeVisible()
  expect(await sidebar.evaluate((element) => Math.round(element.getBoundingClientRect().width))).toBe(260)
  await expect(sidebar.getByText('AgentMesh', { exact: true })).toBeVisible()
  await expect(sidebar.getByText('我的数字员工', { exact: true }).first()).toBeVisible()

  const content = page.locator('main > div').first()
  expect(await content.evaluate((element) => getComputedStyle(element).maxWidth)).toBe('1240px')

  await page.getByRole('link', { name: '我的知识' }).click()
  const tabs = page.getByRole('tablist')
  await expect(tabs).toBeVisible()
  const firstTab = tabs.getByRole('tab').first()
  await expect(firstTab).toHaveAttribute('aria-selected', 'true')
  await firstTab.press('End')
  await expect(tabs.getByRole('tab').last()).toBeFocused()

  await page.getByRole('button', { name: '打开账号与设置' }).click()
  const settings = page.getByRole('dialog', { name: '账号与设置' })
  await expect(settings.getByLabel('T数据')).toBeVisible()
  await expect(settings.getByLabel('M数据')).toBeVisible()
})

test('keeps the existing mobile navigation operable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/digital-self')

  await page.getByRole('button', { name: '打开导航' }).click()
  await expect(page.locator('aside')).toBeVisible()
  await page.getByRole('button', { name: '关闭导航', exact: true }).click()
  await expect(page.getByRole('button', { name: '关闭导航', exact: true }).locator('..')).toHaveClass(/-translate-x-full/)

  await page.goto('/knowledge')
  const mobileTabs = page.getByRole('tablist')
  const lastTab = mobileTabs.getByRole('tab').last()
  await lastTab.click()
  await expect(lastTab).toHaveAttribute('aria-selected', 'true')

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})
