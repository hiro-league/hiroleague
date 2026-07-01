/**
 * Declarative preference manifest (Tier-2.1).
 *
 * A tab's cards + fields are described as DATA here, and a generic renderer (`PrefManifestCard` →
 * `PrefFieldRenderer`) turns the data into the same widgets a hand-written card would. The SAME
 * manifest is the single source for the tab's field ORDER and section mapping (see
 * `manifestFieldPaths` / `manifestSections`), so the search index can't drift from what renders.
 *
 * Most fields are fully data-driven (number / text / toggle / textarea / select / model / embedder /
 * modelProfile + grid / column / panel / gated layout). To gate a card's WHOLE body, wrap its fields
 * in a single `gated` field spec (banner + disabled fieldset — e.g. the reranker card only applies
 * when `search_recipe === 'cross_encoder'`); no separate card-level gating exists. A card CAN carry
 * `validate` — the one card-level thing field specs can't express: a cross-field error registered via
 * `ctrl.setSectionError` (e.g. `limit_min ≤ limit_default ≤ limit_max`) that gates Save. The remaining
 * bespoke bits (a toggle-array block, computed cross-field select options) are escape hatches:
 *  - `select.options` may be a function of the draft (computed / cross-field-disabled options),
 *  - `gated.disabledWhen` is a draft predicate,
 *  - `custom` (field) references a component by string KEY, resolved by the renderer's registry — so
 *    this data module never imports `.svelte` files.
 *
 * Pure data + pure functions only; no Svelte imports. The component keys are typed unions so a typo
 * is a compile error against the renderer registries.
 */
import type { WorkspacePreferences } from '$lib/api/preferences';
import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
import type { PrefSelectOption } from '$lib/features/preferences/shared/preferences-field-options';
import type {
  PrefModelIdPath,
  PrefModelKind
} from '$lib/features/preferences/shared/preferences-model-picker';
import type { PreferencePath } from '$lib/features/preferences/shared/preferences-schema';

/** Static option map/list, or a function of the draft for computed / cross-field-disabled options. */
export type PrefOptionsSource =
  | PrefSelectOption[]
  | Record<string, string>
  | ((draft: WorkspacePreferences) => PrefSelectOption[]);

/** Bespoke FIELD blocks rendered inside a data-driven card (resolved by the field-renderer registry). */
export type CustomFieldKey = 'graphEvalContextToggles';

export type PrefFieldSpec =
  | { kind: 'number'; path: PreferencePath; disabledWhen?: (d: WorkspacePreferences) => boolean }
  | { kind: 'text'; path: PreferencePath; placeholder?: string; maxlength?: number; hint?: string }
  | { kind: 'toggle'; path: PreferencePath; hint?: string }
  | {
      kind: 'textarea';
      path: PreferencePath;
      rows?: number;
      maxlength?: number;
      placeholder?: string;
    }
  | {
      kind: 'select';
      path: PreferencePath;
      options: PrefOptionsSource;
      /** Extra sentence appended to the field's schema description (a card-local UI pointer). */
      hintSuffix?: string;
    }
  | {
      kind: 'model';
      path: PrefModelIdPath;
      modelKind: PrefModelKind;
      labelled?: boolean;
      /** Path whose draft value seeds the empty-box "inherited default" (e.g. llm.default_reranker). */
      emptyFallback?: PreferencePath;
      /** Render the inline local-model download affordance below the picker. */
      download?: 'embedder' | 'reranker';
    }
  /** Standalone tuning-profile picker (not paired with a model — e.g. the default chat profile). */
  | { kind: 'tuningProfile'; path: PreferencePath; scope?: 'llm' | 'memory' | 'knowledge' }
  /** Embedding model picker with a "locked while indexed" badge + inline download (embedders are
   * dimension-bound). `lockedPath` is the backend-computed `*_locked` flag; the empty box inherits
   * `llm.default_embedder`. Used by the graph + knowledge embedders. */
  | { kind: 'embedder'; path: PrefModelIdPath; lockedPath: PreferencePath; heading: string }
  | {
      kind: 'modelProfile';
      modelPath: PrefModelIdPath;
      profilePath: PreferencePath;
      modelKind: PrefModelKind;
      scope?: 'llm' | 'memory' | 'knowledge';
      heading?: string;
    }
  /** Responsive field grid (the 2-col default; `cols: 3` for dense numeric rows). */
  | { kind: 'grid'; cols?: 2 | 3; fields: PrefFieldSpec[] }
  /** A single stacked column (`grid gap-3`) — one grid cell holding several children. */
  | { kind: 'column'; fields: PrefFieldSpec[] }
  /** Labeled group with one group-level reset (a `PrefPanel`). */
  | { kind: 'panel'; title: string; hint?: string; fields: PrefFieldSpec[] }
  /** Fieldset that dims + disables its children when the predicate is true (optional banner above). */
  | { kind: 'gated'; disabledWhen: (d: WorkspacePreferences) => boolean; banner?: string; fields: PrefFieldSpec[] }
  /** A single editable system prompt (markdown editor), with an optional heading + help icon. */
  | {
      kind: 'prompt';
      path: PreferencePath;
      heading?: string;
      headingHelp?: string;
      hint?: string;
      ariaLabel: string;
      editorLabel: string;
    }
  /** A named prompt library (active-profile select + New/Edit/Duplicate), optional heading + help. */
  | {
      kind: 'promptLibrary';
      dictPath: PreferencePath;
      activeIdPath: PreferencePath;
      heading?: string;
      headingHelp?: string;
      hint: string;
      ariaLabel: string;
      editorLabel: string;
    }
  /** Bespoke block; `paths` are its editable fields (in render order) for search/order derivation. */
  | { kind: 'custom'; component: CustomFieldKey; paths: PreferencePath[] };

