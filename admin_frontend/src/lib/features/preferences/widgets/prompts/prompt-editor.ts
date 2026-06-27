import type { AnswerPromptProfile } from '$lib/api/preferences';

/**
 * Shape the unified prompt-editor dialog edits. A `single` model edits one markdown string; a
 * `library` model edits a whole `dict[id → profile]` (answer / retrieval-agent prompt libraries),
 * which round-trips to the backend as one writeWhole path.
 */
export type PromptDialogModel =
  | { kind: 'single'; initialValue: string; defaultText: string }
  | {
      kind: 'library';
      initialDict: Record<string, AnswerPromptProfile>;
      /** Id of the locked built-in profile (its prompt is the "Restore default" source). */
      defaultId: string;
      /** Version selected on the page when the dialog opened. */
      initialSelectedId: string;
    };

/** What the dialog hands back to the parent on Save (parent maps it to a PATCH payload). */
export type PromptSavePayload =
  | { kind: 'single'; value: string }
  | { kind: 'library'; dict: Record<string, AnswerPromptProfile> };

export function slugifyPromptLabel(label: string): string {
  const base = label
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return base || 'profile';
}

/** First unused id derived from `base` against the existing keys (base, base_2, base_3, …). */
export function uniquePromptId(base: string, existing: Record<string, unknown>): string {
  let id = base;
  let n = 2;
  while (id in existing) {
    id = `${base}_${n}`;
    n += 1;
  }
  return id;
}
