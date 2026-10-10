import type { components } from '../../api/generated/schema'

export interface ProcedureTaskDraft {
  projectId: string
  title: string
  description: string
}

export function procedureTaskDraft(projectId: string, procedure: components['schemas']['ProcedureMemoryV1']): ProcedureTaskDraft | null {
  const goal = procedure.goal_patterns.find((value) => value.trim())?.trim()
  if (!goal || !procedure.human_confirmed_by || !procedure.successful_runs?.length) return null
  return { projectId, title: goal.slice(0, 200), description: goal }
}

export function taskDraftFromLocation(state: unknown, projectId: string): ProcedureTaskDraft | null {
  if (!state || typeof state !== 'object' || !('taskDraft' in state)) return null
  const draft = state.taskDraft
  if (!draft || typeof draft !== 'object' || !('projectId' in draft) || !('title' in draft) || !('description' in draft)
    || draft.projectId !== projectId || typeof draft.title !== 'string' || typeof draft.description !== 'string'
    || !draft.title.trim() || draft.title.length > 200 || draft.description.length > 4000) return null
  return { projectId, title: draft.title, description: draft.description }
}
