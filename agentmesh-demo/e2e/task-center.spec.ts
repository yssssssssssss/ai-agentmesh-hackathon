import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test.describe.serial('task center', () => {
  test('shows real task cards, keeps both status axes, filters, and opens a read-only timeline', async ({ page }) => {
    await loginAs(page)
    await page.route('**/api/tasks/task_graph_demo_3', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          item: {},
          runs: [{
            id: 'run_task_demo_3',
            status: 'completed',
            planning_mode: 'standard',
            artifact_count: 1,
            navigation_href: null,
            created_at: '2026-09-01T00:00:00Z',
            updated_at: '2026-09-01T00:01:00Z',
          }],
          artifacts: [{
            id: 'artifact_task_demo_3',
            run_id: 'run_task_demo_3',
            artifact_type: 'task_output',
            content_type: 'application/json',
            verification_state: 'sealed',
            content_hash: 'a'.repeat(64),
            size_bytes: 20,
            download_href: null,
            created_at: '2026-09-01T00:01:00Z',
          }],
          reviews: [{
            review: {
              schema_version: 'task-review-v1',
              id: 'task_review_demo_3',
              task_id: 'task_graph_demo_3',
              run_id: 'run_task_demo_3',
              artifact_ids: ['artifact_task_demo_3'],
              artifact_hashes: ['a'.repeat(64)],
              round: 1,
              status: 'accepted',
              requested_by: 'usr_current_designer',
              reviewer_id: 'usr_team_lead',
              task_version: 4,
              decision_note: '交付满足任务要求。',
              version: 2,
              created_at: '2026-09-01T00:02:00Z',
              updated_at: '2026-09-01T00:03:00Z',
              decided_at: '2026-09-01T00:03:00Z',
            },
            allowed_actions: [],
          }],
          runs_truncated: false,
          artifacts_truncated: false,
          reviews_truncated: false,
        }),
      })
    })
    await page.goto('/tasks')

    await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
    await expect(page.getByText('管理当前项目任务；Agent 执行与项目交付状态保持独立。')).toBeVisible()
    await expect(page.getByRole('link', { name: '任务中心' })).toHaveAttribute('aria-current', 'page')
    await expect(page.getByRole('region', { name: '任务看板' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '协作完成' })).toBeVisible()
    await expect(page.locator('[data-task-id="task_graph_demo_1"]')).toContainText('执行完成')

    const taskTitle = '查询竞品首屏布局方案'
    await page.getByLabel('搜索任务').fill('不存在的任务标题')
    await expect(page.getByRole('heading', { name: '没有符合筛选的任务' })).toBeVisible()
    await page.getByLabel('筛选可见任务').getByRole('button', { name: '清除筛选' }).click()
    await page.getByLabel('搜索任务').fill('竞品首屏')
    await expect(page.getByText('1 项结果', { exact: true })).toBeVisible()
    await page.getByLabel('执行状态').selectOption('waiting_external_agent')
    await page.getByLabel('协作阶段').selectOption('blocked')
    await expect(page.locator('[data-task-id="task_graph_demo_3"]')).toBeVisible()

    await page.getByRole('button', { name: '列表', exact: true }).click()
    await expect(page.getByRole('table')).toContainText(taskTitle)
    await expect(page.getByRole('table')).toContainText('等待外部 Agent')
    await expect(page.getByRole('table')).toContainText('阻塞')

    await page.getByRole('button', { name: `查看任务：${taskTitle}` }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('只读视图，仅展示当前账号可见的任务事实')
    await expect(dialog.getByText('执行状态', { exact: true })).toBeVisible()
    await expect(dialog.getByText('协作阶段', { exact: true })).toBeVisible()
    await expect(dialog.getByRole('heading', { name: '任务步骤' })).toBeVisible()
    await expect(dialog.getByRole('heading', { name: '黑板时间线' })).toBeVisible()
    await expect(dialog.getByText('以下动态已由服务端按当前账号权限过滤。')).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Agent 执行与产物' })).toBeVisible()
    await expect(dialog.getByRole('heading', { name: '交付审核' })).toBeVisible()
    await expect(dialog.getByText('第 1 轮 · 已接受')).toBeVisible()
    await expect(dialog.getByText('交付满足任务要求。')).toBeVisible()
    await expect(dialog).toContainText('completed')
    await expect(dialog).toContainText('1 个已封存产物')
    await expect(dialog).toContainText('task_output · sealed')
    await expect(dialog.getByRole('link', { name: /打开本人的 Run|打开产物/ })).toHaveCount(0)
    await expect(dialog.getByText('修正：需补充竞品时间范围')).toBeVisible()
    await expect(dialog.getByRole('button', { name: /发送回复|确认交接|执行锁/ })).toHaveCount(0)
  })

  test('distinguishes loading from an empty visible task collection', async ({ page }) => {
    await loginAs(page)
    let releaseResponse!: () => void
    const responseGate = new Promise<void>((resolve) => {
      releaseResponse = resolve
    })
    await page.route('**/api/blackboard/task-cards?*', async (route) => {
      await responseGate
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [] }),
      })
    })

    await page.goto('/tasks')
    await expect(page.getByText('正在读取可见任务')).toBeAttached()
    releaseResponse()
    await expect(page.getByRole('heading', { name: '当前没有可见任务' })).toBeVisible()
    await expect(page.getByText('当前项目还没有可见任务。任务可以由用户创建')).toBeVisible()
  })

  test('shows a recoverable list error and retries the same real endpoint', async ({ page }) => {
    await loginAs(page)
    let attempts = 0
    await page.route('**/api/blackboard/task-cards?*', async (route) => {
      attempts += 1
      if (attempts === 1) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Task cards temporarily unavailable' }),
        })
        return
      }
      await route.continue()
    })

    await page.goto('/tasks')
    await expect(page.getByRole('alert')).toContainText('Task cards temporarily unavailable')
    await page.getByRole('button', { name: '重试', exact: true }).click()
    await expect(page.getByText('查询 618 家电会场首屏历史经验', { exact: true })).toBeVisible()
    expect(attempts).toBeGreaterThanOrEqual(2)
  })

  test('handles an unavailable detail without exposing stale content', async ({ page }) => {
    await loginAs(page)
    let attempts = 0
    await page.route('**/api/blackboard/tasks/task_graph_demo_1', async (route) => {
      attempts += 1
      if (attempts === 1) {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Task not found' }),
        })
        return
      }
      await route.continue()
    })
    await page.goto('/tasks')

    await page.getByRole('button', { name: '查看任务：查询 618 家电会场首屏历史经验' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: '无法查看该任务' })).toBeVisible()
    await expect(dialog).toContainText('任务已不存在或当前账号不可见')
    await expect(dialog.getByRole('heading', { name: '黑板时间线' })).toHaveCount(0)
    await dialog.getByRole('button', { name: '重试' }).click()
    await expect(dialog.getByRole('heading', { name: '黑板时间线' })).toBeVisible()
    await expect(dialog.getByText('摘要：首屏经验综合结论')).toBeVisible()
    expect(attempts).toBeGreaterThanOrEqual(2)
  })

  test('shows an independent retry when execution history fails', async ({ page }) => {
    await loginAs(page)
    let attempts = 0
    await page.route('**/api/tasks/task_graph_demo_1', async (route) => {
      attempts += 1
      if (attempts === 1) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Task execution history unavailable' }),
        })
        return
      }
      await route.continue()
    })
    await page.goto('/tasks')
    await page.getByRole('button', { name: '查看任务：查询 618 家电会场首屏历史经验' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('alert')).toContainText('执行记录加载失败')
    await dialog.getByRole('button', { name: '重试执行记录' }).click()
    await expect(dialog.getByText('执行记录加载失败')).toHaveCount(0)
    await expect(dialog.getByRole('heading', { name: '黑板时间线' })).toBeVisible()
    expect(attempts).toBeGreaterThanOrEqual(2)
  })

  test('creates, edits, assigns, and advances a durable project task', async ({ page }) => {
    await loginAs(page)
    await page.goto('/tasks')

    await page.getByRole('button', { name: '新建任务' }).click()
    const createDialog = page.getByRole('dialog')
    await createDialog.getByLabel('任务标题').fill('验证独立任务闭环')
    await createDialog.getByLabel('任务描述').fill('不依赖外部 Provider 的项目任务')
    await createDialog.getByLabel('优先级').selectOption('p1')
    await createDialog.getByLabel('负责人').selectOption('user:usr_current_designer')
    await createDialog.getByLabel('标签').fill('standalone, task')
    await createDialog.getByRole('button', { name: '创建任务' }).click()

    const card = page.locator('[data-task-id]').filter({ hasText: '验证独立任务闭环' })
    await expect(card).toBeVisible()
    await expect(card).toContainText('待办')
    await expect(card).toContainText('P1')
    await expect(card).toContainText('协作负责人')
    await expect(card).toContainText('未指定')
    await expect(card).toContainText('交付负责人：何云深')
    await card.getByRole('button', { name: '管理' }).click()

    const editDialog = page.getByRole('dialog')
    await expect(editDialog.getByRole('heading', { name: '编辑任务' })).toBeVisible()
    await editDialog.getByLabel('任务标题').fill('验证独立任务与记忆闭环')
    await editDialog.getByRole('button', { name: '保存任务' }).click()

    const updatedCard = page.locator('[data-task-id]').filter({ hasText: '验证独立任务与记忆闭环' })
    await expect(updatedCard).toBeVisible()
    await updatedCard.getByRole('button', { name: '管理' }).click()
    await page.getByRole('dialog').getByRole('button', { name: '进入计划' }).click()
    await expect(updatedCard).toContainText('已计划')
    await updatedCard.getByRole('button', { name: '管理' }).click()
    await page.getByRole('dialog').getByRole('button', { name: '开始任务' }).click()
    await expect(updatedCard).toContainText('进行中')
    await updatedCard.getByRole('button', { name: '管理' }).click()
    await expect(page.getByRole('dialog').getByRole('button', { name: '启动个人 Agent' })).toBeDisabled()
    await page.getByRole('dialog').getByRole('button', { name: '关闭' }).click()
  })

  test('suppresses detail-dependent review actions until linked execution eligibility loads', async ({ page }) => {
    await loginAs(page)
    await page.goto('/tasks')
    await page.getByRole('button', { name: '新建任务' }).click()
    await page.getByRole('dialog').getByLabel('任务标题').fill('等待审核资格加载')
    await page.getByRole('dialog').getByRole('button', { name: '创建任务' }).click()
    const card = page.locator('[data-task-id]').filter({ hasText: '等待审核资格加载' })
    await card.getByRole('button', { name: '管理' }).click()
    await page.getByRole('dialog').getByRole('button', { name: '进入计划' }).click()
    await expect(card).toContainText('已计划')
    await card.getByRole('button', { name: '管理' }).click()
    await page.getByRole('dialog').getByRole('button', { name: '开始任务' }).click()
    await expect(card).toContainText('进行中')

    let releaseDetail!: () => void
    const detailGate = new Promise<void>((resolve) => {
      releaseDetail = resolve
    })
    let detailAttempts = 0
    await page.route('**/api/tasks/*', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue()
        return
      }
      await detailGate
      detailAttempts += 1
      if (detailAttempts === 1) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Task detail refresh unavailable' }),
        })
        return
      }
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({
        response,
        json: {
          ...body,
          item: {
            ...body.item,
            allowed_actions: (body.item.allowed_actions ?? []).filter((action: string) => action !== 'submit_review'),
          },
          runs: [{
            id: 'run_other_owner_review',
            status: 'completed',
            planning_mode: 'standard',
            artifact_count: 1,
            can_submit_review: false,
            navigation_href: null,
            created_at: '2026-09-02T00:00:00Z',
            updated_at: '2026-09-02T00:00:00Z',
          }],
          artifacts: [{
            id: 'artifact_other_owner_review',
            run_id: 'run_other_owner_review',
            artifact_type: 'universal_synthesis',
            content_type: 'application/json',
            verification_state: 'sealed',
            content_hash: 'c'.repeat(64),
            size_bytes: 64,
            download_href: null,
            created_at: '2026-09-02T00:00:00Z',
          }],
          reviews: [],
          runs_truncated: false,
          artifacts_truncated: false,
          reviews_truncated: false,
        },
      })
    })
    await card.getByRole('button', { name: '管理' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('button', { name: '进入审核' })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: '提交审核' })).toHaveCount(0)
    releaseDetail()
    await expect(dialog.getByRole('alert')).toContainText('任务权限与状态刷新失败，操作保持禁用')
    await expect(dialog.getByRole('button', { name: '进入审核' })).toHaveCount(0)
    await dialog.getByRole('button', { name: '重试任务详情' }).click()
    await expect(dialog.getByText('completed', { exact: true })).toBeVisible()
    await expect(dialog.getByRole('button', { name: '进入审核' })).toHaveCount(0)
    await expect(dialog.getByRole('button', { name: '提交审核' })).toHaveCount(0)
  })

  test('starts a linked Run when the runtime is ready and removes the duplicate-start action', async ({ page }) => {
    let runStarted = false
    await page.route('**/api/bootstrap', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({ response, json: { ...body, agent_runtime_enabled: true, agent_runtime_ready: true } })
    })
    await page.route('**/api/agent/runs', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.continue()
        return
      }
      const request = JSON.parse(route.request().postData() ?? '{}')
      runStarted = true
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          item: {
            id: 'run_task_ui_linked',
            task_id: request.task_id,
            thread_id: 'thread_task_ui_linked',
            status: 'running',
          },
        }),
      })
    })
    await page.route('**/api/tasks/*', async (route) => {
      if (route.request().method() !== 'GET' || !runStarted) {
        await route.continue()
        return
      }
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({
        response,
        json: {
          ...body,
          item: {
            ...body.item,
            allowed_actions: (body.item.allowed_actions ?? []).filter((action: string) => action !== 'start_agent_run'),
          },
          runs: [{
            id: 'run_task_ui_linked',
            status: 'running',
            planning_mode: 'standard',
            artifact_count: 0,
            navigation_href: '/workspace/thread/thread_task_ui_linked?run=run_task_ui_linked',
            created_at: '2026-09-01T00:00:00Z',
            updated_at: '2026-09-01T00:00:00Z',
          }],
          artifacts: [],
          runs_truncated: false,
          artifacts_truncated: false,
        },
      })
    })
    await loginAs(page)
    await page.goto('/tasks')
    await page.getByRole('button', { name: '新建任务' }).click()
    await page.getByRole('dialog').getByLabel('任务标题').fill('启动关联 Run')
    await page.getByRole('dialog').getByRole('button', { name: '创建任务' }).click()
    const card = page.locator('[data-task-id]').filter({ hasText: '启动关联 Run' })
    await card.getByRole('button', { name: '管理' }).click()
    await page.getByRole('dialog').getByRole('button', { name: '进入计划' }).click()
    await expect(card).toContainText('已计划')
    await card.getByRole('button', { name: '管理' }).click()
    await page.getByRole('dialog').getByRole('button', { name: '开始任务' }).click()
    await expect(card).toContainText('进行中')
    await card.getByRole('button', { name: '管理' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('button', { name: '启动个人 Agent' })).toBeEnabled()
    await dialog.getByRole('button', { name: '启动个人 Agent' }).click()

    await expect(dialog.getByRole('status')).toContainText('AgentRun 已启动：run_task_ui_linked')
    await expect(dialog.getByText('执行记录')).toBeVisible()
    await expect(dialog.getByRole('link', { name: '打开 Run' })).toHaveAttribute('href', /run_task_ui_linked/)
    await expect(dialog.getByRole('button', { name: '启动个人 Agent' })).toHaveCount(0)
  })

  test('submits frozen artifacts and accepts the assigned Task Review', async ({ page }) => {
    let taskId = ''
    let state: 'ready' | 'pending' | 'accepted' = 'ready'
    let baseItem: Record<string, any> | null = null
    let submittedBody: Record<string, any> | null = null
    let decisionBody: Record<string, any> | null = null
    const reviewId = 'task_review_ui_1'
    const runId = 'run_review_ui_1'
    const artifactId = 'artifact_review_ui_1'
    const createdAt = '2026-09-02T00:00:00Z'

    await page.route('**/api/task-reviews/*/decisions', async (route) => {
      decisionBody = JSON.parse(route.request().postData() ?? '{}')
      state = 'accepted'
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          item: {
            review: review('accepted', 2, '验收通过。'),
            allowed_actions: [],
          },
          task: baseItem?.task ?? {},
        }),
      })
    })
    await page.route('**/api/tasks/*/reviews', async (route) => {
      submittedBody = JSON.parse(route.request().postData() ?? '{}')
      state = 'pending'
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          item: {
            review: review('pending', 1, null),
            allowed_actions: ['accept', 'request_changes', 'reject'],
          },
          task: baseItem?.task ?? {},
        }),
      })
    })
    await page.route('**/api/tasks/*', async (route) => {
      const url = new URL(route.request().url())
      const isCurrentTask = Boolean(taskId) && url.pathname === `/api/tasks/${taskId}`
      if (route.request().method() !== 'GET' || !isCurrentTask) {
        await route.continue()
        return
      }
      const response = await route.fetch()
      const body = await response.json()
      baseItem = body.item
      const baseVersion = body.item.management.version
      const pendingReview = review('pending', 1, null)
      const acceptedReview = review('accepted', 2, '验收通过。')
      await route.fulfill({
        response,
        json: {
          ...body,
          item: {
            ...body.item,
            management: {
              ...body.item.management,
              delivery_stage: state === 'ready' ? 'in_progress' : state === 'pending' ? 'review' : 'done',
              version: baseVersion + (state === 'ready' ? 0 : state === 'pending' ? 1 : 2),
            },
            allowed_actions: state === 'ready'
              ? body.item.allowed_actions
              : [],
          },
          runs: [{
            id: runId,
            status: 'completed',
            planning_mode: 'standard',
            artifact_count: 1,
            can_submit_review: true,
            navigation_href: null,
            created_at: createdAt,
            updated_at: createdAt,
          }],
          artifacts: [{
            id: artifactId,
            run_id: runId,
            artifact_type: 'universal_synthesis',
            content_type: 'application/json',
            verification_state: 'sealed',
            content_hash: 'a'.repeat(64),
            size_bytes: 64,
            download_href: null,
            created_at: createdAt,
          }],
          reviews: state === 'ready' ? [] : [{
            review: state === 'pending' ? pendingReview : acceptedReview,
            allowed_actions: state === 'pending' ? ['accept', 'request_changes', 'reject'] : [],
          }],
          runs_truncated: false,
          artifacts_truncated: false,
          reviews_truncated: false,
        },
      })
    })

    function review(status: 'pending' | 'accepted', version: number, note: string | null) {
      return {
        schema_version: 'task-review-v1',
        id: reviewId,
        task_id: taskId,
        run_id: runId,
        artifact_ids: [artifactId],
        artifact_hashes: ['a'.repeat(64)],
        round: 1,
        status,
        requested_by: 'usr_team_lead',
        reviewer_id: 'usr_team_lead',
        task_version: 4,
        decision_note: note,
        version,
        created_at: createdAt,
        updated_at: createdAt,
        decided_at: status === 'accepted' ? createdAt : null,
      }
    }

    await loginAs(page, 'usr_team_lead', 'lead123')
    await page.goto('/tasks')
    await page.getByRole('button', { name: '新建任务' }).click()
    await page.getByRole('dialog').getByLabel('任务标题').fill('审核封存交付物')
    await page.getByRole('dialog').getByRole('button', { name: '创建任务' }).click()
    const card = page.locator('[data-task-id]').filter({ hasText: '审核封存交付物' })
    taskId = await card.getAttribute('data-task-id') ?? ''
    expect(taskId).not.toBe('')
    await card.getByRole('button', { name: '管理' }).click()
    await page.getByRole('dialog').getByRole('button', { name: '进入计划' }).click()
    await expect(card).toContainText('已计划')
    await card.getByRole('button', { name: '管理' }).click()
    await page.getByRole('dialog').getByRole('button', { name: '开始任务' }).click()
    await expect(card).toContainText('进行中')
    await card.getByRole('button', { name: '管理' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: '提交产物审核' })).toBeVisible()
    await expect(dialog.getByText(artifactId)).toBeVisible()
    await dialog.getByRole('button', { name: '提交审核' }).click()
    await expect(dialog.getByRole('status')).toContainText('第 1 轮审核已提交')
    expect(submittedBody).toEqual(expect.objectContaining({
      run_id: runId,
      artifact_ids: [artifactId],
    }))

    await expect(dialog.getByText('第 1 轮 · 待审核')).toBeVisible()
    await expect(dialog.getByText(`sha256:${'a'.repeat(64)}`)).toBeVisible()
    await expect(dialog.getByRole('link', { name: '检查冻结产物' })).toHaveAttribute(
      'href',
      `/api/task-reviews/${reviewId}/artifacts/${artifactId}`,
    )
    await dialog.getByLabel('审核意见').fill('验收通过。')
    await dialog.getByRole('button', { name: '接受交付' }).click()
    await expect(dialog.getByRole('status')).toContainText('交付已接受，任务已完成')
    await expect(dialog.getByText('第 1 轮 · 已接受')).toBeVisible()
    expect(decisionBody).toEqual(expect.objectContaining({
      expected_version: 1,
      decision: 'accepted',
      decision_note: '验收通过。',
    }))
  })

  test('opens a cross-project assigned Task Review from the Inbox projection', async ({ page }) => {
    await loginAs(page, 'usr_team_lead', 'lead123')
    const sourceResponse = await page.request.get('/api/tasks/task_graph_demo_1')
    expect(sourceResponse.ok()).toBe(true)
    const source = await sourceResponse.json()
    const taskId = 'task_review_cross_project'
    const reviewId = 'task_review_inbox_ui'
    const review = {
      schema_version: 'task-review-v1',
      id: reviewId,
      task_id: taskId,
      run_id: 'run_review_inbox_ui',
      artifact_ids: ['artifact_review_inbox_ui'],
      artifact_hashes: ['b'.repeat(64)],
      round: 1,
      status: 'pending',
      requested_by: 'usr_current_designer',
      reviewer_id: 'usr_team_lead',
      task_version: 4,
      decision_note: null,
      version: 1,
      created_at: '2026-09-02T00:00:00Z',
      updated_at: '2026-09-02T00:00:00Z',
      decided_at: null,
    }
    await page.route(`**/api/tasks/${taskId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...source,
          item: {
            ...source.item,
            task: { ...source.item.task, id: taskId, title: '跨项目交付审核' },
            management: { ...source.item.management, delivery_stage: 'review', version: 4 },
            allowed_actions: ['review_deliverable'],
          },
          runs: [],
          artifacts: [],
          reviews: [{ review, allowed_actions: ['accept', 'request_changes', 'reject'] }],
          runs_truncated: false,
          artifacts_truncated: false,
          reviews_truncated: false,
        }),
      })
    })
    await page.route('**/api/inbox?*', async (route) => {
      const response = await route.fetch()
      const body = await response.json()
      await route.fulfill({
        response,
        json: {
          ...body,
          items: [{
            id: 'inbox_task_review_ui',
            title: '审核任务交付：跨项目交付审核',
            summary: '第 1 轮交付包含 1 个已封存产物。',
            item_type: 'task_review',
            scope: 'private',
            user_id: 'usr_team_lead',
            status: 'open',
            workspace_id: 'workspace_jd_design',
            project_id: 'project_other_member_project',
            metadata: {
              review_id: reviewId,
              task_id: taskId,
              run_id: 'run_review_inbox_ui',
              artifact_count: '1',
              round: '1',
            },
            created_at: '2026-09-02T00:00:00Z',
            updated_at: '2026-09-02T00:00:00Z',
            allowed_actions: ['snooze', 'open_task_review'],
          }, ...body.items],
        },
      })
    })
    await page.goto('/knowledge?tab=pending')

    const item = page.locator('[data-inbox-item-id="inbox_task_review_ui"]')
    await expect(item).toContainText('审核任务交付')
    await expect(item.getByRole('button', { name: '标记已解决' })).toHaveCount(0)
    await item.getByRole('button', { name: '打开任务审核' }).click()

    await expect(page).toHaveURL(/\/tasks(?:\?|$)/)
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: '编辑任务' })).toBeVisible()
    await expect(dialog.getByLabel('任务标题')).toHaveValue('跨项目交付审核')
    await expect(dialog.getByText('第 1 轮 · 待审核')).toBeVisible()
  })

  test('reuses the browser command ID after an ambiguous create response', async ({ page }) => {
    await loginAs(page)
    const commandIds: string[] = []
    let attempts = 0
    await page.route('**/api/tasks', async (route) => {
      if (route.request().method() !== 'POST') {
        await route.continue()
        return
      }
      attempts += 1
      commandIds.push(JSON.parse(route.request().postData() ?? '{}').command_id)
      if (attempts === 1) {
        const response = await route.fetch()
        expect(response.ok()).toBe(true)
        await route.abort('failed')
        return
      }
      await route.continue()
    })
    await page.goto('/tasks')
    await page.getByRole('button', { name: '新建任务' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('任务标题').fill('验证幂等创建')
    await dialog.getByRole('button', { name: '创建任务' }).click()
    await expect(dialog.getByRole('alert')).toBeVisible()
    await dialog.getByRole('button', { name: '创建任务' }).click()

    await expect(page.locator('[data-task-id]').filter({ hasText: '验证幂等创建' })).toHaveCount(1)
    expect(commandIds).toHaveLength(2)
    expect(commandIds[1]).toBe(commandIds[0])
  })

  test('concurrent archive converts a stale edit dialog to read-only without losing its draft', async ({ page, request }) => {
    await loginAs(page)
    await page.goto('/tasks')
    await page.getByRole('button', { name: '新建任务' }).click()
    const createDialog = page.getByRole('dialog')
    await createDialog.getByLabel('任务标题').fill('并发归档测试')
    await createDialog.getByRole('button', { name: '创建任务' }).click()
    const card = page.locator('[data-task-id]').filter({ hasText: '并发归档测试' })
    await expect(card).toBeVisible()
    const taskId = await card.getAttribute('data-task-id')
    expect(taskId).toBeTruthy()
    await card.getByRole('button', { name: '管理' }).click()
    const editDialog = page.getByRole('dialog')
    await editDialog.getByLabel('任务标题').fill('未提交的本地标题')

    const login = await request.post('/api/auth/login', {
      data: { user_id: 'usr_team_lead', password: 'lead123' },
    })
    expect(login.ok()).toBe(true)
    let version = 1
    for (const action of ['plan', 'start', 'submit_review', 'complete']) {
      const transition = await request.post(`/api/tasks/${taskId}/transitions`, {
        data: { command_id: `archive-race-${action}`, expected_version: version, action },
      })
      expect(transition.ok()).toBe(true)
      version += 1
    }
    const archive = await request.post(`/api/tasks/${taskId}/archive`, {
      data: { command_id: 'archive-race-final', expected_version: version },
    })
    expect(archive.ok()).toBe(true)

    await editDialog.getByRole('button', { name: '保存任务' }).click()
    await expect(editDialog.getByRole('alert')).toContainText('任务已在其他会话归档')
    await expect(editDialog.getByRole('status')).toContainText('该任务已归档')
    await expect(editDialog.getByLabel('任务标题')).toHaveValue('未提交的本地标题')
    await expect(editDialog.getByLabel('任务标题')).toBeDisabled()
    await expect(editDialog.getByRole('button', { name: '保存任务' })).toHaveCount(0)
  })

  test('keeps tablet and desktop task management views inside the viewport', async ({ page }) => {
    await loginAs(page)
    for (const viewport of [
      { width: 768, height: 1024 },
      { width: 1512, height: 982 },
    ]) {
      await page.setViewportSize(viewport)
      await page.goto('/tasks')
      await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
      await expect(page.getByRole('button', { name: '新建任务' })).toBeVisible()
      const documentMetrics = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }))
      expect(documentMetrics.scrollWidth).toBe(documentMetrics.clientWidth)
    }
  })

  test('keeps the board and drawer inside a 390px viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await loginAs(page)
    await page.goto('/tasks')

    await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible()
    await expect(page.getByRole('region', { name: '任务看板' })).toBeVisible()
    const documentMetrics = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }))
    expect(documentMetrics.scrollWidth).toBe(documentMetrics.clientWidth)

    await page.getByRole('button', { name: '查看任务：查询竞品首屏布局方案' }).click()
    const drawerBounds = await page.getByRole('dialog').boundingBox()
    expect(drawerBounds).not.toBeNull()
    expect(drawerBounds?.width ?? 0).toBeLessThanOrEqual(390)
    expect(drawerBounds?.x ?? -1).toBeGreaterThanOrEqual(0)
  })
})
