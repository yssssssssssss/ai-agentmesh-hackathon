import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { ProjectInspectionReport } from '../../features/tasks/types'
import { ProjectInspectionView } from './ProjectInspectionPanel'

const report: ProjectInspectionReport = {
  schema_version: 'project-inspection-v1',
  project_id: 'project-1', template_id: 'blockers', snapshot_at: '2030-01-02T00:00:00Z',
  since: '2030-01-01T00:00:00Z', data_mode: 'real', outcome: 'completed',
  source_watermarks: { tasks: { record_count: 1, latest_updated_at: '2030-01-01T00:00:00Z' } },
  blockers: [{
    task_id: 'task-1', title: '等待设计交付', delivery_stage: 'in_progress',
    reasons: ['blocked', 'overdue'], blocked_reason: '缺少已审核的材料',
    updated_at: '2030-01-01T00:00:00Z', navigation_href: '/tasks?task=task-1',
  }],
  actual_providers: ['local_task_store'],
}

describe('project inspections', () => {
  it('shows real task evidence, risks and an explicit action link', () => {
    const markup = renderToStaticMarkup(<ProjectInspectionView
      report={report} loading={false} error={null} onInspect={() => {}}
    />)
    expect(markup).toContain('项目巡检')
    expect(markup).toContain('真实项目数据')
    expect(markup).toContain('巡检完成')
    expect(markup).toContain('等待设计交付')
    expect(markup).toContain('缺少已审核的材料')
    expect(markup).toContain('已逾期')
    expect(markup).toContain('href="/tasks?task=task-1"')
    expect(markup).toContain('来源记录')
  })

  it('shows missing history as insufficient evidence without inventing progress', () => {
    const markup = renderToStaticMarkup(<ProjectInspectionView
      report={{ ...report, outcome: 'insufficient_evidence', blockers: [], missing_data: ['task_history_incomplete'] }}
      loading={false} error={null} onInspect={() => {}}
    />)
    expect(markup).toContain('资料不足')
    expect(markup).toContain('无法判断其历史变化')
    expect(markup).not.toContain('巡检完成')
    expect(markup).not.toContain('等待设计交付')
  })

  it('hides earlier reports while querying or after a failed query', () => {
    const loading = renderToStaticMarkup(<ProjectInspectionView
      report={report} loading error={null} onInspect={() => {}}
    />)
    const failed = renderToStaticMarkup(<ProjectInspectionView
      report={report} loading={false} error="项目不可访问" onInspect={() => {}}
    />)
    expect(loading).toContain('正在核对项目记录')
    expect(loading).toContain('disabled')
    expect(loading).not.toContain('巡检完成')
    expect(failed).toContain('项目不可访问')
    expect(failed).not.toContain('等待设计交付')
  })
})
