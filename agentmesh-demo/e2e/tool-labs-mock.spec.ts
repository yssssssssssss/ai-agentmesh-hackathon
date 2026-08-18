import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test.beforeEach(async ({ page }) => {
  await loginAs(page)
  await page.getByRole('link', { name: 'AI 工作台' }).click()
  await expect(page.getByRole('heading', { name: 'AI 工作台' })).toBeVisible()
})

test('opens the aesthetic mock tool above the composer and preserves the chat draft', async ({ page }) => {
  const toolRequests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/tool-labs/')) toolRequests.push(request.url())
  })

  const composer = page.getByLabel('消息')
  const launcher = page.getByRole('button', { name: '美学量化' })
  await composer.fill('保留这段聊天草稿')
  await expect(launcher).toBeVisible()
  await expect(page.getByRole('button', { name: '美学量化', exact: true })).toBeVisible()

  const launcherBox = await launcher.boundingBox()
  const composerBox = await composer.boundingBox()
  expect(launcherBox).not.toBeNull()
  expect(composerBox).not.toBeNull()
  expect(launcherBox!.y).toBeLessThan(composerBox!.y)

  await launcher.click()
  const dialog = page.getByRole('dialog', { name: '美学量化演示' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('报告基于内置京东新品频道截图生成')).toBeVisible()
  const initialFigure = dialog.getByTestId('case-study-figure')
  await expect(initialFigure.getByText('案例原图预览')).toBeVisible()
  await expect(initialFigure.getByText('顶部频道与搜索区')).toHaveCount(0)
  await expect(dialog.getByLabel('上传设计图')).toHaveAttribute('tabindex', '-1')
  const longFileName = 'very-long-aesthetic-design-file-name-that-must-not-overflow-the-picker-control.svg'

  await dialog.getByLabel('上传设计图').setInputFiles({
    name: longFileName,
    mimeType: 'image/svg+xml',
    buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="#f4a261"/></svg>'),
  })
  await expect(dialog.getByRole('img', { name: '设计图预览' })).toBeVisible()
  const imagePicker = dialog.getByRole('button', { name: longFileName })
  expect(await imagePicker.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await dialog.getByLabel('分析模式').selectOption('readability_first')
  await dialog.getByLabel('分析深度').selectOption('deep')
  await dialog.getByRole('button', { name: '添加 ROI' }).click()
  await expect(dialog.getByLabel('ROI 名称 3')).toBeVisible()
  await dialog.getByRole('button', { name: '删除 顶部频道与搜索区' }).click()
  await dialog.getByRole('button', { name: '添加 ROI' }).click()
  await dialog.getByLabel('ROI 名称 3').fill('新区域')
  await expect(dialog.getByLabel('ROI 名称 2')).toHaveValue('区域 3')
  await dialog.getByRole('button', { name: '生成案例报告' }).click()

  await expect(dialog.getByRole('heading', { name: '演示结果' })).toBeVisible()
  await expect(dialog.getByRole('heading', { name: '京东 App 新品频道首页' })).toBeVisible()
  await expect(dialog.getByText('综合分 76')).toBeVisible()
  await expect(dialog.getByTestId('case-study-figure').getByText('顶部频道与搜索区')).toBeVisible()
  await expect(dialog.getByText('注意力热点示意')).toBeVisible()
  const aestheticResultBox = await dialog.getByRole('heading', { name: '演示结果' }).boundingBox()
  const aestheticDialogBox = await dialog.boundingBox()
  expect(aestheticResultBox).not.toBeNull()
  expect(aestheticDialogBox).not.toBeNull()
  expect(aestheticResultBox!.y).toBeGreaterThanOrEqual(aestheticDialogBox!.y)
  expect(aestheticResultBox!.y + aestheticResultBox!.height).toBeLessThanOrEqual(aestheticDialogBox!.y + aestheticDialogBox!.height)
  await dialog.getByRole('button', { name: '返回修改参数' }).click()
  await dialog.getByRole('checkbox', { name: '注意力计入综合分' }).check()
  await dialog.getByRole('button', { name: '生成案例报告' }).click()
  await expect(dialog.getByText('综合分 78')).toBeVisible()
  await expect(dialog.getByText('注意力已计入演示总分')).toBeVisible()
  await dialog.getByRole('button', { name: '返回修改参数' }).click()
  await dialog.getByRole('checkbox', { name: '启用注意力分析' }).uncheck()
  await dialog.getByRole('button', { name: '生成案例报告' }).click()
  await expect(dialog.getByText('综合分 76')).toBeVisible()
  await expect(dialog.getByText('注意力未计入演示总分')).toBeVisible()
  await expect(dialog.getByText('注意力热点示意')).toHaveCount(0)
  await expect(dialog.getByText('注意力聚焦')).toHaveCount(0)
  await expect(dialog.getByText(/注意力 #/)).toHaveCount(0)
  await expect(dialog.getByText('第一注意力峰值')).toHaveCount(0)
  expect(toolRequests).toEqual([])

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(launcher).toBeFocused()
  await expect(composer).toHaveValue('保留这段聊天草稿')
})

test('produces a deterministic experience-model recommendation without backend requests', async ({ page }) => {
  const toolRequests: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/tool-labs/')) toolRequests.push(request.url())
  })

  await page.getByRole('button', { name: '体验模型' }).click()
  const dialog = page.getByRole('dialog', { name: '体验模型演示' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('固定推荐样例，不代表实际研究结论')).toBeVisible()
  await expect(page.getByRole('button', { name: '体验模型', exact: true })).toBeVisible()
  await expect(dialog.getByTestId('case-study-figure').getByText('案例原图预览')).toBeVisible()
  await expect(dialog.getByTestId('case-study-figure').getByText('顶部频道与搜索区')).toHaveCount(0)

  await dialog.getByLabel('研究问题').fill('评估新版首页是否提升用户参与和任务成功率')
  await dialog.getByRole('checkbox', { name: 'HEART' }).check()
  await dialog.getByLabel('人工指定模型').selectOption('kano')
  await dialog.getByRole('button', { name: '生成演示推荐' }).click()

  await expect(dialog.getByRole('heading', { name: '推荐结果' })).toBeVisible()
  await expect(dialog.getByTestId('case-study-figure').getByText('顶部频道与搜索区')).toBeVisible()
  await expect(dialog.getByRole('heading', { name: 'HEART 模型' })).toBeVisible()
  await expect(dialog.getByRole('heading', { name: 'Kano 模型' })).toBeVisible()
  await expect(dialog.getByRole('heading', { name: '方法资料索引' })).toBeVisible()
  const experienceResultBox = await dialog.getByRole('heading', { name: '推荐结果' }).boundingBox()
  const experienceDialogBox = await dialog.boundingBox()
  expect(experienceResultBox).not.toBeNull()
  expect(experienceDialogBox).not.toBeNull()
  expect(experienceResultBox!.y).toBeGreaterThanOrEqual(experienceDialogBox!.y)
  expect(experienceResultBox!.y + experienceResultBox!.height).toBeLessThanOrEqual(experienceDialogBox!.y + experienceDialogBox!.height)
  expect(toolRequests).toEqual([])
})

test('keeps model ranking deterministic and aligns copy with the chosen models', async ({ page }) => {
  const runWithOrder = async (labels: string[]) => {
    await page.getByRole('button', { name: '体验模型' }).click()
    const dialog = page.getByRole('dialog', { name: '体验模型演示' })
    await dialog.getByLabel('研究问题').fill('评估 AI 功能的接受度、行为触发和长期口碑')
    for (const label of labels) await dialog.getByRole('checkbox', { name: label }).check()
    await dialog.getByRole('button', { name: '生成演示推荐' }).click()
    const names = await dialog.locator('[data-testid="recommended-model-name"]').allTextContents()
    const summary = await dialog.getByTestId('experience-summary').textContent()
    const templates = await dialog.locator('[data-testid="question-template"]').allTextContents()
    await dialog.getByRole('button', { name: '关闭' }).click()
    return { names, summary, templates }
  }

  const first = await runWithOrder(['NPS', 'TAM', 'Fogg'])
  const second = await runWithOrder(['Fogg', 'TAM', 'NPS'])
  expect(second.names).toEqual(first.names)
  expect(first.summary).toContain('NPS')
  expect(first.summary).toContain('TAM')
  expect(first.summary).toContain('Fogg')
  expect(first.templates.join(' ')).toContain('NPS')
  expect(first.templates.join(' ')).toContain('TAM')
  expect(first.templates.join(' ')).toContain('Fogg')
})

test('does not steal focus when workspace jobs poll in the background', async ({ page }) => {
  let polls = 0
  await page.route('**/api/documents/jobs', (route) => {
    polls += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [{
        id: 'job-focus-check', file_name: 'focus-check.txt', status: 'running',
        completed_chunks: polls, expected_chunks: 100, uploaded_by: 'usr_current_designer',
        workspace_id: 'ws_home_appliance_design', project_id: 'prj_618_home_appliance',
      }] }),
    })
  })
  await page.reload()
  await page.getByRole('button', { name: '体验模型' }).click()
  const researchQuestion = page.getByRole('dialog', { name: '体验模型演示' }).getByLabel('研究问题')
  await researchQuestion.focus()
  await expect(researchQuestion).toBeFocused()
  await page.waitForTimeout(1_300)
  await expect(researchQuestion).toBeFocused()
})

test('keeps the tool dialog operable across mobile, tablet, and wide layouts', async ({ page }) => {
  for (const viewport of [
    { width: 390, height: 844, columns: 1 },
    { width: 768, height: 900, columns: 1 },
    { width: 1512, height: 944, columns: 2 },
  ]) {
    await page.setViewportSize(viewport)
    await page.getByRole('button', { name: '体验模型' }).click()
    const dialog = page.getByRole('dialog', { name: '体验模型演示' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByLabel('研究问题')).toBeVisible()
    await expect(dialog.getByRole('button', { name: '生成演示推荐' })).toBeVisible()

    const box = await dialog.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.y).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width)
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height)
    const layout = await dialog.getByTestId('experience-model-panel').evaluate((element) => ({
      columns: getComputedStyle(element).gridTemplateColumns.split(' ').length,
      overflow: element.scrollWidth > element.clientWidth,
    }))
    expect(layout.columns).toBe(viewport.columns)
    expect(layout.overflow).toBe(false)
    await dialog.getByRole('button', { name: '关闭' }).click()
  }
})
