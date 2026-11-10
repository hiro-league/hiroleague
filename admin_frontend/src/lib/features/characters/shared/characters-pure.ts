import type {
  CharacterDetail,
  CharacterSaveBody
} from '$lib/api/characters';

// Phase 7b step 5: a character's models + tuning profile became an ordered list of AI profiles, and its
// voice models + per-provider voice + style hint an ordered list of voice profiles (Catalog → Profiles).
export type CharacterForm = {
  new_id: string;
  name: string;
  description: string;
  prompt: string;
  backstory: string;
  /** `ai.profiles` ids in order (the first that can answer asks); [] = Hiro's chat profile. */
  ai_profiles: string[];
  /** `voice.profiles` ids in order (the first whose provider has a key speaks); [] = Hiro's voice. */
  voice_profiles: string[];
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
    ai_profiles: [],
    voice_profiles: [],
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

/** Only non-empty string ids, in order, without repeats (the server de-duplicates the same way). */
function idList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return [...new Set(raw.filter((x): x is string => typeof x === 'string' && x.trim() !== ''))];
}

export function formFromCharacter(character: CharacterDetail): CharacterForm {
  return {
    new_id: character.id,
    name: character.name ?? '',
    description: character.description ?? '',
    prompt: character.prompt ?? '',
    backstory: character.backstory ?? '',
    ai_profiles: idList(character.ai_profiles),
    voice_profiles: idList(character.voice_profiles),
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
  return {
    character_id: form.new_id.trim() || null,
    name: form.name.trim(),
    description: form.description,
    prompt: persistedCharacterId || form.prompt.trim() ? form.prompt : null,
    backstory: form.backstory,
    // Always send JSON arrays: '' means "leave unchanged" on update, so clearing a list must send [].
    ai_profiles_json: JSON.stringify(form.ai_profiles),
    voice_profiles_json: JSON.stringify(form.voice_profiles),
    emotions_enabled: form.emotions_enabled,
    extras_json: form.extras_json
  };
}

/** Move the item at `index` one place up (-1) or down (+1); unchanged at the ends. */
export function moveInList<T>(items: readonly T[], index: number, delta: -1 | 1): T[] {
  const target = index + delta;
  if (index < 0 || index >= items.length || target < 0 || target >= items.length) return [...items];
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
