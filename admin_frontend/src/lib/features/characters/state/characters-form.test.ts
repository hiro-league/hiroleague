import { describe, expect, it } from 'vitest';
import { emptyForm } from '$lib/features/characters/shared/characters-pure';
import { createCharactersFormModel } from '$lib/features/characters/state/characters-form.svelte';

describe('createCharactersFormModel', () => {
  it('starts blank, clean, and with a zero picker nonce', () => {
    const m = createCharactersFormModel();
    expect(m.form).toEqual(emptyForm());
    expect(m.dirty).toBe(false);
    expect(m.modelPickerResetNonce).toBe(0);
  });

  it('markDirty flips the dirty flag', () => {
    const m = createCharactersFormModel();
    m.markDirty();
    expect(m.dirty).toBe(true);
  });

  it('exposes a writable form (bind: target)', () => {
    const m = createCharactersFormModel();
    m.form = { ...emptyForm(), name: 'Ada' };
    expect(m.form.name).toBe('Ada');
  });

  it('resetOrderedModelPickersNonce bumps the nonce so pickers remount', () => {
    const m = createCharactersFormModel();
    m.resetOrderedModelPickersNonce();
    m.resetOrderedModelPickersNonce();
    expect(m.modelPickerResetNonce).toBe(2);
  });
});
