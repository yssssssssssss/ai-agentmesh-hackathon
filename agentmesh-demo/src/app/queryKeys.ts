export interface QueryScope {
  userId: string
  workspaceId: string
  projectId: string
}

export interface AdminQueryScope {
  userId: string
  workspaceId: string
}

export interface AdminAuditFilters {
  action?: string
  targetType?: string
}

const scope = ({ userId, workspaceId, projectId }: QueryScope) => [userId, workspaceId, projectId] as const

export const queryRoots = {
  inbox: ['inbox'] as const,
  memory: ['memory'] as const,
  documents: ['documents'] as const,
  tasks: ['tasks'] as const,
  audit: ['audit'] as const,
  workspace: ['workspace'] as const,
} as const

export const queryKeys = {
  inbox: {
    root: queryRoots.inbox,
    list: (context: QueryScope, includeSnoozed: boolean) =>
      [...queryRoots.inbox, ...scope(context), includeSnoozed] as const,
  },
  memory: {
    root: queryRoots.memory,
    list: (context: QueryScope) => [...queryRoots.memory, ...scope(context)] as const,
    overview: (context: QueryScope) => [...queryRoots.memory, 'overview', ...scope(context)] as const,
  },
  documents: {
    root: queryRoots.documents,
    list: (context: QueryScope) => [...queryRoots.documents, ...scope(context)] as const,
    detail: (context: QueryScope, documentId: string) =>
      [...queryRoots.documents, ...scope(context), documentId] as const,
  },
  tasks: {
    root: queryRoots.tasks,
    cards: (context: QueryScope) => [...queryRoots.tasks, 'cards', ...scope(context)] as const,
    management: (context: QueryScope) => [...queryRoots.tasks, 'management', ...scope(context)] as const,
    managedDetail: (context: QueryScope, taskId: string) =>
      [...queryRoots.tasks, 'management-detail', ...scope(context), taskId] as const,
    detail: (context: QueryScope, taskId: string) =>
      [...queryRoots.tasks, 'detail', ...scope(context), taskId] as const,
  },
  audit: {
    root: queryRoots.audit,
  },
  workspace: {
    root: queryRoots.workspace,
    scoped: (context: QueryScope) => [...queryRoots.workspace, ...scope(context)] as const,
  },
  digitalSelf: {
    agent: (userId: string, workspaceId: string, projectId: string) =>
      ['agent', 'digital-self', userId, workspaceId, projectId] as const,
  },
  insights: {
    tasks: (userId: string, workspaceId: string, projectId: string) =>
      [...queryRoots.tasks, 'insights', userId, workspaceId, projectId] as const,
    activity: (userId: string, workspaceId: string, projectId: string) =>
      ['activity', 'insights', userId, workspaceId, projectId] as const,
    memory: (userId: string, workspaceId: string, projectId: string) =>
      [...queryRoots.memory, 'insights', userId, workspaceId, projectId] as const,
    audit: (userId: string, workspaceId: string, projectId: string) =>
      [...queryRoots.audit, 'insights', userId, workspaceId, projectId] as const,
  },
  admin: {
    root: ({ userId, workspaceId }: AdminQueryScope) => ['admin', userId, workspaceId] as const,
    auditRoot: ({ userId, workspaceId }: AdminQueryScope) =>
      [...queryRoots.audit, 'admin', userId, workspaceId] as const,
    audit: ({ userId, workspaceId }: AdminQueryScope, filters: AdminAuditFilters = {}) =>
      [
        ...queryRoots.audit,
        'admin',
        userId,
        workspaceId,
        { action: filters.action ?? '', targetType: filters.targetType ?? '' },
      ] as const,
  },
} as const
