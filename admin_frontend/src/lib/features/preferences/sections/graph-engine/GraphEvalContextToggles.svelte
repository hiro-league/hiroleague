<script lang="ts">
  /**
   * Bespoke "Eval recalled-context format" block for the Graph search & indexing card: a labeled
   * fieldset (legend + explainer) wrapping three render toggles. Referenced from the manifest as the
   * `graphEvalContextToggles` custom field — the fieldset/legend framing is card-local copy.
   */
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';

  let { ctrl }: { ctrl: PreferencesController } = $props();
</script>

<fieldset class="grid gap-2 border-0 p-0">
  <legend class="font-sans text-sm font-medium">Eval recalled-context format</legend>
  <p class="text-xs text-muted-foreground">
    Which temporal annotations each recalled <span class="font-medium">fact</span> line carries in
    the answer + judge context — e.g.
    <code>Maya lives in Berlin [LIVES_IN · event_time: 2022-01-01]</code>. Eval-only; applied
    identically to the answer, judge, and evidence-check renders.
  </p>
  <PrefFieldGrid>
    <PrefToggleField
      {ctrl}
      path="graph.eval.show_event_time"
      hint="Adds 'event_time: <valid_at>' to each fact. Also governs the [date] prefix on recalled messages (episodes)."
    />
    <PrefToggleField
      {ctrl}
      path="graph.eval.show_expired_at"
      hint="Adds 'expired_at: <invalid_at>' when a fact has been invalidated — the upper bound of its validity window."
    />
    <PrefToggleField
      {ctrl}
      path="graph.eval.show_superseded"
      hint="Tags facts that a newer fact has replaced. Only visible when the retrieval temporal lens is set to include historical facts."
    />
  </PrefFieldGrid>
</fieldset>
