import type { components } from '../../api/generated/schema'
import { apiRequest } from '../../api/client'

export type User = components['schemas']['User']
export type BootstrapState = components['schemas']['BootstrapState']
type UserResponse = components['schemas']['UserResponse']
type StatusResponse = components['schemas']['StatusResponse']

export const authApi = {
  me: async () => (await apiRequest<UserResponse>('/api/auth/me')).user,
  bootstrap: () => apiRequest<BootstrapState>('/api/bootstrap'),
  login: async (userId: string, password: string) =>
    (
      await apiRequest<UserResponse>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, password }),
      })
    ).user,
  logout: () => apiRequest<StatusResponse>('/api/auth/logout', { method: 'POST' }),
}
