// Settings → Users and Roles (every Hiro backend's auth/api.py), owners only.
import { api } from '$kit/api/client';
import type { AppUser, Roles, UserChange } from './types';

export const getUsers = (signal?: AbortSignal) => api<AppUser[]>('users', { signal });
export const saveUser = (id: string, change: UserChange) => api<AppUser[]>(`users/${encodeURIComponent(id)}`, { method: 'PUT', body: change });

// Roles are read-only in the apps since Phase 9a: they change in HiroLeague.
export const getRoles = (signal?: AbortSignal) => api<Roles>('roles', { signal });
/** HiroLeague's People → Roles, opened at one role when given; "" while the core's admin address is unknown. */
export const coreRolesUrl = (adminUrl: string | null | undefined, roleId?: string) =>
	adminUrl ? `${adminUrl}/people/?tab=roles${roleId ? `&role=${encodeURIComponent(roleId)}` : ''}` : '';
