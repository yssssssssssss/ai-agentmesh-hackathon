import { expect, test } from '@playwright/test'

import { E2E_PASSWORD, E2E_USER_ID, loginAs } from './support/auth'

for (const role of [
  { label: '何云深', expectedName: '何云深' },
  { label: '设计组长', expectedName: '设计组长' },
  { label: '平台管理员', expectedName: '平台管理员' },
]) {
  test(`the ${role.label} demo preset signs in with one click`, async ({ page }) => {
    await page.context().clearCookies()
    await page.goto('/digital-self')

    await page.getByRole('button', { name: `以${role.label}身份进入` }).click()

    await expect(page.getByTestId('app-shell')).toBeVisible()
    await expect(page.getByText(role.expectedName, { exact: true })).toBeVisible()
  })
}

test('a pending demo preset locks every sign-in control and marks only the active role busy', async ({ page }) => {
  let releaseLogin!: () => void
  const loginGate = new Promise<void>((resolve) => {
    releaseLogin = resolve
  })
  await page.route('**/api/auth/login', async (route) => {
    await loginGate
    await route.continue()
  })
  await page.context().clearCookies()
  await page.goto('/digital-self')

  const activePreset = page.getByRole('button', { name: '以何云深身份进入' })
  await activePreset.click()

  await expect(activePreset).toBeDisabled()
  await expect(activePreset).toHaveAttribute('aria-busy', 'true')
  await expect(activePreset.locator('svg.animate-spin')).toHaveCount(1)
  for (const label of ['设计组长', '平台管理员']) {
    const preset = page.getByRole('button', { name: `以${label}身份进入` })
    await expect(preset).toBeDisabled()
    await expect(preset).toHaveAttribute('aria-busy', 'false')
    await expect(preset.locator('svg.animate-spin')).toHaveCount(0)
  }
  await expect(page.getByLabel('账号', { exact: true })).toBeDisabled()
  await expect(page.getByLabel('密码')).toBeDisabled()
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeDisabled()

  releaseLogin()
  await expect(page.getByTestId('app-shell')).toBeVisible()
})

test('demo role presets fit a 375px login viewport without horizontal overflow', async ({ page }) => {
  await page.context().clearCookies()
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/digital-self')

  await expect(page.getByRole('button', { name: '以何云深身份进入' })).toBeVisible()

  const metrics = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    buttons: [...document.querySelectorAll<HTMLButtonElement>('button[aria-label^="以"]')].map((button) => {
      const rect = button.getBoundingClientRect()
      return { left: rect.left, right: rect.right, width: rect.width, height: rect.height }
    }),
  }))

  expect(metrics.scrollWidth).toBe(metrics.clientWidth)
  expect(metrics.buttons).toHaveLength(3)
  for (const button of metrics.buttons) {
    expect(button.left).toBeGreaterThanOrEqual(0)
    expect(button.right).toBeLessThanOrEqual(metrics.clientWidth)
    expect(button.width).toBeGreaterThanOrEqual(40)
    expect(button.height).toBeGreaterThanOrEqual(40)
  }
})

test('login survives reload, logout clears the shell, and another user gets a clean session', async ({ page }) => {
  await loginAs(page)
  await expect(page.getByText('何云深', { exact: true })).toBeVisible()

  await page.reload()
  await expect(page.getByTestId('app-shell')).toBeVisible()
  await expect(page.getByText('何云深', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '退出登录' }).click()
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  await expect(page.getByTestId('app-shell')).toHaveCount(0)
  await expect(page.getByLabel('账号', { exact: true })).toHaveValue('')
  await expect(page.getByLabel('密码')).toHaveValue('')

  await page.getByLabel('账号', { exact: true }).fill('usr_admin')
  await page.getByLabel('密码').fill('admin123')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText('平台管理员', { exact: true })).toBeVisible()
  await expect(page.getByText('何云深', { exact: true })).toHaveCount(0)
})

test('a revoked session becomes signed out on reload', async ({ page }) => {
  await loginAs(page)
  await page.route('**/api/auth/me', (route) =>
    route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Session expired"}' }),
  )

  await page.reload()

  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  await expect(page.getByTestId('app-shell')).toHaveCount(0)
})

test('a late 401 from an old session cannot evict a newer login', async ({ page }) => {
  await loginAs(page)
  await page.evaluate(async () => {
    // This must run in the page so it shares the AuthProvider's client singleton.
    const client = await import('/src/api/client.ts')
    const originalFetch = window.fetch
    let releaseOldRequest!: () => void
    window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) !== '/api/stale-session-probe') return originalFetch(input, init)
      return new Promise<Response>((resolve) => {
        releaseOldRequest = () =>
          resolve(
            new Response('{"detail":"Old session expired"}', {
              status: 401,
              headers: { 'Content-Type': 'application/json' },
            }),
          )
      })
    }) as typeof window.fetch
    const staleRequest = client.apiRequest('/api/stale-session-probe').catch(() => undefined)
    window.fetch = originalFetch
    Object.assign(window, { releaseOldRequest, staleRequest })
  })

  await page.getByRole('button', { name: '退出登录' }).click()
  await page.getByLabel('账号', { exact: true }).fill(E2E_USER_ID)
  await page.getByLabel('密码').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByTestId('app-shell')).toBeVisible()

  await page.evaluate(async () => {
    const stale = window as typeof window & {
      releaseOldRequest: () => void
      staleRequest: Promise<unknown>
    }
    stale.releaseOldRequest()
    await stale.staleRequest
  })

  await expect(page.getByTestId('app-shell')).toBeVisible()
  await expect(page.getByRole('button', { name: '登录', exact: true })).toHaveCount(0)
})

