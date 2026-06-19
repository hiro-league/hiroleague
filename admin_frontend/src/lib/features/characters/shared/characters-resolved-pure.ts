import type { CharacterResolvedPayload, CharacterResolvedRow } from '$lib/api/characters';

/** One-line summary for collapsed LLM header (effective catalog model id + optional display name). */
export function llmCollapsedSummary(payload: CharacterResolvedPayload): string {
  if (!payload.llm_applied) return 'No model resolved';
  const applied = payload.llm_applied;
  const row =
    payload.llm_rows.find((r) => r.model_id === applied.model_id) ??
    (payload.llm_workspace_row?.model_id === applied.model_id ? payload.llm_workspace_row : undefined);
  const name = row?.display_name?.trim();
  return name ? `${applied.model_id} · ${name}` : applied.model_id;
}

/** One-line summary for collapsed TTS header (catalog model + optional display + bundled voice id). */
export function voiceCollapsedSummary(payload: CharacterResolvedPayload): string {
  if (payload.voice_disabled) return 'Voice replies disabled';
  if (!payload.voice_applied) return 'No TTS model resolved';
  const applied = payload.voice_applied;
  const vid = applied.catalog_model_id;
  const row =
    payload.voice_rows.find((r) => r.model_id === vid) ??
    (payload.voice_workspace_row?.model_id === vid ? payload.voice_workspace_row : undefined);
  const display = row?.display_name?.trim();
  const voice = applied.synthesis.voice?.trim();
  const base = display ? `${vid} · ${display}` : vid;
  return voice ? `${base} · ${voice}` : base;
}

export function resolvedRowTooltip(status: CharacterResolvedRow['status']): string {
  switch (status) {
    case 'available':
      return 'Online — model is usable with this workspace.';
    case 'unavailable':
      return 'Offline — model is not usable with current workspace configuration.';
    case 'unknown':
      return 'Unknown — resolution could not determine usability.';
    case 'wrong_kind':
      return 'Offline — model kind does not match this slot.';
    case 'deprecated':
      return 'Deprecated — still listed but slated for removal.';
    default:
      return '';
  }
}

export function resolvedRowDotClass(status: CharacterResolvedRow['status']): string {
  switch (status) {
    case 'available':
      return 'bg-emerald-500';
    case 'unavailable':
    case 'wrong_kind':
      return 'bg-red-500';
    case 'deprecated':
      return 'bg-amber-500';
    default:
      return 'bg-muted-foreground/50';
  }
}
