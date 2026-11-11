<script lang="ts">
  /**
   * AI profile editor (dialog): Model, Answer, Budget and Fallback groups on the left, Try it on the
   * right. Inputs bind to `ai.draft`; Save writes `ai.profiles.<id>` through the preferences API.
   */
  import Section from '$kit/ui/section.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import { Input } from '$kit/components/ui/input/index.js';
  import { Textarea } from '$kit/components/ui/textarea/index.js';
  import Field from '$kit/ui/field.svelte';
  import Notice from '$kit/ui/notice.svelte';
  import PickSelect from '$kit/ui/pick-select.svelte';
  import SliderField from '$kit/ui/slider-field.svelte';
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';
  import AiProfileTryIt from './AiProfileTryIt.svelte';
  import type { AiController } from './ai-controller.svelte';
  import { AT_ONCE_OPTIONS, chainLabel, MAX_FALLBACKS, THINKING_LABELS } from './ai-profile-rules';

  let { ai }: { ai: AiController } = $props();
  const uid = $props.id();

  const d = $derived(ai.draft);
  const provider = $derived(ai.draftModel.provider);
  const model = $derived(ai.draftModel.model);
  const kind = $derived(provider?.kind ?? 'api');
  const levels = $derived(model?.thinking ?? []);
  const temperatureOff = $derived(!!ai.draftTemperatureNote);
  const fallbackOptions = $derived(ai.profiles.filter((p) => p.id !== d.id));
  const KIND_WORDS = {
    api: 'Paid per question, by the tokens it uses.',
    local: "Free, and nothing leaves the home. The server's PC must be on.",
    plan: 'Counts against your plan, shared with your own use of it.'
  } as const;
</script>

<Dialog.Root
  open={ai.editorOpen}
  onOpenChange={(next) => {
    if (!next) ai.closeEditor();
  }}
