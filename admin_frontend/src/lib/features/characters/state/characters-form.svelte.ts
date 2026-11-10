import { emptyForm, type CharacterForm } from '$lib/features/characters/shared/characters-pure';

/** Form-only state used by Characters admin (edit UX). Phase 7b step 5: the model pickers' reset nonce
 *  went with the pickers — the profile lists keep no state of their own beyond the form. */
export function createCharactersFormModel() {
  let form = $state<CharacterForm>(emptyForm());
  let dirty = $state(false);

  function markDirty() {
    dirty = true;
  }

  return {
    get form(): CharacterForm {
      return form;
    },
    set form(next: CharacterForm) {
      form = next;
    },
    get dirty(): boolean {
      return dirty;
    },
    set dirty(next: boolean) {
      dirty = next;
    },
    markDirty
  };
}
