import { describe, expect, it } from 'vitest';
import type { CharacterDetail } from '$lib/api/characters';
import {
  characterSaveBody,
  emptyForm,
  formFromCharacter,
  moveInList,
  prettyJson,
  validateCharacterForm,
  type CharacterForm
} from '$lib/features/characters/shared/characters-pure';

function form(over: Partial<CharacterForm> = {}): CharacterForm {
  return { ...emptyForm(), ...over };
}

describe('emptyForm', () => {
  it('returns a blank, fully-defaulted form (no profiles: Hiro’s own)', () => {
    const f = emptyForm();
    expect(f.ai_profiles).toEqual([]);
    expect(f.voice_profiles).toEqual([]);
    expect(f.emotions_enabled).toBe(false);
  });
});

describe('prettyJson', () => {
  it('returns an empty string for null/undefined', () => {
    expect(prettyJson(null)).toBe('');
    expect(prettyJson(undefined)).toBe('');
  });

  it('indents objects with two spaces', () => {
    expect(prettyJson({ a: 1 })).toBe('{\n  "a": 1\n}');
  });
});

describe('formFromCharacter', () => {
  it('maps a full character into form fields', () => {
    const detail: CharacterDetail = {
      id: 'ada',
      name: 'Ada',
      description: 'desc',
      prompt: 'p',
      backstory: 'b',
      ai_profiles: ['hiro-chat', 'claude-backup'],
      voice_profiles: ['hiro-voice'],
      emotions_enabled: true,
      extras: { theme: 'dark' }
    };
    const f = formFromCharacter(detail);
    expect(f.new_id).toBe('ada');
    expect(f.ai_profiles).toEqual(['hiro-chat', 'claude-backup']);
    expect(f.voice_profiles).toEqual(['hiro-voice']);
    expect(f.extras_json).toBe('{\n  "theme": "dark"\n}');
    expect(f.emotions_enabled).toBe(true);
  });

  it('coerces missing/invalid lists to safe defaults', () => {
    const detail = {
      id: 'x',
      name: 'X',
      // not an array → must be dropped to []
      ai_profiles: 'nope' as unknown as string[]
    } as CharacterDetail;
    const f = formFromCharacter(detail);
    expect(f.ai_profiles).toEqual([]);
    expect(f.voice_profiles).toEqual([]);
    expect(f.extras_json).toBe('');
  });

  it('keeps only non-empty string ids, in order, without repeats', () => {
    const detail = {
      id: 'x',
      name: 'X',
      ai_profiles: ['a', '', 3, 'b', 'a'] as unknown as string[]
    } as CharacterDetail;
    expect(formFromCharacter(detail).ai_profiles).toEqual(['a', 'b']);
  });
});

describe('validateCharacterForm', () => {
  it('requires an id when creating a new character', () => {
    expect(validateCharacterForm(null, form({ new_id: '  ' }))).toBe('Character id is required.');
  });

  it('allows a blank id when editing an existing character', () => {
    expect(validateCharacterForm('ada', form({ new_id: '' }))).toBeNull();
  });

  it('rejects extras that are not a JSON object', () => {
    expect(validateCharacterForm('ada', form({ extras_json: '[1,2]' }))).toBe(
      'Extras must be a JSON object.'
    );
  });

  it('reports invalid extras JSON', () => {
    const msg = validateCharacterForm('ada', form({ extras_json: '{bad' }));
    expect(msg).toMatch(/^Extras: invalid JSON/);
  });

  it('passes a valid form', () => {
    expect(validateCharacterForm('ada', form({ extras_json: '{"a":1}' }))).toBeNull();
  });
});

describe('characterSaveBody', () => {
  it('always serializes the profile lists so a cleared list sends [] ("" would leave it unchanged)', () => {
    const body = characterSaveBody('ada', form({ ai_profiles: [], voice_profiles: ['hiro-voice'] }));
    expect(body.ai_profiles_json).toBe('[]');
    expect(body.voice_profiles_json).toBe('["hiro-voice"]');
  });

  it('keeps the list order (the first that can answer asks)', () => {
    const body = characterSaveBody('ada', form({ ai_profiles: ['b', 'a'] }));
    expect(JSON.parse(body.ai_profiles_json)).toEqual(['b', 'a']);
  });

  it('sends only the profile-list fields (no model lists, tuning or TTS settings)', () => {
    const body = characterSaveBody('ada', form());
    for (const gone of ['llm_models_json', 'tuning_profile', 'voice_models_json', 'tts_instructions']) {
      expect(body, gone).not.toHaveProperty(gone);
    }
  });

  it('sends a null id when new_id is blank', () => {
    expect(characterSaveBody('ada', form({ new_id: '   ' })).character_id).toBeNull();
  });

  it('omits the prompt (null) for a new character with a blank prompt', () => {
    expect(characterSaveBody(null, form({ new_id: 'new', prompt: '   ' })).prompt).toBeNull();
  });

  it('keeps the prompt for an existing character even when blank', () => {
    expect(characterSaveBody('ada', form({ prompt: '' })).prompt).toBe('');
  });
});

describe('moveInList', () => {
  it('moves an item up or down one place', () => {
    expect(moveInList(['a', 'b', 'c'], 1, -1)).toEqual(['b', 'a', 'c']);
    expect(moveInList(['a', 'b', 'c'], 1, 1)).toEqual(['a', 'c', 'b']);
  });

  it('leaves the list as it is at the ends (and returns a copy)', () => {
    const items = ['a', 'b'];
    expect(moveInList(items, 0, -1)).toEqual(['a', 'b']);
    expect(moveInList(items, 1, 1)).toEqual(['a', 'b']);
    expect(moveInList(items, 0, -1)).not.toBe(items);
  });
});
