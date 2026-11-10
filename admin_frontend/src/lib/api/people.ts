import { apiRequest } from './client';

/** A person in the family list (Phase 6). */
export type Person = {
  person_id: string;
  name: string;
  /** What Hiro calls them; "" = their name. */
  calls_them: string;
  /** Digits with the country code; "" = none. */
  whatsapp: string;
  role_id: string;
  /** The admin sign-in name; null = they don't use the admin. */
  sign_in: string | null;
  has_sign_in: boolean;
  created_at: string;
  updated_at: string;
};

export type Role = {
  role_id: string;
  name: string;
  built_in: boolean;
  /** Phase 8: people with this role can open HiroLeague's settings (Owner always). */
  admin: boolean;
  /** Phase 9a: one line on what the role is for. */
  says: string;
};

export type PeopleData = { people: Person[]; roles: Role[] };

export type PersonFields = {
  name: string;
  role_id: string;
  calls_them: string;
  whatsapp: string;
};

export async function listPeople() {
  return apiRequest<PeopleData>('/people');
}

export async function addPerson(fields: PersonFields) {
  return apiRequest<{ person: Person }>('/people', { method: 'POST', body: fields });
}

export async function updatePerson(personId: string, fields: Partial<PersonFields>) {
  return apiRequest<{ person: Person }>(`/people/${encodeURIComponent(personId)}`, { method: 'PUT', body: fields });
}

export async function removePerson(personId: string) {
  return apiRequest<{ removed: string }>(`/people/${encodeURIComponent(personId)}`, { method: 'DELETE' });
}

export async function setSignIn(personId: string, signInName: string, password: string) {
  return apiRequest<{ person: Person }>(`/people/${encodeURIComponent(personId)}/sign-in`, {
    method: 'PUT',
    body: { sign_in: signInName, password }
  });
}

export async function removeSignIn(personId: string) {
  return apiRequest<{ person: Person }>(`/people/${encodeURIComponent(personId)}/sign-in`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// Phase 9a: what each role may do, per source (HiroLeague and each extension).
// ---------------------------------------------------------------------------

export type AccessRight = { id: string; name: string; says: string };
export type AccessFeature = { id: string; name: string; rights: AccessRight[]; not_for_owner: boolean };
export type AccessSource = {
  /** "hiroleague", or the extension's name (its rights are kept under it). */
  id: string;
  name: string;
  kind: 'core' | 'extension';
  extension_id: string;
  connected: boolean;
  features: AccessFeature[];
};
/** A role with its rights in every source: {source id: ["<feature>.<right>", ...]}. */
export type RoleAccess = Role & { rights: Record<string, string[]> };
export type AccessData = { sources: AccessSource[]; roles: RoleAccess[] };

export async function listAccess() {
  return apiRequest<AccessData>('/people/access');
}

export async function setRoleRights(roleId: string, source: string, rights: string[]) {
  return apiRequest<{ role: Role }>(`/roles/${encodeURIComponent(roleId)}/rights/${encodeURIComponent(source)}`, {
    method: 'PUT',
    body: { rights }
  });
}

export async function setRoleSays(roleId: string, says: string) {
  return apiRequest<{ role: Role }>(`/roles/${encodeURIComponent(roleId)}/says`, { method: 'PUT', body: { says } });
}

export async function addRole(name: string) {
  return apiRequest<{ role: Role }>('/roles', { method: 'POST', body: { name } });
}

export async function renameRole(roleId: string, name: string) {
  return apiRequest<{ role: Role }>(`/roles/${encodeURIComponent(roleId)}`, { method: 'PUT', body: { name } });
}

export async function removeRole(roleId: string) {
  return apiRequest<{ removed: string }>(`/roles/${encodeURIComponent(roleId)}`, { method: 'DELETE' });
}
