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
