<script lang="ts">
  /**
   * A labeled group of related preference fields inside a section card, with ONE group-level reset.
   *
   * Member `Pref*Field`s register their dotted path via the panel registry (they also hide their own
   * per-field reset dot while inside a panel — the panel owns the reset). The group reset dot shows
   * whenever ANY member differs from its default and, on click, resets every member at once.
   *
   * Defaults come from the generated effective-defaults tree (`model_dump()` of the model), NOT the
   * per-leaf schema `default`: a field seeded by a parent `default_factory` (e.g. `media.input.voice
   * = true`) has a misleading leaf default, and resetting a coherent group together also avoids the
   * transient cross-field-invalid states a single-field reset can produce.
   */
  import { onMount, type Snippet } from 'svelte';
  import { cn } from '$lib/utils';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import ResetDot from '$lib/components/ui/reset-dot.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { DEFAULT_WORKSPACE_PREFERENCES } from '$lib/api/generated/workspace-preferences.defaults';
  import {
    getPreferenceByPath,
    setPreferenceByPath
  } from '$lib/features/preferences/state/preferences-edits';
  import {
    createPrefPanelRegistry,
    providePrefPanelRegistry
  } from '$lib/features/preferences/shared/preferences-panel.svelte';
  import {
    createPrefFieldRegistry,
    providePrefFieldRegistry,
    usePrefFieldRegistry
  } from '$lib/features/preferences/shared/preferences-advanced.svelte';

  type Props = {
    ctrl: PreferencesController;
    title: string;
    /** Optional help text shown as a tooltip next to the panel title (like field/section hints). */
    hint?: string;
    class?: string;
    children: Snippet;
  };

  let { ctrl, title, hint, class: className = '', children }: Props = $props();

  const registry = createPrefPanelRegistry();
  providePrefPanelRegistry(registry);

  // Auto-hide like a section card: when every field in the panel is advanced and "show advanced" is
  // off, the panel renders nothing (no empty titled box). Panel fields register their visibility with
  // THIS field registry; an aggregate probe reports the panel's visibility up to the enclosing card
  // so the card's own auto-hide still counts the panel. Capture the parent BEFORE providing our own.
  const parentFieldRegistry = usePrefFieldRegistry();
  const fieldRegistry = createPrefFieldRegistry();
  providePrefFieldRegistry(fieldRegistry);
  const hidden = $derived(fieldRegistry.hasFields && !fieldRegistry.anyVisible);
  onMount(() =>
    parentFieldRegistry?.register(() => (fieldRegistry.hasFields ? fieldRegistry.anyVisible : true))
  );

  // Dirty when any member's draft value differs from its effective default. Reading the nested draft
  // values inside the derived tracks them, so this recomputes on any member edit (and on register).
  const dirty = $derived.by(() => {
    if (!ctrl.draft) return false;
    return registry.paths.some(
      (p) => getPreferenceByPath(ctrl.draft, p) !== getPreferenceByPath(DEFAULT_WORKSPACE_PREFERENCES, p)
    );
  });

  function resetPanel() {
    if (!ctrl.draft) return;
    for (const p of registry.paths) {
      setPreferenceByPath(ctrl.draft, p, getPreferenceByPath(DEFAULT_WORKSPACE_PREFERENCES, p));
    }
    ctrl.markDirty();
  }
</script>

<!--
  Real <fieldset>/<legend> so the title cross-cuts the border: the browser natively notches the
  top border for the legend, which works over the translucent panel fill without any background
  masking. It's also the semantically-correct grouping for a set of related form controls.
-->
<fieldset
  class={cn('min-w-0 rounded-md border border-border/50 bg-card/30 px-3 pb-3 pt-1', hidden && 'hidden', className)}
>
  <legend class="ml-1 flex items-center gap-1.5 px-1.5 font-sans text-sm font-semibold text-foreground">
    {title}
    {#if hint?.trim()}
      <FieldHelp text={hint} />
    {/if}
    {#if dirty}
      <ResetDot onReset={resetPanel} label={`Reset ${title} to defaults`} />
    {/if}
  </legend>
  <div class="grid gap-2">
    {@render children()}
  </div>
</fieldset>
