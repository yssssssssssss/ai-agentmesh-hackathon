import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test.describe('Collaboration Market', () => {
  test.beforeEach(async ({ page }) => {
    await loginAs(page)
  })

  test('sidebar exposes the market entry and navigates to /market', async ({ page }) => {
    const marketLink = page.getByRole('link', { name: '协作市场' })
    await expect(marketLink).toBeVisible()

    await marketLink.click()
    await expect(page).toHaveURL(/\/market/)
    await expect(page.getByRole('heading', { name: '协作市场' })).toBeVisible()
  })

  test('renders four presence tiles for the personal view', async ({ page }) => {
    await page.getByRole('link', { name: '协作市场' }).click()
    const tiles = page.getByRole('region', { name: '我的市场状态' })
    await expect(tiles).toBeVisible()
    await expect(tiles.getByText('我的记忆')).toBeVisible()
    await expect(tiles.getByText('我发出的信号')).toBeVisible()
    await expect(tiles.getByText('收到的回应')).toBeVisible()
    await expect(tiles.getByText('我提供的帮助')).toBeVisible()
  })

  test('graph section renders once market data resolves', async ({ page }) => {
    await page.getByRole('link', { name: '协作市场' }).click()
    const graph = page.getByRole('region', { name: '协作关系图' })
    await expect(graph).toBeVisible()
    // Toolbar + legend both present regardless of node count
    await expect(graph.getByTitle('复位')).toBeVisible()
    await expect(graph.getByText('我', { exact: true })).toBeVisible()
    await expect(graph.getByText('帮过我')).toBeVisible()
    await expect(graph.getByText('我帮过')).toBeVisible()
  })

  test('exchange tabs switch category and show category tags', async ({ page }) => {
    await page.getByRole('link', { name: '协作市场' }).click()
    const region = page.getByRole('region', { name: '市场交流记录' })
    await expect(region).toBeVisible()

    const tablist = region.getByRole('tablist')
    await expect(tablist.getByRole('tab', { name: /全部/ })).toBeVisible()
    await expect(tablist.getByRole('tab', { name: /我提出的求助/ })).toBeVisible()
    await expect(tablist.getByRole('tab', { name: /谁帮了我/ })).toBeVisible()
    await expect(tablist.getByRole('tab', { name: /我帮了谁/ })).toBeVisible()

    // Switching tabs should not throw and should keep the region mounted.
    await tablist.getByRole('tab', { name: /谁帮了我/ }).click()
    await expect(region).toBeVisible()
    await tablist.getByRole('tab', { name: /我帮了谁/ }).click()
    await expect(region).toBeVisible()
  })
})
