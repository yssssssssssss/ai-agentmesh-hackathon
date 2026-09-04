import { expect, test } from '@playwright/test'

import { loginAs } from './support/auth'

test('shows durable Memory use receipts on the owning Run', async ({ page }) => {
  const runId = 'run-memory-use-ui'
  await page.route(`**/api/agent/runs/${runId}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    json: {
      item: {
        id: runId,
        thread_id: 'thread_graph_demo',
        task_id: 'task-memory-use-ui',
        user_id: 'usr_current_designer',
        workspace_id: 'ws_home_appliance_design',
        project_id: 'prj_618_home_appliance',
        input_text: '复用首屏入口经验',
        status: 'completed',
        skill_id: null,
        skill_name: null,
        plan_id: null,
        retry_of_run_id: null,
        planning_mode: 'standard',
        planning_contract_version: null,
        execution_contract_version: null,
        orchestration_version: 'v1',
        orchestration_mode: 'off',
        requested_orchestration_mode: 'single',
        agent_definition_version: '1',
        project_chat: true,
        tool_call_count: 0,
        output_text: '采用既有入口规则 [T1]',
        created_at: '2026-09-03T00:00:00Z',
        updated_at: '2026-09-03T00:01:00Z',
      },
      memory_uses: [{
        receipt: {
          schema_version: 'memory-use-receipt-v1',
          id: 'memory-use-ui-1',
          run_id: runId,
          task_id: 'task-memory-use-ui',
          memory_id: 'memory-ui-1',
          memory_kind: 'team',
          memory_layer: 'long_term',
          memory_record_type: 'memory_item',
          memory_version: 2,
          memory_hash: 'a'.repeat(64),
          retrieval_reason: 'automatic_run_context',
          retrieval_query_hash: 'b'.repeat(64),
          citation_label: 'T1',
          agent_id: 'agent_personal_current',
          source_ids: ['source-ui-1'],
          created_at: '2026-09-03T00:00:30Z',
        },
        title: '首屏入口数量控制',
        scope: 'team_accepted',
        layer: 'long_term',
        sources: [{
          id: 'source-ui-1',
          title: '618 首屏复盘',
          source_type: 'task_artifact',
          reference: 'artifact://source-ui-1',
          created_at: '2026-09-02T00:00:00Z',
        }],
        cited_in_output: true,
        memory_navigation_href: '/knowledge?project=prj_618_home_appliance&memory=memory-ui-1',
        task_navigation_href: '/tasks?task=task-memory-use-ui',
      }],
    },
  }))

  await loginAs(page)
  await page.goto(`/workspace/thread/thread_graph_demo?run=${runId}`)

  const panel = page.getByRole('region', { name: '本次使用的记忆' })
  await expect(panel).toContainText('[T1]')
  await expect(panel).toContainText('首屏入口数量控制')
  await expect(panel).toContainText('v2')
  await expect(panel).toContainText('输出已引用')
  await expect(panel).toContainText('原始来源：618 首屏复盘')
  await expect(panel.getByRole('link', { name: '查看记忆' })).toHaveAttribute(
    'href',
    '/knowledge?project=prj_618_home_appliance&memory=memory-ui-1',
  )
})
