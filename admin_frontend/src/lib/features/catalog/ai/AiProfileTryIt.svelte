<script lang="ts">
  /**
   * Try it, inside the profile editor: one question with the profile as it is in the editor (saved or
   * not), with an optional picture. It asks for real (`POST /api/ai/try`): an API is billed, a plan's
   * limit is used.
   */
  import { ImagePlus, MessageSquare, X } from '@lucide/svelte';
  import Section from '$kit/ui/section.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import FormField from '$lib/components/ui/form-field.svelte';
  import { ADMIN_TEXTAREA } from '$lib/styling/admin-tokens';
  import type { AiController } from './ai-controller.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import { thinkingWords } from './ai-profile-rules';

  let { ai }: { ai: AiController } = $props();

  let fileInput = $state<HTMLInputElement | null>(null);
  const model = $derived(ai.draftModel.model);
</script>

<Section title="Try it" description="Asks one question with this profile as it is now, saved or not.">
  <p class="text-xs text-muted-foreground">
    {ai.draftModel.provider?.label ?? 'No provider'} · {model?.name ?? ai.draft.model} · thinking
    {thinkingWords(ai.draft.thinking).toLowerCase()}
  </p>
  <FormField label="Question">
    <textarea class={ADMIN_TEXTAREA} rows="3" bind:value={ai.tryPrompt}></textarea>
  </FormField>

  <div class="grid gap-2">
    <span class="font-sans text-sm font-semibold text-muted-foreground">Picture (optional)</span>
    <input
      bind:this={fileInput}
      class="hidden"
      type="file"
      accept="image/*"
      onchange={(event) => void ai.setTryPicture(event.currentTarget.files?.[0] ?? null)}
    />
    {#if ai.tryPicture}
      <div class="flex items-center gap-3">
        <img src={ai.tryPicture.url} alt="Sent with the question" class="h-16 w-24 rounded-md border object-cover" />
        <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground">{ai.tryPicture.name}</span>
        <Button
          size="sm"
          variant="ghost"
          onclick={() => {
            void ai.setTryPicture(null);
            if (fileInput) fileInput.value = '';
          }}
        >
          <X size={13} /> Remove
        </Button>
      </div>
      {#if model && !model.pictures}
        <p class="text-xs text-warning">{model.name} can't see pictures: it gets the text only.</p>
      {/if}
    {:else}
      <Button size="sm" variant="outline" class="w-fit" onclick={() => fileInput?.click()}>
        <ImagePlus size={13} /> Add a picture
      </Button>
    {/if}
  </div>

  <Button class="w-fit" disabled={ai.trying || !ai.tryPrompt.trim() || !ai.draft.model} onclick={() => void ai.tryIt()}>
    <MessageSquare size={15} />
    {ai.trying ? 'Asking…' : 'Ask'}
  </Button>

  {#if ai.tryResult}
    {@const r = ai.tryResult}
    <div class="grid gap-1 rounded-md bg-muted px-3 py-2">
      <p class="text-sm">{r.answer}</p>
      <p class="text-xs text-muted-foreground">
        {r.model} · {r.seconds.toFixed(1)} s · {r.tokensIn} tokens in, {r.tokensOut} out · {r.cost}
      </p>
      {#each r.notes as note (note)}
        <p class="text-xs text-warning">{note}</p>
      {/each}
    </div>
  {:else if ai.tryError}
    <Notice message={ai.tryError} />
  {/if}
</Section>
