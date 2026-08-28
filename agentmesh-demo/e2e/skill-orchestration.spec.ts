import { expect, type Page, type Route, test } from '@playwright/test'

import { loginAs } from './support/auth'

const NOW = '2026-08-19T08:00:00Z'
const RUN_ID = 'run_orchestration_e2e'
const THREAD_ID = 'thread_orchestration_e2e'

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

const skills = [
  {
    id: 'skill_prd', command: '$prd-feasibility', title: 'PRD 可行性评估', description: '评估业务逻辑和风险',
    usage: '$prd-feasibility <prd>', placeholder: '输入 PRD', aliases: [], requires_input: true,
    source: 'builtin', version: '1', activation_policy: 'explicit_only', enabled: true, binding_enabled: true,
    planner_eligible: true, readiness: 'ready', primary_stage: 'pre_design', capability_type: 'review',
    input_kinds: ['prd'], output_kinds: ['feasibility_review'], side_effect: 'draft',
  },
  {
    id: 'skill_competitive', command: '$competitive-analysis', title: '竞品分析', description: '形成竞品证据',
    usage: '$competitive-analysis <goal>', placeholder: '输入目标', aliases: [], requires_input: true,
    source: 'builtin', version: '1', activation_policy: 'explicit_only', enabled: true, binding_enabled: true,
    planner_eligible: true, readiness: 'ready', primary_stage: 'pre_design', capability_type: 'research',
    input_kinds: ['design_requirement'], output_kinds: ['competitive_analysis'], side_effect: 'draft',
  },
  {
    id: 'skill_interview', command: '$generate-interview-guide', title: '用户访谈提纲', description: '生成访谈问题',
    usage: '$generate-interview-guide <goal>', placeholder: '输入目标', aliases: [], requires_input: true,
    source: 'builtin', version: '1', activation_policy: 'explicit_only', enabled: true, binding_enabled: true,
    planner_eligible: true, readiness: 'ready', primary_stage: 'pre_design', capability_type: 'generation',
    input_kinds: ['research_question'], output_kinds: ['interview_guide'], side_effect: 'draft',
  },
]

type Phase = 'planning' | 'preview' | 'running' | 'partial' | 'waiting_tool' | 'cancelled'

function node(
  id: string,
  skillId: string,
  status: string,
  required: boolean,
  output: string,
) {
  return {
    id,
    skill_id: skillId,
    skill_version: '1',
    skill_content_hash: `hash_${skillId}`,
    reason: `生成 ${output}`,
    required,
    depends_on: [],
    parallel_group: 'evidence',
    input_bindings: ['user.prd'],
    output_contract: [output],
    side_effect: 'draft',
    status,
    attempt: status === 'pending' ? 0 : 1,
    error_code: status === 'failed' ? 'optional_provider_error' : null,
  }
}

function run(phase: Phase) {
  const status = {
    planning: 'planning',
    preview: 'waiting_plan_approval',
    running: 'running',
    partial: 'partial',
    waiting_tool: 'waiting_approval',
    cancelled: 'cancelled',
  }[phase]
  return {
    id: RUN_ID,
    thread_id: THREAD_ID,
    user_id: 'usr_current_designer',
    workspace_id: 'ws_home_appliance_design',
    project_id: 'prj_618_home_appliance',
    input_text: '评审 PRD、分析竞品并准备访谈',
    status,
    plan_id: phase === 'planning' ? null : 'plan_orchestration_e2e',
    planning_mode: 'standard',
    orchestration_version: 'v1',
    orchestration_mode: 'execute',
    agent_definition_version: '1',
    project_chat: true,
    tool_call_count: phase === 'waiting_tool' ? 1 : 0,
    error_code: null,
    created_at: NOW,
    updated_at: NOW,
  }
}

