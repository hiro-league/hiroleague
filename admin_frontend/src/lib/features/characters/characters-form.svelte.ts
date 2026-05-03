import { emptyForm, type CharacterForm } from '$lib/features/characters/utils';

/** Form-only state used by Characters admin (edit UX + picker reset nonce). */
export function createCharactersFormModel() {
  let form = $state<CharacterForm>(emptyForm());
  let dirty = $state(false);
  let modelPickerResetNonce = $state(0);

  function markDirty() {
    dirty = true;
  }

  /** Bumps nonce so OrderedModelPicker remounts/clears picker state after form reset (load/new). */
  function resetOrderedModelPickersNonce() {
    modelPickerResetNonce++;
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
    get modelPickerResetNonce(): number {
      return modelPickerResetNonce;
    },
    markDirty,
    resetOrderedModelPickersNonce
  };
}