>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-5xl">
    <Dialog.Header>
      <Dialog.Title>{ai.editorIsNew ? 'New AI profile' : `Edit ${ai.profileName(d.id) || 'profile'}`}</Dialog.Title>
      <Dialog.Description>
        {ai.usedBy(d.id).length ? `Used by ${ai.usedBy(d.id).join(', ')}.` : 'Nothing uses this profile yet.'}
      </Dialog.Description>
    </Dialog.Header>

    <div class="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <div class="grid content-start gap-4">
        <Field label="Name" for="{uid}-name">
          <Input id="{uid}-name" bind:value={ai.draft.name} placeholder="e.g. Camera questions" />
        </Field>

        <Section title="Model">
          <!-- The admin's shared single-model picker (provider list → model list). Local servers'
               and plan tools' models are fed to it as catalog-shaped rows by the AI controller. -->
          <SingleModelPicker
            embedded
            label="Model"
            hint="The model this profile asks."
            selectedId={d.model || null}
            catalogModels={ai.pickerModels}
            catalogLoaded={ai.catalogLoaded}
            catalogAllProviders={ai.pickerProviders}
            workspaceActiveProvidersResolved={ai.pickerActiveResolved}
            workspaceActiveProviderIds={ai.pickerActiveIds}
            busy={false}
            emptyProviders="No chat models in the catalog."
            emptyModelsForProvider="This provider lists no chat models."
            emptyText="No model picked yet."
            clearTitle="Clear the model"
            onSelect={(id) => ai.setDraftModel(id)}
          />
          {#if d.model}
            <p class="text-xs text-muted-foreground">{KIND_WORDS[kind]}</p>
          {/if}
          {#if provider?.notReady}
            <p class="text-xs text-warning">{provider.notReady} Its fallback asks meanwhile.</p>
          {/if}
        </Section>

        <Section title="Answer">
          <!-- items-start: a two-line hint in one cell must not stretch the other cells' controls. -->
          <div class="grid items-start gap-3 sm:grid-cols-3">
            <Field label="Thinking" for="{uid}-thinking">
              <!-- '' = the model's default (stored as null). -->
              <PickSelect
                id="{uid}-thinking"
                class="h-9 w-full text-sm"
                label="Thinking"
                value={d.thinking ?? ''}
                disabled={!levels.length}
                options={[{ value: '', label: 'Model default' }, ...levels.map((level) => ({ value: level, label: THINKING_LABELS[level] }))]}
                onchange={(v) => (ai.draft.thinking = (v || null) as typeof d.thinking)}
              />
            </Field>
            <Field label="Max tokens" for="{uid}-max-tokens" hint="Empty = the model default.">
              <Input id="{uid}-max-tokens" type="number" min="1" step="64" placeholder="Default" bind:value={ai.draft.maxTokens} />
            </Field>
            {#if kind === 'local'}
              <Field label="Context (tokens)" for="{uid}-context" hint="More fits more pictures.">
                <Input id="{uid}-context" type="number" min="2048" step="1024" bind:value={ai.draft.context} />
              </Field>
            {/if}
          </div>
          <SliderField
            label="Temperature"
            hint={ai.draftTemperatureNote ?? 'Lower answers the same way each time; higher varies more.'}
            min={0}
            max={2}
            step={0.1}
            value={d.temperature ?? 1}
            disabled={temperatureOff}
            onchange={(v) => (ai.draft.temperature = v)}
            onreset={() => (ai.draft.temperature = null)}
            modified={!temperatureOff && d.temperature !== null}
            format={() => (temperatureOff ? '—' : (d.temperature?.toFixed(1) ?? 'Default'))}
          />
          <Field label="Extra instructions (optional)" for="{uid}-instructions" hint="Added to every question; leave empty for none.">
            <Textarea id="{uid}-instructions" rows={2} bind:value={ai.draft.instructions} placeholder="e.g. Answer only from what the picture shows." />
          </Field>
        </Section>

        <Section title="Budget">
          <div class="grid items-start gap-3 sm:grid-cols-2">
            {#if kind === 'api'}
              <Field label="Cost per day (USD)" for="{uid}-cost" hint="Past it, the fallback asks. Empty = no limit.">
                <Input id="{uid}-cost" type="number" min="0" step="0.25" bind:value={ai.draft.budget.costPerDay} />
              </Field>
            {:else}
              <Field
                label="Questions per hour"
                for="{uid}-per-hour"
                hint={kind === 'plan'
                  ? "Keeps this profile's share of your plan small. Empty = no limit."
                  : 'Keeps the PC free for you. Empty = no limit.'}
              >
                <Input id="{uid}-per-hour" type="number" min="0" step="1" bind:value={ai.draft.budget.perHour} />
              </Field>
            {/if}
            <Field label="At once" for="{uid}-at-once" hint="Questions it works on together; past it they wait their turn.">
              <PickSelect
                id="{uid}-at-once"
                value={String(ai.draft.budget.atOnce)}
                options={AT_ONCE_OPTIONS.map((n) => ({ value: String(n), label: String(n) }))}
                onchange={(v) => (ai.draft.budget.atOnce = Number(v) as typeof ai.draft.budget.atOnce)}
                label="At once"
                class="h-8 w-full text-sm"
              />
            </Field>
          </div>
        </Section>

        <Section title="Fallback">
          <Field
            label="When it can't answer, ask"
            for="{uid}-fallback"
            hint="Used when a budget is reached, the provider fails, or the ask must stay local."
          >
            <PickSelect
              id="{uid}-fallback"
              value={d.fallbackId ?? ''}
              options={[{ value: '', label: 'Nobody: the ask fails' }, ...fallbackOptions.map((p) => ({ value: p.id, label: p.name }))]}
              onchange={(v) => (ai.draft.fallbackId = v || null)}
              label="Fallback"
              class="h-8 w-full text-sm"
            />
          </Field>
          {#if d.fallbackId}
            <p class="text-sm">
              <span class="font-semibold">{d.name || 'This profile'}</span>
              <span class="text-muted-foreground">{chainLabel(ai.profiles, ai.draftCheck.chain)}</span>
            </p>
          {/if}
          {#if ai.draftCheck.message}
            <Notice message={ai.draftCheck.message} />
          {:else}
            <p class="text-xs text-muted-foreground">At most {MAX_FALLBACKS} fallbacks in a row, and no loops.</p>
          {/if}
        </Section>
      </div>

      <!-- Try it stays in view while the form on the left scrolls. -->
      <div class="grid content-start self-start lg:sticky lg:top-0">
        <AiProfileTryIt {ai} />
      </div>
    </div>

    <Dialog.Footer>
      <Button variant="outline" onclick={() => ai.closeEditor()}>Cancel</Button>
      <Button
        disabled={ai.saving || !d.name.trim() || !d.model || !!ai.draftCheck.message}
        onclick={() => void ai.saveProfile()}
      >
        {ai.saving ? 'Saving…' : 'Save'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
