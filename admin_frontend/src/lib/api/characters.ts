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
  emotions_enabled: boolean;
  extras_json: string;
};

export type CharacterSaveResult = {
  character: CharacterDetail;
  warnings: string[];
};

export async function listCharacters(): Promise<ApiResponse<CharacterRow[]>> {
  return apiRequest<CharacterRow[]>('/characters');
}

export async function getCharacter(id: string): Promise<ApiResponse<CharacterDetail>> {
  return apiRequest<CharacterDetail>(`/characters/${encodeURIComponent(id)}`);
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
