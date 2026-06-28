import { apiRequest, type ApiResponse } from './client';

export type PreferenceFieldMeta = {
  path: string;
  type?: string;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  enum?: string[];
  nullable?: boolean;
  description?: string;
  readOnly?: boolean;
  writeWhole?: boolean;
  preferencesSaveSkip?: boolean;
  model_kind?: string;
  /** Display-only: when true the admin UI hides this field behind the "show advanced" toggle. */
  advanced?: boolean;
};

export type PreferencesSchemaPayload = {
  preferences_version: number;
  fields: Record<string, PreferenceFieldMeta>;
};

export async function getPreferencesSchema(): Promise<ApiResponse<PreferencesSchemaPayload>> {
  return apiRequest<PreferencesSchemaPayload>('/preferences/schema');
}
