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

type ResearchState = 'plan' | 'confirmed' | 'tool_approval' | 'running' | 'unknown' | 'completed' | 'aborted'

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
  const status = {
    plan: 'waiting_plan_approval',
    confirmed: 'planning',
    tool_approval: 'waiting_approval',
    running: 'running',
    unknown: 'waiting_approval',
    completed: 'completed',
    aborted: 'failed',
  }[state]
  return {
    id: runId,
    thread_id: threadId,
    user_id: 'usr_current_designer',
    workspace_id: 'ws_home_appliance_design',
    project_id: 'prj_618_home_appliance',
    input_text: '对比三款企业 AI 研究助手',
    status,
    skill_id: 'skill_competitive',
    skill_name: 'competitive-analysis',
    plan_id: null,
    orchestration_version: 'research-v2',
    orchestration_mode: 'execute',
    requested_orchestration_mode: 'auto',
    agent_definition_version: '1',
    project_chat: true,
    tool_call_count: ['running', 'unknown', 'completed', 'aborted'].includes(state) ? 1 : 0,
    error_code: state === 'aborted' ? 'recovery_aborted' : null,
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
  const stateVersion = {
    plan: 2,
    confirmed: 3,
    tool_approval: 4,
    running: 5,
    unknown: 6,
    completed: 8,
    aborted: 8,
  }[state]
  const attempt = ['tool_approval', 'running', 'unknown', 'completed', 'aborted'].includes(state)
    ? {
        attempt_id: ATTEMPT_ID,
        attempt_number: 1,
        status: state === 'completed' ? 'completed' : state === 'aborted' ? 'failed' : 'running',
        steps: [
          {
            step_number: 1,
            status: state === 'completed' ? 'completed' : state === 'aborted' ? 'failed' : state === 'tool_approval' ? 'ready' : 'running',
            attempt_count: state === 'tool_approval' ? 0 : 1,
            result_artifact_id: state === 'completed' ? 'artifact_tool_result' : null,
            error_code: state === 'aborted' ? 'recovery_aborted' : null,
          },
          {
            step_number: 2,
            status: state === 'completed' ? 'completed' : state === 'aborted' ? 'cancelled' : 'pending',
            attempt_count: state === 'completed' ? 1 : 0,
            result_artifact_id: state === 'completed' ? 'artifact_skill_result' : null,
          },
        ],
      }
    : null
  return {
    run_id: RUN_ID,
    orchestration_version: 'research-v2',
    status: state === 'completed' ? 'completed' : state === 'aborted' ? 'cancelled' : 'running',
    error_code: state === 'aborted' ? 'recovery_aborted' : null,
    workflow: {
      phase: state === 'completed' || state === 'aborted'
        ? 'terminal'
        : state === 'plan' || state === 'confirmed'
          ? 'planning'
          : 'execution',
      active_gate: state === 'plan'
        ? 'plan_confirmation'
        : state === 'tool_approval'
          ? 'tool_approval'
          : state === 'unknown'
            ? 'recovery_decision'
            : 'none',
      state_version: stateVersion,
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
    tool_approval: state === 'tool_approval'
      ? { inbox_item_id: 'inbox_tool_e2e', call_id: 'research-tool:attempt:1', tool_name: 'web_research' }
      : null,
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
  let state = initialState
  let confirmCount = 0
  let executeCount = 0
  let approvalCount = 0
  const recoveryActions: string[] = []
  let releaseCompletion = () => {}
  const completionGate = new Promise<void>((resolve) => { releaseCompletion = resolve })

  await page.route('**/api/chat/skills', (route) => route.fulfill({ json: { items: [] } }))
  await page.route(`**/api/chat/threads/${THREAD_ID}`, (route) => route.fulfill({ json: thread() }))
  await page.route(`**/api/agent/runs/${RUN_ID}/events/stream**`, async (route) => {
    if (state !== 'running') {
      await route.fulfill({ status: 204, body: '' })
      return
    }
    await completionGate
    state = 'completed'
    const stepEvent = {
      id: 'event_research_step',
      run_id: RUN_ID,
      sequence: 1,
      event_type: 'research_step_completed',
      payload: { step_number: 1 },
      created_at: NOW,
    }
    const terminalEvent = {
      id: 'event_research_completed',
      run_id: RUN_ID,
      sequence: 2,
      event_type: 'run_completed',
      payload: {},
      created_at: NOW,
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `id: 1\nevent: research_step_completed\ndata: ${JSON.stringify(stepEvent)}\n\nid: 2\nevent: run_completed\ndata: ${JSON.stringify(terminalEvent)}\n\n`,
    })
  })
  await page.route(`**/api/agent/runs/${RUN_ID}/research**`, async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (url.pathname.endsWith(`/plans/${PLAN_ID}/confirm`) && method === 'POST') {
      confirmCount += 1
      state = 'confirmed'
      await route.fulfill({ status: 202, json: { run_id: RUN_ID, command_type: 'confirm_plan', state_version: 3, accepted: true, replayed: false } })
      return
    }
    if (url.pathname.endsWith('/execute') && method === 'POST') {
      executeCount += 1
      state = 'tool_approval'
      await route.fulfill({ status: 202, json: { run_id: RUN_ID, command_type: 'execute', state_version: 4, accepted: true, replayed: false } })
      return
    }
    if (url.pathname.endsWith('/recover') && method === 'POST') {
      const body = route.request().postDataJSON()
      recoveryActions.push(body.action)
      state = body.action === 'abort' ? 'aborted' : 'tool_approval'
      await route.fulfill({ status: 202, json: { run_id: RUN_ID, command_type: 'recover', state_version: 8, accepted: true, replayed: false } })
      return
    }
    if (method === 'GET' && url.pathname.endsWith('/research')) {
      await route.fulfill({ json: projection(state) })
      return
    }
    await route.continue()
  })
  await page.route('**/api/inbox/inbox_tool_e2e/resolve-tool-approval**', async (route) => {
    approvalCount += 1
    state = 'running'
    await route.fulfill({ json: { run_id: RUN_ID, attempt_id: ATTEMPT_ID, scheduled: true } })
  })
  await page.route(`**/api/agent/runs/${RUN_ID}`, async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { item: run(state) } })
      return
    }
    await route.continue()
  })

  return {
    releaseCompletion: () => releaseCompletion(),
    counts: () => ({ confirmCount, executeCount, approvalCount }),
    recoveryActions: () => [...recoveryActions],
  }
}

