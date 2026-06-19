/**
 * Eval leg constants — the comparison legs a knowledge run can select, in canonical column order,
 * plus their human labels. Kept in a leaf module (no Svelte runes, no model import) so both the
 * setup sub-controller and presentational helpers can use them without a circular dependency on
 * the eval-model facade (which re-exports them for external consumers).
 */
import type { EvalLeg } from '$lib/features/eval/shared/eval-events';

/** All selectable legs, in canonical column order. */
export const EVAL_ALL_LEGS: EvalLeg[] = ['flat', 'graphiti'];

/** Human label for a leg (column header / chip). */
export const EVAL_LEG_LABEL: Record<string, string> = {
  flat: 'Flat',
  graphiti: 'Graphiti'
};
