<script lang="ts">
  import { ImageIcon, Upload } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import CharacterSectionCard from '$lib/features/characters/CharacterSectionCard.svelte';
  import type { CharacterDetail } from '$lib/api/characters';
  import type { CharacterForm } from '$lib/features/characters/utils';

  let {
    form,
    characterId,
    selected,
    markDirty,
    onPickPhoto
  }: {
    form: CharacterForm;
    characterId: string | null | undefined;
    selected: CharacterDetail | null;
    markDirty: () => void;
    onPickPhoto: (event: Event) => void;
  } = $props();

  let photoInput = $state<HTMLInputElement | null>(null);
</script>

<CharacterSectionCard title="Profile">
  {#if !characterId}
    <FormField label="Character id" class="mb-4 max-w-md">
      {#snippet children()}
        <input bind:value={form.new_id} oninput={markDirty} />
      {/snippet}
    </FormField>
  {/if}

  <div class="grid gap-6 lg:grid-cols-[160px_minmax(0,1fr)] lg:items-start">
    <div class="grid justify-items-start gap-3">
      {#if characterId}
        <input class="hidden" type="file" accept="image/*" bind:this={photoInput} onchange={onPickPhoto} />
        <button
          type="button"
          class="overflow-hidden rounded-md border bg-muted/30 p-0 text-left ring-offset-background transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onclick={() => photoInput?.click()}
        >
          {#if selected?.photo_data_url}
            <img class="size-36 object-cover sm:size-40" src={selected.photo_data_url} alt="" />
          {:else}
            <span class="grid size-36 place-items-center text-muted-foreground sm:size-40">
              <ImageIcon size={40} />
            </span>
          {/if}
        </button>
        <Button variant="outline" class="w-full max-w-40" onclick={() => photoInput?.click()}>
          <Upload size={15} /> Photo
        </Button>
      {:else}
        <div
          class="grid size-36 place-items-center rounded-md border border-dashed bg-muted text-muted-foreground sm:size-40"
        >
          <ImageIcon size={40} />
        </div>
        <p class="max-w-[11rem] text-xs text-muted-foreground">
          Save the character first, then you can upload a photo.
        </p>
      {/if}
    </div>

    <div class="grid min-w-0 gap-4">
      <FormField label="Display name" class="w-full md:max-w-[33%] md:min-w-[12rem]">
        {#snippet children()}
          <input bind:value={form.name} oninput={markDirty} />
        {/snippet}
      </FormField>

      <FormField label="Description">
        {#snippet children()}
          <textarea class="min-h-24" bind:value={form.description} oninput={markDirty}></textarea>
        {/snippet}
      </FormField>

      <label class="flex cursor-pointer items-center gap-2 font-sans text-sm font-semibold text-foreground">
        <input
          class="size-4 accent-primary"
          type="checkbox"
          bind:checked={form.emotions_enabled}
          onchange={markDirty}
        />
        Emotions enabled (reserved)
      </label>
    </div>
  </div>
</CharacterSectionCard>