test('drives Plan Confirmation, independent Tool Approval, SSE progress, verified results, and refresh safely', async ({ page }) => {
  await enableRuntimeBootstrap(page, 'execute')
  const api = await installResearchApi(page, 'plan')
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
  await expect(page.getByRole('heading', { name: '确认研究计划' })).toBeVisible()
  await expect(page.getByText('不会批准工具调用，也不会访问 Provider')).toBeVisible()
  await expect(page.getByRole('heading', { name: '独立 Tool Approval' })).toHaveCount(0)

  await page.getByRole('button', { name: '确认此计划' }).click()
  await expect(page.getByRole('heading', { name: '计划已确认' })).toBeVisible()
  expect(api.counts()).toEqual({ confirmCount: 1, executeCount: 0, approvalCount: 0 })

  await page.getByRole('button', { name: '开始执行研究' }).click()
  await expect(page.getByRole('heading', { name: '独立 Tool Approval' })).toBeVisible()
  await expect(page.getByText('Provider 尚未被调用')).toBeVisible()
  expect(api.counts()).toEqual({ confirmCount: 1, executeCount: 1, approvalCount: 0 })

  await page.getByRole('button', { name: '批准工具调用' }).click()
  await expect(page.getByRole('heading', { name: '执行进度' })).toBeVisible()
  await expect(page.getByText('检索并封存外部证据').last()).toBeVisible()
  await expect(page.getByText('执行中').last()).toBeVisible()
  expect(api.counts()).toEqual({ confirmCount: 1, executeCount: 1, approvalCount: 1 })

  api.releaseCompletion()
  await expect(page.getByRole('heading', { name: '研究结果', exact: true })).toBeVisible()
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

  const countsBeforeRefresh = api.counts()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Verified competitive analysis' })).toBeVisible()
  expect(api.counts()).toEqual(countsBeforeRefresh)
})

for (const action of ['retry', 'abort'] as const) {
  test(`requires an explicit ${action} decision for UNKNOWN without automatic resend`, async ({ page }) => {
    await enableRuntimeBootstrap(page, 'execute')
    const api = await installResearchApi(page, 'unknown')
    await loginAs(page)

    await page.goto(`/workspace/thread/${THREAD_ID}?run=${RUN_ID}`)
    await expect(page.getByRole('heading', { name: '外部结果未知' })).toBeVisible()
    await expect(page.getByText('系统没有自动重试')).toBeVisible()
    expect(api.recoveryActions()).toEqual([])

    await page.getByRole('button', { name: action === 'retry' ? '确认后再次发送' : '安全终止' }).click()
    await expect.poll(api.recoveryActions).toEqual([action])
    if (action === 'retry') {
      await expect(page.getByRole('heading', { name: '独立 Tool Approval' })).toBeVisible()
    } else {
      await expect(page.getByRole('heading', { name: '研究已安全终止' })).toBeVisible()
    }
  })
}

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
  expect(api.counts()).toEqual({ confirmCount: 0, executeCount: 0, approvalCount: 0 })

  await page.goto('/workspace')
  await page.getByLabel('消息').fill('新的普通任务')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page).toHaveURL(new RegExp(`${compatThreadId}\\?run=${compatRunId}$`))
  expect(createBody).toMatchObject({ orchestration_mode: 'single' })
  await expect(page.getByLabel('研究任务预览')).toHaveCount(0)
  await expect(page.getByLabel('单 Skill 运行状态')).toContainText('状态：completed')
})
