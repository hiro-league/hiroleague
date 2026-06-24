import { PREF_KEYS, type ChatOverlayMode } from '$lib/preferences/keys';
import { boolCodec, enumCodec } from '$lib/state/codecs';
import { createPersistentState } from '$lib/state/create-persistent-state.svelte';

/**
 * Global chat overlay open/mode state (Facebook-style pop-anywhere chat window).
 *
 * Module-level singleton: the header toggle, the overlay shell, and any future
 * launcher all read/write this one store.
 */
const OVERLAY_MODES = ['full', 'partial'] as const;

const openState = createPersistentState({
  key: PREF_KEYS.chatOverlayOpen,
  tier: 'local',
  codec: boolCodec(false, 'bool01')
});

const modeState = createPersistentState({
  key: PREF_KEYS.chatOverlayMode,
  tier: 'local',
  codec: enumCodec(OVERLAY_MODES, 'partial')
});

export const chatOverlay = {
  get open() {
    return openState.value;
  },
  get mode() {
    return modeState.value;
  },
  /** Header toggle: open if closed, close if open. */
  toggle() {
    openState.value = !openState.value;
  },
  close() {
    openState.value = false;
  },
  /** Switch window size (full ↔ partial); also ensures the overlay is shown. */
  setMode(next: ChatOverlayMode) {
    modeState.value = next;
    openState.value = true;
  }
};
