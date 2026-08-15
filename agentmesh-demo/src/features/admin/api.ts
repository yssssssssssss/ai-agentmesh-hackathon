import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiRequest } from '../../api/client'
import type { components } from '../../api/generated/schema'
import { queryKeys, type AdminAuditFilters, type AdminQueryScope } from '../../app/queryKeys'

export const ADMIN_CAPABILITIES = {
  users: 'manage_users',
  agents: 'manage_public_agent',
  providers: 'view_provider_health',
  o2: 'sync_o2',
  permissionPolicies: 'view_permission_policies',
  riskPolicies: 'manage_risk_policies',
  audit: 'view_audit',
  permissionPolicyManagement: 'manage_permission_policies',
} as const

export type AdminCapability = (typeof ADMIN_CAPABILITIES)[keyof typeof ADMIN_CAPABILITIES]
export type Agent = components['schemas']['Agent']
export type ModelDefinition = components['schemas']['ModelDefinition']
export type ToolDefinition = components['schemas']['ToolDefinition']
export type User = components['schemas']['User']
export type UserCreateRequest = components['schemas']['UserCreateRequest']
export type PermissionPolicyRule = components['schemas']['PermissionPolicyRule']
export type RiskPolicyRule = components['schemas']['RiskPolicyRule']
export type AuditListResponse = components['schemas']['AuditListResponse']
export type ProviderHealthCheckResponse = components['schemas']['ProviderHealthCheckResponse']
export type O2StatusResponse = components['schemas']['O2StatusResponse']
export type O2SyncResponse = components['schemas']['O2SyncResponse']

type UsersResponse = components['schemas']['UsersResponse']
type UserItemResponse = components['schemas']['UserItemResponse']
type AgentsResponse = components['schemas']['AgentsResponse']
type ModelsResponse = components['schemas']['ModelsResponse']
type ToolsResponse = components['schemas']['ToolsResponse']
type PermissionPoliciesResponse = components['schemas']['PermissionPoliciesResponse']
type RiskPoliciesResponse = components['schemas']['RiskPoliciesResponse']
type StatusResponse = components['schemas']['StatusResponse']

export function hasCapability(capabilities: readonly string[], capability: AdminCapability) {
  return capabilities.includes(capability)
}

