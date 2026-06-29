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
  /**
   * Display label for the field, sourced from the backend `Field(title=…)` (Pydantic auto-derives
   * one from the field name when unset). The `Pref*` field widgets render this when no explicit
   * `label` prop is given, and the Settings search indexes it. Single source of truth for labels.
   */
  title?: string;
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
