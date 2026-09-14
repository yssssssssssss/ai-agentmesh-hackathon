import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

const NOW = '2026-09-10T08:00:00Z'
const RUN_ID = 'run_workspace_memory_e2e'
const THREAD_ID = 'thread_workspace_memory_e2e'
const MEMORY_ID = 'memory_run_output_workspace_e2e'

function run() {
  return {
    id: RUN_ID,
    thread_id: THREAD_ID,
    user_id: 'usr_current_designer',
    workspace_id: 'ws_home_appliance_design',
    project_id: 'prj_618_home_appliance',
    input_text: '复用结算页地址编辑经验',
    status: 'completed',
    skill_id: null,
    skill_name: null,
    plan_id: null,
    planning_mode: 'standard',
    orchestration_version: 'v1',
    orchestration_mode: 'off',
    requested_orchestration_mode: 'single',
    agent_definition_version: '1',
    project_chat: true,
    tool_call_count: 0,
    output_text: '沿用已验证结论，保留地址编辑入口 [P1]。',
    error_code: null,
    created_at: NOW,
    updated_at: NOW,
  }
}

const memoryUse = {
  receipt: {
    schema_version: 'memory-use-receipt-v1',
    id: 'memory_use_workspace_e2e',
    run_id: RUN_ID,
    task_id: null,
    memory_id: 'memory_source_workspace_e2e',
    memory_kind: 'personal',
    memory_layer: 'short_term',
    memory_record_type: 'user_memory_item',
    memory_version: 1,
    memory_hash: 'a'.repeat(64),
    retrieval_reason: 'automatic_run_context',
    retrieval_query_hash: 'b'.repeat(64),
    citation_label: 'P1',
    agent_id: 'agent_personal_current',
    source_ids: [],
    created_at: NOW,
  },
  title: '结算页地址编辑经验',
  scope: 'private',
  layer: 'short_term',
  sources: [],
  cited_in_output: true,
  memory_navigation_href: '/knowledge?memory=memory_source_workspace_e2e',
  task_navigation_href: null,
}

test('shows reused Memory and lets the owner save a completed Workspace result', async ({ page }) => {
  await loginAs(page)
  let saved = false

  await page.route(`**/api/chat/threads/${THREAD_ID}`, (route) => route.fulfill({
    json: {
      thread: {
        id: THREAD_ID,
        workspace_id: 'ws_home_appliance_design',
        project_id: 'prj_618_home_appliance',
        user_id: 'usr_current_designer',
        title: 'Workspace Memory 验收',
        status: 'active',
        created_at: NOW,
        updated_at: NOW,
      },
      messages: [],
      turn_traces: [],
    },
  }))
  await page.route(`**/api/agent/runs/${RUN_ID}/memory`, async (route) => {
    expect(route.request().method()).toBe('POST')
    const payload = route.request().postDataJSON() as { title?: string }
    expect(payload.title).toBe('Workspace Memory 验收')
    saved = true
    await route.fulfill({
      json: {
        item: {
          id: MEMORY_ID,
          user_id: 'usr_current_designer',
          layer: 'short_term',
          title: payload.title,
          summary: run().output_text,
          source_kind: 'agent_run_manual',
          memory_type: 'run_output',
          memory_date: '2026-09-10',
          sensitivity: 'normal',
          scope: 'private',
          workspace_id: 'ws_home_appliance_design',
          project_id: 'prj_618_home_appliance',
          source_thread_id: THREAD_ID,
          status: 'active',
          version: 1,
          created_at: NOW,
          updated_at: NOW,
        },
      },
    })
  })
  await page.route(`**/api/agent/runs/${RUN_ID}`, (route) => route.fulfill({
    json: {
      item: run(),
      memory_uses: [memoryUse],
      memory_item_id: saved ? MEMORY_ID : null,
      memory_disposition: saved ? 'projected' : 'policy_skipped',
    },
  }))

  await page.goto(`/workspace/thread/${THREAD_ID}?run=${RUN_ID}`)
  await expect(page.getByRole('heading', { name: '本次使用的记忆' })).toBeVisible()
  await expect(page.getByText('[P1]')).toBeVisible()
  await expect(page.getByText('输出已引用')).toBeVisible()
  await expect(page.getByText('本次结果尚未保存到记忆')).toBeVisible()

  await page.getByRole('button', { name: '保存到个人记忆' }).click()

  await expect(page.getByText('已保存到个人短期记忆')).toBeVisible()
  await expect(page.getByRole('button', { name: '查看记忆' })).toBeVisible()
})