function planDetail(phase: Phase, version: number, includeInterview: boolean) {
  const statuses = phase === 'partial'
    ? ['completed', 'failed', 'skipped']
    : phase === 'waiting_tool'
      ? ['completed', 'waiting_tool_approval', 'pending']
      : phase === 'cancelled'
        ? ['completed', 'cancelled', 'cancelled']
        : phase === 'running'
          ? ['completed', 'running', 'ready']
          : ['pending', 'pending', 'pending']
  const nodes = [
    node('node_prd', 'skill_prd', statuses[0], true, 'feasibility_review'),
    node('node_competitive', 'skill_competitive', statuses[1], false, 'competitive_analysis'),
    ...(includeInterview ? [node('node_interview', 'skill_interview', statuses[2], false, 'interview_guide')] : []),
  ]
  const partial = phase === 'partial'
  const results = partial ? [{
    id: 'result_prd',
    node_id: 'node_prd',
    skill_id: 'skill_prd',
    summary: '核心业务逻辑可行，但需要先验证首屏入口。',
    findings: ['核心链路可实现'],
    recommendations: ['先做灰度验证'],
    sources: [{ id: 'source_prd', title: '618 PRD v4', source_type: 'document', reference: 'doc_prd' }],
    confidence: 0.86,
    limitations: [],
    artifact_ids: [],
    usage: { total_tokens: 128 },
    degradation: null,
    attempt: 1,
    created_at: NOW,
  }] : []
  return {
    plan: {
      id: 'plan_orchestration_e2e',
      run_id: RUN_ID,
      version,
      status: partial ? 'partial' : phase === 'preview' ? 'waiting_approval' : phase === 'cancelled' ? 'cancelled' : 'running',
      intent: {
        goal: '评审 PRD、分析竞品并准备访谈', primary_stage: 'pre_design', input_kinds: ['prd'],
        deliverables: ['feasibility_review', 'competitive_analysis'],
        constraints: { external_write: false, project_scope: 'current' }, explicit_skill_names: [], complexity: 'assisted',
      },
      candidate_skill_ids: skills.map((skill) => skill.id),
      output_contract: ['feasibility_review'],
      preferred_order: nodes.map((item) => item.skill_id),
      nodes,
      planning_mode: 'standard',
      degradation: partial ? '可选竞品分析失败，使用已验证的 PRD 结果综合。' : null,
      created_at: NOW,
      updated_at: `${NOW}.${version}`,
    },
    results,
    synthesis: partial ? {
      summary: 'PRD 主链路可行；竞品证据暂不可用，结论按 Partial 交付。',
      sections: ['需求与风险：核心链路具备实现条件。'],
      claims: [{
        text: '建议先灰度验证首屏入口。',
        node_result_ids: ['result_prd'],
        source_ids: ['source_prd'],
        recommendation: true,
      }],
      limitations: ['竞品分析节点失败'],
      next_actions: ['补充竞品证据后复核'],
      artifact_ids: [],
    } : null,
  }
}

async function enableRuntimeBootstrap(page: Page) {
  await page.route('**/api/bootstrap', async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    await route.fulfill({
      response,
      json: { ...payload, agent_runtime_enabled: true, skill_orchestration_mode: 'execute' },
    })
  })
}

