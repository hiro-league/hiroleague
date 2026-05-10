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
  if (loading) return 'Checking voice (TTS) configuration for this character…';
  if (error?.trim()) return error;
  if (!resolved) return 'Could not load character voice configuration.';
  if (resolved.voice_disabled) {
    return 'Voice replies are disabled in workspace preferences — TTS is not used for agent replies.';
  }
  if (!resolved.voice_applied) {
    return 'No TTS model resolved. Set default TTS in workspace preferences and configure this character’s voice models (see Characters page).';
  }
  return '';
}