export type PrefCardSpec = {
  kind: 'card';
  id: string;
  title: string;
  description?: string;
  /** Computed description (overrides `description`) for cards whose subtitle depends on live state. */
  descriptionOf?: (ctrl: PreferencesController) => string;
  bodyId: string;
  collapsible?: boolean;
  body: PrefFieldSpec[];
  /** Card-level cross-field validation — the one card concern field specs can't express. The error
   * (if any) is registered via `ctrl.setSectionError(id, error)` (gating Save) and rendered under the
   * body; cleared when the card unmounts so it can't leave Save stuck. (To gate the whole body under a
   * condition, wrap the body in a single `gated` field spec instead — no card-level `gated` exists.) */
  validate?: (d: WorkspacePreferences) => string | null;
};

export type PrefTabManifest = {
  cards: PrefCardSpec[];
};

// ---------------------------------------------------------------------------
// Derivations — the manifest is the single source for field order + sections.
// ---------------------------------------------------------------------------

/** Flatten every editable field path a field-spec subtree owns, in render order. */
export function fieldSpecPaths(spec: PrefFieldSpec): string[] {
  switch (spec.kind) {
    case 'number':
    case 'text':
    case 'toggle':
    case 'textarea':
    case 'select':
    case 'model':
    case 'tuningProfile':
    case 'embedder':
      return [spec.path];
    case 'modelProfile':
      return [spec.modelPath, spec.profilePath];
    case 'prompt':
      return [spec.path];
    case 'promptLibrary':
      return [spec.activeIdPath, spec.dictPath];
    case 'grid':
    case 'column':
    case 'panel':
    case 'gated':
      return spec.fields.flatMap(fieldSpecPaths);
    case 'custom':
      return [...spec.paths];
  }
}

/** All editable field paths in a card, in render order. */
export function cardSpecPaths(card: PrefCardSpec): string[] {
  return card.body.flatMap(fieldSpecPaths);
}

/** All editable field paths across the manifest, in render order (drives search arrow-nav order). */
export function manifestFieldPaths(manifest: PrefTabManifest): string[] {
  return manifest.cards.flatMap(cardSpecPaths);
}

/** `{ path → section title }` for every editable path (drives the search "section" label). */
export function manifestSections(manifest: PrefTabManifest): Record<string, string> {
  const out: Record<string, string> = {};
  for (const card of manifest.cards) {
    for (const path of cardSpecPaths(card)) out[path] = card.title;
  }
  return out;
}

/** Card/section titles across the manifest, in render order. */
export function manifestCardSections(manifest: PrefTabManifest): string[] {
  return manifest.cards.map((card) => card.title);
}
