<script lang="ts">
  import { Sparkles, Star } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCard from '$lib/components/page/SectionCard.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import { ADMIN_SECTION_TITLE } from '$lib/styling/admin-tokens';
  import { toast } from '$kit/ui/toast.svelte';
  import type { ImageLabController } from './state/image-lab-controller.svelte';

  let { ctl }: { ctl: ImageLabController } = $props();

  const isDefaultModel = $derived(ctl.options?.default_model === ctl.model);
</script>

<SectionCard class="grid content-start gap-4">
  <h2 class={ADMIN_SECTION_TITLE}>Generate</h2>

  <FormField label="Model">
    {#snippet children()}
      <PickSelect
        class="h-9 w-full text-sm"
        label="Model"
        value={ctl.model}
        options={ctl.models.map((modelRow) => ({
          value: modelRow.id,
          label: `${modelRow.display_name} — ${modelRow.provider_display_name}${modelRow.available ? '' : ' (provider not configured)'}`,
          disabled: !modelRow.available
        }))}
        onchange={(v) => (ctl.model = v)}
      />
    {/snippet}
  </FormField>
  {#if !ctl.modelReady && ctl.selectedModel}
    <p class="font-sans text-xs text-warning">
      {ctl.selectedModel.provider_display_name} is not ready — add its API key
      {ctl.selectedModel.provider_id === 'cloudflare' ? ' and account id ' : ' '}
      on the <a class="underline" href="/catalog">Providers/Models</a> page.
    </p>
  {:else if ctl.model && !isDefaultModel}
    <Button size="sm" variant="outline" class="justify-self-start" onclick={() => void ctl.setDefaultModel(toast.show)}>
      <Star size={13} /> Set as workspace default
    </Button>
  {/if}

  <FormField
    label="Recipe"
    hint="Loads a saved recipe (model, steps, seed, style scaffolding) into this form — generation always runs with exactly what the form shows."
  >
    {#snippet children()}
      <PickSelect
        class="h-8 w-full text-sm"
        label="Recipe"
        value={ctl.profileId}
        options={Object.entries(ctl.profiles).map(([id, profile]) => ({
          value: id,
          label: `${profile.label || id}${profile.locked ? ' (built-in)' : ''}`
        }))}
        onchange={(v) => ctl.applyProfile(v)}
      />
    {/snippet}
  </FormField>

  <FormField label="Prompt">
    {#snippet children()}
      <textarea rows="4" bind:value={ctl.prompt} placeholder="A cozy cabin under northern lights…"></textarea>
    {/snippet}
  </FormField>

  <SectionCardMuted class="grid gap-3">
    <FormField label="Style prefix" hint="Prepended to every prompt — the recipe's look-and-feel.">
      {#snippet children()}
        <input type="text" bind:value={ctl.stylePrefix} placeholder="warm photorealistic style, soft lighting" />
      {/snippet}
    </FormField>
    <FormField label="Style suffix">
      {#snippet children()}
        <input type="text" bind:value={ctl.styleSuffix} placeholder="high detail, no text" />
      {/snippet}
    </FormField>
    <div class="grid gap-3 sm:grid-cols-2">
      <FormField label="Steps (1–8)" hint="More steps = better quality, slower.">
        {#snippet children()}
          <input type="number" min="1" max="8" bind:value={ctl.steps} />
        {/snippet}
      </FormField>
      <FormField label="Seed" hint="Empty = random. Pin for reproducibility.">
        {#snippet children()}
          <input type="text" inputmode="numeric" bind:value={ctl.seedText} placeholder="random" />
        {/snippet}
      </FormField>
    </div>
  </SectionCardMuted>

  {#if ctl.composedPrompt}
    <p class="font-sans text-xs text-muted-foreground">
      <span class="font-semibold">Final prompt:</span>
      {ctl.composedPrompt}
    </p>
  {/if}

  <div class="flex flex-wrap items-center gap-3">
    <Button
      disabled={ctl.generating || !ctl.composedPrompt || !ctl.modelReady}
      onclick={() => void ctl.generate(toast.show)}
    >
      <Sparkles size={15} />
      {ctl.generating ? 'Generating…' : 'Generate'}
    </Button>
    {#if ctl.estimatedCostUsd !== null}
      <span class="font-sans text-xs text-muted-foreground">
        ~${ctl.estimatedCostUsd.toFixed(5)} per image
      </span>
    {/if}
  </div>
</SectionCard>
