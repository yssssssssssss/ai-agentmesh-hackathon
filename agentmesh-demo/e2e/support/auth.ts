import type { Page } from '@playwright/test'

export const E2E_USER_ID = process.env.AGENTMESH_E2E_USER_ID ?? 'usr_current_designer'
export const E2E_PASSWORD = process.env.AGENTMESH_E2E_PASSWORD ?? 'designer123'

export async function loginAs(page: Page, userId = E2E_USER_ID, password = E2E_PASSWORD) {
  await page.context().clearCookies()
  await page.goto('/digital-self')
  await page.getByLabel('账号').fill(userId)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByTestId('app-shell').waitFor()
}
