import { describe, expect, it } from 'vitest';
import { emptyForm } from '$lib/features/characters/shared/characters-pure';
import { createCharactersFormModel } from '$lib/features/characters/state/characters-form.svelte';

describe('createCharactersFormModel', () => {
  it('starts blank and clean', () => {
    const m = createCharactersFormModel();
    expect(m.form).toEqual(emptyForm());
    expect(m.dirty).toBe(false);
  });

  it('markDirty flips the dirty flag', () => {
    const m = createCharactersFormModel();
    m.markDirty();
    expect(m.dirty).toBe(true);
  });

  it('exposes a writable form (bind: target)', () => {
    const m = createCharactersFormModel();
    m.form = { ...emptyForm(), name: 'Ada', ai_profiles: ['hiro-chat'] };
    expect(m.form.name).toBe('Ada');
    expect(m.form.ai_profiles).toEqual(['hiro-chat']);
  });
});