test('a forbidden bootstrap keeps a signed-in denied state', async ({ page }) => {
  await page.route('**/api/bootstrap', (route) =>
    route.fulfill({ status: 403, contentType: 'application/json', body: '{"detail":"Workspace access denied"}' }),
  )
  await page.goto('/digital-self')
  await page.getByLabel('账号').fill(E2E_USER_ID)
  await page.getByLabel('密码').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()

  await expect(page.getByRole('heading', { name: '访问受限' })).toBeVisible()
  await expect(page.getByText('Workspace access denied')).toBeVisible()
  await expect(page.getByRole('button', { name: '登录', exact: true })).toHaveCount(0)
})

test('a failed bootstrap rolls back the just-created server session', async ({ page }) => {
  let rollbackRequests = 0
  await page.route('**/api/bootstrap', (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Bootstrap unavailable"}' }),
  )
  await page.route('**/api/auth/logout', async (route) => {
    rollbackRequests += 1
    await route.continue()
  })
  await page.goto('/digital-self')
  await page.getByLabel('账号').fill(E2E_USER_ID)
  await page.getByLabel('密码').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()

  await expect(page.getByRole('alert')).toContainText('Bootstrap unavailable')
  await expect.poll(() => rollbackRequests).toBe(1)
  const meStatus = await page.evaluate(async () => (await fetch('/api/auth/me')).status)
  expect(meStatus).toBe(401)
})

test('a failed bootstrap blocks on revocation until compensating logout succeeds', async ({ page }) => {
  let logoutAttempts = 0
  await page.route('**/api/bootstrap', (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Bootstrap unavailable"}' }),
  )
  await page.route('**/api/auth/logout', async (route) => {
    logoutAttempts += 1
    if (logoutAttempts === 1) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Logout unavailable"}' })
      return
    }
    await route.continue()
  })
  await page.goto('/digital-self')
  await page.getByLabel('账号').fill(E2E_USER_ID)
  await page.getByLabel('密码').fill(E2E_PASSWORD)
  await page.getByRole('button', { name: '登录', exact: true }).click()

  await expect(page.getByRole('heading', { name: '会话需要撤销' })).toBeVisible()
  await expect(page.getByText('Bootstrap unavailable')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Logout unavailable')
  await expect(page.getByText(/候选会话：/)).toBeVisible()
  await expect(page.getByRole('button', { name: '登录', exact: true })).toHaveCount(0)
  await expect(page.getByTestId('app-shell')).toHaveCount(0)
  const blockedSessionStatus = await page.evaluate(async () => (await fetch('/api/auth/me')).status)
  expect(blockedSessionStatus).toBe(200)

  await page.getByRole('button', { name: '重试退出' }).click()

  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  expect(logoutAttempts).toBe(2)
})

test('logout failure preserves the shell and exposes a retry', async ({ page }) => {
  await loginAs(page)
  await page.route('**/api/auth/logout', (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Logout unavailable"}' }),
  )

  await page.getByRole('button', { name: '退出登录' }).click()

  await expect(page.getByTestId('app-shell')).toBeVisible()
  await expect(page.getByText('Logout unavailable', { exact: true })).toBeVisible()
  await page.unroute('**/api/auth/logout')
  await page.getByRole('button', { name: '重试退出' }).click()
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
})

test('FastAPI serves root, deep links, assets, legacy UI, and JSON API 404', async ({ request }) => {
  const origin = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8021'
  for (const path of ['/', '/workspace/thread/example', '/knowledge/item/example']) {
    const response = await request.get(`${origin}${path}`)
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/html')
  }

  const root = await request.get(`${origin}/`)
  const assetPath = (await root.text()).match(/(?:src|href)="(\/assets\/[^"]+)"/)?.[1]
  expect(assetPath).toBeTruthy()
  expect((await request.get(`${origin}${assetPath}`)).status()).toBe(200)

  const legacy = await request.get(`${origin}/legacy/app.html`)
  expect(legacy.status()).toBe(200)
  const missingApi = await request.get(`${origin}/api/does-not-exist`)
  expect(missingApi.status()).toBe(404)
  expect(missingApi.headers()['content-type']).toContain('application/json')
})

for (const viewport of [
  { width: 390, height: 844 },
  { width: 1512, height: 944 },
]) {
  test(`authenticated shell remains operable at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await loginAs(page)
    const shell = page.getByTestId('app-shell')

    await expect(shell).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width)
    if (viewport.width < 1024) {
      await expect(page.getByRole('button', { name: '打开导航' })).toBeVisible()
      await page.getByRole('button', { name: '打开导航' }).click()
      await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
    } else {
      await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
    }
  })
}

test('drawer and modal set focus, close with Escape, and restore their triggers', async ({ page }) => {
  await loginAs(page)
  const profileTrigger = page.getByRole('button', { name: '打开个人资料' })
  await profileTrigger.click()
  const drawer = page.getByRole('dialog', { name: /何云深/ })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole('button', { name: '关闭' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(profileTrigger).toBeFocused()
  const briefResponse = await page.request.post('/api/chat/messages', {
    data: { content: `$brief.create Auth modal focus ${Date.now()}` },
  })
  expect(briefResponse.ok()).toBeTruthy()
  const briefItem = (await briefResponse.json()).inbox_items[0]

  await page.getByRole('link', { name: '我的知识' }).click()
  await page.getByRole('tab', { name: /待我确认/ }).click()
  const modalTrigger = page.locator(`[data-inbox-item-id="${briefItem.id}"]`).getByRole('button', { name: '确认并沉淀' })
  await expect(modalTrigger).toBeVisible()
  await modalTrigger.click()
  const modal = page.getByRole('dialog', { name: /确认并沉淀/ })
  await expect(modal).toBeVisible()
  await expect(modal.getByRole('button', { name: '关闭' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(modalTrigger).toBeFocused()
})