async function installOrchestrationApi(page: Page, initialPhase: Phase = 'preview') {
  let phase = initialPhase
  let version = 1
  let includeInterview = true
  let patchAttempts = 0
  let streamConnections = 0
  let releaseFirstStream = () => {}
  const firstStreamGate = new Promise<void>((resolve) => { releaseFirstStream = resolve })

  await page.route('**/api/chat/skills', (route) => route.fulfill({ json: { items: skills } }))
  await page.route(`**/api/chat/threads/${THREAD_ID}`, (route) => route.fulfill({
    json: {
      thread: {
        id: THREAD_ID, workspace_id: 'ws_home_appliance_design', project_id: 'prj_618_home_appliance',
        user_id: 'usr_current_designer', title: 'Skill 编排验收', status: 'active', created_at: NOW, updated_at: NOW,
      },
      messages: [{
        id: 'message_orchestration_user', thread_id: THREAD_ID, role: 'user',
        content: '评审 PRD、分析竞品并准备访谈', scope: 'private', sources: [], created_at: NOW,
      }],
      turn_traces: [],
    },
  }))
  await page.route('**/api/agent/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    phase = 'preview'
    await route.fulfill({ status: 202, json: { item: run(phase) } })
  })
  await page.route('**/api/agent/runs/**', async (route: Route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (url.pathname.endsWith('/events/stream')) {
      if (phase === 'preview' || phase === 'planning') {
        await route.fulfill({ status: 204, body: '' })
        return
      }
      streamConnections += 1
      if (phase === 'running' && streamConnections === 1) {
        await firstStreamGate
        const event = { id: 'event_1', run_id: RUN_ID, sequence: 1, event_type: 'node_started', payload: { node_id: 'node_competitive' }, created_at: NOW }
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream',
          body: `id: 1\nevent: node_started\ndata: ${JSON.stringify(event)}\n\n`,
        })
        return
      }
      if (phase === 'running') phase = 'partial'
      const duplicate = { id: 'event_dup', run_id: RUN_ID, sequence: 1, event_type: 'node_started', payload: {}, created_at: NOW }
      const terminal = { id: 'event_2', run_id: RUN_ID, sequence: 2, event_type: 'run_partial', payload: {}, created_at: NOW }
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `id: 1\nevent: node_started\ndata: ${JSON.stringify(duplicate)}\n\nid: 2\nevent: run_partial\ndata: ${JSON.stringify(terminal)}\n\n`,
      })
      return
    }
    if (url.pathname.endsWith('/plan/approve') && method === 'POST') {
      phase = 'running'
      await route.fulfill({ json: { plan: planDetail(phase, version, includeInterview).plan, run: run(phase) } })
      return
    }
    if (url.pathname.endsWith('/plan/reject') && method === 'POST') {
      await route.fulfill({ json: { plan: planDetail('cancelled', version, includeInterview).plan, run: run('cancelled') } })
      return
    }
    if (url.pathname.endsWith('/plan') && method === 'PATCH') {
      patchAttempts += 1
      if (patchAttempts === 1) {
        version = 2
        await route.fulfill({ status: 409, contentType: 'application/json', body: '{"detail":"Skill plan version conflict"}' })
        return
      }
      version = 3
      includeInterview = false
      await route.fulfill({ json: planDetail(phase, version, includeInterview) })
      return
    }
    if (url.pathname.endsWith('/plan') && method === 'GET') {
      await route.fulfill({ json: planDetail(phase, version, includeInterview) })
      return
    }
    if (url.pathname.endsWith('/cancel') && method === 'POST') {
      phase = 'cancelled'
      await route.fulfill({ json: { item: run(phase) } })
      return
    }
    if (url.pathname === `/api/agent/runs/${RUN_ID}` && method === 'GET') {
      await route.fulfill({ json: { item: run(phase) } })
      return
    }
    await route.continue()
  })

  return {
    releaseFirstStream: () => releaseFirstStream(),
    streamConnections: () => streamConnections,
  }
}

