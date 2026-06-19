<script lang="ts">
  import CharacterSectionCard from '$lib/features/characters/sections/CharacterSectionCard.svelte';
  import { characterSectionHintClass } from '$lib/features/characters/shared/character-section-classes';
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { CharacterForm } from '$lib/features/characters/shared/characters-pure';

  let {
    form,
    markDirty
  }: {
    form: CharacterForm;
    markDirty: () => void;
  } = $props();
</script>

<CharacterSectionCard title="Extras">
  {#snippet hint()}
    <p class={characterSectionHintClass}>Future use - Extra character metadata</p>
  {/snippet}
  <FormField label="extras (JSON object)">
    {#snippet children()}
      <textarea class="min-h-28 font-mono" bind:value={form.extras_json} oninput={markDirty}></textarea>
    {/snippet}
  </FormField>
</CharacterSectionCard>
