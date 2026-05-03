import type { CatalogProviderRow } from '$lib/api/catalog';
import type {
  CharacterDetail,
  CharacterSaveBody
} from '$lib/api/characters';

export type CharacterForm = {
  new_id: string;
  name: string;
  description: string;
  prompt: string;
  backstory: string;
  llm_models: string[];
  voice_models: string[];
  tts_instructions: string;
  tts_voice_by_provider: Record<string, string>;
  extras_json: string;
  emotions_enabled: boolean;
};

export function emptyForm(): CharacterForm {
  return {
    new_id: '',
    name: '',
    description: '',
    prompt: '',
    backstory: '',
    llm_models: [],
    voice_models: [],
    tts_instructions: '',
    tts_voice_by_provider: {},
    extras_json: '',
    emotions_enabled: false
  };
}

export function prettyJson(value: unknown): string {
  if (value === null || value === undefined) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function mergeVoiceProviderDefaults(
  saved: Record<string, string>,
  providers: CatalogProviderRow[]
): Record<string, string> {
  const out = { ...saved };
  for (const p of providers) {
    if ((p.tts_voices?.length ?? 0) > 0 && out[p.id] === undefined) out[p.id] = '';
  }
  return out;
}

export function formFromCharacter(character: CharacterDetail): CharacterForm {
  const rawVoices = character.tts_voice_by_provider;
  const voiceMap =
    rawVoices &&
    typeof rawVoices === 'object' &&
    !Array.isArray(rawVoices) &&
    rawVoices !== null
      ? Object.fromEntries(
          Object.entries(rawVoices).filter(
            ([k, v]) => typeof k === 'string' && typeof v === 'string'
          )
        )
      : {};
  return {
    new_id: character.id,
    name: character.name ?? '',
    description: character.description ?? '',
    prompt: character.prompt ?? '',
    backstory: character.backstory ?? '',
    llm_models: Array.isArray(character.llm_models) ? character.llm_models : [],
    voice_models: Array.isArray(character.voice_models) ? character.voice_models : [],
    tts_instructions:
      typeof character.tts_instructions === 'string' ? character.tts_instructions : '',
    tts_voice_by_provider: voiceMap,
    extras_json: prettyJson(character.extras),
    emotions_enabled: Boolean(character.emotions_enabled)
  };
}

/** Validation message or null when the form can be submitted. */
export function validateCharacterForm(
  persistedCharacterId: string | null | undefined,
  form: CharacterForm
): string | null {
  if (!persistedCharacterId && !form.new_id.trim()) return 'Character id is required.';
  if (form.extras_json.trim()) {
    try {
      const parsed = JSON.parse(form.extras_json);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
        return 'Extras must be a JSON object.';
      }
    } catch (err) {
      return err instanceof Error ? `Extras: invalid JSON (${err.message})` : 'Extras: invalid JSON.';
    }
  }
  return null;
}

export function characterSaveBody(
  persistedCharacterId: string | null | undefined,
  form: CharacterForm
): CharacterSaveBody {
  const voicePresets = Object.fromEntries(
    Object.entries(form.tts_voice_by_provider).filter(([, v]) => String(v).trim())
  );
  return {
    character_id: form.new_id.trim() || null,
    name: form.name.trim(),
    description: form.description,
    prompt: persistedCharacterId || form.prompt.trim() ? form.prompt : null,
    backstory: form.backstory,
    // Always send JSON arrays: '' is treated server-side as "omit field", so clearing the bucket must send [].
    llm_models_json: JSON.stringify(form.llm_models),
    voice_models_json: JSON.stringify(form.voice_models),
    tts_instructions: form.tts_instructions,
    tts_voice_by_provider_json: JSON.stringify(voicePresets),
    emotions_enabled: form.emotions_enabled,
    extras_json: form.extras_json
  };
}
