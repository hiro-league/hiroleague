import { apiRequest, type ApiResponse } from './client';

export type ModalityFlags = {
  voice: boolean;
  image: boolean;
  video: boolean;
  file: boolean;
};

export type ModelTuning = {
  temperature: number;
  max_tokens: number;
};

export type WorkspacePreferences = {
  version: number;
  llm: {
    default_chat: string | null;
    default_stt: string | null;
    default_tts: string | null;
    tuning: Record<string, ModelTuning>;
  };
  media: {
    input: ModalityFlags;
    output: ModalityFlags;
  };
  memory: {
    max_messages: number;
  };
};

export type PreferenceSection = {
  key: string;
  label: string;
  description: string;
};

export type PreferencesPayload = {
  preferences: WorkspacePreferences;
  sections: PreferenceSection[];
};

export type PreferencesPatchPayload = PreferencesPayload & {
  changed: string[];
};

export async function getPreferences(): Promise<ApiResponse<PreferencesPayload>> {
  return apiRequest<PreferencesPayload>('/preferences');
}

export async function patchPreferences(
  edits: Record<string, unknown>
): Promise<ApiResponse<PreferencesPatchPayload>> {
  return apiRequest<PreferencesPatchPayload>('/preferences', {
    method: 'PATCH',
    body: { edits }
  });
}
