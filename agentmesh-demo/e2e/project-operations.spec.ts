import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test('operates a project through dependencies, milestones, calendar, and the Agent queue', async ({ page }) => {
  await loginAs(page, 'usr_team_lead', 'lead123')
  const bootstrap = await page.request.get('/api/bootstrap')
  expect(bootstrap.ok()).toBeTruthy()
  const bootstrapBody = await bootstrap.json()
  const projectId = bootstrapBody.project.id as string
  const agentId = bootstrapBody.user.personal_agent_id as string

  const createTask = async (payload: Record<string, unknown>) => {
    const response = await page.request.post('/api/tasks', { data: payload })
    expect(response.status(), await response.text()).toBe(201)
    return (await response.json()).item
  }

  const milestone = await createTask({
    command_id: 'e2e-operations-milestone',
    title: 'Slice 6 发布里程碑',
    task_type: 'milestone',
    due_at: '2026-11-01T00:00:00Z',
  })
  const research = await createTask({
    command_id: 'e2e-operations-research',
    title: '验证运营需求',
    parent_task_id: milestone.task.id,
    assignee_kind: 'agent',
    assignee_id: agentId,
    due_at: '2026-09-20T00:00:00Z',
  })
  const design = await createTask({
    command_id: 'e2e-operations-design',
    title: '实现项目运营界面',
    parent_task_id: milestone.task.id,
    dependency_task_ids: [research.task.id],
    assignee_kind: 'agent',
    assignee_id: agentId,
    due_at: '2026-10-01T00:00:00Z',
  })

  await page.goto('/tasks?surface=overview')
  await expect(page.getByRole('heading', { name: '关键依赖链' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '近期里程碑' })).toBeVisible()
  await expect(page.getByText('Slice 6 发布里程碑')).toBeVisible()
  await expect(page.getByText('验证运营需求')).toBeVisible()
  await expect(page.getByText('实现项目运营界面')).toBeVisible()

  await page.getByRole('button', { name: '日历', exact: true }).click()
  await expect(page.getByRole('heading', { name: '项目日历' })).toBeVisible()
  await expect(page.getByText('实现项目运营界面')).toBeVisible()
  await page.getByRole('button', { name: '下一时间段' }).click()
  await expect(page).toHaveURL(/calendar_month=/)
  await expect(page.getByRole('heading', { name: '项目日历' })).toBeVisible()

  await page.getByRole('button', { name: 'Agent 队列', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Agent 队列' })).toBeVisible()
  await expect(page.getByRole('table')).toContainText('等待依赖')

  await page.goto(`/tasks?manage=${encodeURIComponent(design.task.id)}`)
  const dialog = page.getByRole('dialog', { name: '编辑任务' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('combobox', { name: '父任务' })).toHaveValue(milestone.task.id)
  await expect(dialog.getByRole('heading', { name: '任务结构' })).toBeVisible()
  const dependencyToggle = dialog.getByRole('checkbox', { name: /验证运营需求/ })
  await expect(dependencyToggle).toBeChecked()
  await dependencyToggle.uncheck()
  await dialog.getByRole('button', { name: '保存任务' }).click()
  await expect(dialog).toBeHidden()
  const updatedDesign = await page.request.get(`/api/tasks/${encodeURIComponent(design.task.id)}`)
  expect(updatedDesign.ok()).toBeTruthy()
  expect((await updatedDesign.json()).item.management.dependency_task_ids).toEqual([])

  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/tasks?surface=overview')
  await expect(page.getByRole('heading', { name: '关键依赖链' })).toBeVisible()
  const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(hasHorizontalOverflow).toBeFalsy()
  expect(projectId).toBeTruthy()
})


test('paginates the Task Center without downloading every management page', async ({ page }) => {
  await loginAs(page)
  const card = (id: string, title: string) => ({
    task: {
      id,
      thread_id: `thread-${id}`,
      intent: 'general_chat',
      status: 'created',
      collaboration_stage: 'discussion',
      current_owner_agent_id: null,
      current_owner_label: null,
      execution_lock: null,
      done_when: null,
      title,
      steps: [],
      management: null,
      created_at: '2026-09-06T00:00:00Z',
      updated_at: '2026-09-06T00:00:00Z',
    },
    latest_post: null,
    stage: 'discussion',
    owner: null,
    done_when: null,
    active_lock: null,
    post_count: 0,
    initiator_user_id: 'usr_current_designer',
    initiated_by_current_user: true,
    claimed_by_personal_agent: false,
    upstream_agents: [],
    downstream_agents: [],
    target_post_id: null,
    allowed_actions: [],
  })
  const managed = (id: string, title: string) => ({
    task: { ...card(id, title).task, management: undefined },
    management: {
      schema_version: 'task-management-v1',
      description: '',
      task_type: 'project_action',
      delivery_stage: 'backlog',
      priority: null,
      due_at: null,
      assignee_kind: null,
      assignee_id: null,
      tags: [],
      parent_task_id: null,
      dependency_task_ids: [],
      blocked_reason: null,
      blocked_at: null,
      version: 1,
      archived_at: null,
      created_by: 'usr_current_designer',
      updated_by: 'usr_current_designer',
    },
    readiness: {
      state: 'backlog',
      is_execution_ready: false,
      dependency_count: 0,
      completed_dependency_count: 0,
      blocking_task_ids: [],
      child_count: 0,
      completed_child_count: 0,
    },
    allowed_actions: [],
  })
  await page.route('**/api/blackboard/task-cards?*', async (route) => {
    const pageNumber = Number(new URL(route.request().url()).searchParams.get('page') ?? '1')
    const title = pageNumber === 1 ? '第一页任务' : '第二页任务'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [card(`task-page-${pageNumber}`, title)], total: 101, page: pageNumber, page_size: 100, has_next: pageNumber === 1 }),
    })
  })
  await page.route('**/api/tasks?*', async (route) => {
    const pageNumber = Number(new URL(route.request().url()).searchParams.get('page') ?? '1')
    const title = pageNumber === 1 ? '第一页任务' : '第二页任务'
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [managed(`task-page-${pageNumber}`, title)], total: 101, page: pageNumber, page_size: 100, has_next: pageNumber === 1, counts: { backlog: 101 } }),
    })
  })

  await page.goto('/tasks')
  await expect(page.getByText('第一页任务')).toBeVisible()
  const pagination = page.getByRole('navigation', { name: '任务列表分页' })
  await pagination.getByRole('button', { name: '下一页' }).click()
  await expect(page).toHaveURL(/task_page=2/)
  await expect(page.getByText('第二页任务')).toBeVisible()
  await expect(pagination.getByRole('button', { name: '下一页' })).toBeDisabled()
})
