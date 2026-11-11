<script lang="ts">
  import CharacterSectionCard from '$lib/features/characters/sections/CharacterSectionCard.svelte';
  import { characterSectionHintClass } from '$lib/features/characters/shared/character-section-classes';
  import Field from '$kit/ui/field.svelte';
  import { Textarea } from '$kit/components/ui/textarea/index.js';
  import type { CharacterForm } from '$lib/features/characters/shared/characters-pure';

  let {
    form,
    markDirty
  }: {
    form: CharacterForm;
    markDirty: () => void;
  } = $props();
  const uid = $props.id();
</script>

<CharacterSectionCard title="Extras">
  {#snippet hint()}
    <p class={characterSectionHintClass}>Future use - Extra character metadata</p>
  {/snippet}
  <Field label="extras (JSON object)" for="{uid}-extras">
    <Textarea id="{uid}-extras" class="min-h-28 font-mono" bind:value={form.extras_json} oninput={markDirty} />
  </Field>
</CharacterSectionCard>