test('opens a two-level Skill menu by hover, focus, and mobile click', async ({ page }) => {
  await enableRuntimeBootstrap(page)
  const toolSkills = Array.from({ length: 12 }, (_, index) => ({
    ...skills[0],
    id: `tool_${index}`,
    command: index === 0 ? '$memory.search' : `$tool.${index}`,
    title: index === 0 ? '查询记忆' : `工具 ${index}`,
    primary_stage: 'platform',
  }))
  const categorizedSkills = [
    { ...skills[0], id: 'skill_pre', command: '$research-plan', title: '研究计划', primary_stage: 'pre_design' },
    { ...skills[1], id: 'skill_during', command: '$prototype-test', title: '原型验证', primary_stage: 'during_design' },
    { ...skills[2], id: 'skill_post', command: '$metrics-review', title: '效果评估', primary_stage: 'post_design' },
    ...toolSkills,
  ]
  await page.route('**/api/chat/skills', (route) => route.fulfill({ json: { items: categorizedSkills } }))
  await loginAs(page)
  await page.goto('/workspace')

  await page.getByLabel('消息').fill('$')
  const categories = page.getByRole('tablist', { name: 'Skill 分类' })
  await expect(categories.getByRole('tab')).toHaveCount(4)
  await expect(page.getByRole('button', { name: /^\$research-plan 研究计划/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^\$prototype-test 原型验证/ })).toHaveCount(0)

  const menu = page.getByTestId('skill-hierarchy-menu')
  const beforeHover = await menu.boundingBox()
  await categories.getByRole('tab', { name: '设计中', exact: true }).hover()
  const afterHover = await menu.boundingBox()
  expect(afterHover?.height).toBeCloseTo(beforeHover?.height ?? 0, 1)
  expect(afterHover?.y).toBeCloseTo(beforeHover?.y ?? 0, 1)
  await expect(page.getByRole('button', { name: /^\$prototype-test 原型验证/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^\$research-plan 研究计划/ })).toHaveCount(0)

  await categories.getByRole('tab', { name: '工具', exact: true }).hover()
  const scrollPanel = page.getByTestId('skill-submenu-scroll')
  const scrollMetrics = await scrollPanel.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }))
  expect(scrollMetrics.scrollHeight).toBeGreaterThan(scrollMetrics.clientHeight)
  await scrollPanel.hover()
  await page.mouse.wheel(0, 400)
  await expect.poll(() => scrollPanel.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)

  await page.setViewportSize({ width: 375, height: 812 })
  await categories.getByRole('tab', { name: '工具', exact: true }).click()
  await expect(page.getByRole('button', { name: /^\$memory\.search 查询记忆/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('shows live, non-technical feedback while the planner is working', async ({ page }) => {
  await enableRuntimeBootstrap(page)
  await installOrchestrationApi(page, 'planning')
  await loginAs(page)

  await page.goto(`/workspace/thread/${THREAD_ID}?run=${RUN_ID}`)

  await expect(page.getByRole('heading', { name: '正在理解任务，并匹配可用能力' })).toBeVisible()
  await expect(page.getByText('理解目标')).toBeVisible()
  await expect(page.getByText('生成执行计划')).toBeVisible()
  await expect(page.getByText('此阶段不会调用外部工具')).toBeVisible()
  await expect(page.getByText('状态：planning')).toHaveCount(0)
  await expect(page.locator('.planning-scan')).toHaveCSS('animation-name', 'planning-scan')

  await page.setViewportSize({ width: 375, height: 812 })
  await expect(page.getByRole('heading', { name: '正在理解任务，并匹配可用能力' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('Skill Center handoff prefills an explicit Skill without sending it', async ({ page }) => {
  await enableRuntimeBootstrap(page)
  let runCreates = 0
  await page.route('**/api/chat/skills', (route) => route.fulfill({ json: { items: skills } }))
  await page.route('**/api/agent/runs', async (route) => {
    if (route.request().method() === 'POST') runCreates += 1
    await route.abort()
  })
  await loginAs(page)

  await page.goto('/workspace?skill=%24prd-feasibility')

  await expect(page.getByLabel('消息')).toHaveValue('$prd-feasibility ')
  await expect.poll(() => runCreates).toBe(0)
})

test('handles version conflict, approval, parallel progress, SSE reconnect, Partial, and refresh restoration', async ({ page }) => {
  await enableRuntimeBootstrap(page)
  const api = await installOrchestrationApi(page)
  await loginAs(page)
  await page.goto('/workspace')

  await page.getByLabel('消息').fill('评审 PRD、分析竞品并准备访谈')
  const create = page.waitForRequest((request) => request.url().endsWith('/api/agent/runs') && request.method() === 'POST')
  await page.getByRole('button', { name: '发送' }).click()
  const createRequest = await create
  expect(createRequest.postDataJSON()).toMatchObject({ orchestration_mode: 'auto' })
  await expect(page).toHaveURL(new RegExp(`${THREAD_ID}\\?run=${RUN_ID}$`))
  await expect(page.getByRole('heading', { name: '执行前确认计划' })).toBeVisible()
  await expect(page.getByText('确认计划不会批准任何写入工具')).toBeVisible()

  await page.getByRole('button', { name: '移除 用户访谈提纲' }).click()
  await page.getByRole('button', { name: '保存调整' }).click()
  await expect(page.getByRole('alert')).toContainText('Skill plan version conflict')
  await expect(page.getByText('Skill plan · v2')).toBeVisible()

  await page.getByRole('button', { name: '移除 用户访谈提纲' }).click()
  const update = page.waitForRequest((request) => request.url().endsWith('/plan') && request.method() === 'PATCH')
  await page.getByRole('button', { name: '保存调整' }).click()
  expect((await update).postDataJSON()).toMatchObject({
    selected_skill_ids: ['skill_prd', 'skill_competitive'],
  })
  await expect(page.getByText('Skill plan · v3')).toBeVisible()
  await expect(page.getByRole('button', { name: '移除 用户访谈提纲' })).toHaveCount(0)
  const addableCandidates = page.getByRole('region', { name: '可添加候选' })
  await expect(addableCandidates.getByText('用户访谈提纲')).toBeVisible()
  await expect(addableCandidates.getByRole('button', { name: '加入计划' })).toBeVisible()

  await page.getByRole('button', { name: '确认并开始执行' }).click()
  await expect(page.getByRole('heading', { name: '执行计划进行中' })).toBeVisible()
  await expect(page.getByText('正在处理：竞品分析')).toBeVisible()
  await expect(page.locator('[data-node-status="completed"]')).toHaveCount(1)
  await expect(page.locator('[data-node-status="running"]')).toHaveCount(1)
  await expect(page.getByText('可与其他步骤并行')).toHaveCount(2)
  await expect(page.getByText(/不是多套方案/)).toBeVisible()

  api.releaseFirstStream()
  await expect.poll(api.streamConnections, { timeout: 15_000 }).toBeGreaterThanOrEqual(2)
  await expect(page.getByText('部分完成，有未满足项')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('建议先灰度验证首屏入口。')).toBeVisible()
  await expect(page.getByText('618 PRD v4')).toBeVisible()
  await expect(page.getByRole('link', { name: '独立查看' })).toHaveAttribute(
    'href',
    `/api/agent/runs/${RUN_ID}/report.html`,
  )
  await expect(page.getByRole('link', { name: '下载 HTML' })).toHaveAttribute(
    'href',
    `/api/agent/runs/${RUN_ID}/report.html?download=true`,
  )

  await page.reload()
  await expect(page).toHaveURL(new RegExp(`${THREAD_ID}\\?run=${RUN_ID}$`))
  await expect(page.getByText('部分完成，有未满足项')).toBeVisible()
  await expect(page.getByText('竞品分析节点失败')).toBeVisible()
})

test('keeps high-risk tool confirmation distinct and cancels the durable Run', async ({ page }) => {
  await enableRuntimeBootstrap(page)
  await installOrchestrationApi(page, 'waiting_tool')
  await loginAs(page)

  await page.goto(`/workspace/thread/${THREAD_ID}?run=${RUN_ID}`)
  await expect(page.getByRole('heading', { name: '需要确认高风险操作' })).toBeVisible()
  await expect(page.getByText('为什么这次仍需要确认？')).toBeVisible()
  await expect(page.getByText('确认计划不会批准任何写入工具')).toHaveCount(0)
  await page.getByRole('button', { name: '查看高风险操作' }).click()
  await expect(page).toHaveURL(/\/knowledge\?tab=pending$/)

  await page.goto(`/workspace/thread/${THREAD_ID}?run=${RUN_ID}`)
  await page.getByRole('button', { name: '取消运行' }).click()
  await expect(page.getByRole('heading', { name: '执行已取消' })).toBeVisible()
  await expect(page.locator('[data-node-status="cancelled"]')).toHaveCount(2)
})
