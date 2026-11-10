import type { CharacterResolvedPayload } from '$lib/api/characters';

/**
 * Whether ``routing.metadata.request_voice_reply`` can produce TTS for this character,
 * per admin ``GET /characters/:id/resolved`` — same basis as ``CharacterResolvedBlock`` voice section.
 */
export function characterResolvedAllowsVoiceRequest(
  resolved: CharacterResolvedPayload | null
): boolean {
  return resolved !== null && !resolved.voice_disabled && resolved.voice_applied !== null;
}

/** Title / tooltip when the voice-reply control is disabled (aligned with character page copy). */
export function characterResolvedVoiceReplyControlHint(
  resolved: CharacterResolvedPayload | null,
  error: string | null,
  loading: boolean
): string {
  if (loading) return 'Checking the voice for this character…';
  if (error?.trim()) return error;
  if (!resolved) return 'Could not load character voice configuration.';
  if (resolved.voice_disabled) {
    return 'Voice replies are disabled in workspace preferences — nothing is spoken for agent replies.';
  }
  if (!resolved.voice_applied) {
    // Phase 7b step 5: a character's voice profiles, then Hiro's voice (Settings → General).
    return "No voice resolved. Give this character a voice profile (Characters page) or pick Hiro's voice in Settings → General, and set the speech provider's key.";
  }
  return '';
}
