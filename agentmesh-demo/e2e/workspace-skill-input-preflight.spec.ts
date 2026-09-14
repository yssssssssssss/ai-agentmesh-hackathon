import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

const NOW = '2026-09-09T08:00:00Z'
const RUN_ID = 'run_skill_input_e2e'
const THREAD_ID = 'thread_skill_input_e2e'

function run(status: 'waiting_input' | 'running') {
  return {
    id: RUN_ID,
    thread_id: THREAD_ID,
    user_id: 'usr_current_designer',
    workspace_id: 'ws_home_appliance_design',
    project_id: 'prj_618_home_appliance',
    input_text: '$build-experience-metrics',
    status,
    skill_id: 'skill_metrics',
    skill_name: 'build-experience-metrics',
    plan_id: null,
    planning_mode: 'standard',
    orchestration_version: 'v1',
    orchestration_mode: 'execute',
    requested_orchestration_mode: 'single',
    agent_definition_version: '1',
    project_chat: true,
    tool_call_count: 0,
    error_code: null,
    created_at: NOW,
    updated_at: NOW,
  }
}

function inputRequest(artifactId?: string) {
  return {
    id: 'input_request_e2e',
    run_id: RUN_ID,
    plan_id: null,
    version: 1,
    schema_version: 'skill-input-request-v1',
    status: 'open',
    contract_snapshots: [{
      node_id: 'direct',
      skill_id: 'skill_metrics',
      skill_name: 'build-experience-metrics',
      skill_version: '1',
      skill_content_hash: 'a'.repeat(64),
      contract_hash: 'b'.repeat(64),
    }],
    fields: [
      {
        id: 'direct.product_goal',
        node_id: 'direct',
        skill_id: 'skill_metrics',
        skill_name: 'build-experience-metrics',
        field_id: 'product_goal',
        title: '产品与业务目标',
        description: '说明产品形态和核心目标',
        required: true,
        value_kind: 'text',
        multiple: false,
        accepted_media_types: [],
        required_columns: [],
        options: [],
        artifact_ids: [],
        status: 'missing',
        error_codes: [],
      },
      {
        id: 'direct.baseline_metrics',
        node_id: 'direct',
        skill_id: 'skill_metrics',
        skill_name: 'build-experience-metrics',
        field_id: 'baseline_metrics',
        title: '历史指标数据',
        description: '可选 CSV',
        required: false,
        value_kind: 'artifact',
        multiple: true,
        accepted_media_types: ['text/csv'],
        required_columns: [],
        options: [],
        artifact_ids: artifactId ? [artifactId] : [],
        status: artifactId ? 'satisfied' : 'missing',
        error_codes: [],
      },
    ],
    missing_required_field_ids: ['direct.product_goal'],
    next_run_status: 'running',
    created_at: NOW,
    updated_at: NOW,
    expires_at: '2026-09-10T08:00:00Z',
  }
}

test('collects text and CSV before allowing a Standard Skill to run', async ({ page }) => {
  await loginAs(page)
  let phase: 'waiting_input' | 'running' = 'waiting_input'
  let artifactId: string | undefined

  await page.route(`**/api/chat/threads/${THREAD_ID}`, (route) => route.fulfill({
    json: {
      thread: {
        id: THREAD_ID,
        workspace_id: 'ws_home_appliance_design',
        project_id: 'prj_618_home_appliance',
        user_id: 'usr_current_designer',
        title: 'Skill 输入验收',
        status: 'active',
        created_at: NOW,
        updated_at: NOW,
      },
      messages: [],
      turn_traces: [],
    },
  }))
  await page.route(`**/api/agent/runs/${RUN_ID}/events/stream**`, (route) => route.fulfill({
    status: 204,
    body: '',
  }))
  await page.route(`**/api/agent/runs/${RUN_ID}/input-request`, (route) => route.fulfill({
    json: {
      item: inputRequest(artifactId),
      artifacts: artifactId ? [{
        id: artifactId,
        run_id: RUN_ID,
        field_id: 'direct.baseline_metrics',
        file_name: 'baseline.csv',
        media_type: 'text/csv',
        byte_size: 24,
        content_hash: 'c'.repeat(64),
        status: 'ready',
        summary: { columns: ['date', 'value'], row_count: 1, column_count: 2 },
        error_code: null,
        created_at: NOW,
        updated_at: NOW,
      }] : [],
    },
  }))
  await page.route(`**/api/agent/runs/${RUN_ID}/input-artifacts`, async (route) => {
    expect(route.request().method()).toBe('POST')
    artifactId = 'input_artifact_e2e'
    await route.fulfill({
      json: {
        item: {
          id: artifactId,
          run_id: RUN_ID,
          field_id: 'direct.baseline_metrics',
          file_name: 'baseline.csv',
          media_type: 'text/csv',
          byte_size: 24,
          content_hash: 'c'.repeat(64),
          status: 'ready',
          summary: { columns: ['date', 'value'], row_count: 1, column_count: 2 },
          error_code: null,
          created_at: NOW,
          updated_at: NOW,
        },
      },
    })
  })
  await page.route(`**/api/agent/runs/${RUN_ID}/inputs`, async (route) => {
    const body = route.request().postDataJSON() as {
      text_values: Record<string, string>
      artifact_ids: Record<string, string[]>
      advance: boolean
    }
    expect(body.text_values['direct.product_goal']).toBe('提升新用户首周激活率')
    expect(body.artifact_ids['direct.baseline_metrics']).toEqual(['input_artifact_e2e'])
    expect(body.advance).toBe(true)
    phase = 'running'
    await route.fulfill({
      json: {
        run: run(phase),
        input_request: { ...inputRequest(artifactId), version: 2, status: 'complete', missing_required_field_ids: [] },
        artifacts: [],
      },
    })
  })
  await page.route(`**/api/agent/runs/${RUN_ID}`, (route) => route.fulfill({
    json: { item: run(phase), memory_uses: [] },
  }))

  await page.goto(`/workspace/thread/${THREAD_ID}?run=${RUN_ID}`)
  await expect(page.getByRole('heading', { name: '执行前需要补充资料' })).toBeVisible()
  await expect(page.getByLabel('消息')).toBeDisabled()
  await expect(page.getByLabel('消息')).toHaveAttribute('placeholder', '请先完成上方资料补充')

  await page.getByLabel('产品与业务目标').fill('提升新用户首周激活率')
  await page.getByText('可选资料（不影响继续）').click()
  await page.getByLabel('历史指标数据').setInputFiles({
    name: 'baseline.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('date,value\n2026-09-01,12\n'),
  })
  await expect(page.getByText('baseline.csv')).toBeVisible()
  await page.getByRole('button', { name: '资料齐全，继续' }).click()

  await expect(page.getByRole('heading', { name: '执行前需要补充资料' })).toHaveCount(0)
  await expect(page.getByLabel('单 Skill 运行状态')).toContainText('正在执行')
})
