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
  /** Phase 7b step 5: `ai.profiles` ids in order (the first that can answer asks); [] = Hiro's chat
   *  profile. Replaced llm_models + tuning_profile. */
  ai_profiles?: string[];
  /** Phase 7b step 5: `voice.profiles` ids in order (the first whose provider has a key speaks);
   *  [] = Hiro's voice. Replaced voice_models + tts_instructions + tts_voice_by_provider. */
  voice_profiles?: string[];
  emotions_enabled?: boolean;
  extras?: Record<string, unknown> | null;
};

export type CharacterSaveBody = {
  character_id?: string | null;
  name: string;
  description: string;
  prompt: string | null;
  backstory: string;
  /** JSON array of AI profile ids; on update "" leaves the list unchanged, "[]" clears it. */
  ai_profiles_json: string;
  /** JSON array of voice profile ids; on update "" leaves the list unchanged, "[]" clears it. */
  voice_profiles_json: string;
  emotions_enabled: boolean;
  extras_json: string;
};

export type CharacterSaveResult = {
  character: CharacterDetail;
  warnings: string[];
};

/** One of the character's AI profiles as the resolution view shows it (Phase 7b step 5;
 *  `admin/features/characters/service._ai_row`): can it answer now? */
export type CharacterResolvedAiRow = {
  profile_id: string;
  /** null when the profile doesn't exist (status `missing`). */
  label: string | null;
  model: string | null;
  /** `plan`: a plan tool's model (Claude Code, Codex) — chat can't use it. */
  status: 'available' | 'unavailable' | 'plan' | 'missing';
  fallback?: string | null;
};

/** One of the character's voice profiles (`service._voice_row`): does its provider have a key? */
export type CharacterResolvedVoiceRow = {
  profile_id: string;
  label: string | null;
  model: string | null;
  voice: string | null;
  status: 'available' | 'no_key' | 'missing';
};

export type CharacterResolvedPayload = {
  character_id: string;
  ai_rows: CharacterResolvedAiRow[];
  /** Hiro's chat profile (`llm.chat_profile`), if set — used when no profile of the character can answer. */
  ai_workspace_row: CharacterResolvedAiRow | null;
  ai_applied: {
    /** `character`: from one of its profiles (or their fallbacks); else Hiro's chat profile. */
    source: 'character' | 'workspace_fallback';
    profile_id: string | null;
    profile_label: string | null;
    model_id: string;
    temperature: number;
    max_tokens: number;
    thinking?: 'off' | 'minimal' | 'low' | 'medium' | 'high' | null;
    num_ctx?: number | null;
  } | null;
  voice_rows: CharacterResolvedVoiceRow[];
  /** Hiro's voice (`voice.hiro_profile`), if set — used when no voice profile of the character has a key. */
  voice_workspace_row: CharacterResolvedVoiceRow | null;
  voice_applied: {
    /** `character`: one of its voice profiles; `hiro`: Hiro's voice. */
    source: 'character' | 'hiro';
    profile_id: string;
    label: string;
    model: string;
    voice: string;
    style: string;
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
