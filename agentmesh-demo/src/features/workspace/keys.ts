import type { WorkspaceScope } from './types'

const scopedRoot = ({ userId, workspaceId, projectId }: WorkspaceScope) => [
  'workspace',
  userId,
  workspaceId,
  projectId,
] as const

export const workspaceKeys = {
  root: (scope: WorkspaceScope) => scopedRoot(scope),
  threads: (scope: WorkspaceScope) => [...scopedRoot(scope), 'threads'] as const,
  thread: (scope: WorkspaceScope, threadId: string) => [...scopedRoot(scope), 'threads', threadId] as const,
  skills: (scope: WorkspaceScope) => [...scopedRoot(scope), 'skills'] as const,
  skillCatalog: (scope: WorkspaceScope) => [...scopedRoot(scope), 'skill-catalog'] as const,
  runRoot: (scope: WorkspaceScope) => [...scopedRoot(scope), 'agent-runs'] as const,
  run: (scope: WorkspaceScope, runId: string) => [...scopedRoot(scope), 'agent-runs', runId] as const,
  plan: (scope: WorkspaceScope, runId: string) =>
    [...scopedRoot(scope), 'agent-runs', runId, 'plan'] as const,
  documents: (scope: WorkspaceScope) => [...scopedRoot(scope), 'documents'] as const,
  document: (scope: WorkspaceScope, documentId: string) =>
    [...scopedRoot(scope), 'documents', documentId] as const,
  jobs: (scope: WorkspaceScope) => [...scopedRoot(scope), 'document-jobs'] as const,
  job: (scope: WorkspaceScope, jobId: string) => [...scopedRoot(scope), 'document-jobs', jobId] as const,
  searchRoot: (scope: WorkspaceScope) => [...scopedRoot(scope), 'search'] as const,
  search: (scope: WorkspaceScope, query: string) => [...scopedRoot(scope), 'search', query] as const,
}
