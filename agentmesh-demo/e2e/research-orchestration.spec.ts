import { expect, type Locator, type Page, test } from '@playwright/test'

import { loginAs } from './support/auth'

const NOW = '2026-08-20T02:00:00Z'
const RUN_ID = 'run_research_v2_e2e'
const THREAD_ID = 'thread_research_v2_e2e'
const PLAN_ID = 'research_plan_e2e'
const ATTEMPT_ID = 'attempt_research_v2_e2e'
const INVOCATION_ID = 'invocation_research_v2_e2e'

async function horizontalAlignmentDelta(first: Locator, second: Locator) {
  const [firstBox, secondBox] = await Promise.all([
    first.evaluate((element) => {
      const box = element.getBoundingClientRect()
      return { left: box.left, right: box.right, width: box.width }
    }),
    second.evaluate((element) => {
      const box = element.getBoundingClientRect()
      return { left: box.left, right: box.right, width: box.width }
    }),
  ])
  return {
    left: firstBox.left - secondBox.left,
    right: firstBox.right - secondBox.right,
    width: firstBox.width - secondBox.width,
  }
}

type ResearchState = 'unknown' | 'completed'

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
})

function thread(threadId = THREAD_ID, latestResearchRunId: string | null = RUN_ID) {
  return {
    thread: {
      id: threadId,
      workspace_id: 'ws_home_appliance_design',
      project_id: 'prj_618_home_appliance',
      user_id: 'usr_current_designer',
      title: 'Research v2 验收',
      status: 'active',
      created_at: NOW,
      updated_at: NOW,
    },
    messages: [],
    turn_traces: [],
    latest_research_run_id: latestResearchRunId,
  }
}

function run(state: ResearchState, runId = RUN_ID, threadId = THREAD_ID) {
  return {
    id: runId,
    thread_id: threadId,
    user_id: 'usr_current_designer',
    workspace_id: 'ws_home_appliance_design',
    project_id: 'prj_618_home_appliance',
    input_text: '对比三款企业 AI 研究助手',
    status: state === 'completed' ? 'completed' : 'waiting_approval',
    skill_id: 'skill_competitive',
    skill_name: 'competitive-analysis',
    plan_id: null,
    orchestration_version: 'research-v2',
    orchestration_mode: 'execute',
    requested_orchestration_mode: 'auto',
    agent_definition_version: '1',
    project_chat: true,
    tool_call_count: 1,
    error_code: null,
    created_at: NOW,
    updated_at: NOW,
  }
}

function resultProjection() {
  const fact = {
    claim_id: 'claim_fact_traceability',
    claim_type: 'fact',
    statement: '三款产品提供不同粒度的证据追溯能力。',
    evidence_ids: ['evidence_traceability'],
    parent_claim_ids: [],
    confidence: 'medium',
    conflict_status: 'unknown',
  }
  const recommendation = {
    claim_id: 'claim_recommendation_pilot',
    claim_type: 'recommendation',
    statement: '先用高风险工作流进行小范围试点。',
    evidence_ids: ['evidence_traceability'],
    parent_claim_ids: ['claim_fact_traceability'],
    confidence: 'medium',
    conflict_status: 'unknown',
  }
  return {
    evidence: [{
      evidence_id: 'evidence_traceability',
      quote: 'Provider summary with three independently identified product sources.',
      conflict_status: 'unknown',
      risk_flags: [],
      sources: [{
        source_id: 'source_product_docs',
        title: 'Product documentation',
        url: 'https://example.com/product-docs',
        retrieved_at: NOW,
      }],
    }],
    claims: [fact, recommendation],
    deliverable: {
      summary: '三款产品在证据、恢复和协作方面各有侧重。',
      summary_claim_ids: ['claim_fact_traceability'],
      comparison: [fact],
      recommendations: [recommendation],
      limitations: ['公开资料无法验证私有部署表现。'],
    },
    review: {
      status: 'pass',
      checks: [
        { code: 'claim_evidence_valid', passed: true },
        { code: 'provider_summary_confidence_cap', passed: true },
      ],
    },
    report: {
      title: 'Verified competitive analysis',
      markdown: [
        '# Verified competitive analysis',
        '',
        '## Summary',
        '',
        '**三款产品**在证据、恢复和协作方面各有侧重。',
        '',
        '- 证据可追溯',
        '- 运行可恢复',
        '',
        '| Product | Evidence |',
        '| --- | --- |',
        '| AgentMesh | Traceable |',
        '',
        '[Markdown source](https://example.com/markdown-source)',
      ].join('\n'),
    },
  }
}

