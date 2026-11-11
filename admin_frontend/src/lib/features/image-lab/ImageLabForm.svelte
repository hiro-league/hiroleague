<script lang="ts">
  import { Sparkles, Star } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import { Input } from '$kit/components/ui/input/index.js';
  import { Textarea } from '$kit/components/ui/textarea/index.js';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import Field from '$kit/ui/field.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import Section from '$kit/ui/section.svelte';
  import { toast } from '$kit/ui/toast.svelte';
  import type { ImageLabController } from './state/image-lab-controller.svelte';

  let { ctl }: { ctl: ImageLabController } = $props();
  const uid = $props.id();

  const isDefaultModel = $derived(ctl.options?.default_model === ctl.model);
</script>

<Panel title="Generate" class="content-start" contentClass="grid gap-4">
  <Field label="Model" for="{uid}-model">
    <PickSelect
      id="{uid}-model"
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
  </Field>
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

  <Field
    label="Recipe"
    for="{uid}-recipe"
    hint="Loads a saved recipe (model, steps, seed, style scaffolding) into this form — generation always runs with exactly what the form shows."
  >
    <PickSelect
      id="{uid}-recipe"
      class="h-8 w-full text-sm"
      label="Recipe"
      value={ctl.profileId}
      options={Object.entries(ctl.profiles).map(([id, profile]) => ({
        value: id,
        label: `${profile.label || id}${profile.locked ? ' (built-in)' : ''}`
      }))}
      onchange={(v) => ctl.applyProfile(v)}
    />
  </Field>

  <Field label="Prompt" for="{uid}-prompt">
    <Textarea id="{uid}-prompt" rows={4} bind:value={ctl.prompt} placeholder="A cozy cabin under northern lights…" />
  </Field>

  <Section class="grid gap-3">
    <Field label="Style prefix" for="{uid}-prefix" hint="Prepended to every prompt — the recipe's look-and-feel.">
      <Input id="{uid}-prefix" type="text" bind:value={ctl.stylePrefix} placeholder="warm photorealistic style, soft lighting" />
    </Field>
    <Field label="Style suffix" for="{uid}-suffix">
      <Input id="{uid}-suffix" type="text" bind:value={ctl.styleSuffix} placeholder="high detail, no text" />
    </Field>
    <div class="grid gap-3 sm:grid-cols-2">
      <Field label="Steps (1–8)" for="{uid}-steps" hint="More steps = better quality, slower.">
        <Input id="{uid}-steps" type="number" min="1" max="8" bind:value={ctl.steps} />
      </Field>
      <Field label="Seed" for="{uid}-seed" hint="Empty = random. Pin for reproducibility.">
        <Input id="{uid}-seed" type="text" inputmode="numeric" bind:value={ctl.seedText} placeholder="random" />
      </Field>
    </div>
  </Section>

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
</Panel>
