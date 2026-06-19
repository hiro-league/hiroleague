import { describe, expect, it } from 'vitest';
import type { CatalogProviderRow } from '$lib/api/catalog';
import type { CharacterDetail } from '$lib/api/characters';
import {
  characterSaveBody,
  emptyForm,
  formFromCharacter,
  mergeVoiceProviderDefaults,
  prettyJson,
  validateCharacterForm,
  type CharacterForm
} from '$lib/features/characters/shared/characters-pure';

function provider(id: string, hasVoices: boolean): CatalogProviderRow {
  return {
    id,
    display_name: id,
    hosting: 'cloud',
    tts_voices: hasVoices ? [{ id: `${id}-voice` }] : []
  };
}

function form(over: Partial<CharacterForm> = {}): CharacterForm {
  return { ...emptyForm(), ...over };
}

describe('emptyForm', () => {
  it('returns a blank, fully-defaulted form', () => {
    const f = emptyForm();
    expect(f.llm_models).toEqual([]);
    expect(f.tts_voice_by_provider).toEqual({});
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

describe('mergeVoiceProviderDefaults', () => {
  it('seeds an empty entry for providers that have voices', () => {
    const merged = mergeVoiceProviderDefaults({}, [provider('google', true), provider('x', false)]);
    expect(merged).toEqual({ google: '' });
  });

  it('keeps an already-saved selection and does not overwrite it', () => {
    const merged = mergeVoiceProviderDefaults({ google: 'aoede' }, [provider('google', true)]);
    expect(merged.google).toBe('aoede');
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
      llm_models: ['m1'],
      tuning_profile: 'balanced_chat',
      voice_models: ['v1'],
      tts_instructions: 'speak softly',
      tts_voice_by_provider: { google: 'aoede' },
      emotions_enabled: true,
      extras: { theme: 'dark' }
    };
    const f = formFromCharacter(detail);
    expect(f.new_id).toBe('ada');
    expect(f.llm_models).toEqual(['m1']);
    expect(f.tts_voice_by_provider).toEqual({ google: 'aoede' });
    expect(f.extras_json).toBe('{\n  "theme": "dark"\n}');
    expect(f.emotions_enabled).toBe(true);
  });

  it('coerces missing/invalid fields to safe defaults', () => {
    const detail = {
      id: 'x',
      name: 'X',
      // tts_voice_by_provider intentionally an array → must be dropped to {}
      tts_voice_by_provider: ['nope'] as unknown as Record<string, string>
    } as CharacterDetail;
    const f = formFromCharacter(detail);
    expect(f.llm_models).toEqual([]);
    expect(f.tuning_profile).toBe('');
    expect(f.tts_voice_by_provider).toEqual({});
    expect(f.extras_json).toBe('');
  });

  it('keeps only string-valued voice-by-provider entries', () => {
    const detail = {
      id: 'x',
      name: 'X',
      tts_voice_by_provider: { google: 'aoede', bad: 3 } as unknown as Record<string, string>
    } as CharacterDetail;
    expect(formFromCharacter(detail).tts_voice_by_provider).toEqual({ google: 'aoede' });
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
  it('always serializes model arrays so a cleared bucket sends []', () => {
    const body = characterSaveBody('ada', form({ llm_models: [], voice_models: ['v1'] }));
    expect(body.llm_models_json).toBe('[]');
    expect(body.voice_models_json).toBe('["v1"]');
  });

  it('drops empty voice-preset selections before serializing', () => {
    const body = characterSaveBody(
      'ada',
      form({ tts_voice_by_provider: { google: 'aoede', openai: '', x: '  ' } })
    );
    expect(JSON.parse(body.tts_voice_by_provider_json)).toEqual({ google: 'aoede' });
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