function projection(state: ResearchState) {
  const completed = state === 'completed'
  const attempt = {
    attempt_id: ATTEMPT_ID,
    attempt_number: 1,
    status: completed ? 'completed' : 'running',
    steps: [
      {
        step_number: 1,
        status: completed ? 'completed' : 'running',
        attempt_count: 1,
        result_artifact_id: completed ? 'artifact_tool_result' : null,
      },
      {
        step_number: 2,
        status: completed ? 'completed' : 'pending',
        attempt_count: completed ? 1 : 0,
        result_artifact_id: completed ? 'artifact_skill_result' : null,
      },
    ],
  }
  return {
    run_id: RUN_ID,
    orchestration_version: 'research-v2',
    status: completed ? 'completed' : 'running',
    error_code: null,
    workflow: {
      phase: completed ? 'terminal' : 'execution',
      active_gate: completed ? 'none' : 'recovery_decision',
      state_version: completed ? 8 : 6,
      active_requirement_version_id: 'requirement_e2e',
      active_plan_version_id: PLAN_ID,
      active_attempt_id: attempt ? ATTEMPT_ID : null,
      updated_at: NOW,
    },
    requirement: {
      requirement_version_id: 'requirement_e2e',
      version: 1,
      research_goal: '对比三款企业 AI 研究助手的证据、恢复和协作能力',
      competitor_scope: '三款企业级 AI 研究助手',
      blocking: false,
      clarification_questions: [],
    },
    plans: [{
      plan_version_id: PLAN_ID,
      version: 1,
      recommended: true,
      plan_hash: 'a'.repeat(64),
      steps: [
        { step_number: 1, name: 'Research external evidence', actor_type: 'tool', actor_id: 'tool_web_research', required: true },
        { step_number: 2, name: 'Build competitive analysis', actor_type: 'skill', actor_id: 'skill_competitive', required: true },
      ],
    }],
    attempt,
    gaps: state === 'completed'
      ? [{ code: 'limited_public_data', message: '公开资料无法验证私有部署表现。', question_ids: [] }]
      : [],
    artifacts: state === 'completed'
      ? {
          evidence_manifest_id: 'artifact_manifest',
          claim_ledger_id: 'artifact_claims',
          deliverable_id: 'artifact_deliverable',
          review_id: 'artifact_review',
          report_id: 'artifact_report',
        }
      : {},
    result: state === 'completed' ? resultProjection() : { evidence: [], claims: [] },
    provenance: {
      requested_model: 'default',
      actual_model: state === 'completed' ? 'GPT-5.2-joybuilder' : null,
      tool_implementation_id: 'agentmesh.tool_runtime.gateway.ToolGateway.web_research',
      tool_execution_mode: state === 'completed' ? 'real' : null,
    },
    tool_approval: null,
    recovery: state === 'unknown'
      ? { invocation_id: INVOCATION_ID, state: 'unknown', send_count: 1, error_code: 'tool_result_unknown' }
      : null,
    integrity_errors: [],
  }
}

async function enableRuntimeBootstrap(page: Page, mode: 'off' | 'execute') {
  await page.route('**/api/bootstrap', async (route) => {
    const response = await route.fetch()
    const payload = await response.json()
    await route.fulfill({
      response,
      json: { ...payload, agent_runtime_enabled: true, skill_orchestration_mode: mode },
    })
  })
}

async function installResearchApi(page: Page, initialState: ResearchState) {
  const state = initialState
  const mutationRequests: string[] = []

  await page.route('**/api/chat/skills', (route) => route.fulfill({ json: { items: [] } }))
  await page.route(`**/api/chat/threads/${THREAD_ID}`, (route) => route.fulfill({ json: thread() }))
  await page.route(`**/api/agent/runs/${RUN_ID}/events/stream**`, (route) => (
    route.fulfill({ status: 204, body: '' })
  ))
  await page.route(`**/api/agent/runs/${RUN_ID}/research**`, async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (method === 'GET' && url.pathname.endsWith('/research')) {
      await route.fulfill({ json: projection(state) })
      return
    }
    mutationRequests.push(`${method} ${url.pathname}`)
    await route.fulfill({ status: 405, body: '' })
  })
  await page.route(`**/api/agent/runs/${RUN_ID}`, async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { item: run(state) } })
      return
    }
    await route.continue()
  })

  return {
    mutationRequests: () => [...mutationRequests],
  }
}

