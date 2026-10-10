import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { InspectionSchedule } from '../../features/tasks/automationApi'
import { AutomationScheduleList } from './AutomationSchedulePanel'

const schedule: InspectionSchedule = {
  id: 'schedule-1', title: '早间进展', prompt: 'Project inspection: daily_progress', schedule: '30 9 * * *',
  agent_id: 'agent-1', created_by: 'owner', owner_user_id: 'owner', template_id: 'daily_progress',
  timezone: 'Asia/Shanghai', validation_state: 'valid', version: 1, enabled: true,
  next_run_at: '2030-01-02T01:30:00Z',
  misfire_policy: 'coalesce_latest', overlap_policy: 'skip',
  on_project_changes: false,
}
const actions = { onToggle: () => {}, onRun: () => {}, onHistory: () => {}, onEdit: () => {} }

describe('automatic inspection configuration', () => {
  it('shows explicit task and review change opt-in without implying unrestricted automatic runs', () => {
    const markup = renderToStaticMarkup(<AutomationScheduleList {...actions}
      schedules={[{ ...schedule, on_project_changes: true }]}
      status={{ mode: 'off', runtime_available: true, running: true }} userId="owner" busy={false} />)
    expect(markup).toContain('同时巡检任务与审核变化')
    expect(markup).toContain('至少间隔五分钟')
    expect(markup).toContain('自动执行已关闭')
    expect(markup).toContain('disabled="">立即巡检')
  })

  it('distinguishes an enabled configuration from automation being turned off', () => {
    const markup = renderToStaticMarkup(<AutomationScheduleList {...actions} schedules={[schedule]}
      status={{ mode: 'off', runtime_available: true, running: true }} userId="owner" busy={false} />)
    expect(markup).toContain('配置已启用')
    expect(markup).toContain('自动执行已关闭')
    expect(markup).toContain('01/02 09:30')
    expect(markup).toContain('disabled="">立即巡检')
    expect(markup).toContain('我的 Agent 执行')
    expect(markup).not.toContain('正在读取')
  })

  it('makes legacy definitions require explicit binding even in execute mode', () => {
    const markup = renderToStaticMarkup(<AutomationScheduleList {...actions}
      schedules={[{ ...schedule, validation_state: 'legacy_schedule_unvalidated', next_run_at: null }]}
      status={{ mode: 'execute', runtime_available: true, running: true }} userId="owner" busy={false} />)
    expect(markup).toContain('需要重新绑定项目与模板')
    expect(markup).toContain('重新绑定')
    expect(markup).toContain('disabled="">立即巡检')
  })
})
