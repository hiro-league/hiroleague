<script lang="ts">
  /**
   * The "model picker + tuning-profile select, stacked in one grid column" pair that repeats across
   * the Eval, Graph extraction, and retrieval-agent cards. One component instead of the hand-wired
   * `<div class="grid gap-3"><PrefModelPicker …/><TuningProfileSelect …/></div>` block at every site.
   *
   * An optional `heading` renders a bold title above the picker (used where the model has a named
   * sub-section, e.g. "Knowledge Answering Model") instead of the picker's own inline label.
   */
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';
  import type {
    PrefModelIdPath,
    PrefModelKind
  } from '$lib/features/preferences/shared/preferences-model-picker';
  import { type PreferencePath } from '$lib/features/preferences/shared/preferences-schema';

  type Props = {
    ctrl: PreferencesController;
    kind: PrefModelKind;
    modelPath: PrefModelIdPath;
    profilePath: PreferencePath;
    /** When set, `TuningProfileSelect` writes via `ctrl.setDefaultTuningProfile(scope, …)`. */
    scope?: 'llm' | 'memory' | 'knowledge';
    /** Optional bold heading above the picker (replaces the picker's inline label). */
    heading?: string;
    /** Inherited default model id shown in the empty box for override pickers. */
    emptyFallbackId?: string | null;
    busy?: boolean;
  };

  let { ctrl, kind, modelPath, profilePath, scope, heading, emptyFallbackId, busy }: Props = $props();
</script>

<div class="grid gap-3">
  {#if heading}
    <h4 class="font-sans text-base font-semibold leading-snug text-foreground">{heading}</h4>
  {/if}
  <PrefModelPicker
    {ctrl}
    {kind}
    path={modelPath}
    embedded
    labelled={!heading}
    {emptyFallbackId}
    {busy}
  />
  <TuningProfileSelect {ctrl} path={profilePath} {scope} />
</div>
