import type { ImageLabModelRow } from '$lib/api/image-lab';

/** Locked playground profile used for transparent what-you-see-is-what-runs generation. */
export const IMAGE_LAB_PLAYGROUND_PROFILE_ID = 'image_playground';

const PROFILE_ID_RE = /^[a-z0-9][a-z0-9_]{1,40}$/;

export function isValidImageProfileId(id: string): boolean {
  return PROFILE_ID_RE.test(id.trim());
}

/** Mirrors backend compose_image_prompt (style_prefix, prompt, style_suffix). */
export function composeImagePrompt(stylePrefix: string, prompt: string, styleSuffix: string): string {
  return [stylePrefix.trim(), prompt.trim(), styleSuffix.trim()].filter(Boolean).join(', ');
}

export function parseImageSeed(seedText: string): number | null {
  const text = seedText.trim();
  if (!text) return null;
  const parsed = Number.parseInt(text, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export function estimateImageCostUsd(
  model: Pick<ImageLabModelRow, 'per_image' | 'per_step'> | null,
  steps: number
): number | null {
  if (!model) return null;
  if (model.per_image === null && model.per_step === null) return null;
  return (model.per_image ?? 0) + steps * (model.per_step ?? 0);
}