test('renders historical research results without mutation controls and refreshes safely', async ({ page }) => {
  await enableRuntimeBootstrap(page, 'execute')
  const api = await installResearchApi(page, 'completed')
  await page.route('**/api/documents/jobs', (route) => route.fulfill({
    json: {
      items: [{
        id: 'job_research_layout',
        file_name: 'research-layout.pdf',
        content_type: 'application/pdf',
        workspace_id: 'ws_home_appliance_design',
        project_id: 'prj_618_home_appliance',
        uploaded_by: 'usr_current_designer',
        status: 'completed',
        document_id: 'document_research_layout',
        version: 1,
        expected_chunks: 1,
        completed_chunks: 1,
        error: null,
        error_type: null,
        created_at: NOW,
        updated_at: NOW,
      }],
    },
  }))
  await loginAs(page)

  await page.goto(`/workspace/thread/${THREAD_ID}?run=${RUN_ID}`)
  await expect(page.getByText('Research v2 已退役')).toBeVisible()
  await expect(page.getByRole('heading', { name: '执行进度' })).toBeVisible()
  await expect(page.getByText('检索并封存外部证据').last()).toBeVisible()
  await expect(page.getByRole('heading', { name: '研究结果', exact: true })).toBeVisible()
  for (const label of ['确认此计划', '开始执行研究', '批准工具调用', '拒绝并终止', '确认后再次发送', '安全终止', '取消运行']) {
    await expect(page.getByRole('button', { name: label })).toHaveCount(0)
  }
  expect(api.mutationRequests()).toEqual([])
  const resultsSurface = page.locator('section[aria-labelledby="research-results-title"]')
  const composerSurface = page.getByLabel('消息').locator('..')
  expect(await horizontalAlignmentDelta(resultsSurface, composerSurface)).toEqual({ left: 0, right: 0, width: 0 })
  await page.setViewportSize({ width: 375, height: 812 })
  await expect.poll(() => horizontalAlignmentDelta(resultsSurface, composerSurface)).toEqual({ left: 0, right: 0, width: 0 })
  await page.setViewportSize({ width: 1280, height: 720 })
  await expect(page.getByRole('heading', { name: 'Verified competitive analysis' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Summary', exact: true })).toBeVisible()
  const report = page.locator('article[aria-labelledby="research-report-title"]')
  await expect(report.locator('li').filter({ hasText: '证据可追溯' })).toBeVisible()
  await expect(page.getByRole('table')).toContainText('AgentMesh')
  await expect(page.getByRole('link', { name: 'Markdown source' })).toHaveAttribute('target', '_blank')
  await expect(page.locator('summary').filter({ hasText: '结构化 Deliverable' })).toBeVisible()
  await page.getByRole('link', { name: 'evidence_traceability' }).first().click()
  await expect(page).toHaveURL(/#research-evidence-evidence_traceability$/)
  await expect(page.getByText('Provider summary with three independently identified product sources.')).toBeVisible()
  await expect(page.getByText('确定性 Review · 通过')).toBeVisible()

  const requestsBeforeRefresh = api.mutationRequests()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Verified competitive analysis' })).toBeVisible()
  expect(api.mutationRequests()).toEqual(requestsBeforeRefresh)
})

test('shows an UNKNOWN historical attempt without retry or abort controls', async ({ page }) => {
  await enableRuntimeBootstrap(page, 'execute')
  const api = await installResearchApi(page, 'unknown')
  await loginAs(page)

  await page.goto(`/workspace/thread/${THREAD_ID}?run=${RUN_ID}`)
  await expect(page.getByText('Research v2 已退役')).toBeVisible()
  await expect(page.getByRole('heading', { name: '执行进度' })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认后再次发送' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '安全终止' })).toHaveCount(0)
  expect(api.mutationRequests()).toEqual([])
})

test('keeps historical research readable in off mode and routes new work to v1 compatibility', async ({ page }) => {
  await enableRuntimeBootstrap(page, 'off')
  const api = await installResearchApi(page, 'completed')
  const compatRunId = 'run_v1_compat_e2e'
  const compatThreadId = 'thread_v1_compat_e2e'
  let createBody: Record<string, unknown> | null = null

  await page.route('**/api/agent/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    createBody = route.request().postDataJSON()
    await route.fulfill({
      status: 202,
      json: {
        item: {
          ...run('completed', compatRunId, compatThreadId),
          orchestration_version: 'v1',
          orchestration_mode: 'off',
          requested_orchestration_mode: 'single',
          skill_id: null,
          skill_name: null,
          tool_call_count: 0,
        },
      },
    })
  })
  await page.route(`**/api/chat/threads/${compatThreadId}`, (route) => route.fulfill({ json: thread(compatThreadId, null) }))
  await page.route(`**/api/agent/runs/${compatRunId}`, (route) => route.fulfill({
    json: {
      item: {
        ...run('completed', compatRunId, compatThreadId),
        orchestration_version: 'v1',
        orchestration_mode: 'off',
        requested_orchestration_mode: 'single',
        skill_id: null,
        skill_name: null,
        tool_call_count: 0,
      },
    },
  }))
  await loginAs(page)

  await page.goto(`/workspace/thread/${THREAD_ID}`)
  await expect(page.getByRole('heading', { name: 'Verified competitive analysis' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Verified competitive analysis' })).toBeVisible()
  expect(api.mutationRequests()).toEqual([])

  await page.goto('/workspace')
  await page.getByLabel('消息').fill('新的普通任务')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page).toHaveURL(new RegExp(`${compatThreadId}\\?run=${compatRunId}$`))
  expect(createBody).toMatchObject({ orchestration_mode: 'single' })
  await expect(page.getByLabel('研究任务预览')).toHaveCount(0)
  await expect(page.getByLabel('单 Skill 运行状态')).toContainText('已完成')
})
