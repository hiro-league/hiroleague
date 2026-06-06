import { browser } from '$app/environment';
import { PREF_KEYS, type ChatOverlayMode } from '$lib/preferences/keys';

/**
 * Global chat overlay open/mode state (Facebook-style pop-anywhere chat window).
 *
 * Module-level singleton: the header toggle, the overlay shell, and any future
 * launcher all read/write this one store. Window chrome only — the conversation
 * itself lives in the shared chat engine (see chat-engine-singleton).
 */
const MODES: readonly ChatOverlayMode[] = ['full', 'partial'];

function readMode(): ChatOverlayMode {
  if (!browser) return 'partial';
  const raw = localStorage.getItem(PREF_KEYS.chatOverlayMode);
  return MODES.includes(raw as ChatOverlayMode) ? (raw as ChatOverlayMode) : 'partial';
}

function readOpen(): boolean {
  if (!browser) return false;
  return localStorage.getItem(PREF_KEYS.chatOverlayOpen) === '1';
}

let open = $state(readOpen());
let mode = $state<ChatOverlayMode>(readMode());

function persistOpen() {
  try {
    localStorage.setItem(PREF_KEYS.chatOverlayOpen, open ? '1' : '0');
  } catch {
    /* ignore quota / private mode */
  }
}

function persistMode() {
  try {
    localStorage.setItem(PREF_KEYS.chatOverlayMode, mode);
  } catch {
    /* ignore quota / private mode */
  }
}

export const chatOverlay = {
  get open() {
    return open;
  },
  get mode() {
    return mode;
  },
  /** Header toggle: open if closed, close if open. */
  toggle() {
    open = !open;
    persistOpen();
  },
  close() {
    open = false;
    persistOpen();
  },
  /** Switch window size (full ↔ partial); also ensures the overlay is shown. */
  setMode(next: ChatOverlayMode) {
    mode = next;
    open = true;
    persistMode();
    persistOpen();
  }
};
