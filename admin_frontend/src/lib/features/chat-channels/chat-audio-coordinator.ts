import { writable } from 'svelte/store';

/** Global message-audio speed on the chat channels Messages tab. */
export const CHAT_AUDIO_SPEEDS = [0.85, 1, 1.15, 1.5] as const;

export const chatAudioPlaybackRate = writable<number>(1);

let activeAudio: HTMLAudioElement | null = null;

/** Pause any other chat clip; call from `play` on each `<audio>`. */
export function takeoverChatAudioPlayback(el: HTMLAudioElement) {
  if (activeAudio && activeAudio !== el) {
    try {
      activeAudio.pause();
    } catch {
      /* ignore */
    }
  }
  activeAudio = el;
}

export function releaseChatAudioPlayback(el: HTMLAudioElement) {
  if (activeAudio === el) activeAudio = null;
}

export function cycleChatAudioSpeed() {
  chatAudioPlaybackRate.update((r) => {
    const idx = CHAT_AUDIO_SPEEDS.findIndex((s) => Math.abs(s - r) < 0.001);
    const i = idx >= 0 ? idx : 1;
    return CHAT_AUDIO_SPEEDS[(i + 1) % CHAT_AUDIO_SPEEDS.length];
  });
}

export function formatChatAudioSpeedLabel(rate: number): string {
  const exact = CHAT_AUDIO_SPEEDS.find((s) => Math.abs(s - rate) < 0.001);
  if (exact !== undefined) {
    return exact === 1 ? '1×' : `${exact}×`;
  }
  return `${rate}×`;
}
