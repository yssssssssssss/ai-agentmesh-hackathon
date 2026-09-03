import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

const createdAt = '2026-09-02T00:00:00Z'
const provenance = {
  schema_version: 'memory-provenance-v1',
  source_kind: 'task_artifact',
  task_id: 'task-governed-ui',
  run_id: 'run-governed-ui',
  review_id: 'task-review-governed-ui',
  artifact_ids: ['artifact-governed-ui'],
  artifact_hashes: ['d'.repeat(64)],
  source_memory_ids: [],
  source_memory_versions: [],
  source_memory_hashes: [],
  created_by: 'usr_current_designer',
  created_at: createdAt,
}

const memoryReview = {
  schema_version: 'memory-review-v1',
  id: 'memory-review-governed-ui',
  memory_id: 'memory-governed-ui',
  source_task_review_id: 'task-review-governed-ui',
  requested_by: 'usr_current_designer',
  reviewer_id: 'usr_team_lead',
  status: 'pending',
  decision_note: null,
  memory_version: 1,
  version: 1,
  created_at: createdAt,
  updated_at: createdAt,
  decided_at: null,
}

test('reviews a Team Candidate, then removes disputed knowledge from the active view', async ({ page }) => {
  let memoryState: 'proposed' | 'accepted' | 'disputed' = 'proposed'
  let decisionBody: Record<string, unknown> | null = null
  let transitionBody: Record<string, unknown> | null = null
  const governancePages: number[] = []
  const entry = () => ({
    schema_version: 'memory-entry-view-v1',
    id: 'memory-governed-ui',
    kind: memoryState === 'proposed' ? 'team_candidate' : 'team_knowledge',
    title: '团队可复用的审核经验',
    summary: '交付必须绑定已封存产物和内容哈希。',
    memory_type: 'project_experience',
    scope: memoryState === 'proposed' ? 'team_candidate' : 'team_accepted',
    status: memoryState,
    owner_user_id: 'usr_current_designer',
    workspace_id: 'ws_home_appliance_design',
    project_id: 'prj_618_home_appliance',
    team_id: null,
    layer: null,
    version: memoryState === 'proposed' ? 1 : memoryState === 'accepted' ? 2 : 3,
    content_hash: 'e'.repeat(64),
    provenance,
    provenance_state: 'verified',
    supersedes_memory_id: null,
    archived_at: null,
    archived_by: null,
    archived_from_status: null,
    created_at: createdAt,
    updated_at: createdAt,
    allowed_actions: memoryState === 'proposed'
      ? ['accept_review', 'reject_review', 'expire']
      : memoryState === 'accepted'
        ? ['revise', 'dispute', 'deprecate', 'expire', 'archive']
        : ['revise', 'deprecate', 'expire', 'archive'],
    memory_review: memoryState === 'proposed'
      ? memoryReview
      : { ...memoryReview, status: 'accepted', version: 2, decided_at: createdAt },
    navigation_href: '/knowledge?memory=memory-governed-ui',
  })

  await page.route('**/api/memory/entries?*', async (route) => {
    const url = new URL(route.request().url())
    if (url.searchParams.get('lifecycle') === 'inactive' || url.searchParams.has('status')) {
      const pageNumber = Number(url.searchParams.get('page') ?? '1')
      const statusFilter = url.searchParams.get('status')
      const matchesFilter = memoryState === 'disputed' && (!statusFilter || statusFilter === memoryState)
      governancePages.push(pageNumber)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: {
          items: matchesFilter ? [entry()] : [],
          total: matchesFilter ? 26 : 0,
          page: pageNumber,
          page_size: 25,
          has_next: matchesFilter && pageNumber === 1,
        },
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      json: { items: [entry()], total: 1, page: 1, page_size: 100, has_next: false },
    })
  })
  await page.route('**/api/memory/entries/memory-governed-ui/lineage', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        item: entry(),
        task_id: provenance.task_id,
        run_id: provenance.run_id,
        task_review_id: provenance.review_id,
        artifact_ids: provenance.artifact_ids,
        artifact_hashes: provenance.artifact_hashes,
        source_memory_ids: [],
        source_memories: [],
        superseded_by_memory_ids: [],
        superseded_by_memories: [],
        memory_reviews: [],
        governance_events: [],
      }),
    })
  })
  await page.route('**/api/inbox?*', async (route) => {
    const reviewInbox = {
      id: 'inbox-memory-review-ui',
      title: '审核团队记忆候选',
      summary: '该候选需要独立 Memory Review。',
      item_type: 'memory_review',
      scope: 'private',
      user_id: 'usr_team_lead',
      status: 'open',
      workspace_id: 'ws_home_appliance_design',
      project_id: 'prj_618_home_appliance',
      metadata: {
        memory_review_id: memoryReview.id,
        memory_id: 'memory-governed-ui',
        task_review_id: 'task-review-governed-ui',
      },
      created_at: createdAt,
      updated_at: createdAt,
      allowed_actions: ['open_memory_review'],
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      json: {
        items: memoryState === 'proposed' ? [reviewInbox] : [],
      },
    })
  })
  await page.route('**/api/memory-reviews/*/decisions', async (route) => {
    decisionBody = JSON.parse(route.request().postData() ?? '{}')
    memoryState = 'accepted'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        item: entry(),
        memory_review: {
          review: { ...memoryReview, status: 'accepted', version: 2, decided_at: createdAt },
          allowed_actions: [],
        },
      }),
    })
  })
  await page.route('**/api/memory/memory-governed-ui/transitions', async (route) => {
    transitionBody = JSON.parse(route.request().postData() ?? '{}')
    memoryState = 'disputed'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ item: entry() }),
    })
  })

  await loginAs(page, 'usr_team_lead', 'lead123')
  await page.goto('/knowledge?tab=pending')

  const inboxCard = page.locator('[data-inbox-item-id="inbox-memory-review-ui"]')
  await inboxCard.getByRole('button', { name: '打开记忆审核' }).click()
  await expect(page).toHaveURL(/memory=memory-governed-ui/)
  await expect(page.getByRole('dialog')).toContainText('团队可复用的审核经验')
  await expect(page.getByRole('dialog').getByRole('link', { name: '打开来源任务' })).toHaveAttribute(
    'href',
    '/tasks?task=task-governed-ui',
  )
  await page.getByRole('dialog').getByRole('button', { name: '关闭' }).click()

  const candidateCard = page.locator('[data-inbox-item-id="memory-governed-ui"]')
  await expect(candidateCard.getByRole('button', { name: '接受为团队知识' })).toBeVisible()
  await candidateCard.getByRole('button', { name: '接受为团队知识' }).click()
  await expect(page.getByRole('status')).toContainText('候选已接受为团队知识')
  expect(decisionBody).toEqual(expect.objectContaining({
    expected_memory_version: 1,
    expected_review_version: 1,
    decision: 'accepted',
  }))
  await expect(candidateCard).toHaveCount(0)

  await page.getByRole('tab', { name: /已沉淀知识/ }).click()
  await page.locator('button').filter({ hasText: '团队可复用的审核经验' }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: '标记争议' }).click()
  const transitionDialog = page.getByRole('dialog', { name: '标记团队知识存在争议' })
  await transitionDialog.getByRole('button', { name: '标记争议' }).click()
  await expect(page.getByRole('status')).toContainText('退出自动检索')
  expect(transitionBody).toEqual(expect.objectContaining({
    expected_version: 2,
    action: 'dispute',
  }))

  await page.getByRole('tab', { name: /治理历史/ }).click()
  await expect(page.getByRole('button').filter({ hasText: '团队可复用的审核经验' })).toContainText('存在争议')
  await page.getByRole('button', { name: '下一页' }).click()
  await expect.poll(() => governancePages.includes(2)).toBe(true)
  await page.getByLabel('生命周期状态').selectOption('deprecated')
  await expect(page.getByText('当前筛选下没有治理历史。')).toBeVisible()
  await expect(page.getByLabel('生命周期状态')).toBeVisible()
  await page.getByLabel('生命周期状态').selectOption('all')
  await expect(page.getByRole('button').filter({ hasText: '团队可复用的审核经验' })).toBeVisible()
  await page.setViewportSize({ width: 375, height: 812 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('reuses the revision command ID after an ambiguous response', async ({ page }) => {
  const source = {
    schema_version: 'memory-entry-view-v1',
    id: 'memory-revision-source-ui',
    kind: 'team_knowledge',
    title: '需要更新的团队知识',
    summary: '当前版本内容。',
    memory_type: 'project_experience',
    scope: 'team_accepted',
    status: 'accepted',
    owner_user_id: 'usr_current_designer',
    workspace_id: 'ws_home_appliance_design',
    project_id: 'prj_618_home_appliance',
    team_id: null,
    layer: null,
    version: 2,
    content_hash: 'f'.repeat(64),
    provenance,
    provenance_state: 'verified',
    supersedes_memory_id: null,
    archived_at: null,
    archived_by: null,
    archived_from_status: null,
    created_at: createdAt,
    updated_at: createdAt,
    allowed_actions: ['revise'],
    memory_review: { ...memoryReview, status: 'accepted', version: 2, decided_at: createdAt },
    navigation_href: '/knowledge?memory=memory-revision-source-ui',
  }
  const revisionBodies: Array<Record<string, unknown>> = []

  await page.route('**/api/memory/entries?*', async (route) => {
    const url = new URL(route.request().url())
    const items = url.searchParams.get('lifecycle') === 'inactive' ? [] : [source]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      json: { items, total: items.length, page: 1, page_size: 100, has_next: false },
    })
  })
  await page.route('**/api/memory/entries/memory-revision-source-ui/lineage', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        item: source,
        source_memory_ids: [],
        source_memories: [],
        superseded_by_memory_ids: [],
        superseded_by_memories: [],
        memory_reviews: [],
        governance_events: [],
      }),
    })
  })
  await page.route('**/api/memory/memory-revision-source-ui/revisions', async (route) => {
    const body = JSON.parse(route.request().postData() ?? '{}') as Record<string, unknown>
    revisionBodies.push(body)
    if (revisionBodies.length === 1) {
      await route.abort('failed')
      return
    }
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        item: { ...source, id: 'memory-revision-candidate-ui', kind: 'team_candidate', scope: 'team_candidate', status: 'proposed', version: 1 },
        memory_review: { review: memoryReview, allowed_actions: [] },
      }),
    })
  })

  await loginAs(page)
  await page.goto('/knowledge')
  await page.setViewportSize({ width: 375, height: 812 })
  await page.locator('button').filter({ hasText: '需要更新的团队知识' }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: '创建修订' }).click()

  const revisionDialog = page.getByRole('dialog', { name: '提交团队知识修订' })
  await revisionDialog.getByLabel('标题').fill('更新后的团队知识')
  await revisionDialog.getByLabel('摘要').fill('修订后仍需独立审核。')
  await revisionDialog.getByRole('button', { name: '提交修订候选' }).click()
  await expect(revisionDialog.getByRole('alert')).toBeVisible()
  await revisionDialog.getByRole('button', { name: '提交修订候选' }).click()

  await expect(page.getByRole('status')).toContainText('修订已提交为团队候选')
  expect(revisionBodies).toHaveLength(2)
  expect(revisionBodies[0].command_id).toBe(revisionBodies[1].command_id)
  expect(revisionBodies[1]).toEqual(expect.objectContaining({
    expected_version: 2,
    title: '更新后的团队知识',
    summary: '修订后仍需独立审核。',
  }))
})
