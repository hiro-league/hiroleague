/**
 * Pure helpers for the character resolution view (Phase 7b step 5: from the character's AI / voice
 * profiles, then Hiro's chat profile / Hiro's voice — `GET /characters/:id/resolved`).
 */
import type {
  CharacterResolvedAiRow,
  CharacterResolvedPayload,
  CharacterResolvedVoiceRow
} from '$lib/api/characters';

export type ResolvedRowStatus = CharacterResolvedAiRow['status'] | CharacterResolvedVoiceRow['status'];

/** One-line summary for the collapsed chat header: the profile that answers and its model. */
export function llmCollapsedSummary(payload: CharacterResolvedPayload): string {
  const applied = payload.ai_applied;
  if (!applied) return 'No model resolved';
  const label = applied.profile_label?.trim();
  return label ? `${label} · ${applied.model_id}` : applied.model_id;
}

/** One-line summary for the collapsed voice header: the voice profile, its model and voice. */
export function voiceCollapsedSummary(payload: CharacterResolvedPayload): string {
  if (payload.voice_disabled) return 'Voice replies disabled';
  const applied = payload.voice_applied;
  if (!applied) return 'No voice resolved';
  return [applied.label, applied.model, applied.voice].filter((part) => part?.trim()).join(' · ');
}

/** The tuning the chat applies, compact ("temp 0.3 · max tokens 2,048 · thinking low"). */
export function appliedTuningLine(applied: NonNullable<CharacterResolvedPayload['ai_applied']>): string {
  const parts = [`temp ${applied.temperature}`, `max tokens ${applied.max_tokens.toLocaleString('en-US')}`];
  parts.push(applied.thinking ? `thinking ${applied.thinking}` : 'thinking: model default');
  if (applied.num_ctx) parts.push(`context ${applied.num_ctx.toLocaleString('en-US')}`);
  return parts.join(' · ');
}

export function resolvedRowTooltip(status: ResolvedRowStatus): string {
  switch (status) {
    case 'available':
      return 'Ready — its model can answer with this workspace’s keys.';
    case 'unavailable':
      return 'Not ready — its model has no key or server set up in this workspace.';
    case 'plan':
      return 'Skipped — a plan tool’s model (Claude Code, Codex) can’t be the chat model.';
    case 'no_key':
      return 'Skipped — its speech provider has no key set.';
    case 'missing':
      return 'Missing — no profile with this id any more; it is skipped.';
    default:
      return '';
  }
}

export function resolvedRowDotClass(status: ResolvedRowStatus): string {
  switch (status) {
    case 'available':
      return 'bg-emerald-500';
    case 'unavailable':
    case 'no_key':
    case 'missing':
      return 'bg-red-500';
    case 'plan':
      return 'bg-amber-500';
    default:
      return 'bg-muted-foreground/50';
  }
}
