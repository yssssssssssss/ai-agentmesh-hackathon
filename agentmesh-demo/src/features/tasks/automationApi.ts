import { apiRequest } from '../../api/client'
import type { components } from '../../api/generated/schema'

export type InspectionSchedule = Omit<components['schemas']['ScheduledAgentTaskDefinition'], 'id'> & { id: string }
export type InspectionSchedulePage = Omit<components['schemas']['ScheduledAgentTaskPageV1'], 'items'> & {
  items: InspectionSchedule[]
}
export type AutomationStatus = components['schemas']['AutomationStatusV1']
export type InspectionRunPage = components['schemas']['ScheduledRunPageV1']
export type InspectionRun = components['schemas']['ScheduledRunSummaryV1']
export type CreateSchedule = components['schemas']['ScheduledAgentTaskCreateRequest']
export type UpdateSchedule = components['schemas']['ScheduledAgentTaskUpdateRequest']
export type InspectionOccurrence = components['schemas']['ScheduledOccurrenceV1']

export const automationApi = {
  status: () => apiRequest<AutomationStatus>('/api/agents/scheduled-tasks/status'),
  list: (projectId: string, page = 1) => apiRequest<InspectionSchedulePage>(
    `/api/agents/scheduled-tasks?project_id=${encodeURIComponent(projectId)}&page=${page}&page_size=10&include_unvalidated=true`,
  ),
  create: (payload: CreateSchedule) => apiRequest<InspectionSchedule>('/api/agents/scheduled-tasks', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  update: (id: string, payload: UpdateSchedule) => apiRequest<InspectionSchedule>(
    `/api/agents/scheduled-tasks/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(payload) },
  ),
  runNow: (id: string, commandId: string, version: number) => apiRequest<InspectionOccurrence>(
    `/api/agents/scheduled-tasks/${encodeURIComponent(id)}/run-now`, {
      method: 'POST', body: JSON.stringify({ command_id: commandId, expected_version: version }),
    },
  ),
  runs: (id: string, page = 1) => apiRequest<InspectionRunPage>(
    `/api/agents/scheduled-tasks/${encodeURIComponent(id)}/runs?page=${page}&page_size=10`,
  ),
  report: (runId: string) => apiRequest<components['schemas']['ProjectInspectionReportV1']>(
    `/api/agents/inspection-runs/${encodeURIComponent(runId)}/report`,
  ),
}