export function useUsersAdmin(context: AdminQueryScope, enabled: boolean) {
  const queryClient = useQueryClient()
  const queryKey = [...queryKeys.admin.root(context), 'users'] as const
  const query = useQuery({
    queryKey,
    queryFn: () => apiRequest<UsersResponse>('/api/users'),
    enabled,
  })
  const create = useMutation({
    mutationFn: (request: UserCreateRequest) =>
      apiRequest<UserItemResponse>('/api/users', { method: 'POST', body: JSON.stringify(request) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  })
  const disable = useMutation({
    mutationFn: (userId: string) =>
      apiRequest<UserItemResponse>(`/api/users/${encodeURIComponent(userId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'disabled' }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  })
  const resetPassword = useMutation({
    mutationFn: ({ userId, newPassword }: { userId: string; newPassword: string }) =>
      apiRequest<StatusResponse>(`/api/users/${encodeURIComponent(userId)}/password`, {
        method: 'POST',
        body: JSON.stringify({ new_password: newPassword }),
      }),
  })
  return { query, create, disable, resetPassword }
}

export function useAgentAdmin(context: AdminQueryScope, enabled: boolean) {
  const queryClient = useQueryClient()
  const rootKey = [...queryKeys.admin.root(context), 'agents'] as const
  const agents = useQuery({
    queryKey: rootKey,
    queryFn: () => apiRequest<AgentsResponse>('/api/agents'),
    enabled,
  })
  const models = useQuery({
    queryKey: [...queryKeys.admin.root(context), 'models'],
    queryFn: () => apiRequest<ModelsResponse>('/api/models'),
    enabled,
  })
  const tools = useQuery({
    queryKey: [...queryKeys.admin.root(context), 'tools'],
    queryFn: () => apiRequest<ToolsResponse>('/api/tools'),
    enabled,
  })
  const updateModel = useMutation({
    mutationFn: ({ agentId, modelId }: { agentId: string; modelId: string | null }) =>
      apiRequest<Agent>(`/api/agents/${encodeURIComponent(agentId)}/model`, {
        method: 'PATCH',
        body: JSON.stringify({ model_id: modelId }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: rootKey }),
  })
  const updateTools = useMutation({
    mutationFn: ({ agentId, toolIds }: { agentId: string; toolIds: string[] }) =>
      apiRequest<ToolsResponse>(`/api/agents/${encodeURIComponent(agentId)}/tools`, {
        method: 'PATCH',
        body: JSON.stringify({ tool_ids: toolIds }),
      }),
    onSuccess: (_, variables) =>
      queryClient.invalidateQueries({ queryKey: [...rootKey, variables.agentId, 'tools'] }),
  })

  return { agents, models, tools, updateModel, updateTools }
}

export function useAgentToolsAdmin(
  context: AdminQueryScope,
  agentId: string | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: [...queryKeys.admin.root(context), 'agents', agentId, 'tools'],
    queryFn: () => apiRequest<ToolsResponse>(`/api/agents/${encodeURIComponent(agentId ?? '')}/tools`),
    enabled: enabled && Boolean(agentId),
  })
}

export function useProviderAdmin(
  context: AdminQueryScope,
  providerEnabled: boolean,
  o2Enabled: boolean,
) {
  const queryClient = useQueryClient()
  const providerKey = [...queryKeys.admin.root(context), 'providers'] as const
  const o2Key = [...queryKeys.admin.root(context), 'o2'] as const
  const providers = useQuery({
    queryKey: providerKey,
    queryFn: () => apiRequest<ProviderHealthCheckResponse>('/api/health/providers'),
    enabled: providerEnabled,
  })
  const o2 = useQuery({
    queryKey: o2Key,
    queryFn: () => apiRequest<O2StatusResponse>('/api/integrations/o2/status'),
    enabled: o2Enabled,
  })
  const sync = useMutation({
    mutationFn: () => apiRequest<O2SyncResponse>('/api/integrations/o2/sync', { method: 'POST' }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: providerKey }),
        queryClient.invalidateQueries({ queryKey: o2Key }),
        queryClient.invalidateQueries({ queryKey: [...queryKeys.admin.root(context), 'tools'] }),
      ]),
  })
  return { providers, o2, sync }
}

export function usePolicyAdmin(
  context: AdminQueryScope,
  permissionPoliciesEnabled: boolean,
  riskPoliciesEnabled: boolean,
) {
  const permissionPolicies = useQuery({
    queryKey: [...queryKeys.admin.root(context), 'permission-policies'],
    queryFn: () => apiRequest<PermissionPoliciesResponse>('/api/users/permission-policies'),
    enabled: permissionPoliciesEnabled,
  })
  const riskPolicies = useQuery({
    queryKey: [...queryKeys.admin.root(context), 'risk-policies'],
    queryFn: () => apiRequest<RiskPoliciesResponse>('/api/risk/policies'),
    enabled: riskPoliciesEnabled,
  })
  return { permissionPolicies, riskPolicies }
}

export function useAuditAdmin(
  context: AdminQueryScope,
  filters: AdminAuditFilters,
  enabled: boolean,
) {
  const normalizedFilters = {
    action: filters.action?.trim() || undefined,
    targetType: filters.targetType?.trim() || undefined,
  }
  return useQuery({
    queryKey: queryKeys.admin.audit(context, normalizedFilters),
    queryFn: () => {
      const params = new URLSearchParams({ limit: '100' })
      if (normalizedFilters.action) params.set('action', normalizedFilters.action)
      if (normalizedFilters.targetType) params.set('target_type', normalizedFilters.targetType)
      return apiRequest<AuditListResponse>(`/api/audit?${params.toString()}`)
    },
    enabled,
  })
}
