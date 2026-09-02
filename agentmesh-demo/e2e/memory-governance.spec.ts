import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test('reviews a governed Team Candidate independently from Task Review', async ({ page }) => {
  let decided = false
  let decisionBody: Record<string, unknown> | null = null
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
  const candidate = () => ({
    id: 'memory-governed-ui',
    title: '团队可复用的审核经验',
    summary: '交付必须绑定已封存产物和内容哈希。',
    memory_type: 'project_experience',
    scope: decided ? 'team_accepted' : 'team_candidate',
    status: decided ? 'accepted' : 'proposed',
    owner_user_id: 'usr_current_designer',
    workspace_id: 'ws_home_appliance_design',
    project_id: 'prj_618_home_appliance',
    team_id: null,
    sources: [],
    metadata: {},
    provenance,
    version: decided ? 2 : 1,
    supersedes_memory_id: null,
    archived_at: null,
    archived_by: null,
    archived_from_status: null,
    created_at: createdAt,
    updated_at: createdAt,
    allowed_actions: decided ? [] : ['accept_review', 'reject_review'],
    memory_review: decided ? { ...memoryReview, status: 'accepted', version: 2, decided_at: createdAt } : memoryReview,
  })

  await page.route('**/api/memory?*', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({ response, json: { ...body, items: [candidate(), ...body.items] } })
  })
  await page.route('**/api/inbox?*', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    await route.fulfill({
      response,
      json: {
        ...body,
        items: decided ? body.items : [{
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
        }, ...body.items],
      },
    })
  })
  await page.route('**/api/memory-reviews/*/decisions', async (route) => {
    decisionBody = JSON.parse(route.request().postData() ?? '{}')
    decided = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        item: {
          schema_version: 'memory-entry-view-v1',
          ...candidate(),
          kind: 'team_knowledge',
          navigation_href: '/knowledge?memory=memory-governed-ui',
        },
        memory_review: {
          review: { ...memoryReview, status: 'accepted', version: 2, decided_at: createdAt },
          allowed_actions: [],
        },
      }),
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

  const card = page.locator('[data-inbox-item-id="memory-governed-ui"]')
  await expect(card).toContainText('团队可复用的审核经验')
  await expect(card.getByRole('button', { name: '接受为团队知识' })).toBeVisible()
  await expect(card.getByText('拒绝原因')).toBeVisible()
  await card.getByRole('button', { name: '接受为团队知识' }).click()

  await expect(page.getByRole('status')).toContainText('候选已接受为团队知识')
  expect(decisionBody).toEqual(expect.objectContaining({
    expected_memory_version: 1,
    expected_review_version: 1,
    decision: 'accepted',
  }))
  await expect(card).toHaveCount(0)
})
