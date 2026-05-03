import { apiRequest, type ApiResponse } from './client';

export type CharacterRow = {
  id: string;
  name: string;
  description?: string | null;
  is_default?: boolean;
  has_photo?: boolean;
  photo_data_url?: string | null;
  photo_error?: string | null;
  error?: string | null;
};

export type CharacterDetail = CharacterRow & {
  prompt?: string | null;
  backstory?: string | null;
  llm_models?: string[];
  voice_models?: string[];
  /** Single optional global hint passed to TTS (character-level). */
  tts_instructions?: string | null;
  /** Maps catalog provider id → one bundled voice preset id (catalog.yaml ``tts_voices``). */
  tts_voice_by_provider?: Record<string, string> | null;
  emotions_enabled?: boolean;
  extras?: Record<string, unknown> | null;
};

export type CharacterSaveBody = {
  character_id?: string | null;
  name: string;
  description: string;
  prompt: string | null;
  backstory: string;
  llm_models_json: string;
  voice_models_json: string;
  tts_instructions: string;
  /** Always JSON-serialized object (may be ``{}``) so PATCH replaces the saved map. */
  tts_voice_by_provider_json: string;
  emotions_enabled: boolean;
  extras_json: string;
};

export type CharacterSaveResult = {
  character: CharacterDetail;
  warnings: string[];
};

export type CharacterResolvedRow = {
  model_id: string;
  status: 'available' | 'unavailable' | 'unknown' | 'wrong_kind' | 'deprecated';
  display_name?: string | null;
  replacement_id?: string | null;
  note?: string | null;
};

export type CharacterResolvedPayload = {
  character_id: string;
  llm_rows: CharacterResolvedRow[];
  /** Workspace ``default_chat`` (preferences), if set — shown next to the character list. */
  llm_workspace_row: CharacterResolvedRow | null;
  llm_applied: {
    source: 'character' | 'workspace_fallback';
    model_id: string;
    temperature: number;
    max_tokens: number;
  } | null;
  voice_rows: CharacterResolvedRow[];
  /** Workspace ``default_tts`` (preferences), if set — shown next to the character list. */
  voice_workspace_row: CharacterResolvedRow | null;
  voice_applied: {
    source: 'character' | 'workspace_fallback';
    catalog_model_id: string;
    synthesis: { model: string; voice: string; instructions: string };
  } | null;
  voice_disabled: boolean;
};

export async function listCharacters(): Promise<ApiResponse<CharacterRow[]>> {
  return apiRequest<CharacterRow[]>('/characters');
}

export async function getCharacter(id: string): Promise<ApiResponse<CharacterDetail>> {
  return apiRequest<CharacterDetail>(`/characters/${encodeURIComponent(id)}`);
}

export async function getCharacterResolved(
  id: string
): Promise<ApiResponse<CharacterResolvedPayload>> {
  return apiRequest<CharacterResolvedPayload>(`/characters/${encodeURIComponent(id)}/resolved`);
}

export async function createCharacter(body: CharacterSaveBody) {
  return apiRequest<CharacterSaveResult>('/characters', { method: 'POST', body });
}

export async function updateCharacter(id: string, body: CharacterSaveBody) {
  return apiRequest<CharacterSaveResult>(`/characters/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body
  });
}

export async function deleteCharacter(id: string) {
  return apiRequest<boolean>(`/characters/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function uploadCharacterPhoto(id: string, dataUrl: string) {
  return apiRequest<string>(`/characters/${encodeURIComponent(id)}/photo`, {
    method: 'POST',
    body: { data_url: dataUrl }
  });
}
